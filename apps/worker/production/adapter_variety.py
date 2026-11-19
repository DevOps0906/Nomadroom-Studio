"""예능형 승인 리비전 spec → 렌더 입력(variety_project, Nomadroom 자체 형식) + 비신뢰 재검증(W6).

규칙 정본은 서버 검증(apps/api/app/production/validation_variety.py,
docs/05_DATA_MODEL.md#예능형-spec-필드). 워커는 같은 상한·거부 문자 목록으로 다시 확인하고,
위반은 RenderFailed. 덮임(W3)은 워커가 probe한 실제 원본 크기로 다시 판정한다.
경로 필드는 spec에 없고 렌더러가 작업 폴더 안 고정 이름을 쓴다.
"""

import math
import re
from typing import Any

from production.errors import RenderFailed

PRESET_VERSION = "variety-1080-v1"  # F9: 예능형 렌더 프리셋. task·spec 값과 다르면 렌더하지 않는다
LANGS = ("ko",)  # 예능형 P0는 ko만
FPS = 30
TOL = 0.001
SRC_TOL = 0.05  # 준비된 source 길이와 구간 길이 차이 허용(초)
CANVAS_W, CANVAS_H = 1080, 1920
BAND_TOP, BAND_BOTTOM = 560, 1376
BAND_CX, BAND_CY = 540, 968
MIN_CUT_SEC, MAX_CUTS, MAX_TOTAL_SEC = 0.2, 60, 180.0
MAX_SUBTITLES = MAX_REACTIONS = 200
MAX_HEADER_LINE_CHARS, MAX_TEXT_CHARS = 60, 200
MAX_TEXT_LINES = 3  # 리뷰 반영: 자막·반응 문구 줄 수(서버 _max_lines와 같음)
MAX_SOURCE_SEC = 600.0  # 리뷰 반영: 원본 PCM 전체 해제 상한(준비된 source는 180초 이하)
# 서버(validation_variety._CONTROL)와 같은 목록. LF·CR은 서버처럼 제목만 거부하고
# 자막·반응 문구는 여러 줄로 그린다(CR·CRLF → LF)
_CONTROL = re.compile(
    r"[\x00-\x09\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2066-\u2069\ufeff]"
)


def _num(v: Any) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        raise RenderFailed("spec 숫자 형식 오류")
    return float(v)


def _text(v: Any, limit: int, multiline: bool = True) -> str:
    if not isinstance(v, str) or not v.strip() or len(v) > limit or _CONTROL.search(v):
        raise RenderFailed("spec 문구 오류")
    if not multiline and ("\n" in v or "\r" in v):
        raise RenderFailed("제목 줄바꿈")
    v = v.replace("\r\n", "\n").replace("\r", "\n")
    if v.count("\n") >= MAX_TEXT_LINES:
        raise RenderFailed("문구 줄 수 초과")
    return v


def _list(spec: dict, key: str, limit: int) -> list:
    v = spec.get(key, [])
    if not isinstance(v, list) or len(v) > limit:
        raise RenderFailed(f"spec {key} 형식 오류")
    return v


def frame_of(t: float) -> int:
    """W2 프레임 격자: 출력 시각×30 반올림(0.5는 올림, 부동소수 오차 1e-6 흡수)."""
    return math.floor(t * FPS + 0.5 + 1e-6)


def covered(scale: float, x: float, y: float, src_w: int, src_h: int) -> bool:
    """W3: 원본 사각형(크기 ceil·위치 floor, 실제 원본 크기)이 띠(0~1080×560~1376)를 덮는가."""
    w = math.ceil(CANVAS_W * scale - TOL)
    h = math.ceil(CANVAS_W * src_h / src_w * scale - TOL)
    left = math.floor(BAND_CX + x - CANVAS_W * scale / 2 + TOL)
    top = math.floor(BAND_CY + y - CANVAS_W * src_h / src_w * scale / 2 + TOL)
    return left <= 0 and top <= BAND_TOP and left + w >= CANVAS_W and top + h >= BAND_BOTTOM


def to_variety_project(spec: Any, lang: str | None, source_meta: dict) -> dict[str, Any]:
    """spec + 실제 원본 정보(probe) → 렌더 입력. 컷 경계는 출력 30fps 프레임 격자(W2)."""
    if not isinstance(spec, dict):
        raise RenderFailed("spec 없음")
    if spec.get("preset_version") not in (None, PRESET_VERSION):
        raise RenderFailed("spec preset_version 불일치")
    if lang not in LANGS or spec.get("lang") not in (None, lang):
        raise RenderFailed("spec 언어 불일치")
    header = spec.get("header")
    lines = header.get("lines") if isinstance(header, dict) else None
    if not isinstance(lines, list) or not 1 <= len(lines) <= 2:
        raise RenderFailed("header 형식 오류")
    lines = [_text(t, MAX_HEADER_LINE_CHARS, multiline=False) for t in lines]

    src_w, src_h = source_meta.get("width"), source_meta.get("height")
    if not src_w or not src_h:
        raise RenderFailed("source 크기 없음")
    src_dur = float(source_meta["duration"])
    if not math.isfinite(src_dur) or src_dur > MAX_SOURCE_SEC:
        raise RenderFailed("source 길이 상한 초과")
    raw_cuts = _list(spec, "cuts", MAX_CUTS)
    if not raw_cuts:
        raise RenderFailed("컷 없음")
    cuts, total, frame0 = [], 0.0, 0
    for c in raw_cuts:
        if not isinstance(c, dict):
            raise RenderFailed("cut 형식 오류")
        s, e, scale, x, y = (_num(c.get(k)) for k in ("src_start", "src_end", "scale", "x", "y"))
        if s < -TOL or e - s < MIN_CUT_SEC - TOL or e > src_dur + SRC_TOL:
            raise RenderFailed("cut 범위 오류")
        if not 1 <= scale <= 3 or not covered(scale, x, y, src_w, src_h):
            raise RenderFailed("cut 빈 화면")
        out_start = total
        total += e - s
        frame1 = frame_of(total)
        cuts.append(
            {
                "src_start": max(s, 0.0),
                "src_end": e,
                "scale": scale,
                "x": x,
                "y": y,
                "out_start": out_start,
                "frame_start": frame0,
                "frames": frame1 - frame0,
            }
        )
        frame0 = frame1
    if total > MAX_TOTAL_SEC + TOL:
        raise RenderFailed("출력 총길이 초과")

    subtitles = []
    for sub in _list(spec, "subtitles", MAX_SUBTITLES):
        if not isinstance(sub, dict) or sub.get("style") not in ("line", "punch"):
            raise RenderFailed("subtitle 형식 오류")
        start, end = _num(sub.get("start")), _num(sub.get("end"))
        if start < -TOL or end <= start or end > total + TOL:
            raise RenderFailed("subtitle 범위 오류")
        text = _text(sub.get("text"), MAX_TEXT_CHARS)
        subtitles.append({"start": start, "end": end, "style": sub["style"], "text": text})
    spans = sorted((s["start"], s["end"]) for s in subtitles)
    if any(b[0] < a[1] - TOL for a, b in zip(spans, spans[1:], strict=False)):
        raise RenderFailed("subtitle 겹침")

    reactions = []
    for r in _list(spec, "reactions", MAX_REACTIONS):
        if not isinstance(r, dict):
            raise RenderFailed("reaction 형식 오류")
        start, end, x, y = (_num(r.get(k)) for k in ("start", "end", "x", "y"))
        if start < -TOL or end <= start or end > total + TOL:
            raise RenderFailed("reaction 범위 오류")
        if not (0 <= x <= CANVAS_W and 0 <= y <= CANVAS_H):
            raise RenderFailed("reaction 위치 오류")
        reactions.append(
            {
                "start": start,
                "end": end,
                "x": x,
                "y": y,
                "text": _text(r.get("text"), MAX_TEXT_CHARS),
            }
        )
    return {
        "lang": lang,
        "header": lines,
        "cuts": cuts,
        "frames": frame0,
        "duration": total,
        "subtitles": subtitles,
        "reactions": reactions,
    }
