"""쇼핑 문구 레이어: 문장 자막(자동 줄바꿈)·CTA(4번 문장)·제휴 표기(고정 위치, 영상 내내).

글꼴 선택·자동 축소·지연 그리기(Layer)는 예능형(production.variety.text)을 재사용한다.
위치·크기 상수는 가정(05 쇼핑 spec "위치 고정")이며 리포트에 글꼴만 기록한다.
ja(task-050 K6): 공백이 없는 글이라 글자 단위로 줄을 나누고 행두·행말 금칙을 지킨다.
"""

import math

from PIL import Image, ImageDraw, ImageFont

from production.errors import RenderFailed, TextTooLong
from production.variety.text import (
    MAX_TEXT_H,
    MAX_TEXT_W,
    MIN_SIZE,
    RED,
    WHITE,
    Layer,
    pick_font,
)

W, H = 1080, 1920
FPS = 30
PAD_X, PAD_Y = 28, 16
SUB_SIZE, SUB_CY, SUB_FILL = 56, 1380, (0, 0, 0, 200)
CTA_SIZE, CTA_CY = 60, 1620
DISC_SIZE, DISC_X, DISC_Y, DISC_FILL = 34, 48, 96, (0, 0, 0, 160)
MAX_LINES = 3
# 행두 금칙(줄 첫 글자 불가): 닫는 괄호·구두점·장음·작은 가나 등
NO_START = frozenset(
    "、。，．・：；？！ー―‐〜…‥」』）〕］｝〉》】〟’”"
    "ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶ々ゝゞヽヾ"
    ",.:;!?)]}%"
)
# 행말 금칙(줄 끝 글자 불가): 여는 괄호
NO_END = frozenset("「『（〔［｛〈《【〝‘“([{")


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """공백 단위 탐욕 줄바꿈(한 단어가 폭을 넘으면 그대로 두고 호출자가 글자를 줄인다)."""
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            cand = f"{cur} {word}" if cur else word
            if cur and font.getlength(cand) > max_w:
                lines.append(cur)
                cur = word
            else:
                cur = cand
        lines.append(cur)
    return [line for line in lines if line] or [""]


def wrap_ja(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """글자 단위 탐욕 줄바꿈 + 금칙. 넘치는 글자가 행두 금칙이면 앞 글자를 함께 다음 줄로
    보내고(追い出し), 줄 끝이 행말 금칙이면 그 글자를 다음 줄로 보낸다. 한 글자 줄은 그대로."""
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for ch in para:
            if not cur or font.getlength(cur + ch) <= max_w:
                cur += ch
                continue
            carry = ch
            while carry[0] in NO_START and len(cur) > 1:
                cur, carry = cur[:-1], cur[-1] + carry
            while cur[-1] in NO_END and len(cur) > 1:
                cur, carry = cur[:-1], cur[-1] + carry
            lines.append(cur.strip())
            cur = carry.lstrip()
        lines.append(cur.strip())
    return [line for line in lines if line] or [""]


def _fit_wrapped(text: str, size: int, max_w: int, fonts: list[str], lang: str):
    path = pick_font(text, lang)
    fonts.append(path.stem)
    wrap = wrap_ja if lang == "ja" else _wrap
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    for current in range(size, MIN_SIZE - 1, -2):
        font = ImageFont.truetype(str(path), current)
        lines = wrap(text, font, max_w)
        if len(lines) > MAX_LINES or any(font.getlength(x) > max_w for x in lines):
            continue
        joined = "\n".join(lines)
        box = probe.multiline_textbbox((0, 0), joined, font=font, align="center")
        if box[3] - box[1] > MAX_TEXT_H:
            raise RenderFailed("문구 높이 초과")
        return joined, font, box
    raise TextTooLong("자동 축소 후에도 폭 초과")


def _pill(text, size, fill, cx, cy, start_f, end_f, fonts, lang, max_w=MAX_TEXT_W - 2 * PAD_X):
    joined, font, box = _fit_wrapped(text, size, max_w, fonts, lang)
    tw, th = box[2] - box[0], box[3] - box[1]
    # 여러 줄 bbox는 줄 간격 때문에 실수일 수 있다(ja 줄바꿈에서 발견) → 정수 픽셀로 올림
    pw, ph = math.ceil(tw + 2 * PAD_X), math.ceil(th + 2 * PAD_Y)

    def draw() -> Image.Image:
        img = Image.new("RGBA", (pw, ph))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, pw - 1, ph - 1), radius=min(ph, 60) // 2, fill=fill)
        d.multiline_text(
            (PAD_X - box[0], PAD_Y - box[1]), joined, font=font, fill=WHITE, align="center"
        )
        return img

    x = min(max(round(cx - pw / 2), 0), W - pw) if cx is not None else DISC_X
    y = min(max(round(cy - ph / 2), 0), H - ph) if cx is not None else DISC_Y
    return Layer(pw, ph, x, y, start_f / FPS, end_f / FPS, draw)


def subtitle_layer(
    text: str, start_f: int, end_f: int, fonts: list[str], lang: str = "ko"
) -> Layer:
    one = text.replace("\n", "" if lang == "ja" else " ")
    return _pill(one, SUB_SIZE, SUB_FILL, W / 2, SUB_CY, start_f, end_f, fonts, lang)


def cta_layer(text: str, start_f: int, end_f: int, fonts: list[str], lang: str = "ko") -> Layer:
    return _pill(text, CTA_SIZE, RED, W / 2, CTA_CY, start_f, end_f, fonts, lang)


def disclosure_layer(text: str, frames: int, fonts: list[str], lang: str = "ko") -> Layer:
    """제휴 표기: 왼쪽 위 고정 위치, 0~끝 프레임."""
    return _pill(text, DISC_SIZE, DISC_FILL, None, None, 0, frames, fonts, lang, max_w=W // 2)
