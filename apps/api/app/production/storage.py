"""제작 Storage(비공개 버킷 production) 서명 URL·객체 확인. 근거: docs/05_DATA_MODEL.md#storage.

서명 URL·토큰·객체 경로는 로그·예외 메시지에 넣지 않는다(작업 이름과 상태 코드만).
업로드 서명(/object/upload/sign)은 만료를 지정할 수 없어 Supabase 기본값(실측 2시간,
tasks/task-022.md#구현 결정)을 그대로 쓰고, 응답 expires_at은 토큰의 exp로 계산한다.
"""

import base64
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from app.config import Settings
from app.errors import ApiError
from app.supabase import service_headers

logger = logging.getLogger("nomadroom.production.storage")

BUCKET = "production"
MAX_UPLOAD_BYTES = 524_288_000  # 500MB(01_PRD.md#7 Q8 확정, 버킷 file_size_limit과 같은 값)
DOWNLOAD_EXPIRES_SEC = 600  # 04_API.md#제작-api: 다운로드 10분
UPLOAD_EXPIRES_FALLBACK_SEC = 7200  # 토큰에 exp가 없을 때만(실측 기본값)


def storage_error() -> ApiError:
    return ApiError(503, "UPSTREAM_ERROR", "파일 저장소 요청에 실패했습니다.")


def object_path(
    workspace_id: uuid.UUID | str, job_id: uuid.UUID | str, asset_id: uuid.UUID | str, ext: str
) -> str:
    """{workspace_id}/{job_id}/{asset_id}.{ext} — 값은 모두 서버가 만든 uuid·허용 확장자."""
    return f"{workspace_id}/{job_id}/{asset_id}.{ext}"


def _base(settings: Settings) -> str:
    return f"{settings.supabase_url}/storage/v1"


async def _call(
    client: httpx.AsyncClient, settings: Settings, op: str, method: str, url: str, **kwargs: Any
) -> httpx.Response:
    try:
        return await client.request(method, url, headers=service_headers(settings), **kwargs)
    except httpx.HTTPError as exc:
        logger.warning("파일 저장소 연결 실패: %s", op)
        raise storage_error() from exc


def _json(resp: httpx.Response, op: str) -> dict:
    if resp.status_code >= 400:
        logger.warning("파일 저장소 오류 %s: %s", resp.status_code, op)
        raise storage_error()
    try:
        body = resp.json()
    except ValueError as exc:
        raise storage_error() from exc
    if not isinstance(body, dict):
        raise storage_error()
    return body


def _token_exp(url: str) -> datetime | None:
    token = parse_qs(urlsplit(url).query).get("token", [""])[0]
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        return datetime.fromtimestamp(int(payload["exp"]), UTC)
    except ValueError, KeyError, TypeError:
        return None


async def sign_upload(
    client: httpx.AsyncClient, settings: Settings, path: str
) -> tuple[str, datetime]:
    """단일 객체 PUT 서명 URL(덮어쓰기 끔). (url, expires_at)."""
    resp = await _call(
        client,
        settings,
        "upload/sign",
        "POST",
        f"{_base(settings)}/object/upload/sign/{BUCKET}/{path}",
    )
    rel = _json(resp, "upload/sign").get("url")
    if not isinstance(rel, str) or not rel.startswith("/"):
        raise storage_error()
    url = f"{_base(settings)}{rel}"
    exp = _token_exp(url) or datetime.now(UTC) + timedelta(seconds=UPLOAD_EXPIRES_FALLBACK_SEC)
    return url, exp


async def sign_download(
    client: httpx.AsyncClient, settings: Settings, path: str, expires_in: int = DOWNLOAD_EXPIRES_SEC
) -> tuple[str, datetime]:
    """단일 객체 GET 서명 URL. (url, expires_at)."""
    now = datetime.now(UTC)
    resp = await _call(
        client,
        settings,
        "object/sign",
        "POST",
        f"{_base(settings)}/object/sign/{BUCKET}/{path}",
        json={"expiresIn": expires_in},
    )
    rel = _json(resp, "object/sign").get("signedURL")
    if not isinstance(rel, str) or not rel.startswith("/"):
        raise storage_error()
    return f"{_base(settings)}{rel}", now + timedelta(seconds=expires_in)


async def object_size(client: httpx.AsyncClient, settings: Settings, path: str) -> int | None:
    """객체 크기(바이트). 객체가 없으면 None."""
    resp = await _call(
        client, settings, "object/info", "GET", f"{_base(settings)}/object/info/{BUCKET}/{path}"
    )
    if resp.status_code in (400, 404):
        return None
    size = _json(resp, "object/info").get("size")
    if not isinstance(size, int) or isinstance(size, bool):
        raise storage_error()
    return size


async def delete_object(client: httpx.AsyncClient, settings: Settings, path: str) -> None:
    """객체 삭제(없어도 성공으로 본다)."""
    resp = await _call(
        client, settings, "object/delete", "DELETE", f"{_base(settings)}/object/{BUCKET}/{path}"
    )
    if resp.status_code >= 400 and resp.status_code not in (400, 404):
        logger.warning("파일 저장소 오류 %s: object/delete", resp.status_code)
        raise storage_error()
