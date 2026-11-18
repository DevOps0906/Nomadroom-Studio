"""카테고리형 편집안(edit_revisions.spec) 검증. 정본: docs/05_DATA_MODEL.md 편집안 표.

오류가 있어도 예외 대신 {errors, warnings} 목록으로 반환한다(저장은 허용).
훅 길이(hook_too_long)·문구 폭(text_too_long)은 렌더 워커 몫이라 검사하지 않는다.
"""

import math
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

TOL = 0.001
H = 1080
MIN_SHOW_SEC = 1.4
_Num = Annotated[float, Field(strict=True, allow_inf_nan=False)]
_PATHLIKE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:|^~|[/\\]|^\.\.$")


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Header(_M):
    lines: list[str] = Field(min_length=2, max_length=2)


class Tts(_M):
    voice: str = Field(min_length=1)
    rate: str = "+50%"


class Hook(_M):
    text: str
    audio_asset_id: str | None = None
    tts: Tts | None = None


class Shot(_M):
    start: _Num
    end: _Num
    scale: _Num
    y: _Num


class Item(_M):
    start: _Num
    end: _Num
    kind: Literal["white", "paren", "emph"]
    text: str
    y: _Num | None = None


class Overlay(_M):
    kind: Literal["comment", "source"]
    text: str
    start: _Num
    end: _Num
    x: _Num
    y: _Num
    ref: str | None = None


class Spec(_M):
    lang: Literal["ko", "ja"]
    header: Header
    hook: Hook
    duration: _Num
    shots: list[Shot]
    items: list[Item]
    overlays: list[Overlay] = []
    source_start_sec: _Num | None = None
    preset_version: str | None = None


def _e(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _id_strings(s: Spec) -> list[tuple[str, str]]:
    """경로·URL이면 안 되는(자산 ID·코드 성격의) 문자열 필드."""
    out: list[tuple[str, str]] = []
    if s.hook.audio_asset_id is not None:
        out.append(("hook.audio_asset_id", s.hook.audio_asset_id))
    if s.hook.tts:
        out += [("hook.tts.voice", s.hook.tts.voice), ("hook.tts.rate", s.hook.tts.rate)]
    if s.preset_version is not None:
        out.append(("preset_version", s.preset_version))
    out += [(f"overlays.{i}.ref", o.ref) for i, o in enumerate(s.overlays) if o.ref is not None]
    return out


def validate_spec(
    raw: Any, *, source_duration: float | None = None, job_lang: str | None = None
) -> dict[str, list[dict[str, str]]]:
    """편집안을 검증해 {errors, warnings}를 반환한다. source_duration=analysis 길이(초)."""
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(raw, dict):
        return {"errors": [_e("schema.type", "", "spec은 객체여야 합니다.")], "warnings": []}
    try:
        s = Spec.model_validate(raw)
    except ValidationError as exc:
        for d in exc.errors():
            path = ".".join(str(p) for p in d["loc"])
            errors.append(_e(f"schema.{d['type']}", path, d["msg"]))
        return {"errors": errors, "warnings": warnings}

    if job_lang is not None and s.lang != job_lang:
        errors.append(_e("lang.mismatch", "lang", "작업 lang과 같아야 합니다."))
    for path, value in _id_strings(s):
        if _PATHLIKE.search(value):
            errors.append(_e("path.forbidden", path, "경로·URL 문자열은 둘 수 없습니다."))

    for i, line in enumerate(s.header.lines):
        if not line.strip() or "\n" in line or "\r" in line:
            errors.append(_e("header.lines.invalid", f"header.lines.{i}", "빈 줄·줄바꿈 불가"))

    if not s.hook.text.strip():
        errors.append(_e("hook.text.empty", "hook.text", "훅 문구가 비어 있습니다."))
    if (s.hook.audio_asset_id is None) == (s.hook.tts is None):
        errors.append(_e("hook.audio_xor", "hook", "audio_asset_id와 tts 중 하나만 지정"))

    d = s.duration
    max_d = 180.0 if source_duration is None else min(180.0, source_duration + 0.05)
    if not 0.1 <= d <= max_d:
        errors.append(_e("duration.range", "duration", f"duration은 0.1~{max_d:g}초여야 합니다."))

    _check_shots(s, errors)
    _check_items(s, errors, warnings)
    for i, o in enumerate(s.overlays):
        p = f"overlays.{i}"
        if o.start < -TOL or o.end <= o.start or o.end > d + TOL:
            errors.append(_e("overlays.range", p, "시간이 0~duration 범위를 벗어났습니다."))
        if not o.text.strip():
            errors.append(_e("overlays.text.empty", f"{p}.text", "문구가 비어 있습니다."))
    return {"errors": errors, "warnings": warnings}


def _check_shots(s: Spec, errors: list[dict[str, str]]) -> None:
    if not s.shots:
        errors.append(_e("shots.empty", "shots", "구도가 타임라인 전체를 덮어야 합니다."))
        return
    prev = 0.0
    for i, sh in enumerate(s.shots):
        p = f"shots.{i}"
        if abs(sh.start - prev) > TOL:
            code = "shots.gap" if sh.start > prev else "shots.overlap"
            errors.append(_e(code, p, "구도는 공백·겹침 없이 이어져야 합니다."))
        if sh.end <= sh.start:
            errors.append(_e("shots.order", p, "end가 start보다 커야 합니다."))
        if sh.end > s.duration + TOL:
            errors.append(_e("shots.range", p, "duration을 넘었습니다."))
        if not 1 <= sh.scale <= 3:
            errors.append(_e("shots.scale", f"{p}.scale", "배율은 1~3이어야 합니다."))
        if sh.y > 280:
            errors.append(_e("shots.y", f"{p}.y", "Y는 280 이하여야 합니다."))
        if sh.y + H * sh.scale < H - 0.01:
            errors.append(_e("shots.blank", p, "빈 화면이 생깁니다(Y+1080×배율≥1080)."))
        prev = sh.end
    if abs(prev - s.duration) > TOL:
        errors.append(_e("shots.end", "shots", "구도는 duration에서 끝나야 합니다."))


def _check_items(s: Spec, errors: list[dict[str, str]], warnings: list[dict[str, str]]) -> None:
    if not s.items:
        errors.append(_e("items.empty", "items", "자막이 최소 1개 필요합니다."))
        return
    prev = 0.0
    for i, it in enumerate(s.items):
        p = f"items.{i}"
        if it.start < prev - TOL:
            errors.append(_e("items.overlap", p, "자막은 시간순이며 겹치면 안 됩니다."))
        if it.end <= it.start:
            errors.append(_e("items.order", p, "end가 start보다 커야 합니다."))
        if it.end > s.duration + TOL:
            errors.append(_e("items.range", p, "duration을 넘었습니다."))
        if not it.text.strip():
            errors.append(_e("items.text.empty", f"{p}.text", "문구가 비어 있습니다."))
        elif "\n" in it.text or "\r" in it.text:
            errors.append(_e("items.text.newline", f"{p}.text", "줄바꿈 불가"))
        if it.y is not None and not 310 <= it.y <= 1030:
            errors.append(_e("items.y", f"{p}.y", "y는 310~1030이어야 합니다."))
        if 0 < it.end - it.start < MIN_SHOW_SEC and math.isfinite(it.end):
            warnings.append(_e("items.too_short", p, "표시 1.4초 미만입니다."))
        prev = it.end
    if abs(s.items[0].start) > TOL:
        errors.append(_e("items.first_not_zero", "items.0.start", "첫 자막은 0초에 시작"))
