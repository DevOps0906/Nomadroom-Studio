"""판정 엔진(순수 함수). 규칙 정본: `docs/01_PRD.md#9`, 해석: `tasks/task-005.md#구현 결정`.

DB·네트워크에 접근하지 않는다. 입력 모델 필드 이름은 DB 행과 같다.
"""

import unicodedata
import uuid
from collections.abc import Sequence
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

Status = Literal["producible", "pending", "excluded"]
Reason = Literal[
    "market",
    "category",
    "format",
    "views_min",
    "not_cc",
    "broadcaster",
    "keyword",
    "no_prev",
    "license_unknown",
    "growth_out_of_range",
]

MIN_INTERVAL = timedelta(hours=24)
MAX_INTERVAL = timedelta(days=7)
_PCT_QUANT = Decimal("0.01")


class _Row(BaseModel):
    model_config = ConfigDict(frozen=True)


class Profile(_Row):
    id: uuid.UUID
    market: str
    format: Literal["all", "short", "long"]
    category: str | None
    min_views: int
    max_growth_pct: Decimal  # 단위 %(0.6 = 0.6%)
    keywords: tuple[str, ...] = ()
    cc_only: bool
    include_broadcast: bool


class Candidate(_Row):
    id: uuid.UUID
    title: str
    category: str | None
    format: str | None
    market: str
    license_cc: bool | None  # null = 미확인
    is_broadcaster: bool  # broadcaster_channels 목록 포함 여부(미확인 없음)


class Observation(_Row):
    id: uuid.UUID
    observed_at: AwareDatetime
    view_count: int


class Verdict(_Row):
    candidate_id: uuid.UUID
    profile_id: uuid.UUID
    status: Status
    reason: Reason | None  # 제작 가능이면 null
    growth_pct: Decimal | None  # 소수 둘째 자리 반올림
    prev_observation_id: uuid.UUID | None  # 유효 간격으로 쓴 이전 관측. 조건 제외·no_prev면 null
    curr_observation_id: uuid.UUID


class Representative(_Row):
    rep_status: Status
    rep_profile_id: uuid.UUID
    used: bool  # true면 화면 표시는 판정보다 `used` 우선


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _has_keyword(title: str, keywords: Sequence[str]) -> bool:
    normalized = _normalize(title)
    return any(_normalize(k) in normalized for k in keywords)


def _condition_reason(p: Profile, c: Candidate, curr: Observation) -> Reason | None:
    """순서 1(조건 제외). PRD#9 표 위쪽 행부터 확인한다."""
    if c.market != p.market:
        return "market"
    if p.category is not None and c.category != p.category:
        return "category"
    if p.format != "all" and c.format != p.format:
        return "format"
    if curr.view_count < p.min_views:
        return "views_min"
    if p.cc_only and c.license_cc is False:
        return "not_cc"
    if not p.include_broadcast and c.is_broadcaster:
        return "broadcaster"
    if p.keywords and not _has_keyword(c.title, p.keywords):
        return "keyword"
    return None


def valid_prev(prev: Observation | None, curr: Observation) -> Observation | None:
    """관측 간격이 24시간 이상 7일 이하(양 끝 포함)일 때만 이전 관측으로 인정한다."""
    if prev is None:
        return None
    gap = curr.observed_at - prev.observed_at
    return prev if MIN_INTERVAL <= gap <= MAX_INTERVAL else None


def judge(
    profile: Profile,
    candidate: Candidate,
    prev_obs: Observation | None,
    curr_obs: Observation,
) -> Verdict:
    def verdict(
        status: Status,
        reason: Reason | None,
        growth: Decimal | None = None,
        prev_id: uuid.UUID | None = None,
    ) -> Verdict:
        return Verdict(
            candidate_id=candidate.id,
            profile_id=profile.id,
            status=status,
            reason=reason,
            growth_pct=growth,
            prev_observation_id=prev_id,
            curr_observation_id=curr_obs.id,
        )

    reason = _condition_reason(profile, candidate, curr_obs)
    if reason is not None:
        return verdict("excluded", reason)

    prev = valid_prev(prev_obs, curr_obs)
    if prev is None:
        return verdict("pending", "no_prev")
    if profile.cc_only and candidate.license_cc is None:
        return verdict("pending", "license_unknown", prev_id=prev.id)

    if prev.view_count == 0:
        return verdict("excluded", "growth_out_of_range", prev_id=prev.id)
    growth = Decimal(curr_obs.view_count - prev.view_count) * 100 / Decimal(prev.view_count)
    rounded = growth.quantize(_PCT_QUANT, rounding=ROUND_HALF_UP)
    if Decimal(0) <= growth <= profile.max_growth_pct:
        return verdict("producible", None, rounded, prev.id)
    return verdict("excluded", "growth_out_of_range", rounded, prev.id)


_REP_PRIORITY: tuple[Status, ...] = ("producible", "pending")


def pick_representative(verdicts: Sequence[Verdict], used: bool) -> Representative:
    """verdicts는 프로필 순서(position). 제작 가능 > 근거 대기 > 첫 프로필."""
    if not verdicts:
        raise ValueError("verdicts가 비어 있다")
    chosen = next(
        (v for status in _REP_PRIORITY for v in verdicts if v.status == status),
        verdicts[0],
    )
    return Representative(rep_status=chosen.status, rep_profile_id=chosen.profile_id, used=used)
