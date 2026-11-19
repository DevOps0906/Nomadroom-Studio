"""task-043 쇼핑 편집안 검증 테스트."""

import copy

from app.production.validation_shopping import validate_shopping_spec
from app.production.validation_variety import validate_for_format

_SENT = [
    "퇴근하면 발이 너무 퍼져서 고민이었는데 이걸 신고 달라졌어요.",
    "처음엔 반신반의했는데 일주일 신어 보니 발바닥이 편하더라고요.",
    "오래 서 있는 날에도 피로가 덜해서 매일 챙겨 신고 다녀요.",
    "궁금하신 분은 프로필 링크에서 후기를 확인해 보세요.",
]


def _assets() -> dict:
    ok = {"basis": "own", "has_person": False}
    return {
        "a1": {"kind": "source", "status": "ready", "duration_sec": 30, "rights": ok},
        "a2": {"kind": "source_upload", "status": "ready", "duration_sec": 30, "rights": ok},
        "a3": {"kind": "image", "status": "ready", "rights": ok},
        "n1": {"kind": "narration", "status": "ready", "rights": None},
        "b1": {"kind": "bgm", "status": "ready", "rights": {"basis": "licensed"}},
    }


def good() -> dict:
    srcs = ["a1", "a2", "a3", "a1"]
    return {
        "lang": "ko",
        "script": [{"text": t} for t in _SENT],
        "cuts": [
            {
                "source_asset_id": a,
                "src_start": 0,
                "src_end": 4,
                "scale": 1,
                "x": 0,
                "y": 0,
                "sentence": n,
            }
            for n, a in enumerate(srcs, 1)
        ],
        "voice": {"tts": {"voice": "ko-KR-SunHiNeural", "rate": "+0%"}},
        "cta": {"text": "프로필 링크 확인"},
        "disclosure": {"text": "제휴 링크 포함"},
    }


def codes(r: dict, key: str = "errors") -> list[str]:
    return [x["code"] for x in r[key]]


def run(spec: dict, **kw) -> dict:
    kw.setdefault("assets", _assets())
    return validate_shopping_spec(spec, **kw)


def test_good_spec_clean() -> None:
    assert len("".join(_SENT)) in range(110, 141)
    r = run(good(), product_name="신발")
    assert r == {"errors": [], "warnings": []}


def test_script_count_error() -> None:
    s = good()
    s["script"].pop()
    assert "script.count" in codes(run(s))


def test_script_length_warning() -> None:
    s = good()
    s["script"][0]["text"] = "짧다"
    r = run(s)
    assert "script.length" in codes(r, "warnings")
    assert r["errors"] == []


def test_script_unverified_error() -> None:
    s = good()
    s["script"][1]["text"] += " [확인 필요]"
    assert "script.unverified" in codes(run(s))


def test_banned_phrase_and_product_in_first_warn() -> None:
    s = good()
    s["script"][2]["text"] = "이건 인생템이라 강력 추천해요"
    s["script"][0]["text"] = "에어쿠션 신발 이야기" + s["script"][0]["text"]
    r = run(s, product_name="에어쿠션")
    w = codes(r, "warnings")
    assert w.count("script.banned_phrase") == 2
    assert "script.product_in_first" in w
    assert r["errors"] == []


def test_ja_skips_length_warning() -> None:
    s = good()
    s["lang"] = "ja"
    s["script"][0]["text"] = "短い"
    assert "script.length" not in codes(run(s, job_lang="ja"), "warnings")


def test_sentence_mapping() -> None:
    s = good()
    s["cuts"][3]["sentence"] = 1
    r = run(s)
    assert codes(r).count("cuts.sentence_empty") == 1
    s["cuts"][3]["sentence"] = 5
    assert "cuts.sentence_invalid" in codes(run(s))


def test_sources_few_warning() -> None:
    s = good()
    s["cuts"][2]["source_asset_id"] = "a1"
    assert "sources.few" in codes(run(s), "warnings")


def test_source_invalid_and_range() -> None:
    s = good()
    s["cuts"][0]["source_asset_id"] = "zzz"
    s["cuts"][1]["src_end"] = 31
    s["cuts"][2]["source_asset_id"] = "n1"
    r = run(s)
    assert codes(r).count("cuts.source_invalid") == 2
    assert "cuts.out_of_range" in codes(r)


def test_masks_range() -> None:
    s = good()
    s["cuts"][0]["masks"] = [
        {"x": 0, "y": 1900, "w": 1080, "h": 100},
        {"x": 0, "y": 0, "w": 10, "h": 10},
    ]
    r = run(s)
    assert [x["path"] for x in r["errors"] if x["code"] == "masks.out_of_range"] == [
        "cuts.0.masks.0"
    ]


def test_empty_area() -> None:
    s = good()
    s["cuts"][0]["x"] = 300
    assert "cuts.empty_area" in codes(run(s))
    s = good()
    a = _assets()
    a["a1"].update(width=1920, height=1080)  # 가로 영상은 scale 1로 위아래가 빈다
    assert "cuts.empty_area" in codes(run(s, assets=a))


def test_voice_xor() -> None:
    s = good()
    s["voice"] = {}
    assert "voice.missing" in codes(run(s))
    s["voice"] = {"tts": {"voice": "ko-KR-SunHiNeural", "rate": "+0%"}, "narration_asset_id": "n1"}
    assert "voice.both" in codes(run(s))
    s["voice"] = {"narration_asset_id": "n1"}
    assert run(s)["errors"] == []
    s["voice"] = {"narration_asset_id": "a1"}
    assert "voice.asset_invalid" in codes(run(s))
    a = _assets()
    a["n1"]["status"] = "pending"
    s["voice"] = {"narration_asset_id": "n1"}
    assert "voice.asset_invalid" in codes(run(s, assets=a))


def test_image_motion() -> None:
    s = good()
    s["cuts"][2]["motion"] = {"type": "pan"}
    assert run(s)["errors"] == []
    s["cuts"][2]["motion"] = {"type": "spin"}
    assert "cuts.motion_invalid" in codes(run(s))
    s = good()
    s["cuts"][0]["motion"] = {"type": "zoom"}
    assert "cuts.motion_invalid" in codes(run(s))


def test_cta_disclosure_empty() -> None:
    s = good()
    s["cta"] = {"text": " "}
    del s["disclosure"]
    assert {"cta.empty", "disclosure.empty"} <= set(codes(run(s)))


def test_rights_conditions() -> None:
    a = _assets()
    a["a1"]["rights"] = None
    a["a2"]["rights"] = {"basis": "permission", "has_person": True}
    assert {"rights.missing", "rights.portrait_consent"} <= set(codes(run(good(), assets=a)))
    a["a2"]["rights"]["portrait_consent"] = True
    a["a1"]["rights"] = {"basis": "quote"}
    assert run(good(), assets=a)["errors"] == []


def test_gen_unreviewed() -> None:
    a = _assets()
    a["a2"]["rights"] = {"basis": "ai_generated"}
    assert {"gen.missing", "gen.unreviewed"} <= set(codes(run(good(), assets=a)))
    a["a2"]["rights"]["gen"] = {"platform": "p", "model": "m", "request_id": "r", "cost_krw": 1000}
    assert codes(run(good(), assets=a)) == ["gen.unreviewed"]
    a["a2"]["reviewed"] = True
    assert run(good(), assets=a)["errors"] == []


def test_bgm() -> None:
    s = good()
    s["bgm_asset_id"] = "b1"
    s["source_audio"] = "duck"
    assert run(s)["errors"] == []
    a = _assets()
    a["b1"]["rights"] = {}
    assert "bgm.rights_missing" in codes(run(s, assets=a))
    s["bgm_asset_id"] = "a1"
    assert "bgm.asset_invalid" in codes(run(s))


def test_schema_and_untrusted_text() -> None:
    s = good()
    s["script"][0]["text"] = "이모지😀"
    s["script"][1]["text"] = "제어\x07문자"
    r = run(s)
    assert codes(r) == ["schema.value_error", "schema.value_error"]
    s = good()
    s["extra"] = 1
    assert codes(run(s)) == ["schema.extra_forbidden"]
    assert codes(validate_shopping_spec([], assets={})) == ["schema.type"]


def test_path_forbidden_and_lang() -> None:
    s = good()
    s["cuts"][0]["source_asset_id"] = "https://x/y"
    s["lang"] = "ja"
    r = run(s, job_lang="ko")
    assert {"path.forbidden", "lang.mismatch"} <= set(codes(r))


def test_format_branch_requires_assets() -> None:
    r = validate_for_format("shopping", good())
    assert codes(r) == ["assets.required"]
    r = validate_for_format("shopping", copy.deepcopy(good()), assets=_assets())
    assert r["errors"] == []
    bad = {**good(), "script": []}
    assert "script.count" in codes(validate_for_format("shopping", bad, assets=_assets()))


def test_assets_empty_means_everything_invalid() -> None:
    s = good()
    s["bgm_asset_id"] = "b1"
    s["voice"] = {"narration_asset_id": "n1"}
    r = run(s, assets={})
    c = codes(r)
    assert c.count("cuts.source_invalid") == 4
    assert {"bgm.asset_invalid", "voice.asset_invalid"} <= set(c)


def test_not_ready_assets() -> None:
    a = _assets()
    for k in ("a1", "b1", "n1"):
        a[k]["status"] = "pending"
    s = good()
    s["bgm_asset_id"] = "b1"
    s["voice"] = {"narration_asset_id": "n1"}
    c = codes(run(s, assets=a))
    assert {"cuts.source_invalid", "bgm.asset_invalid", "voice.asset_invalid"} <= set(c)


def test_video_without_duration_invalid() -> None:
    a = _assets()
    a["a1"]["duration_sec"] = None
    assert "cuts.source_invalid" in codes(run(good(), assets=a))


def test_unverified_in_cta_and_disclosure() -> None:
    s = good()
    s["cta"] = {"text": "가격 [확인 필요]"}
    s["disclosure"] = {"text": "[확인 필요]"}
    paths = [x["path"] for x in run(s)["errors"] if x["code"] == "script.unverified"]
    assert paths == ["cta.text", "disclosure.text"]


def test_multi_sentence() -> None:
    s = good()
    s["script"][0]["text"] = "첫째예요. 둘째예요."
    s["script"][1]["text"] = "한 줄\n두 줄"
    s["script"][2]["text"] = "정말 좋아요?!"
    s["script"][3]["text"] = "끝은 일본어。"
    paths = [x["path"] for x in run(s)["errors"] if x["code"] == "script.multi_sentence"]
    assert paths == ["script.0.text", "script.1.text"]


def test_tts_patterns_and_lang() -> None:
    s = good()
    s["voice"] = {"tts": {"voice": "ko-KR-SunHiNeural", "rate": 1.0}}
    assert "schema.string_type" in codes(run(s))
    s["voice"] = {"tts": {"voice": "ko-KR-SunHiNeural", "rate": "fast"}}
    assert "schema.string_pattern_mismatch" in codes(run(s))
    s["voice"] = {"tts": {"voice": "ja-JP-NanamiNeural", "rate": "+10%"}}
    assert "voice.tts_lang" in codes(run(s))


def test_source_start_range() -> None:
    s = good()
    s["source_start_sec"] = 86401
    assert codes(run(s)) == ["schema.less_than_equal"]
    s["source_start_sec"] = -1
    assert codes(run(s)) == ["schema.greater_than_equal"]


def test_banned_phrase_ignores_space_and_case() -> None:
    s = good()
    s["script"][1]["text"] = "이건 인 생 템 이에요"
    r = run(s, banned_phrases=("인생템", "BEST"))
    assert "script.banned_phrase" in codes(r, "warnings")
    s["script"][1]["text"] = "this is b e s t"
    assert "script.banned_phrase" in codes(run(s, banned_phrases=("BEST",)), "warnings")


def test_multi_sentence_ignores_numeric_periods() -> None:
    s = good()
    s["script"][0]["text"] = "3.5인치 화면이에요."
    s["script"][1]["text"] = "무게는 1.2kg, 버전은 v2.0이에요."
    s["script"][2]["text"] = "자세한 건 https://example.com/a.b 에서 봐요."
    assert "script.multi_sentence" not in codes(run(s))
    s["script"][3]["text"] = "좋아요. 싸요."
    paths = [x["path"] for x in run(s)["errors"] if x["code"] == "script.multi_sentence"]
    assert paths == ["script.3.text"]
