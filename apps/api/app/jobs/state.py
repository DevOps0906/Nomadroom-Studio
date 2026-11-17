"""수집 job 상태 전이 공통 함수. 정본: docs/02_ARCHITECTURE.md#3-3 "수집 job 상태 전이".

- 오프라인 지연 평가: claim한 워커의 `last_seen_at`이 3분을 넘은 running collect job
  → failed(error=`worker_offline`). W-01·W-02(task-007)와 A-05 GET/POST(task-008)에서 호출한다.
- 검색 수집 job(`params.source = youtube_search`, task-019)은 오프라인 평가에서 빼고,
  서버 중단 대비로 `started_at` 5분 초과 running 검색 job을 failed(`upstream_error`)로 둔다.
- job이 종료되면 job_profile_runs의 running 행을 job 상태에 맞춰 닫는다
  (done → done, 그 밖 → failed).
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Request

from app.errors import db_error
from app.routes.profiles import _json_list, _send
from app.youtube.constants import SEARCH_STALE_AFTER

logger = logging.getLogger("nomadroom.jobs")

OFFLINE_AFTER = timedelta(minutes=3)
OFFLINE_ERROR = "worker_offline"
SEARCH_SOURCE = "youtube_search"
SEARCH_STALE_ERROR = "upstream_error"


def is_search_job(job: dict) -> bool:
    params = job.get("params")
    return isinstance(params, dict) and params.get("source") == SEARCH_SOURCE


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def close_profile_runs(
    request: Request, ws: uuid.UUID, job_ids: list[str], status: str
) -> None:
    """종료된 job의 running 행을 닫는다. status는 job의 종료 상태."""
    if not job_ids:
        return
    params = {
        "workspace_id": f"eq.{ws}",
        "job_id": f"in.({','.join(job_ids)})",
        "status": "eq.running",
    }
    body = {
        "status": "done" if status == "done" else "failed",
        "updated_at": datetime.now(UTC).isoformat(),
    }
    resp = await _send(request, "PATCH", "job_profile_runs", params=params, json=body)
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: PATCH job_profile_runs", resp.status_code)
        raise db_error()


async def expire_offline_jobs(
    request: Request, ws: uuid.UUID, now: datetime | None = None
) -> list[str]:
    """워크스페이스의 오프라인 워커 running collect job을 failed로 바꾸고 그 id 목록을 돌려준다.

    기준 시각은 max(하트비트 `last_seen_at`, job `started_at`(claim 시각)).
    검색 job은 오프라인 평가 대신 `started_at` 5분 초과로 판단한다(`upstream_error`).
    """
    now = now or datetime.now(UTC)
    params = {
        "select": "id,claimed_by,started_at,params",
        "workspace_id": f"eq.{ws}",
        "kind": "eq.collect",
        "status": "eq.running",
    }
    rows = _json_list(await _send(request, "GET", "jobs", params=params), "GET", "jobs")
    stale_cut = now - SEARCH_STALE_AFTER
    stale = [
        str(j["id"])
        for j in rows
        if is_search_job(j)
        and (started := _parse(j.get("started_at"))) is not None
        and started < stale_cut
    ]
    changed_search = await _fail_jobs(request, ws, stale, SEARCH_STALE_ERROR, now)
    jobs = [j for j in rows if not is_search_job(j)]
    if not jobs:
        return changed_search
    workers = sorted({str(j["claimed_by"]) for j in jobs if j.get("claimed_by")})
    seen: dict[str, datetime] = {}
    if workers:
        hb_params = {
            "select": "worker_id,last_seen_at",
            "workspace_id": f"eq.{ws}",
            "worker_id": f"in.({','.join(workers)})",
        }
        rows = _json_list(
            await _send(request, "GET", "worker_heartbeats", params=hb_params),
            "GET",
            "worker_heartbeats",
        )
        for r in rows:
            at = _parse(r.get("last_seen_at"))
            if at is not None:
                seen[str(r["worker_id"])] = at
    cut = now - OFFLINE_AFTER
    expired: list[str] = []
    for j in jobs:
        worker = str(j["claimed_by"]) if j.get("claimed_by") else None
        # 기준 = max(하트비트, claim 시각): 재수령 직후 옛 하트비트로 실패 처리되지 않게
        hb = seen.get(worker) if worker else None
        times = [t for t in (hb, _parse(j.get("started_at"))) if t is not None]
        last = max(times) if times else None
        if last is None or last < cut:
            expired.append(str(j["id"]))
    changed = await _fail_jobs(request, ws, expired, OFFLINE_ERROR, now)
    return changed_search + changed


async def _fail_jobs(
    request: Request, ws: uuid.UUID, ids: list[str], error: str, now: datetime
) -> list[str]:
    if not ids:
        return []
    patch_params = {
        "workspace_id": f"eq.{ws}",
        "id": f"in.({','.join(ids)})",
        "status": "eq.running",  # 그 사이 W-04로 끝난 job은 건드리지 않는다
    }
    body = {"status": "failed", "error": error, "finished_at": now.isoformat()}
    resp = await _send(
        request,
        "PATCH",
        "jobs",
        params={**patch_params, "select": "id"},
        json=body,
        headers={"Prefer": "return=representation"},
    )
    changed = [str(r["id"]) for r in _json_list(resp, "PATCH", "jobs")]
    if changed:
        logger.info("job 실패 처리(%s) %d건", error, len(changed))
        await close_profile_runs(request, ws, changed, "failed")
    return changed
