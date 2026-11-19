"""URL 원본(YouTube) 다운로드 — 로컬 워커 전용. 근거: tasks/task-031.md#착수-결정 G1~G9.

- yt-dlp Python API(YoutubeDL)만. 사용자 설정 파일·플러그인을 읽지 않고,
  쿠키·로그인·netrc를 쓰지 않는다.
- 추출기는 youtube 하나(generic 금지), 단일 합본 format(https, ≤1080p, mp4/webm)만 받는다.
  external_downloader·후처리기·fixup이 없어 yt-dlp가 ffmpeg를 부르지 않는다(ffmpeg 경로도 막는다).
- SSRF(G2): 연결마다 실제 접속 IP를 검사하는 전용 요청 핸들러(yt-dlp 요청 핸들러 수준)만 쓴다.
  리다이렉트도 새 연결이라 같은 검사를 거친다. 프로세스 전역 socket은 건드리지 않는다. 프록시 없음.
- 상한(G4): noplaylist, 라이브 거부, max_filesize·받은 바이트 상한, socket_timeout,
  전체 실행 시간 상한.
  구간(download_ranges)은 yt-dlp가 ffmpeg로만 처리하므로 쓰지 않고, 받은 파일을 prepare가 자른다
  (구현 결정 참고). 구간이 영상 길이 밖이면 받기 전에 range_invalid.
- 산출 파일은 기존 prepare(sniff·ffprobe·file_input)로만 읽는다.
- 로그·실패 detail에는 호스트와 오류 분류만(G9). URL 전체·yt-dlp 메시지는 쓰지 않는다.
"""

import functools
import http.client
import ipaddress
import logging
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yt_dlp.globals as ytdlp_globals
from yt_dlp import YoutubeDL
from yt_dlp.networking._helper import _socket_connect, create_connection
from yt_dlp.networking._urllib import (
    HTTPCookieProcessor,
    HTTPDefaultErrorHandler,
    HTTPErrorProcessor,
    HTTPHandler,
    ProxyHandler,
    RedirectHandler,
    UnknownHandler,
    UrllibRH,
)

from production.errors import TaskCancelled, TaskFailed
from production.media import Cancel
from production.paths import WorkDir

logger = logging.getLogger("nomadroom.worker.fetch_url")

MB = 1024 * 1024
MAX_INPUT_BYTES = 500 * MB  # runner.MAX_INPUT_BYTES와 같음(버킷 상한)
ALLOWED_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"})
SOCKET_TIMEOUT_SEC = 30
MAX_RUN_SEC = 20 * 60  # 추출+다운로드 전체 상한(별도 스레드 감시, 리뷰 반영 4)
WATCH_POLL_SEC = 0.5  # 감시 주기(취소·시간 상한 확인)
JOIN_GRACE_SEC = 5.0  # 중단 뒤 yt-dlp 스레드가 끝나길 기다리는 시간
# 리뷰 반영 3: 안쪽 4바이트가 IPv4인 IPv6 대역(NAT64·IPv4 호환·IPv4 매핑)은 IPv4로 다시 검사
_EMBEDDED_V4_NETS = tuple(
    ipaddress.IPv6Network(n) for n in ("64:ff9b::/96", "::/96", "::ffff:0:0/96")
)
RANGE_MARGIN_SEC = 0.05  # prepare와 같은 여유
FORMAT = (
    "best[height<=1080][ext=mp4][protocol=https][vcodec!=none][acodec!=none]"
    "/best[height<=1080][ext=webm][protocol=https][vcodec!=none][acodec!=none]"
)
_NO_FFMPEG = "nomadroom-no-ffmpeg"  # 존재하지 않는 이름(yt-dlp가 ffmpeg를 찾지 못하게)


class BlockedAddress(OSError):
    """접속하려는 IP가 공인 주소가 아님(사설·루프백·링크로컬·CGNAT·멀티캐스트 등)."""


class _Deadline(Exception):
    """전체 실행 시간 초과."""


class _TooLarge(Exception):
    """받은 바이트가 상한 초과."""


def url_host(url: str | None) -> str:
    """로그용 호스트(허용 목록 밖이면 '-')."""
    try:
        host = (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return "-"
    return host if host in ALLOWED_HOSTS else "-"


def check_url(url: str | None) -> str:
    """API 검사(apps/api/app/production/url_guard.py)를 워커에서 한 번 더(신뢰하지 않음)."""
    try:
        parts = urlsplit(url or "")
        port = parts.port
    except ValueError:
        raise TaskFailed("prepare", "url_unavailable", "URL 형식 오류") from None
    host = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or host not in ALLOWED_HOSTS
        or port not in (None, 443)
        or "@" in parts.netloc
        or any(c.isspace() or c == "\\" for c in url or "")
    ):
        raise TaskFailed("prepare", "url_unavailable", "허용되지 않은 URL")
    return host


def is_public_ip(ip: str) -> bool:
    """공인 유니캐스트만 True. NAT64(64:ff9b::/96)·IPv4 호환(::/96)·IPv4 매핑(::ffff:0:0/96)은
    마지막 4바이트를 IPv4로 꺼내 그 주소로 판단한다."""
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and any(addr in n for n in _EMBEDDED_V4_NETS):
        addr = ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
    return addr.is_global and not addr.is_multicast


class _Guard:
    """다운로드 1건의 연결 검사·중단·시간 상한 상태. 감시 스레드가 abort하면
    이후 훅·새 연결은 예외를 내고, 열린 소켓은 닫아 막힌 읽기도 깨운다."""

    def __init__(self, cancel: Cancel, deadline: float, clock: Callable[[], float]) -> None:
        self.cancel, self.deadline, self.clock = cancel, deadline, clock
        self.blocked = False
        self.aborted: type[Exception] | None = None
        self._lock = threading.Lock()
        self._socks: list[Any] = []

    def abort(self, reason: type[Exception]) -> None:
        with self._lock:
            if self.aborted is None:
                self.aborted = reason
            socks, self._socks = self._socks, []
        for sock in socks:
            try:
                sock.close()
            except OSError:
                pass

    def tick(self) -> None:
        if self.aborted is not None:
            raise self.aborted()
        self.cancel.check()
        if self.clock() > self.deadline:
            raise _Deadline()

    def connect(self, ip_addr: tuple, timeout: Any, source_address: Any) -> socket.socket:
        """yt-dlp create_connection의 주소별 소켓 함수. 실제로 접속할 IP를 검사한 뒤에만 연다."""
        self.tick()
        if not is_public_ip(str(ip_addr[4][0])):
            self.blocked = True
            raise BlockedAddress("차단 주소")
        sock = _socket_connect(ip_addr, timeout, source_address)
        with self._lock:
            if self.aborted is None:
                self._socks.append(sock)
                return sock
        sock.close()
        raise self.aborted()


def _guarded_rh(guard: _Guard) -> type[UrllibRH]:
    """https만·프록시 없음·연결별 IP 검사를 하는 urllib 요청 핸들러(다운로드마다 새로)."""

    def make_conn(source_address: Any, *args: Any, **kwargs: Any) -> http.client.HTTPSConnection:
        hc = http.client.HTTPSConnection(*args, **kwargs)
        hc._create_connection = functools.partial(  # type: ignore[attr-defined]
            create_connection, _create_socket_func=guard.connect
        )
        if source_address is not None:
            hc.source_address = (source_address, 0)
        return hc

    class GuardedHTTPHandler(HTTPHandler):
        def http_open(self, req: Any) -> Any:  # 리다이렉트로 http가 와도 거부
            guard.blocked = True
            raise urllib.error.URLError("http 거부")

        def https_open(self, req: Any) -> Any:
            if req.headers.pop("Ytdl-socks-proxy", None):
                raise urllib.error.URLError("프록시 거부")
            return self.do_open(
                functools.partial(make_conn, self._source_address), req, context=self._context
            )

    class GuardedUrllibRH(UrllibRH):
        _SUPPORTED_URL_SCHEMES = ("https",)
        _SUPPORTED_PROXY_SCHEMES = ()
        RH_NAME = "nomadroom-guarded"

        def _create_instance(self, proxies: Any, cookiejar: Any, legacy_ssl_support: Any = None):
            # ftp·data·file 처리기 없음(리다이렉트로 다른 프로토콜에 가지 않게)
            opener = urllib.request.OpenerDirector()
            for handler in (
                ProxyHandler({}),
                GuardedHTTPHandler(
                    debuglevel=0,
                    context=self._make_sslcontext(legacy_ssl_support=legacy_ssl_support),
                    source_address=self.source_address,
                ),
                HTTPCookieProcessor(cookiejar),
                UnknownHandler(),
                HTTPDefaultErrorHandler(),
                HTTPErrorProcessor(),
                RedirectHandler(),
            ):
                opener.add_handler(handler)
            opener.addheaders = []
            return opener

    return GuardedUrllibRH


class _GuardedYDL(YoutubeDL):
    """요청 핸들러를 검사 핸들러 하나로 고정(curl_cffi·requests·websockets 미사용)."""

    guard_rh: type[UrllibRH]

    def build_request_director(self, handlers: Any, preferences: Any = None) -> Any:
        return super().build_request_director([self.guard_rh], preferences)


class _SilentLogger:
    """yt-dlp 메시지에는 URL이 들어갈 수 있어 모두 버린다(G9)."""

    def debug(self, msg: str) -> None:
        pass

    info = warning = error = debug


def build_params(out_dir: Path, hook: Callable[[dict], None]) -> dict[str, Any]:
    """YoutubeDL 옵션. 쿠키·로그인·설정·플러그인·외부 다운로더·후처리 관련 키는 넣지 않는다."""
    return {
        "allowed_extractors": ["youtube"],
        "format": FORMAT,
        "noplaylist": True,
        "max_filesize": MAX_INPUT_BYTES,
        "socket_timeout": SOCKET_TIMEOUT_SEC,
        "retries": 1,
        "extractor_retries": 1,
        "fragment_retries": 0,
        "outtmpl": {"default": "source.%(ext)s"},
        "paths": {"home": str(out_dir), "temp": str(out_dir)},
        "restrictfilenames": True,
        "overwrites": True,
        "continuedl": False,
        "fixup": "never",
        "postprocessors": [],
        "ffmpeg_location": str(out_dir / _NO_FFMPEG),
        "proxy": "",
        "js_runtimes": {},
        "remote_components": [],
        "cachedir": False,
        "check_formats": False,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _SilentLogger(),
        "progress_hooks": [hook],
    }


def _new_ydl(params: dict[str, Any], guard: _Guard) -> YoutubeDL:
    ytdlp_globals.plugin_dirs.value = []  # 플러그인 미로드(G5)
    ydl_cls = type("NomadroomYDL", (_GuardedYDL,), {"guard_rh": _guarded_rh(guard)})
    return ydl_cls(params)


def _check_info(info: Any, start: float, length: float | None) -> None:
    if not isinstance(info, dict) or info.get("_type", "video") != "video":
        raise TaskFailed("prepare", "url_unavailable", "단일 영상 아님")
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
        raise TaskFailed("prepare", "url_unavailable", "라이브 거부")
    size = info.get("filesize") or info.get("filesize_approx")
    if isinstance(size, int | float) and size > MAX_INPUT_BYTES:
        raise TaskFailed("prepare", "url_unavailable", "크기 상한 초과")
    duration = info.get("duration")
    if isinstance(duration, int | float) and duration > 0:
        end = start + (length or 0.0)
        if start >= duration or end > duration + RANGE_MARGIN_SEC:
            raise TaskFailed("prepare", "range_invalid", "구간이 원본 밖")


def fetch_url(
    url: str | None,
    work: WorkDir,
    cancel: Cancel,
    on_progress: Callable[[str, int], None],
    start: float = 0.0,
    length: float | None = None,
    ydl_factory: Callable[[dict[str, Any], _Guard], YoutubeDL] = _new_ydl,
    clock: Callable[[], float] = time.monotonic,
) -> Path:
    """URL 원본을 작업 폴더에 받아 경로를 돌려준다.
    실패는 TaskFailed(prepare, url_unavailable·range_invalid·download_failed)."""
    host = check_url(url)
    out_dir = work.path("url_download")
    out_dir.mkdir()
    guard = _Guard(cancel, clock() + MAX_RUN_SEC, clock)

    def hook(d: dict) -> None:
        guard.tick()
        got = d.get("downloaded_bytes") or 0
        if got > MAX_INPUT_BYTES:
            raise _TooLarge()
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if total:
            on_progress("download", min(99, int(got * 100 / total)))

    def fail(code: str, kind: str) -> TaskFailed:
        logger.info("URL 원본 실패: host=%s 분류=%s", host, kind)
        return TaskFailed("prepare", code, f"host={host} {kind}")

    result: dict[str, Exception] = {}

    def body() -> None:
        try:
            with ydl_factory(build_params(out_dir, hook), guard) as ydl:
                info = ydl.extract_info(url, download=False)
                guard.tick()
                _check_info(info, start, length)
                ydl.process_ie_result(info, download=True)
                guard.tick()
        except Exception as exc:  # 감시 스레드(호출자)에서 분류
            result["exc"] = exc

    logger.info("URL 원본 다운로드 시작: host=%s", host)
    # 리뷰 반영 4: yt-dlp를 별도 스레드에서 돌리고 여기서 취소·전체 시간을 감시한다
    # (훅이 불리지 않는 느린 응답에도 상한이 듣게).
    worker = threading.Thread(target=body, name="fetch-url", daemon=True)
    worker.start()
    while worker.is_alive():
        worker.join(WATCH_POLL_SEC)
        if not worker.is_alive():
            break
        if cancel.is_set:
            guard.abort(TaskCancelled)
        elif clock() > guard.deadline:
            guard.abort(_Deadline)
        if guard.aborted is not None:
            worker.join(JOIN_GRACE_SEC)
            break
    exc = result.get("exc")
    if guard.aborted is not None and not isinstance(exc, guard.aborted):
        exc = guard.aborted()  # 소켓을 닫아 생긴 오류도 중단 사유로 분류
    try:
        if exc is not None:
            raise exc
    except TaskCancelled:
        raise
    except TaskFailed as f:
        raise fail(f.code, f.detail) from None
    except _Deadline:
        raise fail("download_failed", "시간 상한 초과") from None
    except _TooLarge:
        raise fail("url_unavailable", "크기 상한 초과") from None
    except Exception:  # yt-dlp 오류 원문은 URL을 담을 수 있어 분류만
        cancel.check()
        raise fail(
            "url_unavailable", "차단 주소" if guard.blocked else "추출·다운로드 실패"
        ) from None

    files = [p for p in out_dir.iterdir() if p.is_file() and p.name.startswith("source.")]
    if len(files) != 1 or files[0].suffix not in (".mp4", ".webm"):
        raise fail("url_unavailable", "파일 없음(크기 상한 등)")
    if files[0].stat().st_size > MAX_INPUT_BYTES:
        raise fail("url_unavailable", "크기 상한 초과")
    on_progress("download", 100)
    logger.info("URL 원본 다운로드 완료: host=%s", host)
    return files[0]
