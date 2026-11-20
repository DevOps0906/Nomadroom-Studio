"""AI 영상 생성 A-22 `/v1/production-jobs/{id}/generation-runs`. 근거: docs/04_API.md#A-22,
tasks/task-054.md#착수-결정 G0~G9, supabase/migrations/20261120000026_generation_runs.sql.

- 기본 꺼짐: VIDEOGEN_ENABLED≠1 또는 키 없음이면 견적·확인·진행 확인 503(기록 없음, G0).
- 견적(구성원) → 확인(owner만, 제출 전 계상) → 플랫폼 제출 → refresh로 진행 확인
  (GET 목록은 부작용 없음).
- 완료 처리는 running→finalizing CAS 1건만, 결과는 서버가 검증·복사해 source_upload로
  저장(G1·G5·G6).
- 검수는 3항목이 모두 true여야 reviewed=true(G4). 프롬프트·URL·키는 로그에 넣지 않는다.
"""

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StringConstraints

from app.auth.user import CurrentUser, get_current_user
from app.errors import ApiError, db_error
from app.production import ai_draft, runs, storage, videogen
from app.production.shopping import no_control
from app.production.videogen import download
from app.routes.production_jobs import _get_asset, _get_job, _rows
from app.routes.profiles import _send
from app.routes.verify_runs import _KEY_RE

logger = logging.getLogger("nomadroom.production_generation")

router = APIRouter(prefix="/v1/production-jobs", tags=["production-jobs"])

MAX_PROMPT_CHARS = 500  # 가정(04_API A-22)
MAX_DURATION_SEC = 15  # 가정(G3)
MAX_INPUT_BYTES = 10 * 1024 * 1024  # 입력 사진 상한(가정)
MAX_COST_FACTOR = 10  # 보고 비용이 견적의 10배를 넘으면 믿지 않는다(리뷰 반영)
INT4_MAX = 2_147_483_647
_IMAGE_MAGIC = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}
RUN_COLUMNS = (
    "id,job_id,source_asset_id,result_asset_id,cut_ref,prompt,platform,model,duration_sec,"
    "est_cost_krw,actual_cost_krw,billable,status,error_code,request_id,created_at,"
    "confirmed_at,finished_at"
)


class BudgetExceeded(Exception):
    def __init__(self, remaining: int) -> None:
        super().__init__("budget_exceeded")
        self.remaining = remaining


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuoteIn(_In):
    source_asset_id: uuid.UUID
    prompt: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_PROMPT_CHARS),
        BeforeValidator(no_control),
    ]
    duration_sec: Annotated[int, Field(ge=1, le=MAX_DURATION_SEC, strict=True)]
    cut_ref: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=50),
            BeforeValidator(no_control),
        ]
        | None
    ) = None


class ReviewIn(_In):
    physics: StrictBool  # 물리 오류 없음
    angle: StrictBool  # 불가능한 앵글 없음
    compare: StrictBool  # 실제 사진과 대조함


class GenerationRunOut(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    source_asset_id: uuid.UUID | None
    result_asset_id: uuid.UUID | None
    cut_ref: str | None
    prompt: str
    platform: str
    model: str
    duration_sec: int
    est_cost_krw: int
    actual_cost_krw: int | None
    billable: bool
    status: str
    error_code: str | None
    request_id: str | None
    created_at: datetime
    confirmed_at: datetime | None
    finished_at: datetime | None


class BudgetOut(BaseModel):
    monthly_left_krw: int
    job_left_krw: int


class RunEnvelope(BaseModel):
    run: GenerationRunOut
    budget: BudgetOut | None = None
    replay: bool = False  # 같은 키·같은 run 재요청(200)이면 true


class RunListOut(BaseModel):
    items: list[GenerationRunOut]


class ReviewOut(BaseModel):
    run: GenerationRunOut
    reviewed: bool
    review_checks: dict[str, Any]


def _budget_response(exc: BudgetExceeded) -> JSONResponse:
    return JSONResponse(
        {
            "code": "CONFLICT",
            "message": "AI 영상 생성 예산(월 예산·작업당 상한)을 넘었습니다.",
            "field": "budget_exceeded",
            "remaining_krw": exc.remaining,
        },
        status_code=409,
    )


def _remaining(resp: Any) -> int:
    try:
        detail = resp.json().get("details")
        return max(0, int(detail))
    except ValueError, TypeError, AttributeError:
        return 0


async def _rpc(request: Request, name: str, payload: dict, field: str | None = None) -> Any:
    """000026 RPC. NR019(예산)·NR020(owner)는 여기서, 나머지 NR 코드는 runs._map."""
    path = f"rpc/{name}"
    resp = await _send(request, "POST", path, json=payload)
    if 400 <= resp.status_code < 500:
        code, message = runs._error_body(resp)
        if code == "NR019":
            raise BudgetExceeded(_remaining(resp))
        if code == "NR020":
            raise ApiError(
                403, "FORBIDDEN", "AI 영상 생성 확인(과금)은 워크스페이스 소유자만 할 수 있습니다."
            )
        err = runs._map(code, message, field)
        if err is not None:
            raise err
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: POST %s", resp.status_code, path)
        raise db_error()
    if not resp.content:
        return None
    try:
        return resp.json()
    except ValueError as exc:
        raise db_error() from exc


def _envelope(result: Any, replay: bool = False) -> RunEnvelope:
    if not isinstance(result, dict) or not isinstance(result.get("run"), dict):
        raise db_error()
    budget = result.get("budget")
    return RunEnvelope(
        run=GenerationRunOut.model_validate(result["run"]),
        budget=BudgetOut.model_validate(budget) if isinstance(budget, dict) else None,
        replay=replay or bool(result.get("replay")),
    )


def _run(result: Any) -> GenerationRunOut:
    if not isinstance(result, dict):
        raise db_error()
    return GenerationRunOut.model_validate(result)


def _key(idempotency_key: str | None) -> str:
    if idempotency_key is None or not _KEY_RE.fullmatch(idempotency_key):
        raise ApiError(400, "VALIDATION", "Idempotency-Key 헤더가 필요합니다.", "Idempotency-Key")
    return idempotency_key


async def _source_image(
    request: Request, ws: uuid.UUID, job_id: uuid.UUID, asset_id: Any
) -> tuple[bytes, str]:
    """입력 사진(이 작업 소유 image)을 서비스 키로 읽는다(서명 URL을 만들지 않음, G6)."""
    if not isinstance(asset_id, str):
        raise ApiError(409, "CONFLICT", "입력 사진을 찾을 수 없습니다.", "source_asset_id")
    asset = await _get_asset(
        request, ws, job_id, uuid.UUID(asset_id), "kind,status,storage_path,mime"
    )
    mime = asset.get("mime")
    if asset.get("kind") != "image" or asset.get("status") != "ready" or mime not in _IMAGE_MAGIC:
        raise ApiError(409, "CONFLICT", "입력 사진을 쓸 수 없습니다.", "source_asset_id")
    state = request.app.state
    data = await ai_draft.download(
        state.http, state.settings, asset["storage_path"], MAX_INPUT_BYTES
    )
    if not data.startswith(_IMAGE_MAGIC[mime]):
        raise ApiError(409, "CONFLICT", "입력 사진을 쓸 수 없습니다.", "source_asset_id")
    return data, mime


async def _mark(
    request: Request, ws: uuid.UUID, run_id: uuid.UUID, outcome: str, rid: str | None, err: str
) -> None:
    """제출 결과 기록. 실패는 로그(예외 이름만)로 남기고 원래 응답을 살린다."""
    try:
        await _rpc(
            request,
            "mark_generation_submitted",
            {
                "p_workspace": str(ws),
                "p_run": str(run_id),
                "p_outcome": outcome,
                "p_request_id": rid,
                "p_error": err,
            },
        )
    except Exception as exc:  # noqa: BLE001 - 기록 실패가 원래 오류를 가리면 안 된다
        logger.warning("AI 생성 제출 기록 실패: run=%s err=%s", run_id, type(exc).__name__)


@router.post("/{job_id}/generation-runs", response_model=RunEnvelope, status_code=201)
async def quote_generation(
    job_id: uuid.UUID,
    body: QuoteIn,
    request: Request,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    user: CurrentUser = Depends(get_current_user),
    adapter: videogen.VideoGenAdapter = Depends(videogen.get_adapter),
) -> Any:
    key = _key(idempotency_key)
    settings = request.app.state.settings
    est = videogen.krw(adapter.estimate_usd(body.duration_sec), settings.videogen_krw_per_usd)
    try:
        result = await _rpc(
            request,
            "quote_generation_run",
            {
                "p_workspace": str(user.workspace_id),
                "p_job": str(job_id),
                "p_user": str(user.user_id),
                "p_key": key,
                "p_source_asset": str(body.source_asset_id),
                "p_prompt": body.prompt,
                "p_duration": body.duration_sec,
                "p_cut_ref": body.cut_ref,
                "p_platform": adapter.platform,
                "p_model": adapter.model,
                "p_est_cost": est,
            },
            "source_asset_id",
        )
    except BudgetExceeded as exc:
        return _budget_response(exc)
    out = _envelope(result)
    if out.replay:
        response.status_code = 200
    return out


@router.post(
    "/{job_id}/generation-runs/{run_id}/confirm", response_model=RunEnvelope, status_code=202
)
async def confirm_generation(
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(get_current_user),
    adapter: videogen.VideoGenAdapter = Depends(videogen.get_adapter),
) -> Any:
    ws = user.workspace_id
    try:
        result = await _rpc(
            request,
            "confirm_generation_run",
            {
                "p_workspace": str(ws),
                "p_job": str(job_id),
                "p_run": str(run_id),
                "p_user": str(user.user_id),
            },
        )
    except BudgetExceeded as exc:
        return _budget_response(exc)
    out = _envelope(result)
    if out.replay:  # G2: 재확인은 현재 run(재제출·재계상 없음)
        response.status_code = 200
        return out
    run = result["run"]
    try:
        image, mime = await _source_image(request, ws, job_id, run.get("source_asset_id"))
    except Exception:
        await _mark(request, ws, run_id, "rejected", None, "input_unavailable")  # 미제출 = 비계상
        raise
    try:
        request_id = await adapter.submit(image, mime, run["prompt"], run["duration_sec"])
    except videogen.Rejected as exc:
        await _mark(request, ws, run_id, "rejected", None, exc.code)
        logger.warning("AI 생성 제출 거부: run=%s code=%s", run_id, exc.code)
        raise videogen.upstream_failed() from None
    except Exception as exc:  # noqa: BLE001 - 응답 불명(타임아웃 등)은 unknown·계상 유지
        code = exc.code if isinstance(exc, videogen.Unknown) else "unexpected"
        await _mark(request, ws, run_id, "unknown", None, code)
        logger.warning("AI 생성 제출 응답 불명: run=%s code=%s", run_id, code)
        raise videogen.upstream_failed() from None
    payload = {
        "p_workspace": str(ws),
        "p_run": str(run_id),
        "p_outcome": "running",
        "p_request_id": request_id,
        "p_error": None,
    }
    try:
        marked = await _rpc(request, "mark_generation_submitted", payload)
    except Exception:  # noqa: BLE001 - 리뷰 반영 2: 1회 재시도
        try:
            marked = await _rpc(request, "mark_generation_submitted", payload)
        except Exception:
            # 이후 재확인·refresh 때 5분 규칙으로 unknown(계상 유지). 요청 ID는 해시만 남긴다
            digest = hashlib.sha256(request_id.encode()).hexdigest()[:16]
            logger.error("AI 생성 제출 기록 실패: run=%s request_sha256=%s", run_id, digest)
            raise
    logger.info("AI 생성 제출: run=%s job=%s", run_id, job_id)
    return RunEnvelope(run=_run(marked), budget=out.budget)


@router.get("/{job_id}/generation-runs", response_model=RunListOut)
async def list_generation_runs(
    job_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user)
) -> RunListOut:
    """부작용 없음(G5): 플랫폼 호출·상태 변경을 하지 않는다."""
    ws = user.workspace_id
    await _get_job(request, ws, job_id, "id")
    rows = await _rows(
        request,
        "GET",
        "generation_runs",
        params={
            "select": RUN_COLUMNS,
            "job_id": f"eq.{job_id}",
            "workspace_id": f"eq.{ws}",
            "order": "created_at.desc",
            "limit": "100",
        },
    )
    return RunListOut(items=[GenerationRunOut.model_validate(r) for r in rows])


async def _finish(
    request: Request, ws: uuid.UUID, run_id: uuid.UUID, token: Any, **values: Any
) -> Any:
    """완료 기록. 선점 토큰이 다르면(회수 뒤 다른 요청이 선점) RPC가 거부한다."""
    payload = {
        "p_workspace": str(ws),
        "p_run": str(run_id),
        "p_token": token,
        "p_status": "failed",
        "p_asset": None,
        "p_path": None,
        "p_size": None,
        "p_actual_cost": None,
        "p_error": None,
    }
    payload.update({f"p_{k}": v for k, v in values.items()})
    return await _rpc(request, "finish_generation_run", payload)


def _actual_cost(cost_usd: Any, run: GenerationRunOut, krw_per_usd: int) -> int | None:
    """플랫폼 보고 비용(원). 견적×10 초과·int4 초과는 믿지 않고 None(견적으로 계상)."""
    if cost_usd is None:
        return None
    value = videogen.krw(cost_usd, krw_per_usd)
    if value > run.est_cost_krw * MAX_COST_FACTOR or value > INT4_MAX:
        logger.warning("AI 생성 보고 비용 비정상(견적으로 계상): run=%s", run.id)
        return None
    return value


async def _saved(
    request: Request, ws: uuid.UUID, job_id: uuid.UUID, run_id: uuid.UUID, asset_id: uuid.UUID
) -> bool:
    """run이 done이고 result_asset_id가 이 자산인지. 확인할 수 없으면 True(객체를 지우지 않음)."""
    try:
        rows = await _rows(
            request,
            "GET",
            "generation_runs",
            params={
                "select": "status,result_asset_id",
                "id": f"eq.{run_id}",
                "job_id": f"eq.{job_id}",
                "workspace_id": f"eq.{ws}",
            },
        )
    except Exception as exc:  # noqa: BLE001 - 확인 실패 시 지우지 않는 쪽(고아 객체)을 택한다
        logger.warning("AI 생성 완료 재조회 실패: run=%s err=%s", run_id, type(exc).__name__)
        return True
    return (
        bool(rows)
        and rows[0].get("status") == "done"
        and (rows[0].get("result_asset_id") == str(asset_id))
    )


@router.post("/{job_id}/generation-runs/{run_id}/refresh", response_model=RunEnvelope)
async def refresh_generation(
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    adapter: videogen.VideoGenAdapter = Depends(videogen.get_adapter),
) -> RunEnvelope:
    ws = user.workspace_id
    ids = {"p_workspace": str(ws), "p_job": str(job_id), "p_run": str(run_id)}
    run = _run(await _rpc(request, "begin_generation_refresh", ids))
    if run.status != "running" or run.request_id is None:
        return RunEnvelope(run=run)
    try:
        polled = await adapter.poll(run.request_id)
    except Exception as exc:  # noqa: BLE001 - 진행 확인 실패는 상태를 바꾸지 않는다
        code = exc.code if isinstance(exc, videogen.Unknown) else "unexpected"
        logger.warning("AI 생성 진행 확인 실패: run=%s code=%s", run_id, code)
        raise videogen.upstream_failed() from None
    if polled.status == "pending":
        return RunEnvelope(run=run)
    claimed = await _rpc(
        request, "claim_generation_finalize", {"p_workspace": str(ws), "p_run": str(run_id)}
    )
    if claimed is None:  # 다른 요청이 완료 처리 중(G5: 1건만)
        return RunEnvelope(run=_run(await _rpc(request, "begin_generation_refresh", ids)))
    if not isinstance(claimed, dict):
        raise db_error()
    token = claimed.get("finalize_token")
    settings = request.app.state.settings
    actual = _actual_cost(polled.cost_usd, run, settings.videogen_krw_per_usd)
    if polled.status == "failed" or polled.video_url is None:
        done = await _finish(
            request, ws, run_id, token, actual_cost=actual, error=polled.error or "platform_failed"
        )
        return RunEnvelope(run=_run(done.get("run") if isinstance(done, dict) else None))
    try:
        data = await download.fetch_video(
            request.app.state.http,
            polled.video_url,
            adapter.result_hosts,
            timeout=settings.videogen_timeout_sec,
        )
    except download.DownloadRejected as exc:
        logger.warning("AI 생성 결과 다운로드 거부: run=%s code=%s", run_id, exc.code)
        done = await _finish(
            request, ws, run_id, token, actual_cost=actual, error="download_rejected"
        )
        return RunEnvelope(run=_run(done.get("run") if isinstance(done, dict) else None))
    asset_id = uuid.uuid4()
    path = storage.object_path(ws, job_id, asset_id, "mp4")
    # 업로드 실패는 finalizing으로 남고 10분 뒤 회수된다(G5)
    await storage.upload_object(
        request.app.state.http,
        settings,
        path,
        data,
        "video/mp4",
        timeout=settings.videogen_timeout_sec,
    )
    try:
        done = await _finish(
            request,
            ws,
            run_id,
            token,
            status="done",
            asset=str(asset_id),
            path=path,
            size=len(data),
            actual_cost=actual,
        )
    except Exception:
        # 리뷰 반영 3: 응답만 잃고 저장은 됐을 수 있다 → 재조회해 done·같은 자산이면 객체 유지
        if not await _saved(request, ws, job_id, run_id, asset_id):
            await runs.delete_objects(request, [path], "generation_finish")
        raise
    if not isinstance(done, dict):
        raise db_error()
    if done.get("rejected"):  # 000023 트리거(상태·상한) 거부: 객체 정리, 비용은 계상 유지(G1)
        await runs.delete_objects(request, [path], "generation_rejected")
    logger.info("AI 생성 완료 처리: run=%s rejected=%s", run_id, bool(done.get("rejected")))
    return RunEnvelope(run=_run(done.get("run")))


@router.post("/{job_id}/generation-runs/{run_id}/review", response_model=ReviewOut)
async def review_generation(
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    body: ReviewIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> ReviewOut:
    result = await _rpc(
        request,
        "review_generation_run",
        {
            "p_workspace": str(user.workspace_id),
            "p_job": str(job_id),
            "p_run": str(run_id),
            "p_user": str(user.user_id),
            "p_checks": body.model_dump(),
        },
    )
    if not isinstance(result, dict) or not isinstance(result.get("review_checks"), dict):
        raise db_error()
    return ReviewOut(
        run=_run(result.get("run")),
        reviewed=bool(result.get("reviewed")),
        review_checks=result["review_checks"],
    )
