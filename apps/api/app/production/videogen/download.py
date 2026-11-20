"""AI 생성 결과 영상 다운로드(task-054 G6, SSRF 방어).

- URL: https·사용자 정보 없음·포트 443·IP 리터럴 금지·어댑터 허용 호스트만.
- DNS: 해석 결과가 하나라도 공인(global) 주소가 아니면 거부(사설·루프백·링크로컬·예약).
- 리다이렉트: 자동 추적 끔, 같은 검사를 통과한 대상만 최대 3회.
- 본문: 스트리밍으로 200MB 상한, mp4 `ftyp` 시그니처 확인.
- 남은 위험: 검사 뒤 연결 시점의 재해석(DNS rebinding)은 막지 못한다(허용 호스트로 범위를 줄임).
URL·응답 원문은 로그·예외에 넣지 않는다.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlsplit

import httpx

MAX_RESULT_BYTES = 200 * 1024 * 1024
MAX_REDIRECTS = 3
_REDIRECTS = frozenset({301, 302, 303, 307, 308})

Resolver = Callable[[str], Awaitable[list[str]]]


class DownloadRejected(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def resolve(host: str) -> list[str]:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise DownloadRejected("dns_failed") from exc
    return [str(info[4][0]) for info in infos]


def check_url(url: str, hosts: frozenset[str]) -> str:
    """허용되면 호스트(소문자)를 돌려준다."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise DownloadRejected("bad_url") from None
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or "@" in parts.netloc or port not in (None, 443):
        raise DownloadRejected("bad_url")
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        raise DownloadRejected("ip_literal")
    if host not in hosts:
        raise DownloadRejected("host_not_allowed")
    return host


async def check_dns(host: str, resolver: Resolver) -> None:
    addrs = await resolver(host)
    if not addrs:
        raise DownloadRejected("dns_failed")
    for raw in addrs:
        try:
            ip = ipaddress.ip_address(raw.split("%", 1)[0])
        except ValueError:
            raise DownloadRejected("dns_failed") from None
        if not ip.is_global or ip.is_multicast:
            raise DownloadRejected("private_address")


async def fetch_video(
    client: httpx.AsyncClient,
    url: str,
    hosts: frozenset[str],
    *,
    timeout: float,
    resolver: Resolver | None = None,
    max_bytes: int = MAX_RESULT_BYTES,
) -> bytes:
    for _ in range(MAX_REDIRECTS + 1):
        host = check_url(url, hosts)
        await check_dns(host, resolver or resolve)
        try:
            async with client.stream("GET", url, timeout=timeout, follow_redirects=False) as resp:
                if resp.status_code in _REDIRECTS:
                    location = resp.headers.get("location")
                    if not location:
                        raise DownloadRejected("bad_redirect")
                    url = urljoin(url, location)
                    continue
                if resp.status_code != 200:
                    raise DownloadRejected(f"http_{resp.status_code}")
                length = resp.headers.get("content-length")
                if length is not None and length.isdigit() and int(length) > max_bytes:
                    raise DownloadRejected("too_large")
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf += chunk
                    if len(buf) > max_bytes:
                        raise DownloadRejected("too_large")
        except httpx.HTTPError as exc:
            raise DownloadRejected("network") from exc
        if len(buf) < 12 or bytes(buf[4:8]) != b"ftyp":
            raise DownloadRejected("not_mp4")
        return bytes(buf)
    raise DownloadRejected("too_many_redirects")
