"""task-028 인수 테스트(API 쪽): CAT-01~07을 한 작업의 시간순 시나리오로 확인한다.

가짜 PostgREST·Storage(test_render_runs의 ProdDB)에 사용자 API(A-09~A-17)와 워커 API(W-05~W-09)를
실제 라우터로 호출한다. 실제 DB·ffmpeg는 실환경 실행(NOW.md 표)과 워커 acceptance가 맡는다.
근거: Nomadroom_Category_Shorts_PRD.md#5 인수 테스트 표.
"""

import copy
import json
import uuid
from collections.abc import Iterator

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import JWKS_URL, make_settings
from tests.production import test_render_runs as rr
from tests.production.test_jobs_api import (
    CAND,
    REST,
    URL,
    WS,
    _params,
    _select,
    cur_updated_at,
    job_row,
)
from tests.production.test_render_runs import ProdDB, ago, install_prod, wauth
from tests.production.test_worker_production import (
    PREPARE_ITEMS,
    RENDER_ITEMS,
    W,
    claim,
    finish,
    item,
    outputs,
    upload_all,
)

db = rr.db  # 픽스처 재사용
auth = rr.auth


def _jobs_route(request: httpx.Request, db: ProdDB) -> httpx.Response:
    """install_prod는 production_jobs INSERT(A-09)를 다루지 않아 이 파일에서 보탠다."""
    p = _params(request)
    sel = {"select": p.get("select", "*")}
    filt = {k: v for k, v in p.items() if k != "select"}
    if request.method == "GET":
        return httpx.Response(200, json=_select(db.jobs, p))
    if request.method == "PATCH":
        hit = [r for r in db.jobs if _select([r], filt)]
        for r in hit:
            r.update(json.loads(request.content))
        return httpx.Response(200, json=_select(hit, sel))
    body = json.loads(request.content)
    if any(
        j["workspace_id"] == body["workspace_id"]
        and j["idempotency_key"] == body["idempotency_key"]
        for j in db.jobs
    ):
        err = {"code": "23505", "message": 'duplicate key value violates unique constraint "x"'}
        return httpx.Response(409, json=err)
    new = job_row()
    new.update(body)
    db.jobs.append(new)
    return httpx.Response(201, json=_select([new], sel))


@pytest.fixture
def api(mock_supabase: respx.MockRouter, jwks_payload: dict, db: ProdDB) -> Iterator[TestClient]:
    mock_supabase.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_payload))
    mock_supabase.get(f"{REST}/workspace_members").mock(
        return_value=httpx.Response(200, json=[{"workspace_id": WS}])
    )
    install_prod(mock_supabase, db)
    mock_supabase.route(url=f"{REST}/production_jobs").mock(  # 같은 패턴은 나중 등록이 대체한다
        side_effect=lambda r: _jobs_route(r, db)
    )
    for name, fn in (
        ("save_production_revision", db.save_revision),
        ("approve_production_revision", db.approve_revision),
    ):  # A-12·A-13 RPC도 install_prod에 없어 보탠다
        mock_supabase.post(f"{REST}/rpc/{name}").mock(
            side_effect=lambda r, f=fn: f(json.loads(r.content))
        )
    with TestClient(create_app(make_settings()), raise_server_exceptions=False) as c:
        yield c


MB = 1024 * 1024
HOOK_ASSET = "hook-asset-1"


def spec(duration: float = 15.0, hook_asset: str = HOOK_ASSET, **over) -> dict:
    s = {
        "lang": "ko",
        "header": {"lines": ["제목 첫줄", "제목 둘째줄"]},
        "hook": {"text": "이게 가능하다고?", "audio_asset_id": hook_asset},
        "duration": duration,
        "shots": [
            {"start": 0, "end": 7, "scale": 1.0, "y": 0},
            {"start": 7, "end": duration, "scale": 1.3, "y": -120},
        ],
        "items": [
            {"start": 0, "end": 2.0, "kind": "white", "text": "이게 가능하다고?"},
            {"start": 2.0, "end": 8, "kind": "paren", "text": "(합성 화면)"},
            {"start": 8, "end": duration, "kind": "emph", "text": "끝까지 보세요"},
        ],
    }
    s.update(over)
    return s


def post(api, auth, path: str, **kw):
    return api.post(f"{URL}{path}", headers={**auth, **kw.pop("headers", {})}, **kw)


def put_spec(api, auth, jid: str, s: dict, base: int):
    body = {"spec": s, "base_rev_no": base, "base_updated_at": cur_updated_at(api, auth, jid)}
    return api.put(f"{URL}/{jid}/revision", json=body, headers=auth)


def make_asset_ready(api, auth, db: ProdDB, jid: str, kind: str, mime: str) -> str:
    r = post(api, auth, f"/{jid}/uploads", json={"kind": kind, "size_bytes": 5 * MB, "mime": mime})
    assert r.status_code == 201, r.text
    aid = r.json()["asset"]["id"]
    row = next(a for a in db.assets if a["id"] == aid)
    db.objects[row["storage_path"]] = row["size_bytes"]
    assert post(api, auth, f"/{jid}/uploads/{aid}/complete").status_code == 200
    return aid


def start_job(api, auth, db: ProdDB, key: str = "cat-job", start: float = 30, length: float = 15):
    if not db.candidates:
        db.candidates.append({"id": CAND, "workspace_id": WS})
    r = post(
        api,
        auth,
        "",
        headers={"Idempotency-Key": key},
        json={
            "title": "저장된 소재",
            "candidate_id": CAND,
            "source_kind": "upload",
            "rights_confirmed": True,
            "source_start_sec": start,
            "segment_len_sec": length,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["job"]


def prepare_to_review(api, auth, db: ProdDB, jid: str, duration: float = 15.0) -> dict:
    make_asset_ready(api, auth, db, jid, "source_upload", "video/mp4")
    assert post(api, auth, f"/{jid}/prepare").status_code == 202
    task = claim(api).json()["task"]
    items = [item("source", "video/mp4", duration_sec=duration), *PREPARE_ITEMS[1:]]
    ids = upload_all(db, outputs(api, "prepare", jid, items))
    meta = {"duration_sec": duration, "width": 1280, "height": 720, "has_audio": True}
    r = finish(api, "prepare", jid, status="done", asset_ids=ids, meta=meta)
    assert r.status_code == 200, r.text
    return task


def render_done(api, db: ProdDB, run_id: str) -> None:
    ids = upload_all(db, outputs(api, "render", run_id, RENDER_ITEMS))
    assert finish(api, "render", run_id, status="done", asset_ids=ids).status_code == 200


def request_run(api, auth, jid: str, rev_id: str, key: str):
    return post(
        api,
        auth,
        f"/{jid}/render-runs",
        headers={"Idempotency-Key": key},
        json={"revision_id": rev_id, "lang": "ko"},
    )


def cooldown(db: ProdDB) -> None:
    for r in db.runs:  # A-15 60초 제한(워크스페이스 단위)을 지난 것으로
        r["created_at"] = ago(minutes=3)


def fail_render(api, run_id: str, stage: str, code: str) -> None:
    r = finish(api, "render", run_id, status="failed", error_stage=stage, error_code=code)
    assert r.status_code == 200, r.text


def approved_job(api, auth, db: ProdDB):
    job = start_job(api, auth, db)
    prepare_to_review(api, auth, db, job["id"])
    hook = make_asset_ready(api, auth, db, job["id"], "hook_audio", "audio/wav")
    assert put_spec(api, auth, job["id"], spec(hook_asset=hook), 1).status_code == 200
    ap = post(api, auth, f"/{job['id']}/revision/approve", json={"rev_no": 1})
    assert ap.status_code == 200, ap.text
    return job, ap.json()["revision"]["id"], hook


def claim_render(api, run_id: str) -> dict:
    task = claim(api).json()["task"]
    assert task["kind"] == "render" and task["id"] == run_id
    return task


# === CAT-01: 저장된 소재에서 시작 ====================================================


def test_cat01_candidate_id_title_and_source_reach_the_worker_task(api, auth, db):
    job = start_job(api, auth, db)
    assert job["candidate_id"] == CAND and job["title"] == "저장된 소재"
    assert job["format"] == "category" and job["status"] == "draft"
    task = prepare_to_review(api, auth, db, job["id"])
    assert task["job_id"] == job["id"] and task["kind"] == "prepare"
    assert task["source_kind"] == "upload"  # 원본 참조
    detail = api.get(f"{URL}/{job['id']}", headers=auth).json()
    assert detail["job"]["candidate_id"] == CAND and detail["job"]["title"] == "저장된 소재"
    assert detail["job"]["status"] == "review"


def test_cat01_same_start_key_does_not_create_second_job(api, auth, db):
    first = start_job(api, auth, db, key="same-start")
    again = post(
        api,
        auth,
        "",
        headers={"Idempotency-Key": "same-start"},
        json={
            "title": "x",
            "candidate_id": CAND,
            "source_kind": "upload",
            "rights_confirmed": True,
            "source_start_sec": 0,
            "segment_len_sec": 15,
        },
    )
    assert again.status_code == 200 and again.json()["job"]["id"] == first["id"]
    assert len(db.jobs) == 1


# === CAT-02: 30초 지점부터 15초 ======================================================


def test_cat02_source_start_30_is_recorded_and_timeline_is_zero_based(api, auth, db):
    job = start_job(api, auth, db, start=30, length=15)
    assert job["source_start_sec"] == 30 and job["segment_len_sec"] == 15
    task = prepare_to_review(api, auth, db, job["id"], duration=15.0)
    assert task["source_start_sec"] == 30 and task["segment_len_sec"] == 15  # 워커가 받는 값
    rev = api.get(f"{URL}/{job['id']}/revision", headers=auth).json()["revision"]
    r = put_spec(api, auth, job["id"], spec(15.0), rev["rev_no"])
    assert r.status_code == 200 and r.json()["revision"]["validation"]["errors"] == []
    saved = r.json()["revision"]["spec"]  # 타임라인은 0부터 구간 길이(15초)까지
    assert saved["shots"][0]["start"] == 0 and saved["shots"][-1]["end"] == 15.0


def test_cat02_timeline_longer_than_segment_is_flagged(api, auth, db):
    job = start_job(api, auth, db)
    prepare_to_review(api, auth, db, job["id"], duration=15.0)
    r = put_spec(api, auth, job["id"], spec(16.0), 1)  # 15초 구간에 16초 편집안
    assert r.status_code == 200
    assert "duration.range" in [e["code"] for e in r.json()["revision"]["validation"]["errors"]]


def test_cat02_negative_start_is_400(api, auth, db):
    r = post(
        api,
        auth,
        "",
        headers={"Idempotency-Key": "neg"},
        json={
            "title": "t",
            "source_kind": "upload",
            "rights_confirmed": True,
            "source_start_sec": -1,
            "segment_len_sec": 15,
        },
    )
    assert r.status_code == 400


# === CAT-03: 구도 공백·자막 겹침 =====================================================


def test_cat03_gap_and_overlap_are_located_and_approval_is_blocked(api, auth, db):
    job = start_job(api, auth, db)
    prepare_to_review(api, auth, db, job["id"])
    bad = spec(
        shots=[
            {"start": 0, "end": 6, "scale": 1.0, "y": 0},
            {"start": 7, "end": 15, "scale": 1.0, "y": 0},
        ],
        items=[
            {"start": 0, "end": 3, "kind": "white", "text": "a"},
            {"start": 2, "end": 8, "kind": "white", "text": "겹침"},
            {"start": 8, "end": 15, "kind": "white", "text": "끝"},
        ],
    )
    r = put_spec(api, auth, job["id"], bad, 1)
    assert r.status_code == 200  # 의미 오류가 있어도 저장
    errs = {(e["code"], e["path"]) for e in r.json()["revision"]["validation"]["errors"]}
    assert ("shots.gap", "shots.1") in errs and ("items.overlap", "items.1") in errs
    ap = post(api, auth, f"/{job['id']}/revision/approve", json={"rev_no": 1})
    assert ap.status_code == 400 and ap.json()["code"] == "VALIDATION"
    assert {e["path"] for e in ap.json()["errors"]} >= {"shots.1", "items.1"}
    rev = api.get(f"{URL}/{job['id']}/revision", headers=auth).json()["revision"]
    assert request_run(api, auth, job["id"], rev["id"], "k-blocked").status_code == 400
    assert db.runs == []  # 렌더 요청도 막힌다(승인 리비전이 없다)


def test_cat03_fix_then_approve_succeeds(api, auth, db):
    job = start_job(api, auth, db)
    prepare_to_review(api, auth, db, job["id"])
    put_spec(api, auth, job["id"], spec(shots=[{"start": 0, "end": 6, "scale": 1.0, "y": 0}]), 1)
    assert post(api, auth, f"/{job['id']}/revision/approve", json={"rev_no": 1}).status_code == 400
    assert (
        put_spec(api, auth, job["id"], spec(), 1).json()["revision"]["validation"]["errors"] == []
    )
    assert post(api, auth, f"/{job['id']}/revision/approve", json={"rev_no": 1}).status_code == 200


# === CAT-04: 첫 자막에 안 들어가는 훅 음성 ===========================================


def test_cat04_hook_too_long_returns_to_review_and_keeps_edit(api, auth, db):
    job, rev_id, hook = approved_job(api, auth, db)
    run = request_run(api, auth, job["id"], rev_id, "k1").json()["render_run"]
    saved_spec = copy.deepcopy(claim_render(api, run["id"])["spec"])
    fail_render(api, run["id"], "audio", "hook_too_long")
    detail = api.get(f"{URL}/{job['id']}", headers=auth).json()
    assert detail["job"]["status"] == "review"  # 편집안 단계로 복귀
    assert detail["latest_run"]["status"] == "failed"
    assert detail["latest_run"]["error_code"] == "hook_too_long"
    got = api.get(f"{URL}/{job['id']}/revision", headers=auth).json()["revision"]["spec"]
    assert got == saved_spec
    assert saved_spec["hook"] == {"text": "이게 가능하다고?", "audio_asset_id": hook}
    retry = post(api, auth, f"/{job['id']}/render-runs/{run['id']}/retry")
    assert retry.status_code == 409  # 재시도 불가(편집 후 A-15)


def test_cat04_edit_hook_then_render_again(api, auth, db):
    job, rev_id, _ = approved_job(api, auth, db)
    run = request_run(api, auth, job["id"], rev_id, "k1").json()["render_run"]
    claim_render(api, run["id"])
    fail_render(api, run["id"], "audio", "hook_too_long")
    new_hook = make_asset_ready(api, auth, db, job["id"], "hook_audio", "audio/wav")
    r = put_spec(api, auth, job["id"], spec(hook_asset=new_hook), 1)
    assert r.status_code == 200 and r.json()["revision"]["rev_no"] == 2  # 승인본 수정 → 새 리비전
    ap = post(api, auth, f"/{job['id']}/revision/approve", json={"rev_no": 2}).json()["revision"]
    cooldown(db)
    again = request_run(api, auth, job["id"], ap["id"], "k2")
    assert again.status_code == 202 and again.json()["render_run"]["attempt"] == 1


# === CAT-05: 원본 음성 있음/없음 (소리 자체는 워커 acceptance) =========================


def test_cat05_render_inputs_expose_only_user_hook_audio_and_source(api, auth, db):
    job, rev_id, hook = approved_job(api, auth, db)
    run = request_run(api, auth, job["id"], rev_id, "k1").json()["render_run"]
    claim_render(api, run["id"])
    inputs = api.get(f"{W}/render/{run['id']}/inputs", headers=wauth()).json()["inputs"]
    kinds = {i["kind"]: i["asset_id"] for i in inputs}
    assert set(kinds) == {"source", "analysis", "hook_audio"} and kinds["hook_audio"] == hook
    assert db.job(job["id"])["source_meta"]["has_audio"] is True


def test_cat05_silent_source_meta_is_recorded(api, auth, db):
    job = start_job(api, auth, db)
    make_asset_ready(api, auth, db, job["id"], "source_upload", "video/mp4")
    post(api, auth, f"/{job['id']}/prepare")
    claim(api)
    ids = upload_all(db, outputs(api, "prepare", job["id"], PREPARE_ITEMS))
    meta = {"duration_sec": 15.0, "width": 1280, "height": 720, "has_audio": False}
    r = finish(api, "prepare", job["id"], status="done", asset_ids=ids, meta=meta)
    assert r.status_code == 200
    assert db.job(job["id"])["source_meta"]["has_audio"] is False


# === CAT-06: 산출물 검수 흐름(실제 MP4 스트림은 워커 acceptance·실환경) =================


def test_cat06_inspect_requires_ready_mp4_and_review_approval_completes(api, auth, db):
    job, rev_id, _ = approved_job(api, auth, db)
    run = request_run(api, auth, job["id"], rev_id, "k1").json()["render_run"]
    claim_render(api, run["id"])
    assert post(api, auth, f"/{job['id']}/review/approve").status_code == 409  # 렌더 중
    render_done(api, db, run["id"])
    detail = api.get(f"{URL}/{job['id']}", headers=auth).json()
    assert detail["job"]["status"] == "inspect"
    assert {"output_mp4", "report"} <= {a["kind"] for a in detail["assets"]}
    mp4 = next(a for a in detail["assets"] if a["kind"] == "output_mp4")
    dl = api.get(f"{URL}/{job['id']}/assets/{mp4['id']}/download-url", headers=auth)
    assert dl.status_code == 200 and dl.json()["url"]
    done = post(api, auth, f"/{job['id']}/review/approve")
    assert done.status_code == 200 and done.json()["job"]["status"] == "done"
    assert done.json()["job"]["completed_at"]


def test_cat06_finish_done_without_output_mp4_is_400(api, auth, db):
    job, rev_id, _ = approved_job(api, auth, db)
    run = request_run(api, auth, job["id"], rev_id, "k1").json()["render_run"]
    claim_render(api, run["id"])
    ids = upload_all(db, outputs(api, "render", run["id"], [item("report", "application/json")]))
    assert finish(api, "render", run["id"], status="done", asset_ids=ids).status_code == 400
    assert db.job(job["id"])["status"] == "rendering"


# === CAT-07: 중복 요청·실패 후 재시도 ================================================


def test_cat07_double_click_same_key_returns_same_run(api, auth, db):
    job, rev_id, _ = approved_job(api, auth, db)
    first = request_run(api, auth, job["id"], rev_id, "dbl")
    again = request_run(api, auth, job["id"], rev_id, "dbl")
    assert first.status_code == 202 and again.status_code == 200
    assert again.json()["render_run"]["id"] == first.json()["render_run"]["id"]
    assert len(db.runs) == 1


def test_cat07_new_key_while_active_is_409(api, auth, db):
    job, rev_id, _ = approved_job(api, auth, db)
    assert request_run(api, auth, job["id"], rev_id, "a").status_code == 202
    assert request_run(api, auth, job["id"], rev_id, "b").status_code == 409
    assert len(db.runs) == 1


def test_cat07_same_key_on_other_job_is_409(api, auth, db):
    job, rev_id, _ = approved_job(api, auth, db)
    assert request_run(api, auth, job["id"], rev_id, "shared").status_code == 202
    other = db.add_job(status="review")
    rev = db.add_revision(other, approved=True)
    assert request_run(api, auth, other["id"], rev["id"], "shared").status_code == 409


def test_cat07_failed_render_retry_continues_with_attempt_2_and_no_overwrite(api, auth, db):
    job, rev_id, _ = approved_job(api, auth, db)
    run = request_run(api, auth, job["id"], rev_id, "k1").json()["render_run"]
    claim_render(api, run["id"])
    fail_render(api, run["id"], "render", "render_failed")
    assert db.job(job["id"])["status"] == "failed"
    retry = post(api, auth, f"/{job['id']}/render-runs/{run['id']}/retry")
    assert retry.status_code == 202
    body = retry.json()["render_run"]
    assert body["attempt"] == 2 and body["retry_of"] == run["id"]
    assert body["revision_id"] == rev_id  # 같은 승인본으로 이어간다
    again = post(api, auth, f"/{job['id']}/render-runs/{run['id']}/retry")
    assert again.status_code == 409  # 진행 중 재시도 중복 거부
    claim_render(api, body["id"])
    render_done(api, db, body["id"])
    assert db.job(job["id"])["status"] == "inspect"
    mp4s = [a for a in db.assets if a["kind"] == "output_mp4"]
    assert len(mp4s) == 1 and mp4s[0]["render_run_id"] == body["id"]  # 실패 run 산출물과 분리
    assert len({r["id"] for r in db.runs}) == 2


def test_cat07_retry_limit_attempt_3_then_blocked(api, auth, db):
    job, rev_id, _ = approved_job(api, auth, db)
    run = request_run(api, auth, job["id"], rev_id, "k1").json()["render_run"]
    for attempt in (1, 2, 3):
        claim_render(api, run["id"])
        fail_render(api, run["id"], "render", "render_failed")
        r = post(api, auth, f"/{job['id']}/render-runs/{run['id']}/retry")
        if attempt < 3:
            assert r.status_code == 202, r.text
            run = r.json()["render_run"]
        else:
            assert r.status_code == 409  # attempt 상한(3) 초과
    assert uuid.UUID(run["id"]) and run["attempt"] == 3
