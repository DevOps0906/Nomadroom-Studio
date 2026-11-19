"""task-032 overlays 검증: 범위·위치·문구, 같은 종류 겹침(오류), 자막과 시간·위치 겹침(경고)."""

from app.production.spec import validate_spec


def base() -> dict:
    return {
        "lang": "ko",
        "header": {"lines": ["제목 첫줄", "제목 둘째줄"]},
        "hook": {"text": "훅", "audio_asset_id": "a-1"},
        "duration": 10.0,
        "shots": [{"start": 0, "end": 10, "scale": 1.0, "y": 0}],
        "items": [{"start": 0, "end": 10, "kind": "white", "text": "자막"}],
    }


def ov(**kw) -> dict:
    return {"kind": "comment", "text": "댓글", "start": 1, "end": 3, "x": 304, "y": 550, **kw}


def run(*overlays: dict) -> dict:
    s = base()
    s["overlays"] = list(overlays)
    return validate_spec(s, source_duration=60.0)


def codes(r: dict, key: str = "errors") -> list[str]:
    return [e["code"] for e in r[key]]


def test_valid_overlay_has_no_issue():
    assert run(ov(), ov(kind="source", text="출처", y=900)) == {"errors": [], "warnings": []}


def test_range_errors():
    assert "overlays.range" in codes(run(ov(end=11)))
    assert "overlays.range" in codes(run(ov(start=-1)))
    assert "overlays.range" in codes(run(ov(start=3, end=3)))


def test_text_errors():
    assert "overlays.text.empty" in codes(run(ov(text=" ")))
    assert "overlays.text.newline" in codes(run(ov(text="a\nb")))
    assert "overlays.text.long" in codes(run(ov(text="가" * 41)))


def test_width_units_boundary():
    assert codes(run(ov(text="가" * 40))) == []
    assert codes(run(ov(text="W" * 40))) == []
    assert "overlays.text.long" in codes(run(ov(text="W" * 41)))
    assert codes(run(ov(text="." * 80))) == []  # 구두점은 1단위


def test_overlay_count_limit():
    many = [
        ov(kind="source" if i % 2 else "comment", start=i * 0.4, end=i * 0.4 + 0.3)
        for i in range(21)
    ]
    assert "overlays.count" in codes(run(*many))
    assert "overlays.count" not in codes(run(*many[:20]))


def test_position_out_of_screen():
    assert codes(run(ov(x=-1))) == ["overlays.pos"]
    assert codes(run(ov(y=1081))) == ["overlays.pos"]


def test_same_kind_overlap_is_error():
    r = run(ov(), ov(start=2, end=4))
    assert codes(r) == ["overlays.overlap"]
    assert r["errors"][0]["path"] == "overlays.1"


def test_adjacent_and_other_kind_are_ok():
    assert codes(run(ov(), ov(start=3, end=5))) == []
    assert codes(run(ov(), ov(kind="source", start=2, end=4, y=900))) == []


def test_caption_overlap_is_warning_only():
    r = run(ov(y=700))
    assert codes(r) == []
    assert codes(r, "warnings") == ["overlays.caption_overlap"]
    assert r["warnings"][0]["path"] == "overlays.0"


def test_caption_with_custom_y_and_time_gap():
    s = base()
    s["items"] = [{"start": 0, "end": 2, "kind": "white", "text": "자막", "y": 500}]
    s["overlays"] = [ov(y=550, start=3, end=5), ov(kind="source", y=500, start=3, end=5)]
    r = validate_spec(s, source_duration=60.0)
    assert codes(r, "warnings") == []  # 시간이 안 겹침
    s["overlays"] = [ov(y=520, start=1, end=3)]
    assert codes(validate_spec(s, source_duration=60.0), "warnings") == ["overlays.caption_overlap"]


def test_ref_must_not_be_path():
    assert "path.forbidden" in codes(run(ov(ref="https://x.test/a")))


def test_overlay_over_header_warns():
    r = run(ov(y=200))
    assert codes(r) == []
    assert codes(r, "warnings") == ["overlays.header_overlap"]
    assert r["warnings"][0]["path"] == "overlays.0"


def test_header_band_boundary():
    assert codes(run(ov(y=300)), "warnings") == ["overlays.header_overlap"]  # 카드 상단 270 < 280
    assert codes(run(ov(y=311)), "warnings") == []  # 카드 상단 281


def test_tts_voice_must_match_lang():
    s = base()
    s["hook"] = {"text": "훅", "tts": {"voice": "ja-JP-NanamiNeural", "rate": "+50%"}}
    assert codes(validate_spec(s, source_duration=60.0)) == ["hook.tts.voice_lang"]
    s["hook"]["tts"]["voice"] = "ko-KR-SunHiNeural"
    assert codes(validate_spec(s, source_duration=60.0)) == []
