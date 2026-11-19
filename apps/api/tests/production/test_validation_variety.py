"""task-034 예능형 편집안 검증 테스트. 예제는 분석 문서 #2 컷 14개(x 정규화 → px = x×540)."""

import copy

from app.production.validation_variety import validate_for_format, validate_variety_spec

# (출력 길이, 원본 시작, 배율, x 정규화)
_CUTS = [
    (1.60, 24.77, 1.48, 0),
    (0.43, 27.17, 1.48, 0),
    (1.37, 2.00, 1.48, 0.48),
    (3.93, 15.40, 1.48, 0),
    (1.93, 19.33, 1.48, 0.28),
    (0.90, 21.27, 1.48, 0.28),
    (3.07, 24.73, 1.66, -0.06),
    (2.77, 33.10, 1.48, 0.45),
    (0.63, 39.13, 1.48, 0),
    (1.10, 39.80, 1.48, 0),
    (2.20, 41.00, 1.48, 0),
    (0.70, 43.30, 1.48, 0),
    (0.90, 44.00, 1.48, 0),
    (2.47, 46.13, 1.48, 0.28),
]


def good() -> dict:
    cuts = [
        {"src_start": s, "src_end": s + d, "scale": sc, "x": x * 540, "y": 0}
        for d, s, sc, x in _CUTS
    ]
    return {
        "lang": "ko",
        "header": {"lines": ["끼는 넘치는데", "바람은 못 피우는 사주ㅋㅋ"]},
        "cuts": cuts,
        "subtitles": [
            {"start": 0, "end": 1.6, "style": "line", "text": "대사"},
            {"start": 3, "end": 5, "style": "punch", "text": "펀치"},
        ],
        "reactions": [{"start": 1, "end": 2.5, "text": "(나는 왜?)", "x": 200, "y": 700}],
    }


def run(spec, **kw):
    kw.setdefault("segment_len", 51.5)
    return validate_variety_spec(spec, **kw)


def codes(res, key="errors"):
    return [e["code"] for e in res[key]]


def test_example_passes():
    r = run(good())
    assert r["errors"] == []
    assert [(w["code"], w["path"]) for w in r["warnings"]] == [("cuts.short", "cuts.1")]


def test_empty_area():
    for field, val in (("x", 900), ("y", 2000)):
        s = good()
        s["cuts"][0][field] = val
        assert "cuts.empty_area" in codes(run(s)), field


def test_empty_area_landscape_source():
    s = good()
    s["cuts"][0]["scale"] = 1.0  # 16:9 원본은 배율 1이면 띠 높이(816)를 못 채운다
    assert "cuts.empty_area" in codes(run(s, source_size=(1920.0, 1080.0)))


def test_out_of_range_and_short():
    s = good()
    s["cuts"][0]["src_end"] = 60
    assert "cuts.out_of_range" in codes(run(s))
    s = good()
    s["cuts"][1]["src_end"] = s["cuts"][1]["src_start"] + 0.1
    assert "cuts.too_short" in codes(run(s))
    s = good()
    s["cuts"][1]["src_end"] = s["cuts"][1]["src_start"] + 0.4
    r = run(s)
    assert "cuts.short" in codes(r, "warnings") and not r["errors"]


def test_count_and_total():
    s = good()
    s["cuts"] = []
    assert "cuts.count" in codes(run(s))
    s = good()
    s["cuts"] = [copy.deepcopy(s["cuts"][0]) for _ in range(61)]
    # task-035 리뷰: 61개 이상은 파싱 단계 스키마 상한(schema.too_long)
    assert codes(run(s, segment_len=None)) == ["schema.too_long"]
    s = good()
    s["cuts"] = [{"src_start": 0, "src_end": 50, "scale": 1.5, "x": 0, "y": 0}] * 4
    assert "cuts.total_too_long" in codes(run(s, segment_len=None))


def test_subtitles():
    s = good()
    s["subtitles"][1]["start"] = 1.0
    assert "subtitles.overlap" in codes(run(s))
    s = good()
    s["subtitles"][1]["end"] = 99
    assert "subtitles.out_of_range" in codes(run(s))
    s = good()
    s["subtitles"][0].update(text="  ", style="x")
    c = codes(run(s))
    assert "subtitles.empty_text" in c and "subtitles.style" in c
    s = good()
    s["subtitles"][1].update(start=4, end=4.5)  # 공백 허용, 0.5초 → 경고
    r = run(s)
    assert not r["errors"] and "subtitles.short" in codes(r, "warnings")


def test_reactions():
    s = good()
    s["reactions"][0]["x"] = 2000
    assert "reactions.out_of_range" in codes(run(s))
    s = good()
    s["reactions"].append({"start": 2, "end": 3, "text": "하", "x": 10, "y": 10})
    r = run(s)
    assert not r["errors"] and "reactions.overlap" in codes(r, "warnings")


def test_header_and_paths():
    s = good()
    s["header"]["lines"] = []
    assert "header.invalid" in codes(run(s))
    s["header"]["lines"] = ["a", "b", "c"]
    assert "header.invalid" in codes(run(s))
    s = good()
    s["preset_version"] = "C:/x/y"
    assert "path.forbidden" in codes(run(s))
    s = good()
    s["cuts"][0]["source_path"] = "videos/a.mp4"
    assert "schema.extra_forbidden" in codes(run(s))
    s = good()
    s["source_url"] = "https://x.test/a.mp4"
    assert "schema.extra_forbidden" in codes(run(s))


def test_dispatch():
    assert validate_for_format("variety", good(), segment_len=51.5)["errors"] == []
    assert "format.unknown" in codes(validate_for_format("x", {}))
    # 카테고리형은 기존 검증으로 간다(예능형 spec은 스키마 오류)
    r = validate_for_format("category", good())
    assert r["errors"] and all(e["code"].startswith(("schema.", "lang.")) for e in r["errors"])


def test_source_size_invalid():
    for size in ((0.0, 1920.0), (1080.0, -1.0), (float("nan"), 1920.0), (1080.0, float("inf"))):
        assert "source_size.invalid" in codes(run(good(), source_size=size))


def test_subtitle_short_tolerance_and_max_end_overlap():
    s = good()
    s["subtitles"] = [{"start": 6.8, "end": 8.2, "style": "line", "text": "경계"}]
    assert codes(run(s), "warnings") == ["cuts.short"]
    s = good()
    s["subtitles"] = [
        {"start": 0, "end": 10, "style": "line", "text": "a"},
        {"start": 1, "end": 2, "style": "line", "text": "b"},
        {"start": 3, "end": 4, "style": "line", "text": "c"},
    ]
    r = run(s)
    assert [e["path"] for e in r["errors"] if e["code"] == "subtitles.overlap"] == [
        "subtitles.1",
        "subtitles.2",
    ]


# === task-036 리뷰 반영: 줄 수 상한·비BMP 문자 거부(스키마 오류) ===================


def test_text_line_cap_three_lines():
    for field_name in ("subtitles", "reactions"):
        ok = good()
        ok[field_name][0]["text"] = "하나\n둘\r\n셋"
        assert run(ok)["errors"] == []
        for bad in (
            "a" + "\n" * 198,
            "하나\n둘\n셋\n넷",
            "하나\r둘\r셋\r넷",
            "하나\r\n둘\r\n셋\r\n넷",
        ):
            s = good()
            s[field_name][0]["text"] = bad
            assert codes(run(s)) == ["schema.value_error"], (field_name, bad)


def test_non_bmp_chars_rejected():
    emoji = "웃음 " + chr(0x1F602)
    for path in ("header", "subtitles", "reactions"):
        s = good()
        if path == "header":
            s["header"]["lines"][0] = emoji
        else:
            s[path][0]["text"] = emoji
        assert codes(run(s)) == ["schema.value_error"], path
    s = good()
    s["subtitles"][0]["text"] = "관상 " + chr(0x89C0) + chr(0x76F8)  # BMP 한자는 허용
    assert run(s)["errors"] == []
