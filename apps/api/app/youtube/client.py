"""YouTube Data API v3 클라이언트(`videos.list`·검색). 근거: docs/adr/0002-observation-quota.md.

- 키는 쿼리(`key=`)가 아니라 `X-Goog-Api-Key` 헤더로만 보낸다(URL·로그에 남지 않게).
- 응답 값(제목·채널 등)은 비신뢰 데이터다. 형식이 맞지 않는 항목은 버린다(→ 관측 실패).
"""

import asyncio
import logging
import re
from dataclasses import dataclass

import httpx
from pydantic import SecretStr

from app.youtube.constants import BATCH_SIZE

logger = logging.getLogger("nomadroom.youtube")

VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
VIDEOS_PART = "snippet,statistics,status"
VIDEOS_PART_WITH_DURATION = "snippet,statistics,status,contentDetails"  # 같은 1 unit
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"  # 100 unit/호출
VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
CHANNEL_ID_RE = re.compile(r"UC[0-9A-Za-z_-]{22}")
VIEW_COUNT_RE = re.compile(r"[0-9]{1,18}")  # bigint 범위 안(ASCII 숫자만)
MAX_TITLE = 300
MAX_CHANNEL_TITLE = 200
# ISO 8601 기간(예: PT1M30S, P1DT2H). 주·연·월 단위는 YouTube 영상 길이에 쓰이지 않는다.
DURATION_RE = re.compile(
    r"P(?:([0-9]{1,4})D)?(?:T(?:([0-9]{1,4})H)?(?:([0-9]{1,4})M)?(?:([0-9]{1,6})S)?)?"
)
_QUOTA_REASONS = frozenset({"quotaExceeded", "dailyLimitExceeded"})


class YouTubeQuotaExceeded(Exception):
    """YouTube가 할당량 초과(403 quotaExceeded 등)로 거부했다."""


class YouTubeUnavailable(Exception):
    """연결 실패·4xx/5xx·형식 오류."""


@dataclass(frozen=True)
class VideoInfo:
    video_id: str
    view_count: int
    license_cc: bool
    channel_id: str | None
    channel_title: str | None
    title: str | None
    duration_s: int | None = None  # contentDetails를 요청했을 때만. 0·형식 오류는 None


def _quota_reason(resp: httpx.Response) -> bool:
    try:
        errors = resp.json()["error"]["errors"]
        return any(e.get("reason") in _QUOTA_REASONS for e in errors)
    except ValueError, KeyError, TypeError, AttributeError:
        return False


def parse_duration(value: object) -> int | None:
    """ISO 8601 기간 → 초. 형식이 다르거나 0초(라이브 등)면 None."""
    if not isinstance(value, str):
        return None
    m = DURATION_RE.fullmatch(value)
    if m is None or value in ("P", "PT"):
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    total = ((d * 24 + h) * 60 + mi) * 60 + s
    return total or None


def _parse_item(item: object) -> VideoInfo | None:
    if not isinstance(item, dict):
        return None
    vid = item.get("id")
    snippet = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    status = item.get("status") or {}
    if not (isinstance(vid, str) and isinstance(snippet, dict) and isinstance(stats, dict)):
        return None
    if not isinstance(status, dict):
        return None
    raw_views = stats.get("viewCount")  # 문자열(uint64). 비공개 통계면 없음
    if not (isinstance(raw_views, str) and VIEW_COUNT_RE.fullmatch(raw_views)):
        return None
    channel_id = snippet.get("channelId")
    channel_title = snippet.get("channelTitle")
    title = snippet.get("title")
    details = item.get("contentDetails")
    duration = parse_duration(details.get("duration")) if isinstance(details, dict) else None
    return VideoInfo(
        video_id=vid,
        view_count=int(raw_views),
        license_cc=status.get("license") == "creativeCommon",
        channel_id=channel_id
        if isinstance(channel_id, str) and CHANNEL_ID_RE.fullmatch(channel_id)
        else None,
        channel_title=channel_title[:MAX_CHANNEL_TITLE] if isinstance(channel_title, str) else None,
        title=title[:MAX_TITLE] if isinstance(title, str) else None,
        duration_s=duration,
    )


async def _get_items(
    http: httpx.AsyncClient,
    api_key: SecretStr,
    url: str,
    params: dict,
    total_timeout: float | None = None,
) -> list:
    """GET → `items` 목록. 할당량 거부는 YouTubeQuotaExceeded, 그 밖 실패는 YouTubeUnavailable.

    total_timeout(초)을 주면 요청 전체(연결~본문)를 그 안에 끝낸다(httpx 타임아웃은 단계별).
    """
    try:
        async with asyncio.timeout(total_timeout):
            resp = await http.get(
                url, params=params, headers={"X-Goog-Api-Key": api_key.get_secret_value()}
            )
    except TimeoutError as exc:
        logger.warning("YouTube 응답 시간 초과")
        raise YouTubeUnavailable() from exc
    except httpx.HTTPError as exc:
        logger.warning("YouTube 연결 실패: %s", type(exc).__name__)
        raise YouTubeUnavailable() from exc
    if resp.status_code == 403 and _quota_reason(resp):
        logger.warning("YouTube 할당량 초과 응답")
        raise YouTubeQuotaExceeded()
    try:
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except httpx.HTTPStatusError as exc:
        logger.warning("YouTube 오류 응답 %s", resp.status_code, exc_info=exc)
        raise YouTubeUnavailable() from exc
    except (ValueError, AttributeError) as exc:
        raise YouTubeUnavailable() from exc
    if not isinstance(items, list):
        raise YouTubeUnavailable()
    return items


async def videos_list(
    http: httpx.AsyncClient,
    api_key: SecretStr,
    video_ids: list[str],
    *,
    with_duration: bool = False,
    total_timeout: float | None = None,
) -> dict[str, VideoInfo]:
    """id 최대 50개를 한 번(1 unit)에 조회한다. 응답에 없는 id(삭제·비공개)는 결과에 없다."""
    if not 0 < len(video_ids) <= BATCH_SIZE:
        raise ValueError("video_ids는 1~50개")
    part = VIDEOS_PART_WITH_DURATION if with_duration else VIDEOS_PART
    params = {"part": part, "id": ",".join(video_ids), "maxResults": BATCH_SIZE}
    items = await _get_items(http, api_key, VIDEOS_URL, params, total_timeout)
    wanted = set(video_ids)
    out: dict[str, VideoInfo] = {}
    for item in items:
        info = _parse_item(item)
        if info is not None and info.video_id in wanted:
            out[info.video_id] = info
    return out


async def find_video_ids(
    http: httpx.AsyncClient,
    api_key: SecretStr,
    params: dict[str, str | int],
    total_timeout: float | None = None,
) -> list[str]:
    """YouTube 검색 1회(100 unit). 응답 id는 비신뢰: VIDEO_ID_RE만 통과, 순서 유지·중복 제거."""
    items = await _get_items(http, api_key, SEARCH_URL, params, total_timeout)
    out: dict[str, None] = {}
    for item in items:
        ident = item.get("id") if isinstance(item, dict) else None
        vid = ident.get("videoId") if isinstance(ident, dict) else None
        if isinstance(vid, str) and VIDEO_ID_RE.fullmatch(vid):
            out.setdefault(vid, None)
    return list(out)
