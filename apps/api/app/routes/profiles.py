"""A-03 프로필: 목록·조건 수정(낙관적 잠금)·선택(원자적 RPC). 근거: tasks/task-010.md#구현 결정."""

import logging
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from app.auth.user import CurrentUser, get_current_user
from app.errors import ApiError, db_error, not_found
from app.supabase import rest_url, service_headers

logger = logging.getLogger("nomadroom.profiles")

router = APIRouter(prefix="/v1/profiles", tags=["profiles"])

COLUMNS = (
    "id,name,market,format,category,min_views,max_growth_pct,keywords,"
    "cc_only,include_broadcast,selected,updated_at"
)
MAX_SELECTED = 3
MAX_KEYWORDS = 5
MAX_CATEGORY_LEN = 40
CATEGORY_ALL = "전체"
MAX_LIST_LEN = 20  # 중복 제거 전 원본 목록 상한
MAX_RAW_TEXT_LEN = 200  # 공백 제거 전 원본 문자열 상한
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

# RPC set_profile_selection 비즈니스 예외(SQLSTATE) → 400
_RPC_ERRORS = {
    "NR001": "프로필은 최대 3개까지 선택할 수 있습니다.",
    "NR002": "없는 프로필이 포함되어 있습니다.",
}


def conflict() -> ApiError:
    return ApiError(
        409, "CONFLICT", "다른 곳에서 먼저 수정되었습니다. 다시 불러온 뒤 시도하세요.", "updated_at"
    )


def _require_str(v: Any) -> Any:
    if not isinstance(v, str):
        raise ValueError("ISO 8601 문자열이어야 합니다")
    return v


def _raw_text(v: Any) -> Any:
    """정규화(공백 제거) 전 원본 문자열의 길이·제어 문자를 검사한다."""
    if isinstance(v, str):
        if len(v) > MAX_RAW_TEXT_LEN:
            raise ValueError("200자 이하여야 합니다")
        if _CONTROL_CHARS.search(v):
            raise ValueError("제어 문자는 사용할 수 없습니다")
    return v


# BeforeValidator는 뒤에 둔 것이 먼저 실행된다: 원본 검사 → 공백 제거·길이 검사
Keyword = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=30),
    BeforeValidator(_raw_text),
]


class ProfileOut(BaseModel):
    id: uuid.UUID
    name: str
    market: Literal["KR", "JP"]
    format: Literal["all", "short", "long"]
    category: str | None
    min_views: int
    max_growth_pct: float
    keywords: list[str]
    cc_only: bool
    include_broadcast: bool
    selected: bool
    updated_at: datetime


class ProfileListOut(BaseModel):
    items: list[ProfileOut]


class ProfileUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: Literal["KR", "JP"]
    format: Literal["all", "short", "long"]
    category: Annotated[str | None, BeforeValidator(_raw_text)]
    min_views: Annotated[int, Field(ge=0, le=2_000_000_000)]
    max_growth_pct: Annotated[Decimal, Field(ge=0, le=1000, decimal_places=2)]
    keywords: Annotated[list[Keyword], Field(max_length=MAX_LIST_LEN)]
    cc_only: bool
    include_broadcast: bool
    updated_at: Annotated[AwareDatetime, BeforeValidator(_require_str)]

    @field_validator("category")
    @classmethod
    def _category(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if v in ("", CATEGORY_ALL):
            return None
        if len(v) > MAX_CATEGORY_LEN:
            raise ValueError("40자 이하여야 합니다")
        return v

    @field_validator("keywords")
    @classmethod
    def _keywords(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for kw in v:
            key = kw.casefold()
            if key not in seen:
                seen.add(key)
                out.append(kw)
        if len(out) > MAX_KEYWORDS:
            raise ValueError("키워드는 최대 5개입니다")
        return out


class SelectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_ids: Annotated[list[uuid.UUID], Field(max_length=MAX_LIST_LEN)]

    @field_validator("selected_ids")
    @classmethod
    def _dedupe(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        out = list(dict.fromkeys(v))
        if len(out) > MAX_SELECTED:
            raise ValueError("최대 3개까지 선택할 수 있습니다")
        return out


class SelectionOut(BaseModel):
    selected_ids: list[uuid.UUID]


async def _send(request: Request, method: str, path: str, **kwargs: Any) -> httpx.Response:
    state = request.app.state
    try:
        resp = await state.http.request(
            method,
            rest_url(state.settings, path),
            headers={**service_headers(state.settings), **kwargs.pop("headers", {})},
            **kwargs,
        )
    except httpx.HTTPError as exc:
        logger.warning("데이터 저장소 연결 실패: %s %s", method, path)
        raise db_error() from exc
    return resp


def _json_list(resp: httpx.Response, method: str, path: str) -> list:
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: %s %s", resp.status_code, method, path)
        raise db_error()
    try:
        rows = resp.json()
    except ValueError as exc:
        raise db_error() from exc
    if not isinstance(rows, list):
        raise db_error()
    return rows


@router.get("", response_model=ProfileListOut)
async def list_profiles(
    request: Request, user: CurrentUser = Depends(get_current_user)
) -> ProfileListOut:
    params = {
        "select": COLUMNS,
        "workspace_id": f"eq.{user.workspace_id}",
        "order": "name.asc,id.asc",
    }
    resp = await _send(request, "GET", "profiles", params=params)
    rows = _json_list(resp, "GET", "profiles")
    return ProfileListOut(items=[ProfileOut.model_validate(r) for r in rows])


# /selection은 /{profile_id}보다 먼저 등록한다.
@router.put("/selection", response_model=SelectionOut)
async def put_selection(
    body: SelectionIn, request: Request, user: CurrentUser = Depends(get_current_user)
) -> SelectionOut:
    path = "rpc/set_profile_selection"
    payload = {"p_workspace": str(user.workspace_id), "p_ids": [str(i) for i in body.selected_ids]}
    resp = await _send(request, "POST", path, json=payload)
    if 400 <= resp.status_code < 500:
        try:
            code = resp.json().get("code")
        except ValueError, AttributeError:
            code = None
        if code in _RPC_ERRORS:
            raise ApiError(400, "VALIDATION", _RPC_ERRORS[code], "selected_ids")
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: POST %s", resp.status_code, path)
        raise db_error()
    try:
        return SelectionOut(selected_ids=resp.json())
    except ValueError as exc:
        raise db_error() from exc


@router.put("/{profile_id}", response_model=ProfileOut)
async def put_profile(
    profile_id: uuid.UUID,
    body: ProfileUpdateIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> ProfileOut:
    data = body.model_dump(exclude={"updated_at", "max_growth_pct"})
    data["max_growth_pct"] = format(body.max_growth_pct, "f")
    data["updated_at"] = datetime.now(UTC).isoformat()
    params = {
        "id": f"eq.{profile_id}",
        "workspace_id": f"eq.{user.workspace_id}",
        "updated_at": f"eq.{body.updated_at.isoformat()}",
        "select": COLUMNS,
    }
    resp = await _send(
        request,
        "PATCH",
        "profiles",
        params=params,
        json=data,
        headers={"Prefer": "return=representation"},
    )
    rows = _json_list(resp, "PATCH", "profiles")
    if rows:
        return ProfileOut.model_validate(rows[0])
    # 0행: 같은 워크스페이스에 있으면 updated_at 불일치(409), 없으면 404(타 워크스페이스 포함)
    check = await _send(
        request,
        "GET",
        "profiles",
        params={
            "select": "id",
            "id": f"eq.{profile_id}",
            "workspace_id": f"eq.{user.workspace_id}",
        },
    )
    if _json_list(check, "GET", "profiles"):
        raise conflict()
    raise not_found()
