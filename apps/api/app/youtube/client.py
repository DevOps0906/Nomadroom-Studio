"""YouTube Data API v3 `videos.list` 클라이언트. 근거: docs/adr/0002-observation-quota.md.

- 키는 쿼리(`key=`)가 아니라 `X-Goog-Api-Key` 헤더로만 보낸다(URL·로그에 남지 않게).
- 응답 값(제목·채널 등)은 비신뢰 데이터다. 형식이 맞지 않는 항목은 버린다(→ 관측 실패).
"""

import logging
import re
from dataclasses import dataclass

import httpx
from pydantic import SecretStr

from app.youtube.constants import BATCH_SIZE

logger = logging.getLogger("nomadroom.youtube")

VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
VIDEOS_PART = "snippet,statistics,status"
VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
CHANNEL_ID_RE = re.compile(r"UC[0-9A-Za-z_-]{22}")
VIEW_COUNT_RE = re.compile(r"[0-9]{1,18}")  # bigint 범위 안(ASCII 숫자만)
MAX_TITLE = 300
MAX_CHANNEL_TITLE = 200
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


def _quota_reason(resp: httpx.Response) -> bool:
    try:
        errors = resp.json()["error"]["errors"]
        return any(e.get("reason") in _QUOTA_REASONS for e in errors)
    except ValueError, KeyError, TypeError, AttributeError:
        return False


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
    return VideoInfo(
        video_id=vid,
        view_count=int(raw_views),
        license_cc=status.get("license") == "creativeCommon",
        channel_id=channel_id
        if isinstance(channel_id, str) and CHANNEL_ID_RE.fullmatch(channel_id)
        else None,
        channel_title=channel_title[:MAX_CHANNEL_TITLE] if isinstance(channel_title, str) else None,
        title=title[:MAX_TITLE] if isinstance(title, str) else None,
    )


async def videos_list(
    http: httpx.AsyncClient, api_key: SecretStr, video_ids: list[str]
) -> dict[str, VideoInfo]:
    """id 최대 50개를 한 번(1 unit)에 조회한다. 응답에 없는 id(삭제·비공개)는 결과에 없다."""
    if not 0 < len(video_ids) <= BATCH_SIZE:
        raise ValueError("video_ids는 1~50개")
    try:
        resp = await http.get(
            VIDEOS_URL,
            params={"part": VIDEOS_PART, "id": ",".join(video_ids), "maxResults": BATCH_SIZE},
            headers={"X-Goog-Api-Key": api_key.get_secret_value()},
        )
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
    wanted = set(video_ids)
    out: dict[str, VideoInfo] = {}
    for item in items:
        info = _parse_item(item)
        if info is not None and info.video_id in wanted:
            out[info.video_id] = info
    return out
