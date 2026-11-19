"""task-021 편집안 검증 테스트(배포본 render.py validate() 순수 검증부 사본과 동등성 비교)."""

import copy
import math

import pytest

from app.production.spec import validate_spec

SRC_DUR = 60.0


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


def codes(r: dict, key: str = "errors") -> list[str]:
    return [e["code"] for e in r[key]]


def run(mut=None, **kw) -> dict:
    s = good()
    if mut:
        mut(s)
    return validate_spec(s, source_duration=SRC_DUR, **kw)


def test_good_has_no_errors_or_warnings():
    assert run() == {"errors": [], "warnings": []}


def test_not_dict():
    assert codes(validate_spec([])) == ["schema.type"]


def test_schema_error_has_path():
    r = run(lambda s: s.__setitem__("duration", "x"))
    assert r["errors"][0]["path"] == "duration"


def test_nan_rejected():
    assert run(lambda s: s.__setitem__("duration", math.nan))["errors"]


def test_bool_rejected_as_number():
    assert run(lambda s: s["shots"][0].__setitem__("y", True))["errors"]


def test_header_must_be_two_lines():
    assert run(lambda s: s["header"].__setitem__("lines", ["a"]))["errors"]


def test_header_newline_and_blank():
    r = run(lambda s: s["header"].__setitem__("lines", ["a\nb", "  "]))
    assert codes(r).count("header.lines.invalid") == 2


def test_hook_text_empty():
    assert "hook.text.empty" in codes(run(lambda s: s["hook"].__setitem__("text", " ")))


def test_hook_audio_xor():
    assert "hook.audio_xor" in codes(run(lambda s: s["hook"].pop("audio_asset_id")))

    def both(s):
        s["hook"]["tts"] = {"voice": "ko-KR-SunHiNeural"}

    assert "hook.audio_xor" in codes(run(both))


def test_hook_tts_only_ok():
    def m(s):
        s["hook"].pop("audio_asset_id")
        s["hook"]["tts"] = {"voice": "ko-KR-SunHiNeural"}

    assert run(m)["errors"] == []


@pytest.mark.parametrize(
    "tts",
    [
        {"voice": "ko-KR-SunHiNeural'><break time='9s'/>"},
        {"voice": "ko-KR-<SunHi>Neural"},
        {"voice": "ko-KR-SunHiNeural\n"},
        {"voice": "ko-KR-SunHiNeural", "rate": "+50%'>"},
        {"voice": "ko-KR-SunHiNeural", "rate": "+50%\n"},
        {"voice": "ko-KR-SunHiNeural", "rate": "<prosody>"},
    ],
)
def test_hook_tts_ssml_injection_rejected(tts):
    # task-030 리뷰 반영: voice·rate 형식 고정(SSML 주입·끝 개행 차단) → 검증 오류로 승인 막힘
    def m(s):
        s["hook"].pop("audio_asset_id")
        s["hook"]["tts"] = tts

    assert run(m)["errors"]


def test_hook_tts_rate_ok():
    def m(s):
        s["hook"].pop("audio_asset_id")
        s["hook"]["tts"] = {"voice": "ja-JP-NanamiNeural", "rate": "-10%"}

    assert run(m)["errors"] == []


def test_duration_range():
    assert "duration.range" in codes(run(lambda s: s.__setitem__("duration", 0.05)))
    assert "duration.range" in codes(run(lambda s: s.__setitem__("duration", 61)))
    assert "duration.range" in codes(validate_spec({**good(), "duration": 181}))


def test_shots_gap_overlap_end():
    assert "shots.gap" in codes(run(lambda s: s["shots"][1].__setitem__("start", 4.5)))
    assert "shots.overlap" in codes(run(lambda s: s["shots"][1].__setitem__("start", 3.5)))
    assert "shots.end" in codes(run(lambda s: s["shots"][1].__setitem__("end", 9)))


def test_shots_range_scale_y_blank():
    assert "shots.range" in codes(run(lambda s: s["shots"][1].__setitem__("end", 11)))
    assert "shots.scale" in codes(run(lambda s: s["shots"][0].__setitem__("scale", 3.5)))
    assert "shots.y" in codes(run(lambda s: s["shots"][0].__setitem__("y", 300)))
    assert "shots.blank" in codes(run(lambda s: s["shots"][0].__setitem__("y", -100)))


def test_shots_empty():
    assert "shots.empty" in codes(run(lambda s: s.__setitem__("shots", [])))


def test_items_overlap_range_first_not_zero():
    assert "items.overlap" in codes(run(lambda s: s["items"][1].__setitem__("start", 1.5)))
    assert "items.range" in codes(run(lambda s: s["items"][2].__setitem__("end", 11)))
    assert "items.first_not_zero" in codes(run(lambda s: s["items"][0].__setitem__("start", 0.5)))


def test_items_text_y_kind_empty():
    assert "items.text.empty" in codes(run(lambda s: s["items"][0].__setitem__("text", " ")))
    assert "items.text.newline" in codes(run(lambda s: s["items"][0].__setitem__("text", "a\nb")))
    assert "items.y" in codes(run(lambda s: s["items"][0].__setitem__("y", 100)))
    assert "items.y" in codes(run(lambda s: s["items"][0].__setitem__("y", 1031)))
    assert run(lambda s: s["items"][0].__setitem__("kind", "red"))["errors"]
    assert "items.empty" in codes(run(lambda s: s.__setitem__("items", [])))


def _short(s):
    s["items"][0]["end"] = 1.0
    s["items"][1]["start"] = 1.0


def test_short_item_is_warning_only():
    r = run(_short)
    assert r["errors"] == []
    assert codes(r, "warnings") == ["items.too_short"]


def test_warning_returned_even_with_errors():
    def m(s):
        _short(s)
        s["shots"] = []

    r = run(m)
    assert r["errors"] and codes(r, "warnings") == ["items.too_short"]


@pytest.mark.parametrize(
    "value", ["/etc/passwd", "C:\\x\\a.wav", "..", "../a", "a/../b", "https://x.com/a", "a/b"]
)
def test_path_and_url_rejected(value):
    r = run(lambda s: s["hook"].__setitem__("audio_asset_id", value))
    assert "path.forbidden" in codes(r)


def test_extra_path_field_rejected():
    assert run(lambda s: s.__setitem__("source", "source.mp4"))["errors"]


def test_uuid_asset_id_ok():
    uid = "0b9c1f2e-1111-4222-8333-444455556666"
    assert run(lambda s: s["hook"].__setitem__("audio_asset_id", uid))["errors"] == []


def test_lang_mismatch():
    assert "lang.mismatch" in codes(run(job_lang="ja"))
    assert run(job_lang="ko")["errors"] == []


def test_overlays_range_and_schema():
    ov = {"kind": "comment", "text": "t", "start": 1, "end": 3, "x": 10, "y": 20}
    assert run(lambda s: s.__setitem__("overlays", [ov]))["errors"] == []
    bad = {**ov, "end": 11}
    assert "overlays.range" in codes(run(lambda s: s.__setitem__("overlays", [bad])))
    assert run(lambda s: s.__setitem__("overlays", [{**ov, "kind": "x"}]))["errors"]


# ---- 배포본 validate() 동등성 (render.py 순수 검증부 사본, probe·resolve 제외) ----
def _numeric(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label)
    return float(value)


def ref_validate(project, meta_duration):
    if project.get("lang") not in ("ko", "ja"):
        raise ValueError("lang")
    header = project.get("header")
    if (
        not isinstance(header, list)
        or len(header) != 2
        or not all(isinstance(x, str) and x.strip() for x in header)
    ):
        raise ValueError("header")
    duration = _numeric(project.get("duration", meta_duration), "duration")
    if not 0.1 <= duration <= min(180, meta_duration + 0.05):
        raise ValueError("duration")
    shots = project.get("shots", [])
    if not shots:
        raise ValueError("shots")
    previous = 0.0
    for shot in shots:
        if not isinstance(shot, list) or len(shot) != 4:
            raise ValueError("shot format")
        start, end, zoom, y = (_numeric(v, "shot") for v in shot)
        if abs(start - previous) > 0.001 or end <= start or end > duration + 0.001:
            raise ValueError("shots continuity")
        if not 1 <= zoom <= 3 or y > 280 or y + 1080 * zoom < 1080 - 0.01:
            raise ValueError("shot transform")
        previous = end
    if abs(previous - duration) > 0.001:
        raise ValueError("shots end")
    items = project.get("items", [])
    if not items:
        raise ValueError("items")
    previous = 0.0
    for item in items:
        if not isinstance(item, list) or len(item) not in (4, 5):
            raise ValueError("caption format")
        start, end = _numeric(item[0], "s"), _numeric(item[1], "e")
        if start < previous - 0.001 or end <= start or end > duration + 0.001:
            raise ValueError("caption order")
        if item[2] not in ("white", "paren", "emph") or not str(item[3]).strip():
            raise ValueError("caption kind/text")
        if len(item) == 5 and not 310 <= _numeric(item[4], "y") <= 1030:
            raise ValueError("caption y")
        previous = end
    if abs(items[0][0]) > 0.001:
        raise ValueError("first caption")
    if not project.get("hook_audio") and not str(project.get("hook", "")).strip():
        raise ValueError("hook")
    if any("\n" in t for t in [*header, *(i[3] for i in items)]):
        raise ValueError("newline")


def to_project(s: dict) -> dict:
    """Nomadroom spec -> 배포본 project.json 형태(검증에 쓰는 필드만)."""
    return {
        "lang": s["lang"],
        "header": s["header"]["lines"],
        "hook": s["hook"]["text"],
        "hook_audio": "hook.wav",
        "duration": s["duration"],
        "shots": [[x["start"], x["end"], x["scale"], x["y"]] for x in s["shots"]],
        "items": [
            [i["start"], i["end"], i["kind"], i["text"], *([i["y"]] if "y" in i else [])]
            for i in s["items"]
        ],
    }


def _set(path_fn, key, value):
    return lambda s: path_fn(s).__setitem__(key, value)


CASES = {
    "ok": lambda s: None,
    "gap": _set(lambda s: s["shots"][1], "start", 4.5),
    "overlap": _set(lambda s: s["shots"][1], "start", 3.5),
    "short_end": _set(lambda s: s["shots"][1], "end", 9),
    "over_duration": _set(lambda s: s["shots"][1], "end", 11),
    "zoom": _set(lambda s: s["shots"][0], "scale", 3.5),
    "y_high": _set(lambda s: s["shots"][0], "y", 300),
    "blank": _set(lambda s: s["shots"][0], "y", -100),
    "cap_overlap": _set(lambda s: s["items"][1], "start", 1.5),
    "cap_range": _set(lambda s: s["items"][2], "end", 11),
    "first": _set(lambda s: s["items"][0], "start", 0.5),
    "cap_y": _set(lambda s: s["items"][1], "y", 100),
    "cap_blank": _set(lambda s: s["items"][0], "text", " "),
    "cap_kind": _set(lambda s: s["items"][0], "kind", "red"),
    "newline": _set(lambda s: s["items"][0], "text", "a\nb"),
    "header_blank": _set(lambda s: s["header"], "lines", ["a", " "]),
    "dur_small": _set(lambda s: s, "duration", 0.05),
    "dur_src": _set(lambda s: s, "duration", 61),
    "short_cap_only": _short,
}


@pytest.mark.parametrize("name", list(CASES))
def test_equivalent_to_distributed_validate(name):
    s = good()
    CASES[name](s)
    try:
        ref_validate(to_project(copy.deepcopy(s)), SRC_DUR)
        ref_ok = True
    except ValueError:
        ref_ok = False
    mine = validate_spec(s, source_duration=SRC_DUR)
    assert (mine["errors"] == []) is ref_ok, (name, mine)
