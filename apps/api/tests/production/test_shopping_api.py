"""task-044 쇼핑 API(사용자): A-09 kind·vertical·brief·affiliates·금지 품목, A-10 다건·권리,
A-11 금지 품목 재검사, A-13 권리 없는 승인 400, P9 자산 삭제, A-21 게시 문구, 로그에 링크·토큰 0.

가짜 PostgREST·Storage는 test_jobs_api를 재사용한다. DB 트리거(000023)는 pgTAP이 검사한다.
"""

import copy
import io
import logging
import sys
import uuid
from typing import Any

import pytest

from app.logging_mask import setup_logging
from app.production import shopping
from tests.production import test_jobs_api as ja
from tests.production.test_jobs_api import OTHER_WS, URL, FakeDB, _now, create_body
from tests.production.test_validation_shopping import good as shopping_good

api = ja.api  # 픽스처 재사용
auth = ja.auth
db = ja.db

KO_LINK = "https://link.example.com/ko/aff-7f3a9c"
JA_LINK = "https://a.example.jp/ja/aff-91bd02"
RIGHTS = {"basis": "own", "has_person": False}


def shop_body(**over: Any) -> dict:
    body = create_body(
        title="발 편한 운동화",
        kind="shopping",
        vertical="product",
        not_banned_confirmed=True,
        brief={"product_name": "운동화", "pain": "발이 아픔", "scenes": ["출근", "산책", "등산"]},
        affiliates=[
            {"lang": "ko", "partner": "쿠팡", "url": KO_LINK},
            {"lang": "ja", "partner": "楽天", "url": JA_LINK},
        ],
        comment_keyword="링크",
    )
    body.update(over)
    return body


def post(api, auth, body: dict, key: str = "shop-1"):
    return api.post(URL, json=body, headers={**auth, "Idempotency-Key": key})


def shop_job(db: FakeDB, **over: Any) -> dict:
    base = {
        "kind": "shopping",
        "format": "shopping",
        "vertical": "product",
        "preset_version": "shopping-1080-v1",
        "brief": {"product_name": "운동화"},
        "affiliates": [
            {"lang": "ko", "partner": "쿠팡", "url": KO_LINK},
            {"lang": "ja", "partner": "楽天", "url": JA_LINK},
        ],
        "comment_keyword": "링크",
    }
    base.update(over)
    return db.add_job(**base)


def upload(api, auth, jid: str, kind: str = "source_upload", mime: str = "video/mp4", **over):
    body = {"kind": kind, "size_bytes": 10, "mime": mime, "rights": RIGHTS, **over}
    return api.post(f"{URL}/{jid}/uploads", json=body, headers=auth)


# === A-09 생성 =====================================================================


def test_create_shopping_job_201_with_server_values(api, auth, db):
    r = post(api, auth, shop_body())
    assert r.status_code == 201, r.text
    job = r.json()["job"]
    assert (job["kind"], job["format"], job["vertical"]) == ("shopping", "shopping", "product")
    assert job["preset_version"] == "shopping-1080-v1"
    assert job["brief"]["product_name"] == "운동화"
    assert job["affiliates"][0] == {"lang": "ko", "partner": "쿠팡", "url": KO_LINK}
    assert job["comment_keyword"] == "링크"
    assert "not_banned_confirmed" not in db.jobs[0]


@pytest.mark.parametrize(
    ("over", "field"),
    [
        ({"format": "category"}, "format"),
        ({"vertical": None}, "vertical"),
        (
            {"source_kind": "url", "source_url": "https://youtu.be/abc", "rights_confirmed": True},
            "source_kind",
        ),
        ({"brief": {"destination": "오사카"}}, "brief.destination"),
        ({"not_banned_confirmed": False}, "banned_category"),
    ],
)
def test_create_shopping_validation_400(api, auth, db, over, field):
    r = post(api, auth, shop_body(**over))
    assert r.status_code == 400
    assert r.json()["field"] == field
    assert db.jobs == []


def test_general_job_rejects_shopping_fields(api, auth, db):
    r = post(api, auth, create_body(brief={"product_name": "x"}))
    assert r.status_code == 400 and r.json()["field"] == "brief"
    r = post(api, auth, create_body(kind="general", format="shopping"), key="k2")
    assert r.status_code == 400 and r.json()["field"] == "format"
    assert db.jobs == []


@pytest.mark.parametrize(
    "over",
    [
        {"title": "건강기능식품 솔직 후기"},
        {"title": "건 강 기 능 식 품"},  # 공백 우회
        {"title": "의​약품 정리"},  # 폭 없는 공백
        {"title": "영양-제 추천"},  # 구두점
        {"title": "ＳＵＰＰＬＥＭＥＮＴ"},  # 전각(NFKC)
        {"title": "Daily Medicine kit"},  # 대소문자(casefold)
        {"brief": {"product_name": "건기식", "scenes": []}},
        {"brief": {"product_name": "x", "facts": ["サプリ です"]}},
        {"comment_keyword": "의약품"},
    ],
)
def test_p7_banned_category_400_including_bypass(api, auth, db, over):
    r = post(api, auth, shop_body(**over))
    assert r.status_code == 400
    assert r.json() == {
        "code": "VALIDATION",
        "message": "의약품·건강기능식품은 쇼핑 작업으로 만들 수 없습니다.",
        "field": "banned_category",
    }
    assert db.jobs == []


def test_p7_no_false_positive_on_short_words(api, auth, db):
    body = shop_body(
        title="호텔 예약 약속 장소",
        vertical="travel",
        brief={"destination": "오사카", "product_type": "stay", "appeal": "야경"},
    )
    assert post(api, auth, body).status_code == 201


@pytest.mark.parametrize(
    "aff",
    [
        {"lang": "ko", "partner": "p", "url": "http://link.example.com/a"},
        {"lang": "ko", "partner": "p", "url": "javascript:alert(1)"},
        {"lang": "ko", "partner": "p", "url": "https://link.example.com/a b"},
        {"lang": "ko", "partner": "p", "url": "https://user:pw@link.example.com/a"},
        {"lang": "ko", "partner": "p", "url": "https://link.example.com/" + "a" * 2048},
        {"lang": "ko", "partner": " ", "url": KO_LINK},
        {"lang": "en", "partner": "p", "url": KO_LINK},
        {"lang": "ko", "partner": "p", "url": KO_LINK, "token": "x"},
    ],
)
def test_affiliates_validation_400(api, auth, db, aff):
    r = post(api, auth, shop_body(affiliates=[aff]))
    assert r.status_code == 400
    assert r.json()["field"].startswith("affiliates")
    assert db.jobs == []


def test_affiliates_count_cap_20(api, auth, db):
    many = [{"lang": "ko", "partner": "p", "url": f"{KO_LINK}{i}"} for i in range(21)]
    assert post(api, auth, shop_body(affiliates=many)).status_code == 400


# === A-09 PATCH(P10)·목록·상세 =====================================================


def test_p10_patch_brief_affiliates_vertical(api, auth, db):
    job = shop_job(db)
    body = {
        "vertical": "travel",
        "brief": {"destination": "후쿠오카", "product_type": "tour"},
        "affiliates": [{"lang": "ja", "partner": "楽天", "url": JA_LINK}],
        "comment_keyword": "여행",
    }
    r = api.patch(f"{URL}/{job['id']}", json=body, headers=auth)
    assert r.status_code == 200, r.text
    assert job["vertical"] == "travel" and job["brief"] == {
        "destination": "후쿠오카",
        "product_type": "tour",
        "scenes": [],
        "facts": [],
    }
    assert job["affiliates"] == [{"lang": "ja", "partner": "楽天", "url": JA_LINK}]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"brief": {"product_name": "건강 기능 식품"}}, "banned_category"),
        ({"vertical": None}, "vertical"),
        ({"affiliates": None}, "affiliates"),
        ({"vertical": "travel"}, "brief.product_name"),  # 기존 brief가 상품 항목
        ({"kind": "general"}, "kind"),  # kind 불변(extra=forbid)
        (
            {"source_kind": "url", "source_url": "https://youtu.be/a", "rights_confirmed": True},
            "source_kind",
        ),
    ],
)
def test_p10_patch_shopping_400(api, auth, db, body, field):
    job = shop_job(db)
    before = dict(job)
    r = api.patch(f"{URL}/{job['id']}", json=body, headers=auth)
    assert r.status_code == 400
    assert r.json()["field"] == field
    assert job == before


def test_patch_general_job_rejects_shopping_fields(api, auth, db):
    job = db.add_job()
    r = api.patch(f"{URL}/{job['id']}", json={"affiliates": []}, headers=auth)
    assert r.status_code == 400 and r.json()["field"] == "affiliates"


def test_list_filters_kind_format_lang_and_columns(api, auth, db):
    gen = db.add_job(current_revision_id=str(uuid.uuid4()))
    shop = shop_job(
        db, current_revision_id=str(uuid.uuid4()), current_ja_revision_id=str(uuid.uuid4())
    )
    shop_job(db, vertical="travel")
    items = api.get(URL, params={"kind": "shopping"}, headers=auth).json()["items"]
    assert {i["kind"] for i in items} == {"shopping"} and len(items) == 2
    items = api.get(URL, params={"format": "shopping", "lang": "ja"}, headers=auth).json()["items"]
    assert [i["id"] for i in items] == [shop["id"]]
    assert items[0]["langs"] == ["ko", "ja"] and items[0]["vertical"] == "product"
    items = api.get(URL, params={"lang": "ko"}, headers=auth).json()["items"]
    assert {i["id"] for i in items} == {gen["id"], shop["id"]}


def test_detail_current_revision_per_lang(api, auth, db):
    job = shop_job(db, status="inspect")
    ko = db.add_revision(job, approved=True)
    ja = db.add_revision(job, lang="ja", approved=False)
    job.update(current_revision_id=ko["id"], current_ja_revision_id=ja["id"])
    cur = api.get(f"{URL}/{job['id']}", headers=auth).json()["current_revision"]
    assert cur["ko"]["id"] == ko["id"] and cur["ja"]["id"] == ja["id"]


# === A-10 업로드(P5·P6) ============================================================


@pytest.mark.parametrize(
    ("over", "field"),
    [
        ({"rights": None}, "rights"),
        ({"rights": {"basis": "ai_generated"}}, "rights.basis"),
        ({"rights": {"basis": "own", "gen": {"platform": "x"}}}, "rights.gen"),
        ({"rights": {"basis": "own", "reviewed": True}}, "rights.reviewed"),
        ({"rights": {"basis": "own", "has_person": True}}, "rights.portrait_consent"),
        ({"rights": {"basis": "own", "source_url": "ftp://x.example.com/a"}}, "rights.source_url"),
    ],
)
def test_p6_shopping_upload_rights_rules(api, auth, db, over, field):
    job = shop_job(db)
    r = upload(api, auth, job["id"], **over)
    assert r.status_code == 400
    assert r.json()["field"] == field
    assert db.assets == []


def test_shopping_uploads_store_rights_and_new_kinds(api, auth, db):
    job = shop_job(db)
    rights = {"basis": "licensed", "has_person": True, "portrait_consent": True, "author": "a"}
    assert upload(api, auth, job["id"], "image", "image/png", rights=rights).status_code == 201
    assert upload(api, auth, job["id"], "bgm", "audio/mpeg").status_code == 201
    assert upload(api, auth, job["id"], "narration", "audio/wav").status_code == 201
    img = next(a for a in db.assets if a["kind"] == "image")
    assert img["rights"] == {
        "basis": "licensed",
        "author": "a",
        "has_person": True,
        "portrait_consent": True,
    }
    assert img["storage_path"].endswith(".png")


def test_general_job_rejects_shopping_upload_kinds(api, auth, db):
    job = db.add_job()
    for kind, mime in (("image", "image/png"), ("bgm", "audio/mpeg"), ("narration", "audio/wav")):
        assert upload(api, auth, job["id"], kind, mime).status_code == 400
    # 일반 작업은 권리 선택(없이도 업로드)
    assert upload(api, auth, job["id"], rights=None).status_code == 201


def test_p5_multiple_source_uploads_keep_pending_cap_10(api, auth, db):
    job = shop_job(db)
    for _ in range(10):
        assert upload(api, auth, job["id"]).status_code == 201
    assert sum(a["kind"] == "source_upload" for a in db.assets) == 10  # 이전 pending 유지
    r = upload(api, auth, job["id"])
    assert r.status_code == 409 and r.json()["field"] == "kind"


def test_narration_per_sentence_cap_4_keeps_pending(api, auth, db):
    job = shop_job(db)
    for _ in range(4):
        assert upload(api, auth, job["id"], "narration", "audio/wav").status_code == 201
    assert sum(a["kind"] == "narration" for a in db.assets) == 4
    assert upload(api, auth, job["id"], "narration", "audio/wav").status_code == 409


def test_bgm_new_upload_replaces_pending(api, auth, db):
    job = shop_job(db)
    upload(api, auth, job["id"], "bgm", "audio/mpeg")
    upload(api, auth, job["id"], "bgm", "audio/mpeg")
    assert sum(a["kind"] == "bgm" for a in db.assets) == 1


@pytest.mark.parametrize(
    ("kind", "mime"),
    [("source_upload", "video/mp4"), ("image", "image/png"), ("narration", "audio/wav")],
)
def test_p2_insert_race_over_cap_is_409(api, auth, db, kind, mime):
    job = shop_job(db)
    db.asset_insert_error = "23505"  # 트리거(리뷰 반영 4): 동시 업로드로 상한 초과
    r = upload(api, auth, job["id"], kind, mime)
    assert r.status_code == 409 and r.json()["code"] == "CONFLICT"


def test_shopping_complete_allows_several_ready_sources(api, auth, db):
    job = shop_job(db)
    first = db.add_asset(job, "source_upload", status="ready", size_bytes=10)
    second = db.add_asset(job, "source_upload", status="pending", size_bytes=10)
    db.objects[second["storage_path"]] = 10
    r = api.post(f"{URL}/{job['id']}/uploads/{second['id']}/complete", headers=auth)
    assert r.status_code == 200 and second["status"] == "ready" and first["status"] == "ready"


def test_general_complete_race_still_409(api, auth, db):
    job = db.add_job()
    db.add_asset(job, "source_upload", status="ready")
    second = db.add_asset(job, "source_upload", status="pending", size_bytes=10)
    db.objects[second["storage_path"]] = 10
    db.hide_ready_source = True
    r = api.post(f"{URL}/{job['id']}/uploads/{second['id']}/complete", headers=auth)
    assert r.status_code == 409 and r.json()["message"] == "이미 업로드된 원본이 있습니다."


# === A-11 =========================================================================


def test_prepare_shopping_banned_recheck_then_starts(api, auth, db):
    job = shop_job(db)
    db.add_asset(job, "source_upload", rights=RIGHTS)
    db.add_asset(job, "source_upload", rights=RIGHTS)
    job["brief"] = {"product_name": "건강기능식품"}  # 저장 뒤 바뀐 값도 다시 본다
    r = api.post(f"{URL}/{job['id']}/prepare", headers=auth)
    assert r.status_code == 400 and r.json()["field"] == "banned_category"
    job["brief"] = {"product_name": "운동화"}
    # task-045: 쇼핑 렌더러가 생겨 409(field kind)를 풀었다 — 지원 워커가 claim한다(R4)
    r = api.post(f"{URL}/{job['id']}/prepare", headers=auth)
    assert r.status_code == 202, r.text
    assert job["status"] == "preparing"


def test_review3_prepare_race_with_source_delete_is_409(api, auth, db):
    job = db.add_job()
    db.add_asset(job, "source_upload")
    db.write_errors["PATCH production_jobs"] = "NR010"  # 확인 뒤 원본이 지워짐(트리거)
    r = api.post(f"{URL}/{job['id']}/prepare", headers=auth)
    assert r.status_code == 409 and r.json()["field"] == "source_upload"
    assert job["status"] == "draft"


# === 리뷰 반영 5: 제어·서식·줄 구분 문자 ==================================================


@pytest.mark.parametrize("ch", ["\u2028", "\u2029", "\u0085", "\u202e", "\u200b", "\x07"])
@pytest.mark.parametrize(
    "make",
    [
        lambda c: {"brief": {"product_name": f"운동{c}화"}},
        lambda c: {"comment_keyword": f"링{c}크"},
        lambda c: {"affiliates": [{"lang": "ko", "partner": f"쿠{c}팡", "url": KO_LINK}]},
    ],
)
def test_review5_invisible_and_separator_chars_rejected(api, auth, db, ch, make):
    r = post(api, auth, shop_body(**make(ch)))
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION"
    assert db.jobs == []


def test_review5_rights_note_separator_rejected(api, auth, db):
    job = shop_job(db)
    r = upload(api, auth, job["id"], rights={"basis": "own", "note": "a\u2029b"})
    assert r.status_code == 400 and r.json()["field"] == "rights.note"


# === A-12·A-13 쇼핑 검증(권리) =======================================================


def review_shop(db: FakeDB, rights: Any = RIGHTS) -> tuple[dict, dict, list[str]]:
    """원본 2개(+파생 source)·사진 1개, 컷은 파생 source·원본·사진을 쓴다."""
    job = shop_job(db, status="review")
    u1 = db.add_asset(job, "source_upload", rights=rights)
    u2 = db.add_asset(job, "source_upload", rights=RIGHTS)
    s1 = db.add_asset(job, "source", created_by="w", parent_asset_id=u1["id"], duration_sec=30)
    db.add_asset(job, "source", created_by="w", parent_asset_id=u2["id"], duration_sec=30)
    img = db.add_asset(job, "image", rights=RIGHTS)
    spec = shopping_good()
    ids = [s1["id"], u2["id"], img["id"], s1["id"]]
    for cut, aid in zip(spec["cuts"], ids, strict=True):
        cut["source_asset_id"] = aid
    rev = db.add_revision(job, spec=spec)
    return job, rev, [u1["id"], s1["id"], img["id"]]


def test_approve_shopping_ok_with_rights(api, auth, db):
    job, rev, _ = review_shop(db)
    r = api.post(f"{URL}/{job['id']}/revision/approve", json={"rev_no": 1}, headers=auth)
    assert r.status_code == 200, r.text
    assert rev["approved_at"] is not None


@pytest.mark.parametrize(
    "rights",
    [None, {"note": "basis 없음"}, {"basis": "own", "has_person": True, "portrait_consent": False}],
)
def test_approve_without_rights_400(api, auth, db, rights):
    # 파생 source의 권리는 부모 source_upload 값으로 본다(P1)
    job, rev, _ = review_shop(db, rights=rights)
    r = api.post(f"{URL}/{job['id']}/revision/approve", json={"rev_no": 1}, headers=auth)
    assert r.status_code == 400
    codes = {e["code"] for e in r.json()["errors"]}
    assert codes & {"rights.missing", "rights.portrait_consent"}
    assert rev["approved_at"] is None


def test_reviewed_in_rights_jsonb_is_ignored(api, auth, db):
    # AI 생성 basis가 DB에 있어도 reviewed는 사용자 jsonb에서 읽지 않는다(P6)
    gen = {"platform": "p", "model": "m", "request_id": "r", "cost_krw": 0}
    job, _, _ = review_shop(db, rights={"basis": "ai_generated", "gen": gen, "reviewed": True})
    r = api.post(f"{URL}/{job['id']}/revision/approve", json={"rev_no": 1}, headers=auth)
    assert r.status_code == 400
    assert "gen.unreviewed" in {e["code"] for e in r.json()["errors"]}


def test_put_shopping_spec_validates_with_job_assets(api, auth, db):
    job, rev, _ = review_shop(db)
    spec = copy.deepcopy(rev["spec"])
    spec["cuts"][0]["source_asset_id"] = str(uuid.uuid4())  # 다른(없는) 자산
    r = api.put(f"{URL}/{job['id']}/revision", json={"spec": spec, "base_rev_no": 1}, headers=auth)
    assert r.status_code == 200
    codes = [e["code"] for e in r.json()["revision"]["validation"]["errors"]]
    assert "cuts.source_invalid" in codes and "assets.required" not in codes


# === P9 자산 삭제 ===================================================================


def test_p9_delete_source_upload_only_in_prepare_state(api, auth, db):
    job = shop_job(db)
    a = db.add_asset(job, "source_upload")
    db.objects[a["storage_path"]] = 10
    r = api.delete(f"{URL}/{job['id']}/assets/{a['id']}", headers=auth)
    assert r.status_code == 204
    assert a not in db.assets and a["storage_path"] not in db.objects
    job2 = shop_job(db, status="review")
    b = db.add_asset(job2, "source_upload")
    assert api.delete(f"{URL}/{job2['id']}/assets/{b['id']}", headers=auth).status_code == 409
    assert b in db.assets


def test_p9_delete_image_only_when_not_referenced(api, auth, db):
    job, _, (_, s1, img) = review_shop(db)
    r = api.delete(f"{URL}/{job['id']}/assets/{img}", headers=auth)
    assert r.status_code == 409 and r.json()["field"] == "asset_id"
    free = db.add_asset(job, "bgm", rights=RIGHTS)
    assert api.delete(f"{URL}/{job['id']}/assets/{free['id']}", headers=auth).status_code == 204
    # 워커 산출물·훅 음성은 지울 수 없다
    assert api.delete(f"{URL}/{job['id']}/assets/{s1}", headers=auth).status_code == 409


def test_p9_delete_trigger_race_and_other_workspace(api, auth, db):
    job = shop_job(db)
    a = db.add_asset(job, "source_upload")
    other = shop_job(db, ws=OTHER_WS)
    b = db.add_asset(other, "source_upload")
    assert api.delete(f"{URL}/{other['id']}/assets/{b['id']}", headers=auth).status_code == 404
    assert api.delete(f"{URL}/{job['id']}/assets/{uuid.uuid4()}", headers=auth).status_code == 404
    assert a in db.assets


# === A-21 게시 문구(P8) =============================================================


def done_run(db: FakeDB, job: dict, lang: str = "ko", **over: Any) -> dict:
    run = {
        "id": str(uuid.uuid4()),
        "workspace_id": job["workspace_id"],
        "job_id": job["id"],
        "lang": lang,
        "status": "done",
        "created_at": _now(),
        "finished_at": _now(),
        **over,
    }
    db.runs.append(run)
    return run


def publish(api, auth, jid: str, **params):
    return api.get(f"{URL}/{jid}/publish-text", params=params, headers=auth)


def test_a21_publish_text_by_lang(api, auth, db):
    job = shop_job(db, status="done")
    run = done_run(db, job)
    ja = done_run(db, job, "ja")
    r = publish(api, auth, job["id"])
    assert r.status_code == 200
    out = r.json()
    assert out["render_run_id"] == run["id"] and out["lang"] == "ko"
    lines = out["text"]["caption"].splitlines()
    assert lines[0].startswith("[광고]") and "링크" in lines[1]
    assert KO_LINK in out["text"]["pinned_comment"] and JA_LINK not in out["text"]["pinned_comment"]
    assert out["text"]["recommended_time"]
    assert r.headers["cache-control"] == "no-store"
    r = publish(api, auth, job["id"], lang="ja")
    assert r.json()["render_run_id"] == ja["id"] and JA_LINK in r.json()["text"]["pinned_comment"]
    assert r.json()["text"]["caption"].startswith("【PR】")


def test_a21_filters_run_by_job_status_lang(api, auth, db):
    job = shop_job(db, status="done")
    other = shop_job(db, status="done")
    foreign = done_run(db, other)
    failed = done_run(db, job, status="failed")
    assert publish(api, auth, job["id"]).status_code == 409
    assert publish(api, auth, job["id"], render_run_id=foreign["id"]).status_code == 409
    assert publish(api, auth, job["id"], render_run_id=failed["id"]).status_code == 409
    done_run(db, job, "ja")
    assert publish(api, auth, job["id"], lang="ko").status_code == 409
    gen = db.add_job(status="done")
    done_run(db, gen)
    r = publish(api, auth, gen["id"])
    assert r.status_code == 400 and r.json()["field"] == "kind"
    ws_other = shop_job(db, ws=OTHER_WS)
    assert publish(api, auth, ws_other["id"]).status_code == 404


def test_p8_logs_never_contain_affiliate_links_or_signed_tokens(api, auth, db, caplog):
    stream = io.StringIO()
    handler = setup_logging(stream)
    caplog.set_level(logging.DEBUG)
    try:
        assert post(api, auth, shop_body()).status_code == 201
        bad = shop_body(affiliates=[{"lang": "ko", "partner": "p", "url": KO_LINK + " x"}])
        assert post(api, auth, bad, key="shop-2").status_code == 400
        job = db.jobs[0]
        a = upload(api, auth, job["id"]).json()["asset"]
        asset = next(x for x in db.assets if x["id"] == a["id"])
        db.objects[asset["storage_path"]] = 10
        api.post(f"{URL}/{job['id']}/uploads/{a['id']}/complete", headers=auth)
        api.patch(
            f"{URL}/{job['id']}",
            json={"affiliates": [{"lang": "ko", "partner": "p", "url": KO_LINK}]},
            headers=auth,
        )
        job["status"] = "done"
        done_run(db, job)
        assert publish(api, auth, job["id"]).status_code == 200
        assert publish(api, auth, job["id"], lang="ja").status_code == 409
        db.fail_tables.add("render_runs")  # 저장소 오류(503) 경로
        assert publish(api, auth, job["id"]).status_code == 503
    finally:
        handler.setStream(sys.stderr)
    logged = caplog.text + stream.getvalue()
    assert "게시 문구" in logged
    for secret in (KO_LINK, JA_LINK, "link.example.com", "aff-7f3a9c"):
        assert secret not in logged
    assert db.issued_tokens
    for token in db.issued_tokens:
        assert token not in logged and token.rsplit(".", 1)[1] not in logged
    assert "token=" not in logged


# === 리뷰 반영 6·7 ==================================================================


def test_review6_delete_race_with_revision_save_is_409(api, auth, db):
    job, _, _ = review_shop(db)
    free = db.add_asset(job, "narration", rights=RIGHTS)
    db.objects[free["storage_path"]] = 10
    db.write_errors["DELETE production_assets"] = "NR010"  # 그 사이 저장된 리비전이 참조(트리거)
    r = api.delete(f"{URL}/{job['id']}/assets/{free['id']}", headers=auth)
    assert r.status_code == 409
    assert free in db.assets and free["storage_path"] in db.objects


@pytest.mark.parametrize("status", ["review", "inspect"])
def test_review7_patch_shopping_fields_after_prepare(api, auth, db, status):
    job = shop_job(db, status=status)
    body = {"affiliates": [{"lang": "ko", "partner": "쿠팡", "url": KO_LINK + "2"}]}
    r = api.patch(f"{URL}/{job['id']}", json=body, headers=auth)
    assert r.status_code == 200
    assert job["affiliates"][0]["url"] == KO_LINK + "2"
    r = api.patch(f"{URL}/{job['id']}", json={"brief": {"product_name": "새 이름"}}, headers=auth)
    assert r.status_code == 200 and job["brief"]["product_name"] == "새 이름"


@pytest.mark.parametrize(
    "body",
    [
        {"segment_len_sec": 30},
        {"credit": "x", "comment_keyword": "링크"},  # 쇼핑 항목과 섞어도 기존 규칙
    ],
)
def test_review7_other_fields_still_prepare_state_only(api, auth, db, body):
    job = shop_job(db, status="review")
    assert api.patch(f"{URL}/{job['id']}", json=body, headers=auth).status_code == 409


def test_review7_shopping_fields_not_allowed_while_rendering_or_general(api, auth, db):
    job = shop_job(db, status="rendering")
    r = api.patch(f"{URL}/{job['id']}", json={"comment_keyword": "x"}, headers=auth)
    assert r.status_code == 409
    gen = db.add_job(status="review")
    assert api.patch(f"{URL}/{gen['id']}", json={"affiliates": []}, headers=auth).status_code == 409


def test_detail_assets_include_rights_and_parent(api, auth, db):
    # task-045: PROD-03 권리 목록(A-09 상세 assets에 rights·parent_asset_id)
    job = shop_job(db, status="review")
    db.add_revision(job)
    up = db.add_asset(job, "source_upload", rights=RIGHTS)
    db.add_asset(job, "source", parent_asset_id=up["id"], duration_sec=10)
    r = api.get(f"{URL}/{job['id']}", headers=auth)
    assert r.status_code == 200, r.text
    got = {a["kind"]: a for a in r.json()["assets"]}
    assert got["source_upload"]["rights"] == RIGHTS
    assert got["source_upload"]["parent_asset_id"] is None
    assert got["source"]["parent_asset_id"] == up["id"] and got["source"]["rights"] is None
    assert "storage_path" not in got["source"]


def test_review4_delete_narration_in_sentence_list_is_409(api, auth, db):
    # 리뷰 반영 4: spec_asset_refs가 문장별 녹음 4개(narration_asset_ids)도 참조로 본다
    job, rev, _ = review_shop(db)
    narr = [db.add_asset(job, "narration") for _ in range(4)]
    rev["spec"]["voice"] = {"narration_asset_ids": [n["id"] for n in narr]}
    r = api.delete(f"{URL}/{job['id']}/assets/{narr[2]['id']}", headers=auth)
    assert r.status_code == 409 and r.json()["field"] == "asset_id"
    assert narr[2] in db.assets
    free = db.add_asset(job, "narration")
    assert api.delete(f"{URL}/{job['id']}/assets/{free['id']}", headers=auth).status_code == 204


def test_review4_spec_asset_refs_includes_sentence_narrations():
    spec = {
        "cuts": [{"source_asset_id": "c1"}],
        "bgm_asset_id": "b1",
        "voice": {"narration_asset_ids": ["n1", "n2", 3, "n4"]},
    }
    assert shopping.spec_asset_refs(spec) == {"c1", "b1", "n1", "n2", "n4"}
