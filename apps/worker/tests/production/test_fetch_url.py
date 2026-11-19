"""task-031 URL 원본(yt-dlp) 테스트. 실제 네트워크·다운로드 없음(YoutubeDL은 가짜, 소켓 접속은 목).

근거: tasks/task-031.md#착수-결정 G1~G9.
"""

import logging
import shutil
import socket
import uuid
from pathlib import Path

import pytest
from worker_fakes import make_task, needs_ffmpeg

from production import fetch_url as fu
from production.errors import TaskCancelled, TaskFailed
from production.media import Cancel
from production.paths import WorkDir
from production.runner import run_task

YT = "https://www.youtube.com/watch?v=abcdefghijk&secret_q=1"
FORBIDDEN_KEYS = {
    "cookiefile",
    "cookiesfrombrowser",
    "usenetrc",
    "netrc_location",
    "netrc_cmd",
    "username",
    "password",
    "videopassword",
    "ap_username",
    "ap_password",
    "external_downloader",
    "external_downloader_args",
    "postprocessor_args",
    "config_locations",
    "plugin_dirs",
    "download_ranges",  # ffmpeg 강제(구현 결정 U1)
}


@pytest.fixture
def work(tmp_path) -> WorkDir:
    w = WorkDir(tmp_path, uuid.uuid4())
    w.reset()
    return w


class FakeYDL:
    """YoutubeDL 대역. info와 다운로드 동작(훅 호출·파일 쓰기·예외)을 지정한다."""

    instances: list[FakeYDL] = []

    def __init__(self, params, guard, info=None, download=None, extract_error=None):
        self.params, self.guard = params, guard
        self.info = info if info is not None else {"_type": "video", "duration": 300}
        self.download, self.extract_error = download, extract_error
        self.downloaded = False
        FakeYDL.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        assert download is False
        if self.extract_error:
            raise self.extract_error
        return self.info

    def process_ie_result(self, info, download=True):
        self.downloaded = True
        if self.download:
            self.download(self)
        else:
            write_file(self, b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)


def write_file(ydl: FakeYDL, data: bytes, name: str = "source.mp4") -> None:
    hook = ydl.params["progress_hooks"][0]
    hook({"status": "downloading", "downloaded_bytes": len(data), "total_bytes": len(data)})
    Path(ydl.params["paths"]["home"], name).write_bytes(data)


def factory(**kw):
    FakeYDL.instances = []
    return lambda params, guard: FakeYDL(params, guard, **kw)


def run(work, ydl_factory, cancel=None, start=0.0, length=60.0, url=YT, **kw):
    progress: list[tuple[str, int]] = []
    path = fu.fetch_url(
        url,
        work,
        cancel or Cancel(),
        lambda s, p: progress.append((s, p)),
        start,
        length,
        ydl_factory=ydl_factory,
        **kw,
    )
    return path, progress


# === 옵션(G3·G4·G5) =================================================================


def test_params_have_no_cookie_login_config_plugin_or_external_downloader(tmp_path):
    p = fu.build_params(tmp_path, lambda d: None)
    assert FORBIDDEN_KEYS.isdisjoint(p)
    assert p["allowed_extractors"] == ["youtube"]
    assert p["postprocessors"] == [] and p["fixup"] == "never"
    assert p["noplaylist"] is True
    assert p["max_filesize"] == 500 * 1024 * 1024
    assert p["socket_timeout"] == fu.SOCKET_TIMEOUT_SEC
    assert p["proxy"] == "" and p["js_runtimes"] == {} and p["remote_components"] == []
    assert "protocol=https" in p["format"] and "height<=1080" in p["format"]
    assert "+" not in p["format"]  # 합본 단일 format만(병합 = ffmpeg 금지)
    assert not Path(p["ffmpeg_location"]).exists()


def test_real_ydl_loads_only_youtube_extractor_no_plugins_no_cookies(tmp_path):
    guard = fu._Guard(Cancel(), 1e18, lambda: 0.0)
    with fu._new_ydl(fu.build_params(tmp_path, lambda d: None), guard) as ydl:
        assert list(ydl._ies) == ["Youtube"]
        assert fu.ytdlp_globals.plugin_dirs.value == []
        assert len(ydl.cookiejar) == 0
        handlers = list(ydl._request_director.handlers.values())
        assert len(handlers) == 1 and handlers[0].RH_NAME == "nomadroom-guarded"
        assert ydl.params.get("cookiefile") is None and not ydl.params.get("usenetrc")
        assert ydl.params.get("external_downloader") is None


# === SSRF: 연결별 IP 검사(G2) ======================================================


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "224.0.0.1",
        "0.0.0.0",  # noqa: S104
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:10.0.0.1",
        "ff02::1",
        "64:ff9b::a00:1",  # NAT64 → 10.0.0.1
        "64:ff9b::7f00:1",  # NAT64 → 127.0.0.1
        "::a9fe:a9fe",  # IPv4 호환 → 169.254.169.254
        "::7f00:1",  # IPv4 호환 → 127.0.0.1
        "::ffff:192.168.1.1",
    ],
)
def test_private_ips_rejected(ip):
    assert fu.is_public_ip(ip) is False


def test_guard_connect_blocks_private_and_allows_public(monkeypatch):
    calls = []
    monkeypatch.setattr(fu, "_socket_connect", lambda a, t, s: calls.append(a[4][0]) or "sock")
    guard = fu._Guard(Cancel(), 1e18, lambda: 0.0)
    v4 = (socket.AF_INET, socket.SOCK_STREAM, 6, "")
    with pytest.raises(fu.BlockedAddress):
        guard.connect((*v4, ("10.0.0.8", 443)), 5, None)
    assert guard.blocked and calls == []
    assert guard.connect((*v4, ("142.250.0.1", 443)), 5, None) == "sock"
    assert calls == ["142.250.0.1"]


def _resolve_to(monkeypatch, ip: str) -> list:
    seen = []

    def fake_getaddrinfo(host, port, *a, **k):
        seen.append(host)
        fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(fam, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    return seen


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.7", "169.254.169.254", "::1"])
def test_request_handler_rejects_resolved_private_ip(tmp_path, monkeypatch, ip):
    """yt-dlp 요청 경로 그대로: 호스트가 사설 IP로 해석되면 접속 전에 막힌다
    (리다이렉트도 새 연결이라 같은 경로)."""
    seen = _resolve_to(monkeypatch, ip)
    monkeypatch.setattr(fu, "_socket_connect", lambda *a: pytest.fail("접속 시도 금지"))
    guard = fu._Guard(Cancel(), 1e18, lambda: 0.0)
    with fu._new_ydl(fu.build_params(tmp_path, lambda d: None), guard) as ydl:
        with pytest.raises(Exception):  # noqa: B017  (yt-dlp TransportError)
            ydl.urlopen("https://www.youtube.com/watch?v=x")
    assert guard.blocked and seen == ["www.youtube.com"]


@pytest.mark.parametrize("url", ["http://www.youtube.com/", "file:///etc/passwd", "ftp://x/"])
def test_request_handler_rejects_non_https(tmp_path, monkeypatch, url):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("조회 금지"))
    guard = fu._Guard(Cancel(), 1e18, lambda: 0.0)
    with fu._new_ydl(fu.build_params(tmp_path, lambda d: None), guard) as ydl:
        with pytest.raises(Exception):  # noqa: B017  (yt-dlp UnsupportedRequest·RequestError)
            ydl.urlopen(url)


def test_ip_block_during_fetch_is_url_unavailable(work):
    def blocked(ydl):
        ydl.guard.blocked = True
        raise RuntimeError("Unable to download https://10.0.0.1/secret")

    with pytest.raises(TaskFailed) as e:
        run(work, factory(download=blocked))
    assert e.value.code == "url_unavailable" and "차단 주소" in e.value.detail
    assert "10.0.0.1" not in e.value.detail and "secret" not in e.value.detail


# === URL 재검사(G1) ================================================================


@pytest.mark.parametrize(
    "url",
    [
        None,
        "http://www.youtube.com/watch?v=x",
        "https://127.0.0.1/v",
        "https://[::1]/v",
        "file:///etc/passwd",
        "https://vimeo.com/1",
        "https://www.youtube.com:8443/v",
        "https://u@www.youtube.com/v",
    ],
)
def test_worker_rechecks_url(work, url):
    with pytest.raises(TaskFailed) as e:
        run(work, factory(), url=url)
    assert e.value.code == "url_unavailable"
    assert FakeYDL.instances == []


# === 상한(G4) ======================================================================


@pytest.mark.parametrize(
    "info",
    [
        {"_type": "video", "is_live": True},
        {"_type": "video", "live_status": "is_upcoming"},
        {"_type": "playlist", "entries": []},
        {"_type": "video", "filesize": 600 * 1024 * 1024},
    ],
)
def test_live_playlist_and_too_big_rejected_before_download(work, info):
    with pytest.raises(TaskFailed) as e:
        run(work, factory(info=info))
    assert e.value.code == "url_unavailable"
    assert FakeYDL.instances[0].downloaded is False


@pytest.mark.parametrize("start,length", [(290.0, 60.0), (300.0, 1.0)])
def test_range_outside_duration_is_range_invalid(work, start, length):
    with pytest.raises(TaskFailed) as e:
        run(work, factory(info={"_type": "video", "duration": 300}), start=start, length=length)
    assert e.value.code == "range_invalid"
    assert FakeYDL.instances[0].downloaded is False


def test_downloaded_bytes_over_limit_stops(work):
    def huge(ydl):
        ydl.params["progress_hooks"][0]({"downloaded_bytes": fu.MAX_INPUT_BYTES + 1})

    with pytest.raises(TaskFailed) as e:
        run(work, factory(download=huge))
    assert e.value.code == "url_unavailable"


def test_missing_file_after_max_filesize_skip(work):
    with pytest.raises(TaskFailed) as e:
        run(work, factory(download=lambda ydl: None))
    assert e.value.code == "url_unavailable"


def test_total_time_limit(work):
    now = [0.0]

    def slow(ydl):
        now[0] = fu.MAX_RUN_SEC + 1
        ydl.params["progress_hooks"][0]({"downloaded_bytes": 1})

    with pytest.raises(TaskFailed) as e:
        run(work, factory(download=slow), clock=lambda: now[0])
    assert e.value.code == "download_failed"


# === 중단(G7)·성공·로그(G9) ========================================================


def test_progress_hook_checks_cancel(work):
    cancel = Cancel()

    def cancelled(ydl):
        cancel.trigger()
        ydl.params["progress_hooks"][0]({"downloaded_bytes": 1})

    with pytest.raises(TaskCancelled):
        run(work, factory(download=cancelled), cancel=cancel)


def test_extractor_error_is_url_unavailable_without_message(work, caplog):
    caplog.set_level(logging.DEBUG)
    err = RuntimeError(f"Sign in to confirm you're not a bot {YT}")
    with pytest.raises(TaskFailed) as e:
        run(work, factory(extract_error=err))
    assert e.value.code == "url_unavailable"
    assert "watch" not in e.value.detail and "Sign in" not in e.value.detail
    assert "abcdefghijk" not in caplog.text and "secret_q" not in caplog.text


def test_success_returns_file_and_logs_host_only(work, caplog):
    caplog.set_level(logging.DEBUG)
    path, progress = run(work, factory())
    assert path.name == "source.mp4" and path.is_relative_to(work.dir)
    assert progress[-1] == ("download", 100)
    assert "host=www.youtube.com" in caplog.text
    assert "abcdefghijk" not in caplog.text and "secret_q" not in caplog.text
    assert FakeYDL.instances[0].params["outtmpl"] == {"default": "source.%(ext)s"}


def test_unexpected_extension_rejected(work):
    with pytest.raises(TaskFailed) as e:
        run(work, factory(download=lambda ydl: write_file(ydl, b"x", "source.mkv")))
    assert e.value.code == "url_unavailable"


# === runner 연결 ====================================================================


def test_runner_url_failure_reports_url_unavailable(api, server, media, tmp_path, monkeypatch):
    def fail(*a, **k):
        raise TaskFailed("prepare", "url_unavailable", "host=www.youtube.com 추출·다운로드 실패")

    monkeypatch.setattr("production.runner.fetch_url", fail)
    task = make_task("prepare", source_kind="url", source_url=YT, segment_len_sec=3.0)
    assert run_task(api, task, tmp_path, media, 60) == "failed"
    assert server.finished[-1] == {
        "status": "failed",
        "error_stage": "prepare",
        "error_code": "url_unavailable",
    }
    assert not [c for c in server.calls if c[1].endswith("/inputs")]  # W-06 업로드 경로 미사용


@needs_ffmpeg
def test_runner_url_success_uses_local_file(api, server, media, samples, tmp_path, monkeypatch):
    got = {}

    def fake_fetch(url, work, cancel, on_progress, start, length):
        got.update(url=url, start=start, length=length)
        dest = work.path("url_download")
        dest.mkdir()
        return Path(shutil.copy(samples["src"], dest / "source.mp4"))

    monkeypatch.setattr("production.runner.fetch_url", fake_fetch)
    task = make_task(
        "prepare", source_kind="url", source_url=YT, source_start_sec=0.5, segment_len_sec=2.0
    )
    assert run_task(api, task, tmp_path, media, 60) == "done"
    assert got == {"url": YT, "start": 0.5, "length": 2.0}
    assert server.finished[-1]["status"] == "done"
    assert not [c for c in server.calls if c[1].endswith("/inputs")]


# === 리뷰 반영 3·4 ==================================================================


@pytest.mark.parametrize("ip", ["8.8.8.8", "64:ff9b::808:808", "::ffff:8.8.8.8", "2001:4860::8888"])
def test_public_ips_allowed_including_embedded_v4(ip):
    assert fu.is_public_ip(ip) is True


def test_abort_closes_open_sockets_and_blocks_new_connections(monkeypatch):
    class Sock:
        closed = False

        def close(self):
            self.closed = True

    sock = Sock()
    monkeypatch.setattr(fu, "_socket_connect", lambda *a: sock)
    guard = fu._Guard(Cancel(), 1e18, lambda: 0.0)
    v4 = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("142.250.0.1", 443))
    assert guard.connect(v4, 5, None) is sock
    guard.abort(fu._Deadline)
    assert sock.closed  # 막힌 읽기를 깨운다
    with pytest.raises(fu._Deadline):
        guard.connect(v4, 5, None)
    with pytest.raises(fu._Deadline):
        guard.tick()


@pytest.fixture
def fast_watch(monkeypatch):
    monkeypatch.setattr(fu, "WATCH_POLL_SEC", 0.02)
    monkeypatch.setattr(fu, "JOIN_GRACE_SEC", 0.5)


def _hanging_extract(release):
    """훅도 연결 검사도 거치지 않고 멈춘 추출(느린 응답). release가 set되면 풀린다."""

    def factory_(params, guard):
        ydl = FakeYDL(params, guard)
        ydl.extract_info = lambda url, download=True: release.wait(10) and None
        return ydl

    return factory_


def test_slow_extraction_hits_time_limit(work, monkeypatch, fast_watch):
    import threading
    import time

    monkeypatch.setattr(fu, "MAX_RUN_SEC", 0.2)
    release = threading.Event()
    t0 = time.monotonic()
    try:
        with pytest.raises(TaskFailed) as e:
            run(work, _hanging_extract(release))
    finally:
        release.set()
    assert e.value.code == "download_failed" and "시간 상한" in e.value.detail
    assert time.monotonic() - t0 < 5


def test_slow_extraction_cancel(work, fast_watch):
    import threading
    import time

    release = threading.Event()
    cancel = Cancel()
    threading.Timer(0.1, cancel.trigger).start()
    t0 = time.monotonic()
    try:
        with pytest.raises(TaskCancelled):
            run(work, _hanging_extract(release), cancel=cancel)
    finally:
        release.set()
    assert time.monotonic() - t0 < 5
