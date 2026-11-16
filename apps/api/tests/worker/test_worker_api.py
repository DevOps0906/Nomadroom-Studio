"""워커 API W-01~W-04 단위 테스트(PostgREST·YouTube 모두 목). 근거: tasks/task-007.md."""

import asyncio
import io
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.logging_mask import setup_logging
from app.main import create_app
from tests.conftest import make_settings
from tests.worker.conftest import (
    JOB,
    OTHER_JOB,
    OTHER_WS,
    PROFILE_JP,
    PROFILE_KR,
    PROFILE_OUT,
    SECRET,
    WORKER_A,
    WORKER_B,
    WORKER_OTHER,
    WORKER_REVOKED,
    WS,
    YT_KEY,
    FakeDB,
    auth,
    install,
    item,
    job,
    token,
    vid,
    yt_item,
)

CLAIM = "/worker/v1/jobs/claim"
HEARTBEAT = "/worker/v1/heartbeat"


def cands(jid: str = JOB) -> str:
    return f"/worker/v1/jobs/{jid}/candidates"


def finish(jid: str = JOB) -> str:
    return f"/worker/v1/jobs/{jid}/finish"


def ago(**kw) -> str:
    return (datetime.now(UTC) - timedelta(**kw)).isoformat()


def running(db: FakeDB, worker: str = WORKER_A, **over) -> dict:
    j = job(**{"status": "running", "claimed_by": worker, "started_at": ago(seconds=10), **over})
    db.jobs.append(j)
    return j


def fresh_heartbeat(db: FakeDB, worker: str = WORKER_A, at: str | None = None) -> None:
    db.heartbeats.append(
        {"worker_id": worker, "workspace_id": WS, "last_seen_at": at or ago(seconds=5)}
    )


@pytest.fixture
def log_stream():
    stream = io.StringIO()
    handler = setup_logging(stream=stream)
    try:
        yield stream
    finally:
        logging.getLogger().removeHandler(handler)


# --- 인증·인가 -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", CLAIM, None),
        ("POST", HEARTBEAT, {}),
        ("POST", cands(), {"profile_id": PROFILE_KR, "items": [item(1)]}),
        ("POST", finish(), {"status": "done"}),
    ],
)
def test_revoked_or_bad_token_401(api: TestClient, db: FakeDB, method, path, body):
    running(db)
    for headers in (
        auth(WORKER_REVOKED),
        {"Authorization": f"Bearer {WORKER_A}.wrong"},
        {"Authorization": "Bearer nope"},
        {},
    ):
        resp = api.request(method, path, json=body, headers=headers)
        assert resp.status_code == 401, (path, resp.json())
        assert resp.json()["code"] == "UNAUTHENTICATED"
    assert db.jobs[0]["status"] == "running"


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (cands(OTHER_JOB), {"profile_id": PROFILE_KR, "items": [item(1)]}),
        (finish(OTHER_JOB), {"status": "done"}),
    ],
)
def test_other_workspace_job_404(api: TestClient, db: FakeDB, path, body):
    db.jobs.append(job(OTHER_JOB, ws=OTHER_WS, status="running", claimed_by=WORKER_OTHER))
    resp = api.post(path, json=body, headers=auth())
    assert resp.status_code == 404 and resp.json()["code"] == "NOT_FOUND"
    resp = api.post(HEARTBEAT, json={"job_id": OTHER_JOB}, headers=auth())
    assert resp.status_code == 404
    assert db.jobs[0]["status"] == "running"


def test_same_workspace_other_worker_404(api: TestClient, db: FakeDB):
    running(db, WORKER_B)
    assert api.post(finish(), json={"status": "done"}, headers=auth()).status_code == 404
    body = {"profile_id": PROFILE_KR, "items": [item(1)]}
    assert api.post(cands(), json=body, headers=auth()).status_code == 404
    assert api.post(HEARTBEAT, json={"job_id": JOB}, headers=auth()).status_code == 404
    assert db.jobs[0]["status"] == "running" and not db.apply_calls
    # 다른 워커의 job id는 current_job_id에 기록되지 않는다
    assert all(h.get("current_job_id") != JOB for h in db.heartbeats)


# --- W-01 claim ------------------------------------------------------------------


def test_claim_no_job_204(api: TestClient, db: FakeDB):
    resp = api.post(CLAIM, headers=auth())
    assert resp.status_code == 204 and resp.content == b""
    hb = db.heartbeats[0]
    assert hb["worker_id"] == WORKER_A and hb["current_job_id"] is None


def test_claim_other_workspace_queue_not_visible(api: TestClient, db: FakeDB):
    db.jobs.append(job(OTHER_JOB, ws=OTHER_WS))
    assert api.post(CLAIM, headers=auth()).status_code == 204
    assert db.jobs[0]["status"] == "queued" and db.jobs[0]["claimed_by"] is None


@pytest.mark.parametrize("start", ["queued", "retrying"])
def test_claim_transitions_to_running(api: TestClient, db: FakeDB, start: str):
    db.jobs.append(job(status=start, params={"resume_from_profile_id": PROFILE_JP, "limit": 50}))
    resp = api.post(CLAIM, headers=auth())
    assert resp.status_code == 200, resp.json()
    body = resp.json()["job"]
    assert body["id"] == JOB and body["kind"] == "collect"
    assert [p["id"] for p in body["profiles"]] == [PROFILE_KR, PROFILE_JP]
    assert set(body["profiles"][0]) == {
        "id",
        "market",
        "format",
        "category",
        "min_views",
        "keywords",
        "cc_only",
        "include_broadcast",
    }
    assert body["resume_from_profile_id"] == PROFILE_JP and body["limit"] == 50
    j = db.jobs[0]
    assert j["status"] == "running" and j["claimed_by"] == WORKER_A and j["started_at"]
    assert db.heartbeats[0]["current_job_id"] == JOB


def test_claim_default_limit(api: TestClient, db: FakeDB):
    db.jobs.append(job(params={"limit": 999}))
    assert api.post(CLAIM, headers=auth()).json()["job"]["limit"] == 200


def test_claim_concurrent_only_one_wins(mock_supabase, db: FakeDB):
    db.jobs.append(job())
    install(mock_supabase, db)
    app = create_app(make_settings(youtube_api_key=YT_KEY))

    async def run() -> list[int]:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                rs = await asyncio.gather(
                    c.post(CLAIM, headers=auth(WORKER_A)), c.post(CLAIM, headers=auth(WORKER_B))
                )
        return sorted(r.status_code for r in rs)

    assert asyncio.run(run()) == [200, 204]
    assert db.jobs[0]["claimed_by"] in (WORKER_A, WORKER_B)


def test_claim_restart_returns_own_running_job(api: TestClient, db: FakeDB):
    running(db)
    fresh_heartbeat(db)
    resp = api.post(CLAIM, headers=auth())
    assert resp.status_code == 200 and resp.json()["job"]["id"] == JOB
    # 다른 워커는 받지 못한다
    assert api.post(CLAIM, headers=auth(WORKER_B)).status_code == 204


def test_claim_does_not_take_others_running_job(api: TestClient, db: FakeDB):
    running(db, WORKER_B)
    fresh_heartbeat(db, WORKER_B)
    assert api.post(CLAIM, headers=auth()).status_code == 204
    assert db.jobs[0]["claimed_by"] == WORKER_B


# --- 오프라인 지연 평가 -----------------------------------------------------------


def test_offline_worker_job_failed_on_claim(api: TestClient, db: FakeDB):
    running(db, WORKER_B, started_at=ago(minutes=10))
    fresh_heartbeat(db, WORKER_B, at=ago(minutes=3, seconds=1))
    db.runs.append(
        {"workspace_id": WS, "job_id": JOB, "profile_id": PROFILE_KR, "status": "running"}
    )
    assert api.post(CLAIM, headers=auth()).status_code == 204
    j = db.jobs[0]
    assert j["status"] == "failed" and j["error"] == "worker_offline" and j["finished_at"]
    assert db.runs[0]["status"] == "failed"


def test_offline_without_heartbeat_uses_started_at(api: TestClient, db: FakeDB):
    db.jobs.append(job(status="running", claimed_by=WORKER_B, started_at=ago(minutes=4)))
    api.post(HEARTBEAT, json={}, headers=auth())
    assert db.jobs[0]["status"] == "failed" and db.jobs[0]["error"] == "worker_offline"


def test_not_offline_within_3_minutes(api: TestClient, db: FakeDB):
    running(db, WORKER_B)
    fresh_heartbeat(db, WORKER_B, at=ago(minutes=2, seconds=50))
    api.post(HEARTBEAT, json={}, headers=auth())
    assert db.jobs[0]["status"] == "running"


def test_offline_failed_job_then_heartbeat_409(api: TestClient, db: FakeDB):
    """오프라인 판정 뒤 돌아온 워커: W-02~04는 409, claim은 새 작업만."""
    running(db, started_at=ago(minutes=10))
    fresh_heartbeat(db, at=ago(minutes=5))
    api.post(HEARTBEAT, json={}, headers=auth(WORKER_B))  # 다른 워커가 평가를 일으킴
    assert db.jobs[0]["status"] == "failed"
    assert api.post(HEARTBEAT, json={"job_id": JOB}, headers=auth()).status_code == 409
    assert api.post(finish(), json={"status": "done"}, headers=auth()).status_code == 409


# --- W-02 heartbeat --------------------------------------------------------------


def test_heartbeat_records_chrome_and_stop_requested(api: TestClient, db: FakeDB):
    running(db, stop_requested=True)
    body = {
        "job_id": JOB,
        "chrome": [
            {"profile_id": PROFILE_JP, "state": "login_needed", "detail": "login_required"},
            {"profile_id": PROFILE_KR, "state": "ready"},
        ],
    }
    resp = api.post(HEARTBEAT, json=body, headers=auth())
    assert resp.status_code == 200 and resp.json() == {"stop_requested": True}
    hb = db.heartbeats[0]
    assert hb["current_job_id"] == JOB
    assert hb["chrome"][PROFILE_JP] == {"state": "login_needed", "detail": "login_required"}
    runs = {r["profile_id"]: r for r in db.runs}
    assert runs[PROFILE_JP]["chrome_state"] == "login_needed"
    assert runs[PROFILE_JP]["position"] == 1 and runs[PROFILE_KR]["position"] == 0
    # 두 번째 하트비트는 같은 행을 갱신(행 추가 없음)
    api.post(HEARTBEAT, json={"job_id": JOB, "chrome": [body["chrome"][1]]}, headers=auth())
    assert len(db.runs) == 2 and len(db.heartbeats) == 1


def test_heartbeat_without_job(api: TestClient, db: FakeDB):
    resp = api.post(HEARTBEAT, headers=auth())
    assert resp.status_code == 200 and resp.json() == {"stop_requested": False}
    assert db.heartbeats[0]["current_job_id"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"job_id": JOB, "chrome": [{"profile_id": PROFILE_OUT, "state": "ready"}]},
        {"chrome": [{"profile_id": PROFILE_KR, "state": "ready"}]},
        {
            "job_id": JOB,
            "chrome": [{"profile_id": PROFILE_KR, "state": "ready", "detail": "C:\\x"}],
        },
        {"job_id": JOB, "chrome": [{"profile_id": PROFILE_KR, "state": "weird"}]},
        {"job_id": JOB, "extra": 1},
    ],
)
def test_heartbeat_validation_400(api: TestClient, db: FakeDB, body):
    running(db)
    resp = api.post(HEARTBEAT, json=body, headers=auth())
    assert resp.status_code == 400 and resp.json()["code"] == "VALIDATION"
    assert not db.runs


# --- W-03 후보 접수 --------------------------------------------------------------


def seed_youtube(db: FakeDB, *ns: int, **kw) -> None:
    for n in ns:
        db.youtube[vid(n)] = yt_item(vid(n), 1000 + n, **kw)


def test_candidates_accept_dedupe_unavailable(api: TestClient, db: FakeDB):
    running(db)
    db.candidates.append({"id": "x", "workspace_id": WS, "video_id": vid(3)})  # 기존 후보
    db.candidates.append({"id": "y", "workspace_id": OTHER_WS, "video_id": vid(4)})  # 다른 ws
    seed_youtube(db, 1, 2, 4)  # 5는 YouTube 응답에 없음
    items = [item(1), item(2), item(1, title="중복"), item(3), item(4), item(5)]
    resp = api.post(cands(), json={"profile_id": PROFILE_KR, "items": items}, headers=auth())
    assert resp.status_code == 200, resp.json()
    assert resp.json() == {"accepted": 3, "duplicates": 2, "unavailable": 1}
    assert len(db.youtube_calls) == 1 and db.quota_calls == 1
    sent = db.youtube_calls[0]
    assert sent.headers["X-Goog-Api-Key"] == YT_KEY and "key=" not in str(sent.url)
    assert set(sent.url.params["id"].split(",")) == {vid(1), vid(2), vid(4), vid(5)}
    run = db.runs[0]
    assert run["profile_id"] == PROFILE_KR and run["collected_count"] == 3
    new = {c["video_id"]: c for c in db.candidates if c.get("first_job_id") == JOB}
    assert set(new) == {vid(1), vid(2), vid(4)}


def test_candidates_youtube_values_override_worker(api: TestClient, db: FakeDB):
    running(db)
    bc = "UC" + "b" * 22
    db.broadcasters.append({"workspace_id": WS, "channel_id": bc})
    seed_youtube(db, 1, license="youtube", channel=bc)
    body = {"profile_id": PROFILE_KR, "items": [item(1, title="워커가 바꾼 제목")]}
    assert api.post(cands(), json=body, headers=auth()).status_code == 200
    c = db.candidates[0]
    assert c["title"] == "t"  # YouTube 제목
    assert c["thumbnail_url"] == f"https://i.ytimg.com/vi/{vid(1)}/hqdefault.jpg"
    assert c["channel_id"] == bc and c["channel_title"] == f"채널 {bc}"
    assert c["license_cc"] is False and c["is_broadcaster"] is True
    # 워커 값 그대로
    assert (c["market"], c["format"], c["genre"]) == ("KR", "long", "음악")
    # 이전 관측 없음 → 근거 대기
    assert db.verdicts[0] == {
        "candidate_id": c["id"],
        "profile_id": PROFILE_KR,
        "status": "pending",
        "reason": "no_prev",
    }
    assert c["rep_status"] == "pending" and c["rep_profile_id"] == PROFILE_KR
    assert db.observations[0]["view_count"] == 1001


def test_candidates_condition_excluded(api: TestClient, db: FakeDB):
    running(db)
    seed_youtube(db, 1)
    body = {"profile_id": PROFILE_JP, "items": [item(1, market="KR")]}
    assert api.post(cands(), json=body, headers=auth()).json()["accepted"] == 1
    assert db.verdicts[0]["status"] == "excluded" and db.verdicts[0]["reason"] == "market"
    assert db.runs[0]["position"] == 1


def test_candidates_all_duplicates_skips_youtube(api: TestClient, db: FakeDB):
    running(db)
    db.candidates.append({"id": "x", "workspace_id": WS, "video_id": vid(1)})
    body = {"profile_id": PROFILE_KR, "items": [item(1), item(1)]}
    resp = api.post(cands(), json=body, headers=auth())
    assert resp.json() == {"accepted": 0, "duplicates": 2, "unavailable": 0}
    assert not db.youtube_calls and db.quota_calls == 0 and not db.apply_calls


def test_candidates_race_counts_as_duplicate(api: TestClient, db: FakeDB):
    running(db)
    seed_youtube(db, 1, 2)
    db.race_insert = [vid(2)]
    body = {"profile_id": PROFILE_KR, "items": [item(1), item(2)]}
    assert api.post(cands(), json=body, headers=auth()).json() == {
        "accepted": 1,
        "duplicates": 1,
        "unavailable": 0,
    }


def test_candidates_batches_of_50(api: TestClient, db: FakeDB):
    running(db)
    seed_youtube(db, *range(1, 121))
    body = {"profile_id": PROFILE_KR, "items": [item(n) for n in range(1, 121)]}
    assert api.post(cands(), json=body, headers=auth()).json()["accepted"] == 120
    assert len(db.youtube_calls) == 3 and db.quota_calls == 3 and len(db.apply_calls) == 1


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (httpx.Response(500), 502, "UPSTREAM_ERROR"),
        (httpx.ConnectError("x"), 502, "UPSTREAM_ERROR"),
        (
            httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}}),
            429,
            "QUOTA_EXCEEDED",
        ),
    ],
)
def test_candidates_youtube_failure_inserts_nothing(
    api: TestClient, db: FakeDB, error, status, code
):
    running(db)
    db.youtube_error = error
    body = {"profile_id": PROFILE_KR, "items": [item(1)]}
    resp = api.post(cands(), json=body, headers=auth())
    assert resp.status_code == status and resp.json()["code"] == code
    assert not db.apply_calls and not db.candidates and not db.runs


def test_candidates_second_batch_failure_inserts_nothing(api: TestClient, db: FakeDB):
    """첫 묶음 조회가 성공해도 두 번째 묶음이 실패하면 아무것도 넣지 않는다."""
    running(db)
    seed_youtube(db, *range(1, 61))

    class Calls(list):
        def append(self, x):
            super().append(x)
            if len(self) == 2:
                db.youtube_error = httpx.Response(500)  # 다음 호출부터 실패

    db.youtube_calls = Calls()
    body = {"profile_id": PROFILE_KR, "items": [item(n) for n in range(1, 61)]}
    resp = api.post(cands(), json=body, headers=auth())
    assert resp.status_code == 502 and len(db.youtube_calls) == 2
    assert not db.apply_calls and not db.candidates and not db.runs


def test_candidates_quota_reserve_refused_429(api: TestClient, db: FakeDB):
    running(db)
    seed_youtube(db, 1)
    db.quota_ok = False
    resp = api.post(cands(), json={"profile_id": PROFILE_KR, "items": [item(1)]}, headers=auth())
    assert resp.status_code == 429 and resp.json()["code"] == "QUOTA_EXCEEDED"
    assert not db.youtube_calls and not db.apply_calls


@pytest.mark.parametrize("status", ["stopped", "done", "failed", "queued", "retrying"])
def test_candidates_not_running_409(api: TestClient, db: FakeDB, status: str):
    db.jobs.append(job(status=status, claimed_by=WORKER_A))
    resp = api.post(cands(), json={"profile_id": PROFILE_KR, "items": [item(1)]}, headers=auth())
    assert resp.status_code == 409 and resp.json()["code"] == "CONFLICT"
    assert not db.youtube_calls


def test_candidates_job_stopped_between_check_and_apply_409(api: TestClient, db: FakeDB):
    j = running(db)
    seed_youtube(db, 1)

    class Calls(list):
        def append(self, x):
            super().append(x)
            j["status"] = "stopped"  # YouTube 조회 중 중지됨

    db.youtube_calls = Calls()
    resp = api.post(cands(), json={"profile_id": PROFILE_KR, "items": [item(1)]}, headers=auth())
    assert resp.status_code == 409 and not db.candidates


def test_candidates_profile_not_in_job_400(api: TestClient, db: FakeDB):
    running(db)
    resp = api.post(cands(), json={"profile_id": PROFILE_OUT, "items": [item(1)]}, headers=auth())
    assert resp.status_code == 400 and resp.json()["field"] == "profile_id"


def test_candidates_201_items_400(api: TestClient, db: FakeDB):
    running(db)
    body = {"profile_id": PROFILE_KR, "items": [item(n) for n in range(201)]}
    resp = api.post(cands(), json=body, headers=auth())
    assert resp.status_code == 400 and resp.json()["code"] == "VALIDATION"
    assert not db.youtube_calls


@pytest.mark.parametrize(
    "bad",
    [
        {"video_id": "short"},
        {"video_id": "abc/def#123"},
        {"title": "x" * 301},
        {"title": "줄\n바꿈"},
        {"channel_title": "c" * 201},
        {"genre": "g" * 41},
        {"category": "a\x00b"},
        {"market": "US"},
        {"format": "medium"},
        {"cookie": "SID=abc"},
    ],
)
def test_candidates_item_validation_400(api: TestClient, db: FakeDB, bad: dict):
    running(db)
    body = {"profile_id": PROFILE_KR, "items": [item(1, **bad)]}
    resp = api.post(cands(), json=body, headers=auth())
    assert resp.status_code == 400 and resp.json()["code"] == "VALIDATION"
    assert "SID=abc" not in resp.text and "\x00" not in resp.text


def test_body_over_1mb_413(api: TestClient, db: FakeDB):
    running(db)
    big = (
        b'{"profile_id": "'
        + PROFILE_KR.encode()
        + b'", "items": [], "pad": "'
        + b"x" * 1_100_000
        + b'"}'
    )
    resp = api.post(cands(), content=big, headers={**auth(), "Content-Type": "application/json"})
    assert resp.status_code == 413 and resp.json()["code"] == "PAYLOAD_TOO_LARGE"

    def chunks():
        yield b'{"pad": "'
        for _ in range(11):
            yield b"x" * 100_000
        yield b'"}'

    resp = api.post(
        cands(), content=chunks(), headers={**auth(), "Content-Type": "application/json"}
    )
    assert resp.status_code == 413


# --- W-04 finish -----------------------------------------------------------------


@pytest.mark.parametrize(("status", "run_status"), [("done", "done"), ("failed", "failed")])
def test_finish_done_failed(api: TestClient, db: FakeDB, status: str, run_status: str):
    running(db)
    db.runs.append(
        {"workspace_id": WS, "job_id": JOB, "profile_id": PROFILE_KR, "status": "running"}
    )
    db.runs.append({"workspace_id": WS, "job_id": JOB, "profile_id": PROFILE_JP, "status": "done"})
    body = {"status": status} | ({"error": "vidiq_changed"} if status == "failed" else {})
    resp = api.post(finish(), json=body, headers=auth())
    assert resp.status_code == 200 and resp.json() == {"job": {"status": status}}
    j = db.jobs[0]
    assert j["status"] == status and j["finished_at"]
    assert j["error"] == (None if status == "done" else "vidiq_changed")
    assert db.runs[0]["status"] == run_status and db.runs[1]["status"] == "done"


def test_finish_failed_default_error(api: TestClient, db: FakeDB):
    running(db)
    api.post(finish(), json={"status": "failed"}, headers=auth())
    assert db.jobs[0]["error"] == "unknown"


def test_finish_stopped_requires_stop_requested(api: TestClient, db: FakeDB):
    running(db)
    resp = api.post(finish(), json={"status": "stopped"}, headers=auth())
    assert resp.status_code == 409 and db.jobs[0]["status"] == "running"
    db.jobs[0]["stop_requested"] = True
    resp = api.post(finish(), json={"status": "stopped"}, headers=auth())
    assert resp.status_code == 200 and db.jobs[0]["status"] == "stopped"
    assert db.jobs[0]["error"] == "stopped_by_user"


@pytest.mark.parametrize("status", ["stopped", "failed", "queued", "retrying"])
def test_finish_not_running_409(api: TestClient, db: FakeDB, status: str):
    db.jobs.append(job(status=status, claimed_by=WORKER_A, stop_requested=True))
    resp = api.post(finish(), json={"status": "done"}, headers=auth())
    assert resp.status_code == 409 and db.jobs[0]["status"] == status


@pytest.mark.parametrize(
    "body", [{"status": "running"}, {"status": "failed", "error": "C:\\Users\\x cookie"}, {}]
)
def test_finish_validation_400(api: TestClient, db: FakeDB, body):
    running(db)
    resp = api.post(finish(), json=body, headers=auth())
    assert resp.status_code == 400 and "cookie" not in resp.text


def test_full_lifecycle(api: TestClient, db: FakeDB):
    """queued → claim(running) → heartbeat → candidates → stop 요청 → finish(stopped)."""
    db.jobs.append(job())
    seed_youtube(db, 1)
    assert api.post(CLAIM, headers=auth()).status_code == 200
    assert api.post(HEARTBEAT, json={"job_id": JOB}, headers=auth()).json() == {
        "stop_requested": False
    }
    body = {"profile_id": PROFILE_KR, "items": [item(1)]}
    assert api.post(cands(), json=body, headers=auth()).json()["accepted"] == 1
    db.jobs[0]["stop_requested"] = True  # A-05 stop(task-008)이 켠다
    assert api.post(HEARTBEAT, json={"job_id": JOB}, headers=auth()).json() == {
        "stop_requested": True
    }
    assert api.post(finish(), json={"status": "stopped"}, headers=auth()).status_code == 200
    assert api.post(HEARTBEAT, json={"job_id": JOB}, headers=auth()).status_code == 409
    assert api.post(cands(), json=body, headers=auth()).status_code == 409
    assert db.runs[0]["status"] == "failed"  # running 행은 job 종료에 맞춰 닫힘


# --- 로그 ------------------------------------------------------------------------


def test_logs_have_no_token_or_cookie(api: TestClient, db: FakeDB, log_stream):
    running(db)
    seed_youtube(db, 1)
    cookie = "SID=supersecretcookievalue; HSID=abc"
    api.post(
        HEARTBEAT,
        json={
            "job_id": JOB,
            "chrome": [{"profile_id": PROFILE_KR, "state": "error", "detail": cookie}],
        },
        headers=auth(),
    )
    api.post(
        cands(), json={"profile_id": PROFILE_KR, "items": [item(1, title=cookie)]}, headers=auth()
    )
    api.post(
        cands(), json={"profile_id": PROFILE_KR, "items": [item(2, genre=cookie)]}, headers=auth()
    )
    db.youtube_error = httpx.Response(500)
    api.post(cands(), json={"profile_id": PROFILE_KR, "items": [item(3)]}, headers=auth())
    api.post(finish(), json={"status": "failed", "error": cookie}, headers=auth())
    api.post(CLAIM, headers=auth(WORKER_REVOKED))
    api.post(CLAIM, headers={"Authorization": f"Bearer {WORKER_A}.{SECRET}wrong", "Cookie": cookie})
    logs = log_stream.getvalue()
    assert logs  # 경고가 실제로 기록됐다
    for secret in (token(WORKER_A), SECRET, "supersecretcookievalue", "HSID", YT_KEY):
        assert secret not in logs


# --- 리뷰 반영 회귀 테스트(task-007 "리뷰 반영 결정") --------------------------------


def test_offline_basis_is_max_of_heartbeat_and_started_at(api: TestClient, db: FakeDB):
    """재수령 직후: 옛 하트비트(5분 전)가 있어도 claim 시각이 최근이면 실패 처리하지 않는다."""
    running(db, WORKER_B, started_at=ago(seconds=30))
    fresh_heartbeat(db, WORKER_B, at=ago(minutes=5))
    api.post(HEARTBEAT, json={}, headers=auth())
    assert db.jobs[0]["status"] == "running"


def test_claim_clears_previous_failure(api: TestClient, db: FakeDB):
    db.jobs.append(
        job(
            status="retrying",
            error="worker_offline",
            finished_at=ago(minutes=1),
            claimed_by=WORKER_B,
        )
    )
    assert api.post(CLAIM, headers=auth()).status_code == 200
    j = db.jobs[0]
    assert j["status"] == "running" and j["error"] is None and j["finished_at"] is None
    assert j["claimed_by"] == WORKER_A


@pytest.mark.parametrize("status", ["done", "failed", "stopped"])
def test_finish_idempotent_same_status(api: TestClient, db: FakeDB, status: str):
    running(db, stop_requested=True)
    db.runs.append(
        {"workspace_id": WS, "job_id": JOB, "profile_id": PROFILE_KR, "status": "running"}
    )
    assert api.post(finish(), json={"status": status}, headers=auth()).status_code == 200
    db.runs[0]["status"] = "running"  # 첫 요청의 행 닫기가 실패했다고 가정
    resp = api.post(finish(), json={"status": status}, headers=auth())
    assert resp.status_code == 200 and resp.json() == {"job": {"status": status}}
    assert db.runs[0]["status"] == ("done" if status == "done" else "failed")
    other = "failed" if status != "failed" else "done"
    assert api.post(finish(), json={"status": other}, headers=auth()).status_code == 409


def test_finish_offline_failed_not_idempotent(api: TestClient, db: FakeDB):
    db.jobs.append(job(status="failed", claimed_by=WORKER_A, error="worker_offline"))
    assert api.post(finish(), json={"status": "failed"}, headers=auth()).status_code == 409


def test_candidates_stop_requested_409(api: TestClient, db: FakeDB):
    running(db, stop_requested=True)
    seed_youtube(db, 1)
    resp = api.post(cands(), json={"profile_id": PROFILE_KR, "items": [item(1)]}, headers=auth())
    assert resp.status_code == 409 and resp.json()["code"] == "CONFLICT"
    assert not db.lookup_calls and not db.youtube_calls and not db.apply_calls


def test_candidates_stop_requested_during_lookup_409(api: TestClient, db: FakeDB):
    j = running(db)
    seed_youtube(db, 1)

    class Calls(list):
        def append(self, x):
            super().append(x)
            j["stop_requested"] = True  # YouTube 조회 중 중지 요청

    db.youtube_calls = Calls()
    resp = api.post(cands(), json={"profile_id": PROFILE_KR, "items": [item(1)]}, headers=auth())
    assert resp.status_code == 409 and not db.candidates


def test_candidates_cumulative_limit_409(api: TestClient, db: FakeDB):
    """반복 W-03: job 누적 조회가 params.limit을 넘으면 YouTube·할당량을 쓰기 전에 409."""
    running(db, params={"limit": 3})
    seed_youtube(db, *range(1, 10))
    ok = api.post(
        cands(), json={"profile_id": PROFILE_KR, "items": [item(1), item(2)]}, headers=auth()
    )
    assert ok.status_code == 200 and ok.json()["accepted"] == 2
    calls = (len(db.youtube_calls), db.quota_calls)
    resp = api.post(
        cands(), json={"profile_id": PROFILE_JP, "items": [item(3), item(4)]}, headers=auth()
    )
    assert resp.status_code == 409 and resp.json()["message"] == "수집 상한에 도달했습니다."
    assert (len(db.youtube_calls), db.quota_calls) == calls
    assert db.jobs[0]["lookup_count"] == 2
    assert db.lookup_calls[0]["p_n"] == 2


def test_candidates_default_limit_200(api: TestClient, db: FakeDB):
    running(db)
    db.jobs[0]["lookup_count"] = 199
    seed_youtube(db, 1, 2)
    body = {"profile_id": PROFILE_KR, "items": [item(1), item(2)]}
    assert api.post(cands(), json=body, headers=auth()).status_code == 409
    body = {"profile_id": PROFILE_KR, "items": [item(1)]}
    assert api.post(cands(), json=body, headers=auth()).status_code == 200


def test_candidates_apply_limit_nr005_409(api: TestClient, db: FakeDB):
    """조회 예약은 통과해도 RPC가 누적 accepted 상한으로 거부하면 409."""
    running(db, params={"limit": 2})
    db.runs.append(
        {
            "workspace_id": WS,
            "job_id": JOB,
            "profile_id": PROFILE_KR,
            "position": 0,
            "status": "running",
            "collected_count": 2,
        }
    )
    seed_youtube(db, 1)
    resp = api.post(cands(), json={"profile_id": PROFILE_KR, "items": [item(1)]}, headers=auth())
    assert resp.status_code == 409 and not db.candidates


def test_candidates_next_profile_closes_previous(api: TestClient, db: FakeDB):
    running(db)
    seed_youtube(db, 1, 2)
    api.post(cands(), json={"profile_id": PROFILE_KR, "items": [item(1)]}, headers=auth())
    api.post(cands(), json={"profile_id": PROFILE_JP, "items": [item(2)]}, headers=auth())
    runs = {r["profile_id"]: r["status"] for r in db.runs}
    assert runs == {PROFILE_KR: "done", PROFILE_JP: "running"}


@pytest.mark.parametrize("title", [None, "", "   "])
def test_candidates_blank_youtube_title_unavailable(api: TestClient, db: FakeDB, title):
    running(db)
    seed_youtube(db, 1, 2)
    db.youtube[vid(1)]["snippet"]["title"] = title
    body = {"profile_id": PROFILE_KR, "items": [item(1), item(2)]}
    resp = api.post(cands(), json=body, headers=auth())
    assert resp.json() == {"accepted": 1, "duplicates": 0, "unavailable": 1}
    assert [c["video_id"] for c in db.candidates] == [vid(2)]
    assert all(c["title"] != "워커 제목 1" for c in db.candidates)


@pytest.mark.parametrize(
    "ch",
    [
        "\x85",
        "\x9f",
        "\u200b",
        "\u200d",
        "\ufeff",
        "\u2028",
        "\u2029",
        "\u202a",
        "\u202e",
        "\u2066",
        "\u2069",
        "\x07",
        "\x7f",
    ],
)
@pytest.mark.parametrize("key", ["genre", "category"])
def test_candidates_forbidden_unicode_400(api: TestClient, db: FakeDB, ch: str, key: str):
    running(db)
    body = {"profile_id": PROFILE_KR, "items": [item(1, **{key: f"예{ch}능"})]}
    resp = api.post(cands(), json=body, headers=auth())
    assert resp.status_code == 400 and resp.json()["code"] == "VALIDATION"
    assert not db.lookup_calls


def test_candidates_normal_unicode_ok(api: TestClient, db: FakeDB):
    running(db)
    seed_youtube(db, 1)
    body = {"profile_id": PROFILE_KR, "items": [item(1, genre="영화·드라마", category="J-POP 🎵")]}
    assert api.post(cands(), json=body, headers=auth()).status_code == 200


@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer nope", "Basic abc", f"Bearer {WORKER_A}", "Bearer not-a-uuid-at-all.secret"],
)
def test_bad_authorization_format_401_before_body(mock_supabase, db: FakeDB, authorization):
    """형식이 아닌 Authorization이면 본문을 한 바이트도 읽지 않고 401."""
    install(mock_supabase, db)
    app = create_app(make_settings(youtube_api_key=YT_KEY))
    received: list[dict] = []
    sent: list[dict] = []
    headers = [(b"content-type", b"application/json"), (b"content-length", b"10")]
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": cands(),
        "raw_path": cands().encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("t", 1),
        "server": ("t", 80),
    }

    async def receive() -> dict:
        msg = {"type": "http.request", "body": b"{}", "more_body": False}
        received.append(msg)
        return msg

    async def send(msg: dict) -> None:
        sent.append(msg)

    asyncio.run(app(scope, receive, send))
    assert sent[0]["status"] == 401 and not received
    assert dict(sent[0]["headers"])[b"www-authenticate"] == b"Bearer"
    assert b"UNAUTHENTICATED" in sent[1]["body"]
    # 워커 조회(DB)도 하지 않는다
    assert not [c for c in mock_supabase.calls if "/workers" in str(c.request.url)]
