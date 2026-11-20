"""task-053 일본어판·쇼핑 P1 인수 테스트(API 쪽): JA-01·JA-04·JA-05·SHOP-07·SHOP-08(API).

Claude(번역 A-20·AI 대본 A-14)와 영상 생성 플랫폼은 모의, 외부 호출은 없다.
렌더(MP4)·TTS 실행은 워커 acceptance가 맡는다.
근거: tasks/plan-shopping-japanese.md#인수 기준(JA-01·04·05, SHOP-07·08).
"""

import copy
import json
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.production import ai_draft_shopping as ads
from app.production import translate, videogen
from app.production.videogen.base import PollResult
from tests.production import test_ai_draft as base
from tests.production import test_translate as tr
from tests.production import test_videogen as vg
from tests.production.test_ai_draft import AiDB
from tests.production.test_ai_shopping import SENT_A, ai_out, shop_ready, tool_response
from tests.production.test_jobs_api import URL
from tests.production.test_shopping_api import JA_LINK, KO_LINK, done_run, publish
from tests.production.test_shopping_api import shop_job as pub_shop_job
from tests.production.test_validation_shopping import good as shop_spec

auth, claude, key, no_network = base.auth, base.claude, base.key, base.no_network
public_dns = vg.public_dns  # autouse: 결과 호스트 DNS 고정

# --- 픽스처(파일 안에서 db·api가 겹치지 않게 접두어를 쓴다) ------------------------------------


@pytest.fixture
def tdb() -> tr.TDB:
    return tr.TDB()


@pytest.fixture
def tapi(mock_supabase, jwks_payload, tdb, claude, key) -> Iterator[TestClient]:
    tr._routes(mock_supabase, tdb)
    with base._client(mock_supabase, jwks_payload, tdb, anthropic_api_key=key) as c:
        yield c
    assert all(call.request.url.host == "supabase.test" for call in mock_supabase.calls)


@pytest.fixture
def adb() -> AiDB:
    return AiDB(candidates=[{"id": base.CAND, "workspace_id": base.WS, "title": "후보"}])


@pytest.fixture
def aapi(mock_supabase, jwks_payload, adb, claude, key) -> Iterator[TestClient]:
    with base._client(mock_supabase, jwks_payload, adb, anthropic_api_key=key) as c:
        yield c
    assert all(call.request.url.host == "supabase.test" for call in mock_supabase.calls)


@pytest.fixture
def gdb() -> vg.GenDB:
    return vg.GenDB()


@pytest.fixture
def gadapter() -> vg.FakeAdapter:
    return vg.FakeAdapter()


@pytest.fixture
def gapi(mock_supabase, jwks_payload, gdb, gadapter) -> Iterator[TestClient]:
    with vg._client(
        mock_supabase,
        jwks_payload,
        gdb,
        gadapter,
        videogen_enabled=True,
        videogen_xai_api_key=vg.XAI_KEY,
    ) as c:
        yield c
    hosts = {call.request.url.host for call in mock_supabase.calls}
    assert hosts <= {"supabase.test", "vidgen.x.ai"}, hosts


def flat(obj: Any, prefix: str = "") -> dict[str, Any]:
    """spec을 리프 경로 → 값으로 편다(배열은 인덱스)."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            out.update(flat(v, f"{prefix}.{k}" if prefix else k))
        return out
    if isinstance(obj, list):
        out = {}
        for i, v in enumerate(obj):
            out.update(flat(v, f"{prefix}.{i}"))
        return out
    return {prefix: obj}


def changed_paths(ko: dict, ja: dict) -> set[str]:
    a, b = flat(ko), flat(ja)
    return {p for p in a.keys() | b.keys() if a.get(p, "<none>") != b.get(p, "<none>")}


# 번역 경로(…text, header.lines.N) 외에 달라도 되는 것: 언어 표시·음성·고지(J6)
ALLOWED_PREFIX = ("lang", "hook.tts", "hook.audio_asset_id", "voice", "disclosure", "header.lines")


def upload_audio(api, auth, db, jid: str, kind: str, rights: dict | None = None) -> str:
    body: dict[str, Any] = {"kind": kind, "size_bytes": 1024, "mime": "audio/wav"}
    if rights:
        body["rights"] = rights
    r = api.post(f"{URL}/{jid}/uploads", json=body, headers=auth)
    assert r.status_code == 201, r.text
    aid = r.json()["asset"]["id"]
    row = next(a for a in db.assets if a["id"] == aid)
    db.objects[row["storage_path"]] = 1024
    assert api.post(f"{URL}/{jid}/uploads/{aid}/complete", headers=auth).status_code == 200
    return aid


# === JA-01: 승인 ko → A-20 파생, 번역 경로 외 동일, 세 형식 =========================================


@pytest.mark.parametrize("fmt", ["category", "variety", "shopping"])
def test_ja01_derive_from_approved_ko_only_text_paths_differ(tapi, auth, tdb, claude, fmt):
    job, ko, ja = tr.derived(tapi, auth, tdb, claude, fmt)
    assert ko["approved_at"] is not None and ja["lang"] == "ja"
    assert ja["derived_from"] == ko["id"] and ja["approved_at"] is None
    diff = changed_paths(ko["spec"], ja["spec"])
    assert diff, "텍스트가 번역되지 않음"
    ko_slots, ja_slots = dict(translate.text_slots(fmt, ko["spec"])), dict(
        translate.text_slots(fmt, ja["spec"])
    )
    assert ko_slots.keys() == ja_slots.keys()
    texts = [p for p, t in ko_slots.items() if t.strip()]
    assert texts and all(ja_slots[p] != ko_slots[p] for p in texts)  # 번역 경로 값이 실제로 달라짐
    for p in diff:
        assert p.endswith(".text") or p.startswith(ALLOWED_PREFIX), f"번역 경로 밖 변경: {p}"
    # 컷·구도·시각·좌표 계열 키는 하나도 바뀌지 않는다
    frozen = ("cuts", "shots", "start", "end", "x", "y", "scale", "kind", "style", "masks")
    for p in diff:
        assert not any(seg in frozen for seg in p.split(".")), p
    assert translate.locked_errors(fmt, ja["spec"], ko["spec"]) == []
    assert ja["validation"]["errors"] == []


def test_ja01_boundary_ko_rev_kept_and_second_derive_makes_new_rev(tapi, auth, tdb, claude):
    job, ko, ja1 = tr.derived(tapi, auth, tdb, claude)
    before = copy.deepcopy(ko["spec"])
    tdb.jobs[0]["translate_requests"][0]["created_at"] = "2026-01-01T00:00:00+00:00"
    claude.replies = [tr.reply("category", ko["spec"])]
    r = tr.post(tapi, auth, job, ko["id"], k="tr-2")
    assert r.status_code == 201 and r.json()["revision"]["rev_no"] == 2
    assert ko["spec"] == before and ja1["rev_no"] == 1  # ko·기존 ja는 그대로


def test_ja01_failure_unapproved_ko_cannot_derive(tapi, auth, tdb, claude):
    job, ko = tr.MAKERS["category"](tdb)
    ko["approved_at"] = None
    r = tr.post(tapi, auth, job, ko["id"])
    assert r.status_code == 400 and r.json()["field"] == "revision_id"
    assert claude.calls == [] and job["current_ja_revision_id"] is None


def test_ja01_failure_added_number_twice_is_502_no_ja_revision(tapi, auth, tdb, claude):
    job, ko = tr.MAKERS["shopping"](tdb)

    def add(items: list) -> None:
        items[0]["text"] += " 100円"

    claude.replies = [tr.reply("shopping", ko["spec"], add)]
    r = tr.post(tapi, auth, job, ko["id"])
    assert r.status_code == 502 and job["current_ja_revision_id"] is None


# === JA-04: 초안 수정(A-12 lang=ja) → 승인(A-13), ja 녹음 참조 ======================================


def test_ja04_edit_draft_then_approve(tapi, auth, tdb, claude):
    job, ko, ja = tr.derived(tapi, auth, tdb, claude)
    spec = copy.deepcopy(ja["spec"])
    spec["hook"]["text"] = "直した一言"
    r = tr.put_ja(tapi, auth, job, spec)
    assert r.status_code == 200, r.text
    ap = tr.approve_ja(tapi, auth, job)
    assert ap.status_code == 200, ap.json()
    assert ja["approved_at"] is not None and ja["spec"]["hook"]["text"] == "直した一言"
    assert ko["approved_at"] is not None and job["status"] == "review"


def test_ja04_hook_audio_ja_recording_approvable_ko_recording_blocked(tapi, auth, tdb, claude):
    job, ko, ja = tr.derived(tapi, auth, tdb, claude)
    aid = upload_audio(tapi, auth, tdb, job["id"], "hook_audio")
    spec = copy.deepcopy(ja["spec"])
    spec["hook"] = {"text": spec["hook"]["text"], "audio_asset_id": aid}
    r = tr.put_ja(tapi, auth, job, spec)
    assert r.status_code == 200 and tr.codes(r.json()["revision"]["validation"]) == []
    assert tr.approve_ja(tapi, auth, job).status_code == 200
    # ko 녹음 참조(경계 반대편)는 승인 차단
    ko_audio = ko["spec"]["hook"]["audio_asset_id"]
    spec = copy.deepcopy(ja["spec"])
    spec["hook"] = {"text": spec["hook"]["text"], "audio_asset_id": ko_audio}
    put = tr.put_ja(tapi, auth, job, spec, base_no=1)  # 승인된 ja에서 새 리비전(rev2)
    assert put.status_code == 200 and "ja.voice_from_ko" in tr.codes(
        put.json()["revision"]["validation"]
    )
    r = tr.approve_ja(tapi, auth, job, rev_no=2)
    assert r.status_code == 400 and "ja.voice_from_ko" in tr.codes(r)


def test_ja04_shopping_narration_ja_recording_ok_even_when_ko_has_four(tapi, auth, tdb, claude):
    job, ko, ja = tr.derived(tapi, auth, tdb, claude, "shopping")
    ko_nar = ko["spec"]["voice"]["narration_asset_ids"]
    assert len(ko_nar) == 4  # ko가 녹음 4개를 가진 작업(상한 8)
    rights = {"basis": "own", "has_person": False}
    nar = [upload_audio(tapi, auth, tdb, job["id"], "narration", rights) for _ in range(4)]
    assert not set(nar) & set(ko_nar)
    spec = copy.deepcopy(ja["spec"])
    spec["voice"] = {"narration_asset_ids": nar}
    r = tr.put_ja(tapi, auth, job, spec)
    assert r.status_code == 200 and tr.codes(r.json()["revision"]["validation"]) == []
    assert tr.approve_ja(tapi, auth, job).status_code == 200
    assert ja["spec"]["voice"] == {"narration_asset_ids": nar} and ja["approved_at"] is not None


def test_ja04_shopping_ko_narration_reference_blocked(tapi, auth, tdb, claude):
    job, ko, ja = tr.derived(tapi, auth, tdb, claude, "shopping")
    spec = copy.deepcopy(ja["spec"])
    spec["voice"] = {"narration_asset_ids": ko["spec"]["voice"]["narration_asset_ids"]}
    assert tr.put_ja(tapi, auth, job, spec).status_code == 200
    r = tr.approve_ja(tapi, auth, job)
    assert r.status_code == 400 and "ja.voice_from_ko" in tr.codes(r) and ja["approved_at"] is None


def test_ja04_failure_locked_field_edit_rejected_not_saved(tapi, auth, tdb, claude):
    job, _, ja = tr.derived(tapi, auth, tdb, claude)
    before = copy.deepcopy(ja["spec"])
    spec = copy.deepcopy(ja["spec"])
    spec["shots"][0]["scale"] = 1.5
    r = tr.put_ja(tapi, auth, job, spec)
    assert r.status_code == 400 and "ja.locked_field" in tr.codes(r)
    assert ja["spec"] == before and tr.approve_ja(tapi, auth, job).status_code == 200


# === JA-05: ja 게시 문구(A-21) ====================================================================


def test_ja05_publish_text_ja_has_pr_and_only_ja_links(tapi, auth, tdb):
    amazon = "https://www.amazon.co.jp/dp/B0TEST0001?tag=aff-22"
    job = pub_shop_job(
        tdb,
        status="done",
        affiliates=[
            {"lang": "ko", "partner": "쿠팡", "url": KO_LINK},
            {"lang": "ja", "partner": "楽天", "url": JA_LINK},
            {"lang": "ja", "partner": "アマゾン", "url": amazon},
        ],
    )
    done_run(tdb, job, "ko")
    ja_run = done_run(tdb, job, "ja")
    r = publish(tapi, auth, job["id"], lang="ja")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["lang"] == "ja" and out["render_run_id"] == ja_run["id"]
    text = out["text"]
    assert text["caption"].splitlines()[0].startswith("【PR】")
    assert "PR" in text["caption"] and "[광고]" not in text["caption"]
    assert JA_LINK in text["pinned_comment"] and KO_LINK not in text["pinned_comment"]
    assert "楽天" in text["pinned_comment"] and "쿠팡" not in text["pinned_comment"]
    assert "アマゾン" in text["pinned_comment"] and amazon in text["pinned_comment"]


def test_ja05_boundary_no_ja_affiliate_means_empty_links_but_still_pr(tapi, auth, tdb):
    job = pub_shop_job(
        tdb, status="done", affiliates=[{"lang": "ko", "partner": "쿠팡", "url": KO_LINK}]
    )
    done_run(tdb, job, "ja")
    out = publish(tapi, auth, job["id"], lang="ja").json()["text"]
    assert out["caption"].startswith("【PR】")
    assert out["pinned_comment"] == "" and KO_LINK not in json.dumps(out, ensure_ascii=False)


def test_ja05_failure_ja_without_done_ja_run_is_409(tapi, auth, tdb):
    job = pub_shop_job(tdb, status="done")
    done_run(tdb, job, "ko")
    assert publish(tapi, auth, job["id"], lang="ja").status_code == 409


# === SHOP-07: AI 대본 3안(A-14 shopping) ==========================================================


def test_shop07_three_variants_distinct_hooks_pass_validation(aapi, auth, adb, claude):
    claude.replies = [tool_response(ai_out())]
    job, _ = shop_ready(adb)
    r = base.post(aapi, auth, job)
    assert r.status_code == 201, r.text
    body = r.json()
    hooks = [v["hook_type"] for v in body["variants"]]
    assert len(hooks) == 3 and len(set(hooks)) == 3 and set(hooks) <= set(ads.HOOK_TYPES)
    assert all(len(v["sentences"]) == 4 for v in body["variants"])
    assert body["revision"]["validation"]["errors"] == []
    assert body["revision"]["spec"]["script"] == [{"text": t} for t in SENT_A]


def test_shop07_boundary_exactly_four_sentences_each(aapi, auth, adb, claude):
    claude.replies = [tool_response(ai_out())]
    job, _ = shop_ready(adb)
    assert base.post(aapi, auth, job).status_code == 201
    out = ai_out()
    out["variants"][0]["sentences"].append("다섯 번째 문장이에요.")  # 5문장은 경계 밖
    claude.replies = [tool_response(out)]
    job2, _ = shop_ready(adb)
    r = base.post(aapi, auth, job2, k="ai-key-2")
    assert r.status_code == 502


def test_shop07_failure_duplicate_hook_type_is_502_error_path(aapi, auth, adb, claude):
    bad = ai_out()
    bad["variants"][1]["hook_type"] = bad["variants"][0]["hook_type"]
    claude.replies = [tool_response(bad)]
    job, _ = shop_ready(adb)
    revs = len(adb.revisions)
    r = base.post(aapi, auth, job)
    assert r.status_code == 502 and r.json()["code"] == "UPSTREAM_ERROR"
    assert len(adb.revisions) == revs and job["ai_draft_requests"][0]["status"] == "failed"


# === SHOP-08(API): AI 영상 생성 예산·미검수 승인 차단·검수 ==========================================


@pytest.mark.parametrize(("budget", "cap"), [(0, 6_000), (10_000, 0)])
def test_shop08_zero_budget_quote_409(gapi, auth, gdb, budget, cap):
    gdb.budget, gdb.cap = budget, cap
    job, img = vg.shop_job(gdb)
    r = vg.quote(gapi, auth, job, img)
    assert r.status_code == 409 and r.json()["field"] == "budget_exceeded"
    assert r.json()["remaining_krw"] == 0 and gdb.gen_runs == []


def test_shop08_over_budget_quote_409_and_boundary_exact_ok(gapi, auth, gdb, gadapter):
    gdb.cap = 579  # 5초 견적 580원 → 초과
    job, img = vg.shop_job(gdb)
    r = vg.quote(gapi, auth, job, img, duration_sec=5)
    assert r.status_code == 409 and r.json()["remaining_krw"] == 579
    gdb.cap = 580  # 경계: 딱 맞으면 통과
    assert vg.quote(gapi, auth, job, img, key="g-2", duration_sec=5).status_code == 201
    assert gadapter.submits == []  # 견적만으로는 제출하지 않는다


def _approve(api, auth, job: dict) -> httpx.Response:
    return api.post(f"{URL}/{job['id']}/revision/approve", json={"rev_no": 1}, headers=auth)


def test_shop08_unreviewed_ai_cut_blocks_approve_until_three_checks(
    gapi, auth, gdb, gadapter, mock_supabase
):
    mock_supabase.get(vg.RESULT_URL).mock(return_value=httpx.Response(200, content=vg.MP4))
    gadapter.poll_result = PollResult("done", video_url=vg.RESULT_URL)
    job, run_id, asset_id = vg._done_run(gapi, auth, gdb, gadapter, mock_supabase)
    assert next(a for a in gdb.assets if a["id"] == asset_id)["reviewed"] is False
    job["status"] = "review"
    # 준비 단계 산출물(파생 source)이 AI 컷 원본 — 권리·검수는 부모 업로드 값으로 본다
    child = gdb.add_asset(job, "source", created_by="w", parent_asset_id=asset_id, duration_sec=30)
    spec = shop_spec()
    for cut in spec["cuts"]:
        cut["source_asset_id"] = child["id"]
    rev = gdb.add_revision(job, spec=spec)
    # 미검수 → 승인 차단
    r = _approve(gapi, auth, job)
    assert r.status_code == 400 and "gen.unreviewed" in {e["code"] for e in r.json()["errors"]}
    assert rev["approved_at"] is None
    # 검수 3항목 중 하나라도 false → 여전히 차단
    path = f"{URL}/{job['id']}/generation-runs/{run_id}/review"
    r = gapi.post(path, json={"physics": True, "angle": False, "compare": True}, headers=auth)
    assert r.status_code == 200 and r.json()["reviewed"] is False
    r = _approve(gapi, auth, job)
    assert r.status_code == 400 and "gen.unreviewed" in {e["code"] for e in r.json()["errors"]}
    # 3항목 모두 통과 → 승인
    r = gapi.post(path, json={"physics": True, "angle": True, "compare": True}, headers=auth)
    assert r.status_code == 200 and r.json()["reviewed"] is True
    ap = _approve(gapi, auth, job)
    assert ap.status_code == 200, ap.json()
    assert rev["approved_at"] is not None


def test_shop08_failure_review_before_done_is_409(gapi, auth, gdb, gadapter):
    job, img = vg.shop_job(gdb)
    run_id = vg.running_run(gapi, auth, gdb, job, img)
    path = f"{URL}/{job['id']}/generation-runs/{run_id}/review"
    r = gapi.post(path, json={"physics": True, "angle": True, "compare": True}, headers=auth)
    assert r.status_code == 409
    assert uuid.UUID(run_id) and videogen is not None
