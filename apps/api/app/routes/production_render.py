"""렌더 요청·재시도 A-15·A-16. 근거: docs/04_API.md#A-15·#A-16, tasks/task-023.md(E1·E3·E5·E8).

판정·전이는 RPC(request_render_run·retry_render_run) 한 트랜잭션이 정본이다(job 행 for update).
ja(task-050, 000028): job inspect·done·현재 승인 ja(파생 원본 = 현재 승인 ko)만, job 상태 불변.
ja run 재시도는 RPC가 409(A-15로 다시 요청).
"""

import logging
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict

from app.auth.user import CurrentUser, get_current_user
from app.errors import ApiError, db_error, not_found
from app.production import runs
from app.routes.profiles import _json_list, _send
from app.routes.verify_runs import _KEY_RE
from app.routes.worker_production import shopping_ref_assets

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


RENDER_FORMATS = ("category", "variety", "shopping")  # task-036 예능형 · task-045 쇼핑


async def _require_render_format(request: Request, user: CurrentUser, job_id: uuid.UUID) -> str:
    """렌더러가 없는 형식(shopping 등)은 렌더 요청·재시도 409. 없는 작업은 404."""
    jobs = _json_list(
        await _send(
            request,
            "GET",
            "production_jobs",
            params={
                "select": "id,format",
                "id": f"eq.{job_id}",
                "workspace_id": f"eq.{user.workspace_id}",
            },
        ),
        "GET",
        "production_jobs",
    )
    if not jobs:
        raise not_found()
    if jobs[0]["format"] not in RENDER_FORMATS:
        raise ApiError(409, "CONFLICT", "이 형식의 렌더는 아직 준비 중입니다.", "format")
    return jobs[0]["format"]


async def _require_shopping_assets(
    request: Request, user: CurrentUser, job_id: uuid.UUID, revision_id: uuid.UUID
) -> None:
    """task-045(044 이월): 쇼핑 렌더 요청 때 리비전이 참조하는 자산이 이 작업 소유·ready이고
    컷 원본마다 파생 source가 있는지 다시 본다(fail-closed, 아니면 409 field assets).
    리비전이 없거나 다른 작업이면 여기서는 통과시키고 RPC가 400으로 거부한다."""
    revs = _json_list(
        await _send(
            request,
            "GET",
            "edit_revisions",
            params={
                "select": "spec",
                "id": f"eq.{revision_id}",
                "job_id": f"eq.{job_id}",
                "workspace_id": f"eq.{user.workspace_id}",
            },
        ),
        "GET",
        "edit_revisions",
    )
    if not revs:
        return
    _, ok = await shopping_ref_assets(request, user.workspace_id, job_id, revs[0].get("spec"))
    if not ok:
        msg = "편집안이 쓰는 자산이 없거나 준비되지 않았습니다."
        raise ApiError(409, "CONFLICT", msg, "assets")


async def _key_used(request: Request, user: CurrentUser, key: str) -> bool:
    rows = _json_list(
        await _send(
            request,
            "GET",
            "render_runs",
            params={
                "select": "id",
                "workspace_id": f"eq.{user.workspace_id}",
                "idempotency_key": f"eq.{key}",
            },
        ),
        "GET",
        "render_runs",
    )
    return bool(rows)


async def _run_revision(
    request: Request, user: CurrentUser, job_id: uuid.UUID, run_id: uuid.UUID
) -> uuid.UUID | None:
    """재시도 대상 run의 리비전(없으면 None → RPC가 404·409로 판정)."""
    rows = _json_list(
        await _send(
            request,
            "GET",
            "render_runs",
            params={
                "select": "revision_id",
                "id": f"eq.{run_id}",
                "job_id": f"eq.{job_id}",
                "workspace_id": f"eq.{user.workspace_id}",
            },
        ),
        "GET",
        "render_runs",
    )
    return uuid.UUID(str(rows[0]["revision_id"])) if rows else None


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
    fmt = await _require_render_format(request, user, job_id)  # task-035 V2·task-036
    if body.lang == "ja" and fmt == "variety":
        # task-050 K1: 예능형 일본어판 렌더는 task-051 전까지 준비 중
        raise ApiError(409, "CONFLICT", "이 형식의 일본어판 렌더는 아직 준비 중입니다.", "lang")
    if fmt == "shopping" and not await _key_used(request, user, idempotency_key):
        # 리뷰 반영 3: 같은 키 재전송은 RPC가 기존 run을 돌려주게 두고, 새 run 경로만 재확인
        await _require_shopping_assets(request, user, job_id, body.revision_id)
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
    fmt = await _require_render_format(request, user, job_id)  # task-035 V2·task-036
    if fmt == "shopping":  # 리뷰 반영 3: 재시도도 그 run 리비전의 참조 자산을 다시 본다
        revision = await _run_revision(request, user, job_id, run_id)
        if revision is not None:
            await _require_shopping_assets(request, user, job_id, revision)
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
