# ruff: noqa: F401, F811
"""task-048 쇼핑 P0 인수 테스트(API 쪽): SHOP-01(API 흐름)·03·04·05.

가짜 PostgREST·Storage(ProdDB)에 사용자 API·워커 API를 실제 라우터로 호출한다.
실제 ffmpeg 렌더(SHOP-01 MP4·SHOP-02 블러)는 워커 acceptance·실환경이 맡는다.
근거: tasks/plan-shopping-japanese.md#인수 기준(SHOP-01~05).
"""

import copy
import uuid

import pytest

from tests.production.acceptance.test_cat_api_acceptance import (  # noqa: F401
    api,
    auth,
    db,
    post,
    put_spec,
    render_done,
    request_run,
)
from tests.production.test_jobs_api import CAND, URL, WS
from tests.production.test_render_runs import ProdDB, wauth
from tests.production.test_shopping_api import (
    JA_LINK,
    KO_LINK,
    RIGHTS,
    shop_body,
)
from tests.production.test_validation_shopping import good as shop_spec
from tests.production.test_worker_production import (
    W,
    claim,
    finish,
    item,
    outputs,
    upload_all,
)

PRESET = "shopping-1080-v1"
SHOP_META = {"duration_sec": 20.0, "width": 1080, "height": 1920, "has_audio": True}
BAN_MSG = "의약품·건강기능식품은 쇼핑 작업으로 만들 수 없습니다."


def create(api, auth, db: ProdDB, key: str = "shop-job", **over):
    if not db.candidates:
        db.candidates.append({"id": CAND, "workspace_id": WS})
    body = shop_body(**over)
    body.setdefault("candidate_id", CAND)
    return post(api, auth, "", headers={"Idempotency-Key": key}, json=body)


def upload_ready(api, auth, db: ProdDB, jid: str, kind: str, mime: str, rights=RIGHTS) -> str:
    r = post(
        api,
        auth,
        f"/{jid}/uploads",
        json={"kind": kind, "size_bytes": 1024, "mime": mime, "rights": rights},
    )
    assert r.status_code == 201, r.text
    aid = r.json()["asset"]["id"]
    row = next(a for a in db.assets if a["id"] == aid)
    db.objects[row["storage_path"]] = row["size_bytes"]
    assert post(api, auth, f"/{jid}/uploads/{aid}/complete").status_code == 200
    return aid


def shop_claim(api):
    return api.post(f"{W}/claim", json={"capabilities": ["shopping"]}, headers=wauth())


def errs(resp, key: str = "errors") -> list[str]:
    return [e["code"] for e in resp.json()["revision"]["validation"][key]]


def prepared_job(api, auth, db: ProdDB, n_sources: int = 3, **over) -> tuple[dict, list[str]]:
    """원본 n개 등록 → prepare 202 → 쇼핑 워커 claim → 원본별 산출물 → review."""
    r = create(api, auth, db, **over)
    assert r.status_code == 201, r.text
    job = r.json()["job"]
    ups = [
        upload_ready(api, auth, db, job["id"], "source_upload", "video/mp4")
        for _ in range(n_sources)
    ]
    assert post(api, auth, f"/{job['id']}/prepare").status_code == 202
    assert shop_claim(api).status_code == 200
    ids: list[str] = []
    for up in ups:
        items = [
            item("source", "video/mp4", duration_sec=20.0, parent_asset_id=up),
            item("analysis", "application/json", parent_asset_id=up),
            item("sheet", "image/jpeg", parent_asset_id=up),
        ]
        ids += upload_all(db, outputs(api, "prepare", job["id"], items))
    r = finish(api, "prepare", job["id"], status="done", asset_ids=ids, meta=SHOP_META)
    assert r.status_code == 200, r.text
    assert db.job(job["id"])["status"] == "review"
    derived = [a["id"] for a in db.assets if a["kind"] == "source" and a["job_id"] == job["id"]]
    assert len(derived) == n_sources
    return job, derived


def with_narrations(api, auth, db: ProdDB, jid: str, spec: dict) -> dict:
    nar = [upload_ready(api, auth, db, jid, "narration", "audio/wav") for _ in range(4)]
    spec["voice"] = {"narration_asset_ids": nar}
    return spec


def map_cuts(spec: dict, derived: list[str]) -> dict:
    for i, cut in enumerate(spec["cuts"]):
        cut["source_asset_id"] = derived[i % len(derived)]
    return spec


def approve(api, auth, jid: str, rev_no: int = 1):
    return post(api, auth, f"/{jid}/revision/approve", json={"rev_no": rev_no})


def review_ready(api, auth, db: ProdDB, mutate=None, n_sources: int = 3, **over):
    job, derived = prepared_job(api, auth, db, n_sources, **over)
    spec = map_cuts(shop_spec(), derived)
    with_narrations(api, auth, db, job["id"], spec)
    if mutate:
        mutate(spec)
    r = put_spec(api, auth, job["id"], spec, 1)
    assert r.status_code == 200, r.text
    return job, r


# === SHOP-01: 상품 작업 → 원본 3개 → 4문장 대본·녹음 → 승인 → 렌더 배정 ===============


def test_shop01_three_sources_four_sentences_to_render_task_payload(api, auth, db):
    job, r = review_ready(api, auth, db)
    assert job["format"] == "shopping" and job["preset_version"] == PRESET
    assert errs(r) == [] and errs(r, "warnings") == []
    ap = approve(api, auth, job["id"])
    assert ap.status_code == 200, ap.text
    rev_id = ap.json()["revision"]["id"]
    run = request_run(api, auth, job["id"], rev_id, "shop-run-1").json()["render_run"]
    assert run["preset_version"] == PRESET
    task = shop_claim(api).json()["task"]
    assert task["kind"] == "render" and task["id"] == run["id"]
    assert task["format"] == "shopping" and task["job_kind"] == "shopping"
    ts = task["spec"]
    assert len(ts["script"]) == 4  # 4문장
    assert sorted(c["sentence"] for c in ts["cuts"]) == [1, 2, 3, 4]  # 문장마다 컷
    narr = ts["voice"]["narration_asset_ids"]
    assert len(narr) == 4 and len(set(narr)) == 4  # 문장별 녹음 4개
    inputs = api.get(f"{W}/render/{run['id']}/inputs", headers=wauth()).json()["inputs"]
    got = {i["asset_id"]: i["kind"] for i in inputs}
    assert set(narr) <= set(got) and {got[n] for n in narr} == {"narration"}
    cut_ids = {c["source_asset_id"] for c in ts["cuts"]}
    assert cut_ids <= set(got) and {got[c] for c in cut_ids} == {"source"}  # 컷은 파생 source
    assert len(cut_ids) == 3  # 원본 3개 모두 사용
    render_done(api, db, run["id"])
    assert db.job(job["id"])["status"] == "inspect"


def test_shop01_boundary_uploads_over_cap_10_rejected(api, auth, db):
    r = create(api, auth, db)
    jid = r.json()["job"]["id"]
    for _ in range(10):
        upload_ready(api, auth, db, jid, "source_upload", "video/mp4")
    r = post(
        api,
        auth,
        f"/{jid}/uploads",
        json={"kind": "source_upload", "size_bytes": 10, "mime": "video/mp4", "rights": RIGHTS},
    )
    assert r.status_code == 409


def test_shop01_failure_prepare_missing_a_source_set_stays_preparing(api, auth, db):
    r = create(api, auth, db)
    jid = r.json()["job"]["id"]
    ups = [upload_ready(api, auth, db, jid, "source_upload", "video/mp4") for _ in range(3)]
    assert post(api, auth, f"/{jid}/prepare").status_code == 202
    assert shop_claim(api).status_code == 200
    items = [
        item("source", "video/mp4", duration_sec=20.0, parent_asset_id=ups[0]),
        item("analysis", "application/json", parent_asset_id=ups[0]),
        item("sheet", "image/jpeg", parent_asset_id=ups[0]),
    ]
    ids = upload_all(db, outputs(api, "prepare", jid, items))
    r = finish(api, "prepare", jid, status="done", asset_ids=ids, meta=SHOP_META)
    assert r.status_code == 400 and db.job(jid)["status"] == "preparing"


def test_shop01_failure_prepare_without_source_is_400(api, auth, db):
    jid = create(api, auth, db).json()["job"]["id"]
    assert post(api, auth, f"/{jid}/prepare").status_code == 400


# === SHOP-03: 승인 차단 4종 / 경고만 3종 ==================================================


def approve_blocked(api, auth, db, jid: str, code: str):
    ap = approve(api, auth, jid)
    assert ap.status_code == 400, ap.text
    assert code in [e["code"] for e in ap.json()["errors"]]
    rev = next(x for x in db.revisions if x["job_id"] == jid)  # 실제 존재하는 차단된 리비전
    assert rev["approved_at"] is None
    rr = request_run(api, auth, jid, rev["id"], "blocked-run")
    body = rr.json()
    assert (rr.status_code, body["code"], body["field"]) == (400, "VALIDATION", "revision_id")
    assert db.runs == []


def test_shop03_block_rights_not_recorded(api, auth, db):
    job, derived = prepared_job(api, auth, db, 3)
    # 권리 기록 없는 원본: 부모 source_upload의 rights를 비운다
    victim = next(a for a in db.assets if a["kind"] == "source_upload" and a["job_id"] == job["id"])
    victim["rights"] = None
    spec = with_narrations(api, auth, db, job["id"], map_cuts(shop_spec(), derived))
    r = put_spec(api, auth, job["id"], spec, 1)
    assert r.status_code == 200 and "rights.missing" in errs(r)
    approve_blocked(api, auth, db, job["id"], "rights.missing")


def test_shop03_block_portrait_without_consent(api, auth, db):
    job, derived = prepared_job(api, auth, db, 3)
    next(a for a in db.assets if a["kind"] == "source_upload")["rights"] = {
        "basis": "own",
        "has_person": True,
        "portrait_consent": False,
    }
    spec = with_narrations(api, auth, db, job["id"], map_cuts(shop_spec(), derived))
    r = put_spec(api, auth, job["id"], spec, 1)
    assert "rights.portrait_consent" in errs(r)
    approve_blocked(api, auth, db, job["id"], "rights.portrait_consent")


def test_shop03_block_unverified_marker_left(api, auth, db):
    def mut(s):
        s["script"][1]["text"] += " [확인 필요]"

    job, r = review_ready(api, auth, db, mut)
    assert "script.unverified" in errs(r)
    approve_blocked(api, auth, db, job["id"], "script.unverified")


def test_shop03_block_not_four_sentences(api, auth, db):
    def mut(s):
        s["script"].pop()

    job, r = review_ready(api, auth, db, mut)
    assert "script.count" in errs(r)
    approve_blocked(api, auth, db, job["id"], "script.count")


def test_shop03_warn_length_out_of_range_banned_phrase_few_sources_still_approvable(api, auth, db):
    def mut(s):
        s["script"][0]["text"] = "짧다"  # 글자 수 범위 밖
        s["script"][2]["text"] = "이건 인생템이라 강력 추천해요"  # 금지 문구
        s["cuts"][1]["source_asset_id"] = s["cuts"][0]["source_asset_id"]  # 원본 2개로 줄여 사용

    job, r = review_ready(api, auth, db, mut, n_sources=2)
    assert errs(r) == [], errs(r)
    w = set(errs(r, "warnings"))
    assert {"script.length", "script.banned_phrase"} <= w
    assert approve(api, auth, job["id"]).status_code == 200  # 경고는 승인 가능


def test_shop03_warn_fewer_than_three_sources_only_warns(api, auth, db):
    job, r = review_ready(api, auth, db, n_sources=2)  # 원본 2개만 등록한 작업
    assert errs(r) == [] and "sources.few" in errs(r, "warnings")
    assert approve(api, auth, job["id"]).status_code == 200


def test_shop03_boundary_exactly_three_sources_has_no_few_warning(api, auth, db):
    job, r = review_ready(api, auth, db)
    assert "sources.few" not in errs(r, "warnings")


# === SHOP-04: 의약품·건기식 작업 생성 거부 ================================================


@pytest.mark.parametrize(
    "over",
    [
        {"title": "건강기능식품 솔직 후기"},
        {"title": "건 강 기 능 식 품"},  # 경계: 공백 우회
        {"brief": {"product_name": "의약품", "scenes": []}},
        {"comment_keyword": "영양제"},
    ],
)
def test_shop04_medicine_or_supplement_creation_rejected(api, auth, db, over):
    r = create(api, auth, db, **over)
    assert r.status_code == 400
    assert r.json() == {"code": "VALIDATION", "message": BAN_MSG, "field": "banned_category"}
    assert db.jobs == []


def test_shop04_unconfirmed_banned_checkbox_rejected(api, auth, db):
    r = create(api, auth, db, not_banned_confirmed=False)
    assert r.status_code == 400 and r.json()["field"] == "banned_category"
    assert db.jobs == []


def test_shop04_normal_product_is_created(api, auth, db):
    assert create(api, auth, db).status_code == 201


# === SHOP-05: 여행 작업 게시 문구 ========================================================


def test_shop05_travel_publish_text_has_disclosure_keyword_and_link_notice(api, auth, db):
    body = {
        "title": "오사카 2박 3일",
        "vertical": "travel",
        "brief": {"destination": "오사카", "product_type": "tour", "appeal": "야경"},
        "comment_keyword": "오사카여행",
    }
    r = create(api, auth, db, **body)
    assert r.status_code == 201, r.text
    job = db.jobs[0]
    assert job["vertical"] == "travel"
    job["status"] = "done"
    for lang in ("ko", "ja"):
        db.runs.append(
            {
                "id": str(uuid.uuid4()),
                "workspace_id": job["workspace_id"],
                "job_id": job["id"],
                "lang": lang,
                "status": "done",
                "created_at": "2026-11-20T00:00:00+00:00",
                "finished_at": "2026-11-20T00:01:00+00:00",
            }
        )
    out = api.get(f"{URL}/{job['id']}/publish-text", headers=auth)
    assert out.status_code == 200, out.text
    text = out.json()["text"]
    lines = text["caption"].splitlines()
    assert lines[0].startswith("[광고]")  # 대가성 표기
    assert db.jobs[0]["comment_keyword"] == "오사카여행"
    assert len(lines) == 2 and "오사카여행" in lines[1]  # 지정한 댓글 키워드 안내 문장
    assert "오사카여행" not in text["pinned_comment"]  # 키워드 안내와 링크 안내는 별개 필드
    assert text["pinned_comment"].splitlines()[0] == "구매 링크"  # 제휴 링크 안내 머리글
    assert KO_LINK in text["pinned_comment"]  # 제휴 링크 안내
    assert JA_LINK not in text["pinned_comment"]
    ja = api.get(f"{URL}/{job['id']}/publish-text", params={"lang": "ja"}, headers=auth).json()
    assert ja["text"]["caption"].startswith("【PR】") and JA_LINK in ja["text"]["pinned_comment"]


def test_shop05_failure_publish_text_before_done_run_is_409(api, auth, db):
    assert (
        create(api, auth, db, vertical="travel", brief={"destination": "오사카"}).status_code == 201
    )
    jid = db.jobs[0]["id"]
    r = api.get(f"{URL}/{jid}/publish-text", headers=auth)
    assert r.status_code == 409


def test_shop05_boundary_other_language_without_run_is_409(api, auth, db):
    assert create(api, auth, db).status_code == 201
    job = db.jobs[0]
    job["status"] = "done"
    db.runs.append(
        {
            "id": str(uuid.uuid4()),
            "workspace_id": job["workspace_id"],
            "job_id": job["id"],
            "lang": "ko",
            "status": "done",
            "created_at": "2026-11-20T00:00:00+00:00",
            "finished_at": "2026-11-20T00:01:00+00:00",
        }
    )
    r = api.get(f"{URL}/{job['id']}/publish-text", params={"lang": "ja"}, headers=auth)
    assert r.status_code == 409
