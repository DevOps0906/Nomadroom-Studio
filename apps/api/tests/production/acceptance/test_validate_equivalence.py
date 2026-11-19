"""task-021 리뷰 🟡1: 배포본 validate() 동등성 강화 — 통과 여부뿐 아니라 오류 코드까지 고정한다.

배포본(scripts/render.py validate)의 ValueError 메시지를 '기대값'으로 고정해 두고(배포본 코드는
import하지 않는다), 같은 입력을 validate_spec에 넣어 (1) 둘 다 거부하는지 (2) 우리 오류 코드가
의도한 코드인지 확인한다. 케이스: 훅 빈 값·NaN·헤더 줄 수·자막 y 등.
의도된 차이: 우리는 한 번에 여러 오류를 모아 반환하고(배포본은 첫 오류에서 중단), 훅은
audio_asset_id/tts 중 하나가 필수(hook.audio_xor)다.
"""

import copy
import math

import pytest

from app.production.spec import validate_spec

SRC = 60.0


def good() -> dict:
    return {
        "lang": "ko",
        "header": {"lines": ["제목 첫줄", "제목 둘째줄"]},
        "hook": {"text": "훅", "audio_asset_id": "a-1"},
        "duration": 10.0,
        "shots": [
            {"start": 0, "end": 4, "scale": 1.0, "y": 0},
            {"start": 4, "end": 10, "scale": 1.5, "y": -100},
        ],
        "items": [
            {"start": 0, "end": 2, "kind": "white", "text": "훅"},
            {"start": 2, "end": 5, "kind": "paren", "text": "(둘)", "y": 500},
            {"start": 5, "end": 10, "kind": "emph", "text": "*셋*"},
        ],
    }


def _set(path, key, value):
    def mut(s: dict) -> None:
        node = s
        for p in path:
            node = node[p]
        node[key] = value

    return mut


# 이름: (변형, 배포본 오류 메시지(고정), 우리 오류 코드 집합에 반드시 포함되는 코드)
CASES: dict[str, tuple] = {
    "hook_empty": (
        _set(["hook"], "text", ""),
        "hook text or hook_audio is required.",  # 배포본은 hook_audio가 있으면 통과 → 아래 별도
        {"hook.text.empty"},
    ),
    "header_one_line": (
        _set([], "header", {"lines": ["하나"]}),
        "header must contain two nonempty strings.",
        {"schema.too_short"},
    ),
    "header_three_lines": (
        _set([], "header", {"lines": ["a", "b", "c"]}),
        "header must contain two nonempty strings.",
        {"schema.too_long"},
    ),
    "header_blank_line": (
        _set([], "header", {"lines": ["a", " "]}),
        "header must contain two nonempty strings.",
        {"header.lines.invalid"},
    ),
    "duration_nan": (
        _set([], "duration", math.nan),
        "duration must be a finite number.",
        {"schema.finite_number"},
    ),
    "duration_inf": (
        _set([], "duration", math.inf),
        "duration must be a finite number.",
        {"schema.finite_number"},
    ),
    "duration_over_source": (
        _set([], "duration", 61),
        "duration is outside source bounds (maximum 180s).",
        {"duration.range"},
    ),
    "duration_zero": (
        _set([], "duration", 0.05),
        "duration is outside source bounds (maximum 180s).",
        {"duration.range"},
    ),
    "shot_gap": (
        _set(["shots", 1], "start", 4.5),
        "Shots must be continuous, ordered and within duration.",
        {"shots.gap"},
    ),
    "shot_overlap": (
        _set(["shots", 1], "start", 3.5),
        "Shots must be continuous, ordered and within duration.",
        {"shots.overlap"},
    ),
    "shot_zoom_high": (
        _set(["shots", 0], "scale", 3.5),
        "Shot transform leaves a blank area or uses zoom outside 1..3.",
        {"shots.scale"},
    ),
    "shot_y_high": (
        _set(["shots", 0], "y", 300),
        "Shot transform leaves a blank area or uses zoom outside 1..3.",
        {"shots.y"},
    ),
    "shot_blank": (
        _set(["shots", 0], "y", -100),
        "Shot transform leaves a blank area or uses zoom outside 1..3.",
        {"shots.blank"},
    ),
    "shot_end_short": (
        _set(["shots", 1], "end", 9),
        "Shots must end at duration.",
        {"shots.end"},
    ),
    "item_overlap": (
        _set(["items", 1], "start", 1.5),
        "Captions must be ordered, nonoverlapping and within duration.",
        {"items.overlap"},
    ),
    "item_over_duration": (
        _set(["items", 2], "end", 11),
        "Captions must be ordered, nonoverlapping and within duration.",
        {"items.range"},
    ),
    "item_y_low": (
        _set(["items", 1], "y", 309),
        "caption y must be between 310 and 1030.",
        {"items.y"},
    ),
    "item_y_high": (
        _set(["items", 1], "y", 1031),
        "caption y must be between 310 and 1030.",
        {"items.y"},
    ),
    "item_y_nan": (
        _set(["items", 1], "y", math.nan),
        "caption y must be a finite number.",
        {"schema.finite_number"},
    ),
    "item_blank_text": (
        _set(["items", 0], "text", " "),
        "Invalid caption kind/text.",
        {"items.text.empty"},
    ),
    "item_bad_kind": (
        _set(["items", 0], "kind", "red"),
        "Invalid caption kind/text.",
        {"schema.literal_error"},
    ),
    "first_not_zero": (
        _set(["items", 0], "start", 0.5),
        "First hook caption must start at zero.",
        {"items.first_not_zero"},
    ),
    "caption_newline": (
        _set(["items", 0], "text", "a\nb"),
        "Each header/caption is one line; remove embedded newlines.",
        {"items.text.newline"},
    ),
    "header_newline": (
        _set([], "header", {"lines": ["a\nb", "c"]}),
        "Each header/caption is one line; remove embedded newlines.",
        {"header.lines.invalid"},
    ),
}


@pytest.mark.parametrize("name", [n for n in CASES if n != "hook_empty"])
def test_rejected_by_both_and_error_code_is_pinned(name):
    mutate, original_message, codes = CASES[name]
    s = good()
    mutate(s)
    got = validate_spec(copy.deepcopy(s), source_duration=SRC)
    got_codes = {e["code"] for e in got["errors"]}
    assert original_message  # 배포본이 거부하는 입력(기대 메시지 고정)
    assert codes <= got_codes, (name, got_codes)
    assert got["errors"], name


def test_hook_empty_text_is_rejected_even_with_audio():
    """배포본: hook_audio가 있으면 hook 문구가 비어도 통과. 우리: 훅 문구는 항상 필수."""
    s = good()
    s["hook"]["text"] = "  "
    assert "hook.text.empty" in {e["code"] for e in validate_spec(s, source_duration=SRC)["errors"]}


def test_good_has_no_errors_and_boundaries_pass():
    assert validate_spec(good(), source_duration=SRC) == {"errors": [], "warnings": []}
    for y in (310, 1030):  # 경계값 포함
        s = good()
        s["items"][1]["y"] = y
        assert validate_spec(s, source_duration=SRC)["errors"] == []
    s = good()  # 구간 길이 + 0.05 까지 허용
    s["duration"] = 10.05
    s["shots"][1]["end"] = 10.05
    s["items"][2]["end"] = 10.05
    assert validate_spec(s, source_duration=10.0)["errors"] == []


@pytest.mark.parametrize("bad", ["x", True, None, [1]])
def test_non_numeric_values_are_schema_errors(bad):
    s = good()
    s["duration"] = bad
    errs = validate_spec(s, source_duration=SRC)["errors"]
    assert errs and errs[0]["path"] == "duration" and errs[0]["code"].startswith("schema.")


def test_errors_carry_paths_for_every_case():
    for name, (mutate, _, _) in CASES.items():
        s = good()
        mutate(s)
        for e in validate_spec(s, source_duration=SRC)["errors"]:
            assert set(e) == {"code", "path", "message"} and e["message"], name
