"""렌더 요청·재시도 A-15·A-16. 근거: docs/04_API.md#A-15·#A-16, tasks/task-023.md(E1·E3·E5·E8).

판정·전이는 RPC(request_render_run·retry_render_run) 한 트랜잭션이 정본이다(job 행 for update).
"""

import logging
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict

from app.auth.user import CurrentUser, get_current_user
from app.errors import ApiError, db_error
from app.production import runs
from app.routes.verify_runs import _KEY_RE

logger = logging.getLogger("nomadroom.production_render")

router = APIRouter(prefix="/v1/production-jobs", tags=["production-render"])


class RenderRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: uuid.UUID
    lang: Literal["ko", "ja"]


class RenderRunOut(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    revision_id: uuid.UUID
    lang: str
    status: str
    attempt: int
    retry_of: uuid.UUID | None
    preset_version: str


class RenderRunEnvelope(BaseModel):
    render_run: RenderRunOut


def _envelope(body: object) -> tuple[RenderRunEnvelope, bool]:
    if not isinstance(body, dict):
        raise db_error()
    return RenderRunEnvelope(render_run=RenderRunOut.model_validate(body)), bool(
        body.get("created")
    )


@router.post("/{job_id}/render-runs", response_model=RenderRunEnvelope, status_code=202)
async def request_render(
    job_id: uuid.UUID,
    body: RenderRunIn,
    request: Request,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    user: CurrentUser = Depends(get_current_user),
) -> RenderRunEnvelope:
    if idempotency_key is None or not _KEY_RE.fullmatch(idempotency_key):
        raise ApiError(400, "VALIDATION", "Idempotency-Key 헤더가 필요합니다.", "Idempotency-Key")
    if body.lang == "ja":
        # E8: 일본어 렌더는 task-049 전까지 준비 중
        raise ApiError(400, "VALIDATION", "준비 중인 기능입니다.", "lang")
    await runs.expire_offline(request, user.workspace_id)  # E3
    out, created = _envelope(
        await runs.rpc(
            request,
            "request_render_run",
            {
                "p_workspace": str(user.workspace_id),
                "p_job": str(job_id),
                "p_user": str(user.user_id),
                "p_revision": str(body.revision_id),
                "p_lang": body.lang,
                "p_key": idempotency_key,
            },
            "revision_id",
        )
    )
    if not created:
        response.status_code = 200
    else:
        logger.info("렌더 요청: job=%s run=%s", job_id, out.render_run.id)
    return out


@router.post(
    "/{job_id}/render-runs/{run_id}/retry", response_model=RenderRunEnvelope, status_code=202
)
async def retry_render(
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> RenderRunEnvelope:
    await runs.expire_offline(request, user.workspace_id)  # E3
    out, _ = _envelope(
        await runs.rpc(
            request,
            "retry_render_run",
            {
                "p_workspace": str(user.workspace_id),
                "p_job": str(job_id),
                "p_user": str(user.user_id),
                "p_run": str(run_id),
            },
        )
    )
    logger.info(
        "렌더 재시도: job=%s run=%s attempt=%s", job_id, out.render_run.id, out.render_run.attempt
    )
    return out
