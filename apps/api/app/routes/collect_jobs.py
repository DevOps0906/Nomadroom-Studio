"""A-05 수집 작업(생성·상태·재시도·중지). 근거: tasks/task-008.md#구현 결정, 02_ARCHITECTURE#3-3.

- 생성(task-019): 멱등 키 → 60초·24시간 제한 → 대상 프로필(최대 3) → 활성 job 확인
  → 검색 할당량 예약(프로필 수 × 100, 실패면 429·job 없음) → jobs(running, source=youtube_search)
  → 실행 행(pending) → 서버가 동기로 검색 수집 후 done·failed(`app.collect.search`).
- 재시도: vidIQ job은 RPC(retry_collect_job), 검색 job은 서버가 남은 프로필만 다시 예약해
  failed → running으로 바꾼 뒤 같은 요청 안에서 실행한다. 중지: vidIQ job은 RPC, 검색 job은 409.
- 모든 경로가 먼저 오프라인 지연 평가(`expire_offline_jobs`)를 한다.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.auth.user import CurrentUser, get_current_user
from app.collect import search
from app.errors import ApiError, db_error, not_found
from app.jobs.state import OFFLINE_AFTER, SEARCH_SOURCE, expire_offline_jobs, is_search_job
from app.routes.candidates import count_rows
from app.routes.profiles import COLUMNS as PROFILE_COLUMNS
from app.routes.profiles import MAX_SELECTED, _json_list, _send
from app.routes.verify_runs import (
    _KEY_RE,
    ACTIVE_JOB_INDEX,
    IDEMPOTENCY_CONSTRAINT,
    _profile,
    _rpc,
    _ts,
    quota_exceeded,
    youtube_error,
)
from app.youtube.constants import (
    DAILY_UNIT_LIMIT,
    MAX_CANDIDATES,
    RATE_LIMIT_WINDOW,
    SEARCH_DAILY_UNIT_LIMIT,
    SEARCH_UNITS,
)

logger = logging.getLogger("nomadroom.collect_jobs")

router = APIRouter(prefix="/v1/collect-jobs", tags=["collect-jobs"])

JOB_COLUMNS = (
    "id,kind,status,error,profile_ids,params,stop_requested,retry_count,claimed_by,"
    "idempotency_key,started_at"
)
RUN_COLUMNS = "profile_id,position,chrome_state,detail,status,collected_count"
DAILY_JOB_LIMIT = 20  # 워크스페이스당 최근 24시간 collect job 생성 상한
DAILY_WINDOW = timedelta(hours=24)

JobStatus = Literal["queued", "running", "retrying", "stopped", "failed", "done"]
JobSource = Literal["vidiq", "youtube_search"]
ACTIVE_STATUSES = ("queued", "running", "retrying")
MAX_RETRIES = 3


# --- 입출력 모델 ---------------------------------------------------------------


class CollectJobIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_ids: Annotated[list[uuid.UUID] | None, Field(max_length=20)] = None

    @field_validator("profile_ids")
    @classmethod
    def _dedupe(cls, v: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        if v is None:
            return None
        out = list(dict.fromkeys(v))
        if len(out) > MAX_SELECTED:
            raise ValueError("최대 3개까지 수집할 수 있습니다")
        return out


class ProfileRunOut(BaseModel):
    profile_id: uuid.UUID
    chrome_state: Literal["ready", "resize_needed", "login_needed", "error"] | None = None
    detail: str | None = None
    status: Literal["pending", "running", "done", "failed"]
    collected_count: int


class JobResultOut(BaseModel):
    candidates: int
    producible: int
    pending: int


class CollectJobOut(BaseModel):
    id: uuid.UUID
    source: JobSource
    status: JobStatus
    error: str | None = None
    stop_requested: bool
    retry_count: int
    profiles: list[ProfileRunOut]


class CollectJobDetailOut(CollectJobOut):
    result: JobResultOut | None  # 종료 상태(done·failed·stopped)일 때만 집계, 진행 중이면 null
    worker_last_seen_at: datetime | None
    worker_online: bool


class CollectJobEnvelope(BaseModel):
    job: CollectJobOut


class CollectJobDetailEnvelope(BaseModel):
    job: CollectJobDetailOut


# --- 오류 ----------------------------------------------------------------------


def _conflict(message: str) -> ApiError:
    return ApiError(409, "CONFLICT", message)


def _running() -> ApiError:
    return _conflict("수집이 이미 진행 중입니다.")


def _key_reused() -> ApiError:
    return ApiError(
        409, "CONFLICT", "같은 Idempotency-Key가 다른 작업에 사용되었습니다.", "Idempotency-Key"
    )


def _rate_limited() -> ApiError:
    return ApiError(
        429, "RATE_LIMITED", "수집을 너무 자주 요청했습니다. 잠시 후 다시 시도해 주세요."
    )


# RPC 비즈니스 예외(SQLSTATE) → API 오류. NR006 문구는 RPC마다 다르다.
_RETRY_ERRORS = {
    "NR005": "이 작업의 조회 상한 도달 — 새 수집 실행",
    "NR006": "재시도할 수 없는 작업입니다.",
    "NR007": "다른 수집이 진행 중입니다.",
}
_STOP_ERRORS = {"NR006": "이미 종료된 작업입니다."}
_NOT_RETRYABLE = "재시도할 수 없는 작업입니다."
_SEARCH_NOT_STOPPABLE = "검색 수집은 중지할 수 없습니다."


class _IdempotentHit(Exception):
    """동시 요청이 같은 키로 먼저 job을 만들었다."""


# --- 헬퍼 ----------------------------------------------------------------------


def _error_body(resp: Any) -> dict:
    try:
        body = resp.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


async def _find_by_key(request: Request, ws: uuid.UUID, key: str) -> dict | None:
    params = {"select": JOB_COLUMNS, "workspace_id": f"eq.{ws}", "idempotency_key": f"eq.{key}"}
    rows = _json_list(await _send(request, "GET", "jobs", params=params), "GET", "jobs")
    return rows[0] if rows else None


async def _get_job(request: Request, ws: uuid.UUID, job_id: uuid.UUID) -> dict:
    """같은 워크스페이스의 collect job. 아니면(다른 kind 포함) 404."""
    params = {
        "select": JOB_COLUMNS,
        "id": f"eq.{job_id}",
        "workspace_id": f"eq.{ws}",
        "kind": "eq.collect",
    }
    rows = _json_list(await _send(request, "GET", "jobs", params=params), "GET", "jobs")
    if len(rows) != 1:
        raise not_found()
    return rows[0]


async def _job_out(request: Request, ws: uuid.UUID, job: dict) -> CollectJobOut:
    params = {
        "select": RUN_COLUMNS,
        "workspace_id": f"eq.{ws}",
        "job_id": f"eq.{job['id']}",
        "order": "position.asc",
    }
    runs = _json_list(
        await _send(request, "GET", "job_profile_runs", params=params), "GET", "job_profile_runs"
    )
    by_profile = {str(r["profile_id"]): r for r in runs}
    profiles = []
    # profile_ids 순서가 position. 실행 행이 없으면(생성 실패) pending으로 보인다.
    for pid in job.get("profile_ids") or []:
        r = by_profile.get(str(pid))
        if r is None:
            profiles.append(ProfileRunOut(profile_id=pid, status="pending", collected_count=0))
        else:
            profiles.append(ProfileRunOut.model_validate(r))
    return CollectJobOut(
        id=job["id"],
        source=SEARCH_SOURCE if is_search_job(job) else "vidiq",
        status=job["status"],
        error=job.get("error"),
        stop_requested=bool(job.get("stop_requested")),
        retry_count=job.get("retry_count") or 0,
        profiles=profiles,
    )


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def _worker_last_seen(request: Request, ws: uuid.UUID, job: dict) -> datetime | None:
    """claim한 워커 값, 없으면 폐기되지 않은 워크스페이스 워커 중 최댓값, 워커가 없으면 None."""
    if job.get("claimed_by"):
        ids = [str(job["claimed_by"])]
    else:
        w_params = {"select": "id", "workspace_id": f"eq.{ws}", "revoked_at": "is.null"}
        rows = _json_list(await _send(request, "GET", "workers", params=w_params), "GET", "workers")
        ids = [str(r["id"]) for r in rows]
    if not ids:
        return None
    hb_params = {
        "select": "last_seen_at",
        "workspace_id": f"eq.{ws}",
        "worker_id": f"in.({','.join(ids)})",
    }
    rows = _json_list(
        await _send(request, "GET", "worker_heartbeats", params=hb_params),
        "GET",
        "worker_heartbeats",
    )
    seen = [t for t in (_parse(r.get("last_seen_at")) for r in rows) if t is not None]
    return max(seen) if seen else None


async def _result(request: Request, ws: uuid.UUID, job_id: str) -> JobResultOut:
    """이 job이 처음 넣은 후보(first_job_id) 수와 대표 판정별 수(used 제외)."""
    base = {"select": "id", "workspace_id": f"eq.{ws}", "first_job_id": f"eq.{job_id}"}
    total, producible, pending = await asyncio.gather(
        count_rows(request, "candidates", base),
        count_rows(
            request, "candidates", {**base, "used": "is.false", "rep_status": "eq.producible"}
        ),
        count_rows(request, "candidates", {**base, "used": "is.false", "rep_status": "eq.pending"}),
    )
    return JobResultOut(candidates=total, producible=producible, pending=pending)


async def _check_rate_limit(request: Request, ws: uuid.UUID, key: str, now: datetime) -> None:
    """직전 collect job 생성 후 60초 안의 새 키 요청, 최근 24시간 20건 도달은 429."""
    params = {
        "select": "id,idempotency_key",
        "workspace_id": f"eq.{ws}",
        "kind": "eq.collect",
        "created_at": f"gt.{_ts(now - RATE_LIMIT_WINDOW)}",
    }
    rows = _json_list(await _send(request, "GET", "jobs", params=params), "GET", "jobs")
    if any(r.get("idempotency_key") != key for r in rows):
        raise _rate_limited()
    daily = {
        "select": "id",
        "workspace_id": f"eq.{ws}",
        "kind": "eq.collect",
        "created_at": f"gt.{_ts(now - DAILY_WINDOW)}",
    }
    if await count_rows(request, "jobs", daily) >= DAILY_JOB_LIMIT:
        raise _rate_limited()


async def _target_profiles(
    request: Request, ws: uuid.UUID, body: CollectJobIn | None
) -> list[dict]:
    """이번 수집 프로필 행(요청 순서, 생략 시 선택된 프로필 name 순)."""
    params = {"select": PROFILE_COLUMNS, "workspace_id": f"eq.{ws}", "order": "name.asc,id.asc"}
    rows = _json_list(await _send(request, "GET", "profiles", params=params), "GET", "profiles")
    if body is not None and body.profile_ids is not None:
        by_id = {str(r["id"]): r for r in rows}
        ids = [str(i) for i in body.profile_ids]
        if any(i not in by_id for i in ids):
            raise ApiError(400, "VALIDATION", "없는 프로필이 포함되어 있습니다.", "profile_ids")
        out = [by_id[i] for i in ids]
    else:
        out = [r for r in rows if r["selected"]]
        if len(out) > MAX_SELECTED:
            raise ApiError(400, "VALIDATION", "선택된 프로필이 3개를 넘습니다.", "profile_ids")
    if not out:
        raise ApiError(400, "VALIDATION", "수집할 프로필이 없습니다.", "profile_ids")
    return out


async def _job_profiles(request: Request, ws: uuid.UUID, ids: list[str]) -> list[dict]:
    """job.profile_ids 순서의 프로필 행(없어진 프로필은 빠진다)."""
    params = {
        "select": PROFILE_COLUMNS,
        "workspace_id": f"eq.{ws}",
        "id": f"in.({','.join(ids)})",
    }
    rows = _json_list(await _send(request, "GET", "profiles", params=params), "GET", "profiles")
    by_id = {str(r["id"]): r for r in rows}
    return [by_id[i] for i in ids if i in by_id]


async def _active_jobs(request: Request, ws: uuid.UUID) -> list[dict]:
    params = {
        "select": JOB_COLUMNS,
        "workspace_id": f"eq.{ws}",
        "kind": "eq.collect",
        "status": f"in.({','.join(ACTIVE_STATUSES)})",
    }
    return _json_list(await _send(request, "GET", "jobs", params=params), "GET", "jobs")


async def _reserve_search(request: Request, n_profiles: int) -> None:
    """검색 일 상한(2,000)과 전체 방어선(8,000)을 한 번에 원자적으로 예약. 실패면 429."""
    reserved = await _rpc(
        request,
        "reserve_search_quota",
        {
            "p_units": n_profiles * SEARCH_UNITS,
            "p_search_limit": SEARCH_DAILY_UNIT_LIMIT,
            "p_limit": DAILY_UNIT_LIMIT,
        },
    )
    if reserved is not True:
        raise quota_exceeded()


async def _release_search(request: Request, n_profiles: int) -> None:
    """예약 뒤 job 생성·재시도 전이가 실패했다(검색 안 함) → 예약분을 되돌린다(best-effort)."""
    path = "rpc/release_search_quota"
    try:
        resp = await _send(request, "POST", path, json={"p_units": n_profiles * SEARCH_UNITS})
    except ApiError:
        logger.warning("검색 할당량 되돌리기 실패(연결)")
        return
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: POST %s", resp.status_code, path)


def _api_key(request: Request) -> SecretStr:
    api_key = request.app.state.settings.youtube_api_key
    if api_key is None:
        logger.warning("YOUTUBE_API_KEY 미설정")
        raise youtube_error()
    return api_key


async def _create_job(
    request: Request, user: CurrentUser, key: str, profile_ids: list[str]
) -> dict:
    # 검색 job은 워커가 수령하지 않도록 바로 running으로 만든다(claimed_by 없음).
    body = {
        "workspace_id": str(user.workspace_id),
        "kind": "collect",
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "profile_ids": profile_ids,
        "params": {"limit": MAX_CANDIDATES, "source": SEARCH_SOURCE},
        "idempotency_key": key,
        "requested_by": str(user.user_id),
    }
    resp = await _send(
        request,
        "POST",
        "jobs",
        params={"select": JOB_COLUMNS},
        json=body,
        headers={"Prefer": "return=representation"},
    )
    if resp.status_code == 409:
        err = _error_body(resp)
        text = f"{err.get('message', '')} {err.get('details', '')}"
        if IDEMPOTENCY_CONSTRAINT in text:
            raise _IdempotentHit()
        if ACTIVE_JOB_INDEX in text:
            raise _running()
    rows = _json_list(resp, "POST", "jobs")
    if not rows:
        raise db_error()
    return rows[0]


async def _create_runs(request: Request, ws: uuid.UUID, job_id: str, ids: list[str]) -> None:
    """프로필별 실행 행(pending). 실패해도 W-02·RPC upsert가 보완하므로 로그만 남긴다."""
    rows = [
        {
            "workspace_id": str(ws),
            "job_id": job_id,
            "profile_id": pid,
            "position": pos,
            "status": "pending",
        }
        for pos, pid in enumerate(ids)
    ]
    try:
        resp = await _send(
            request, "POST", "job_profile_runs", json=rows, headers={"Prefer": "return=minimal"}
        )
    except ApiError:
        logger.warning("실행 행 생성 실패(연결)")
        return
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: POST job_profile_runs", resp.status_code)


async def _control_rpc(
    request: Request, name: str, ws: uuid.UUID, job_id: uuid.UUID, errors: dict[str, str]
) -> None:
    path = f"rpc/{name}"
    resp = await _send(request, "POST", path, json={"p_workspace": str(ws), "p_job": str(job_id)})
    if resp.status_code < 400:
        return
    err = _error_body(resp)
    code = err.get("code")
    logger.warning("데이터 저장소 오류 %s(%s): POST %s", resp.status_code, code, path)
    if code == "NR003":
        raise not_found()
    if code in errors:
        raise _conflict(errors[code])
    # 그 사이 다른 POST가 활성 job을 만들었다(활성 유니크 인덱스)
    if code == "23505" and "NR007" in errors:
        raise _conflict(errors["NR007"])
    raise db_error()


async def _retry_search(request: Request, ws: uuid.UUID, job: dict) -> None:
    """검색 job 재시도: 남은(done 아닌) 프로필만 예약 → failed → running(조건부) → 동기 실행."""
    retry_count = job.get("retry_count") or 0
    if job["status"] != "failed" or retry_count >= MAX_RETRIES or job.get("stop_requested"):
        raise _conflict(_NOT_RETRYABLE)
    api_key = _api_key(request)
    job_id = str(job["id"])
    run_params = {
        "select": "profile_id,status",
        "workspace_id": f"eq.{ws}",
        "job_id": f"eq.{job_id}",
    }
    runs = _json_list(
        await _send(request, "GET", "job_profile_runs", params=run_params),
        "GET",
        "job_profile_runs",
    )
    done = {str(r["profile_id"]) for r in runs if r["status"] == "done"}
    rows = await _job_profiles(request, ws, [str(p) for p in job.get("profile_ids") or []])
    todo = [r for r in rows if str(r["id"]) not in done]
    if not todo:
        raise _conflict(_NOT_RETRYABLE)
    if any(str(j["id"]) != job_id for j in await _active_jobs(request, ws)):
        raise _conflict(_RETRY_ERRORS["NR007"])
    # 남용 방지: 직전 실행 시작 후 60초 안의 재시도는 429(생성 POST와 같은 구간·문구)
    last_start = _parse(job.get("started_at"))
    if last_start is not None and datetime.now(UTC) - last_start < RATE_LIMIT_WINDOW:
        raise _rate_limited()
    await _reserve_search(request, len(todo))
    try:
        await _start_retry(request, ws, job, retry_count, str(todo[0]["id"]))
    except BaseException:
        await _release_search(request, len(todo))
        raise

    reset = {
        "workspace_id": f"eq.{ws}",
        "job_id": f"eq.{job_id}",
        "profile_id": f"in.({','.join(str(r['id']) for r in todo)})",
        "status": "eq.failed",
    }
    resp = await _send(
        request,
        "PATCH",
        "job_profile_runs",
        params=reset,
        json={"status": "pending", "updated_at": datetime.now(UTC).isoformat()},
    )
    if resp.status_code >= 400:  # 화면 표시만 늦다. 실행이 running·done으로 덮어쓴다
        logger.warning("데이터 저장소 오류 %s: PATCH job_profile_runs", resp.status_code)
    await search.execute(
        request, ws, job_id, [_profile(r) for r in rows], [_profile(r) for r in todo], api_key
    )


async def _start_retry(
    request: Request, ws: uuid.UUID, job: dict, retry_count: int, resume_from: str
) -> None:
    """failed → running 조건부 전이. 동시 재시도·활성 충돌이면 409."""
    job_id = str(job["id"])
    params = {
        "select": JOB_COLUMNS,
        "id": f"eq.{job_id}",
        "workspace_id": f"eq.{ws}",
        "status": "eq.failed",
        "retry_count": f"eq.{retry_count}",
        "stop_requested": "is.false",
    }
    body = {
        "status": "running",
        "retry_count": retry_count + 1,
        "error": None,
        "finished_at": None,
        "started_at": datetime.now(UTC).isoformat(),
        "params": {**(job.get("params") or {}), "resume_from_profile_id": resume_from},
    }
    resp = await _send(
        request,
        "PATCH",
        "jobs",
        params=params,
        json=body,
        headers={"Prefer": "return=representation"},
    )
    if resp.status_code == 409 and ACTIVE_JOB_INDEX in str(_error_body(resp).get("message", "")):
        raise _conflict(_RETRY_ERRORS["NR007"])
    if not _json_list(resp, "PATCH", "jobs"):
        raise _conflict(_NOT_RETRYABLE)  # 동시 재시도가 먼저 바꿨다


# --- A-05 ----------------------------------------------------------------------


@router.post("", response_model=CollectJobEnvelope, status_code=202)
async def post_collect_job(
    request: Request,
    response: Response,
    body: CollectJobIn | None = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    user: CurrentUser = Depends(get_current_user),
) -> CollectJobEnvelope:
    if idempotency_key is None or not _KEY_RE.fullmatch(idempotency_key):
        raise ApiError(400, "VALIDATION", "Idempotency-Key 헤더가 필요합니다.", "Idempotency-Key")
    ws = user.workspace_id
    await expire_offline_jobs(request, ws)

    # 같은 키 재요청은 본문이 달라도 기존 job(200). 활성 409보다 먼저 확인한다.
    existing = await _find_by_key(request, ws, idempotency_key)
    if existing is not None:
        if existing.get("kind") != "collect":
            raise _key_reused()
        response.status_code = 200
        return CollectJobEnvelope(job=await _job_out(request, ws, existing))

    api_key = _api_key(request)
    await _check_rate_limit(request, ws, idempotency_key, datetime.now(UTC))
    rows = await _target_profiles(request, ws, body)
    ids = [str(r["id"]) for r in rows]
    # 진행 중 job이 있으면 할당량을 쓰기 전에 거부한다(생성 시 유니크 인덱스가 최종 확인).
    active = await _active_jobs(request, ws)
    same = [j for j in active if j.get("idempotency_key") == idempotency_key]
    if same:  # 동시 요청이 같은 키로 먼저 만들었다
        response.status_code = 200
        return CollectJobEnvelope(job=await _job_out(request, ws, same[0]))
    if active:
        raise _running()
    await _reserve_search(request, len(ids))
    try:
        job = await _create_job(request, user, idempotency_key, ids)
    except BaseException as exc:
        # job이 없으니 검색도 하지 않는다 → 예약분을 되돌린다(멱등·활성 충돌·DB 오류·취소)
        await _release_search(request, len(ids))
        if not isinstance(exc, _IdempotentHit):
            raise
        hit = await _find_by_key(request, ws, idempotency_key)
        if hit is None:
            raise db_error() from None
        if hit.get("kind") != "collect":
            raise _key_reused() from None
        response.status_code = 200
        return CollectJobEnvelope(job=await _job_out(request, ws, hit))
    await _create_runs(request, ws, str(job["id"]), ids)
    profiles = [_profile(r) for r in rows]
    await search.execute(request, ws, str(job["id"]), profiles, profiles, api_key)
    job = await _get_job(request, ws, uuid.UUID(str(job["id"])))
    return CollectJobEnvelope(job=await _job_out(request, ws, job))


async def _no_result() -> None:
    return None


async def _detail(request: Request, ws: uuid.UUID, job: dict) -> CollectJobDetailEnvelope:
    # 폴링(3초) 비용: 진행 중 job은 결과 집계(count 3회)를 생략한다.
    finished = job["status"] not in ACTIVE_STATUSES
    base, result, last_seen = await asyncio.gather(
        _job_out(request, ws, job),
        _result(request, ws, str(job["id"])) if finished else _no_result(),
        _worker_last_seen(request, ws, job),
    )
    online = last_seen is not None and datetime.now(UTC) - last_seen <= OFFLINE_AFTER
    return CollectJobDetailEnvelope(
        job=CollectJobDetailOut(
            **base.model_dump(),
            result=result,
            worker_last_seen_at=last_seen,
            worker_online=online,
        )
    )


# /active는 /{job_id}보다 먼저 등록해야 UUID 검증에 걸리지 않는다.
@router.get(
    "/active",
    response_model=CollectJobDetailEnvelope,
    responses={204: {"description": "활성 collect job 없음"}},
)
async def get_active_collect_job(
    request: Request, user: CurrentUser = Depends(get_current_user)
) -> CollectJobDetailEnvelope | Response:
    """이 워크스페이스의 활성 collect job 1건(화면 재진입 복구용). 없으면 204."""
    ws = user.workspace_id
    await expire_offline_jobs(request, ws)
    params = {
        "select": JOB_COLUMNS,
        "workspace_id": f"eq.{ws}",
        "kind": "eq.collect",
        "status": f"in.({','.join(ACTIVE_STATUSES)})",
        "order": "created_at.desc,id.desc",
        "limit": "1",
    }
    rows = _json_list(await _send(request, "GET", "jobs", params=params), "GET", "jobs")
    if not rows:
        return Response(status_code=204)
    return await _detail(request, ws, rows[0])


@router.get("/{job_id}", response_model=CollectJobDetailEnvelope)
async def get_collect_job(
    job_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user)
) -> CollectJobDetailEnvelope:
    ws = user.workspace_id
    await expire_offline_jobs(request, ws)
    return await _detail(request, ws, await _get_job(request, ws, job_id))


@router.post("/{job_id}/retry", response_model=CollectJobEnvelope)
async def retry_collect_job(
    job_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user)
) -> CollectJobEnvelope:
    ws = user.workspace_id
    await expire_offline_jobs(request, ws)
    job = await _get_job(request, ws, job_id)
    if is_search_job(job):
        await _retry_search(request, ws, job)
    else:
        await _control_rpc(request, "retry_collect_job", ws, job_id, _RETRY_ERRORS)
    return CollectJobEnvelope(job=await _job_out(request, ws, await _get_job(request, ws, job_id)))


@router.post("/{job_id}/stop", response_model=CollectJobEnvelope)
async def stop_collect_job(
    job_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user)
) -> CollectJobEnvelope:
    ws = user.workspace_id
    await expire_offline_jobs(request, ws)
    if is_search_job(await _get_job(request, ws, job_id)):
        raise _conflict(_SEARCH_NOT_STOPPABLE)
    await _control_rpc(request, "stop_collect_job", ws, job_id, _STOP_ERRORS)
    return CollectJobEnvelope(job=await _job_out(request, ws, await _get_job(request, ws, job_id)))
