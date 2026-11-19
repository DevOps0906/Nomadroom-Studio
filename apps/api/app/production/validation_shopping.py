"""쇼핑 편집안(format=shopping) 검증. 정본: docs/05_DATA_MODEL.md#쇼핑-spec-필드.

일반쇼츠·예능형 검증은 바꾸지 않고, 비신뢰 텍스트 규칙(제어 문자·비BMP·길이)은
validation_variety의 것을 재사용한다. 오류·경고는 {code, path, message}, 예외 대신 반환한다.
자산 정보(`assets`)는 호출자(API)가 이 작업 소유 행만 담아 넘긴다. 없으면 자산 의존 검사는 생략한다.
"""

import math
import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, ValidationError

from app.production.spec import _PATHLIKE, TTS_RATE_PATTERN, TTS_VOICE_PATTERN
from app.production.validation_variety import (
    _M,
    CANVAS_H,
    CANVAS_W,
    MAX_CUTS,
    TOL,
    _e,
    _Num,
    _Text,
)

SENTENCES = 4
SCRIPT_MIN_CHARS = 110
SCRIPT_MAX_CHARS = 140
MAX_MASKS = 20
MAX_SCRIPT_ITEMS = 20  # 4문장이 아닌 입력도 count 오류로 돌려주되 상한은 둔다
MIN_SOURCES = 3
CONFIRM_MARK = "[확인 필요]"
DEFAULT_BANNED_PHRASES = ("강력 추천", "인생템", "지금 바로")  # 가정: 금지어 설정 전 기본값
MOTION_TYPES = ("pan", "zoom", "none")
VIDEO_KINDS = ("source", "source_upload")
CUT_KINDS = (*VIDEO_KINDS, "image")
MAX_START_SEC = 86400
NARRATIONS = SENTENCES  # task-045 사용자 결정: 문장별 녹음 4개(문장 순서)
# task-045 팀장 결정(Q12): 표기 고정 문구. 다른 값이면 오류
DISCLOSURE_TEXT = {"ko": "제휴 링크 포함", "ja": "PR"}
# task-045 팀장 결정(Q13): 사진은 직접 촬영·라이선스 구매·AI 생성(054 경로)만. 제휴처 제공 금지
IMAGE_BASES = ("own", "licensed", "ai_generated")
_TERMINATORS = ".?!。？！"
# 종결 부호가 아닌 마침표: URL, 숫자 사이(3.5·v2.0)
_NON_TERMINAL = re.compile(r"https?://\S+|www\.\S+|(?<=\d)\.(?=\d)")
_Id = Annotated[str, StringConstraints(max_length=200)]
_Assets = Mapping[str, Mapping[str, Any]]


class Sentence(_M):
    text: _Text


class Mask(_M):
    x: _Num
    y: _Num
    w: _Num
    h: _Num


class Motion(_M):
    type: str


class Cut(_M):
    source_asset_id: _Id
    src_start: _Num
    src_end: _Num
    scale: _Num
    x: _Num
    y: _Num
    sentence: Annotated[int, Field(strict=True)]
    masks: Annotated[list[Mask], Field(max_length=MAX_MASKS)] = []
    motion: Motion | None = None


class Tts(_M):
    voice: str = Field(pattern=TTS_VOICE_PATTERN)
    rate: str = Field(pattern=TTS_RATE_PATTERN)


class Voice(_M):
    tts: Tts | None = None
    # 문장 i의 녹음 = narration_asset_ids[i](정확히 4개, 개수는 의미 검사 voice.narration_count)
    narration_asset_ids: Annotated[list[_Id], Field(max_length=MAX_SCRIPT_ITEMS)] | None = None


class Caption(_M):
    text: _Text = ""


class ShoppingSpec(_M):
    lang: Literal["ko", "ja"] | None = None
    script: Annotated[list[Sentence], Field(max_length=MAX_SCRIPT_ITEMS)]
    cuts: Annotated[list[Cut], Field(max_length=MAX_CUTS)]
    voice: Voice = Voice()
    source_audio: Literal["mute", "duck"] = "mute"
    bgm_asset_id: _Id | None = None
    cta: Caption = Caption()
    disclosure: Caption = Caption()
    source_start_sec: Annotated[_Num, Field(ge=0, le=MAX_START_SEC)] | None = None
    preset_version: str | None = None


def validate_shopping_spec(
    raw: Any,
    *,
    assets: _Assets,
    job_lang: str | None = None,
    product_name: str | None = None,
    banned_phrases: tuple[str, ...] = DEFAULT_BANNED_PHRASES,
) -> dict[str, list[dict[str, str]]]:
    """assets(필수): id -> {kind, status, duration_sec, width, height, rights, reviewed}(이 작업
    소유 자산만. 없는 id·다른 작업 id는 오류). 호출자는 승인·저장 때 반드시 넘긴다.
    product_name: brief 제품명(여행은 목적지). 없으면 1번 문장 제품명 경고를 생략한다."""
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(raw, dict):
        return {"errors": [_e("schema.type", "", "spec은 객체여야 합니다.")], "warnings": []}
    try:
        s = ShoppingSpec.model_validate(raw)
    except ValidationError as exc:
        for d in exc.errors():
            path = ".".join(str(p) for p in d["loc"])
            errors.append(_e(f"schema.{d['type']}", path, d["msg"]))
        return {"errors": errors, "warnings": warnings}

    lang = s.lang or job_lang
    if job_lang is not None and s.lang is not None and s.lang != job_lang:
        errors.append(_e("lang.mismatch", "lang", "작업 lang과 같아야 합니다."))
    _check_paths(s, errors)
    voice = s.voice.tts.voice if s.voice.tts else None
    if voice is not None and lang is not None and voice.split("-", 1)[0] != lang:
        errors.append(_e("voice.tts_lang", "voice.tts.voice", "voice 언어가 spec lang과 달라요."))
    _check_script(s, lang, product_name, banned_phrases, errors, warnings)
    _check_cuts(s, assets, errors, warnings)
    _check_voice(s, assets, errors)
    _check_captions(s, lang, errors)
    _check_rights(s, assets, errors)
    return {"errors": errors, "warnings": warnings}


def _flat(v: str) -> str:
    return re.sub(r"\s+", "", v).casefold()


def _multi_sentence(text: str) -> bool:
    body = _NON_TERMINAL.sub("", text.strip().rstrip(_TERMINATORS))
    return "\n" in body or "\r" in body or any(ch in body for ch in _TERMINATORS)


def _usable(a: Mapping[str, Any] | None, kinds: tuple[str, ...]) -> bool:
    return a is not None and a.get("kind") in kinds and a.get("status") == "ready"


def _check_paths(s: ShoppingSpec, errors: list[dict[str, str]]) -> None:
    items: list[tuple[str, str | None]] = [
        ("preset_version", s.preset_version),
        ("bgm_asset_id", s.bgm_asset_id),
        ("voice.tts.voice", s.voice.tts.voice if s.voice.tts else None),
    ]
    items += [
        (f"voice.narration_asset_ids.{i}", v)
        for i, v in enumerate(s.voice.narration_asset_ids or [])
    ]
    items += [(f"cuts.{i}.source_asset_id", c.source_asset_id) for i, c in enumerate(s.cuts)]
    for path, value in items:
        if value is not None and _PATHLIKE.search(value):
            errors.append(_e("path.forbidden", path, "경로·URL 문자열은 둘 수 없습니다."))


def _check_script(
    s: ShoppingSpec,
    lang: str | None,
    product_name: str | None,
    banned: tuple[str, ...],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    texts = [x.text for x in s.script]
    if len(texts) != SENTENCES:
        errors.append(_e("script.count", "script", f"대본은 정확히 {SENTENCES}문장이어야 합니다."))
    for i, t in enumerate(texts):
        if not t.strip():
            errors.append(_e("script.empty_text", f"script.{i}.text", "문장이 비어 있습니다."))
    for i, t in enumerate(texts):
        if _multi_sentence(t):
            msg = "항목 하나에 문장 하나만 넣어야 합니다."
            errors.append(_e("script.multi_sentence", f"script.{i}.text", msg))
    marked = [(f"script.{i}.text", t) for i, t in enumerate(texts)]
    marked += [("cta.text", s.cta.text), ("disclosure.text", s.disclosure.text)]
    for path, t in marked:
        if CONFIRM_MARK in t:
            msg = f"{CONFIRM_MARK} 표시를 확인하고 지워야 합니다."
            errors.append(_e("script.unverified", path, msg))
    total = sum(len(t) for t in texts)
    in_range = SCRIPT_MIN_CHARS <= total <= SCRIPT_MAX_CHARS
    if lang != "ja" and len(texts) == SENTENCES and not in_range:
        msg = f"공백 포함 합계 {SCRIPT_MIN_CHARS}~{SCRIPT_MAX_CHARS}자 권장(현재 {total}자)."
        warnings.append(_e("script.length", "script", msg))
    for i, t in enumerate(texts):
        flat = _flat(t)
        for phrase in banned:
            if _flat(phrase) and _flat(phrase) in flat:
                msg = f"금지 문구 '{phrase}'가 있습니다."
                warnings.append(_e("script.banned_phrase", f"script.{i}.text", msg))
    name = (product_name or "").strip().casefold()
    if name and texts and name in texts[0].casefold():
        msg = "1번 문장에 제품명이 있습니다."
        warnings.append(_e("script.product_in_first", "script.0.text", msg))


def _check_cuts(
    s: ShoppingSpec,
    assets: _Assets,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    if not 1 <= len(s.cuts) <= MAX_CUTS:
        errors.append(_e("cuts.count", "cuts", f"컷은 1~{MAX_CUTS}개여야 합니다."))
    covered: set[int] = set()
    for i, c in enumerate(s.cuts):
        p = f"cuts.{i}"
        asset = assets.get(c.source_asset_id)
        kind = asset.get("kind") if asset else None
        duration = asset.get("duration_sec") if asset else None
        has_len = isinstance(duration, int | float) and not isinstance(duration, bool)
        if not _usable(asset, CUT_KINDS) or (kind in VIDEO_KINDS and not has_len):
            msg = "이 작업의 준비된 원본·이미지(영상은 길이 포함)가 아닙니다."
            errors.append(_e("cuts.source_invalid", f"{p}.source_asset_id", msg))
        if not 1 <= c.sentence <= SENTENCES:
            msg = f"문장 번호는 1~{SENTENCES}입니다."
            errors.append(_e("cuts.sentence_invalid", f"{p}.sentence", msg))
        else:
            covered.add(c.sentence)
        too_long = kind in VIDEO_KINDS and has_len and c.src_end > duration + TOL  # type: ignore[operator]
        if c.src_start < -TOL or c.src_end <= c.src_start or too_long:
            errors.append(_e("cuts.out_of_range", p, "원본 시각이 범위를 벗어났습니다."))
        if not 1 <= c.scale <= 3:
            errors.append(_e("cuts.scale", f"{p}.scale", "배율은 1~3이어야 합니다."))
        else:
            _check_area(c, asset, p, errors)
        for j, m in enumerate(c.masks):
            if (
                m.x < -TOL
                or m.y < -TOL
                or m.w <= 0
                or m.h <= 0
                or m.x + m.w > CANVAS_W + TOL
                or m.y + m.h > CANVAS_H + TOL
            ):
                msg = "가림 영역이 캔버스를 벗어났습니다."
                errors.append(_e("masks.out_of_range", f"{p}.masks.{j}", msg))
        if c.motion is not None:
            not_image = kind != "image"
            if c.motion.type not in MOTION_TYPES or not_image:
                msg = "motion은 image 컷의 pan·zoom·none만 가능합니다."
                errors.append(_e("cuts.motion_invalid", f"{p}.motion", msg))
    for n in range(1, SENTENCES + 1):
        if n not in covered:
            errors.append(_e("cuts.sentence_empty", "cuts", f"{n}번 문장에 컷이 없습니다."))
    if len({c.source_asset_id for c in s.cuts}) < MIN_SOURCES:
        warnings.append(_e("sources.few", "cuts", f"사용 원본이 {MIN_SOURCES}개 미만입니다."))


def _check_area(
    c: Cut, asset: Mapping[str, Any] | None, path: str, errors: list[dict[str, str]]
) -> None:
    """가로 맞춤 배치(예능형과 같은 식)가 전체 캔버스를 덮는지. 크기 없으면 1080x1920 가정."""
    w0 = asset.get("width") if asset else None
    h0 = asset.get("height") if asset else None
    ok = all(isinstance(v, int | float) and math.isfinite(v) and v > 0 for v in (w0, h0))
    src_w, src_h = (float(w0), float(h0)) if ok else (1080.0, 1920.0)  # type: ignore[arg-type]
    w = CANVAS_W * c.scale
    h = CANVAS_W * src_h / src_w * c.scale
    cx, cy = CANVAS_W / 2 + c.x, CANVAS_H / 2 + c.y
    if (
        cx - w / 2 > TOL
        or cx + w / 2 < CANVAS_W - TOL
        or cy - h / 2 > TOL
        or cy + h / 2 < CANVAS_H - TOL
    ):
        errors.append(_e("cuts.empty_area", path, "화면에 빈 영역이 생깁니다."))


def _check_voice(s: ShoppingSpec, assets: _Assets, errors: list[dict[str, str]]) -> None:
    has_tts, ids = s.voice.tts is not None, s.voice.narration_asset_ids
    if not has_tts and ids is None:
        msg = "tts 또는 narration_asset_ids 중 하나가 필요합니다."
        errors.append(_e("voice.missing", "voice", msg))
    elif has_tts and ids is not None:
        msg = "tts와 narration_asset_ids는 함께 쓸 수 없습니다."
        errors.append(_e("voice.both", "voice", msg))
    if ids is not None:
        if len(ids) != NARRATIONS or len(set(ids)) != len(ids):
            msg = f"문장별 녹음은 서로 다른 {NARRATIONS}개(문장 순서)여야 합니다."
            errors.append(_e("voice.narration_count", "voice.narration_asset_ids", msg))
        for i, nid in enumerate(ids):
            if not _usable(assets.get(nid), ("narration",)):
                msg = "이 작업의 준비된 narration 자산이 아닙니다."
                errors.append(_e("voice.asset_invalid", f"voice.narration_asset_ids.{i}", msg))


def _check_captions(s: ShoppingSpec, lang: str | None, errors: list[dict[str, str]]) -> None:
    if not s.cta.text.strip():
        errors.append(_e("cta.empty", "cta.text", "4번 문장 화면 문구가 비어 있습니다."))
    fixed = DISCLOSURE_TEXT.get(lang or "ko", DISCLOSURE_TEXT["ko"])
    if not s.disclosure.text.strip():
        errors.append(_e("disclosure.empty", "disclosure.text", "제휴 표기 문구가 비어 있습니다."))
    elif s.disclosure.text != fixed:
        msg = f"제휴 표기는 고정 문구 '{fixed}'만 쓸 수 있습니다."
        errors.append(_e("disclosure.fixed", "disclosure.text", msg))


def _check_rights(s: ShoppingSpec, assets: _Assets, errors: list[dict[str, str]]) -> None:
    """사용한 원본·이미지·BGM만 본다(한 자산은 처음 참조 경로에서 한 번만 보고)."""
    refs = [(f"cuts.{i}.source_asset_id", c.source_asset_id) for i, c in enumerate(s.cuts)]
    if s.bgm_asset_id is not None:
        refs.append(("bgm_asset_id", s.bgm_asset_id))
    seen: set[tuple[str, bool]] = set()
    for path, aid in refs:
        a = assets.get(aid)
        is_bgm = path == "bgm_asset_id"
        if a is None and is_bgm:
            errors.append(_e("bgm.asset_invalid", path, "이 작업의 bgm 자산이 아닙니다."))
        if a is None or (aid, is_bgm) in seen:
            continue
        seen.add((aid, is_bgm))
        if is_bgm and not _usable(a, ("bgm",)):
            errors.append(_e("bgm.asset_invalid", path, "이 작업의 bgm 자산이 아닙니다."))
        raw_rights = a.get("rights")
        rights: Mapping[str, Any] = raw_rights if isinstance(raw_rights, Mapping) else {}
        if not rights.get("basis"):
            code = "bgm.rights_missing" if is_bgm else "rights.missing"
            errors.append(_e(code, path, "권리 근거(basis)를 입력해야 합니다."))
            continue
        if a.get("kind") == "image" and not is_bgm and rights.get("basis") not in IMAGE_BASES:
            msg = "사진은 직접 촬영·라이선스 구매·AI 생성만 쓸 수 있습니다(제휴처 이미지 금지)."
            errors.append(_e("rights.image_basis", path, msg))
        if rights.get("has_person") is True and rights.get("portrait_consent") is not True:
            errors.append(_e("rights.portrait_consent", path, "인물 초상 동의가 필요합니다."))
        if rights.get("basis") == "ai_generated":
            if not _gen_ok(rights.get("gen")):
                msg = "AI 생성 자산은 gen(platform·model·request_id·cost_krw)이 필요합니다."
                errors.append(_e("gen.missing", path, msg))
            if a.get("reviewed") is not True:
                msg = "AI 생성 컷은 검수(reviewed) 후 승인할 수 있습니다."
                errors.append(_e("gen.unreviewed", path, msg))


def _gen_ok(gen: Any) -> bool:
    if not isinstance(gen, Mapping):
        return False
    keys = ("platform", "model", "request_id")
    texts = all(isinstance(gen.get(k), str) and gen[k].strip() for k in keys)
    cost = gen.get("cost_krw")
    return texts and isinstance(cost, int) and not isinstance(cost, bool) and cost >= 0
