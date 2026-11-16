"""A-04 후보 목록 · A-06 관측 근거. 근거: tasks/task-011.md#구현 결정.

모든 조회는 service_role PostgREST + workspace_id 조건. 목록은 뷰 candidate_list_v(000008).
"""

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.auth.user import CurrentUser, get_current_user
from app.errors import ApiError, db_error, not_found
from app.routes.profiles import _json_list, _send
from app.verdict.engine import MIN_INTERVAL, Reason

logger = logging.getLogger("nomadroom.candidates")

router = APIRouter(prefix="/v1/candidates", tags=["candidates"])

VIEW = "candidate_list_v"
DisplayStatus = Literal["producible", "pending", "excluded", "used"]
COUNT_STATUSES: tuple[DisplayStatus, ...] = ("producible", "pending", "excluded", "used")
SORT_ORDERS = {
    "growth": "growth_pct.desc.nullslast,id.asc",
    "views": "curr_view_count.desc.nullslast,id.asc",
    "recent": "created_at.desc,id.asc",
}
THUMBNAIL_PREFIX = "https://i.ytimg.com/"
MAX_PAGE_SIZE = 60
MAX_PAGE = 1000
MAX_Q_LEN = 100
MAX_CATEGORY_LEN = 40
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_BS = "\\"
_DAY_SECONDS = Decimal(86400)
_DAYS_QUANT = Decimal("0.1")

ITEM_COLUMNS = (
    "id,thumbnail_url,display_status,genre,title,format,license_cc,used,growth_pct,"
    "prev_observed_at,prev_view_count,curr_observed_at,curr_view_count,latest_observed_at"
)
EVIDENCE_COLUMNS = (
    "id,title,display_status,growth_pct,reason,prev_observed_at,prev_view_count,"
    "curr_observed_at,curr_view_count,latest_observed_at"
)


# --- 응답 모델 -----------------------------------------------------------------


class ObservationOut(BaseModel):
    observed_at: datetime
    view_count: int


class CountsOut(BaseModel):
    total: int
    producible: int
    pending: int
    excluded: int
    used: int


class CandidateItemOut(BaseModel):
    id: uuid.UUID
    thumbnail_url: str | None
    status: DisplayStatus
    genre: str | None
    title: str
    format: Literal["short", "long"] | None
    profile_names: list[str]
    license_cc: bool | None
    prev: ObservationOut | None
    curr: ObservationOut | None
    growth_pct: float | None
    period_days: float | None
    next_observation_at: datetime | None
    used: bool


class CandidateListOut(BaseModel):
    counts: CountsOut
    categories: list[str]
    items: list[CandidateItemOut]
    updated_at: datetime


class EvidenceCandidateOut(BaseModel):
    id: uuid.UUID
    title: str
    status: DisplayStatus


class EvidenceOut(BaseModel):
    candidate: EvidenceCandidateOut
    prev: ObservationOut | None
    curr: ObservationOut | None
    growth_pct: float | None
    reason: Reason | None
    needs_prev: bool
    next_observation_at: datetime | None


# --- 공통 헬퍼(dashboard도 사용) -------------------------------------------------


def parse_ts(v: Any) -> datetime | None:
    if v is None:
        return None
    try:
        dt = datetime.fromisoformat(v)
    except (TypeError, ValueError) as exc:
        raise db_error() from exc
    return dt.astimezone(UTC)


def safe_thumbnail(url: Any) -> str | None:
    """비신뢰 데이터: i.ytimg.com https만 내보낸다."""
    if isinstance(url, str) and url.startswith(THUMBNAIL_PREFIX):
        return url
    return None


def observation(at: Any, count: Any) -> ObservationOut | None:
    observed_at = parse_ts(at)
    if observed_at is None or count is None:
        return None
    return ObservationOut(observed_at=observed_at, view_count=count)


def next_observation_at(status: str, latest: Any) -> datetime | None:
    """근거 대기만: 최신 관측 + 24시간(과거여도 그대로)."""
    latest_at = parse_ts(latest)
    if status != "pending" or latest_at is None:
        return None
    return latest_at + MIN_INTERVAL


def period_days(prev: ObservationOut | None, curr: ObservationOut | None) -> float | None:
    if prev is None or curr is None:
        return None
    seconds = Decimal(str((curr.observed_at - prev.observed_at).total_seconds()))
    return float((seconds / _DAY_SECONDS).quantize(_DAYS_QUANT, rounding=ROUND_HALF_UP))


def to_float(v: Any) -> float | None:
    return None if v is None else float(v)


async def count_rows(request: Request, path: str, params: dict[str, str]) -> int:
    """exact HEAD 요청의 Content-Range 총계(`0-2/3`·`*/0`)."""
    resp = await _send(request, "HEAD", path, params=params, headers={"Prefer": "count=exact"})
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: HEAD %s", resp.status_code, path)
        raise db_error()
    total = resp.headers.get("content-range", "").rpartition("/")[2]
    if not total.isdigit():
        raise db_error()
    return int(total)


async def profile_names_by_id(request: Request, workspace_id: uuid.UUID) -> dict[str, str]:
    params = {"select": "id,name", "workspace_id": f"eq.{workspace_id}"}
    rows = _json_list(await _send(request, "GET", "profiles", params=params), "GET", "profiles")
    return {r["id"]: r["name"] for r in rows}


# --- 입력 검증 -----------------------------------------------------------------


def _validation(field: str, message: str = "입력값이 올바르지 않습니다.") -> ApiError:
    return ApiError(400, "VALIDATION", message, field)


def _check_text(value: str, field: str, max_len: int) -> str:
    if _CONTROL_CHARS.search(value):
        raise _validation(field, "제어 문자는 사용할 수 없습니다.")
    value = value.strip()
    if not 1 <= len(value) <= max_len:
        raise _validation(field, f"1~{max_len}자여야 합니다.")
    return value


def _like_pattern(q: str) -> str:
    """PostgREST or=() 안의 ilike 값. LIKE 특수문자는 리터럴, 값은 큰따옴표로 감싼다.

    PostgREST는 `*`를 항상 `%`로 바꾸므로 리터럴 `*`는 표현할 수 없다. 한 글자 와일드카드 `_`로
    바꿔 원래 문자열을 놓치지 않게 한다(로컬 PostgREST 16.5에서 확인).
    """
    out = []
    for ch in q:
        if ch in (_BS, "%", "_"):
            out.append(_BS + ch)
        elif ch == "*":
            out.append("_")
        else:
            out.append(ch)
    pattern = "*" + "".join(out) + "*"
    return '"' + pattern.replace(_BS, _BS + _BS).replace('"', _BS + '"') + '"'


# --- A-04 ----------------------------------------------------------------------


@router.get("", response_model=CandidateListOut)
async def list_candidates(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    status: Literal["all", "producible", "pending", "excluded", "used"] = "all",
    category: str | None = None,
    format: Literal["all", "short", "long"] = "all",
    profile_id: uuid.UUID | None = None,
    license: Literal["cc", "any"] = "any",
    q: str | None = None,
    sort: Literal["growth", "views", "recent"] = "recent",
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 24,
) -> CandidateListOut:
    ws = user.workspace_id
    # status 외 필터(counts에도 같이 적용)
    filters: dict[str, str] = {"workspace_id": f"eq.{ws}"}
    embed = ""
    if category is not None:
        filters["category"] = f"eq.{_check_text(category, 'category', MAX_CATEGORY_LEN)}"
    if format != "all":
        filters["format"] = f"eq.{format}"
    if license == "cc":
        filters["license_cc"] = "is.true"
    # 공백만인 q는 필터 없음. 제어 문자가 섞였으면 _check_text가 400
    if q is not None and (q.strip() or _CONTROL_CHARS.search(q)):
        v = _like_pattern(_check_text(q, "q", MAX_Q_LEN))
        filters["or"] = f"(title.ilike.{v},channel_title.ilike.{v})"
    if profile_id is not None:
        embed = ",candidate_verdicts!inner(profile_id)"
        filters["candidate_verdicts.profile_id"] = f"eq.{profile_id}"
        filters["candidate_verdicts.workspace_id"] = f"eq.{ws}"

    item_params = {
        **filters,
        "select": ITEM_COLUMNS + embed,
        "order": SORT_ORDERS[sort],
        "limit": str(size),
        "offset": str((page - 1) * size),
    }
    if status != "all":
        item_params["display_status"] = f"eq.{status}"

    async def fetch_items() -> list:
        return _json_list(await _send(request, "GET", VIEW, params=item_params), "GET", VIEW)

    async def fetch_categories() -> list[str]:
        params = {
            "select": "category",
            "workspace_id": f"eq.{ws}",
            "category": "not.is.null",
        }
        resp = await _send(request, "GET", "candidates", params=params)
        rows = _json_list(resp, "GET", "candidates")
        return sorted({r["category"] for r in rows if r.get("category")})

    count_params = [
        {**filters, "select": "id" + embed, "display_status": f"eq.{s}"} for s in COUNT_STATUSES
    ]
    rows, categories, names, *counts = await asyncio.gather(
        fetch_items(),
        fetch_categories(),
        profile_names_by_id(request, ws),
        *(count_rows(request, VIEW, p) for p in count_params),
    )
    by_status = dict(zip(COUNT_STATUSES, counts, strict=True))

    # 판정이 excluded가 아닌 프로필 이름(name 순)
    profile_names: dict[str, list[str]] = {}
    if rows:
        ids = ",".join(r["id"] for r in rows)
        params = {
            "select": "candidate_id,profile_id",
            "workspace_id": f"eq.{ws}",
            "candidate_id": f"in.({ids})",
            "status": "neq.excluded",
        }
        verdicts = _json_list(
            await _send(request, "GET", "candidate_verdicts", params=params),
            "GET",
            "candidate_verdicts",
        )
        for v in verdicts:
            name = names.get(v["profile_id"])
            if name is not None:
                profile_names.setdefault(v["candidate_id"], []).append(name)

    items = []
    for r in rows:
        prev = observation(r["prev_observed_at"], r["prev_view_count"])
        curr = observation(r["curr_observed_at"], r["curr_view_count"])
        items.append(
            CandidateItemOut(
                id=r["id"],
                thumbnail_url=safe_thumbnail(r["thumbnail_url"]),
                status=r["display_status"],
                genre=r["genre"],
                title=r["title"],
                format=r["format"],
                profile_names=sorted(profile_names.get(r["id"], [])),
                license_cc=r["license_cc"],
                prev=prev,
                curr=curr,
                growth_pct=to_float(r["growth_pct"]),
                period_days=period_days(prev, curr),
                next_observation_at=next_observation_at(
                    r["display_status"], r["latest_observed_at"]
                ),
                used=r["used"],
            )
        )

    return CandidateListOut(
        counts=CountsOut(total=sum(counts), **by_status),
        categories=categories,
        items=items,
        updated_at=datetime.now(UTC),
    )


# --- A-06 ----------------------------------------------------------------------


@router.get("/{candidate_id}/evidence", response_model=EvidenceOut)
async def get_evidence(
    candidate_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> EvidenceOut:
    params = {
        "select": EVIDENCE_COLUMNS,
        "id": f"eq.{candidate_id}",
        "workspace_id": f"eq.{user.workspace_id}",
    }
    rows = _json_list(await _send(request, "GET", VIEW, params=params), "GET", VIEW)
    if not rows:
        raise not_found()  # 없는 id·타 워크스페이스 모두 404
    r = rows[0]
    candidate = EvidenceCandidateOut(id=r["id"], title=r["title"], status=r["display_status"])
    next_at = next_observation_at(r["display_status"], r["latest_observed_at"])
    curr = observation(r["curr_observed_at"], r["curr_view_count"])
    if curr is None:
        # 대표 판정 없음 또는 curr 관측 정리됨
        return EvidenceOut(
            candidate=candidate,
            prev=None,
            curr=None,
            growth_pct=None,
            reason=None,
            needs_prev=True,
            next_observation_at=next_at,
        )
    prev = observation(r["prev_observed_at"], r["prev_view_count"])
    return EvidenceOut(
        candidate=candidate,
        prev=prev,
        curr=curr,
        growth_pct=to_float(r["growth_pct"]),
        reason=r["reason"],
        needs_prev=prev is None,
        next_observation_at=next_at,
    )
