"""예능형(variety) 편집안 검증 + format 분기 진입점. 정본: docs/05_DATA_MODEL.md#예능형-spec-필드.

카테고리형 규칙(spec.py)은 바꾸지 않고 `validate_for_format`이 format으로 갈라 호출한다.
오류·경고는 {code, path, message}. 예외 대신 {errors, warnings}로 반환한다.
"""

import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.production.spec import _PATHLIKE, validate_spec

TOL = 0.001
CANVAS_W = 1080
CANVAS_H = 1920
BAND_TOP = 560
BAND_BOTTOM = 1376
BAND_CX = 540
BAND_CY = 968
MIN_CUT_SEC = 0.2  # 가정 Q11
WARN_CUT_SEC = 0.5
MAX_CUTS = 60
MAX_TOTAL_SEC = 180.0
MIN_SHOW_SEC = 1.4
_Num = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Header(_M):
    lines: list[str]


class Cut(_M):
    src_start: _Num
    src_end: _Num
    scale: _Num
    x: _Num
    y: _Num


class Subtitle(_M):
    start: _Num
    end: _Num
    style: str
    text: str


class Reaction(_M):
    start: _Num
    end: _Num
    text: str
    x: _Num
    y: _Num


class VarietySpec(_M):
    lang: Literal["ko"] | None = None
    header: Header
    cuts: list[Cut]
    subtitles: list[Subtitle] = []
    reactions: list[Reaction] = []
    source_start_sec: _Num | None = None
    preset_version: str | None = None


def _e(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def validate_for_format(
    fmt: str,
    raw: Any,
    *,
    source_duration: float | None = None,
    segment_len: float | None = None,
    source_size: tuple[float, float] | None = None,
    job_lang: str | None = None,
) -> dict[str, list[dict[str, str]]]:
    """format(`category`·`variety`)으로 검증 모듈을 고른다. 모르는 format은 오류."""
    if fmt == "category":
        return validate_spec(raw, source_duration=source_duration, job_lang=job_lang)
    if fmt == "variety":
        return validate_variety_spec(
            raw, segment_len=segment_len, source_size=source_size, job_lang=job_lang
        )
    return {"errors": [_e("format.unknown", "", "알 수 없는 format입니다.")], "warnings": []}


def validate_variety_spec(
    raw: Any,
    *,
    segment_len: float | None = None,
    source_size: tuple[float, float] | None = None,
    job_lang: str | None = None,
) -> dict[str, list[dict[str, str]]]:
    """예능형 편집안 검증. segment_len=선택 구간 길이(초, 없으면 범위 상한 검사 생략),
    source_size=원본 (폭, 높이) px(없으면 1080x1920 세로 영상으로 가정)."""
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(raw, dict):
        return {"errors": [_e("schema.type", "", "spec은 객체여야 합니다.")], "warnings": []}
    try:
        s = VarietySpec.model_validate(raw)
    except ValidationError as exc:
        for d in exc.errors():
            path = ".".join(str(p) for p in d["loc"])
            errors.append(_e(f"schema.{d['type']}", path, d["msg"]))
        return {"errors": errors, "warnings": warnings}

    if job_lang is not None and s.lang is not None and s.lang != job_lang:
        errors.append(_e("lang.mismatch", "lang", "작업 lang과 같아야 합니다."))
    if s.preset_version is not None and _PATHLIKE.search(s.preset_version):
        errors.append(_e("path.forbidden", "preset_version", "경로·URL 문자열은 둘 수 없습니다."))

    lines = s.header.lines
    if not 1 <= len(lines) <= 2 or any(not ln.strip() or "\n" in ln or "\r" in ln for ln in lines):
        errors.append(_e("header.invalid", "header.lines", "제목은 1~2줄, 빈 줄·줄바꿈 불가"))

    size = source_size or (1080.0, 1920.0)
    if not all(math.isfinite(v) and v > 0 for v in size):
        errors.append(
            _e("source_size.invalid", "source_size", "원본 크기는 0보다 큰 유한값이어야 합니다.")
        )
        size = (1080.0, 1920.0)
    total = _check_cuts(s, errors, warnings, segment_len, size)
    _check_subtitles(s, total, errors, warnings)
    _check_reactions(s, total, errors, warnings)
    return {"errors": errors, "warnings": warnings}


def _check_cuts(
    s: VarietySpec,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
    segment_len: float | None,
    size: tuple[float, float],
) -> float:
    if not 1 <= len(s.cuts) <= MAX_CUTS:
        errors.append(_e("cuts.count", "cuts", f"컷은 1~{MAX_CUTS}개여야 합니다."))
    total = 0.0
    src_w, src_h = size
    for i, c in enumerate(s.cuts):
        p = f"cuts.{i}"
        length = c.src_end - c.src_start
        if (
            c.src_start < -TOL
            or c.src_end <= c.src_start
            or (segment_len is not None and c.src_end > segment_len + TOL)
        ):
            errors.append(_e("cuts.out_of_range", p, "원본 시각이 구간 범위를 벗어났습니다."))
        if 0 < length < MIN_CUT_SEC - TOL:
            errors.append(_e("cuts.too_short", p, f"컷 길이는 {MIN_CUT_SEC}초 이상이어야 합니다."))
        elif 0 < length < WARN_CUT_SEC - TOL:
            warnings.append(_e("cuts.short", p, f"컷 길이 {WARN_CUT_SEC}초 미만입니다."))
        if not 1 <= c.scale <= 3:
            errors.append(_e("cuts.scale", f"{p}.scale", "배율은 1~3이어야 합니다."))
        else:
            w = CANVAS_W * c.scale
            h = CANVAS_W * src_h / src_w * c.scale
            cx, cy = BAND_CX + c.x, BAND_CY + c.y
            if (
                cx - w / 2 > TOL
                or cx + w / 2 < CANVAS_W - TOL
                or cy - h / 2 > BAND_TOP + TOL
                or cy + h / 2 < BAND_BOTTOM - TOL
            ):
                errors.append(_e("cuts.empty_area", p, "영상 띠에 빈 화면이 생깁니다."))
        if length > 0:
            total += length
    if total > MAX_TOTAL_SEC + TOL:
        errors.append(
            _e("cuts.total_too_long", "cuts", f"출력 총길이는 {MAX_TOTAL_SEC:g}초 이하여야 합니다.")
        )
    return total


def _check_subtitles(
    s: VarietySpec, total: float, errors: list[dict[str, str]], warnings: list[dict[str, str]]
) -> None:
    for i, sub in enumerate(s.subtitles):
        p = f"subtitles.{i}"
        if sub.start < -TOL or sub.end <= sub.start or sub.end > total + TOL:
            errors.append(_e("subtitles.out_of_range", p, "시간이 0~총길이 범위를 벗어났습니다."))
        if not sub.text.strip():
            errors.append(_e("subtitles.empty_text", f"{p}.text", "문구가 비어 있습니다."))
        if sub.style not in ("line", "punch"):
            errors.append(_e("subtitles.style", f"{p}.style", "style은 line·punch만 가능합니다."))
        if 0 < sub.end - sub.start < MIN_SHOW_SEC - TOL:
            warnings.append(_e("subtitles.short", p, "표시 1.4초 미만입니다."))
    max_end = -math.inf
    for sub_start, sub_end, i in sorted((x.start, x.end, i) for i, x in enumerate(s.subtitles)):
        if sub_start < max_end - TOL:
            errors.append(_e("subtitles.overlap", f"subtitles.{i}", "자막 구간이 겹칩니다."))
        max_end = max(max_end, sub_end)


def _check_reactions(
    s: VarietySpec, total: float, errors: list[dict[str, str]], warnings: list[dict[str, str]]
) -> None:
    for i, r in enumerate(s.reactions):
        p = f"reactions.{i}"
        if (
            r.start < -TOL
            or r.end <= r.start
            or r.end > total + TOL
            or not (0 <= r.x <= CANVAS_W and 0 <= r.y <= CANVAS_H)
        ):
            errors.append(_e("reactions.out_of_range", p, "시간·좌표가 범위를 벗어났습니다."))
        if not r.text.strip():
            errors.append(_e("reactions.empty_text", f"{p}.text", "문구가 비어 있습니다."))
    max_end = -math.inf
    for r_start, r_end, i in sorted((x.start, x.end, i) for i, x in enumerate(s.reactions)):
        if r_start < max_end - TOL:
            warnings.append(_e("reactions.overlap", f"reactions.{i}", "반응 자막이 겹칩니다."))
        max_end = max(max_end, r_end)
