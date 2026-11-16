"""사용자 의존성: Supabase JWT 검증 + workspace_members 소속 확인으로 workspace_id를 정한다.

workspace_id는 요청 입력으로 받지 않는다. 소속은 매 요청 확인한다(소속 제거 즉시 반영).
"""

import logging
import uuid
from dataclasses import dataclass

import httpx
import jwt
from fastapi import Request

from app.auth.bearer import bearer_token
from app.auth.jwks import JwksCache, JwksUnavailable, UnknownKid
from app.config import Settings
from app.errors import forbidden, unauthenticated, upstream_error
from app.supabase import rest_url, service_headers

logger = logging.getLogger("nomadroom.auth")

AUDIENCE = "authenticated"


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    workspace_id: uuid.UUID


async def verify_jwt(
    token: str, settings: Settings, jwks: JwksCache, client: httpx.AsyncClient
) -> uuid.UUID:
    """서명·exp·aud·iss·sub·role 검증 후 사용자 UUID를 돌려준다. 실패는 401, JWKS 문제는 503."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise unauthenticated() from exc
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise unauthenticated()
    try:
        vk = await jwks.get_key(client, kid)
    except UnknownKid as exc:
        raise unauthenticated() from exc
    except JwksUnavailable as exc:
        logger.warning("JWKS를 사용할 수 없음")
        raise upstream_error() from exc
    try:
        claims = jwt.decode(
            token,
            vk.key,
            algorithms=[vk.algorithm],
            audience=AUDIENCE,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "aud", "iss", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise unauthenticated() from exc
    if claims.get("role") != AUDIENCE:
        raise unauthenticated()
    try:
        return uuid.UUID(str(claims["sub"]))
    except ValueError as exc:
        raise unauthenticated() from exc


async def resolve_workspace(
    user_id: uuid.UUID, settings: Settings, client: httpx.AsyncClient
) -> uuid.UUID:
    """소속 0행·2행 이상은 403(MVP는 사용자당 워크스페이스 1개). 임의로 하나를 고르지 않는다."""
    try:
        resp = await client.get(
            rest_url(settings, "workspace_members"),
            params={"select": "workspace_id", "user_id": f"eq.{user_id}"},
            headers=service_headers(settings),
        )
        resp.raise_for_status()
        rows = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("소속 조회 실패")
        raise upstream_error() from exc
    if not isinstance(rows, list) or len(rows) != 1:
        raise forbidden()
    try:
        return uuid.UUID(str(rows[0]["workspace_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise upstream_error() from exc


async def get_current_user(request: Request) -> CurrentUser:
    token = bearer_token(request)
    if token is None:
        raise unauthenticated()
    state = request.app.state
    user_id = await verify_jwt(token, state.settings, state.jwks, state.http)
    workspace_id = await resolve_workspace(user_id, state.settings, state.http)
    return CurrentUser(user_id=user_id, workspace_id=workspace_id)
