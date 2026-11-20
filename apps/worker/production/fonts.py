"""언어별 글꼴(task-050 K5). 파일 출처·SHA-256·라이선스는 licenses/THIRD_PARTY.md.

lang=ja면 제목·자막·오버레이·CTA를 모두 Noto Sans CJK JP로 그린다(한국어 글꼴로 대체하지 않는다).
"""

from pathlib import Path

from production.errors import RenderFailed

FONTS = Path(__file__).resolve().parent.parent / "fonts"
PRETENDARD_BLACK = FONTS / "Pretendard-Black.otf"
NOTO_KR_BOLD = FONTS / "NotoSansCJKkr-Bold.otf"
NOTO_JP_BOLD = FONTS / "NotoSansCJKjp-Bold.otf"
NOTO_JP_BLACK = FONTS / "NotoSansCJKjp-Black.otf"

# 카테고리형: (제목, 자막·오버레이)
CATEGORY = {"ko": (PRETENDARD_BLACK, NOTO_KR_BOLD), "ja": (NOTO_JP_BLACK, NOTO_JP_BOLD)}


def category_fonts(lang: str) -> tuple[Path, Path]:
    if lang not in CATEGORY:
        raise RenderFailed("지원하지 않는 언어")
    return CATEGORY[lang]
