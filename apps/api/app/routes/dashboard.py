"""A-02 대시보드 요약. 근거: tasks/task-011.md#구현 결정.

기간은 now 기준 rolling(24h·7d). 미연동 3칸(in_progress·reviewed·upload_pending)은 항상 null.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.auth.user import CurrentUser, get_current_user
from app.routes.candidates import VIEW, count_rows, parse_ts, profile_names_by_id, to_float
from app.routes.profiles import _json_list, _send

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])

PERIODS = {"24h": timedelta(hours=24), "7d": timedelta(days=7)}
RECENT_READY_LIMIT = 5


class StatsOut(BaseModel):
    collected: int
    in_progress: int | None = None
    reviewed: int | None = None
    upload_pending: int | None = None


class StealthOut(BaseModel):
    producible: int
    pending: int


class RecentReadyOut(BaseModel):
    id: uuid.UUID
    title: str
    profile_name: str | None
    growth_pct: float | None
    status_changed_at: datetime


class SummaryOut(BaseModel):
    stats: StatsOut
    stealth: StealthOut
    recent_ready: list[RecentReadyOut]
    updated_at: datetime


@router.get("/summary", response_model=SummaryOut)
async def get_summary(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    period: Literal["24h", "7d"] = "7d",
) -> SummaryOut:
    ws = user.workspace_id
    now = datetime.now(UTC)
    since = (now - PERIODS[period]).isoformat()
    ws_eq = f"eq.{ws}"

    async def fetch_recent() -> list:
        params = {
            "select": "id,title,growth_pct,status_changed_at,rep_profile_id",
            "workspace_id": ws_eq,
            "display_status": "eq.producible",
            "status_changed_at": f"gte.{since}",
            "order": "status_changed_at.desc,id.asc",
            "limit": str(RECENT_READY_LIMIT),
        }
        return _json_list(await _send(request, "GET", VIEW, params=params), "GET", VIEW)

    collected, producible, pending, recent, names = await asyncio.gather(
        count_rows(
            request,
            "candidates",
            {"select": "id", "workspace_id": ws_eq, "created_at": f"gte.{since}"},
        ),
        count_rows(
            request,
            VIEW,
            {"select": "id", "workspace_id": ws_eq, "display_status": "eq.producible"},
        ),
        count_rows(
            request, VIEW, {"select": "id", "workspace_id": ws_eq, "display_status": "eq.pending"}
        ),
        fetch_recent(),
        profile_names_by_id(request, ws),
    )
    return SummaryOut(
        stats=StatsOut(collected=collected),
        stealth=StealthOut(producible=producible, pending=pending),
        recent_ready=[
            RecentReadyOut(
                id=r["id"],
                title=r["title"],
                profile_name=names.get(r["rep_profile_id"]) if r["rep_profile_id"] else None,
                growth_pct=to_float(r["growth_pct"]),
                status_changed_at=parse_ts(r["status_changed_at"]),
            )
            for r in recent
        ],
        updated_at=now,
    )
