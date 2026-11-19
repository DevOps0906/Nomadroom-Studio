"""task-044 쇼핑 워커 API(W-05~W-09): job_kind shopping 재현, claim 쇼핑 보류(045 전),
원본별 prepare 입력·계보(parent) 필수·상한, 전부 끝나야 review.

가짜 RPC는 test_render_runs(000023 claim·finish 본뜸)를 재사용한다. 실제 SQL은 pgTAP
(supabase/tests/production_shopping_api_test.sql)이 검사한다.
"""

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


def test_p4_claim_skips_shopping_until_task045(api, db):
    shop_preparing(db, claimed=False)
    assert claim(api).status_code == 204
    gen = db.add_job(status="preparing")
    db.add_asset(gen, "source_upload")
    r = claim(api)
    assert r.status_code == 200 and r.json()["task"]["job_id"] == gen["id"]


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
