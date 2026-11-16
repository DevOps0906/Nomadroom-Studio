"""Supabase JWKS 조회·캐시.

비대칭 키(ES256·RS256)만 쓰고, 알고리즘은 JWK에서 정한다(헤더 alg 불신).
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

ALLOWED_ALGS = frozenset({"ES256", "RS256"})
JWKS_TTL_SECONDS = 600.0
UNKNOWN_KID_REFETCH_SECONDS = 60.0
FAILURE_RETRY_SECONDS = 60.0


class JwksUnavailable(Exception):
    """JWKS 조회 실패 또는 쓸 수 있는 키가 하나도 없음(서버 쪽 문제)."""


class UnknownKid(Exception):
    """토큰의 kid가 JWKS에 없음(토큰 쪽 문제)."""


@dataclass(frozen=True)
class VerifyKey:
    key: Any
    algorithm: str


def _algorithm_for(jwk: dict[str, Any]) -> str | None:
    kty = jwk.get("kty")
    if kty == "EC" and jwk.get("crv") == "P-256":
        alg = "ES256"
    elif kty == "RSA":
        alg = "RS256"
    else:
        return None
    declared = jwk.get("alg")
    if declared is not None and declared != alg:
        return None
    if jwk.get("use") not in (None, "sig"):
        return None
    return alg


def parse_jwks(payload: Any) -> dict[str, VerifyKey]:
    keys: dict[str, VerifyKey] = {}
    if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
        return keys
    for jwk in payload["keys"]:
        if not isinstance(jwk, dict) or not isinstance(jwk.get("kid"), str):
            continue
        alg = _algorithm_for(jwk)
        if alg is None or alg not in ALLOWED_ALGS:
            continue
        try:
            key = jwt.PyJWK(jwk, algorithm=alg).key
        except jwt.PyJWTError, ValueError, TypeError:
            continue
        keys[jwk["kid"]] = VerifyKey(key=key, algorithm=alg)
    return keys


class JwksCache:
    def __init__(
        self,
        url: str,
        ttl: float = JWKS_TTL_SECONDS,
        unknown_kid_interval: float = UNKNOWN_KID_REFETCH_SECONDS,
        failure_retry: float = FAILURE_RETRY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._url = url
        self._ttl = ttl
        self._unknown_kid_interval = unknown_kid_interval
        self._clock = clock
        self._keys: dict[str, VerifyKey] | None = None
        self._fetched_at = 0.0
        self._last_attempt: float | None = None
        self._failure_retry = failure_retry
        self._failed_at: float | None = None
        self._lock = asyncio.Lock()

    async def _refresh(self, client: httpx.AsyncClient) -> None:
        self._last_attempt = self._clock()
        try:
            resp = await client.get(self._url)
            resp.raise_for_status()
            keys = parse_jwks(resp.json())
        except (httpx.HTTPError, ValueError) as exc:
            self._failed_at = self._clock()
            raise JwksUnavailable("JWKS 조회 실패") from exc
        if not keys:
            self._failed_at = self._clock()
            raise JwksUnavailable("JWKS에 쓸 수 있는 키 없음")
        self._keys = keys
        self._fetched_at = self._clock()
        self._failed_at = None

    async def get_key(self, client: httpx.AsyncClient, kid: str) -> VerifyKey:
        async with self._lock:
            now = self._clock()
            if self._keys is None or now - self._fetched_at >= self._ttl:
                # 만료된 키는 쓰지 않는다. 직전 조회가 실패했으면 대기 시간 동안 바로 503
                # (동시 요청이 조회 타임아웃만큼 줄 서지 않게).
                self._keys = None
                if self._failed_at is not None and now - self._failed_at < self._failure_retry:
                    raise JwksUnavailable("JWKS 조회 실패 후 재시도 대기 중")
                await self._refresh(client)
            assert self._keys is not None  # noqa: S101 - _refresh 성공 후 항상 채워짐
            found = self._keys.get(kid)
            if found is None and (
                self._last_attempt is None
                or self._clock() - self._last_attempt >= self._unknown_kid_interval
            ):
                await self._refresh(client)
                found = self._keys.get(kid)
            if found is None:
                raise UnknownKid(kid)
            return found
