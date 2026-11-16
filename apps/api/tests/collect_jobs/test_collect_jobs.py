"""A-05 수집 작업 API 단위 테스트(가짜 PostgREST). 근거: tasks/task-008.md#구현 결정."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import create_app
from tests.collect_jobs.conftest import (
    JOB,
    OTHER_WS,
    P1,
    P2,
    P3,
    P4,
    P_OTHER,
    WORKER,
    WORKER_REVOKED,
    FakeDB,
    job,
    run,
)
from tests.conftest import make_settings

OTHER_JOB = "00000000-0000-4000-8000-0000000000f2"


def _post(api: TestClient, auth: dict, key: str = "c-1", body: dict | None = None):
    return api.post("/v1/collect-jobs", headers={**auth, "Idempotency-Key": key}, json=body)


# --- POST -----------------------------------------------------------------------


def test_post_creates_queued_job_and_runs(api: TestClient, auth: dict, db: FakeDB):
    resp = _post(api, auth)
    assert resp.status_code == 202, resp.json()
    out = resp.json()["job"]
    assert out["status"] == "queued" and out["stop_requested"] is False
    assert [p["profile_id"] for p in out["profiles"]] == [P1, P2]  # 선택된 프로필, name 순
    assert all(p["status"] == "pending" and p["collected_count"] == 0 for p in out["profiles"])
    created = db.jobs[0]
    assert created["kind"] == "collect" and created["params"] == {"limit": 200}
    assert created["profile_ids"] == [P1, P2]
    assert [(r["profile_id"], r["position"], r["status"]) for r in db.runs] == [
        (P1, 0, "pending"),
        (P2, 1, "pending"),
    ]


def test_post_explicit_profiles_keeps_order(api: TestClient, auth: dict, db: FakeDB):
    resp = _post(api, auth, body={"profile_ids": [P3, P1, P3]})
    assert resp.status_code == 202
    assert db.jobs[0]["profile_ids"] == [P3, P1]


def test_post_same_key_returns_existing_200(api: TestClient, auth: dict, db: FakeDB):
    first = _post(api, auth, key="same")
    again = _post(api, auth, key="same", body={"profile_ids": [P3]})
    assert first.status_code == 202 and again.status_code == 200
    assert again.json() == first.json() and len(db.jobs) == 1


def test_post_same_key_checked_before_active_409(api: TestClient, auth: dict, db: FakeDB):
    db.jobs.append(
        job(
            status="running",
            idempotency_key="dup",
            claimed_by=None,
            started_at=datetime.now(UTC).isoformat(),
        )
    )
    resp = _post(api, auth, key="dup")
    assert resp.status_code == 200 and resp.json()["job"]["id"] == JOB


def test_post_same_key_other_kind_409(api: TestClient, auth: dict, db: FakeDB):
    db.jobs.append(job(kind="verify", status="done", idempotency_key="v-1"))
    resp = _post(api, auth, key="v-1")
    assert resp.status_code == 409 and resp.json()["field"] == "Idempotency-Key"


def test_post_concurrent_same_key_23505_returns_existing(api: TestClient, auth: dict, db: FakeDB):
    # 동시 요청이 먼저 만든 job: 첫 키 조회는 비어 있고 INSERT가 멱등 키 23505로 실패
    db.jobs.append(job(idempotency_key="race", created_at=datetime.now(UTC).isoformat()))
    db.hide_key_lookups = 1
    resp = _post(api, auth, key="race")
    assert resp.status_code == 200 and resp.json()["job"]["id"] == JOB
    assert len(db.jobs) == 1


def test_post_active_job_409(api: TestClient, auth: dict, db: FakeDB):
    db.jobs.append(job(status="retrying"))
    resp = _post(api, auth, key="new")
    assert resp.status_code == 409 and resp.json()["code"] == "CONFLICT"


def test_post_rate_limited_429(api: TestClient, auth: dict, db: FakeDB):
    db.jobs.append(
        job(status="stopped", idempotency_key="old", created_at=datetime.now(UTC).isoformat())
    )
    resp = _post(api, auth, key="new")
    assert resp.status_code == 429 and resp.json()["code"] == "RATE_LIMITED"
    db.jobs[0]["created_at"] = (datetime.now(UTC) - timedelta(seconds=61)).isoformat()
    assert _post(api, auth, key="new").status_code == 202


def test_post_zero_profiles_400(api: TestClient, auth: dict, db: FakeDB):
    for p in db.profiles:
        p["selected"] = False
    resp = _post(api, auth)
    assert resp.status_code == 400 and resp.json()["field"] == "profile_ids"
    assert _post(api, auth, key="c-2", body={"profile_ids": []}).status_code == 400
    assert db.jobs == []


def test_post_four_profiles_400(api: TestClient, auth: dict, db: FakeDB):
    resp = _post(api, auth, body={"profile_ids": [P1, P2, P3, P4]})
    assert resp.status_code == 400 and db.jobs == []


def test_post_other_workspace_profile_400(api: TestClient, auth: dict, db: FakeDB):
    resp = _post(api, auth, body={"profile_ids": [P1, P_OTHER]})
    assert resp.status_code == 400 and db.jobs == []


def test_post_missing_key_400(api: TestClient, auth: dict):
    assert api.post("/v1/collect-jobs", headers=auth).status_code == 400
    assert _post(api, auth, key="has space").status_code == 400


def test_post_runs_failure_still_202(api: TestClient, auth: dict, db: FakeDB):
    db.runs_insert_fails = True
    resp = _post(api, auth)
    assert resp.status_code == 202
    assert [p["status"] for p in resp.json()["job"]["profiles"]] == ["pending", "pending"]


def test_post_unauthenticated_401(api: TestClient):
    assert api.post("/v1/collect-jobs", headers={"Idempotency-Key": "x"}).status_code == 401


# --- GET ------------------------------------------------------------------------


def test_get_job_detail(api: TestClient, auth: dict, db: FakeDB):
    seen = datetime.now(UTC) - timedelta(minutes=1)
    db.jobs.append(job(status="running", claimed_by=WORKER, started_at=seen.isoformat()))
    db.runs += [
        run(JOB, P2, 1, "pending"),
        run(JOB, P1, 0, "running", 3, chrome_state="resize_needed", detail="window_small"),
    ]
    db.heartbeats.append(
        {
            "worker_id": WORKER,
            "workspace_id": db.jobs[0]["workspace_id"],
            "last_seen_at": seen.isoformat(),
        }
    )
    db.candidates += [
        {
            "id": "c1",
            "workspace_id": db.jobs[0]["workspace_id"],
            "first_job_id": JOB,
            "used": False,
            "rep_status": "producible",
        },
        {
            "id": "c2",
            "workspace_id": db.jobs[0]["workspace_id"],
            "first_job_id": JOB,
            "used": False,
            "rep_status": "pending",
        },
        {
            "id": "c3",
            "workspace_id": db.jobs[0]["workspace_id"],
            "first_job_id": JOB,
            "used": True,
            "rep_status": "producible",
        },
        {
            "id": "c4",
            "workspace_id": db.jobs[0]["workspace_id"],
            "first_job_id": OTHER_JOB,
            "used": False,
            "rep_status": "pending",
        },
    ]
    resp = api.get(f"/v1/collect-jobs/{JOB}", headers=auth)
    assert resp.status_code == 200, resp.json()
    out = resp.json()["job"]
    assert out["status"] == "running"
    assert out["result"] is None  # 진행 중이면 집계 생략
    assert [p["profile_id"] for p in out["profiles"]] == [P1, P2]
    assert out["profiles"][0] == {
        "profile_id": P1,
        "chrome_state": "resize_needed",
        "detail": "window_small",
        "status": "running",
        "collected_count": 3,
    }
    assert datetime.fromisoformat(out["worker_last_seen_at"]) == seen
    assert out["worker_online"] is True


def test_get_expires_offline_job(api: TestClient, auth: dict, db: FakeDB):
    old = datetime.now(UTC) - timedelta(minutes=5)
    db.jobs.append(job(status="running", claimed_by=WORKER, started_at=old.isoformat()))
    db.runs.append(run(JOB, P1, 0, "running", 2))
    db.heartbeats.append(
        {
            "worker_id": WORKER,
            "workspace_id": db.jobs[0]["workspace_id"],
            "last_seen_at": old.isoformat(),
        }
    )
    out = api.get(f"/v1/collect-jobs/{JOB}", headers=auth).json()["job"]
    assert out["status"] == "failed" and out["error"] == "worker_offline"
    assert out["worker_online"] is False
    assert out["profiles"][0]["status"] == "failed"


def test_get_worker_seen_falls_back_to_non_revoked_max(api: TestClient, auth: dict, db: FakeDB):
    db.jobs.append(job())
    ws = db.jobs[0]["workspace_id"]
    recent = datetime.now(UTC) - timedelta(minutes=10)
    db.heartbeats += [
        {"worker_id": WORKER, "workspace_id": ws, "last_seen_at": recent.isoformat()},
        {
            "worker_id": WORKER_REVOKED,
            "workspace_id": ws,
            "last_seen_at": datetime.now(UTC).isoformat(),
        },
    ]
    out = api.get(f"/v1/collect-jobs/{JOB}", headers=auth).json()["job"]
    assert datetime.fromisoformat(out["worker_last_seen_at"]) == recent
    assert out["worker_online"] is False


def test_get_no_worker_null(api: TestClient, auth: dict, db: FakeDB):
    db.workers.clear()
    db.jobs.append(job())
    out = api.get(f"/v1/collect-jobs/{JOB}", headers=auth).json()["job"]
    assert out["worker_last_seen_at"] is None and out["worker_online"] is False


def test_get_other_kind_or_workspace_404(api: TestClient, auth: dict, db: FakeDB):
    db.jobs += [job(kind="verify"), job(OTHER_JOB, workspace_id=OTHER_WS)]
    assert api.get(f"/v1/collect-jobs/{JOB}", headers=auth).status_code == 404
    assert api.get(f"/v1/collect-jobs/{OTHER_JOB}", headers=auth).status_code == 404
    assert api.get("/v1/collect-jobs/not-a-uuid", headers=auth).status_code == 400


# --- retry ----------------------------------------------------------------------


def _failed(db: FakeDB, **over) -> None:
    db.jobs.append(job(status="failed", error="chrome_failed", claimed_by=WORKER, **over))
    db.runs += [run(JOB, P1, 0, "done", 3), run(JOB, P2, 1, "failed", 1)]


def test_retry_from_first_not_done(api: TestClient, auth: dict, db: FakeDB):
    _failed(db, lookup_count=4)
    resp = api.post(f"/v1/collect-jobs/{JOB}/retry", headers=auth)
    assert resp.status_code == 200, resp.json()
    out = resp.json()["job"]
    assert out["status"] == "retrying" and out["retry_count"] == 1 and out["error"] is None
    assert [p["status"] for p in out["profiles"]] == ["done", "pending"]
    j = db.jobs[0]
    assert j["params"]["resume_from_profile_id"] == P2 and j["lookup_count"] == 4
    assert j["claimed_by"] is None
    # 두 번째 retry(이미 retrying)는 409
    again = api.post(f"/v1/collect-jobs/{JOB}/retry", headers=auth)
    assert again.status_code == 409


def test_retry_limit_409(api: TestClient, auth: dict, db: FakeDB):
    _failed(db, retry_count=3)
    resp = api.post(f"/v1/collect-jobs/{JOB}/retry", headers=auth)
    assert resp.status_code == 409 and "재시도" in resp.json()["message"]


def test_retry_stop_requested_409(api: TestClient, auth: dict, db: FakeDB):
    _failed(db, stop_requested=True)
    assert api.post(f"/v1/collect-jobs/{JOB}/retry", headers=auth).status_code == 409


def test_retry_lookup_limit_409(api: TestClient, auth: dict, db: FakeDB):
    _failed(db, lookup_count=200)
    resp = api.post(f"/v1/collect-jobs/{JOB}/retry", headers=auth)
    assert resp.status_code == 409
    assert resp.json()["message"] == "이 작업의 조회 상한 도달 — 새 수집 실행"


def test_retry_other_active_409(api: TestClient, auth: dict, db: FakeDB):
    _failed(db)
    db.jobs.append(job(OTHER_JOB, status="queued"))
    resp = api.post(f"/v1/collect-jobs/{JOB}/retry", headers=auth)
    assert resp.status_code == 409 and "진행 중" in resp.json()["message"]


def test_retry_not_failed_409(api: TestClient, auth: dict, db: FakeDB):
    db.jobs.append(job(status="done"))
    assert api.post(f"/v1/collect-jobs/{JOB}/retry", headers=auth).status_code == 409


def test_retry_other_kind_or_workspace_404(api: TestClient, auth: dict, db: FakeDB):
    db.jobs += [
        job(kind="verify", status="failed"),
        job(OTHER_JOB, workspace_id=OTHER_WS, status="failed"),
    ]
    assert api.post(f"/v1/collect-jobs/{JOB}/retry", headers=auth).status_code == 404
    assert api.post(f"/v1/collect-jobs/{OTHER_JOB}/retry", headers=auth).status_code == 404
    assert db.jobs[0]["status"] == "failed" and db.jobs[1]["status"] == "failed"


# --- stop -----------------------------------------------------------------------


def test_stop_queued_immediately(api: TestClient, auth: dict, db: FakeDB):
    db.jobs.append(job(status="queued"))
    out = api.post(f"/v1/collect-jobs/{JOB}/stop", headers=auth).json()["job"]
    assert out["status"] == "stopped" and out["error"] == "stopped_by_user"


def test_stop_retrying_immediately(api: TestClient, auth: dict, db: FakeDB):
    db.jobs.append(job(status="retrying"))
    out = api.post(f"/v1/collect-jobs/{JOB}/stop", headers=auth).json()["job"]
    assert out["status"] == "stopped"


def test_stop_running_requests_only_and_keeps_candidates(api: TestClient, auth: dict, db: FakeDB):
    now = datetime.now(UTC).isoformat()
    db.jobs.append(job(status="running", claimed_by=WORKER, started_at=now))
    db.heartbeats.append(
        {"worker_id": WORKER, "workspace_id": db.jobs[0]["workspace_id"], "last_seen_at": now}
    )
    db.candidates.append(
        {
            "id": "c1",
            "workspace_id": db.jobs[0]["workspace_id"],
            "first_job_id": JOB,
            "used": False,
            "rep_status": "pending",
        }
    )
    resp = api.post(f"/v1/collect-jobs/{JOB}/stop", headers=auth)
    assert resp.status_code == 200
    out = resp.json()["job"]
    assert out["status"] == "running" and out["stop_requested"] is True
    # 워커가 W-04 stopped로 마감한 뒤에도 후보는 그대로
    db.jobs[0].update(status="stopped", error="stopped_by_user")
    got = api.get(f"/v1/collect-jobs/{JOB}", headers=auth).json()["job"]
    assert got["status"] == "stopped" and got["result"]["candidates"] == 1
    assert len(db.candidates) == 1


def test_stop_finished_409(api: TestClient, auth: dict, db: FakeDB):
    for i, status in enumerate(("done", "failed", "stopped")):
        jid = f"00000000-0000-4000-8000-00000000010{i}"
        db.jobs.append(job(jid, status=status))
        resp = api.post(f"/v1/collect-jobs/{jid}/stop", headers=auth)
        assert resp.status_code == 409 and resp.json()["message"] == "이미 종료된 작업입니다."


def test_stop_other_kind_or_workspace_404(api: TestClient, auth: dict, db: FakeDB):
    db.jobs += [job(kind="verify"), job(OTHER_JOB, workspace_id=OTHER_WS)]
    assert api.post(f"/v1/collect-jobs/{JOB}/stop", headers=auth).status_code == 404
    assert api.post(f"/v1/collect-jobs/{OTHER_JOB}/stop", headers=auth).status_code == 404
    assert [j["status"] for j in db.jobs] == ["queued", "queued"]


# --- OpenAPI --------------------------------------------------------------------


def test_openapi_matches_04():
    spec = create_app(make_settings(api_docs_enabled=True)).openapi()
    paths = {p: set(v) for p, v in spec["paths"].items() if p.startswith("/v1/collect-jobs")}
    assert paths == {
        "/v1/collect-jobs": {"post"},
        "/v1/collect-jobs/active": {"get"},
        "/v1/collect-jobs/{job_id}": {"get"},
        "/v1/collect-jobs/{job_id}/retry": {"post"},
        "/v1/collect-jobs/{job_id}/stop": {"post"},
    }
    assert "202" in spec["paths"]["/v1/collect-jobs"]["post"]["responses"]
    for p in ("/v1/collect-jobs/{job_id}/retry", "/v1/collect-jobs/{job_id}/stop"):
        assert "requestBody" not in spec["paths"][p]["post"]  # 본문 없음


# --- 리뷰 반영 ------------------------------------------------------------------


def test_post_daily_limit_429(api: TestClient, auth: dict, db: FakeDB):
    base = datetime.now(UTC) - timedelta(hours=23)
    for i in range(20):
        db.jobs.append(
            job(
                f"00000000-0000-4000-8000-0000000002{i:02d}",
                status="stopped",
                idempotency_key=f"old-{i}",
                created_at=(base + timedelta(minutes=i)).isoformat(),
            )
        )
    resp = _post(api, auth, key="new")
    assert resp.status_code == 429 and resp.json()["code"] == "RATE_LIMITED"
    assert len(db.jobs) == 20
    # 24시간을 넘긴 job은 세지 않는다
    db.jobs[0]["created_at"] = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    assert _post(api, auth, key="new").status_code == 202


def test_post_selected_over_three_400(api: TestClient, auth: dict, db: FakeDB):
    for p in db.profiles:
        p["selected"] = True  # 같은 워크스페이스 4개 선택(다른 워크스페이스 1개는 조회되지 않음)
    db.profiles[:] = [p for p in db.profiles if p["id"] != P_OTHER]
    resp = _post(api, auth)
    assert resp.status_code == 400 and resp.json()["field"] == "profile_ids"
    assert db.jobs == []


def test_post_bad_idempotency_key_400(api: TestClient, auth: dict, db: FakeDB):
    for key in ("k" * 101, b"a\x01b", "키".encode()):
        resp = api.post("/v1/collect-jobs", headers={**auth, "Idempotency-Key": key})
        assert resp.status_code == 400 and resp.json()["field"] == "Idempotency-Key"
    assert _post(api, auth, key="k" * 100).status_code == 202
    assert len(db.jobs) == 1


def test_openapi_retry_stop_200():
    spec = create_app(make_settings(api_docs_enabled=True)).openapi()
    for p in ("/v1/collect-jobs/{job_id}/retry", "/v1/collect-jobs/{job_id}/stop"):
        assert "200" in spec["paths"][p]["post"]["responses"]
    assert "200" in spec["paths"]["/v1/collect-jobs/{job_id}"]["get"]["responses"]


# --- active (task-013) ----------------------------------------------------------


def test_active_returns_detail_200(api: TestClient, auth: dict, db: FakeDB):
    db.jobs += [
        job(OTHER_JOB, status="done", idempotency_key="old"),
        job(status="queued"),
    ]
    db.runs.append(run(JOB, P1, 0, "pending"))
    resp = api.get("/v1/collect-jobs/active", headers=auth)
    assert resp.status_code == 200, resp.json()
    out = resp.json()["job"]
    assert out["id"] == JOB and out["status"] == "queued"
    assert set(out) >= {"result", "profiles", "worker_last_seen_at", "worker_online"}
    assert out == api.get(f"/v1/collect-jobs/{JOB}", headers=auth).json()["job"]


def test_active_none_204(api: TestClient, auth: dict, db: FakeDB):
    db.jobs += [job(status="done"), job(OTHER_JOB, status="stopped", idempotency_key="s")]
    resp = api.get("/v1/collect-jobs/active", headers=auth)
    assert resp.status_code == 204 and resp.content == b""


def test_active_ignores_other_workspace_and_kind(api: TestClient, auth: dict, db: FakeDB):
    db.jobs += [
        job(status="running", workspace_id=OTHER_WS),
        job(OTHER_JOB, status="queued", kind="verify", idempotency_key="v"),
    ]
    assert api.get("/v1/collect-jobs/active", headers=auth).status_code == 204


def test_active_retrying_200(api: TestClient, auth: dict, db: FakeDB):
    db.jobs.append(job(status="retrying"))
    out = api.get("/v1/collect-jobs/active", headers=auth).json()["job"]
    assert out["status"] == "retrying"


def test_active_offline_running_expired_first_204(api: TestClient, auth: dict, db: FakeDB):
    old = datetime.now(UTC) - timedelta(minutes=5)
    db.jobs.append(job(status="running", claimed_by=WORKER, started_at=old.isoformat()))
    db.heartbeats.append(
        {
            "worker_id": WORKER,
            "workspace_id": db.jobs[0]["workspace_id"],
            "last_seen_at": old.isoformat(),
        }
    )
    assert api.get("/v1/collect-jobs/active", headers=auth).status_code == 204
    assert db.jobs[0]["status"] == "failed"


def test_active_unauthenticated_401(api: TestClient):
    assert api.get("/v1/collect-jobs/active").status_code == 401


def test_detail_result_only_when_finished(api: TestClient, auth: dict, db: FakeDB):
    """종료 상태에서만 결과 집계(candidates HEAD 3회). 진행 중은 null·집계 호출 없음."""
    db.jobs.append(job(status="queued"))
    db.candidates.append(
        {
            "id": "c1",
            "workspace_id": db.jobs[0]["workspace_id"],
            "first_job_id": JOB,
            "used": False,
            "rep_status": "producible",
        }
    )
    now = datetime.now(UTC).isoformat()
    db.jobs[0].update(claimed_by=WORKER, started_at=now)
    db.heartbeats.append(
        {"worker_id": WORKER, "workspace_id": db.jobs[0]["workspace_id"], "last_seen_at": now}
    )
    for status in ("queued", "running", "retrying"):
        db.jobs[0]["status"] = status
        out = api.get(f"/v1/collect-jobs/{JOB}", headers=auth).json()["job"]
        assert out["result"] is None, status
    assert api.get("/v1/collect-jobs/active", headers=auth).json()["job"]["result"] is None
    for status in ("done", "failed", "stopped"):
        db.jobs[0]["status"] = status
        out = api.get(f"/v1/collect-jobs/{JOB}", headers=auth).json()["job"]
        assert out["result"] == {"candidates": 1, "producible": 1, "pending": 0}, status
