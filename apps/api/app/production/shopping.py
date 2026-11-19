"""쇼핑 작업(kind=shopping) 입력 모델·금지 품목 검사·승인용 자산 맵·게시 문구(A-21).

근거: docs/04_API.md#A-09·#A-10·#A-21, docs/05_DATA_MODEL.md#쇼핑-확장,
tasks/task-044.md#착수-결정 P1·P6·P7·P8.
- 제휴 링크(affiliates)는 응답·게시 문구에만 쓰고 로그에 남기지 않는다.
- 권리(rights)는 사용자 입력만 받는다(gen·reviewed 없음, basis ai_generated 거부
  — AI 생성은 task-054 경로).
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
)

# 쇼핑 원본(source_upload) 작업당 상한, pending 포함(가정, 000023 트리거와 같은 값)
MAX_SOURCES = 10
MAX_IMAGES = 10  # 쇼핑 사진(image) 작업당 상한, pending 포함(가정)
MAX_NARRATIONS = 4  # 문장별 녹음 4개(사용자 결정 2026-11-20, TTS 꺼짐 대체), pending 포함
# 쇼핑에서 이전 pending을 지우지 않고 상한에 pending을 포함하는 업로드 kind(P5)
MULTI_LIMITS = {"source_upload": MAX_SOURCES, "image": MAX_IMAGES, "narration": MAX_NARRATIONS}
MAX_AFFILIATES = 20  # 000021 production_affiliates_valid와 같은 값
MAX_URL = 2048
# 제어(Cc)·서식(Cf: 폭 없는 문자·bidi 제어)·줄/문단 구분(Zl·Zp: U+2028·2029) 거부(리뷰 반영 5)
_BAD_CATEGORIES = ("Cc", "Cf", "Zl", "Zp")
_URL_CHARS = re.compile(r"[^\s\x00-\x1f\x7f]+")

# 금지 품목(의약품·건강기능식품) 키워드.
# 정규화(NFKC·casefold·문자·숫자만) 뒤 부분 문자열로 찾는다(가정).
BANNED_KEYWORDS = (
    "의약품",
    "일반의약품",
    "전문의약품",
    "건강기능식품",
    "건기식",
    "건강보조식품",
    "영양제",
    "영양보충제",
    "식이보충제",
    "처방약",
    "다이어트약",
    "医薬品",
    "医薬部外品",
    "健康食品",
    "機能性表示食品",
    "特定保健用食品",
    "サプリメント",
    "サプリ",
    "supplement",
    "pharmaceutical",
    "medicine",
)


def no_control(v: Any) -> Any:
    if isinstance(v, str) and any(unicodedata.category(ch) in _BAD_CATEGORIES for ch in v):
        raise ValueError("제어 문자는 사용할 수 없습니다")
    return v


def _text(max_len: int) -> Any:
    return Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=max_len),
        BeforeValidator(no_control),
    ]


def _url(v: str, *, https_only: bool) -> str:
    """공백·제어 문자 없는 http(s) URL(사용자 정보 없음). 입력 값은 오류 문구에 넣지 않는다."""
    if len(v) > MAX_URL or not _URL_CHARS.fullmatch(v):
        raise ValueError("링크 형식이 올바르지 않습니다")
    parts = urlsplit(v)
    schemes = ("https",) if https_only else ("http", "https")
    if parts.scheme not in schemes or not parts.hostname or "@" in parts.netloc:
        raise ValueError("링크 형식이 올바르지 않습니다")
    return v


def _https(v: str) -> str:
    return _url(v, https_only=True)


def _http_or_https(v: str) -> str:
    return _url(v, https_only=False)


Short = _text(100)
Text = _text(300)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(_In):
    gender: Literal["female", "male", "all"] | None = None
    age: Short | None = None


class BriefIn(_In):
    """상품: product_name·pain, 여행: destination·product_type·appeal.
    공통: 장면·빼야 할 말·확인된 사실·target."""

    product_name: Short | None = None
    pain: Text | None = None
    destination: Short | None = None
    product_type: Literal["stay", "tour", "package"] | None = None
    appeal: Text | None = None
    scenes: Annotated[list[Text], Field(max_length=5)] = []
    avoid: Text | None = None
    facts: Annotated[list[Text], Field(max_length=10)] = []
    target: Target | None = None


_PRODUCT_ONLY = ("product_name", "pain")
_TRAVEL_ONLY = ("destination", "product_type", "appeal")


def brief_vertical_field(brief: Mapping[str, Any] | None, vertical: str | None) -> str | None:
    """분야에 맞지 않는 brief 필드 이름(없으면 None)."""
    if not brief:
        return None
    other = _TRAVEL_ONLY if vertical == "product" else _PRODUCT_ONLY
    for name in other:
        if brief.get(name) not in (None, "", []):
            return f"brief.{name}"
    return None


class AffiliateIn(_In):
    lang: Literal["ko", "ja"]
    partner: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=50),
        BeforeValidator(no_control),
    ]
    url: Annotated[str, AfterValidator(_https)]  # DB check가 https만 허용(000021)


Affiliates = Annotated[list[AffiliateIn], Field(max_length=MAX_AFFILIATES)]


class RightsIn(_In):
    """자산 권리(사용자 입력). gen·reviewed는 받지 않는다(P6)."""

    basis: Literal["own", "licensed", "permission", "quote", "platform_audio"]
    source_url: Annotated[str, AfterValidator(_http_or_https)] | None = None
    author: Short | None = None
    has_person: bool = False
    portrait_consent: bool = False
    note: _text(500) | None = None  # type: ignore[valid-type]


# --- 금지 품목(P7) -----------------------------------------------------------------


def normalize(text: str) -> str:
    """NFKC → casefold → 문자·숫자만(공백·구두점·폭 없는 문자 제거)."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in folded if unicodedata.category(ch)[0] in "LN")


_BANNED_NORM = tuple({normalize(k) for k in BANNED_KEYWORDS})


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _strings(v)


def has_banned(*values: Any) -> bool:
    """제목·brief·댓글 키워드 등 텍스트에 금지 품목 키워드가 있는지."""
    for raw in values:
        for s in _strings(raw):
            flat = normalize(s)
            if any(k in flat for k in _BANNED_NORM):
                return True
    return False


# --- 승인·저장 검증용 자산 맵(P1) ----------------------------------------------------

MAP_KINDS = ("source_upload", "source", "image", "bgm", "narration")


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def assets_map(rows: list[dict]) -> dict[str, dict[str, Any]]:
    """이 작업 소유 자산 행 → validate_shopping_spec의 assets.

    rights·reviewed는 사용자 입력 자산(파생 source는 부모 source_upload) 값,
    duration은 파생 source 값.
    reviewed는 사용자 jsonb에서 읽지 않는다(AI 생성 검수는 task-054 칼럼).
    """
    by_id = {str(r["id"]): r for r in rows}
    child_duration: dict[str, float | None] = {}
    for r in rows:
        if r["kind"] == "source" and r["status"] == "ready" and r.get("parent_asset_id"):
            child_duration.setdefault(str(r["parent_asset_id"]), _num(r.get("duration_sec")))
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        kind = r["kind"]
        if kind not in MAP_KINDS:
            continue
        rights = r.get("rights")
        duration = _num(r.get("duration_sec"))
        if kind == "source":
            parent = by_id.get(str(r.get("parent_asset_id")))
            rights = parent.get("rights") if parent else None
        elif kind == "source_upload":
            duration = child_duration.get(str(r["id"]))
        out[str(r["id"])] = {
            "kind": kind,
            "status": r["status"],
            "duration_sec": duration,
            "width": None,
            "height": None,
            "rights": rights if isinstance(rights, Mapping) else None,
            "reviewed": False,
        }
    return out


def spec_asset_refs(spec: Any) -> set[str]:
    """편집안이 참조하는 자산 ID(컷 원본·BGM·내레이션)."""
    refs: set[str] = set()
    if not isinstance(spec, Mapping):
        return refs
    cuts = spec.get("cuts")
    if isinstance(cuts, list):
        refs.update(
            c["source_asset_id"]
            for c in cuts
            if isinstance(c, Mapping) and isinstance(c.get("source_asset_id"), str)
        )
    if isinstance(spec.get("bgm_asset_id"), str):
        refs.add(spec["bgm_asset_id"])
    voice = spec.get("voice")
    if isinstance(voice, Mapping) and isinstance(voice.get("narration_asset_id"), str):
        refs.add(voice["narration_asset_id"])
    return refs


def product_name(job: Mapping[str, Any]) -> str | None:
    brief = job.get("brief")
    if not isinstance(brief, Mapping):
        return None
    key = "destination" if job.get("vertical") == "travel" else "product_name"
    name = brief.get(key)
    return name if isinstance(name, str) else None


# --- A-21 게시 문구(P8) -------------------------------------------------------------

DISCLOSURE = {
    "ko": "[광고] 이 영상에는 제휴 링크가 있어 구매 시 일정 수수료를 받을 수 있습니다.",
    "ja": "【PR】この動画にはアフィリエイトリンクが含まれています。",
}
KEYWORD_GUIDE = {
    "ko": '댓글에 "{kw}"를 남겨 주시면 링크를 안내해 드려요.',
    "ja": "コメントに「{kw}」と書いてくれたらリンクをご案内します。",
}
LINKS_HEADER = {"ko": "구매 링크", "ja": "購入リンク"}
RECOMMENDED_TIME = "인스타 오전 8시(옵션 18시) — 강의 기준 가정"


def publish_text(lang: str, affiliates: Any, comment_keyword: str | None) -> dict[str, str]:
    """caption 첫 줄 대가성 표기 + 댓글 키워드 안내, pinned_comment는 lang이 같은 제휴 링크."""
    caption = [DISCLOSURE[lang]]
    if comment_keyword and comment_keyword.strip():
        caption.append(KEYWORD_GUIDE[lang].format(kw=comment_keyword.strip()))
    links = [
        f"{a['partner']}: {a['url']}"
        for a in (affiliates if isinstance(affiliates, list) else [])
        if isinstance(a, Mapping) and a.get("lang") == lang and a.get("url") and a.get("partner")
    ]
    pinned = "\n".join([LINKS_HEADER[lang], *links]) if links else ""
    return {
        "caption": "\n".join(caption),
        "pinned_comment": pinned,
        "recommended_time": RECOMMENDED_TIME,
    }
