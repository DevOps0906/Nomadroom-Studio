"""제작 작업 API A-09~A-13·A-17·A-18·A-21. 근거: docs/04_API.md#제작-api, tasks/task-022.md(D1~D9),
쇼핑(kind=shopping)은 tasks/task-044.md#착수-결정(P1~P10),
일본어판(lang=ja) A-12·A-13은 tasks/task-049.md#착수-결정(J2·J4~J8, RPC 000027).

- 웹·API는 작업 ID·자산 ID만 주고받는다. 경로는 서버가 만든다(production/storage.py).
- 모든 조회에 workspace_id 조건, 자산은 id·job_id·workspace_id 세 조건(D9). 타 워크스페이스 404.
- 서명 URL·토큰·제휴 링크는 로그에 쓰지 않는다(응답에만).
"""

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
)

from app.auth.user import CurrentUser, get_current_user
from app.errors import ApiError, db_error, not_found
from app.jobs.state import OFFLINE_AFTER
from app.production import shopping, storage, translate
from app.production.runs import delete_objects, expire_offline
from app.production.spec import TOL
from app.production.url_guard import check_source_url
from app.production.validation_shopping import validate_shopping_spec
from app.production.validation_variety import validate_for_format
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
    "ai_draft_count,retry_count,updated_at,requested_by,created_at,completed_at,"
    "kind,vertical,brief,affiliates,comment_keyword,current_ja_revision_id"
)
LIST_COLUMNS = (
    "id,title,kind,format,vertical,status,failed_stage,error_code,candidate_id,updated_at,"
    "completed_at,current_revision_id,current_ja_revision_id"
)
# task-045: rights·parent_asset_id는 쇼핑 PROD-03 권리 목록·원본 계보용(A-09 상세)
ASSET_COLUMNS = "id,kind,status,size_bytes,duration_sec,rights,parent_asset_id"
RUN_COLUMNS = "id,status,progress_pct,progress_stage,error_stage,error_code,attempt,claimed_by"
REVISION_COLUMNS = "id,rev_no,spec,origin,validation,approved_at,derived_from,updated_at"
IDEMPOTENCY_CONSTRAINT = "production_jobs_workspace_id_idempotency_key_key"
# 원본 개수 트리거(000023): 23505 = 일반 ready 2건째·쇼핑 11건째, NR010 = 상태 불가
_SOURCE_LIMIT = "23505"

# 형식별 출력 프리셋(서버가 정함). shopping 값은 가정(렌더러 task-045가 같은 값을 쓴다)
PRESET_VERSION = {
    "category": "category-1080-v1",
    "variety": "variety-1080-v1",
    "shopping": "shopping-1080-v1",
}
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
# 쇼핑 업로드(A-10): 사진·BGM·첨부 녹음. 음성은 hook_audio와 같은 목록(버킷 allowed_mime_types 안)
UPLOAD_MIME["image"] = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
UPLOAD_MIME["bgm"] = UPLOAD_MIME["hook_audio"]
UPLOAD_MIME["narration"] = UPLOAD_MIME["hook_audio"]
SHOPPING_UPLOADS = ("source_upload", "image", "bgm", "narration")
# P9: 사용자가 지울 수 있는 자산
_DELETABLE = ("source_upload", "image", "bgm", "narration")

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


Keyword = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=50),
    BeforeValidator(shopping.no_control),
]


class JobCreateIn(BaseModel):
    # rights_confirmed_by·at 등 서버 칸은 extra=forbid로 거부(D7)
    model_config = ConfigDict(extra="forbid")

    title: Title
    kind: Literal["general", "shopping"] = "general"
    # 기본값: kind=shopping이면 shopping, 아니면 category(kind와 짝이 맞아야 함)
    format: Literal["category", "variety", "shopping"] | None = None
    vertical: Literal["product", "travel"] | None = None
    brief: shopping.BriefIn | None = None
    affiliates: shopping.Affiliates = []
    comment_keyword: Keyword | None = None
    # 금지 품목(의약품·건강기능식품) 아님 확인 체크(쇼핑 필수, 저장하지 않음)
    not_banned_confirmed: bool = False
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
    # P10: 쇼핑만(kind 불변)
    vertical: Literal["product", "travel"] | None = None
    brief: shopping.BriefIn | None = None
    affiliates: shopping.Affiliates | None = None
    comment_keyword: Keyword | None = None


_PATCH_NOT_NULL = (
    "source_kind",
    "rights_confirmed",
    "source_start_sec",
    "segment_len_sec",
    "vertical",
    "affiliates",
)
_SHOPPING_FIELDS = ("vertical", "brief", "affiliates", "comment_keyword")
_SHOPPING_EDIT_STATES = ("review", "inspect")


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
    kind: str
    vertical: str | None
    brief: dict[str, Any] | None
    affiliates: list[dict[str, Any]]
    comment_keyword: str | None
    current_ja_revision_id: uuid.UUID | None


class JobEnvelope(BaseModel):
    job: JobOut


class JobListItem(BaseModel):
    id: uuid.UUID
    title: str
    kind: str
    format: str
    vertical: str | None
    langs: list[str]  # 리비전 보유 언어(←current_revision_id·current_ja_revision_id)
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
    rights: dict[str, Any] | None = None  # task-045: 사용자 입력 권리(쇼핑), 없으면 null
    parent_asset_id: uuid.UUID | None = None  # task-044 P1 계보(파생 산출물의 원본)


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

    kind: Literal["source_upload", "hook_audio", "image", "bgm", "narration"]
    size_bytes: Annotated[int, Field(strict=True, ge=1, le=storage.MAX_UPLOAD_BYTES)]
    mime: Annotated[str, StringConstraints(max_length=100)]
    rights: shopping.RightsIn | None = None  # 쇼핑 필수, 일반 선택(P6)


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
    derived_from: uuid.UUID | None = None  # ja 리비전의 원본 ko 리비전(task-049)
    updated_at: datetime  # 다음 PUT의 base_updated_at(task-059 L1)


class RevisionEnvelope(BaseModel):
    revision: RevisionOut


class RevisionPutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: dict[str, Any]
    base_rev_no: Annotated[int, Field(strict=True, ge=1)]
    # task-059 L3·L4: 읽은 리비전 updated_at(필수, 시간대 포함). 잠금 안에서 rev_no와 함께 비교
    base_updated_at: AwareDatetime


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rev_no: Annotated[int, Field(strict=True, ge=1)]
    lang: Literal["ko", "ja"] = "ko"  # task-049 J5


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


class PublishText(BaseModel):
    caption: str
    pinned_comment: str
    recommended_time: str


class PublishTextOut(BaseModel):
    text: PublishText
    render_run_id: uuid.UUID
    lang: str


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


def _source_size(job: dict) -> tuple[float, float] | None:
    meta = job.get("source_meta")
    if not isinstance(meta, dict):
        return None
    w, h = meta.get("width"), meta.get("height")
    if isinstance(w, int | float) and isinstance(h, int | float):
        return float(w), float(h)
    return None


async def _shopping_assets(request: Request, ws: uuid.UUID, job_id: uuid.UUID) -> dict:
    """쇼핑 검증용 자산 맵(이 작업 소유·렌더 산출물 제외, task-043 fail-closed)."""
    rows = await _rows(
        request,
        "GET",
        "production_assets",
        params={
            "select": "id,kind,status,duration_sec,rights,reviewed,parent_asset_id",
            "job_id": f"eq.{job_id}",
            "workspace_id": f"eq.{ws}",
            "render_run_id": "is.null",
        },
    )
    return shopping.assets_map(rows)


def _validate(
    spec: dict,
    job: dict,
    source_duration: float | None,
    assets: dict | None = None,
    lang: str | None = None,
) -> dict:
    """작업 format별 검증(validate_for_format) + 작업 값 비교(source_start_sec·preset_version).

    스키마 오류가 있으면 의미 검사(작업 값 비교 포함)를 하지 않는다(task-021 리뷰 🟡2).
    variety: 구간 길이 = min(segment_len_sec, 원본 길이), 원본 크기 = source_meta(task-035 V4).
    shopping: 이 작업 자산 맵(assets)이 없으면 assets.required 오류(fail-closed).
    lang: 리비전 언어(task-049 J4, 없으면 작업 lang).
    """
    lang = lang or job.get("lang")
    size = _source_size(job)
    segment_len = float(job["segment_len_sec"]) if job.get("segment_len_sec") is not None else None
    if segment_len is not None and source_duration is not None:
        segment_len = min(segment_len, source_duration)
    if job["format"] == "shopping" and assets is not None:
        result = validate_shopping_spec(
            spec,
            assets=assets,
            job_lang=lang,
            product_name=shopping.product_name(job),
        )
    else:
        result = validate_for_format(
            job["format"],
            spec,
            source_duration=source_duration,
            segment_len=segment_len,
            source_size=size,
            job_lang=lang,
        )
    if any(e["code"].startswith("schema.") for e in result["errors"]):
        return result
    if job["format"] == "variety" and size is None:
        result["errors"].append(
            {
                "code": "source_size.missing",
                "path": "source_size",
                "message": "원본 크기를 알 수 없습니다. 준비를 다시 실행하세요.",
            }
        )
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


# --- 일본어판(ja) 리비전(task-049) ------------------------------------------------


async def _revision_row(
    request: Request, ws: uuid.UUID, job_id: Any, rev_id: Any, lang: str, columns: str
) -> dict | None:
    if not rev_id:
        return None
    rows = await _rows(
        request,
        "GET",
        "edit_revisions",
        params={
            "select": columns,
            "id": f"eq.{rev_id}",
            "job_id": f"eq.{job_id}",
            "workspace_id": f"eq.{ws}",
            "lang": f"eq.{lang}",
        },
    )
    return rows[0] if rows else None


async def _ko_approved(request: Request, ws: uuid.UUID, job: dict) -> bool:
    """현재 ko 리비전이 승인됐는지(J2)."""
    ko = await _revision_row(
        request, ws, job["id"], job.get("current_revision_id"), "ko", "id,approved_at"
    )
    return ko is not None and ko.get("approved_at") is not None


async def _ja_rendering(request: Request, ws: uuid.UUID, job_id: Any) -> bool:
    rows = await _rows(
        request,
        "GET",
        "render_runs",
        params={
            "select": "id",
            "job_id": f"eq.{job_id}",
            "workspace_id": f"eq.{ws}",
            "lang": "eq.ja",
            "status": "in.(queued,running)",
            "limit": "1",
        },
    )
    return bool(rows)


async def _ja_writable(request: Request, ws: uuid.UUID, job: dict) -> None:
    """J2: 현재 ko 승인 + ja 렌더 진행 중 아님 + 현재 ja 리비전 있음. 아니면 409."""
    if not job.get("current_ja_revision_id") or not await _ko_approved(request, ws, job):
        raise ApiError(
            409, "CONFLICT", "원본(ko) 편집안이 승인되고 일본어판이 있을 때만 할 수 있습니다."
        )
    if await _ja_rendering(request, ws, job["id"]):
        raise ApiError(409, "CONFLICT", "일본어판 렌더가 진행 중입니다.")


async def _source_errors(request: Request, ws: uuid.UUID, job: dict, rev: dict) -> list[dict]:
    """J8: 읽는 시점에 derived_from과 현재 ko 승인 리비전을 비교한다."""
    return translate.source_changed(
        rev.get("derived_from"),
        job.get("current_revision_id"),
        await _ko_approved(request, ws, job),
    )


def _validate_ja(
    spec: dict,
    job: dict,
    ko_spec: Any,
    source_duration: float | None,
    assets: dict | None,
) -> dict:
    """ja 리비전 검증(J4·J6·J10): 리비전 lang=ja로 형식 검증 + ja 내용 규칙 + ko 녹음 참조."""
    result = _validate(spec, job, source_duration, assets, lang="ja")
    if any(e["code"].startswith("schema.") for e in result["errors"]):
        return result
    rules = translate.content_rules(job["format"], spec)
    result["errors"] += rules["errors"] + translate.voice_errors(job["format"], spec, ko_spec)
    result["warnings"] += rules["warnings"]
    return result


def _with_errors(rev: dict, extra: list[dict]) -> dict:
    """저장된 validation과 별개로 읽는 시점 오류를 합친 응답용 사본."""
    if not extra:
        return rev
    v = rev.get("validation") or {}
    return {
        **rev,
        "validation": {
            **v,
            "errors": [*(v.get("errors") or []), *extra],
            "warnings": list(v.get("warnings") or []),
        },
    }


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


def _check_url_source(kind: str, url: str | None, rights: bool) -> None:
    """task-031 G1·G8: url 작업은 권리 확인 + 허용 URL 필수, upload 작업은 URL 없음."""
    if kind == "url":
        if not rights:
            raise ApiError(
                400, "VALIDATION", "URL 원본은 사용 권한 확인이 필요합니다.", "rights_confirmed"
            )
        if url is None:
            raise ApiError(400, "VALIDATION", "URL을 입력하세요.", "source_url")
    elif url is not None:
        raise ApiError(400, "VALIDATION", "업로드 작업에는 URL을 쓰지 않습니다.", "source_url")


def _http(request: Request) -> Any:
    return request.app.state.http


def _banned() -> ApiError:
    """금지 품목(의약품·건강기능식품). 입력 값·찾은 키워드는 응답에 넣지 않는다."""
    return ApiError(
        400,
        "VALIDATION",
        "의약품·건강기능식품은 쇼핑 작업으로 만들 수 없습니다.",
        "banned_category",
    )


def _check_brief(brief: dict | None, vertical: str | None) -> None:
    bad = shopping.brief_vertical_field(brief, vertical)
    if bad is not None:
        raise ApiError(400, "VALIDATION", "분야에 맞지 않는 브리프 항목입니다.", bad)


def _write_conflict(
    resp: Any, limit_message: str = "원본을 더 올릴 수 없습니다."
) -> ApiError | None:
    """자산 쓰기의 원본 개수·상태 트리거(000023) 오류 → 409. 그 밖은 None."""
    if not 400 <= resp.status_code < 500:
        return None
    try:
        code = resp.json().get("code")
    except ValueError, AttributeError:
        return None
    if code == _SOURCE_LIMIT:
        return ApiError(409, "CONFLICT", limit_message, "kind")
    if code == _RPC_STATE:
        return ApiError(409, "CONFLICT", "현재 상태에서는 할 수 없습니다.")
    if code == "23503":
        return ApiError(409, "CONFLICT", "이 자산을 쓰는 파일이 있어 지울 수 없습니다.")
    return None


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

    fmt = body.format or ("shopping" if body.kind == "shopping" else "category")
    if (body.kind == "shopping") != (fmt == "shopping"):
        raise ApiError(400, "VALIDATION", "유형과 형식이 맞지 않습니다.", "format")
    brief = body.brief.model_dump(exclude_none=True) if body.brief is not None else None
    affiliates = [a.model_dump() for a in body.affiliates]
    keyword = body.comment_keyword or None
    if body.kind == "shopping":
        if body.vertical is None:
            raise ApiError(400, "VALIDATION", "분야를 선택하세요.", "vertical")
        if body.source_kind != "upload":
            raise ApiError(400, "VALIDATION", "쇼핑 원본은 업로드만 됩니다.", "source_kind")
        if not body.not_banned_confirmed or shopping.has_banned(body.title, brief, keyword):
            raise _banned()
        _check_brief(brief, body.vertical)
    else:
        for name in _SHOPPING_FIELDS:
            if name in body.model_fields_set and getattr(body, name) not in (None, []):
                raise ApiError(400, "VALIDATION", "쇼핑 작업에만 쓰는 항목입니다.", name)
    source_url = check_source_url(body.source_url) if body.source_url is not None else None
    _check_url_source(body.source_kind, source_url, body.rights_confirmed)
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
        "kind": body.kind,
        "format": fmt,
        "vertical": body.vertical if body.kind == "shopping" else None,
        "brief": brief,
        "affiliates": affiliates,
        "comment_keyword": keyword,
        "candidate_id": str(body.candidate_id) if body.candidate_id else None,
        "source_kind": body.source_kind,
        "source_url": source_url,
        "license_cc": body.license_cc,
        "credit": body.credit or None,
        "source_start_sec": body.source_start_sec,
        "segment_len_sec": body.segment_len_sec,
        "preset_version": PRESET_VERSION[fmt],
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


_LANG_REVISION = {"ko": "current_revision_id", "ja": "current_ja_revision_id"}


@router.get("", response_model=JobListOut)
async def list_jobs(
    request: Request,
    status: Literal["draft", "preparing", "review", "rendering", "inspect", "done", "failed"]
    | None = None,
    job_format: Annotated[
        Literal["category", "variety", "shopping"] | None, Query(alias="format")
    ] = None,
    kind: Literal["general", "shopping"] | None = None,
    lang: Literal["ko", "ja"] | None = None,
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
    if kind is not None:
        params["kind"] = f"eq.{kind}"
    if lang is not None:
        # 리비전 보유 언어 = 언어별 현재 리비전이 있음(ko는 첫 리비전부터 항상 current_revision_id)
        params[_LANG_REVISION[lang]] = "not.is.null"
    rows = await _rows(request, "GET", "production_jobs", params=params)
    items = [
        JobListItem.model_validate(
            {**r, "langs": [k for k, col in _LANG_REVISION.items() if r.get(col)]}
        )
        for r in rows
    ]
    return JobListOut(items=items)


@router.get("/{job_id}", response_model=JobDetailOut)
async def get_job(
    job_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user)
) -> JobDetailOut:
    ws = user.workspace_id
    await expire_offline(request, ws)  # task-023 E3: 오프라인 지연 평가
    job = await _get_job(request, ws, job_id, f"{JOB_COLUMNS},claimed_by")
    scope = {"job_id": f"eq.{job_id}", "workspace_id": f"eq.{ws}"}
    rev_ids = [str(job[c]) for c in _LANG_REVISION.values() if job.get(c)]

    async def _revision() -> list:
        if not rev_ids:
            return []
        return await _rows(
            request,
            "GET",
            "edit_revisions",
            params={
                "select": "id,rev_no,approved_at,validation",
                "id": f"in.({','.join(rev_ids)})",
                **scope,
            },
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
    by_id = {str(r["id"]): r for r in revs}
    current = {
        lang: RevisionSummary.model_validate(by_id[str(job[col])])
        if job.get(col) and str(job[col]) in by_id
        else None
        for lang, col in _LANG_REVISION.items()
    }
    return JobDetailOut(
        job=JobOut.model_validate(job),
        assets=[AssetOut.model_validate(a) for a in assets],
        current_revision=CurrentRevisionOut(**current),
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
    url_sent = "source_url" in sent
    new_url = check_source_url(body.source_url) if body.source_url is not None else None

    ws = user.workspace_id
    job = await _get_job(request, ws, job_id)
    # 리뷰 반영 7(P10): 쇼핑 항목(brief·affiliates·vertical·comment_keyword)만 보내면
    # review·inspect에서도 허용. 그 밖 필드는 기존대로 draft·failed(prepare)만
    shopping_only = job.get("kind") == "shopping" and sent <= set(_SHOPPING_FIELDS)
    if not (_is_prepare_state(job) or (shopping_only and job["status"] in _SHOPPING_EDIT_STATES)):
        raise _state_conflict(job["status"])
    # 보낸 값과 저장된 값을 합친 최종 상태로 검사(G8: url 작업의 권리 해제 400)
    kind = body.source_kind if "source_kind" in sent else job["source_kind"]
    if url_sent:
        url = new_url
    elif kind == "upload":
        url = None  # upload로 바꾸면 남은 URL은 지운다
    else:
        url = job.get("source_url")
    rights = body.rights_confirmed if "rights_confirmed" in sent else job["rights_confirmed"]
    _check_url_source(kind, url, bool(rights))

    data: dict[str, Any] = {}
    if job.get("kind") == "shopping":
        # P10: brief·affiliates·vertical(·comment_keyword). 최종 상태로 분야·금지 품목 재검사
        if kind != "upload":
            raise ApiError(400, "VALIDATION", "쇼핑 원본은 업로드만 됩니다.", "source_kind")
        if "brief" in sent:
            data["brief"] = (
                body.brief.model_dump(exclude_none=True) if body.brief is not None else None
            )
        if "affiliates" in sent:
            data["affiliates"] = [a.model_dump() for a in body.affiliates or []]
        if "comment_keyword" in sent:
            data["comment_keyword"] = body.comment_keyword or None
        if "vertical" in sent:
            data["vertical"] = body.vertical
        brief = data["brief"] if "brief" in sent else job.get("brief")
        keyword = (
            data["comment_keyword"] if "comment_keyword" in sent else job.get("comment_keyword")
        )
        if shopping.has_banned(job["title"], brief, keyword):
            raise _banned()
        _check_brief(brief, data.get("vertical", job.get("vertical")))
    else:
        for name in _SHOPPING_FIELDS:
            if name in sent:
                raise ApiError(400, "VALIDATION", "쇼핑 작업에만 쓰는 항목입니다.", name)
    for name in ("source_kind", "license_cc", "credit", "source_start_sec", "segment_len_sec"):
        if name in sent:
            data[name] = getattr(body, name)
    if "credit" in data:
        data["credit"] = data["credit"] or None
    if url_sent or "source_kind" in sent:
        data["source_url"] = url
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
        "source_kind": f"eq.{job['source_kind']}",  # task-031 리뷰: 원본 방식 동시 전환도 409
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
    if kind in ("image", "bgm", "narration"):
        # 쇼핑 사진·BGM·첨부 녹음: 준비·렌더 진행 중과 완료 뒤만 막는다(가정)
        return job["status"] in ("draft", "review", "inspect", "failed")
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
    job = await _get_job(request, ws, job_id, "id,status,failed_stage,format,kind")
    is_shopping = job.get("kind") == "shopping"
    if body.kind == "hook_audio" and job["format"] != "category":
        raise ApiError(400, "VALIDATION", "이 형식은 훅 음성을 쓰지 않습니다.", "kind")
    if body.kind in ("image", "bgm", "narration") and not is_shopping:
        raise ApiError(400, "VALIDATION", "쇼핑 작업에만 올릴 수 있습니다.", "kind")
    # P6: 쇼핑은 자산마다 권리 basis 필수, 초상 동의 없는 인물 자산 거부
    if is_shopping and body.rights is None:
        raise ApiError(400, "VALIDATION", "권리 근거를 입력하세요.", "rights")
    if body.rights is not None and body.rights.has_person and not body.rights.portrait_consent:
        raise ApiError(400, "VALIDATION", "인물 초상 동의가 필요합니다.", "rights.portrait_consent")
    if not _upload_state_ok(body.kind, job):
        raise _state_conflict(job["status"])

    current = await _uploads(request, ws, job_id, body.kind)
    if is_shopping and body.kind in shopping.MULTI_LIMITS:
        # P5: 쇼핑 원본·사진·문장별 녹음은 다건. 이전 pending을 지우지 않고 상한에 pending 포함
        if len(current) >= shopping.MULTI_LIMITS[body.kind]:
            raise ApiError(409, "CONFLICT", "더 올릴 수 없습니다.", "kind")
    else:
        # D5: 일반 원본은 작업당 1건(ready가 있으면 409). 이전 pending은 지운다
        if body.kind == "source_upload" and any(a["status"] == "ready" for a in current):
            raise ApiError(409, "CONFLICT", "이미 업로드된 원본이 있습니다.", "kind")
        for old in current:
            if old["status"] == "pending":
                await _drop_pending(request, ws, job_id, old)

    asset_id = uuid.uuid4()
    path = storage.object_path(ws, job_id, asset_id, ext)
    row: dict[str, Any] = {
        "id": str(asset_id),
        "workspace_id": str(ws),
        "job_id": str(job_id),
        "kind": body.kind,
        "storage_path": path,
        "mime": body.mime,
        "size_bytes": body.size_bytes,
        "status": "pending",
        "created_by": str(user.user_id),
    }
    if body.rights is not None:
        row["rights"] = body.rights.model_dump(exclude_none=True)
    resp = await _send(
        request,
        "POST",
        "production_assets",
        params={"select": "id,kind,status"},
        json=row,
        headers={"Prefer": "return=representation"},
    )
    conflict = _write_conflict(resp)
    if conflict is not None:
        raise conflict  # 동시 업로드로 쇼핑 원본 상한을 넘김(000023 트리거)
    rows = _json_list(resp, "POST", "production_assets")
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
    job = await _get_job(request, ws, job_id, "id,status,failed_stage,format,kind")
    if not _upload_state_ok(asset["kind"], job):
        raise _state_conflict(job["status"])
    if asset["kind"] == "source_upload" and job.get("kind") != "shopping":
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
    conflict = _write_conflict(resp, "이미 업로드된 원본이 있습니다.")
    if conflict is not None:
        raise conflict  # 동시 complete 경합(일반 ready 2건째)·준비 시작 뒤 완료(000023 트리거)
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
    if job["source_kind"] == "url" and not (job["rights_confirmed"] and job.get("source_url")):
        # task-031 리뷰: URL 원본은 권리 확인 + URL이 있어야 준비 시작(DB check와 이중 방어)
        raise ApiError(
            400, "VALIDATION", "URL 원본은 사용 권한 확인이 필요합니다.", "rights_confirmed"
        )
    if job.get("kind") == "shopping" and shopping.has_banned(
        job["title"], job.get("brief"), job.get("comment_keyword")
    ):
        raise _banned()  # 원본 준비 시작도 금지 품목이면 막는다(PROD-01S)
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
    resp = await _send(
        request,
        "PATCH",
        "production_jobs",
        params={**params, "select": JOB_COLUMNS},
        json={
            "status": "preparing",
            "retry_count": job["retry_count"] + (1 if retry else 0),
            "failed_stage": None,
            "error_code": None,
            "claimed_by": None,
            "updated_at": datetime.now(UTC).isoformat(),
        },
        headers={"Prefer": "return=representation"},
    )
    conflict = _write_conflict(resp)
    if conflict is not None:
        # 리뷰 반영 3: 확인 뒤 원본이 지워진 경합(000023 production_jobs_prepare_source)
        raise ApiError(409, "CONFLICT", "업로드된 원본이 없습니다.", "source_upload")
    rows = _json_list(resp, "PATCH", "production_jobs")
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
    lang: Literal["ko", "ja"] = "ko",
    user: CurrentUser = Depends(get_current_user),
) -> RevisionEnvelope:
    ws = user.workspace_id
    job = await _get_job(request, ws, job_id, "id,current_revision_id,current_ja_revision_id")
    current = job.get(_LANG_REVISION[lang])
    params = {
        "select": REVISION_COLUMNS,
        "job_id": f"eq.{job_id}",
        "workspace_id": f"eq.{ws}",
        "lang": f"eq.{lang}",
    }
    if rev_no is not None:
        params["rev_no"] = f"eq.{rev_no}"
    elif current:
        params["id"] = f"eq.{current}"
    else:
        raise not_found()
    rows = await _rows(request, "GET", "edit_revisions", params=params)
    if not rows:
        raise not_found()
    rev = rows[0]
    if lang == "ja":  # J8: 원본 변경은 읽는 시점에 계산해 합친다(저장하지 않음)
        rev = _with_errors(rev, await _source_errors(request, ws, job, rev))
    return RevisionEnvelope(revision=RevisionOut.model_validate(rev))


@router.put("/{job_id}/revision", response_model=RevisionEnvelope)
async def put_revision(
    job_id: uuid.UUID,
    body: RevisionPutIn,
    request: Request,
    lang: Literal["ko", "ja"] = "ko",
    user: CurrentUser = Depends(get_current_user),
) -> RevisionEnvelope | JSONResponse:
    ws = user.workspace_id
    job = await _get_job(
        request,
        ws,
        job_id,
        "id,status,failed_stage,format,lang,source_start_sec,segment_len_sec,preset_version,"
        "source_meta,current_revision_id,kind,vertical,brief,current_ja_revision_id",
    )
    if lang == "ja":
        return await _put_ja(request, ws, job, body, user)
    # D3: review·inspect·failed(audio·render)만, 리비전 없으면 409
    editable = job["status"] in ("review", "inspect") or (
        job["status"] == "failed" and job.get("failed_stage") in ("audio", "render")
    )
    if not editable or not job.get("current_revision_id"):
        raise _state_conflict(job["status"])

    assets = await _shopping_assets(request, ws, job_id) if job["format"] == "shopping" else None
    validation = _validate(body.spec, job, await _source_duration(request, ws, job_id), assets)
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
            "p_base_updated_at": body.base_updated_at.isoformat(),
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


async def _put_ja(
    request: Request, ws: uuid.UUID, job: dict, body: RevisionPutIn, user: CurrentUser
) -> RevisionEnvelope | JSONResponse:
    """A-12 PUT(ja): J2 허용 조건 → ja 검증 → 편집 가드(J7, 400 저장 안 함) → save_ja_revision.
    job 상태는 바꾸지 않는다."""
    job_id = job["id"]
    await _ja_writable(request, ws, job)
    ja = await _revision_row(
        request, ws, job_id, job["current_ja_revision_id"], "ja", "id,rev_no,derived_from"
    )
    if ja is None:
        raise _state_conflict(job["status"])
    ko = await _revision_row(request, ws, job_id, ja.get("derived_from"), "ko", "id,spec")
    ko_spec = ko.get("spec") if ko else None
    assets = await _shopping_assets(request, ws, job_id) if job["format"] == "shopping" else None
    duration = await _source_duration(request, ws, job_id)
    validation = _validate_ja(body.spec, job, ko_spec, duration, assets)
    if _rejected(validation):
        return _validation_response("편집안 형식이 올바르지 않습니다.", validation)
    locked = translate.locked_errors(job["format"], body.spec, ko_spec)
    if locked:
        return _validation_response(
            "일본어판은 문구·음성만 고칠 수 있습니다.", {**validation, "errors": locked}
        )
    saved = await _rpc(
        request,
        "save_ja_revision",
        {
            "p_workspace": str(ws),
            "p_job": str(job_id),
            "p_user": str(user.user_id),
            "p_base_rev_no": body.base_rev_no,
            "p_base_updated_at": body.base_updated_at.isoformat(),
            "p_spec": body.spec,
            "p_validation": validation,
        },
        "base_rev_no",
    )
    logger.info(
        "일본어판 편집안 저장: job=%s rev=%s errors=%d",
        job_id,
        saved.get("rev_no"),
        len(validation["errors"]),
    )
    saved = _with_errors(saved, await _source_errors(request, ws, job, saved))
    return RevisionEnvelope(revision=RevisionOut.model_validate(saved))


async def _approve_ja(
    request: Request, ws: uuid.UUID, job_id: uuid.UUID, body: ApproveIn, user: CurrentUser
) -> ApprovedEnvelope | JSONResponse:
    """A-13(ja): J2 허용 조건 → 서버 재검증(ja 규칙·ko 녹음·편집 가드·원본 변경 J8) →
    approve_ja_revision(updated_at 일치). job 상태는 바꾸지 않는다."""
    job = await _get_job(
        request,
        ws,
        job_id,
        "id,status,format,lang,source_start_sec,segment_len_sec,preset_version,source_meta,"
        "current_revision_id,current_ja_revision_id,kind,vertical,brief",
    )
    await _ja_writable(request, ws, job)
    rev = await _revision_row(
        request,
        ws,
        job_id,
        job["current_ja_revision_id"],
        "ja",
        "id,rev_no,spec,approved_at,updated_at,derived_from",
    )
    if rev is None:
        raise _state_conflict(job["status"])
    if rev["rev_no"] != body.rev_no:
        raise _stale("rev_no")
    if rev["approved_at"] is not None:
        raise ApiError(409, "CONFLICT", "이미 승인된 리비전입니다.", "rev_no")
    ko = await _revision_row(request, ws, job_id, rev.get("derived_from"), "ko", "id,spec")
    ko_spec = ko.get("spec") if ko else None
    assets = await _shopping_assets(request, ws, job_id) if job["format"] == "shopping" else None
    validation = _validate_ja(
        rev["spec"], job, ko_spec, await _source_duration(request, ws, job_id), assets
    )
    if not any(e["code"].startswith("schema.") for e in validation["errors"]):
        validation["errors"] += translate.locked_errors(job["format"], rev["spec"], ko_spec)
    validation["errors"] += await _source_errors(request, ws, job, rev)
    if validation["errors"]:
        return _validation_response("편집안에 오류가 있어 승인할 수 없습니다.", validation)
    approved = await _rpc(
        request,
        "approve_ja_revision",
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
    logger.info("일본어판 편집안 승인: job=%s rev=%s", job_id, approved.get("rev_no"))
    return ApprovedEnvelope(revision=ApprovedRevisionOut.model_validate(approved))


# --- A-13 ----------------------------------------------------------------------


@router.post("/{job_id}/revision/approve", response_model=ApprovedEnvelope)
async def approve_revision(
    job_id: uuid.UUID,
    body: ApproveIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> ApprovedEnvelope | JSONResponse:
    ws = user.workspace_id
    if body.lang == "ja":
        return await _approve_ja(request, ws, job_id, body, user)
    job = await _get_job(
        request,
        ws,
        job_id,
        "id,status,format,lang,source_start_sec,segment_len_sec,preset_version,source_meta,"
        "current_revision_id,kind,vertical,brief",
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

    # 서버 재검증(저장된 validation을 믿지 않는다). 쇼핑은 이 작업 자산의 권리까지(task-043)
    assets = await _shopping_assets(request, ws, job_id) if job["format"] == "shopping" else None
    validation = _validate(rev["spec"], job, await _source_duration(request, ws, job_id), assets)
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


# --- P9 자산 삭제 -------------------------------------------------------------------


@router.delete("/{job_id}/assets/{asset_id}", status_code=204, response_class=Response)
async def delete_asset(
    job_id: uuid.UUID,
    asset_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """사용자 업로드 자산 삭제(객체+행). source_upload는 draft·failed(prepare)에서만,
    image·bgm·narration은 현재 리비전(ko·ja)이 참조하지 않을 때만(task-044 P9)."""
    ws = user.workspace_id
    asset = await _get_asset(request, ws, job_id, asset_id, "id,kind,status,storage_path")
    if asset["kind"] not in _DELETABLE:
        raise ApiError(409, "CONFLICT", "지울 수 없는 자산입니다.")
    job = await _get_job(
        request, ws, job_id, "id,status,failed_stage,current_revision_id,current_ja_revision_id"
    )
    if asset["kind"] == "source_upload":
        if not _is_prepare_state(job):
            raise _state_conflict(job["status"])
    else:
        rev_ids = [str(job[c]) for c in _LANG_REVISION.values() if job.get(c)]
        revs = []
        if rev_ids:
            revs = await _rows(
                request,
                "GET",
                "edit_revisions",
                params={
                    "select": "spec",
                    "id": f"in.({','.join(rev_ids)})",
                    "job_id": f"eq.{job_id}",
                    "workspace_id": f"eq.{ws}",
                },
            )
        if any(str(asset_id) in shopping.spec_asset_refs(r.get("spec")) for r in revs):
            raise ApiError(409, "CONFLICT", "편집안에서 쓰는 자산입니다.", "asset_id")
    resp = await _send(
        request,
        "DELETE",
        "production_assets",
        params={
            "id": f"eq.{asset_id}",
            "job_id": f"eq.{job_id}",
            "workspace_id": f"eq.{ws}",
            "select": "id",
        },
        headers={"Prefer": "return=representation"},
    )
    conflict = _write_conflict(resp)
    if conflict is not None:
        raise conflict  # 준비 시작과 경합(000023 삭제 가드)·파생 산출물 있음
    if not _json_list(resp, "DELETE", "production_assets"):
        raise not_found()
    # 행이 먼저 사라졌으니 객체 삭제 실패는 로그만(id)
    await delete_objects(request, [asset["storage_path"]], "삭제")
    logger.info("자산 삭제: job=%s asset=%s kind=%s", job_id, asset_id, asset["kind"])
    return Response(status_code=204)


# --- A-21 게시 문구 -------------------------------------------------------------------


@router.get("/{job_id}/publish-text", response_model=PublishTextOut)
async def publish_text(
    job_id: uuid.UUID,
    request: Request,
    response: Response,
    lang: Literal["ko", "ja"] = "ko",
    render_run_id: uuid.UUID | None = None,
    user: CurrentUser = Depends(get_current_user),
) -> PublishTextOut:
    """쇼핑만. job·워크스페이스·status done·lang이 맞는 run 기준, 제휴 링크는 응답에만(P8)."""
    ws = user.workspace_id
    job = await _get_job(request, ws, job_id, "id,kind,affiliates,comment_keyword")
    if job.get("kind") != "shopping":
        raise ApiError(400, "VALIDATION", "쇼핑 작업만 게시 문구를 만듭니다.", "kind")
    params = {
        "select": "id",
        "job_id": f"eq.{job_id}",
        "workspace_id": f"eq.{ws}",
        "status": "eq.done",
        "lang": f"eq.{lang}",
        "order": "finished_at.desc,created_at.desc",
        "limit": "1",
    }
    if render_run_id is not None:
        params["id"] = f"eq.{render_run_id}"
    found = await _rows(request, "GET", "render_runs", params=params)
    if not found:
        raise ApiError(409, "CONFLICT", "완료된 렌더가 없습니다.", "render_run_id")
    text = shopping.publish_text(lang, job.get("affiliates"), job.get("comment_keyword"))
    response.headers["Cache-Control"] = "no-store"
    logger.info("게시 문구 발급: job=%s run=%s lang=%s", job_id, found[0]["id"], lang)
    return PublishTextOut(
        text=PublishText.model_validate(text), render_run_id=found[0]["id"], lang=lang
    )
