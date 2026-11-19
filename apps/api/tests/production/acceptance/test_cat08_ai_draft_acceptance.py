# ruff: noqa: F401, F811
"""task-033 인수(API): AI 초안(A-14)이 TTS·오버레이·원본 참조가 있는 편집안과 함께 쓰일 때.

Claude는 SDK 가로채기 목(실제 네트워크 없음). 장면 설정은 test_ai_draft의 픽스처를 재사용한다.
"""

import json

import anthropic
import httpx
import pytest

from tests.production.test_ai_draft import (  # noqa: F401  (fixture 재사용)
    ai_output,
    api,
    auth,
    claude,
    db,
    key,
    no_network,
    post,
    ready_job,
    tool_response,
)

TTS = {"voice": "ko-KR-SunHiNeural", "rate": "+50%"}
COMMENT = {"kind": "comment", "text": "댓글 하나", "start": 2.0, "end": 6.0, "x": 304, "y": 550}


def job_with_tts_and_overlay(db):
    job, rev = ready_job(
        db, source_kind="url", source_url="https://www.youtube.com/watch?v=abcDEF12345"
    )
    rev["spec"]["hook"] = {"text": "사용자 훅", "tts": dict(TTS)}
    rev["spec"]["overlays"] = [COMMENT]
    return job, rev


def test_ai_draft_keeps_user_tts_choice_and_url_source_reference(api, auth, db, claude):
    """정상: AI가 훅 음성을 못 바꾼다(직전 리비전 tts 유지), 원본 URL 참조·자동 승인 없음."""
    job, rev1 = job_with_tts_and_overlay(db)
    r = post(api, auth, job)
    assert r.status_code == 201, r.text
    rev = r.json()["revision"]
    assert rev["spec"]["hook"]["tts"] == TTS and rev["approved_at"] is None
    assert job["source_kind"] == "url" and job["source_url"].startswith("https://www.youtube.com/")
    assert rev1["spec"]["overlays"] == [COMMENT]  # 직전 편집안(오버레이 포함)은 보관됨


def test_ai_draft_sends_only_jpeg_sheets_even_with_url_source(api, auth, db, claude):
    """경계: URL 원본 작업도 원본 영상·음성은 전송하지 않고 JPEG 시트만."""
    job, _ = job_with_tts_and_overlay(db)
    assert post(api, auth, job).status_code == 201
    blocks = claude.calls[0]["messages"][0]["content"]
    kinds = {b.get("source", {}).get("media_type") for b in blocks if b["type"] == "image"}
    assert kinds == {"image/jpeg"}
    assert "youtube.com" not in json.dumps(claude.calls[0]["system"])


def test_ai_draft_failure_502_leaves_tts_revision_intact(api, auth, db, claude):
    """실패: Claude 오류(502) 시 현재 리비전은 그대로(TTS·오버레이 편집안 보존)."""
    req = httpx.Request("POST", "https://example.invalid/v1/messages")
    claude.replies = [anthropic.APIConnectionError(message="x", request=req)]
    job, rev1 = job_with_tts_and_overlay(db)
    r = post(api, auth, job)
    assert r.status_code == 502
    assert job["current_revision_id"] == rev1["id"]
    assert rev1["spec"]["hook"]["tts"] == TTS


def test_ai_draft_keeps_existing_overlays(api, auth, db, claude):
    job, _ = job_with_tts_and_overlay(db)
    r = post(api, auth, job)
    assert r.status_code == 201
    assert r.json()["revision"]["spec"].get("overlays") == [COMMENT]
