"""YouTube 검색 후보 수집(서버 동기 처리). 근거: tasks/task-019.md#착수 결정, ADR 0002(2026-11-17).

프로필마다: 검색(할당량은 job 생성 전에 예약됨) → 응답 id를 VIDEO_ID_RE로 거름 → 기존 후보 제외
→ [reserve_quota → videos.list(+contentDetails)] → 이번 실행의 모든 프로필로 판정(prev 없음)
→ apply_search_batch RPC(후보·관측·판정·실행 행 done을 한 트랜잭션).
YouTube 실패·할당량 초과는 job을 failed(upstream_error·quota_exceeded)로 닫고 정상 반환한다.
데이터 저장소 오류·예상 못 한 예외·취소는 job을 닫은 뒤 다시 던진다(verify 정리 패턴).
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import Request
from pydantic import SecretStr

from app.errors import ApiError, db_error
from app.jobs.state import close_profile_runs
from app.routes.profiles import CATEGORY_ALL, _json_list, _send
from app.routes.verify_runs import _rpc
from app.routes.worker import THUMBNAIL_URL
from app.verdict.engine import Candidate, Observation, Profile, judge, pick_representative
from app.youtube.client import (
    VIDEO_ID_RE,
    VideoInfo,
    YouTubeQuotaExceeded,
    YouTubeUnavailable,
    find_video_ids,
    videos_list,
)
from app.youtube.constants import (
    DAILY_UNIT_LIMIT,
    SEARCH_MAX_RESULTS,
    SEARCH_RUN_DEADLINE_SECONDS,
    SHORTS_MAX_SECONDS,
    VIDEOS_LIST_UNITS,
    YOUTUBE_CALL_TIMEOUT_SECONDS,
)

logger = logging.getLogger("nomadroom.collect.search")

MARKET_LANGUAGE = {"KR": "ko", "JP": "ja"}  # 시장 → relevanceLanguage
KEYWORD_OR = " | "


class SearchFailed(Exception):
    """YouTube 실패·할당량 초과. job은 error 코드로 실패 처리된다."""

    def __init__(self, error: Literal["upstream_error", "quota_exceeded"]):
        super().__init__(error)
        self.error = error


def search_params(profile: Profile) -> dict[str, str | int]:
    """프로필 조건 → 검색 파라미터. publishedAfter 없음, category는 판정이 거른다."""
    params: dict[str, str | int] = {
        "part": "id",
        "type": "video",
        "maxResults": SEARCH_MAX_RESULTS,
        "order": "viewCount",
        "regionCode": profile.market,
    }
    lang = MARKET_LANGUAGE.get(profile.market)
    if lang is not None:
        params["relevanceLanguage"] = lang
    if profile.keywords:
        params["q"] = KEYWORD_OR.join(profile.keywords)
    if profile.format == "short":
        params["videoDuration"] = "short"
    return params


def measured_format(duration_s: int | None) -> Literal["short", "long"] | None:
    """실측 길이로 형식을 정한다. 길이를 모르면 None(형식 조건이 있는 프로필에서 제외됨)."""
    if duration_s is None:
        return None
    return "short" if duration_s <= SHORTS_MAX_SECONDS else "long"


def found_category(profile: Profile) -> str | None:
    """검색 결과에는 카테고리 값이 없다. 그 영상을 찾은 프로필의 category를 쓴다("전체"면 null)."""
    if profile.category in (None, "", CATEGORY_ALL):
        return None
    return profile.category


def build_item(
    video_id: str,
    info: VideoInfo,
    observed_at: datetime,
    market: str,
    category: str | None,
    run_profiles: list[Profile],
    broadcasters: set[str],
) -> dict:
    """apply_search_batch 항목 1건. 판정은 이번 실행의 모든 프로필(순서 = job.profile_ids)."""
    title = info.title or ""  # 빈 제목은 호출 전에 걸러진다
    is_broadcaster = info.channel_id is not None and info.channel_id in broadcasters
    fmt = measured_format(info.duration_s)
    candidate = Candidate(
        id=uuid.uuid4(),  # 판정 계산용 임시 id(후보 id는 RPC가 만든다)
        title=title,
        category=category,
        format=fmt,
        market=market,
        license_cc=info.license_cc,
        is_broadcaster=is_broadcaster,
    )
    curr = Observation(id=uuid.uuid4(), observed_at=observed_at, view_count=info.view_count)
    verdicts = [judge(p, candidate, None, curr) for p in run_profiles]
    rep = pick_representative(verdicts, used=False)
    return {
        "video_id": video_id,
        "title": title,
        "thumbnail_url": THUMBNAIL_URL.format(video_id=video_id),
        "category": category,
        "format": fmt,
        "market": market,
        "channel_id": info.channel_id,
        "channel_title": info.channel_title,
        "license_cc": info.license_cc,
        "is_broadcaster": is_broadcaster,
        "observed_at": observed_at.isoformat(),
        "view_count": info.view_count,
        "rep_status": rep.rep_status,
        "rep_profile_id": str(rep.rep_profile_id),
        "verdicts": [
            {"profile_id": str(v.profile_id), "status": v.status, "reason": v.reason}
            for v in verdicts
        ],
    }


async def _existing_video_ids(request: Request, ws: uuid.UUID, ids: list[str]) -> set[str]:
    # ids는 VIDEO_ID_RE를 통과한 값만 온다(PostgREST 필터 주입 방지)
    params = {"select": "video_id", "workspace_id": f"eq.{ws}", "video_id": f"in.({','.join(ids)})"}
    rows = _json_list(await _send(request, "GET", "candidates", params=params), "GET", "candidates")
    return {r["video_id"] for r in rows}


async def _mark_run(request: Request, ws: uuid.UUID, job_id: str, profile_id: str) -> None:
    params = {
        "workspace_id": f"eq.{ws}",
        "job_id": f"eq.{job_id}",
        "profile_id": f"eq.{profile_id}",
    }
    body = {"status": "running", "updated_at": datetime.now(UTC).isoformat()}
    resp = await _send(request, "PATCH", "job_profile_runs", params=params, json=body)
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: PATCH job_profile_runs", resp.status_code)
        raise db_error()


async def _run_profile(
    request: Request,
    ws: uuid.UUID,
    job_id: str,
    profile: Profile,
    run_profiles: list[Profile],
    api_key: SecretStr,
    broadcasters: set[str],
) -> int:
    http = request.app.state.http
    await _mark_run(request, ws, job_id, str(profile.id))
    try:
        found_ids = await find_video_ids(
            http, api_key, search_params(profile), YOUTUBE_CALL_TIMEOUT_SECONDS
        )
    except YouTubeQuotaExceeded:
        raise SearchFailed("quota_exceeded") from None
    except YouTubeUnavailable:
        raise SearchFailed("upstream_error") from None
    ids = [v for v in found_ids if VIDEO_ID_RE.fullmatch(v)][:SEARCH_MAX_RESULTS]

    items: list[dict] = []
    existing = await _existing_video_ids(request, ws, ids) if ids else set()
    new = [v for v in ids if v not in existing]
    if new:
        reserved = await _rpc(
            request, "reserve_quota", {"p_units": VIDEOS_LIST_UNITS, "p_limit": DAILY_UNIT_LIMIT}
        )
        if reserved is not True:
            raise SearchFailed("quota_exceeded")
        try:
            infos = await videos_list(
                http,
                api_key,
                new,
                with_duration=True,
                total_timeout=YOUTUBE_CALL_TIMEOUT_SECONDS,
            )
        except YouTubeQuotaExceeded:
            raise SearchFailed("quota_exceeded") from None
        except YouTubeUnavailable:
            raise SearchFailed("upstream_error") from None
        observed_at = datetime.now(UTC)
        # 응답에서 빠졌거나(삭제·비공개) 제목이 빈 영상은 제외
        items = [
            build_item(
                v,
                infos[v],
                observed_at,
                profile.market,
                found_category(profile),
                run_profiles,
                broadcasters,
            )
            for v in new
            if v in infos and (infos[v].title or "").strip()
        ]
    # 새 후보가 없어도 호출한다: 실행 행 done 처리와 job 상태 확인을 RPC가 함께 한다.
    applied = await _rpc(
        request,
        "apply_search_batch",
        {
            "p_workspace": str(ws),
            "p_job": job_id,
            "p_profile": str(profile.id),
            "p_payload": {"items": items},
        },
    )
    if not isinstance(applied, int) or isinstance(applied, bool):
        raise db_error()
    return applied


async def _finish(request: Request, ws: uuid.UUID, job_id: str, status: str, error: str | None):
    params = {"id": f"eq.{job_id}", "workspace_id": f"eq.{ws}", "status": "eq.running"}
    body = {"status": status, "error": error, "finished_at": datetime.now(UTC).isoformat()}
    resp = await _send(request, "PATCH", "jobs", params=params, json=body)
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: PATCH jobs(종료)", resp.status_code)
        raise db_error()
    await close_profile_runs(request, ws, [job_id], status)


async def _finish_best_effort(request: Request, ws: uuid.UUID, job_id: str, error: str) -> None:
    try:
        await _finish(request, ws, job_id, "failed", error)
    except Exception:
        logger.warning("검색 job 실패 기록 실패(5분 뒤 정리됨)")


async def execute(
    request: Request,
    ws: uuid.UUID,
    job_id: str,
    run_profiles: list[Profile],
    todo: list[Profile],
    api_key: SecretStr,
) -> None:
    """running 검색 job을 todo 프로필 순서로 처리하고 done·failed로 닫는다."""
    try:
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
        # 실행 전체 마감: 넘기면 upstream_error로 닫는다(웹 대기 60초 안에 응답)
        async with asyncio.timeout(SEARCH_RUN_DEADLINE_SECONDS):
            for profile in todo:
                await _run_profile(
                    request, ws, job_id, profile, run_profiles, api_key, broadcasters
                )
    except TimeoutError:
        logger.warning("검색 수집 마감 초과")
        await _finish_best_effort(request, ws, job_id, "upstream_error")
        return
    except SearchFailed as exc:
        logger.warning("검색 수집 실패: %s", exc.error)
        await _finish_best_effort(request, ws, job_id, exc.error)
        return
    except ApiError:
        await _finish_best_effort(request, ws, job_id, "db_error")
        raise
    except BaseException:
        # 처리되지 않은 예외·취소(CancelledError)도 job을 닫는다(best-effort)
        await _finish_best_effort(request, ws, job_id, "internal")
        raise
    try:
        await _finish(request, ws, job_id, "done", None)
    except ApiError:
        logger.warning("검색 job 종료 기록 재시도")
        await _finish(request, ws, job_id, "done", None)
