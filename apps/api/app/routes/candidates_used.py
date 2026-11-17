"""A-08 사용 표시 토글. 근거: tasks/task-017.md#착수 결정.

used=true 재요청은 멱등(used_at 유지). 해제(false)는 used_at null, 다시 표시하면 새 시각.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, StrictBool

from app.auth.user import CurrentUser, get_current_user
from app.errors import db_error, not_found
from app.routes.profiles import _json_list, _send

router = APIRouter(prefix="/v1/candidates", tags=["candidates"])

TABLE = "candidates"
COLUMNS = "id,used,used_at"


class UsedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    used: StrictBool


class UsedOut(BaseModel):
    id: uuid.UUID
    used: bool
    used_at: datetime | None


def _out(rows: list) -> UsedOut:
    try:
        return UsedOut.model_validate(rows[0])
    except ValueError as exc:
        raise db_error() from exc


@router.patch("/{candidate_id}/used", response_model=UsedOut)
async def patch_used(
    candidate_id: uuid.UUID,
    body: UsedIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> UsedOut:
    params = {
        "id": f"eq.{candidate_id}",
        "workspace_id": f"eq.{user.workspace_id}",
        "select": COLUMNS,
    }
    if body.used:
        # 아직 미사용인 행만 갱신해 used_at을 처음 표시한 시각으로 고정한다
        params["used"] = "is.false"
        data: dict = {"used": True, "used_at": datetime.now(UTC).isoformat()}
    else:
        data = {"used": False, "used_at": None}
    resp = await _send(
        request,
        "PATCH",
        TABLE,
        params=params,
        json=data,
        headers={"Prefer": "return=representation"},
    )
    rows = _json_list(resp, "PATCH", TABLE)
    if rows:
        return _out(rows)
    if body.used:
        # 0행: 이미 true(200·현재값)인지, 없는 id·타 워크스페이스(404)인지 구분
        check = await _send(
            request,
            "GET",
            TABLE,
            params={
                "select": COLUMNS,
                "id": f"eq.{candidate_id}",
                "workspace_id": f"eq.{user.workspace_id}",
            },
        )
        rows = _json_list(check, "GET", TABLE)
        if rows:
            return _out(rows)
    raise not_found()
