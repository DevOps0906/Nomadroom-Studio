"""댓글·출처 오버레이(spec overlays) 정규화·카드 그리기. 텍스트는 PIL로만 그린다(필터 문자열 금지).

위치 x·y는 608×1080 화면에서 카드의 중심(px)이다. 이미지·URL 첨부는 지원하지 않는다.
"""

import math
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from production.errors import RenderFailed, TextTooLong
from production.fonts import category_fonts

W, H = 608, 1080
MAX_UNITS = 80  # 폭 단위(공백·ASCII 구두점 1, 그 밖 2) = 최소 12pt에서 504px 이내
MAX_COUNT = 20
NARROW = " .,'!?:;-()"
MAX_CARD_W = 540
PAD_X, PAD_Y = 18, 12
SIZES = {"comment": 30, "source": 22}


def text_units(text: str) -> int:
    return sum(1 if ch in NARROW else 2 for ch in text)


def _num(v: Any) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        raise RenderFailed("overlay 값 형식 오류")
    return float(v)


def normalize(raw: Any, duration: float) -> list[dict[str, Any]]:
    """spec overlays → 렌더러용 목록. 형식·범위·같은 종류 겹침 오류는 RenderFailed."""
    if not isinstance(raw, list):
        raise RenderFailed("overlays 형식 오류")
    if len(raw) > MAX_COUNT:
        raise RenderFailed("overlay 개수 초과")
    out: list[dict[str, Any]] = []
    for o in raw:
        if not isinstance(o, dict):
            raise RenderFailed("overlay 형식 오류")
        kind, text = o.get("kind"), o.get("text")
        if kind not in SIZES or not isinstance(text, str):
            raise RenderFailed("overlay kind·text 오류")
        if not text.strip() or "\n" in text or "\r" in text or text_units(text) > MAX_UNITS:
            raise RenderFailed("overlay 문구 오류")
        start, end, x, y = (_num(o.get(k)) for k in ("start", "end", "x", "y"))
        if start < -0.001 or end <= start or end > duration + 0.001:
            raise RenderFailed("overlay 구간이 범위를 벗어남")
        if not (0 <= x <= W and 0 <= y <= H):
            raise RenderFailed("overlay 위치가 화면 밖")
        out.append({"kind": kind, "text": text, "start": start, "end": end, "x": x, "y": y})
    for kind in SIZES:
        spans = sorted((o["start"], o["end"]) for o in out if o["kind"] == kind)
        for a, b in zip(spans, spans[1:], strict=False):
            if b[0] < a[1] - 0.001:
                raise RenderFailed("같은 종류 overlay 구간이 겹침")
    return out


def draw_card(overlay: dict[str, Any], lang: str = "ko") -> Image.Image:
    """오버레이 하나를 608×1080 RGBA 레이어로 그린다. 문구가 카드 폭을 넘으면 TextTooLong.
    글꼴은 언어별 자막 글꼴(ko: Noto KR, ja: Noto JP, task-050)."""
    kind, text = overlay["kind"], overlay["text"]
    font_path = category_fonts(lang)[1]
    layer = Image.new("RGBA", (W, H))
    draw = ImageDraw.Draw(layer)
    inner = MAX_CARD_W - 2 * PAD_X
    for size in range(SIZES[kind], 11, -1):
        font = ImageFont.truetype(str(font_path), size)
        b = draw.textbbox((0, 0), text, font=font)
        if b[2] - b[0] <= inner:
            break
    else:
        raise TextTooLong("오버레이 문구 폭 초과")
    tw, th = b[2] - b[0], b[3] - b[1]
    cw, ch = tw + 2 * PAD_X, th + 2 * PAD_Y
    left = min(max(overlay["x"] - cw / 2, 0), W - cw)
    top = min(max(overlay["y"] - ch / 2, 0), H - ch)
    if kind == "comment":
        fill, ink = (255, 255, 255, 235), (20, 20, 20, 255)
    else:
        fill, ink = (0, 0, 0, 170), (255, 255, 255, 255)
    draw.rounded_rectangle((left, top, left + cw, top + ch), radius=14, fill=fill)
    draw.text((left + PAD_X - b[0], top + PAD_Y - b[1]), text, font=font, fill=ink)
    return layer


def build_layers(
    items: list[dict[str, Any]], lang: str = "ko"
) -> list[tuple[float, float, Image.Image]]:
    return [(o["start"], o["end"], draw_card(o, lang)) for o in items]
