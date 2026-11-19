# ruff: noqa: F401, F811
"""task-033 인수 테스트(API 쪽): CAT-08(P1: URL 원본·오버레이·TTS) + TTS 실패 복귀.

가짜 PostgREST·Storage(ProdDB)·가짜 Claude(SDK 가로채기, 실제 네트워크 없음)로 사용자 API·워커 API를
실제 라우터로 호출한다. 실제 DB·ffmpeg·워커는 실환경 실행(scratchpad acc033)이 맡는다.
근거: Nomadroom_Category_Shorts_PRD.md#5 CAT-08, tasks/task-029~032.md.
"""

import json
from typing import Any

import pytest

from tests.production.acceptance.test_cat_api_acceptance import (  # noqa: F401  (fixture 재사용)
    HOOK_ASSET,
    api,
    approved_job,
    auth,
    claim_render,
    cooldown,
    db,
    fail_render,
    make_asset_ready,
    post,
    prepare_to_review,
    put_spec,
    render_done,
    request_run,
    spec,
    start_job,
)
from tests.production.test_jobs_api import CAND, URL, WS
from tests.production.test_render_runs import ProdDB
from tests.production.test_worker_production import W

YT = "https://www.youtube.com/watch?v=abcDEF12345"
TTS = {"voice": "ko-KR-SunHiNeural", "rate": "+50%"}
# 자막 기본 y: emph 390, 그 외 700. 카드 높이 때문에 75px 안이면 겹침 경고(spec.py).
COMMENT = {
    "kind": "comment",
    "text": "댓글: 이거 실화냐",
    "start": 2.0,
    "end": 6.0,
    "x": 304,
    "y": 200,
}
SOURCE = {
    "kind": "source",
    "text": "출처: 합성 영상",
    "start": 0.0,
    "end": 15.0,
    "x": 304,
    "y": 1000,
}


def tts_spec(**over: Any) -> dict:
    s = spec(**over)
    s["hook"] = {"text": "이게 가능하다고?", "tts": dict(TTS)}
    return s


def codes(resp, kind: str = "errors") -> list[str]:
    return [e["code"] for e in resp.json()["revision"]["validation"][kind]]


def approve(api, auth, jid: str, rev_no: int):
    return post(api, auth, f"/{jid}/revision/approve", json={"rev_no": rev_no})


def url_job(api, auth, db: ProdDB, key: str = "cat08-url") -> dict:
    if not db.candidates:
        db.candidates.append({"id": CAND, "workspace_id": WS})
    r = post(
        api,
        auth,
        "",
        headers={"Idempotency-Key": key},
        json={
            "title": "URL 원본",
            "candidate_id": CAND,
            "source_kind": "url",
            "source_url": YT,
            "rights_confirmed": True,
            "source_start_sec": 30,
            "segment_len_sec": 15,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["job"]


def url_job_to_review(api, auth, db: ProdDB) -> dict:
    """URL 원본은 업로드 없이 prepare(워커가 내려받는다) → review. 원본 업로드 단계 없음."""
    from tests.production.test_worker_production import (
        PREPARE_ITEMS,
        claim,
        finish,
        item,
        outputs,
        upload_all,
    )

    job = url_job(api, auth, db)
    assert post(api, auth, f"/{job['id']}/prepare").status_code == 202
    task = claim(api).json()["task"]
    items = [item("source", "video/mp4", duration_sec=15.0), *PREPARE_ITEMS[1:]]
    ids = upload_all(db, outputs(api, "prepare", job["id"], items))
    meta = {"duration_sec": 15.0, "width": 1280, "height": 720, "has_audio": True}
    assert (
        finish(api, "prepare", job["id"], status="done", asset_ids=ids, meta=meta).status_code
        == 200
    )
    return task | {"job": job}


# === CAT-08 오버레이 ==================================================================


def test_cat08_overlays_saved_validated_and_sent_to_worker_unchanged(api, auth, db):
    """정상: 댓글·출처 오버레이가 검증 통과 후 승인본 그대로 워커 render task에 실린다."""
    job = start_job(api, auth, db)
    prepare_to_review(api, auth, db, job["id"])
    hook = make_asset_ready(api, auth, db, job["id"], "hook_audio", "audio/wav")
    s = spec(hook_asset=hook, overlays=[COMMENT, SOURCE])
    r = put_spec(api, auth, job["id"], s, 1)
    assert r.status_code == 200 and codes(r) == [] and codes(r, "warnings") == []
    rev = approve(api, auth, job["id"], 1)
    assert rev.status_code == 200, rev.text
    run = request_run(api, auth, job["id"], rev.json()["revision"]["id"], "k1").json()["render_run"]
    task = claim_render(api, run["id"])
    assert task["spec"]["overlays"] == [COMMENT, SOURCE]  # 출력물에 넣을 레이어가 그대로 전달
    render_done(api, db, run["id"])
    done = post(api, auth, f"/{job['id']}/review/approve")
    assert done.status_code == 200 and done.json()["job"]["status"] == "done"


def test_cat08_caption_overlap_is_warning_not_blocking(api, auth, db):
    """경계: 자막과 시간·위치가 겹치면 경고만(렌더는 막지 않음, task-032 결정). 위치 표시 확인."""
    job = start_job(api, auth, db)
    prepare_to_review(api, auth, db, job["id"])
    hook = make_asset_ready(api, auth, db, job["id"], "hook_audio", "audio/wav")
    near_caption = {**COMMENT, "start": 3.0, "end": 5.0, "y": 700}  # 자막(paren 2~8, y700)과 겹침
    r = put_spec(api, auth, job["id"], spec(hook_asset=hook, overlays=[near_caption]), 1)
    assert codes(r) == [] and codes(r, "warnings") == ["overlays.caption_overlap"]
    assert r.json()["revision"]["validation"]["warnings"][0]["path"] == "overlays.0"
    assert approve(api, auth, job["id"], 1).status_code == 200


def test_cat08_same_kind_overlap_blocks_approval_with_location(api, auth, db):
    """실패: 같은 종류 오버레이 구간이 겹치면 오류로 위치를 알리고 승인·렌더를 막는다."""
    job = start_job(api, auth, db)
    prepare_to_review(api, auth, db, job["id"])
    hook = make_asset_ready(api, auth, db, job["id"], "hook_audio", "audio/wav")
    a = {**COMMENT, "start": 1.0, "end": 5.0}
    b = {**COMMENT, "start": 4.0, "end": 8.0, "text": "다른 댓글"}
    r = put_spec(api, auth, job["id"], spec(hook_asset=hook, overlays=[a, b]), 1)
    errs = r.json()["revision"]["validation"]["errors"]
    assert [(e["code"], e["path"]) for e in errs] == [("overlays.overlap", "overlays.1")]
    ap = approve(api, auth, job["id"], 1)
    assert ap.status_code == 400 and ap.json()["code"] == "VALIDATION"
    assert db.runs == []


@pytest.mark.parametrize(
    "over, code",
    [
        ({"x": 700}, "overlays.pos"),
        ({"y": -5}, "overlays.pos"),
        ({"text": "두 줄\n입니다"}, "overlays.text.newline"),
        ({"text": ""}, "overlays.text.empty"),
        ({"end": 99}, "overlays.range"),
    ],
)
def test_cat08_invalid_overlay_fields_are_errors(api, auth, db, over, code):
    job = start_job(api, auth, db)
    prepare_to_review(api, auth, db, job["id"])
    r = put_spec(api, auth, job["id"], spec(overlays=[{**COMMENT, **over}]), 1)
    assert code in codes(r)


# === CAT-08 URL 원본 ===================================================================


def test_cat08_url_source_reference_survives_edit_render_and_done(api, auth, db):
    """원본 참조 유지: URL 원본 작업이 편집·렌더·검수 승인까지 source_url·source_kind를 지닌다."""
    task = url_job_to_review(api, auth, db)
    job = task["job"]
    assert task["source_kind"] == "url"
    hook = make_asset_ready(api, auth, db, job["id"], "hook_audio", "audio/wav")
    assert (
        put_spec(api, auth, job["id"], spec(hook_asset=hook, overlays=[COMMENT]), 1).status_code
        == 200
    )
    rev = approve(api, auth, job["id"], 1).json()["revision"]
    run = request_run(api, auth, job["id"], rev["id"], "k1").json()["render_run"]
    claim_render(api, run["id"])
    render_done(api, db, run["id"])
    assert post(api, auth, f"/{job['id']}/review/approve").status_code == 200
    row = db.job(job["id"])
    assert row["source_kind"] == "url" and row["source_url"] == YT and row["status"] == "done"
    assert row["candidate_id"] == CAND
    assert not any(a["kind"] == "source_upload" for a in db.assets)  # 업로드 없이 진행됨


@pytest.mark.parametrize(
    "bad_url",
    [
        "https://example.com/video.mp4",
        "http://www.youtube.com/watch?v=abcDEF12345",
        "https://169.254.169.254/latest",
        "https://www.youtube.com.evil.test/watch?v=x",
        "file:///etc/passwd",
    ],
)
def test_cat08_non_youtube_or_internal_url_is_400_and_not_stored(api, auth, db, bad_url):
    db.candidates.append({"id": CAND, "workspace_id": WS})
    r = post(
        api,
        auth,
        "",
        headers={"Idempotency-Key": "bad-url"},
        json={
            "title": "t",
            "source_kind": "url",
            "source_url": bad_url,
            "rights_confirmed": True,
            "source_start_sec": 0,
            "segment_len_sec": 15,
        },
    )
    assert r.status_code == 400 and r.json()["field"] == "source_url"
    assert db.jobs == []


def test_cat08_url_job_requires_rights_confirmation(api, auth, db):
    r = post(
        api,
        auth,
        "",
        headers={"Idempotency-Key": "no-rights"},
        json={
            "title": "t",
            "source_kind": "url",
            "source_url": YT,
            "rights_confirmed": False,
            "source_start_sec": 0,
            "segment_len_sec": 15,
        },
    )
    assert r.status_code == 400


# === TTS: 훅 음성 선택과 실패 복귀 ======================================================


def test_tts_spec_needs_no_hook_upload_and_tts_failed_returns_to_review_keeping_edit(api, auth, db):
    """TTS 편집안은 훅 업로드 없이 승인되고, tts_failed면 review로 복귀해 편집안 유지."""
    job = start_job(api, auth, db)
    prepare_to_review(api, auth, db, job["id"])
    s = tts_spec(overlays=[COMMENT, SOURCE])
    r = put_spec(api, auth, job["id"], s, 1)
    assert codes(r) == [], r.text
    rev = approve(api, auth, job["id"], 1).json()["revision"]
    run = request_run(api, auth, job["id"], rev["id"], "k1").json()["render_run"]
    task = claim_render(api, run["id"])
    assert task["spec"]["hook"]["tts"] == TTS and task["spec"]["hook"].get("audio_asset_id") is None
    inputs = api.get(f"{W}/render/{run['id']}/inputs", headers=_wauth()).json()["inputs"]
    assert "hook_audio" not in {i["kind"] for i in inputs}  # TTS면 첨부 음성 입력 없음
    fail_render(api, run["id"], "audio", "tts_failed")
    detail = api.get(f"{URL}/{job['id']}", headers=auth).json()
    assert detail["job"]["status"] == "review"
    assert detail["latest_run"]["error_code"] == "tts_failed"
    got = api.get(f"{URL}/{job['id']}/revision", headers=auth).json()["revision"]
    assert got["spec"] == task["spec"] and got["approved_at"] is not None
    retry = post(api, auth, f"/{job['id']}/render-runs/{run['id']}/retry")
    assert retry.status_code == 409  # 같은 TTS로 자동 재시도 불가 — 편집(첨부 전환)이 정본 경로


def test_tts_failed_then_switch_to_attached_voice_reapprove_and_render_succeeds(api, auth, db):
    """복귀 경로: tts_failed → 첨부 음성으로 바꿔 새 리비전 → 재승인 → 렌더 성공 → 검수 승인."""
    job = start_job(api, auth, db)
    prepare_to_review(api, auth, db, job["id"])
    put_spec(api, auth, job["id"], tts_spec(overlays=[COMMENT]), 1)
    rev1 = approve(api, auth, job["id"], 1).json()["revision"]
    run1 = request_run(api, auth, job["id"], rev1["id"], "k1").json()["render_run"]
    claim_render(api, run1["id"])
    fail_render(api, run1["id"], "audio", "tts_failed")
    # 첨부 음성을 올리고 hook.tts를 뺀 새 편집안(승인본 수정 → 새 리비전 2)
    hook = make_asset_ready(api, auth, db, job["id"], "hook_audio", "audio/wav")
    r = put_spec(api, auth, job["id"], spec(hook_asset=hook, overlays=[COMMENT]), 1)
    assert r.status_code == 200 and r.json()["revision"]["rev_no"] == 2 and codes(r) == []
    assert "tts" not in r.json()["revision"]["spec"]["hook"]
    rev2 = approve(api, auth, job["id"], 2).json()["revision"]
    cooldown(db)
    run2 = request_run(api, auth, job["id"], rev2["id"], "k2")
    assert run2.status_code == 202 and run2.json()["render_run"]["attempt"] == 1
    task = claim_render(api, run2.json()["render_run"]["id"])
    assert task["spec"]["hook"]["audio_asset_id"] == hook and "tts" not in task["spec"]["hook"]
    render_done(api, db, run2.json()["render_run"]["id"])
    done = post(api, auth, f"/{job['id']}/review/approve")
    assert done.status_code == 200 and done.json()["job"]["status"] == "done"


def test_tts_and_attached_voice_together_is_error(api, auth, db):
    """경계: 첨부 음성과 TTS를 동시에 지정하면 hook.audio_xor 오류로 승인을 막는다."""
    job = start_job(api, auth, db)
    prepare_to_review(api, auth, db, job["id"])
    hook = make_asset_ready(api, auth, db, job["id"], "hook_audio", "audio/wav")
    both = spec(hook_asset=hook)
    both["hook"]["tts"] = dict(TTS)
    r = put_spec(api, auth, job["id"], both, 1)
    assert "hook.audio_xor" in codes(r)
    assert approve(api, auth, job["id"], 1).status_code == 400
    neither = spec(hook_asset=None)
    assert "hook.audio_xor" in codes(put_spec(api, auth, job["id"], neither, 1))


@pytest.mark.parametrize(
    "tts",
    [
        {"voice": "ko-KR-SunHiNeural</voice><x>", "rate": "+50%"},
        {"voice": "ko-KR-SunHiNeural", "rate": "+50%\n"},
        {"voice": "ko-KR-SunHiNeural", "rate": "fast"},
        {"voice": "../etc/passwd", "rate": "+0%"},
    ],
)
def test_tts_voice_and_rate_injection_is_rejected_at_save(api, auth, db, tts):
    """실패: SSML 주입 가능한 voice·rate는 저장 단계에서 거부(워커 도달 전)."""
    job = start_job(api, auth, db)
    prepare_to_review(api, auth, db, job["id"])
    s = spec(hook_asset=None)
    s["hook"] = {"text": "훅", "tts": tts}
    r = put_spec(api, auth, job["id"], s, 1)
    assert r.status_code == 400 or any(c.startswith("schema.") for c in codes(r)), r.text


def _wauth() -> dict:
    from tests.production.test_render_runs import wauth

    return wauth()


# === 종단 순서(API 한 작업): URL 원본 → 오버레이·TTS → tts_failed → 첨부 → 완료 ===========


def test_cat08_full_story_url_overlay_tts_fail_attach_done(api, auth, db):
    task = url_job_to_review(api, auth, db)
    job = task["job"]
    r = put_spec(api, auth, job["id"], tts_spec(overlays=[COMMENT, SOURCE]), 1)
    assert codes(r) == [] and codes(r, "warnings") == []
    rev1 = approve(api, auth, job["id"], 1).json()["revision"]
    run1 = request_run(api, auth, job["id"], rev1["id"], "k1").json()["render_run"]
    claim_render(api, run1["id"])
    fail_render(api, run1["id"], "audio", "tts_failed")
    assert db.job(job["id"])["status"] == "review"
    hook = make_asset_ready(api, auth, db, job["id"], "hook_audio", "audio/wav")
    put_spec(api, auth, job["id"], spec(hook_asset=hook, overlays=[COMMENT, SOURCE]), 1)
    rev2 = approve(api, auth, job["id"], 2).json()["revision"]
    cooldown(db)
    run2 = request_run(api, auth, job["id"], rev2["id"], "k2").json()["render_run"]
    claim_render(api, run2["id"])
    render_done(api, db, run2["id"])
    assert post(api, auth, f"/{job['id']}/review/approve").status_code == 200
    row = db.job(job["id"])
    assert row["status"] == "done" and row["source_url"] == YT
    assert HOOK_ASSET  # (spec 헬퍼 상수 import 유지)
    assert json.loads(json.dumps(db.revisions[-1]["spec"]))["overlays"] == [COMMENT, SOURCE]


@pytest.mark.xfail(
    strict=True,
    reason="결함 후보(🟡): 제목(header, 화면 위쪽 y≈130~260)과 겹치는 오버레이는 경고도 없다. "
    "실환경 프레임(acc033 A_t4)에서 y=200 댓글 카드가 제목 글자를 가렸다. 자막만 검사한다.",
)
def test_cat08_overlay_covering_header_warns(api, auth, db):
    job = start_job(api, auth, db)
    prepare_to_review(api, auth, db, job["id"])
    hook = make_asset_ready(api, auth, db, job["id"], "hook_audio", "audio/wav")
    r = put_spec(api, auth, job["id"], spec(hook_asset=hook, overlays=[COMMENT]), 1)
    assert codes(r, "warnings") != []
