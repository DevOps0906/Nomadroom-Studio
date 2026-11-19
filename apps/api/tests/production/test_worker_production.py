"""task-023 제작 워커 API(W-05~W-09) 단위 테스트. 가짜 저장소·RPC는 test_render_runs를 재사용한다.

완료 조건(두 워커 동시 claim 중 1건만 수령, 허용 외 kind 400, 타 워크스페이스 토큰 404)과
착수 결정 E2·E4·E6·E7·E9를 각각 1건 이상 확인한다.
"""

import io
import logging
import sys
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.logging_mask import setup_logging
from tests.production import test_render_runs as rr
from tests.production.test_jobs_api import OTHER_WS, STORAGE, WS, good_spec
from tests.production.test_render_runs import (
    WORKER_A,
    WORKER_B,
    WORKER_OTHER,
    ProdDB,
    ago,
    wauth,
)

api = rr.api  # 픽스처 재사용
db = rr.db

W = "/worker/v1/production"


def preparing(db: ProdDB, ws: str = WS, **over) -> dict:
    job = db.add_job(ws=ws, status="preparing", **over)
    db.add_asset(job, "source_upload")
    return job


def rendering(db: ProdDB, status: str = "queued", **over) -> tuple[dict, dict, dict]:
    job = db.add_job(status="rendering", format=over.pop("format", "category"))
    rev = db.add_revision(job, approved=True)
    run = db.add_run(job, rev, status=status, **over)
    return job, rev, run


def claim(api, worker: str = WORKER_A):
    return api.post(f"{W}/claim", headers=wauth(worker))


def outputs(api, kind: str, task_id: str, items: list[dict], worker: str = WORKER_A):
    return api.post(f"{W}/{kind}/{task_id}/outputs", json={"items": items}, headers=wauth(worker))


def finish(api, kind: str, task_id: str, worker: str = WORKER_A, **body):
    return api.post(f"{W}/{kind}/{task_id}/finish", json=body, headers=wauth(worker))


def item(kind: str, mime: str, size: int = 10, **over) -> dict:
    return {"kind": kind, "mime": mime, "size_bytes": size, **over}


PREPARE_ITEMS = [
    item("source", "video/mp4", duration_sec=60.0),
    item("analysis", "application/json"),
    item("sheet", "image/jpeg"),
]
META = {"duration_sec": 60.0, "width": 1920, "height": 1080, "has_audio": True}
RENDER_ITEMS = [item("output_mp4", "video/mp4"), item("report", "application/json")]


def upload_all(db: ProdDB, resp) -> list[str]:
    """W-07 응답의 자산을 선언 크기 그대로 Storage에 올린 것으로 둔다."""
    ids = []
    for it in resp.json()["items"]:
        asset = next(a for a in db.assets if a["id"] == it["asset_id"])
        db.objects[asset["storage_path"]] = asset["size_bytes"]
        ids.append(it["asset_id"])
    return ids


# === W-05 수령(E2·E4) ============================================================


def test_w05_no_task_is_204_and_heartbeat_upserted_without_job(api, db):
    r = claim(api)
    assert r.status_code == 204
    hb = next(h for h in db.heartbeats if h["worker_id"] == WORKER_A)
    assert hb["current_job_id"] is None and hb["workspace_id"] == WS


def test_w05_two_workers_claim_only_one_gets_task(api, db):
    job = preparing(db)
    first = claim(api, WORKER_A)
    second = claim(api, WORKER_B)
    assert first.status_code == 200 and second.status_code == 204
    task = first.json()["task"]
    assert task["kind"] == "prepare" and task["id"] == job["id"] and task["job_id"] == job["id"]
    assert task["job_kind"] == "general" and task["format"] == "category"
    assert task["source_kind"] == "upload" and task["spec"] is None
    assert db.job(job["id"])["claimed_by"] == WORKER_A


def test_e2_restart_recovery_returns_same_task(api, db):
    _, _, run = rendering(db)
    first = claim(api).json()["task"]
    rendering(db, created_at=ago(minutes=1))  # 다른 대기 run이 있어도
    again = claim(api).json()["task"]
    assert again["id"] == first["id"] == run["id"]


def test_w05_render_task_has_spec_lang_and_marks_running(api, db):
    _, rev, run = rendering(db)
    task = claim(api).json()["task"]
    assert task["kind"] == "render" and task["lang"] == "ko"
    assert task["spec"] == rev["spec"] == good_spec()
    assert run["status"] == "running" and run["claimed_by"] == WORKER_A
    assert run["started_at"] is not None


def test_e2_oldest_task_first(api, db):
    rendering(db, created_at=ago(minutes=2))
    job = preparing(db, created_at=ago(minutes=5))
    assert claim(api).json()["task"]["id"] == job["id"]


def test_w05_other_workspace_tasks_not_claimed(api, db):
    preparing(db, ws=OTHER_WS)
    assert claim(api).status_code == 204


# === 인가(404·409) ===============================================================


def test_other_workspace_token_is_404_everywhere(api, db):
    job = preparing(db)
    claim(api)
    calls = [
        api.get(f"{W}/prepare/{job['id']}/inputs", headers=wauth(WORKER_OTHER)),
        outputs(api, "prepare", job["id"], PREPARE_ITEMS, WORKER_OTHER),
        api.post(
            f"{W}/prepare/{job['id']}/progress",
            json={"stage": "extract", "progress_pct": 5},
            headers=wauth(WORKER_OTHER),
        ),
        finish(
            api,
            "prepare",
            job["id"],
            WORKER_OTHER,
            status="failed",
            error_stage="prepare",
            error_code="unknown",
        ),
    ]
    assert [c.status_code for c in calls] == [404] * 4
    assert db.job(job["id"])["status"] == "preparing"


def test_other_worker_same_workspace_is_409(api, db):
    job = preparing(db)
    claim(api, WORKER_A)
    r = api.get(f"{W}/prepare/{job['id']}/inputs", headers=wauth(WORKER_B))
    assert r.status_code == 409 and r.json()["message"] == "다른 워커의 작업입니다."


def test_invalid_worker_token_is_401(api, db):
    r = api.post(f"{W}/claim", headers={"Authorization": f"Bearer {WORKER_A}.wrong"})
    assert r.status_code == 401


# === W-06 입력(E9) ===============================================================


def test_w06_prepare_inputs_signed_source_upload(api, db):
    job = preparing(db)
    claim(api)
    before = datetime.now(UTC)
    r = api.get(f"{W}/prepare/{job['id']}/inputs", headers=wauth())
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    inputs = r.json()["inputs"]
    assert [i["kind"] for i in inputs] == ["source_upload"]
    assert inputs[0]["download_url"].startswith(f"{STORAGE}/object/sign/production/")
    expires = datetime.fromisoformat(inputs[0]["expires_at"])
    assert timedelta(seconds=595) <= expires - before <= timedelta(seconds=605)


def test_e9_render_inputs_latest_source_analysis_and_user_hook_audio(api, db):
    job, _, run = rendering(db)
    db.add_asset(job, "source", created_at=ago(minutes=9))
    new_source = db.add_asset(job, "source", created_at=ago(minutes=8))
    analysis = db.add_asset(job, "analysis", mime="application/json")
    hook = db.add_asset(job, "hook_audio", mime="audio/wav", created_at=ago(minutes=7))
    db.add_asset(job, "hook_audio", status="pending", mime="audio/wav")
    db.add_asset(job, "sheet", mime="image/jpeg")
    claim(api)
    # 렌더 산출물 hook_audio(render_run_id 있음)는 입력이 아니다
    db.add_asset(job, "hook_audio", mime="audio/wav", render_run_id=run["id"])
    inputs = api.get(f"{W}/render/{run['id']}/inputs", headers=wauth()).json()["inputs"]
    got = {i["kind"]: i["asset_id"] for i in inputs}
    assert got == {"source": new_source["id"], "analysis": analysis["id"], "hook_audio": hook["id"]}


def test_e9_variety_render_inputs_have_no_hook_audio(api, db):
    job, _, run = rendering(db, format="variety")
    db.add_asset(job, "source")
    db.add_asset(job, "hook_audio", mime="audio/wav")
    claim(api)
    inputs = api.get(f"{W}/render/{run['id']}/inputs", headers=wauth()).json()["inputs"]
    assert [i["kind"] for i in inputs] == ["source"]


# === W-07 산출물(E7) =============================================================


def test_w07_creates_pending_assets_with_server_paths(api, db):
    job = preparing(db)
    claim(api)
    r = outputs(api, "prepare", job["id"], PREPARE_ITEMS)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    items = r.json()["items"]
    assert [i["kind"] for i in items] == ["source", "analysis", "sheet"]
    rows = {a["id"]: a for a in db.assets}
    for it in items:
        a = rows[it["asset_id"]]
        assert a["status"] == "pending" and a["created_by"] == WORKER_A
        assert a["render_run_id"] is None
        assert a["storage_path"].startswith(f"{WS}/{job['id']}/{it['asset_id']}.")
        assert it["upload_url"].startswith(f"{STORAGE}/object/upload/sign/production/")
        exp = datetime.fromisoformat(it["expires_at"]) - datetime.now(UTC)
        assert timedelta(hours=1, minutes=59) <= exp <= timedelta(hours=2, minutes=1)
    assert rows[items[1]["asset_id"]]["storage_path"].endswith(".json")
    assert rows[items[0]["asset_id"]]["duration_sec"] == 60.0


def test_w07_render_outputs_bound_to_run(api, db):
    _, _, run = rendering(db)
    claim(api)
    r = outputs(api, "render", run["id"], [*RENDER_ITEMS, item("hook_audio", "audio/wav")])
    assert r.status_code == 200
    assert all(a["render_run_id"] == run["id"] for a in db.assets)


@pytest.mark.parametrize(
    ("kind", "bad"),
    [
        ("prepare", item("output_mp4", "video/mp4")),
        ("prepare", item("hook_audio", "audio/wav")),
        ("render", item("sheet", "image/jpeg")),
        ("render", item("source_upload", "video/mp4")),
    ],
)
def test_w07_kind_not_allowed_for_task_is_400(api, db, kind, bad):
    if kind == "prepare":
        task_id = preparing(db)["id"]
    else:
        task_id = rendering(db)[2]["id"]
    claim(api)
    r = outputs(api, kind, task_id, [bad])
    assert r.status_code == 400
    assert not [a for a in db.assets if a["kind"] == bad["kind"] and a["status"] == "pending"]


def test_w07_variety_render_rejects_hook_audio_and_mime_mismatch(api, db):
    _, _, run = rendering(db, format="variety")
    claim(api)
    assert outputs(api, "render", run["id"], [item("hook_audio", "audio/wav")]).status_code == 400
    r = outputs(api, "render", run["id"], [item("output_mp4", "video/webm")])
    assert r.status_code == 400 and r.json()["field"] == "items.0.mime"


def test_e7_pending_cap_and_sheet_cap(api, db):
    job = preparing(db)
    claim(api)
    sheets = [item("sheet", "image/jpeg") for _ in range(200)]
    assert outputs(api, "prepare", job["id"], sheets).status_code == 200
    r = outputs(api, "prepare", job["id"], [item("sheet", "image/jpeg")])
    assert r.status_code == 400  # sheet 200 초과
    assert outputs(api, "prepare", job["id"], [item("source", "video/mp4")] * 10).status_code == 200
    r = outputs(api, "prepare", job["id"], [item("analysis", "application/json")])
    assert r.status_code == 400  # pending 210 초과


def test_w07_size_over_limit_is_400(api, db):
    job = preparing(db)
    claim(api)
    big = item("source", "video/mp4", size=524_288_001)
    assert outputs(api, "prepare", job["id"], [big]).status_code == 400


# === W-08 진행(E3·E4) ============================================================


def test_w08_updates_render_progress_and_heartbeat(api, db):
    _, _, run = rendering(db)
    claim(api)
    db.heartbeats.clear()
    r = api.post(
        f"{W}/render/{run['id']}/progress",
        json={"stage": "encode", "progress_pct": 40},
        headers=wauth(),
    )
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert run["progress_pct"] == 40 and run["progress_stage"] == "encode"
    assert db.heartbeats[0]["worker_id"] == WORKER_A


def test_w08_prepare_progress_touches_job_updated_at(api, db):
    job = preparing(db)
    claim(api)
    job["updated_at"] = ago(minutes=2)
    r = api.post(
        f"{W}/prepare/{job['id']}/progress",
        json={"stage": "extract", "progress_pct": 10},
        headers=wauth(),
    )
    assert r.status_code == 200
    assert datetime.fromisoformat(job["updated_at"]) > datetime.now(UTC) - timedelta(seconds=30)


def test_e3_late_progress_after_3_minutes_is_409_and_job_failed(api, db):
    job, _, run = rendering(db)
    claim(api)
    run["updated_at"] = ago(minutes=4)
    run["started_at"] = ago(minutes=5)
    r = api.post(
        f"{W}/render/{run['id']}/progress",
        json={"stage": "encode", "progress_pct": 50},
        headers=wauth(),
    )
    assert r.status_code == 409
    assert run["status"] == "failed" and run["error_code"] == "worker_offline"
    assert db.job(job["id"])["status"] == "failed"


def test_w08_invalid_stage_or_pct_is_400(api, db):
    _, _, run = rendering(db)
    claim(api)
    for body in ({"stage": "upload", "progress_pct": 101}, {"stage": "x", "progress_pct": 1}):
        r = api.post(f"{W}/render/{run['id']}/progress", json=body, headers=wauth())
        assert r.status_code == 400


# === W-09 완료·실패(E6) ==========================================================


def test_w09_prepare_done_moves_to_review_with_first_revision(api, db):
    job = preparing(db)
    claim(api)
    ids = upload_all(db, outputs(api, "prepare", job["id"], PREPARE_ITEMS))
    extra = outputs(api, "prepare", job["id"], [item("sheet", "image/jpeg")]).json()["items"][0]
    extra_row = next(a for a in db.assets if a["id"] == extra["asset_id"])
    db.objects[extra_row["storage_path"]] = 10
    meta = {"duration_sec": 60.0, "width": 1920, "height": 1080, "has_audio": True}
    r = finish(api, "prepare", job["id"], status="done", asset_ids=ids, meta=meta)
    assert r.status_code == 200 and r.json() == {"task": {"status": "done"}}
    j = db.job(job["id"])
    assert j["status"] == "review" and j["source_meta"] == meta
    rev = next(r for r in db.revisions if r["id"] == j["current_revision_id"])
    assert rev["rev_no"] == 1 and rev["spec"] == {} and rev["validation"]["errors"]
    assert all(a["status"] == "ready" for a in db.assets if a["id"] in ids)
    # E6: 목록에 없는 pending 산출물은 행·객체 모두 지운다
    assert extra_row not in db.assets and extra_row["storage_path"] not in db.objects
    assert (
        finish(api, "prepare", job["id"], status="done", asset_ids=ids, meta=META).status_code
        == 409
    )


def test_w09_prepare_missing_required_asset_is_400(api, db):
    job = preparing(db)
    claim(api)
    ids = upload_all(db, outputs(api, "prepare", job["id"], PREPARE_ITEMS[:2]))
    r = finish(api, "prepare", job["id"], status="done", asset_ids=ids, meta=META)
    assert r.status_code == 400 and r.json()["field"] == "asset_ids"
    assert db.job(job["id"])["status"] == "preparing"


def test_w09_object_missing_or_size_mismatch_is_400(api, db):
    job = preparing(db)
    claim(api)
    ids = upload_all(db, outputs(api, "prepare", job["id"], PREPARE_ITEMS))
    path = next(a for a in db.assets if a["id"] == ids[0])["storage_path"]
    db.objects[path] = 9
    assert (
        finish(api, "prepare", job["id"], status="done", asset_ids=ids, meta=META).status_code
        == 400
    )
    del db.objects[path]
    assert (
        finish(api, "prepare", job["id"], status="done", asset_ids=ids, meta=META).status_code
        == 400
    )


def test_e6_assets_must_be_pending_own_and_of_this_task(api, db):
    job = preparing(db)
    claim(api)
    ids = upload_all(db, outputs(api, "prepare", job["id"], PREPARE_ITEMS))
    user_asset = db.add_asset(job, "sheet", status="pending", mime="image/jpeg")  # 사용자 생성
    db.objects[user_asset["storage_path"]] = 1000
    r = finish(
        api, "prepare", job["id"], status="done", asset_ids=[*ids, user_asset["id"]], meta=META
    )
    assert r.status_code == 400
    other = db.add_job(status="preparing")
    foreign = db.add_asset(other, "sheet", status="pending", created_by=WORKER_A)
    r = finish(api, "prepare", job["id"], status="done", asset_ids=[*ids, foreign["id"]], meta=META)
    assert r.status_code == 400
    ready = db.add_asset(job, "sheet", created_by=WORKER_A)
    r = finish(api, "prepare", job["id"], status="done", asset_ids=[*ids, ready["id"]], meta=META)
    assert r.status_code == 400


def test_w09_render_done_moves_to_inspect_and_links_assets(api, db):
    job, _, run = rendering(db)
    claim(api)
    ids = upload_all(db, outputs(api, "render", run["id"], RENDER_ITEMS))
    r = finish(api, "render", run["id"], status="done", asset_ids=ids)
    assert r.status_code == 200
    assert run["status"] == "done" and run["progress_pct"] == 100
    assert {run["mp4_asset_id"], run["report_asset_id"]} == set(ids)
    assert db.job(job["id"])["status"] == "inspect"


def test_w09_render_done_requires_mp4_and_report(api, db):
    _, _, run = rendering(db)
    claim(api)
    ids = upload_all(db, outputs(api, "render", run["id"], RENDER_ITEMS[:1]))
    assert finish(api, "render", run["id"], status="done", asset_ids=ids).status_code == 400


@pytest.mark.parametrize("code", ["hook_too_long", "text_too_long", "tts_failed"])
def test_w09_review_return_codes_send_job_back_to_review(api, db, code):
    job, rev, run = rendering(db)
    claim(api)
    pending = outputs(api, "render", run["id"], RENDER_ITEMS[:1]).json()["items"][0]
    r = finish(api, "render", run["id"], status="failed", error_stage="audio", error_code=code)
    assert r.status_code == 200 and r.json()["task"]["status"] == "failed"
    j = db.job(job["id"])
    assert j["status"] == "review" and j["failed_stage"] is None
    assert j["current_revision_id"] == rev["id"] and rev["spec"] == good_spec()  # 편집안 보존
    assert run["status"] == "failed" and run["error_code"] == code
    assert not [a for a in db.assets if a["id"] == pending["asset_id"]]  # 실패면 pending 정리


def test_w09_render_failed_other_code_fails_job(api, db):
    job, _, run = rendering(db)
    claim(api)
    r = finish(
        api, "render", run["id"], status="failed", error_stage="render", error_code="render_failed"
    )
    assert r.status_code == 200
    j = db.job(job["id"])
    assert (j["status"], j["failed_stage"], j["error_code"]) == (
        "failed",
        "render",
        "render_failed",
    )


def test_w09_prepare_failed(api, db):
    job = preparing(db)
    claim(api)
    r = finish(
        api,
        "prepare",
        job["id"],
        status="failed",
        error_stage="prepare",
        error_code="range_invalid",
    )
    assert r.status_code == 200
    assert db.job(job["id"])["failed_stage"] == "prepare"


@pytest.mark.parametrize(
    ("kind", "body"),
    [
        ("render", {"status": "failed", "error_stage": "render", "error_code": "worker_offline"}),
        ("render", {"status": "failed", "error_stage": "prepare", "error_code": "render_failed"}),
        ("render", {"status": "failed", "error_stage": "render", "error_code": "range_invalid"}),
        ("prepare", {"status": "failed", "error_stage": "render", "error_code": "unknown"}),
        ("prepare", {"status": "failed", "error_stage": "prepare"}),
        ("render", {"status": "done", "asset_ids": [], "error_code": "unknown"}),
        ("render", {"status": "failed", "error_stage": "render", "error_code": "x" * 41}),
    ],
)
def test_e6_error_stage_and_code_are_validated_per_kind(api, db, kind, body):
    task_id = preparing(db)["id"] if kind == "prepare" else rendering(db)[2]["id"]
    claim(api)
    r = finish(api, kind, task_id, **body)
    assert r.status_code == 400
    assert "finish" not in db.rpc_calls


def test_w09_variety_has_no_hook_too_long(api, db):
    _, _, run = rendering(db, format="variety")
    claim(api)
    r = finish(
        api, "render", run["id"], status="failed", error_stage="audio", error_code="hook_too_long"
    )
    assert r.status_code == 400


def test_full_flow_prepare_then_render(api, db, make_token):
    """prepare → (승인 리비전 준비) → A-15 → render → inspect."""
    job = preparing(db)
    claim(api)
    ids = upload_all(db, outputs(api, "prepare", job["id"], PREPARE_ITEMS))
    assert (
        finish(api, "prepare", job["id"], status="done", asset_ids=ids, meta=META).status_code
        == 200
    )
    rev = next(r for r in db.revisions if r["job_id"] == job["id"])
    rev.update(spec=good_spec(), approved_at=datetime.now(UTC).isoformat())
    auth = {"Authorization": f"Bearer {make_token()}", "Idempotency-Key": "flow-1"}
    r = api.post(
        f"/v1/production-jobs/{job['id']}/render-runs",
        json={"revision_id": rev["id"], "lang": "ko"},
        headers=auth,
    )
    assert r.status_code == 202
    task = claim(api).json()["task"]
    assert task["kind"] == "render" and task["job_id"] == job["id"]
    out = upload_all(db, outputs(api, "render", task["id"], RENDER_ITEMS))
    assert finish(api, "render", task["id"], status="done", asset_ids=out).status_code == 200
    assert db.job(job["id"])["status"] == "inspect"


# === 로그: 서명 URL 토큰 0건 =====================================================


def test_logs_never_contain_signed_url_tokens(api, db, caplog):
    stream = io.StringIO()
    handler = setup_logging(stream)
    caplog.set_level(logging.DEBUG)
    try:
        job = preparing(db)
        claim(api)
        api.get(f"{W}/prepare/{job['id']}/inputs", headers=wauth())
        ids = upload_all(db, outputs(api, "prepare", job["id"], PREPARE_ITEMS))
        finish(api, "prepare", job["id"], status="done", asset_ids=ids, meta=META)
    finally:
        handler.setStream(sys.stderr)
    assert len(db.issued_tokens) == 4
    logged = caplog.text + stream.getvalue()
    assert "제작 task" in logged
    for token in db.issued_tokens:
        assert token not in logged and token.rsplit(".", 1)[1] not in logged
    assert "token=" not in logged and str(uuid.UUID(WS)) + "/" not in logged


# === 리뷰 반영(1~5) ==============================================================


def test_review1_prepare_done_needs_exactly_one_source_and_analysis(api, db):
    job = preparing(db)
    claim(api)
    items = [*PREPARE_ITEMS, item("source", "video/mp4")]
    ids = upload_all(db, outputs(api, "prepare", job["id"], items))
    r = finish(api, "prepare", job["id"], status="done", asset_ids=ids, meta=META)
    assert r.status_code == 400 and r.json()["field"] == "asset_ids"
    assert db.job(job["id"])["status"] == "preparing"


def test_review1_rpc_unique_violation_is_409_not_503(api, db, mock_supabase):
    import httpx

    from tests.production.test_jobs_api import REST

    job = preparing(db)
    claim(api)
    ids = upload_all(db, outputs(api, "prepare", job["id"], PREPARE_ITEMS))
    mock_supabase.post(f"{REST}/rpc/finish_production_task").mock(
        return_value=httpx.Response(409, json={"code": "23505", "message": "duplicate key"})
    )
    r = finish(api, "prepare", job["id"], status="done", asset_ids=ids, meta=META)
    assert r.status_code == 409 and r.json()["code"] == "CONFLICT"
    assert "duplicate" not in r.text


def test_review2_prepare_done_requires_meta(api, db):
    job = preparing(db)
    claim(api)
    ids = upload_all(db, outputs(api, "prepare", job["id"], PREPARE_ITEMS))
    r = finish(api, "prepare", job["id"], status="done", asset_ids=ids)
    assert r.status_code == 400 and r.json()["field"] == "meta"
    assert "finish" not in db.rpc_calls


def test_review3_recovery_claim_refreshes_updated_at(api, db):
    job = preparing(db)
    claim(api)
    job["updated_at"] = ago(minutes=2)
    assert claim(api).json()["task"]["id"] == job["id"]
    assert datetime.fromisoformat(job["updated_at"]) > datetime.now(UTC) - timedelta(seconds=30)


def test_review4_expiry_deletes_pending_outputs_and_objects(api, db, make_token):
    job, _, run = rendering(db)
    claim(api)
    out = outputs(api, "render", run["id"], RENDER_ITEMS).json()["items"]
    paths = [a["storage_path"] for a in db.assets if a["render_run_id"] == run["id"]]
    for p in paths:
        db.objects[p] = 10
    kept = db.add_asset(job, "source")  # ready 입력은 그대로
    run["updated_at"] = ago(minutes=4)
    run["started_at"] = ago(minutes=5)
    r = api.get(
        f"/v1/production-jobs/{job['id']}", headers={"Authorization": f"Bearer {make_token()}"}
    )
    assert r.json()["job"]["error_code"] == "worker_offline"
    assert not [a for a in db.assets if a["id"] in {o["asset_id"] for o in out}]
    assert all(p not in db.objects for p in paths)
    assert kept in db.assets


def test_review4_expiry_object_delete_failure_is_ignored(api, db, mock_supabase, caplog):
    import httpx

    job = preparing(db)
    claim(api)
    outputs(api, "prepare", job["id"], PREPARE_ITEMS)
    job["updated_at"] = ago(minutes=4)
    mock_supabase.delete(url__startswith=f"{STORAGE}/object/production/").mock(
        return_value=httpx.Response(500, json={"message": "boom"})
    )
    caplog.set_level(logging.WARNING)
    r = claim(api, WORKER_B)  # W-05 앞 만료 평가
    assert r.status_code == 204
    assert db.job(job["id"])["error_code"] == "worker_offline"
    assert "정리 실패" in caplog.text and f"{WS}/" not in caplog.text


@pytest.mark.parametrize(
    ("kind", "mime", "size", "ok"),
    [
        ("sheet", "image/jpeg", 5 * 1024 * 1024, True),
        ("sheet", "image/jpeg", 5 * 1024 * 1024 + 1, False),
        ("analysis", "application/json", 50 * 1024 * 1024 + 1, False),
        ("source", "video/mp4", 524_288_000, True),
    ],
)
def test_review5_output_size_cap_per_kind(api, db, kind, mime, size, ok):
    job = preparing(db)
    claim(api)
    r = outputs(api, "prepare", job["id"], [item(kind, mime, size=size)])
    assert (r.status_code == 200) is ok
    if not ok:
        assert r.json()["field"] == "items.0.size_bytes"


def test_review5_report_size_cap(api, db):
    _, _, run = rendering(db)
    claim(api)
    big = item("report", "application/json", size=50 * 1024 * 1024 + 1)
    assert outputs(api, "render", run["id"], [big]).status_code == 400


def test_v4_variety_prepare_done_first_revision_uses_variety_validation(api, db):
    job = preparing(db, format="variety", preset_version="variety-1080-v1")
    claim(api)
    ids = upload_all(db, outputs(api, "prepare", job["id"], PREPARE_ITEMS))
    r = finish(api, "prepare", job["id"], status="done", asset_ids=ids, meta=META)
    assert r.status_code == 200
    j = db.job(job["id"])
    rev = next(r for r in db.revisions if r["id"] == j["current_revision_id"])
    assert rev["spec"] == {}
    paths = {e["path"] for e in rev["validation"]["errors"]}
    assert {"header", "cuts"} <= paths and "shots" not in paths  # 카테고리형 아님
    assert all(e["code"].startswith("schema.") for e in rev["validation"]["errors"])
