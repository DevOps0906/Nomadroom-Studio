# ruff: noqa: F401, F811
"""task-041 인수(API): 예능형 P1 VAR-06·07.

VAR-06 중 받아쓰기는 task-039 보류(Q10 기본값, PyAV GPL 동봉)라 "수동 입력 자막 -> AI 초안 -> 수정 저장"
과 "받아쓰기 없이 수동 입력만으로 끝까지"로 대체한다. Claude는 목, 네트워크 없음.
"""

import copy

import anthropic
import httpx

from tests.production.test_ai_draft import post
from tests.production.test_ai_draft_variety import (  # noqa: F401  (fixture 재사용)
    LINES,
    ai_out,
    api,
    auth,
    claude,
    db,
    key,
    no_network,
    tool_response,
    variety_ready,
)
from tests.production.test_jobs_api import URL, cur_updated_at


def save(api, auth, job: dict, spec: dict, base: int):
    return api.put(
        f"{URL}/{job['id']}/revision",
        json={
            "spec": spec,
            "base_rev_no": base,
            "base_updated_at": cur_updated_at(api, auth, job["id"]),
        },
        headers=auth,
    )


# === VAR-06 (받아쓰기 보류 -> 수동 입력으로 대체) =============================================


def test_var06_manual_dialogue_then_ai_draft_then_user_edit_saves(api, auth, db, claude):
    claude.replies = [tool_response(ai_out())]
    job, _ = variety_ready(db)
    r = post(api, auth, job)
    assert r.status_code == 201, r.text
    rev = r.json()["revision"]
    assert [s["text"] for s in rev["spec"]["subtitles"]] == ["둘째 대사", "첫 대사"]
    edited = copy.deepcopy(rev["spec"])
    edited["subtitles"][0]["text"] = "사용자가 고친 대사"
    s = save(api, auth, job, edited, rev["rev_no"])
    assert s.status_code == 200, s.text
    assert s.json()["revision"]["validation"]["errors"] == []
    assert s.json()["revision"]["spec"]["subtitles"][0]["text"] == "사용자가 고친 대사"


def test_var06_no_dialogue_is_manual_only_and_still_saves(api, auth, db, claude):
    """경계: 받아쓰기·대사 없음 -> 자막 비어도 초안 성공, 사용자가 수동으로 자막을 채워 저장."""
    claude.replies = [tool_response(ai_out(subtitles=[]))]
    job, _ = variety_ready(db, subtitles=[])
    r = post(api, auth, job)
    assert r.status_code == 201, r.text
    rev = r.json()["revision"]
    assert rev["spec"]["subtitles"] == [] and rev["validation"]["errors"] == []
    manual = copy.deepcopy(rev["spec"])
    manual["subtitles"] = [dict(LINES[0])]
    s = save(api, auth, job, manual, rev["rev_no"])
    assert s.status_code == 200 and s.json()["revision"]["validation"]["errors"] == []


def test_var06_ai_failure_keeps_user_revision_and_manual_save_still_works(api, auth, db, claude):
    """실패: AI 502여도 현재 리비전 유지, 수동 편집 저장으로 계속 진행."""
    req = httpx.Request("POST", "https://example.invalid/v1/messages")
    claude.replies = [anthropic.APIConnectionError(message="x", request=req)]
    job, rev1 = variety_ready(db)
    assert post(api, auth, job).status_code == 502
    assert job["current_revision_id"] == rev1["id"]
    manual = copy.deepcopy(rev1["spec"])
    manual["subtitles"][0]["text"] = "수동 수정"
    s = save(api, auth, job, manual, 1)
    assert s.status_code == 200 and s.json()["revision"]["validation"]["errors"] == []


# === VAR-07 ===============================================================================


def test_var07_ai_output_passes_variety_validation(api, auth, db, claude):
    claude.replies = [tool_response(ai_out())]
    job, _ = variety_ready(db)
    r = post(api, auth, job)
    assert r.status_code == 201
    assert r.json()["revision"]["validation"]["errors"] == []
    assert r.json()["revision"]["approved_at"] is None


def test_var07_cut_ending_exactly_at_segment_end_is_valid(api, auth, db, claude):
    """경계: 원본 길이(18초)에 정확히 끝나는 컷은 범위 안."""
    out = ai_out(cuts=[{"src_start": 0, "src_end": 18, "scale": 1, "x": 0, "y": 0}])
    claude.replies = [tool_response(out)]
    job, _ = variety_ready(db)
    r = post(api, auth, job)
    assert r.status_code == 201
    assert "cuts.out_of_range" not in [e["code"] for e in r.json()["revision"]["validation"]["errors"]]


def test_var07_invalid_ai_output_shows_field_paths(api, auth, db, claude):
    bad = ai_out()
    bad["cuts"][1]["src_end"] = 99  # 구간 밖
    bad["cuts"][1]["src_start"] = 98
    claude.replies = [tool_response(bad)]
    job, _ = variety_ready(db)
    r = post(api, auth, job)
    assert r.status_code == 201
    errors = r.json()["revision"]["validation"]["errors"]
    hit = [e for e in errors if e["code"] == "cuts.out_of_range"]
    assert hit and hit[0]["path"] == "cuts.1"


def test_var07_schema_violation_is_502_not_saved(api, auth, db, claude):
    claude.replies = [tool_response({"cuts": "x"}), tool_response({"cuts": "x"})]
    job, rev1 = variety_ready(db)
    revs = len(db.revisions)
    assert post(api, auth, job).status_code == 502
    assert len(db.revisions) == revs and job["current_revision_id"] == rev1["id"]
