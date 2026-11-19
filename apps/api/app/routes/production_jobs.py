"""제작 작업 API A-09~A-13·A-17·A-18. 근거: docs/04_API.md#제작-api, tasks/task-022.md(D1~D9).

- 웹·API는 작업 ID·자산 ID만 주고받는다. 경로는 서버가 만든다(production/storage.py).
- 모든 조회에 workspace_id 조건, 자산은 id·job_id·workspace_id 세 조건(D9). 타 워크스페이스 404.
- 서명 URL·토큰은 로그에 쓰지 않는다(응답에만).
"""

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from app.auth.user import CurrentUser, get_current_user
from app.errors import ApiError, db_error, not_found
from app.jobs.state import OFFLINE_AFTER
from app.production import storage
from app.production.runs import expire_offline
from app.production.spec import TOL, validate_spec
from app.routes.collect_jobs import _worker_last_seen
from app.routes.profiles import _json_list, _send
from app.routes.verify_runs import _KEY_RE

logger = logging.getLogger("nomadroom.production_jobs")

router = APIRouter(prefix="/v1/production-jobs", tags=["production-jobs"])

JOB_COLUMNS = (
    "id,workspace_id,title,format,status,failed_stage,error_code,transcribe_state,"
    "transcribe_error,transcribe_updated_at,candidate_id,source_kind,source_url,"
    "rights_confirmed,rights_confirmed_by,rights_confirmed_at,license_cc,credit,"
    "source_start_sec,segment_len_sec,lang,preset_version,source_meta,current_revision_id,"
    "ai_draft_count,retry_count,updated_at,requested_by,created_at,completed_at"
)
LIST_COLUMNS = "id,title,format,status,failed_stage,error_code,candidate_id,updated_at,completed_at"
ASSET_COLUMNS = "id,kind,status,size_bytes,duration_sec"
RUN_COLUMNS = "id,status,progress_pct,progress_stage,error_stage,error_code,attempt,claimed_by"
REVISION_COLUMNS = "id,rev_no,spec,origin,validation,approved_at"
IDEMPOTENCY_CONSTRAINT = "production_jobs_workspace_id_idempotency_key_key"
READY_SOURCE_INDEX = "production_assets_one_ready_source_uidx"

# 형식별 출력 프리셋(서버가 정함). variety 값은 task-035에서 연다.
PRESET_VERSION = {"category": "category-1080-v1"}
MAX_PREPARE_RETRY = 3  # 02_ARCHITECTURE.md#3-3과 같은 값(가정)
MAX_SOURCE_START_SEC = 86_400  # 원본 시작점 상한 24시간(가정)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

# 업로드 허용 mime → 확장자(05_DATA_MODEL.md production_assets: 영상·음성 허용 목록)
UPLOAD_MIME = {
    "source_upload": {
        "video/mp4": "mp4",
        "video/quicktime": "mov",
        "video/webm": "webm",
        "video/x-matroska": "mkv",
    },
    "hook_audio": {
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
        "audio/x-m4a": "m4a",
    },
}

# save/approve RPC SQLSTATE(20261119000016_production_api.sql)
_RPC_NOT_FOUND = "NR009"
_RPC_STATE = "NR010"
_RPC_STALE = "NR011"


# --- 오류 ----------------------------------------------------------------------


def _state_conflict(status: str | None) -> ApiError:
    return ApiError(409, "CONFLICT", f"현재 상태({status})에서는 할 수 없습니다.")


def _stale(field: str) -> ApiError:
    return ApiError(
        409, "CONFLICT", "다른 곳에서 먼저 수정되었습니다. 다시 불러온 뒤 시도하세요.", field
    )


def _not_ready_yet(field: str) -> ApiError:
    return ApiError(400, "VALIDATION", "준비 중인 기능입니다.", field)


def _validation_response(message: str, validation: dict) -> JSONResponse:
    """편집안 오류 목록을 담은 400(코드·경로·문구만, 입력 값 없음)."""
    return JSONResponse(
        {
            "code": "VALIDATION",
            "message": message,
            "field": "spec",
            "errors": validation["errors"],
            "warnings": validation["warnings"],
        },
        status_code=400,
    )


# --- 입출력 모델 ---------------------------------------------------------------


def _no_control(v: Any) -> Any:
    if isinstance(v, str) and _CONTROL_CHARS.search(v):
        raise ValueError("제어 문자는 사용할 수 없습니다")
    return v


Title = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    BeforeValidator(_no_control),
]
Credit = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=200), BeforeValidator(_no_control)
]
StartSec = Annotated[float, Field(ge=0, le=MAX_SOURCE_START_SEC, allow_inf_nan=False)]
SegmentSec = Annotated[float, Field(gt=0, le=180, allow_inf_nan=False)]


class JobCreateIn(BaseModel):
    # rights_confirmed_by·at 등 서버 칸은 extra=forbid로 거부(D7)
    model_config = ConfigDict(extra="forbid")

    title: Title
    format: Literal["category", "variety", "shopping"] = "category"
    candidate_id: uuid.UUID | None = None
    source_kind: Literal["upload", "url"]
    source_url: str | None = None
    rights_confirmed: bool
    license_cc: bool | None = None
    credit: Credit | None = None
    source_start_sec: StartSec
    segment_len_sec: SegmentSec


class JobPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: Literal["upload", "url"] | None = None
    source_url: str | None = None
    rights_confirmed: bool | None = None
    license_cc: bool | None = None
    credit: Credit | None = None
    source_start_sec: StartSec | None = None
    segment_len_sec: SegmentSec | None = None


_PATCH_NOT_NULL = ("source_kind", "rights_confirmed", "source_start_sec", "segment_len_sec")


class JobOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str
    format: str
    status: str
    failed_stage: str | None
    error_code: str | None
    transcribe_state: str | None
    transcribe_error: str | None
    transcribe_updated_at: datetime | None
    candidate_id: uuid.UUID | None
    source_kind: str
    source_url: str | None
    rights_confirmed: bool
    rights_confirmed_by: uuid.UUID | None
    rights_confirmed_at: datetime | None
    license_cc: bool | None
    credit: str | None
    source_start_sec: float
    segment_len_sec: float
    lang: str
    preset_version: str
    source_meta: dict[str, Any] | None
    current_revision_id: uuid.UUID | None
    ai_draft_count: int
    retry_count: int
    updated_at: datetime
    requested_by: uuid.UUID | None
    created_at: datetime
    completed_at: datetime | None


class JobEnvelope(BaseModel):
    job: JobOut


class JobListItem(BaseModel):
    id: uuid.UUID
    title: str
    format: str
    status: str
    failed_stage: str | None
    error_code: str | None
    candidate_id: uuid.UUID | None
    updated_at: datetime
    completed_at: datetime | None


class JobListOut(BaseModel):
    items: list[JobListItem]


class AssetOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    size_bytes: int | None
    duration_sec: float | None


class RevisionSummary(BaseModel):
    id: uuid.UUID
    rev_no: int
    approved_at: datetime | None
    validation: dict[str, Any]


class CurrentRevisionOut(BaseModel):
    ko: RevisionSummary | None
    ja: RevisionSummary | None = None


class RunOut(BaseModel):
    id: uuid.UUID
    status: str
    progress_pct: int
    progress_stage: str | None
    error_stage: str | None
    error_code: str | None
    attempt: int


class JobDetailOut(BaseModel):
    job: JobOut
    assets: list[AssetOut]
    current_revision: CurrentRevisionOut
    latest_run: RunOut | None
    worker_online: bool


class UploadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["source_upload", "hook_audio"]
    size_bytes: Annotated[int, Field(strict=True, ge=1, le=storage.MAX_UPLOAD_BYTES)]
    mime: Annotated[str, StringConstraints(max_length=100)]


class UploadAssetOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str


class UploadOut(BaseModel):
    asset: UploadAssetOut
    upload_url: str
    expires_at: datetime


class AssetEnvelope(BaseModel):
    asset: AssetOut


class RevisionOut(BaseModel):
    id: uuid.UUID
    rev_no: int
    spec: dict[str, Any]
    origin: str
    validation: dict[str, Any]
    approved_at: datetime | None


class RevisionEnvelope(BaseModel):
    revision: RevisionOut


class RevisionPutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: dict[str, Any]
    base_rev_no: Annotated[int, Field(strict=True, ge=1)]


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rev_no: Annotated[int, Field(strict=True, ge=1)]


class ApprovedRevisionOut(BaseModel):
    id: uuid.UUID
    rev_no: int
    approved_at: datetime
    approved_by: uuid.UUID | None


class ApprovedEnvelope(BaseModel):
    revision: ApprovedRevisionOut


class DownloadOut(BaseModel):
    url: str
    expires_at: datetime
    kind: str


# --- 저장소 헬퍼 ---------------------------------------------------------------


async def _rows(request: Request, method: str, table: str, **kwargs: Any) -> list:
    return _json_list(await _send(request, method, table, **kwargs), method, table)


async def _get_job(
    request: Request, ws: uuid.UUID, job_id: uuid.UUID, columns: str = JOB_COLUMNS
) -> dict:
    rows = await _rows(
        request,
        "GET",
        "production_jobs",
        params={"select": columns, "id": f"eq.{job_id}", "workspace_id": f"eq.{ws}"},
    )
    if not rows:
        raise not_found()
    return rows[0]


async def _get_asset(
    request: Request, ws: uuid.UUID, job_id: uuid.UUID, asset_id: uuid.UUID, columns: str
) -> dict:
    """D9: 자산은 항상 id·job_id·workspace_id 세 조건으로만 찾는다."""
    rows = await _rows(
        request,
        "GET",
        "production_assets",
        params={
            "select": columns,
            "id": f"eq.{asset_id}",
            "job_id": f"eq.{job_id}",
            "workspace_id": f"eq.{ws}",
        },
    )
    if not rows:
        raise not_found()
    return rows[0]


async def _patch_job(request: Request, params: dict[str, str], body: dict[str, Any]) -> list[dict]:
    return await _rows(
        request,
        "PATCH",
        "production_jobs",
        params={**params, "select": JOB_COLUMNS},
        json=body,
        headers={"Prefer": "return=representation"},
    )


async def _find_by_key(request: Request, ws: uuid.UUID, key: str) -> dict | None:
    rows = await _rows(
        request,
        "GET",
        "production_jobs",
        params={"select": JOB_COLUMNS, "workspace_id": f"eq.{ws}", "idempotency_key": f"eq.{key}"},
    )
    return rows[0] if rows else None


async def _rpc(request: Request, name: str, payload: dict, stale_field: str) -> dict:
    path = f"rpc/{name}"
    resp = await _send(request, "POST", path, json=payload)
    if 400 <= resp.status_code < 500:
        try:
            code = resp.json().get("code")
        except ValueError, AttributeError:
            code = None
        if code == _RPC_NOT_FOUND:
            raise not_found()
        if code == _RPC_STATE:
            raise ApiError(409, "CONFLICT", "현재 상태에서는 할 수 없습니다.")
        if code == _RPC_STALE:
            raise _stale(stale_field)
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: POST %s", resp.status_code, path)
        raise db_error()
    try:
        body = resp.json()
    except ValueError as exc:
        raise db_error() from exc
    if not isinstance(body, dict):
        raise db_error()
    return body


async def _source_duration(request: Request, ws: uuid.UUID, job_id: uuid.UUID) -> float | None:
    """편집안 길이 상한 기준: 준비(prepare)가 만든 최신 ready `source` 자산 길이(초)."""
    rows = await _rows(
        request,
        "GET",
        "production_assets",
        params={
            "select": "duration_sec",
            "job_id": f"eq.{job_id}",
            "workspace_id": f"eq.{ws}",
            "kind": "eq.source",
            "status": "eq.ready",
            "order": "created_at.desc",
            "limit": "1",
        },
    )
    value = rows[0].get("duration_sec") if rows else None
    return float(value) if isinstance(value, int | float) else None


def _validate(spec: dict, job: dict, source_duration: float | None) -> dict:
    """validate_spec + 작업 값 비교(source_start_sec·preset_version, task-021 리뷰 🟡2).

    스키마 오류가 있으면 의미 검사(작업 값 비교 포함)를 하지 않는다.
    """
    result = validate_spec(spec, source_duration=source_duration, job_lang=job.get("lang"))
    if any(e["code"].startswith("schema.") for e in result["errors"]):
        return result
    start = spec.get("source_start_sec")
    if start is not None and abs(float(start) - float(job["source_start_sec"])) > TOL:
        result["errors"].append(
            {
                "code": "source_start_sec.mismatch",
                "path": "source_start_sec",
                "message": "작업의 원본 시작점과 같아야 합니다.",
            }
        )
    preset = spec.get("preset_version")
    if preset is not None and preset != job["preset_version"]:
        result["errors"].append(
            {
                "code": "preset_version.mismatch",
                "path": "preset_version",
                "message": "작업의 프리셋 버전과 같아야 합니다.",
            }
        )
    return result


def _rejected(validation: dict) -> bool:
    """저장하지 않고 400으로 돌려보낼 오류: 스키마 오류·경로 문자열."""
    return any(
        e["code"].startswith("schema.") or e["code"] == "path.forbidden"
        for e in validation["errors"]
    )


def _is_prepare_state(job: dict) -> bool:
    return job["status"] == "draft" or (
        job["status"] == "failed" and job.get("failed_stage") == "prepare"
    )


def _rights_patch(new: bool, current: bool, user: CurrentUser, now: datetime) -> dict[str, Any]:
    """D7: false→true일 때만 by·at 기록, true 재전송은 유지, false면 둘 다 null."""
    if not new:
        return {"rights_confirmed": False, "rights_confirmed_by": None, "rights_confirmed_at": None}
    if current:
        return {"rights_confirmed": True}
    return {
        "rights_confirmed": True,
        "rights_confirmed_by": str(user.user_id),
        "rights_confirmed_at": now.isoformat(),
    }


def _http(request: Request) -> Any:
    return request.app.state.http


# --- A-09 ----------------------------------------------------------------------


@router.post("", response_model=JobEnvelope, status_code=201)
async def create_job(
    body: JobCreateIn,
    request: Request,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    user: CurrentUser = Depends(get_current_user),
) -> JobEnvelope:
    if idempotency_key is None or not _KEY_RE.fullmatch(idempotency_key):
        raise ApiError(400, "VALIDATION", "Idempotency-Key 헤더가 필요합니다.", "Idempotency-Key")
    ws = user.workspace_id

    # D1: 같은 키 재요청은 본문이 달라도 기존 작업 200
    existing = await _find_by_key(request, ws, idempotency_key)
    if existing is not None:
        response.status_code = 200
        return JobEnvelope(job=JobOut.model_validate(existing))

    if body.format != "category":
        raise _not_ready_yet("format")  # variety는 task-035, shopping은 task-042
    if body.source_kind == "url" or body.source_url is not None:
        raise _not_ready_yet("source_kind")  # D6: URL 원본은 task-031(SSRF)
    if body.candidate_id is not None:
        found = await _rows(
            request,
            "GET",
            "candidates",
            params={"select": "id", "id": f"eq.{body.candidate_id}", "workspace_id": f"eq.{ws}"},
        )
        if not found:
            raise not_found()

    now = datetime.now(UTC)
    row = {
        "workspace_id": str(ws),
        "title": body.title,
        "format": body.format,
        "candidate_id": str(body.candidate_id) if body.candidate_id else None,
        "source_kind": body.source_kind,
        "license_cc": body.license_cc,
        "credit": body.credit or None,
        "source_start_sec": body.source_start_sec,
        "segment_len_sec": body.segment_len_sec,
        "preset_version": PRESET_VERSION[body.format],
        "requested_by": str(user.user_id),
        "idempotency_key": idempotency_key,
        **_rights_patch(body.rights_confirmed, False, user, now),
    }
    resp = await _send(
        request,
        "POST",
        "production_jobs",
        params={"select": JOB_COLUMNS},
        json=row,
        headers={"Prefer": "return=representation"},
    )
    if resp.status_code == 409:
        try:
            err = resp.json()
        except ValueError:
            err = {}
        text = f"{err.get('message', '')} {err.get('details', '')}" if isinstance(err, dict) else ""
        if IDEMPOTENCY_CONSTRAINT in text:
            hit = await _find_by_key(request, ws, idempotency_key)
            if hit is None:
                raise db_error()
            response.status_code = 200
            return JobEnvelope(job=JobOut.model_validate(hit))
    rows = _json_list(resp, "POST", "production_jobs")
    if not rows:
        raise db_error()
    logger.info("제작 작업 생성: %s", rows[0]["id"])
    return JobEnvelope(job=JobOut.model_validate(rows[0]))


@router.get("", response_model=JobListOut)
async def list_jobs(
    request: Request,
    status: Literal["draft", "preparing", "review", "rendering", "inspect", "done", "failed"]
    | None = None,
    job_format: Annotated[Literal["category", "variety"] | None, Query(alias="format")] = None,
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
    size: Annotated[int, Query(ge=1, le=60)] = 24,
    user: CurrentUser = Depends(get_current_user),
) -> JobListOut:
    await expire_offline(request, user.workspace_id)  # task-023 E3
    params = {
        "select": LIST_COLUMNS,
        "workspace_id": f"eq.{user.workspace_id}",
        "order": "created_at.desc,id.desc",
        "limit": str(size),
        "offset": str((page - 1) * size),
    }
    if status is not None:
        params["status"] = f"eq.{status}"
    if job_format is not None:
        params["format"] = f"eq.{job_format}"
    rows = await _rows(request, "GET", "production_jobs", params=params)
    return JobListOut(items=[JobListItem.model_validate(r) for r in rows])


@router.get("/{job_id}", response_model=JobDetailOut)
async def get_job(
    job_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user)
) -> JobDetailOut:
    ws = user.workspace_id
    await expire_offline(request, ws)  # task-023 E3: 오프라인 지연 평가
    job = await _get_job(request, ws, job_id, f"{JOB_COLUMNS},claimed_by")
    scope = {"job_id": f"eq.{job_id}", "workspace_id": f"eq.{ws}"}
    rev_id = job.get("current_revision_id")

    async def _revision() -> list:
        if not rev_id:
            return []
        return await _rows(
            request,
            "GET",
            "edit_revisions",
            params={"select": "id,rev_no,approved_at,validation", "id": f"eq.{rev_id}", **scope},
        )

    assets, revs, runs = await asyncio.gather(
        _rows(
            request,
            "GET",
            "production_assets",
            params={"select": ASSET_COLUMNS, **scope, "order": "created_at.asc,id.asc"},
        ),
        _revision(),
        _rows(
            request,
            "GET",
            "render_runs",
            params={"select": RUN_COLUMNS, **scope, "order": "created_at.desc", "limit": "1"},
        ),
    )
    run = runs[0] if runs else None
    claimed = (run or {}).get("claimed_by") or job.get("claimed_by")
    last_seen = await _worker_last_seen(request, ws, {"claimed_by": claimed})
    online = last_seen is not None and datetime.now(UTC) - last_seen <= OFFLINE_AFTER
    return JobDetailOut(
        job=JobOut.model_validate(job),
        assets=[AssetOut.model_validate(a) for a in assets],
        current_revision=CurrentRevisionOut(
            ko=RevisionSummary.model_validate(revs[0]) if revs else None
        ),
        latest_run=RunOut.model_validate(run) if run else None,
        worker_online=online,
    )


@router.patch("/{job_id}", response_model=JobEnvelope)
async def patch_job(
    job_id: uuid.UUID,
    body: JobPatchIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> JobEnvelope:
    sent = body.model_fields_set
    if not sent:
        raise ApiError(400, "VALIDATION", "바꿀 필드가 없습니다.")
    for name in _PATCH_NOT_NULL:
        if name in sent and getattr(body, name) is None:
            raise ApiError(400, "VALIDATION", "입력값이 올바르지 않습니다.", name)
    if body.source_kind == "url" or "source_url" in sent:
        raise _not_ready_yet("source_kind")  # D6

    ws = user.workspace_id
    job = await _get_job(request, ws, job_id)
    if not _is_prepare_state(job):
        raise _state_conflict(job["status"])

    data: dict[str, Any] = {}
    for name in ("source_kind", "license_cc", "credit", "source_start_sec", "segment_len_sec"):
        if name in sent:
            data[name] = getattr(body, name)
    if "credit" in data:
        data["credit"] = data["credit"] or None
    now = datetime.now(UTC)
    if "rights_confirmed" in sent:
        data.update(
            _rights_patch(bool(body.rights_confirmed), bool(job["rights_confirmed"]), user, now)
        )
    data["updated_at"] = now.isoformat()
    # 읽은 상태·권리 값이 그대로일 때만 갱신(동시 변경이면 409)
    params = {
        "id": f"eq.{job_id}",
        "workspace_id": f"eq.{ws}",
        "status": f"eq.{job['status']}",
        "rights_confirmed": f"is.{str(bool(job['rights_confirmed'])).lower()}",
    }
    if job["status"] == "failed":
        params["failed_stage"] = "eq.prepare"
    rows = await _patch_job(request, params, data)
    if not rows:
        raise _stale("status")
    return JobEnvelope(job=JobOut.model_validate(rows[0]))


# --- A-10 ----------------------------------------------------------------------


def _upload_state_ok(kind: str, job: dict) -> bool:
    if kind == "source_upload":
        return _is_prepare_state(job)
    # hook_audio: review·failed(render), task-023 E10으로 failed(audio)도(audio_missing 복구)
    return job["status"] == "review" or (
        job["status"] == "failed" and job.get("failed_stage") in ("render", "audio")
    )


async def _uploads(
    request: Request, ws: uuid.UUID, job_id: uuid.UUID, kind: str = "source_upload"
) -> list[dict]:
    return await _rows(
        request,
        "GET",
        "production_assets",
        params={
            "select": "id,status,storage_path",
            "job_id": f"eq.{job_id}",
            "workspace_id": f"eq.{ws}",
            "kind": f"eq.{kind}",
        },
    )


async def _drop_pending(request: Request, ws: uuid.UUID, job_id: uuid.UUID, asset: dict) -> None:
    """pending 자산의 Storage 객체와 행을 지운다(ready 행은 조건으로 보호)."""
    state = request.app.state
    await storage.delete_object(_http(request), state.settings, asset["storage_path"])
    await _rows(
        request,
        "DELETE",
        "production_assets",
        params={
            "id": f"eq.{asset['id']}",
            "job_id": f"eq.{job_id}",
            "workspace_id": f"eq.{ws}",
            "status": "eq.pending",
            "select": "id",
        },
        headers={"Prefer": "return=representation"},
    )


@router.post("/{job_id}/uploads", response_model=UploadOut, status_code=201)
async def create_upload(
    job_id: uuid.UUID,
    body: UploadIn,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(get_current_user),
) -> UploadOut:
    ext = UPLOAD_MIME[body.kind].get(body.mime)
    if ext is None:
        raise ApiError(400, "VALIDATION", "허용되지 않은 파일 형식입니다.", "mime")
    ws = user.workspace_id
    job = await _get_job(request, ws, job_id, "id,status,failed_stage,format")
    if body.kind == "hook_audio" and job["format"] != "category":
        raise ApiError(400, "VALIDATION", "이 형식은 훅 음성을 쓰지 않습니다.", "kind")
    if not _upload_state_ok(body.kind, job):
        raise _state_conflict(job["status"])

    current = await _uploads(request, ws, job_id, body.kind)
    # D5: 원본은 작업당 1건(ready가 있으면 409). 원본·훅 음성 모두 이전 pending은 지운다
    if body.kind == "source_upload" and any(a["status"] == "ready" for a in current):
        raise ApiError(409, "CONFLICT", "이미 업로드된 원본이 있습니다.", "kind")
    for old in current:
        if old["status"] == "pending":
            await _drop_pending(request, ws, job_id, old)

    asset_id = uuid.uuid4()
    path = storage.object_path(ws, job_id, asset_id, ext)
    rows = await _rows(
        request,
        "POST",
        "production_assets",
        params={"select": "id,kind,status"},
        json={
            "id": str(asset_id),
            "workspace_id": str(ws),
            "job_id": str(job_id),
            "kind": body.kind,
            "storage_path": path,
            "mime": body.mime,
            "size_bytes": body.size_bytes,
            "status": "pending",
            "created_by": str(user.user_id),
        },
        headers={"Prefer": "return=representation"},
    )
    if not rows:
        raise db_error()
    url, expires_at = await storage.sign_upload(_http(request), request.app.state.settings, path)
    response.headers["Cache-Control"] = "no-store"
    logger.info("업로드 서명 발급: job=%s asset=%s kind=%s", job_id, asset_id, body.kind)
    return UploadOut(
        asset=UploadAssetOut.model_validate(rows[0]), upload_url=url, expires_at=expires_at
    )


@router.post("/{job_id}/uploads/{asset_id}/complete", response_model=AssetEnvelope)
async def complete_upload(
    job_id: uuid.UUID,
    asset_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> AssetEnvelope:
    ws = user.workspace_id
    asset = await _get_asset(request, ws, job_id, asset_id, f"{ASSET_COLUMNS},storage_path")
    if asset["status"] == "ready":
        return AssetEnvelope(asset=AssetOut.model_validate(asset))
    if asset["kind"] not in UPLOAD_MIME:
        raise ApiError(409, "CONFLICT", "사용자가 올리는 자산이 아닙니다.")
    job = await _get_job(request, ws, job_id, "id,status,failed_stage,format")
    if not _upload_state_ok(asset["kind"], job):
        raise _state_conflict(job["status"])
    if asset["kind"] == "source_upload":
        others = await _uploads(request, ws, job_id)
        if any(a["status"] == "ready" and a["id"] != str(asset_id) for a in others):
            raise ApiError(409, "CONFLICT", "이미 업로드된 원본이 있습니다.")

    size = await storage.object_size(
        _http(request), request.app.state.settings, asset["storage_path"]
    )
    if size is None:
        raise ApiError(409, "CONFLICT", "업로드된 파일이 없습니다.")
    if size != asset.get("size_bytes") or size > storage.MAX_UPLOAD_BYTES:
        # 선언과 다른 파일은 남기지 않는다(다시 업로드 요청부터)
        await _drop_pending(request, ws, job_id, asset)
        raise ApiError(409, "CONFLICT", "업로드된 파일 크기가 요청과 다릅니다.", "size_bytes")

    resp = await _send(
        request,
        "PATCH",
        "production_assets",
        params={
            "id": f"eq.{asset_id}",
            "job_id": f"eq.{job_id}",
            "workspace_id": f"eq.{ws}",
            "status": "eq.pending",
            "select": ASSET_COLUMNS,
        },
        json={"status": "ready"},
        headers={"Prefer": "return=representation"},
    )
    if resp.status_code == 409 and READY_SOURCE_INDEX in resp.text:
        # 동시 complete 경합: 다른 원본이 먼저 ready가 됐다(000016 부분 unique)
        raise ApiError(409, "CONFLICT", "이미 업로드된 원본이 있습니다.")
    rows = _json_list(resp, "PATCH", "production_assets")
    if not rows:
        # 동시 완료 요청: 이미 ready면 멱등 200
        again = await _get_asset(request, ws, job_id, asset_id, ASSET_COLUMNS)
        if again["status"] != "ready":
            raise db_error()
        rows = [again]
    logger.info("업로드 완료: job=%s asset=%s", job_id, asset_id)
    return AssetEnvelope(asset=AssetOut.model_validate(rows[0]))


# --- A-11 ----------------------------------------------------------------------


@router.post("/{job_id}/prepare", response_model=JobEnvelope, status_code=202)
async def prepare_job(
    job_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user)
) -> JobEnvelope:
    ws = user.workspace_id
    job = await _get_job(request, ws, job_id)
    if not _is_prepare_state(job):
        raise _state_conflict(job["status"])
    retry = job["status"] == "failed"
    if retry and job["retry_count"] >= MAX_PREPARE_RETRY:
        raise ApiError(409, "CONFLICT", "재시도 횟수를 넘었습니다.")
    if job["source_kind"] == "upload":
        uploads = await _uploads(request, ws, job_id)
        if not any(a["status"] == "ready" for a in uploads):
            raise ApiError(400, "VALIDATION", "업로드된 원본이 없습니다.", "source_upload")

    # D8: 읽은 상태·retry_count 조건부 PATCH 한 번
    params = {
        "id": f"eq.{job_id}",
        "workspace_id": f"eq.{ws}",
        "status": f"eq.{job['status']}",
        "retry_count": f"eq.{job['retry_count']}",
    }
    if retry:
        params["failed_stage"] = "eq.prepare"
    rows = await _patch_job(
        request,
        params,
        {
            "status": "preparing",
            "retry_count": job["retry_count"] + (1 if retry else 0),
            "failed_stage": None,
            "error_code": None,
            "claimed_by": None,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )
    if not rows:
        raise _stale("status")
    logger.info("제작 준비 요청: job=%s retry=%s", job_id, retry)
    return JobEnvelope(job=JobOut.model_validate(rows[0]))


# --- A-12 ----------------------------------------------------------------------


@router.get("/{job_id}/revision", response_model=RevisionEnvelope)
async def get_revision(
    job_id: uuid.UUID,
    request: Request,
    rev_no: Annotated[int | None, Query(ge=1)] = None,
    lang: Literal["ko"] = "ko",
    user: CurrentUser = Depends(get_current_user),
) -> RevisionEnvelope:
    ws = user.workspace_id
    job = await _get_job(request, ws, job_id, "id,current_revision_id")
    params = {
        "select": REVISION_COLUMNS,
        "job_id": f"eq.{job_id}",
        "workspace_id": f"eq.{ws}",
        "lang": f"eq.{lang}",
    }
    if rev_no is not None:
        params["rev_no"] = f"eq.{rev_no}"
    elif job.get("current_revision_id"):
        params["id"] = f"eq.{job['current_revision_id']}"
    else:
        raise not_found()
    rows = await _rows(request, "GET", "edit_revisions", params=params)
    if not rows:
        raise not_found()
    return RevisionEnvelope(revision=RevisionOut.model_validate(rows[0]))


@router.put("/{job_id}/revision", response_model=RevisionEnvelope)
async def put_revision(
    job_id: uuid.UUID,
    body: RevisionPutIn,
    request: Request,
    lang: Literal["ko"] = "ko",
    user: CurrentUser = Depends(get_current_user),
) -> RevisionEnvelope | JSONResponse:
    ws = user.workspace_id
    job = await _get_job(
        request,
        ws,
        job_id,
        "id,status,failed_stage,lang,source_start_sec,preset_version,current_revision_id",
    )
    # D3: review·inspect·failed(audio·render)만, 리비전 없으면 409
    editable = job["status"] in ("review", "inspect") or (
        job["status"] == "failed" and job.get("failed_stage") in ("audio", "render")
    )
    if not editable or not job.get("current_revision_id"):
        raise _state_conflict(job["status"])

    validation = _validate(body.spec, job, await _source_duration(request, ws, job_id))
    if _rejected(validation):
        return _validation_response("편집안 형식이 올바르지 않습니다.", validation)
    saved = await _rpc(
        request,
        "save_production_revision",
        {
            "p_workspace": str(ws),
            "p_job": str(job_id),
            "p_user": str(user.user_id),
            "p_base_rev_no": body.base_rev_no,
            "p_spec": body.spec,
            "p_validation": validation,
        },
        "base_rev_no",
    )
    logger.info(
        "편집안 저장: job=%s rev=%s errors=%d",
        job_id,
        saved.get("rev_no"),
        len(validation["errors"]),
    )
    return RevisionEnvelope(revision=RevisionOut.model_validate(saved))


# --- A-13 ----------------------------------------------------------------------


@router.post("/{job_id}/revision/approve", response_model=ApprovedEnvelope)
async def approve_revision(
    job_id: uuid.UUID,
    body: ApproveIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> ApprovedEnvelope | JSONResponse:
    ws = user.workspace_id
    job = await _get_job(
        request,
        ws,
        job_id,
        "id,status,lang,source_start_sec,preset_version,current_revision_id",
    )
    if job["status"] != "review" or not job.get("current_revision_id"):
        raise _state_conflict(job["status"])
    revs = await _rows(
        request,
        "GET",
        "edit_revisions",
        params={
            "select": "id,rev_no,spec,approved_at,updated_at",
            "id": f"eq.{job['current_revision_id']}",
            "job_id": f"eq.{job_id}",
            "workspace_id": f"eq.{ws}",
        },
    )
    if not revs:
        raise _state_conflict(job["status"])
    rev = revs[0]
    if rev["rev_no"] != body.rev_no:
        raise _stale("rev_no")
    if rev["approved_at"] is not None:
        raise ApiError(409, "CONFLICT", "이미 승인된 리비전입니다.", "rev_no")

    # 서버 재검증(저장된 validation을 믿지 않는다)
    validation = _validate(rev["spec"], job, await _source_duration(request, ws, job_id))
    if validation["errors"]:
        return _validation_response("편집안에 오류가 있어 승인할 수 없습니다.", validation)
    approved = await _rpc(
        request,
        "approve_production_revision",
        {
            "p_workspace": str(ws),
            "p_job": str(job_id),
            "p_user": str(user.user_id),
            "p_rev_no": body.rev_no,
            "p_updated_at": rev["updated_at"],
            "p_validation": validation,
        },
        "rev_no",
    )
    logger.info("편집안 승인: job=%s rev=%s", job_id, approved.get("rev_no"))
    return ApprovedEnvelope(revision=ApprovedRevisionOut.model_validate(approved))


# --- A-17 ----------------------------------------------------------------------


@router.post("/{job_id}/review/approve", response_model=JobEnvelope)
async def approve_review(
    job_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user)
) -> JobEnvelope:
    ws = user.workspace_id
    job = await _get_job(request, ws, job_id, "id,status,current_revision_id")
    rev_id = job.get("current_revision_id")
    if job["status"] != "inspect" or not rev_id:
        raise _state_conflict(job["status"])
    scope = {"job_id": f"eq.{job_id}", "workspace_id": f"eq.{ws}"}
    # D9: 현재 승인 리비전의 최신 done run → mp4 자산 ready
    runs = await _rows(
        request,
        "GET",
        "render_runs",
        params={
            "select": "id,mp4_asset_id",
            **scope,
            "revision_id": f"eq.{rev_id}",
            "lang": "eq.ko",
            "status": "eq.done",
            "order": "created_at.desc",
            "limit": "1",
        },
    )
    mp4_id = runs[0].get("mp4_asset_id") if runs else None
    mp4 = []
    if mp4_id:
        mp4 = await _rows(
            request,
            "GET",
            "production_assets",
            params={
                "select": "id",
                "id": f"eq.{mp4_id}",
                **scope,
                "kind": "eq.output_mp4",
                "status": "eq.ready",
            },
        )
    if not mp4:
        raise ApiError(409, "CONFLICT", "검수할 MP4가 없습니다.")
    now = datetime.now(UTC).isoformat()
    rows = await _patch_job(
        request,
        {
            "id": f"eq.{job_id}",
            "workspace_id": f"eq.{ws}",
            "status": "eq.inspect",
            "current_revision_id": f"eq.{rev_id}",
        },
        {"status": "done", "completed_at": now, "updated_at": now},
    )
    if not rows:
        raise _stale("status")
    logger.info("검수 승인: job=%s", job_id)
    return JobEnvelope(job=JobOut.model_validate(rows[0]))


# --- A-18 ----------------------------------------------------------------------


@router.get("/{job_id}/assets/{asset_id}/download-url", response_model=DownloadOut)
async def download_url(
    job_id: uuid.UUID,
    asset_id: uuid.UUID,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(get_current_user),
) -> DownloadOut:
    asset = await _get_asset(
        request, user.workspace_id, job_id, asset_id, "id,kind,status,storage_path"
    )
    if asset["status"] != "ready":
        raise ApiError(409, "CONFLICT", "아직 준비되지 않은 파일입니다.")
    url, expires_at = await storage.sign_download(
        _http(request), request.app.state.settings, asset["storage_path"]
    )
    response.headers["Cache-Control"] = "no-store"
    logger.info("다운로드 서명 발급: job=%s asset=%s kind=%s", job_id, asset_id, asset["kind"])
    return DownloadOut(url=url, expires_at=expires_at, kind=asset["kind"])
