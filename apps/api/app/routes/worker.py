"""워커 API W-01~W-04. 근거: docs/04_API.md#워커 API, tasks/task-007.md#구현 결정.

인증은 워커 토큰(`get_current_worker`). 인가: job.workspace_id = 토큰 워크스페이스 그리고
claimed_by = 현재 워커(W-02~04). 아니면 404(존재 노출 방지).
워커 입력은 신뢰하지 않는다: 형식 검증, 제목·채널·라이선스·썸네일은 YouTube 값으로 덮어쓴다.
오류 응답·로그에 토큰·쿠키·경로·입력 원문을 넣지 않는다.
"""

import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.worker import CurrentWorker, get_current_worker, parse_token
from app.errors import ApiError, ErrorBody, db_error, unauthenticated
from app.jobs.state import (
    OFFLINE_ERROR,
    SEARCH_SOURCE,
    close_profile_runs,
    expire_offline_jobs,
)
from app.routes.profiles import _json_list, _send
from app.routes.verify_runs import _profile, quota_exceeded, youtube_error
from app.verdict.engine import Candidate, Observation, judge
from app.youtube.client import (
    VideoInfo,
    YouTubeQuotaExceeded,
    YouTubeUnavailable,
    videos_list,
)
from app.youtube.constants import BATCH_SIZE, DAILY_UNIT_LIMIT, MAX_CANDIDATES, VIDEOS_LIST_UNITS

logger = logging.getLogger("nomadroom.worker")

router = APIRouter(prefix="/worker/v1", tags=["worker"])

PREFIX = "/worker/"
MAX_BODY_BYTES = 1_000_000  # 워커 라우트 본문 상한 1MB
JOB_COLUMNS = "id,workspace_id,kind,status,profile_ids,params,stop_requested,claimed_by,error"
CLAIM_PROFILE_COLUMNS = "id,market,format,category,min_views,keywords,cc_only,include_broadcast"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
# 분류 문자열(genre·category): C0·DEL·C1, 폭 없는 문자, 줄·문단 구분, 방향 제어 거부
_UNSAFE = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200d\u2028-\u202e\u2066-\u2069\ufeff]")
THUMBNAIL_URL = "https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


# --- 본문 크기 제한(ASGI 미들웨어, main.py에서 등록) ----------------------------


class WorkerBodyLimit:
    """`/worker/` 경로 요청 본문이 1MB를 넘으면 413. Content-Length 없는 스트림도 센다."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(PREFIX):
            await self.app(scope, receive, send)
            return
        # 인증 전 버퍼링 방지: 토큰 형식이 아니면 본문을 읽기 전에 401(토큰 대조는 라우트에서)
        if not _bearer_format_ok(scope):
            await _send_error(send, 401, unauthenticated(), {b"www-authenticate": b"Bearer"})
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    too_large = int(value) > self.max_bytes
                except ValueError:
                    too_large = True
                if too_large:
                    await self._reject(send)
                    return
        # 본문을 상한까지 먼저 읽는다(넘으면 413). FastAPI 본문 파싱이 예외를 400으로 바꾸므로
        # 앱 안에서 끊지 않고 여기서 판단한 뒤 그대로 다시 넘긴다.
        chunks: list[bytes] = []
        received = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunk = message.get("body", b"")
            received += len(chunk)
            if received > self.max_bytes:
                await self._reject(send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(send: Send) -> None:
        await _send_error(send, 413, ApiError(413, "PAYLOAD_TOO_LARGE", "요청 본문이 너무 큽니다."))


def _bearer_format_ok(scope: Scope) -> bool:
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            scheme, _, token = value.decode("latin-1").partition(" ")
            return scheme.lower() == "bearer" and parse_token(token.strip()) is not None
    return False


async def _send_error(
    send: Send, status: int, err: ApiError, extra: dict[bytes, bytes] | None = None
) -> None:
    body = ErrorBody(code=err.code, message=err.message)
    data = body.model_dump_json(exclude_none=True).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(data)).encode()),
        *(extra or {}).items(),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": data})


# --- 입력 모델 -------------------------------------------------------------------


def _no_control(v: Any) -> Any:
    if isinstance(v, str) and _CONTROL.search(v):
        raise ValueError("제어 문자는 허용되지 않습니다")
    return v


Short = Annotated[str, StringConstraints(max_length=40)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def _check_control(cls, v: Any) -> Any:
        return _no_control(v)


class ChromeIn(_In):
    profile_id: uuid.UUID
    state: Literal["ready", "resize_needed", "login_needed", "error"]
    detail: (
        Literal["window_small", "login_required", "profile_locked", "network", "unknown"] | None
    ) = None


class HeartbeatIn(_In):
    job_id: uuid.UUID | None = None
    chrome: Annotated[list[ChromeIn], Field(max_length=20)] = []


class CandidateItemIn(_In):
    video_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{11}$")]
    title: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    thumbnail_url: Annotated[str, StringConstraints(max_length=300)] | None = None  # 사용 안 함
    genre: Short | None = None
    category: Short | None = None
    format: Literal["short", "long"] | None = None
    market: Literal["KR", "JP"]
    channel_id: Short | None = None
    channel_title: Annotated[str, StringConstraints(max_length=200)] | None = None

    @field_validator("genre", "category", mode="after")
    @classmethod
    def _check_unsafe(cls, v: str | None) -> str | None:
        if v is not None and _UNSAFE.search(v):
            raise ValueError("허용되지 않는 문자가 있습니다")
        return v


class CandidatesIn(_In):
    profile_id: uuid.UUID
    items: Annotated[list[CandidateItemIn], Field(min_length=1, max_length=MAX_CANDIDATES)]


FinishError = Literal["chrome_failed", "vidiq_changed", "network", "stopped_by_user", "unknown"]


class FinishIn(_In):
    status: Literal["done", "failed", "stopped"]
    error: FinishError | None = None


# --- 출력 모델 -------------------------------------------------------------------


class ClaimProfileOut(BaseModel):
    id: uuid.UUID
    market: str
    format: Literal["all", "short", "long"]
    category: str | None
    min_views: int
    keywords: list[str]
    cc_only: bool
    include_broadcast: bool


class ClaimJobOut(BaseModel):
    id: uuid.UUID
    kind: Literal["collect"]
    profiles: list[ClaimProfileOut]
    resume_from_profile_id: uuid.UUID | None = None
    limit: int


class ClaimOut(BaseModel):
    job: ClaimJobOut


class HeartbeatOut(BaseModel):
    stop_requested: bool


class CandidatesOut(BaseModel):
    accepted: int
    duplicates: int
    unavailable: int


class FinishJobOut(BaseModel):
    status: Literal["done", "failed", "stopped"]


class FinishOut(BaseModel):
    job: FinishJobOut


# --- 오류 ------------------------------------------------------------------------


def _conflict(message: str) -> ApiError:
    return ApiError(409, "CONFLICT", message)


def _job_not_running() -> ApiError:
    return _conflict("진행 중인 작업이 아닙니다.")


def _profile_not_in_job() -> ApiError:
    return ApiError(400, "VALIDATION", "작업에 속하지 않은 프로필입니다.", "profile_id")


# --- 헬퍼 ------------------------------------------------------------------------


def _ts(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


async def _owned_job(request: Request, worker: CurrentWorker, job_id: uuid.UUID) -> dict:
    """이 워커가 claim한 자기 워크스페이스 collect job. 아니면 404."""
    params = {
        "select": JOB_COLUMNS,
        "id": f"eq.{job_id}",
        "workspace_id": f"eq.{worker.workspace_id}",
        "kind": "eq.collect",
        "claimed_by": f"eq.{worker.worker_id}",
    }
    rows = _json_list(await _send(request, "GET", "jobs", params=params), "GET", "jobs")
    if len(rows) != 1:
        raise ApiError(404, "NOT_FOUND", "찾을 수 없습니다.")
    return rows[0]


async def _touch_heartbeat(
    request: Request, worker: CurrentWorker, job_id: str | None, chrome: dict | None = None
) -> None:
    body: dict[str, Any] = {
        "worker_id": str(worker.worker_id),
        "workspace_id": str(worker.workspace_id),
        "last_seen_at": _ts(datetime.now(UTC)),
        "current_job_id": job_id,
    }
    if chrome is not None:
        body["chrome"] = chrome
    resp = await _send(
        request,
        "POST",
        "worker_heartbeats",
        params={"on_conflict": "worker_id"},
        json=body,
        headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
    )
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: POST worker_heartbeats", resp.status_code)
        raise db_error()


def _claim_out(job: dict, profile_rows: list[dict]) -> ClaimOut:
    by_id = {str(r["id"]): r for r in profile_rows}
    ordered = [by_id[str(pid)] for pid in job.get("profile_ids") or [] if str(pid) in by_id]
    params = job.get("params") if isinstance(job.get("params"), dict) else {}
    resume = params.get("resume_from_profile_id")
    try:
        resume_id = uuid.UUID(str(resume)) if resume else None
    except ValueError:
        resume_id = None
    limit = params.get("limit")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 0 < limit <= MAX_CANDIDATES:
        limit = MAX_CANDIDATES
    return ClaimOut(
        job=ClaimJobOut(
            id=job["id"],
            kind="collect",
            profiles=[ClaimProfileOut.model_validate(r) for r in ordered],
            resume_from_profile_id=resume_id,
            limit=limit,
        )
    )


async def _profiles_of(request: Request, ws: uuid.UUID, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    params = {
        "select": CLAIM_PROFILE_COLUMNS,
        "workspace_id": f"eq.{ws}",
        "id": f"in.({','.join(ids)})",
    }
    return _json_list(await _send(request, "GET", "profiles", params=params), "GET", "profiles")


def _rpc_error_code(resp: Any) -> str | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    code = body.get("code") if isinstance(body, dict) else None
    return code if isinstance(code, str) else None


# --- W-01 claim ------------------------------------------------------------------


@router.post(
    "/jobs/claim",
    response_model=ClaimOut,
    responses={204: {"description": "작업 없음"}},
)
async def claim_job(
    request: Request, worker: CurrentWorker = Depends(get_current_worker)
) -> ClaimOut | Response:
    ws = worker.workspace_id
    await expire_offline_jobs(request, ws)

    # 재시작 복구: 이 워커가 이미 running인 job이 있으면 그대로 돌려준다.
    own_params = {
        "select": JOB_COLUMNS,
        "workspace_id": f"eq.{ws}",
        "kind": "eq.collect",
        "status": "eq.running",
        "claimed_by": f"eq.{worker.worker_id}",
        "limit": "1",
    }
    rows = _json_list(await _send(request, "GET", "jobs", params=own_params), "GET", "jobs")
    if rows:
        job = rows[0]
    else:
        # 조건부 갱신 1회(원자적). 활성 collect job은 워크스페이스당 1건(유니크 인덱스).
        now = datetime.now(UTC)
        params = {
            "select": JOB_COLUMNS,
            "workspace_id": f"eq.{ws}",
            "kind": "eq.collect",
            "status": "in.(queued,retrying)",
            # 검색 수집 job(task-019)은 서버가 처리한다. 워커가 수령하지 않는다.
            "or": f"(params->>source.is.null,params->>source.neq.{SEARCH_SOURCE})",
        }
        body = {
            "status": "running",
            "claimed_by": str(worker.worker_id),
            "started_at": _ts(now),
            "error": None,  # 재시도(retrying) 전 실패 흔적을 비운다
            "finished_at": None,
        }
        resp = await _send(
            request,
            "PATCH",
            "jobs",
            params=params,
            json=body,
            headers={"Prefer": "return=representation"},
        )
        rows = _json_list(resp, "PATCH", "jobs")
        if not rows:
            await _touch_heartbeat(request, worker, None)
            return Response(status_code=204)
        job = rows[0]
    await _touch_heartbeat(request, worker, str(job["id"]))
    profiles = await _profiles_of(request, ws, [str(p) for p in job.get("profile_ids") or []])
    return _claim_out(job, profiles)


# --- W-02 heartbeat --------------------------------------------------------------


@router.post("/heartbeat", response_model=HeartbeatOut)
async def heartbeat(
    request: Request,
    body: HeartbeatIn | None = None,
    worker: CurrentWorker = Depends(get_current_worker),
) -> HeartbeatOut:
    body = body or HeartbeatIn()
    ws = worker.workspace_id
    job: dict | None = None
    if body.job_id is not None:
        job = await _owned_job(request, worker, body.job_id)
        if job["status"] != "running":
            raise _job_not_running()
    elif body.chrome:
        raise ApiError(400, "VALIDATION", "chrome에는 job_id가 필요합니다.", "job_id")

    chrome = {str(c.profile_id): {"state": c.state, "detail": c.detail} for c in body.chrome}
    if job is not None and body.chrome:
        profile_ids = [str(p) for p in job.get("profile_ids") or []]
        if any(pid not in profile_ids for pid in chrome):
            raise _profile_not_in_job()
        now = _ts(datetime.now(UTC))
        runs = [
            {
                "workspace_id": str(ws),
                "job_id": str(job["id"]),
                "profile_id": pid,
                "position": profile_ids.index(pid),
                "chrome_state": c["state"],
                "detail": c["detail"],
                "updated_at": now,
            }
            for pid, c in chrome.items()
        ]
        resp = await _send(
            request,
            "POST",
            "job_profile_runs",
            params={"on_conflict": "job_id,profile_id"},
            json=runs,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )
        if resp.status_code >= 400:
            logger.warning("데이터 저장소 오류 %s: POST job_profile_runs", resp.status_code)
            raise db_error()

    await _touch_heartbeat(
        request, worker, str(job["id"]) if job else None, chrome if body.chrome else None
    )
    await expire_offline_jobs(request, ws)
    return HeartbeatOut(stop_requested=bool(job and job.get("stop_requested")))


# --- W-03 후보 접수 --------------------------------------------------------------


def _collect_item(
    item: CandidateItemIn,
    info: VideoInfo,
    observed_at: datetime,
    profile: Any,
    broadcasters: set[str],
) -> dict:
    title = info.title or ""  # 빈 제목은 호출 전에 unavailable로 걸러진다
    is_broadcaster = info.channel_id is not None and info.channel_id in broadcasters
    candidate = Candidate(
        id=uuid.uuid4(),  # 판정 계산용 임시 id(후보 id는 RPC가 만든다)
        title=title,
        category=item.category,
        format=item.format,
        market=item.market,
        license_cc=info.license_cc,
        is_broadcaster=is_broadcaster,
    )
    curr = Observation(id=uuid.uuid4(), observed_at=observed_at, view_count=info.view_count)
    verdict = judge(profile, candidate, None, curr)
    return {
        "video_id": item.video_id,
        "title": title,
        "thumbnail_url": THUMBNAIL_URL.format(video_id=item.video_id),
        "genre": item.genre,
        "category": item.category,
        "format": item.format,
        "market": item.market,
        "channel_id": info.channel_id,
        "channel_title": info.channel_title,
        "license_cc": info.license_cc,
        "is_broadcaster": is_broadcaster,
        "observed_at": observed_at.isoformat(),
        "view_count": info.view_count,
        "status": verdict.status,
        "reason": verdict.reason,
    }


@router.post("/jobs/{job_id}/candidates", response_model=CandidatesOut)
async def post_candidates(
    job_id: uuid.UUID,
    body: CandidatesIn,
    request: Request,
    worker: CurrentWorker = Depends(get_current_worker),
) -> CandidatesOut:
    ws = worker.workspace_id
    job = await _owned_job(request, worker, job_id)
    if job["status"] != "running":
        raise _job_not_running()
    if job.get("stop_requested"):
        raise _conflict("중지 요청된 작업입니다.")
    if str(body.profile_id) not in [str(p) for p in job.get("profile_ids") or []]:
        raise _profile_not_in_job()

    # 요청 안 중복 제거(처음 것 유지)
    unique: dict[str, CandidateItemIn] = {}
    for item in body.items:
        unique.setdefault(item.video_id, item)
    duplicates = len(body.items) - len(unique)

    # 워크스페이스에 이미 있는 후보 제외
    existing_params = {
        "select": "video_id",
        "workspace_id": f"eq.{ws}",
        "video_id": f"in.({','.join(unique)})",
    }
    existing = {
        r["video_id"]
        for r in _json_list(
            await _send(request, "GET", "candidates", params=existing_params), "GET", "candidates"
        )
    }
    new = [i for vid, i in unique.items() if vid not in existing]
    duplicates += len(unique) - len(new)
    if not new:
        return CandidatesOut(accepted=0, duplicates=duplicates, unavailable=0)

    api_key = request.app.state.settings.youtube_api_key
    if api_key is None:
        logger.warning("YOUTUBE_API_KEY 미설정")
        raise youtube_error()

    prof_params = {
        "select": "id,market,format,category,min_views,max_growth_pct,keywords,cc_only,"
        "include_broadcast",
        "workspace_id": f"eq.{ws}",
        "id": f"eq.{body.profile_id}",
    }
    prof_rows = _json_list(
        await _send(request, "GET", "profiles", params=prof_params), "GET", "profiles"
    )
    if len(prof_rows) != 1:
        raise _profile_not_in_job()
    profile = _profile(prof_rows[0])
    bc_rows = _json_list(
        await _send(
            request,
            "GET",
            "broadcaster_channels",
            params={"select": "channel_id", "workspace_id": f"eq.{ws}"},
        ),
        "GET",
        "broadcaster_channels",
    )
    broadcasters = {r["channel_id"] for r in bc_rows}

    # job당 조회 상한(params.limit, 기본 200)을 할당량 예약 전에 원자적으로 예약한다.
    await _collect_rpc(
        request,
        "reserve_collect_lookup",
        {
            "p_workspace": str(ws),
            "p_job": str(job_id),
            "p_worker": str(worker.worker_id),
            "p_n": len(new),
        },
    )

    # YouTube 조회를 모두 마친 뒤 한 번에 반영한다(실패하면 아무것도 넣지 않음).
    infos: dict[str, VideoInfo] = {}
    for start in range(0, len(new), BATCH_SIZE):
        batch = [i.video_id for i in new[start : start + BATCH_SIZE]]
        reserved = await _rpc_json(
            request, "reserve_quota", {"p_units": VIDEOS_LIST_UNITS, "p_limit": DAILY_UNIT_LIMIT}
        )
        if reserved is not True:
            raise quota_exceeded()
        try:
            infos.update(await videos_list(request.app.state.http, api_key, batch))
        except YouTubeQuotaExceeded:
            raise quota_exceeded() from None
        except YouTubeUnavailable:
            raise youtube_error() from None
    observed_at = datetime.now(UTC)

    # 응답에 없거나 제목이 빈 영상은 unavailable(워커 제목으로 대체하지 않음)
    found = [i for i in new if i.video_id in infos and (infos[i.video_id].title or "").strip()]
    unavailable = len(new) - len(found)
    if not found:
        return CandidatesOut(accepted=0, duplicates=duplicates, unavailable=unavailable)
    items = [_collect_item(i, infos[i.video_id], observed_at, profile, broadcasters) for i in found]
    accepted = await _collect_rpc(
        request,
        "apply_collect_batch",
        {
            "p_workspace": str(ws),
            "p_job": str(job_id),
            "p_worker": str(worker.worker_id),
            "p_profile": str(body.profile_id),
            "p_payload": {"items": items},
        },
    )
    if not isinstance(accepted, int) or isinstance(accepted, bool):
        raise db_error()
    # 동시 요청이 먼저 넣은 후보는 RPC가 건너뛴다 → duplicates
    duplicates += len(found) - accepted
    return CandidatesOut(accepted=accepted, duplicates=duplicates, unavailable=unavailable)


async def _collect_rpc(request: Request, name: str, payload: dict) -> Any:
    """수집 RPC 호출. 비즈니스 오류(SQLSTATE)를 API 오류로 바꾼다."""
    path = f"rpc/{name}"
    resp = await _send(request, "POST", path, json=payload)
    if resp.status_code >= 400:
        code = _rpc_error_code(resp)
        logger.warning("데이터 저장소 오류 %s(%s): POST %s", resp.status_code, code, path)
        if code == "NR004":
            raise _job_not_running()  # 그 사이 중지 요청·종료됨
        if code == "NR005":
            raise _conflict("수집 상한에 도달했습니다.")
        if code == "NR003":
            raise _profile_not_in_job()
        raise db_error()
    try:
        return resp.json()
    except ValueError as exc:
        raise db_error() from exc


async def _rpc_json(request: Request, name: str, payload: dict) -> Any:
    path = f"rpc/{name}"
    resp = await _send(request, "POST", path, json=payload)
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: POST %s", resp.status_code, path)
        raise db_error()
    try:
        return resp.json()
    except ValueError as exc:
        raise db_error() from exc


# --- W-04 finish -----------------------------------------------------------------


@router.post("/jobs/{job_id}/finish", response_model=FinishOut)
async def finish_job(
    job_id: uuid.UUID,
    body: FinishIn,
    request: Request,
    worker: CurrentWorker = Depends(get_current_worker),
) -> FinishOut:
    ws = worker.workspace_id
    job = await _owned_job(request, worker, job_id)
    if job["status"] != "running":
        # 멱등: 이 워커가 같은 상태로 이미 끝낸 job이면 행 닫기만 다시 하고 200
        if job["status"] == body.status and job.get("error") != OFFLINE_ERROR:
            await close_profile_runs(request, ws, [str(job_id)], body.status)
            return FinishOut(job=FinishJobOut(status=body.status))
        raise _conflict("이미 종료된 작업입니다.")
    if body.status == "stopped" and not job.get("stop_requested"):
        raise _conflict("중지 요청이 없는 작업은 중지로 끝낼 수 없습니다.")
    error = None
    if body.status != "done":
        error = body.error or ("stopped_by_user" if body.status == "stopped" else "unknown")
    params = {
        "select": "id,status",
        "id": f"eq.{job_id}",
        "workspace_id": f"eq.{ws}",
        "kind": "eq.collect",
        "status": "eq.running",
        "claimed_by": f"eq.{worker.worker_id}",
    }
    if body.status == "stopped":
        params["stop_requested"] = "is.true"
    resp = await _send(
        request,
        "PATCH",
        "jobs",
        params=params,
        json={"status": body.status, "error": error, "finished_at": _ts(datetime.now(UTC))},
        headers={"Prefer": "return=representation"},
    )
    if not _json_list(resp, "PATCH", "jobs"):
        raise _conflict("이미 종료된 작업입니다.")  # 그 사이 오프라인 실패 처리 등
    await close_profile_runs(request, ws, [str(job_id)], body.status)
    return FinishOut(job=FinishJobOut(status=body.status))
