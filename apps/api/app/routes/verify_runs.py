"""A-07 기록 검증(동기). 근거: tasks/task-006.md#구현 결정, docs/adr/0002-observation-quota.md.

흐름: 멱등 키 조회 → 오래된 verify job 정리 → job(running) 생성
→ 대상(used=false, 최신 관측 없음 또는 24시간 이상, 최대 200)
→ 50개 묶음마다 [할당량 예약 → videos.list → 판정 → apply_verify_batch RPC].
vidIQ 값은 판정에 쓰지 않는다(관측값은 YouTube 응답만).
"""

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth.user import CurrentUser, get_current_user
from app.errors import ApiError, db_error
from app.routes.candidates import COUNT_STATUSES, VIEW, CountsOut, count_rows
from app.routes.profiles import COLUMNS as PROFILE_COLUMNS
from app.routes.profiles import MAX_SELECTED, _json_list, _send
from app.verdict.engine import (
    MAX_INTERVAL,
    MIN_INTERVAL,
    Candidate,
    Observation,
    Profile,
    Verdict,
    judge,
    pick_representative,
    valid_prev,
)
from app.youtube.client import (
    VIDEO_ID_RE,
    VideoInfo,
    YouTubeQuotaExceeded,
    YouTubeUnavailable,
    videos_list,
)
from app.youtube.constants import (
    BATCH_SIZE,
    DAILY_UNIT_LIMIT,
    MAX_CANDIDATES,
    RATE_LIMIT_WINDOW,
    STALE_JOB_AFTER,
    VIDEOS_LIST_UNITS,
)

logger = logging.getLogger("nomadroom.verify_runs")

router = APIRouter(prefix="/v1/verify-runs", tags=["verify-runs"])

JOB_COLUMNS = "id,kind,status,result"
TARGET_COLUMNS = (
    "id,video_id,title,category,format,market,license_cc,is_broadcaster,latest_observed_at"
)
IDEMPOTENCY_CONSTRAINT = "jobs_workspace_id_idempotency_key_key"
ACTIVE_JOB_INDEX = "jobs_one_active_per_kind_idx"
_KEY_RE = re.compile(r"[\x21-\x7e]{1,100}")  # 출력 가능한 ASCII, 공백 없음


# --- 입출력 모델 ---------------------------------------------------------------


class VerifyRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_ids: Annotated[list[uuid.UUID] | None, Field(max_length=20)] = None

    @field_validator("profile_ids")
    @classmethod
    def _dedupe(cls, v: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        if v is None:
            return None
        out = list(dict.fromkeys(v))
        if len(out) > MAX_SELECTED:
            raise ValueError("최대 3개까지 검증할 수 있습니다")
        return out


class JobOut(BaseModel):
    id: uuid.UUID
    kind: Literal["verify"]
    status: Literal["queued", "running", "retrying", "stopped", "failed", "done"]


class VerifyRunOut(BaseModel):
    job: JobOut
    checked: int | None = None
    skipped_recent: int | None = None
    failed: int | None = None
    counts: CountsOut | None = None


# --- 오류 ----------------------------------------------------------------------


def quota_exceeded() -> ApiError:
    return ApiError(
        429,
        "QUOTA_EXCEEDED",
        "오늘 YouTube 조회 한도에 도달했습니다. 남은 후보는 이전 판정을 유지합니다.",
    )


def youtube_error() -> ApiError:
    return ApiError(502, "UPSTREAM_ERROR", "YouTube 조회에 실패했습니다.")


def rate_limited() -> ApiError:
    return ApiError(
        429, "RATE_LIMITED", "검증을 너무 자주 요청했습니다. 잠시 후 다시 시도해 주세요."
    )


def _running() -> ApiError:
    return ApiError(409, "CONFLICT", "검증이 이미 진행 중입니다.")


def _key_reused() -> ApiError:
    return ApiError(
        409, "CONFLICT", "같은 Idempotency-Key가 다른 작업에 사용되었습니다.", "Idempotency-Key"
    )


# --- 헬퍼 ----------------------------------------------------------------------


def _ts(dt: datetime) -> str:
    """PostgREST 필터용 UTC 시각(`+` 없는 형식)."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _replay(job: dict) -> VerifyRunOut:
    """같은 키의 기존 job: running이면 status만, 끝났으면 저장된 result 그대로."""
    if job.get("kind") != "verify":
        raise _key_reused()
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    counts = result.get("counts")
    return VerifyRunOut(
        job=JobOut(id=job["id"], kind="verify", status=job["status"]),
        checked=result.get("checked"),
        skipped_recent=result.get("skipped_recent"),
        failed=result.get("failed"),
        counts=CountsOut.model_validate(counts) if counts else None,
    )


async def _find_job(request: Request, ws: uuid.UUID, key: str) -> dict | None:
    params = {"select": JOB_COLUMNS, "workspace_id": f"eq.{ws}", "idempotency_key": f"eq.{key}"}
    rows = _json_list(await _send(request, "GET", "jobs", params=params), "GET", "jobs")
    return rows[0] if rows else None


async def _check_rate_limit(request: Request, ws: uuid.UUID, key: str, now: datetime) -> None:
    """직전 verify job 생성 후 60초 안의 새 키 요청은 429. 같은 키(동시 요청)는 멱등 처리로."""
    params = {
        "select": "id,idempotency_key",
        "workspace_id": f"eq.{ws}",
        "kind": "eq.verify",
        "created_at": f"gt.{_ts(now - RATE_LIMIT_WINDOW)}",
    }
    rows = _json_list(await _send(request, "GET", "jobs", params=params), "GET", "jobs")
    if any(r.get("idempotency_key") != key for r in rows):
        raise rate_limited()


async def _expire_stale_jobs(request: Request, ws: uuid.UUID, now: datetime) -> None:
    cut = _ts(now - STALE_JOB_AFTER)
    params = {
        "workspace_id": f"eq.{ws}",
        "kind": "eq.verify",
        "status": "in.(queued,running)",
        "or": f"(started_at.lt.{cut},and(started_at.is.null,created_at.lt.{cut}))",
    }
    body = {"status": "failed", "error": "timeout", "finished_at": now.isoformat()}
    resp = await _send(request, "PATCH", "jobs", params=params, json=body)
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: PATCH jobs(정리)", resp.status_code)
        raise db_error()


async def _create_job(
    request: Request, user: CurrentUser, key: str, profile_ids: list[str], now: datetime
) -> dict:
    body = {
        "workspace_id": str(user.workspace_id),
        "kind": "verify",
        "status": "running",
        "profile_ids": profile_ids,
        "idempotency_key": key,
        "requested_by": str(user.user_id),
        "started_at": now.isoformat(),
    }
    resp = await _send(
        request, "POST", "jobs", json=body, headers={"Prefer": "return=representation"}
    )
    if resp.status_code == 409:
        try:
            err = resp.json()
        except ValueError:
            err = {}
        text = f"{err.get('message', '')} {err.get('details', '')}" if isinstance(err, dict) else ""
        if IDEMPOTENCY_CONSTRAINT in text:
            raise _IdempotentHit()
        if ACTIVE_JOB_INDEX in text:
            raise _running()
    rows = _json_list(resp, "POST", "jobs")
    if not rows:
        raise db_error()
    return rows[0]


class _IdempotentHit(Exception):
    """동시 요청이 같은 키로 먼저 job을 만들었다."""


async def _finish_job(
    request: Request, ws: uuid.UUID, job_id: str, status: str, result: dict, error: str | None
) -> None:
    params = {"id": f"eq.{job_id}", "workspace_id": f"eq.{ws}"}
    body = {
        "status": status,
        "result": result,
        "error": error,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    resp = await _send(request, "PATCH", "jobs", params=params, json=body)
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: PATCH jobs(종료)", resp.status_code)
        raise db_error()


async def _rpc(request: Request, name: str, payload: dict) -> Any:
    path = f"rpc/{name}"
    resp = await _send(request, "POST", path, json=payload)
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: POST %s", resp.status_code, path)
        raise db_error()
    try:
        return resp.json()
    except ValueError as exc:
        raise db_error() from exc


def _profile(r: dict) -> Profile:
    return Profile(
        id=r["id"],
        market=r["market"],
        format=r["format"],
        category=r["category"],
        min_views=r["min_views"],
        max_growth_pct=Decimal(str(r["max_growth_pct"])),
        keywords=tuple(r["keywords"] or ()),
        cc_only=r["cc_only"],
        include_broadcast=r["include_broadcast"],
    )


async def _resolve_profiles(
    request: Request, ws: uuid.UUID, body: VerifyRunIn | None
) -> tuple[list[dict], list[dict]]:
    """(워크스페이스 전체 프로필 name 순, 이번 실행 프로필)."""
    params = {"select": PROFILE_COLUMNS, "workspace_id": f"eq.{ws}", "order": "name.asc,id.asc"}
    all_rows = _json_list(await _send(request, "GET", "profiles", params=params), "GET", "profiles")
    if body is not None and body.profile_ids is not None:
        wanted = {str(i) for i in body.profile_ids}
        run = [r for r in all_rows if r["id"] in wanted]
        if len(run) != len(wanted):
            raise ApiError(400, "VALIDATION", "없는 프로필이 포함되어 있습니다.", "profile_ids")
    else:
        run = [r for r in all_rows if r["selected"]]
    if not run:
        raise ApiError(400, "VALIDATION", "검증할 프로필이 없습니다.", "profile_ids")
    return all_rows, run


async def _targets(request: Request, ws: uuid.UUID, now: datetime) -> tuple[list[dict], int]:
    cut = _ts(now - MIN_INTERVAL)
    params = {
        "select": TARGET_COLUMNS,
        "workspace_id": f"eq.{ws}",
        "used": "is.false",
        "or": f"(latest_observed_at.is.null,latest_observed_at.lte.{cut})",
        "order": "latest_observed_at.asc.nullsfirst,id.asc",
        "limit": str(MAX_CANDIDATES),
    }
    skip_params = {
        "select": "id",
        "workspace_id": f"eq.{ws}",
        "used": "is.false",
        "latest_observed_at": f"gt.{cut}",
    }
    resp, skipped = await asyncio.gather(
        _send(request, "GET", VIEW, params=params), count_rows(request, VIEW, skip_params)
    )
    return _json_list(resp, "GET", VIEW)[:MAX_CANDIDATES], skipped


async def _batch_context(
    request: Request, ws: uuid.UUID, cand_ids: list[str], now: datetime
) -> tuple[dict[str, Observation], dict[str, dict[str, str]]]:
    """(후보별 최신 관측(7일+여유 이내), 후보별 기존 판정 {profile_id: status})."""
    ids = f"in.({','.join(cand_ids)})"
    obs_params = {
        "select": "id,candidate_id,observed_at,view_count",
        "workspace_id": f"eq.{ws}",
        "candidate_id": ids,
        "observed_at": f"gte.{_ts(now - MAX_INTERVAL - timedelta(hours=1))}",
        "order": "candidate_id.asc,observed_at.desc",
    }
    ver_params = {
        "select": "candidate_id,profile_id,status",
        "workspace_id": f"eq.{ws}",
        "candidate_id": ids,
    }
    obs_resp, ver_resp = await asyncio.gather(
        _send(request, "GET", "observations", params=obs_params),
        _send(request, "GET", "candidate_verdicts", params=ver_params),
    )
    # observed_at desc 순이므로 후보별로 처음 만나는 유효 간격(24시간~7일) 관측이 그중 최신
    latest: dict[str, Observation] = {}
    curr = Observation(id=uuid.uuid4(), observed_at=now, view_count=0)
    for r in _json_list(obs_resp, "GET", "observations"):
        if r["candidate_id"] in latest:
            continue
        obs = Observation.model_validate(r)
        if valid_prev(obs, curr) is not None:
            latest[r["candidate_id"]] = obs
    existing: dict[str, dict[str, str]] = {}
    for r in _json_list(ver_resp, "GET", "candidate_verdicts"):
        existing.setdefault(r["candidate_id"], {})[r["profile_id"]] = r["status"]
    return latest, existing


def _item_payload(
    target: dict,
    info: VideoInfo,
    observed_at: datetime,
    prev: Observation | None,
    existing: dict[str, str],
    all_profiles: list[dict],
    run_profiles: list[Profile],
    broadcasters: set[str],
) -> dict:
    candidate = Candidate(
        id=target["id"],
        title=target["title"],
        category=target["category"],
        format=target["format"],
        market=target["market"] or "",
        license_cc=info.license_cc,
        is_broadcaster=info.channel_id is not None and info.channel_id in broadcasters,
    )
    # 관측 id는 RPC가 만든다. 판정 계산용 임시 id
    curr = Observation(id=uuid.uuid4(), observed_at=observed_at, view_count=info.view_count)
    new = {str(p.id): judge(p, candidate, prev, curr) for p in run_profiles}
    merged: list[Verdict] = []
    for p in all_profiles:  # name asc, id asc
        pid = p["id"]
        if pid in new:
            merged.append(new[pid])
        elif pid in existing:
            merged.append(
                Verdict.model_construct(
                    candidate_id=candidate.id, profile_id=pid, status=existing[pid]
                )
            )
    rep = pick_representative(merged, used=False)
    return {
        "candidate_id": str(candidate.id),
        "observed_at": observed_at.isoformat(),
        "view_count": info.view_count,
        "license_cc": info.license_cc,
        "channel_id": info.channel_id,
        "channel_title": info.channel_title,
        "is_broadcaster": candidate.is_broadcaster,
        "rep_status": rep.rep_status,
        "rep_profile_id": str(rep.rep_profile_id),
        "verdicts": [
            {
                "profile_id": str(v.profile_id),
                "status": v.status,
                "reason": v.reason,
                "growth_pct": None if v.growth_pct is None else str(v.growth_pct),
                "prev_observation_id": None
                if v.prev_observation_id is None
                else str(v.prev_observation_id),
            }
            for v in new.values()
        ],
    }


async def _counts(request: Request, ws: uuid.UUID) -> CountsOut:
    params = [
        {"select": "id", "workspace_id": f"eq.{ws}", "display_status": f"eq.{s}"}
        for s in COUNT_STATUSES
    ]
    counts = await asyncio.gather(*(count_rows(request, VIEW, p) for p in params))
    return CountsOut(total=sum(counts), **dict(zip(COUNT_STATUSES, counts, strict=True)))


# --- A-07 ----------------------------------------------------------------------


@router.post("", response_model=VerifyRunOut)
async def post_verify_run(
    request: Request,
    body: VerifyRunIn | None = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    user: CurrentUser = Depends(get_current_user),
) -> VerifyRunOut:
    if idempotency_key is None or not _KEY_RE.fullmatch(idempotency_key):
        raise ApiError(400, "VALIDATION", "Idempotency-Key 헤더가 필요합니다.", "Idempotency-Key")
    ws = user.workspace_id

    # 같은 키 재요청은 본문이 달라도 기존 job을 돌려준다(문서화된 동작)
    existing_job = await _find_job(request, ws, idempotency_key)
    if existing_job is not None:
        return _replay(existing_job)

    api_key = request.app.state.settings.youtube_api_key
    if api_key is None:
        logger.warning("YOUTUBE_API_KEY 미설정")
        raise youtube_error()

    now = datetime.now(UTC)
    await _check_rate_limit(request, ws, idempotency_key, now)
    all_rows, run_rows = await _resolve_profiles(request, ws, body)
    await _expire_stale_jobs(request, ws, now)
    try:
        job = await _create_job(request, user, idempotency_key, [r["id"] for r in run_rows], now)
    except _IdempotentHit:
        hit = await _find_job(request, ws, idempotency_key)
        if hit is None:
            raise db_error() from None
        return _replay(hit)
    job_id = job["id"]

    checked = failed = skipped = 0
    try:
        targets, skipped = await _targets(request, ws, now)
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
        run_profiles = [_profile(r) for r in run_rows]

        for start in range(0, len(targets), BATCH_SIZE):
            batch = targets[start : start + BATCH_SIZE]
            valid = [t for t in batch if isinstance(t["video_id"], str)]
            valid = [t for t in valid if VIDEO_ID_RE.fullmatch(t["video_id"])]
            failed += len(batch) - len(valid)
            if not valid:
                continue
            reserved = await _rpc(
                request,
                "reserve_quota",
                {"p_units": VIDEOS_LIST_UNITS, "p_limit": DAILY_UNIT_LIMIT},
            )
            if reserved is not True:
                raise quota_exceeded()
            try:
                infos = await videos_list(
                    request.app.state.http, api_key, [t["video_id"] for t in valid]
                )
            except YouTubeQuotaExceeded:
                raise quota_exceeded() from None
            except YouTubeUnavailable:
                raise youtube_error() from None
            observed_at = datetime.now(UTC)

            found = [t for t in valid if t["video_id"] in infos]
            failed += len(valid) - len(found)  # 응답에서 빠진 영상(삭제·비공개)
            if not found:
                continue
            try:
                latest, existing = await _batch_context(
                    request, ws, [t["id"] for t in found], observed_at
                )
                items = [
                    _item_payload(
                        t,
                        infos[t["video_id"]],
                        observed_at,
                        latest.get(t["id"]),
                        existing.get(t["id"], {}),
                        all_rows,
                        run_profiles,
                        broadcasters,
                    )
                    for t in found
                ]
                applied = await _rpc(
                    request,
                    "apply_verify_batch",
                    {"p_workspace": str(ws), "p_job": job_id, "p_payload": {"items": items}},
                )
            except ApiError:
                # 이 묶음만 실패(RPC면 롤백, 이전 판정 유지). 다음 묶음은 계속
                failed += len(found)
                continue
            checked += applied if isinstance(applied, int) else 0
        counts = await _counts(request, ws)
    except ApiError as exc:
        error = {429: "quota_exceeded", 502: "upstream_error"}.get(exc.status_code, "db_error")
        partial = {"checked": checked, "skipped_recent": skipped, "failed": failed}
        try:
            await _finish_job(request, ws, job_id, "failed", partial, error)
        except ApiError:
            logger.warning("job 실패 기록 실패(10분 뒤 정리됨)")
        raise
    except BaseException:
        # 처리되지 않은 예외·취소(CancelledError)도 job을 닫는다(best-effort)
        try:
            await _finish_job(request, ws, job_id, "failed", {}, "internal")
        except Exception:
            logger.warning("job 실패 기록 실패(10분 뒤 정리됨)")
        raise

    result = {
        "checked": checked,
        "skipped_recent": skipped,
        "failed": failed,
        "counts": counts.model_dump(),
    }
    try:
        await _finish_job(request, ws, job_id, "done", result, None)
    except ApiError:
        logger.warning("job 종료 기록 재시도")
        await _finish_job(request, ws, job_id, "done", result, None)
    return VerifyRunOut(
        job=JobOut(id=job_id, kind="verify", status="done"),
        checked=checked,
        skipped_recent=skipped,
        failed=failed,
        counts=counts,
    )
