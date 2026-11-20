"""예능형 문구 레이어(제목·대사 자막·반응 자막). 텍스트는 PIL로만 그린다(drawtext 금지).

글꼴(W8·W9): 예제 글꼴(Cafe24 Ohsquare·잘난체)은 라이선스 근거가 없어 동봉하지 않는다.
Pretendard-Black으로 대체하고, 문구에 Pretendard 글리프가 없는 글자가 있으면 그 문구 전체를
NotoSansCJKkr-Bold로 그린다. 둘 다 없으면 RenderFailed(glyph_missing). 이모지는 미지원.
ja(task-051): 제목 Noto Sans CJK JP Black, 대사·반응 자막 JP Bold(task-050 fonts.py), 줄은 글자 단위
줄바꿈 + 금칙(shopping.text.wrap_ja)으로 최대 3줄. ko 경로는 바뀌지 않는다.
크기 상수는 docs/research/variety-shorts-zip-analysis.md#3 실측 위치 기준(05 예능형 장 기록).
"""

import math
import struct
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from production import fonts as lang_fonts
from production.adapter_variety import MAX_TEXT_LINES, frame_of
from production.errors import RenderFailed, TextTooLong

W, H = 1080, 1920
FONTS = Path(__file__).resolve().parent.parent.parent / "fonts"
PRIMARY_FONT = FONTS / "Pretendard-Black.otf"
FALLBACK_FONT = FONTS / "NotoSansCJKkr-Bold.otf"
JA_FONTS = (FONTS / "NotoSansCJKjp-Bold.otf",)  # 일본어는 한국어 글꼴로 대체하지 않는다

RED = (232, 32, 42, 255)
WHITE = (255, 255, 255, 255)
MIN_SIZE = 24
MAX_TEXT_W = 1000  # 문구(알약·테두리 포함) 최대 폭 px
MAX_TEXT_H = 400  # 문구 높이 상한 px(최대 3줄, 리뷰 반영)
# 제목: 띠 위 328~496(2줄 중심 370·454, 1줄 412). 빨강 + 흰 테두리
TITLE_SIZE, TITLE_STROKE = 76, 6
TITLE_CENTERS = {1: (412,), 2: (370, 454)}
TITLE_GAP, TITLE_BOTTOM = 8, 552  # ja 여러 줄 제목: 블록 간격, 바닥 상한(띠 위 560 - 8)
# 대사 자막: 띠 아래쪽 안(중심 y 1240) 알약. line=검정 바탕, punch=빨강 바탕(글자 더 큼)
SUB_CY = 1240
SUB_SIZE = {"line": 52, "punch": 60}
SUB_FILL = {"line": (0, 0, 0, 230), "punch": RED}
PILL_PAD_X, PILL_PAD_Y = 28, 16
# 반응 자막: 빨강 + 흰 테두리, 중심 (x, y) 자유 위치(캔버스 안으로 당김)
REACT_SIZE, REACT_STROKE = 48, 5


@cache
def _codepoints(path: Path) -> frozenset[int]:
    """OTF/TTF cmap(형식 4·12)에서 글리프가 있는(glyph id≠0) 코드 포인트 집합."""
    data = path.read_bytes()
    num_tables = struct.unpack_from(">H", data, 4)[0]
    cmap = None
    for i in range(num_tables):
        tag, _, offset, _ = struct.unpack_from(">4sIII", data, 12 + 16 * i)
        if tag == b"cmap":
            cmap = offset
    if cmap is None:
        return frozenset()
    count = struct.unpack_from(">H", data, cmap + 2)[0]
    subtables = {}
    for i in range(count):
        pid, eid, off = struct.unpack_from(">HHI", data, cmap + 4 + 8 * i)
        fmt = struct.unpack_from(">H", data, cmap + off)[0]
        subtables[(pid, eid, fmt)] = cmap + off
    for key in ((3, 10, 12), (0, 4, 12), (0, 6, 12)):
        if key in subtables:
            return _format12(data, subtables[key])
    for key in ((3, 1, 4), (0, 3, 4)):
        if key in subtables:
            return _format4(data, subtables[key])
    return frozenset()


def _format12(data: bytes, base: int) -> frozenset[int]:
    groups = struct.unpack_from(">I", data, base + 12)[0]
    out: set[int] = set()
    for i in range(groups):
        start, end, gid = struct.unpack_from(">III", data, base + 16 + 12 * i)
        out.update(c for c in range(start, end + 1) if gid + (c - start) != 0)
    return frozenset(out)


def _format4(data: bytes, base: int) -> frozenset[int]:
    seg2 = struct.unpack_from(">H", data, base + 6)[0]
    ends = base + 14
    starts = ends + seg2 + 2
    deltas = starts + seg2
    ranges = deltas + seg2
    out: set[int] = set()
    for i in range(0, seg2, 2):
        end = struct.unpack_from(">H", data, ends + i)[0]
        start = struct.unpack_from(">H", data, starts + i)[0]
        delta = struct.unpack_from(">h", data, deltas + i)[0]
        roff = struct.unpack_from(">H", data, ranges + i)[0]
        for c in range(start, min(end, 0xFFFE) + 1):
            if roff == 0:
                gid = (c + delta) & 0xFFFF
            else:
                gid = struct.unpack_from(">H", data, ranges + i + roff + 2 * (c - start))[0]
                gid = (gid + delta) & 0xFFFF if gid else 0
            if gid:
                out.add(c)
    return frozenset(out)


def pick_font(text: str, lang: str = "ko") -> Path:
    """문구 전체를 그릴 수 있는 첫 글꼴(ko: Pretendard → Noto KR, ja: Noto JP만, task-050 K5).
    없으면 glyph_missing."""
    needed = {ord(ch) for ch in text if not ch.isspace()}
    for path in JA_FONTS if lang == "ja" else (PRIMARY_FONT, FALLBACK_FONT):
        if needed <= _codepoints(path):
            return path
    raise RenderFailed("glyph_missing")


def _font_for(text: str, lang: str, title: bool) -> Path:
    """ja 제목은 JP Black(task-050 카테고리 ja와 같음), 나머지는 pick_font."""
    if lang == "ja" and title:
        if {ord(ch) for ch in text if not ch.isspace()} <= _codepoints(lang_fonts.NOTO_JP_BLACK):
            return lang_fonts.NOTO_JP_BLACK
        raise RenderFailed("glyph_missing")
    return pick_font(text, lang)


def _fit(text: str, path: Path, size: int, stroke: int, max_w: int, lang: str = "ko"):
    """자동 축소. ja는 크기마다 글자 단위 줄바꿈 + 금칙으로 다시 나눈다(최대 3줄).
    반환 (그릴 문구, 글꼴, bbox)."""
    from production.shopping.text import wrap_ja  # 순환 import 회피(shopping.text가 이 모듈을 쓴다)

    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    for current in range(size, MIN_SIZE - 1, -1):
        font = ImageFont.truetype(str(path), current)
        drawn = text
        if lang == "ja":
            lines = wrap_ja(text, font, max_w - 2 * stroke)
            if len(lines) > MAX_TEXT_LINES:
                continue
            drawn = "\n".join(lines)
        box = probe.textbbox((0, 0), drawn, font=font, stroke_width=stroke, align="center")
        if box[2] - box[0] <= max_w:
            if box[3] - box[1] > MAX_TEXT_H:  # 리뷰 반영: 줄 수 공격 등 높이 상한
                raise RenderFailed("문구 높이 초과")
            return drawn, font, box
    raise TextTooLong("자동 축소 후에도 폭 초과")


class Layer:
    """캔버스 위 (x, y)에 붙일 RGBA 레이어. 표시 구간은 출력 프레임 [fs, fe)(컷 격자와 같은
    frame_of 기준). 이미지는 처음 표시될 때 그리고(release로 버림) 크기만 미리 잰다."""

    def __init__(self, w, h, x, y, start, end, draw) -> None:
        self.w, self.h, self.x, self.y = w, h, x, y
        self.fs, self.fe = frame_of(start), frame_of(end)
        self._draw, self._image = draw, None

    @property
    def pixels(self) -> int:
        return self.w * self.h

    @property
    def image(self) -> Image.Image:
        if self._image is None:
            self._image = self._draw()
        return self._image

    def release(self) -> None:
        self._image = None


def _stroked(
    text: str, size: int, stroke: int, fonts: list[str], lang: str = "ko", title: bool = False
):
    path = _font_for(text, lang, title)
    fonts.append(path.stem)
    text, font, box = _fit(text, path, size, stroke, MAX_TEXT_W, lang)
    w, h = math.ceil(box[2] - box[0]), math.ceil(box[3] - box[1])

    def draw() -> Image.Image:
        img = Image.new("RGBA", (w, h))
        ImageDraw.Draw(img).text(
            (-box[0], -box[1]),
            text,
            font=font,
            fill=RED,
            stroke_width=stroke,
            stroke_fill=WHITE,
            align="center",
        )
        return img

    return w, h, draw


def title_layer(lines: list[str], fonts: list[str], lang: str = "ko") -> Image.Image:
    """제목 1~2줄을 캔버스 전체 크기 RGBA 한 장으로(영상 내내 표시, 고정 배경에 합친다)."""
    canvas = Image.new("RGBA", (W, H))
    parts = [_stroked(t, TITLE_SIZE, TITLE_STROKE, fonts, lang, title=True) for t in lines]
    tops = [cy - h // 2 for (_, h, _), cy in zip(parts, TITLE_CENTERS[len(lines)], strict=True)]
    if lang == "ja":  # ja는 줄바꿈으로 여러 줄이 될 수 있어 실제 높이로 쌓는다(ko 위치 불변)
        tops = title_tops([h for _, h, _ in parts])
    for (w, _, draw), top in zip(parts, tops, strict=True):
        canvas.alpha_composite(draw(), ((W - w) // 2, top))
    return canvas


def title_tops(heights: list[int]) -> list[int]:
    """ja 제목 블록 위치(task-051 리뷰 반영): 기본 중심(1줄 412, 2줄 370·454)에서 겹치지 않으면
    그대로, 겹치면 간격 TITLE_GAP으로 412 중심에 쌓고 바닥이 TITLE_BOTTOM을 넘으면 위로 올린다.
    맨 위가 0보다 위면 text_too_long."""
    tops = [cy - h // 2 for h, cy in zip(heights, TITLE_CENTERS[len(heights)], strict=True)]
    if len(heights) == 1 or tops[0] + heights[0] <= tops[1]:
        if tops[-1] + heights[-1] <= TITLE_BOTTOM and tops[0] >= 0:
            return tops
    total = sum(heights) + TITLE_GAP * (len(heights) - 1)
    top = min(TITLE_CENTERS[1][0] - total // 2, TITLE_BOTTOM - total)
    if top < 0:
        raise TextTooLong("제목 높이 초과")
    out = []
    for h in heights:
        out.append(top)
        top += h + TITLE_GAP
    return out


def subtitle_layer(sub: dict, fonts: list[str], lang: str = "ko") -> Layer:
    text, style = sub["text"], sub["style"]
    path = pick_font(text, lang)
    fonts.append(path.stem)
    text, font, box = _fit(text, path, SUB_SIZE[style], 0, MAX_TEXT_W - 2 * PILL_PAD_X, lang)
    tw, th = math.ceil(box[2] - box[0]), math.ceil(box[3] - box[1])
    pw, ph = tw + 2 * PILL_PAD_X, th + 2 * PILL_PAD_Y

    def draw() -> Image.Image:
        img = Image.new("RGBA", (pw, ph))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, pw - 1, ph - 1), radius=min(ph, 120) // 2, fill=SUB_FILL[style])
        d.text(
            (PILL_PAD_X - box[0], PILL_PAD_Y - box[1]), text, font=font, fill=WHITE, align="center"
        )
        return img

    x, y = (W - pw) // 2, min(max(SUB_CY - ph // 2, 0), H - ph)
    return Layer(pw, ph, x, y, sub["start"], sub["end"], draw)


def reaction_layer(r: dict, fonts: list[str], lang: str = "ko") -> Layer:
    w, h, draw = _stroked(r["text"], REACT_SIZE, REACT_STROKE, fonts, lang)
    x = min(max(round(r["x"] - w / 2), 0), W - w)
    y = min(max(round(r["y"] - h / 2), 0), H - h)
    return Layer(w, h, x, y, r["start"], r["end"], draw)
