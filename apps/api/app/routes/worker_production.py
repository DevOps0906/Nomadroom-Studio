"""제작 워커 API W-05~W-09. 근거: docs/04_API.md#제작-워커-api, tasks/task-023.md(E1~E9),
docs/adr/0003-production-render-worker.md.

인증은 워커 토큰(`get_current_worker`). 인가: task의 workspace_id = 토큰 워크스페이스(아니면 404),
claimed_by = 현재 워커·진행 중(아니면 409 — 다른 워커 task·종료). 워커는 task id·자산 ID만 보내고
경로·파일명은 서버가 만든다. 서명 URL·토큰·경로는 로그에 쓰지 않는다(응답에만).
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.auth.worker import CurrentWorker, get_current_worker
from app.errors import ApiError, db_error, not_found
from app.production import runs, shopping, storage
from app.production.validation_variety import validate_for_format
from app.routes.production_jobs import UPLOAD_MIME
from app.routes.profiles import _json_list, _send
from app.routes.worker import _touch_heartbeat

logger = logging.getLogger("nomadroom.worker_production")

router = APIRouter(prefix="/worker/v1/production", tags=["worker-production"])

TaskKind = Literal["prepare", "render"]
MAX_SHEETS = 200  # W-07 sheet ≤200(가정)
MAX_PENDING = MAX_SHEETS + 10  # E7: task당 pending 상한(sheet 수+10)
# P5: 쇼핑 prepare는 원본마다 source·analysis·sheet(≤200) — task당 pending ≤ 원본 수×(200+2)
PER_SOURCE = MAX_SHEETS + 2
MAX_FINISH_IDS = shopping.MAX_SOURCES * PER_SOURCE
_ID_CHUNK = 100  # 자산 id in.(...) 조회 한 번에 넣는 수(URL 길이)

# E7: kind → mime → 확장자(버킷 allowed_mime_types 안, 000015)
OUTPUT_MIME: dict[str, dict[str, str]] = {
    "source": {"video/mp4": "mp4"},
    "analysis": {"application/json": "json"},
    "sheet": {"image/jpeg": "jpg"},
    "output_mp4": {"video/mp4": "mp4"},
    "report": {"application/json": "json"},
    "hook_audio": UPLOAD_MIME["hook_audio"],
}
# 리뷰 반영 5: kind별 크기 상한(영상·음성은 버킷 상한 500MB)
MB = 1024 * 1024
OUTPUT_MAX_BYTES: dict[str, int] = {
    "source": storage.MAX_UPLOAD_BYTES,
    "output_mp4": storage.MAX_UPLOAD_BYTES,
    "hook_audio": storage.MAX_UPLOAD_BYTES,
    "sheet": 5 * MB,
    "analysis": 50 * MB,
    "report": 50 * MB,
}
PREPARE_KINDS = ("source", "analysis", "sheet")
RENDER_KINDS = ("output_mp4", "report", "hook_audio")

# E6: kind별 실패 단계·코드(worker_offline은 서버 생성이라 받지 않는다)
PrepareCode = Literal[
    "range_invalid", "input_invalid", "url_unavailable", "download_failed", "unknown"
]
RenderCode = Literal[
    "hook_too_long", "text_too_long", "tts_failed", "audio_missing", "render_failed", "unknown"
]
PREPARE_CODES = set(PrepareCode.__args__)  # type: ignore[attr-defined]
RENDER_CODES = set(RenderCode.__args__)  # type: ignore[attr-defined]
ERROR_STAGES = {"prepare": {"prepare"}, "render": {"audio", "render"}}


# --- 입출력 모델 -------------------------------------------------------------------


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskOut(BaseModel):
    kind: TaskKind
    id: uuid.UUID
    job_id: uuid.UUID
    job_kind: Literal["general", "shopping"]
    format: str
    preset_version: str
    lang: str | None = None
    source_start_sec: float | None = None
    segment_len_sec: float | None = None
    source_kind: str | None = None
    source_url: str | None = None  # task-031: rights_confirmed URL 작업의 prepare만(000019)
    spec: dict[str, Any] | None = None


class ClaimOut(BaseModel):
    task: TaskOut


class ClaimIn(_In):
    """task-045 R4: 워커가 처리할 수 있는 형식. shopping을 알린 워커에게만 쇼핑 task를 새로 준다."""

    capabilities: Annotated[list[Literal["shopping"]], Field(max_length=5)] = []


class InputOut(BaseModel):
    asset_id: uuid.UUID
    kind: str
    download_url: str
    expires_at: datetime
    # task-045 R5: 쇼핑 render의 파생 source는 부모 source_upload(컷이 가리키는 id)를 함께 준다
    parent_asset_id: uuid.UUID | None = None


class InputsOut(BaseModel):
    inputs: list[InputOut]


class OutputItemIn(_In):
    kind: Literal["source", "analysis", "sheet", "output_mp4", "report", "hook_audio"]
    size_bytes: Annotated[int, Field(strict=True, ge=1, le=storage.MAX_UPLOAD_BYTES)]
    mime: Annotated[str, StringConstraints(max_length=100)]
    duration_sec: Annotated[float, Field(ge=0, le=86_400, allow_inf_nan=False)] | None = None
    # P1 계보: prepare 산출물의 원본(source_upload). 쇼핑 필수, 일반 업로드 작업은 생략 시 그 원본
    parent_asset_id: uuid.UUID | None = None


class OutputsIn(_In):
    items: Annotated[list[OutputItemIn], Field(min_length=1, max_length=MAX_PENDING)]


class OutputOut(BaseModel):
    asset_id: uuid.UUID
    kind: str
    upload_url: str
    expires_at: datetime


class OutputsOut(BaseModel):
    items: list[OutputOut]


class ProgressIn(_In):
    stage: Literal["download", "extract", "sheet", "audio", "compose", "encode", "upload"]
    progress_pct: Annotated[int, Field(strict=True, ge=0, le=100)]


class ProgressOut(BaseModel):
    ok: bool


class PrepareMeta(_In):
    duration_sec: Annotated[float, Field(ge=0, le=86_400, allow_inf_nan=False)]
    width: Annotated[int, Field(strict=True, ge=1, le=10_000)]
    height: Annotated[int, Field(strict=True, ge=1, le=10_000)]
    has_audio: bool


class FinishIn(_In):
    status: Literal["done", "failed"]
    asset_ids: Annotated[list[uuid.UUID], Field(max_length=MAX_FINISH_IDS)] = []
    meta: PrepareMeta | None = None
    error_stage: Literal["prepare", "audio", "render"] | None = None
    error_code: Annotated[str, StringConstraints(max_length=40)] | None = None


class FinishTaskOut(BaseModel):
    status: Literal["done", "failed"]


class FinishOut(BaseModel):
    task: FinishTaskOut


# --- 헬퍼 ------------------------------------------------------------------------


def _bad(message: str, field: str) -> ApiError:
    return ApiError(400, "VALIDATION", message, field)


def _conflict(message: str) -> ApiError:
    return ApiError(409, "CONFLICT", message)


async def _rows(request: Request, method: str, table: str, **kwargs: Any) -> list:
    return _json_list(await _send(request, method, table, **kwargs), method, table)


async def _one(request: Request, table: str, params: dict[str, str]) -> dict | None:
    rows = await _rows(request, "GET", table, params=params)
    return rows[0] if rows else None


async def _task(
    request: Request, worker: CurrentWorker, kind: TaskKind, task_id: uuid.UUID
) -> tuple[dict, dict | None]:
    """수령한 진행 중 task의 (job, run). 타 워크스페이스·없음 404, 다른 워커·종료 409."""
    ws = str(worker.workspace_id)
    run: dict | None = None
    if kind == "render":
        run = await _one(
            request,
            "render_runs",
            {
                "select": "id,job_id,status,claimed_by,lang,revision_id",
                "id": f"eq.{task_id}",
                "workspace_id": f"eq.{ws}",
            },
        )
        if run is None:
            raise not_found()
        owner, active = run.get("claimed_by"), run["status"] == "running"
        job_id = run["job_id"]
    else:
        job_id = str(task_id)
    job = await _one(
        request,
        "production_jobs",
        {
            "select": "id,status,format,lang,claimed_by,kind,source_kind",
            "id": f"eq.{job_id}",
            "workspace_id": f"eq.{ws}",
        },
    )
    if job is None:
        raise not_found()
    if kind == "prepare":
        owner, active = job.get("claimed_by"), job["status"] == "preparing"
    if str(owner) != str(worker.worker_id):
        raise _conflict("다른 워커의 작업입니다.")
    if not active:
        raise _conflict("종료된 작업입니다.")
    return job, run


def _scope(job: dict, run: dict | None, ws: uuid.UUID) -> dict[str, str]:
    """이 task의 산출물 범위: 같은 job, render는 render_run_id=run, prepare는 null."""
    return {
        "job_id": f"eq.{job['id']}",
        "workspace_id": f"eq.{ws}",
        "render_run_id": f"eq.{run['id']}" if run else "is.null",
    }


def _allowed_kinds(kind: TaskKind, job: dict) -> tuple[str, ...]:
    if kind == "prepare":
        return PREPARE_KINDS
    # hook_audio 산출물은 category만(variety는 훅 음성 없음)
    return RENDER_KINDS if job["format"] == "category" else RENDER_KINDS[:2]


def _http(request: Request) -> Any:
    return request.app.state.http


def _is_shopping(job: dict) -> bool:
    return job.get("kind") == "shopping"


async def _ready_uploads(request: Request, job: dict, ws: uuid.UUID) -> list[dict]:
    """prepare 입력·계보 부모: 이 작업의 ready source_upload(오래된 순)."""
    return await _rows(
        request,
        "GET",
        "production_assets",
        params={
            "select": "id,kind,storage_path",
            "job_id": f"eq.{job['id']}",
            "workspace_id": f"eq.{ws}",
            "kind": "eq.source_upload",
            "status": "eq.ready",
            "order": "created_at.asc,id.asc",
        },
    )


async def _assets_by_ids(request: Request, params: dict[str, str], ids: list) -> list[dict]:
    """id 목록을 나눠 조회한다(쇼핑 finish는 수천 건일 수 있다)."""
    rows: list[dict] = []
    for i in range(0, len(ids), _ID_CHUNK):
        chunk = ids[i : i + _ID_CHUNK]
        rows += await _rows(
            request,
            "GET",
            "production_assets",
            params={**params, "id": f"in.({','.join(str(x) for x in chunk)})"},
        )
    return rows


def spec_refs(spec: Any) -> dict[str, list[str]]:
    """쇼핑 편집안이 참조하는 자산 id(종류별, 순서 유지). 문자열이 아닌 값은 버린다."""
    out: dict[str, list[str]] = {"cuts": [], "bgm": [], "narration": []}
    if not isinstance(spec, dict):
        return out
    cuts = spec.get("cuts")
    for c in cuts if isinstance(cuts, list) else []:
        if isinstance(c, dict) and isinstance(c.get("source_asset_id"), str):
            out["cuts"].append(c["source_asset_id"])
    if isinstance(spec.get("bgm_asset_id"), str):
        out["bgm"].append(spec["bgm_asset_id"])
    voice = spec.get("voice")
    ids = voice.get("narration_asset_ids") if isinstance(voice, dict) else None
    out["narration"] = [i for i in (ids if isinstance(ids, list) else []) if isinstance(i, str)]
    return out


def _uuid_or_none(v: str) -> str | None:
    try:
        return str(uuid.UUID(v))
    except ValueError:
        return None


async def shopping_ref_assets(
    request: Request, ws: uuid.UUID, job_id: Any, spec: Any
) -> tuple[list[dict], bool]:
    """R3·R5: 편집안이 참조하는 이 작업 소유·ready·사용자 자산과 컷 원본(source_upload)의 파생
    source. 반환 (서명할 행, 참조 전부 충족 여부).
    source_upload 자체는 넣지 않는다(디코드 안 함)."""
    refs = spec_refs(spec)
    wanted = {
        "cuts": ("source_upload", "source", "image"),
        "bgm": ("bgm",),
        "narration": ("narration",),
    }
    all_ids = {i for ids in refs.values() for i in ids}
    ids = [u for u in (_uuid_or_none(i) for i in all_ids) if u]
    base = {
        "select": "id,kind,storage_path,parent_asset_id,created_at",
        "job_id": f"eq.{job_id}",
        "workspace_id": f"eq.{ws}",
        "status": "eq.ready",
        "render_run_id": "is.null",
    }
    rows = {str(r["id"]): r for r in await _assets_by_ids(request, base, ids)} if ids else {}
    ok = len(ids) == len(all_ids)
    for group, kinds in wanted.items():
        ok = ok and all(rows.get(i, {}).get("kind") in kinds for i in refs[group])
    uploads = [i for i in refs["cuts"] if rows.get(i, {}).get("kind") == "source_upload"]
    children: dict[str, dict] = {}
    if uploads:
        derived = await _rows(
            request,
            "GET",
            "production_assets",
            params={
                **base,
                "kind": "eq.source",
                "parent_asset_id": f"in.({','.join(sorted(set(uploads)))})",
                "order": "created_at.desc,id.desc",
            },
        )
        for r in derived:
            children.setdefault(str(r["parent_asset_id"]), r)
        ok = ok and all(u in children for u in uploads)
    out = [r for r in rows.values() if r["kind"] != "source_upload"]
    out += list(children.values())
    out.sort(key=lambda r: str(r["id"]))
    return out, ok


async def _shopping_render_inputs(
    request: Request, worker: CurrentWorker, job: dict, run: dict | None
) -> list[InputOut]:
    """R3: 이 run의 승인 리비전 spec이 참조하는 자산만 서명한다(없는 참조는 빼고 워커가 실패)."""
    rev = await _one(
        request,
        "edit_revisions",
        {
            "select": "spec",
            "id": f"eq.{run['revision_id']}" if run else "is.null",
            "job_id": f"eq.{job['id']}",
            "workspace_id": f"eq.{worker.workspace_id}",
        },
    )
    rows, _ = await shopping_ref_assets(
        request, worker.workspace_id, job["id"], rev.get("spec") if rev else None
    )
    settings = request.app.state.settings
    inputs = []
    for r in rows:
        url, exp = await storage.sign_download(_http(request), settings, r["storage_path"])
        inputs.append(
            InputOut(
                asset_id=r["id"],
                kind=r["kind"],
                download_url=url,
                expires_at=exp,
                parent_asset_id=r.get("parent_asset_id") if r["kind"] == "source" else None,
            )
        )
    return inputs


# --- W-05 수령 --------------------------------------------------------------------


@router.post("/claim", response_model=ClaimOut, responses={204: {"description": "작업 없음"}})
async def claim_task(
    request: Request,
    body: ClaimIn | None = None,
    worker: CurrentWorker = Depends(get_current_worker),
) -> ClaimOut | Response:
    await _touch_heartbeat(request, worker, None)  # E4: current_job_id는 jobs FK라 null
    await runs.expire_offline(request, worker.workspace_id)  # E3
    task = await runs.rpc(
        request,
        "claim_production_task",
        {
            "p_workspace": str(worker.workspace_id),
            "p_worker": str(worker.worker_id),
            "p_formats": sorted(set(body.capabilities)) if body else [],
        },
    )
    if task is None:
        return Response(status_code=204)
    if not isinstance(task, dict):
        raise db_error()
    out = ClaimOut(task=TaskOut.model_validate(task))
    logger.info("제작 task 수령: kind=%s id=%s", out.task.kind, out.task.id)
    return out


# --- W-06 입력 --------------------------------------------------------------------


@router.get("/{kind}/{task_id}/inputs", response_model=InputsOut)
async def task_inputs(
    kind: TaskKind,
    task_id: uuid.UUID,
    request: Request,
    response: Response,
    worker: CurrentWorker = Depends(get_current_worker),
) -> InputsOut:
    job, run = await _task(request, worker, kind, task_id)
    settings = request.app.state.settings
    if kind == "prepare" and _is_shopping(job):
        # 쇼핑: ready 원본 전부(원본별로 source·analysis·sheet를 W-07로 올린다)
        inputs = []
        for r in await _ready_uploads(request, job, worker.workspace_id):
            url, exp = await storage.sign_download(_http(request), settings, r["storage_path"])
            inputs.append(
                InputOut(asset_id=r["id"], kind=r["kind"], download_url=url, expires_at=exp)
            )
        response.headers["Cache-Control"] = "no-store"
        logger.info("제작 입력 서명 발급: kind=%s id=%s n=%d", kind, task_id, len(inputs))
        return InputsOut(inputs=inputs)
    if kind == "render" and _is_shopping(job):
        inputs = await _shopping_render_inputs(request, worker, job, run)
        response.headers["Cache-Control"] = "no-store"
        logger.info("제작 입력 서명 발급: kind=%s id=%s n=%d", kind, task_id, len(inputs))
        return InputsOut(inputs=inputs)
    if kind == "prepare":
        wanted: tuple[str, ...] = ("source_upload",)
    else:
        # E9: 최신 ready source·analysis + render_run_id null인 최신 hook_audio(category만)
        wanted = (
            ("source", "analysis", "hook_audio")
            if job["format"] == "category"
            else (
                "source",
                "analysis",
            )
        )
    rows = await _rows(
        request,
        "GET",
        "production_assets",
        params={
            "select": "id,kind,storage_path",
            "job_id": f"eq.{job['id']}",
            "workspace_id": f"eq.{worker.workspace_id}",
            "status": "eq.ready",
            "render_run_id": "is.null",
            "kind": f"in.({','.join(wanted)})",
            "order": "created_at.desc,id.desc",
        },
    )
    latest: dict[str, dict] = {}
    for r in rows:
        latest.setdefault(r["kind"], r)
    inputs = []
    for k in wanted:
        if k in latest:
            url, exp = await storage.sign_download(
                _http(request), settings, latest[k]["storage_path"]
            )
            inputs.append(
                InputOut(asset_id=latest[k]["id"], kind=k, download_url=url, expires_at=exp)
            )
    response.headers["Cache-Control"] = "no-store"
    logger.info("제작 입력 서명 발급: kind=%s id=%s n=%d", kind, task_id, len(inputs))
    return InputsOut(inputs=inputs)


# --- W-07 산출물 업로드 -----------------------------------------------------------


async def _parents(
    request: Request, worker: CurrentWorker, kind: TaskKind, job: dict, body: OutputsIn
) -> list[str | None]:
    """P1: 항목별 부모 source_upload id. render는 없음, 쇼핑 prepare는 필수,
    일반 업로드 prepare는 생략 시 그 작업의 ready 원본, URL 작업은 없음."""
    sent = [str(it.parent_asset_id) if it.parent_asset_id else None for it in body.items]
    if kind == "render" or job.get("source_kind") == "url":
        for i, p in enumerate(sent):
            if p is not None:
                raise _bad("이 산출물에는 원본을 지정하지 않습니다.", f"items.{i}.parent_asset_id")
        return sent
    ready = [str(r["id"]) for r in await _ready_uploads(request, job, worker.workspace_id)]
    out: list[str | None] = []
    for i, p in enumerate(sent):
        if p is None and not _is_shopping(job) and len(ready) == 1:
            p = ready[0]
        if p is None or p not in ready:
            raise _bad("이 작업의 준비된 원본이 아닙니다.", f"items.{i}.parent_asset_id")
        out.append(p)
    return out


@router.post("/{kind}/{task_id}/outputs", response_model=OutputsOut)
async def task_outputs(
    kind: TaskKind,
    task_id: uuid.UUID,
    body: OutputsIn,
    request: Request,
    response: Response,
    worker: CurrentWorker = Depends(get_current_worker),
) -> OutputsOut:
    job, run = await _task(request, worker, kind, task_id)
    allowed = _allowed_kinds(kind, job)
    exts: list[str] = []
    for i, item in enumerate(body.items):
        if item.kind not in allowed:
            raise _bad("허용되지 않은 산출물 종류입니다.", f"items.{i}.kind")
        if item.size_bytes > OUTPUT_MAX_BYTES[item.kind]:
            raise _bad("파일이 너무 큽니다.", f"items.{i}.size_bytes")
        ext = OUTPUT_MIME[item.kind].get(item.mime)
        if ext is None:
            raise _bad("허용되지 않은 파일 형식입니다.", f"items.{i}.mime")
        exts.append(ext)

    ws = worker.workspace_id
    parents = await _parents(request, worker, kind, job, body)
    pending = await _rows(
        request,
        "GET",
        "production_assets",
        params={
            "select": "id,kind,parent_asset_id",
            **_scope(job, run, ws),
            "status": "eq.pending",
        },
    )
    if kind == "prepare" and _is_shopping(job):
        # P5: 상한은 원본 수×(sheet 200+2), sheet는 원본마다 200
        n_sources = len({p for p in parents if p} | {str(a["parent_asset_id"]) for a in pending})
        if len(pending) + len(body.items) > max(n_sources, 1) * PER_SOURCE:
            raise _bad("올릴 산출물이 너무 많습니다.", "items")
        sheets: dict[str, int] = {}
        pairs = [(a["kind"], a.get("parent_asset_id")) for a in pending]
        pairs += [(it.kind, par) for it, par in zip(body.items, parents, strict=True)]
        for k, par in pairs:
            if k == "sheet":
                sheets[str(par)] = sheets.get(str(par), 0) + 1
        if any(n > MAX_SHEETS for n in sheets.values()):
            raise _bad("시트 이미지가 너무 많습니다.", "items")
    else:
        if len(pending) + len(body.items) > MAX_PENDING:
            raise _bad("올릴 산출물이 너무 많습니다.", "items")
        n_sheets = sum(1 for a in pending if a["kind"] == "sheet") + sum(
            1 for it in body.items if it.kind == "sheet"
        )
        if n_sheets > MAX_SHEETS:
            raise _bad("시트 이미지가 너무 많습니다.", "items")

    new_rows = []
    for item, ext, parent in zip(body.items, exts, parents, strict=True):
        asset_id = uuid.uuid4()
        new_rows.append(
            {
                "id": str(asset_id),
                "workspace_id": str(ws),
                "job_id": str(job["id"]),
                "kind": item.kind,
                "storage_path": storage.object_path(ws, job["id"], asset_id, ext),
                "mime": item.mime,
                "size_bytes": item.size_bytes,
                "duration_sec": item.duration_sec,
                "status": "pending",
                "render_run_id": str(run["id"]) if run else None,
                "parent_asset_id": parent,
                "created_by": str(worker.worker_id),
            }
        )
    inserted = await _rows(
        request,
        "POST",
        "production_assets",
        params={"select": "id"},
        json=new_rows,
        headers={"Prefer": "return=representation"},
    )
    if len(inserted) != len(new_rows):
        raise db_error()
    settings = request.app.state.settings
    items = []
    for row in new_rows:
        url, exp = await storage.sign_upload(_http(request), settings, row["storage_path"])
        items.append(
            OutputOut(asset_id=row["id"], kind=row["kind"], upload_url=url, expires_at=exp)
        )
    response.headers["Cache-Control"] = "no-store"
    logger.info("제작 산출물 서명 발급: kind=%s id=%s n=%d", kind, task_id, len(items))
    return OutputsOut(items=items)


# --- W-08 진행 --------------------------------------------------------------------


@router.post("/{kind}/{task_id}/progress", response_model=ProgressOut)
async def task_progress(
    kind: TaskKind,
    task_id: uuid.UUID,
    body: ProgressIn,
    request: Request,
    worker: CurrentWorker = Depends(get_current_worker),
) -> ProgressOut:
    await _touch_heartbeat(request, worker, None)  # E4
    await runs.expire_offline(request, worker.workspace_id)  # E3: 3분 넘은 보고는 종료로 본다
    job, run = await _task(request, worker, kind, task_id)
    now = datetime.now(UTC).isoformat()
    owned = {"workspace_id": f"eq.{worker.workspace_id}", "claimed_by": f"eq.{worker.worker_id}"}
    if run is not None:
        table, params = "render_runs", {"id": f"eq.{run['id']}", "status": "eq.running", **owned}
        data: dict[str, Any] = {
            "progress_pct": body.progress_pct,
            "progress_stage": body.stage,
            "updated_at": now,
        }
    else:
        table, params = (
            "production_jobs",
            {"id": f"eq.{job['id']}", "status": "eq.preparing", **owned},
        )
        data = {"updated_at": now}
    rows = await _rows(
        request,
        "PATCH",
        table,
        params={**params, "select": "id"},
        json=data,
        headers={"Prefer": "return=representation"},
    )
    if not rows:
        raise _conflict("종료된 작업입니다.")
    return ProgressOut(ok=True)


# --- W-09 완료·실패 ---------------------------------------------------------------


def _check_finish(kind: TaskKind, job: dict, body: FinishIn) -> None:
    """E6: 상태별 필수·금지 필드와 kind별 단계·코드."""
    if body.status == "done":
        if body.error_stage is not None or body.error_code is not None:
            raise _bad("완료에는 실패 사유를 보내지 않습니다.", "error_code")
        if not body.asset_ids:
            raise _bad("필수 산출물이 없습니다.", "asset_ids")
        if len(set(body.asset_ids)) != len(body.asset_ids):
            raise _bad("산출물 ID가 중복되었습니다.", "asset_ids")
        if body.meta is not None and kind != "prepare":
            raise _bad("meta는 준비 작업에만 보냅니다.", "meta")
        if body.meta is None and kind == "prepare":
            raise _bad("준비 완료에는 meta가 필요합니다.", "meta")  # 리뷰 반영 2
        return
    if body.asset_ids or body.meta is not None:
        raise _bad("실패에는 산출물을 보내지 않습니다.", "asset_ids")
    if body.error_stage not in ERROR_STAGES[kind]:
        raise _bad("실패 단계가 올바르지 않습니다.", "error_stage")
    codes = PREPARE_CODES if kind == "prepare" else RENDER_CODES
    if body.error_code not in codes:
        raise _bad("실패 코드가 올바르지 않습니다.", "error_code")
    if body.error_code == "hook_too_long" and job["format"] != "category":
        raise _bad("이 형식은 훅 음성을 쓰지 않습니다.", "error_code")


async def _verify_outputs(
    request: Request, worker: CurrentWorker, kind: TaskKind, job: dict, run: dict | None, ids: list
) -> None:
    """E6 목록 자산 확인 + Storage 실제 크기 = 선언 크기(없거나 다르면 400)."""
    rows = await _assets_by_ids(
        request,
        {
            "select": "id,kind,status,storage_path,size_bytes,created_by,render_run_id,"
            "parent_asset_id",
            **_scope(job, run, worker.workspace_id),
        },
        ids,
    )
    allowed = _allowed_kinds(kind, job)
    if len(rows) != len(ids) or any(
        r["status"] != "pending"
        or r["kind"] not in allowed
        or str(r.get("created_by")) != str(worker.worker_id)
        for r in rows
    ):
        raise _bad("산출물 목록이 올바르지 않습니다.", "asset_ids")
    kinds = [r["kind"] for r in rows]
    if kind == "prepare" and _is_shopping(job):
        # P3: ready 원본마다 source·analysis 정확히 1건·sheet 1건 이상, 모든 산출물은 그 원본의 것
        ready = {str(r["id"]) for r in await _ready_uploads(request, job, worker.workspace_id)}
        groups: dict[str, list[str]] = {u: [] for u in ready}
        for r in rows:
            parent = str(r.get("parent_asset_id"))
            if parent not in groups:
                raise _bad("필수 산출물이 없습니다.", "asset_ids")
            groups[parent].append(r["kind"])
        missing = not groups or any(
            g.count("source") != 1 or g.count("analysis") != 1 or "sheet" not in g
            for g in groups.values()
        )
    elif kind == "prepare":
        # 리뷰 반영 1: source·analysis 정확히 1건, sheet 1건 이상
        missing = kinds.count("source") != 1 or kinds.count("analysis") != 1 or "sheet" not in kinds
    else:
        missing = kinds.count("output_mp4") != 1 or kinds.count("report") != 1
        if kinds.count("hook_audio") > 1:
            raise _bad("산출물 목록이 올바르지 않습니다.", "asset_ids")
    if missing:
        raise _bad("필수 산출물이 없습니다.", "asset_ids")
    settings = request.app.state.settings
    for r in rows:
        size = await storage.object_size(_http(request), settings, r["storage_path"])
        if size is None or size != r.get("size_bytes"):
            raise _bad("업로드된 파일이 없거나 크기가 다릅니다.", "asset_ids")


@router.post("/{kind}/{task_id}/finish", response_model=FinishOut)
async def task_finish(
    kind: TaskKind,
    task_id: uuid.UUID,
    body: FinishIn,
    request: Request,
    worker: CurrentWorker = Depends(get_current_worker),
) -> FinishOut:
    job, run = await _task(request, worker, kind, task_id)
    _check_finish(kind, job, body)
    spec: dict | None = None
    validation: dict | None = None
    if body.status == "done":
        await _verify_outputs(request, worker, kind, job, run, body.asset_ids)
        if kind == "prepare":
            # 첫 편집안 리비전(빈 편집안 + 서버 검증 결과, A-12로 채운다)
            # format별 검증(task-035 V4). 빈 편집안이라 스키마 오류에서 멈추므로 구간 길이는 생략
            spec = {}
            validation = validate_for_format(
                job["format"],
                spec,
                source_duration=body.meta.duration_sec if body.meta else None,
                source_size=(body.meta.width, body.meta.height) if body.meta else None,
                job_lang=job.get("lang"),
                assets={},  # 빈 편집안이라 스키마 오류에서 멈춘다(쇼핑 assets.required 회피)
            )
    result = await runs.rpc(
        request,
        "finish_production_task",
        {
            "p_workspace": str(worker.workspace_id),
            "p_worker": str(worker.worker_id),
            "p_kind": kind,
            "p_task": str(task_id),
            "p_status": body.status,
            "p_asset_ids": [str(i) for i in body.asset_ids],
            "p_meta": body.meta.model_dump() if body.meta else None,
            "p_error_stage": body.error_stage,
            "p_error_code": body.error_code,
            "p_spec": spec,
            "p_validation": validation,
        },
        "asset_ids",
    )
    if not isinstance(result, dict):
        raise db_error()
    await runs.delete_objects(request, result.get("deleted_paths"), "종료")
    logger.info(
        "제작 task 종료: kind=%s id=%s status=%s code=%s",
        kind,
        task_id,
        body.status,
        body.error_code,
    )
    return FinishOut(task=FinishTaskOut(status=body.status))
