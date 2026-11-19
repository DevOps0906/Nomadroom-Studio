"""task-044 쇼핑 워커 API(W-05~W-09): job_kind shopping 재현, claim 쇼핑 보류(045 전),
원본별 prepare 입력·계보(parent) 필수·상한, 전부 끝나야 review.

가짜 RPC는 test_render_runs(000023 claim·finish 본뜸)를 재사용한다. 실제 SQL은 pgTAP
(supabase/tests/production_shopping_api_test.sql)이 검사한다.
"""

import pytest

from tests.production import test_render_runs as rr
from tests.production.test_render_runs import WORKER_A, ProdDB, ago, wauth
from tests.production.test_worker_production import (
    META,
    W,
    claim,
    finish,
    item,
    outputs,
    upload_all,
)

api = rr.api  # 픽스처 재사용
db = rr.db
auth = rr.auth


def shop_preparing(db: ProdDB, n: int = 2, claimed: bool = True, **over) -> tuple[dict, list]:
    job = db.add_job(
        status="preparing",
        kind="shopping",
        format="shopping",
        vertical="product",
        preset_version="shopping-1080-v1",
        claimed_by=WORKER_A if claimed else None,
        updated_at=ago(seconds=1),  # 3분 만료 대상이 아니게
        **over,
    )
    ups = [db.add_asset(job, "source_upload", rights={"basis": "own"}) for _ in range(n)]
    return job, ups


def set_items(parent: str, sheets: int = 1) -> list[dict]:
    return [
        item("source", "video/mp4", duration_sec=20.0, parent_asset_id=parent),
        item("analysis", "application/json", parent_asset_id=parent),
        *[item("sheet", "image/jpeg", parent_asset_id=parent) for _ in range(sheets)],
    ]


# --- W-05 ---------------------------------------------------------------------------


def test_p4_claim_skips_shopping_without_capability(api, db):
    # task-045 R4: 지원 형식을 알리지 않은 워커(구버전)에게는 쇼핑을 새로 주지 않는다
    shop_preparing(db, claimed=False)
    assert claim(api).status_code == 204
    gen = db.add_job(status="preparing")
    db.add_asset(gen, "source_upload")
    r = claim(api)
    assert r.status_code == 200 and r.json()["task"]["job_id"] == gen["id"]


def test_r4_claim_gives_shopping_to_capable_worker(api, db):
    job, _ = shop_preparing(db, claimed=False)
    r = api.post(f"{W}/claim", json={"capabilities": ["shopping"]}, headers=wauth())
    assert r.status_code == 200, r.text
    assert r.json()["task"]["job_id"] == job["id"] and r.json()["task"]["job_kind"] == "shopping"
    assert job["claimed_by"] == WORKER_A


@pytest.mark.parametrize("body", [{"capabilities": ["video"]}, {"formats": ["shopping"]}])
def test_r4_claim_rejects_unknown_capability(api, db, body):
    assert api.post(f"{W}/claim", json=body, headers=wauth()).status_code in (400, 422)


def test_p4_task_out_accepts_shopping_job_kind(api, db):
    # 재시작 복구(이미 이 워커가 수령)는 kind 조건 없이 돌려준다 → TaskOut이 shopping을 받아야 한다
    job, _ = shop_preparing(db)
    r = claim(api)
    assert r.status_code == 200, r.text
    assert r.json()["task"]["job_kind"] == "shopping"
    assert r.json()["task"]["job_id"] == job["id"]


# --- W-06 ---------------------------------------------------------------------------


def test_w06_shopping_prepare_inputs_every_ready_source(api, db):
    job, ups = shop_preparing(db, n=3)
    db.add_asset(job, "source_upload", status="pending")
    r = api.get(f"{W}/prepare/{job['id']}/inputs", headers=wauth())
    assert r.status_code == 200
    got = r.json()["inputs"]
    assert [i["asset_id"] for i in got] == [u["id"] for u in ups]
    assert {i["kind"] for i in got} == {"source_upload"}


# --- W-07 계보·상한 ------------------------------------------------------------------


def test_p1_shopping_outputs_require_parent(api, db):
    job, ups = shop_preparing(db)
    r = outputs(api, "prepare", job["id"], [item("sheet", "image/jpeg")])
    assert r.status_code == 400 and r.json()["field"] == "items.0.parent_asset_id"
    other, other_ups = shop_preparing(db, claimed=False)
    bad = [item("sheet", "image/jpeg", parent_asset_id=other_ups[0]["id"])]
    assert outputs(api, "prepare", job["id"], bad).status_code == 400
    r = outputs(api, "prepare", job["id"], set_items(ups[0]["id"]))
    assert r.status_code == 200
    made = [a for a in db.assets if a["status"] == "pending"]
    assert {a["parent_asset_id"] for a in made} == {ups[0]["id"]}


def test_p1_general_outputs_get_parent_and_url_job_rejects_parent(api, db):
    job = db.add_job(status="preparing", claimed_by=WORKER_A)
    up = db.add_asset(job, "source_upload")
    assert outputs(api, "prepare", job["id"], [item("sheet", "image/jpeg")]).status_code == 200
    assert next(a for a in db.assets if a["kind"] == "sheet")["parent_asset_id"] == up["id"]
    url_job = db.add_job(
        status="preparing",
        claimed_by=WORKER_A,
        source_kind="url",
        source_url="https://youtu.be/abc",
        rights_confirmed=True,
    )
    bad = [item("sheet", "image/jpeg", parent_asset_id=up["id"])]
    r = outputs(api, "prepare", url_job["id"], bad)
    assert r.status_code == 400 and r.json()["field"] == "items.0.parent_asset_id"
    assert outputs(api, "prepare", url_job["id"], [item("sheet", "image/jpeg")]).status_code == 200


def test_p5_shopping_sheet_cap_per_source(api, db):
    job, ups = shop_preparing(db)
    sheets = [item("sheet", "image/jpeg", parent_asset_id=ups[0]["id"]) for _ in range(200)]
    assert outputs(api, "prepare", job["id"], sheets).status_code == 200
    one_more = [item("sheet", "image/jpeg", parent_asset_id=ups[0]["id"])]
    assert outputs(api, "prepare", job["id"], one_more).status_code == 400
    # 다른 원본의 시트는 따로 센다(일반 작업 상한 210을 넘어도 원본 수×202 안이면 허용)
    other = [item("sheet", "image/jpeg", parent_asset_id=ups[1]["id"]) for _ in range(150)]
    assert outputs(api, "prepare", job["id"], other).status_code == 200


# --- W-09 전부 끝나야 review ----------------------------------------------------------


def test_p3_shopping_finish_needs_every_source(api, db):
    job, ups = shop_preparing(db)
    first = upload_all(db, outputs(api, "prepare", job["id"], set_items(ups[0]["id"])))
    r = finish(api, "prepare", job["id"], status="done", asset_ids=first, meta=META)
    assert r.status_code == 400 and job["status"] == "preparing"
    second = upload_all(db, outputs(api, "prepare", job["id"], set_items(ups[1]["id"], 150)))
    ids = first + second  # 원본 2개, 156건(일반 상한 210과 무관하게 나눠 조회)
    r = finish(api, "prepare", job["id"], status="done", asset_ids=ids, meta=META)
    assert r.status_code == 200, r.text
    assert job["status"] == "review"
    assert all(a["status"] == "ready" for a in db.assets if a["id"] in ids)
    rev = next(x for x in db.revisions if x["job_id"] == job["id"])
    assert "assets.required" not in {e["code"] for e in rev["validation"]["errors"]}


def test_p3_shopping_finish_rejects_two_sets_for_one_source(api, db):
    job, ups = shop_preparing(db, n=1)
    a = upload_all(db, outputs(api, "prepare", job["id"], set_items(ups[0]["id"])))
    b = upload_all(db, outputs(api, "prepare", job["id"], set_items(ups[0]["id"])))
    r = finish(api, "prepare", job["id"], status="done", asset_ids=a + b, meta=META)
    assert r.status_code == 400 and job["status"] == "preparing"


# --- task-045 W-06 쇼핑 render 입력·A-15 자산 재확인 ----------------------------------


def shop_render_setup(db: ProdDB) -> tuple[dict, dict, dict]:
    job = db.add_job(
        status="review",
        kind="shopping",
        format="shopping",
        vertical="product",
        preset_version="shopping-1080-v1",
    )
    up = db.add_asset(job, "source_upload", rights={"basis": "own"})
    child = db.add_asset(job, "source", parent_asset_id=up["id"])
    db.add_asset(job, "analysis", parent_asset_id=up["id"])
    img = db.add_asset(job, "image", rights={"basis": "own"})
    bgm = db.add_asset(job, "bgm", rights={"basis": "licensed"})
    narr = [db.add_asset(job, "narration") for _ in range(4)]
    unused = db.add_asset(job, "image", rights={"basis": "own"})
    spec = {
        "cuts": [
            {"source_asset_id": up["id"], "sentence": 1},
            {"source_asset_id": img["id"], "sentence": 2},
        ],
        "bgm_asset_id": bgm["id"],
        "voice": {"narration_asset_ids": [n["id"] for n in narr]},
    }
    rev = db.add_revision(job, approved=True, spec=spec)
    ids = {
        "up": up["id"],
        "child": child["id"],
        "img": img["id"],
        "bgm": bgm["id"],
        "narr": [n["id"] for n in narr],
        "unused": unused["id"],
    }
    return job, rev, ids


def test_r3_shopping_render_inputs_only_spec_refs(api, db):
    job, rev, ids = shop_render_setup(db)
    other = db.add_job(status="review", kind="shopping", format="shopping")
    foreign = db.add_asset(other, "image", rights={"basis": "own"})
    rev["spec"]["cuts"].append({"source_asset_id": foreign["id"], "sentence": 3})
    run = db.add_run(job, rev, status="running", claimed_by=WORKER_A, updated_at=ago(seconds=1))
    r = api.get(f"{W}/render/{run['id']}/inputs", headers=wauth())
    assert r.status_code == 200, r.text
    got = {i["asset_id"]: i for i in r.json()["inputs"]}
    want = {ids["child"], ids["img"], ids["bgm"], *ids["narr"]}
    assert set(got) == want  # 원본 업로드·미사용 사진·다른 작업 자산·analysis 없음
    assert got[ids["child"]]["parent_asset_id"] == ids["up"]  # R5: 컷 id → 파생 source
    assert got[ids["child"]]["kind"] == "source"
    assert {got[n]["kind"] for n in ids["narr"]} == {"narration"}


def test_a15_shopping_render_rechecks_ref_assets(api, auth, db):
    job, rev, ids = shop_render_setup(db)
    db.assets[:] = [a for a in db.assets if a["id"] != ids["narr"][2]]  # 참조 녹음 사라짐
    r = rr.render(api, auth, job, rev)
    assert r.status_code == 409 and r.json()["field"] == "assets"
    assert db.runs == []


def test_a15_shopping_render_needs_derived_source(api, auth, db):
    job, rev, ids = shop_render_setup(db)
    next(a for a in db.assets if a["id"] == ids["child"])["status"] = "pending"
    r = rr.render(api, auth, job, rev)
    assert r.status_code == 409 and r.json()["field"] == "assets"


def test_a15_shopping_render_ok(api, auth, db):
    job, rev, _ = shop_render_setup(db)
    r = rr.render(api, auth, job, rev)
    assert r.status_code == 202, r.text
    assert r.json()["render_run"]["preset_version"] == "shopping-1080-v1"


def test_review3_a15_same_key_replay_returns_existing_run(api, auth, db):
    # 리뷰 반영 3: 같은 Idempotency-Key 재전송은 자산 재확인 없이 RPC가 기존 run(200)
    job, rev, ids = shop_render_setup(db)
    assert rr.render(api, auth, job, rev, key="rk-shop").status_code == 202
    db.assets[:] = [a for a in db.assets if a["id"] != ids["narr"][0]]
    r = rr.render(api, auth, job, rev, key="rk-shop")
    assert r.status_code == 200 and len(db.runs) == 1


def test_review3_a16_retry_rechecks_ref_assets(api, auth, db):
    job, rev, ids = shop_render_setup(db)
    job.update(status="failed", failed_stage="render", error_code="render_failed")
    run = db.add_run(job, rev, status="failed", error_stage="render", error_code="render_failed")
    db.assets[:] = [a for a in db.assets if a["id"] != ids["bgm"]]
    r = rr.retry(api, auth, job, run)
    assert r.status_code == 409 and r.json()["field"] == "assets"
    assert "retry" not in db.rpc_calls
    db.add_asset(job, "bgm", id=ids["bgm"], rights={"basis": "licensed"})
    assert rr.retry(api, auth, job, run).status_code == 202
