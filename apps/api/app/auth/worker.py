"""워커 토큰 인증. 토큰 형식 `<worker_id>.<secret>`, DB에는 sha256(secret) hex만 저장한다.

형식 오류·UUID 아님·없음·해시 불일치·폐기는 모두 같은 401 UNAUTHENTICATED.
"""

import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass

import httpx
from fastapi import Request

from app.auth.bearer import bearer_token
from app.config import Settings
from app.errors import unauthenticated, upstream_error
from app.supabase import rest_url, service_headers

logger = logging.getLogger("nomadroom.auth")

_DUMMY_HASH = "0" * 64


@dataclass(frozen=True)
class CurrentWorker:
    worker_id: uuid.UUID
    workspace_id: uuid.UUID


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def format_token(worker_id: uuid.UUID, secret: str) -> str:
    return f"{worker_id}.{secret}"


def parse_token(token: str) -> tuple[uuid.UUID, str] | None:
    raw_id, sep, secret = token.partition(".")
    if not sep or not secret or len(raw_id) != 36:
        return None
    try:
        worker_id = uuid.UUID(raw_id)
    except ValueError:
        return None
    return worker_id, secret


async def authenticate_worker(
    token: str, settings: Settings, client: httpx.AsyncClient
) -> CurrentWorker:
    parsed = parse_token(token)
    if parsed is None:
        raise unauthenticated()
    worker_id, secret = parsed
    try:
        # worker_id는 UUID로 파싱된 값만 쿼리에 넣는다.
        resp = await client.get(
            rest_url(settings, "workers"),
            params={
                "select": "id,workspace_id,token_hash,revoked_at",
                "id": f"eq.{worker_id}",
            },
            headers=service_headers(settings),
        )
        resp.raise_for_status()
        rows = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("워커 조회 실패")
        raise upstream_error() from exc
    row = rows[0] if isinstance(rows, list) and len(rows) == 1 else None
    stored = row.get("token_hash") if isinstance(row, dict) else None
    if not isinstance(stored, str):
        stored = _DUMMY_HASH
    matched = hmac.compare_digest(hash_secret(secret), stored)
    if row is None or not matched or row.get("revoked_at") is not None:
        raise unauthenticated()
    try:
        return CurrentWorker(worker_id=worker_id, workspace_id=uuid.UUID(str(row["workspace_id"])))
    except (KeyError, ValueError) as exc:
        raise upstream_error() from exc


async def get_current_worker(request: Request) -> CurrentWorker:
    token = bearer_token(request)
    if token is None:
        raise unauthenticated()
    state = request.app.state
    return await authenticate_worker(token, state.settings, state.http)
