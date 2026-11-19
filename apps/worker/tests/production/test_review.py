"""리뷰 반영(1~9) 확인."""

import inspect
import logging
import subprocess
import sys
import uuid

import httpx
import pytest
from worker_fakes import FFMPEG, make_spec, make_task, needs_ffmpeg

import main as worker_main
from production import api as api_mod
from production.api import SignedUrl, WorkerApi
from production.config import Settings
from production.errors import ApiCallError, TaskCancelled
from production.media import Cancel, Media, MediaError, MediaTimeout, sniff
from production.paths import WorkDir, clean_root
from production.runner import run_task


def _render_task():
    return make_task("render", spec=make_spec())


# --- 1. 영상 크기 상한 ---------------------------------------------------------------


@needs_ffmpeg
def test_probe_rejects_over_8192(media, tmp_path):
    big = tmp_path / "big.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=8200x16:d=0.1",
            "-frames:v",
            "1",
            "-c:v",
            "libx264",
            str(big),
        ],
        check=True,
    )
    with pytest.raises(MediaError):
        media.probe(big, Cancel())


@needs_ffmpeg
def test_prepare_over_8192_is_input_invalid(api, server, media, tmp_path, monkeypatch):
    monkeypatch.setattr("production.media.MAX_DIMENSION", 320)  # 합성 원본(640×360)을 상한 초과로
    from worker_fakes import FFMPEG as ff

    src = tmp_path / "s.mp4"
    subprocess.run(
        [
            ff,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:d=1",
            "-c:v",
            "libx264",
            str(src),
        ],
        check=True,
    )
    server.inputs["source_upload"] = (str(uuid.uuid4()), src.read_bytes())
    assert run_task(api, make_task("prepare"), tmp_path / "w", media, 60) == "failed"
    assert server.finished[-1]["error_code"] == "input_invalid"


# --- 2. ffmpeg 실행 시간 상한 --------------------------------------------------------


def test_run_default_timeout_and_timeout_kills(media):
    assert inspect.signature(Media.run).parameters["timeout"].default == 600
    with pytest.raises(MediaTimeout):
        media.run([sys.executable, "-c", "import time; time.sleep(30)"], Cancel(), timeout=0.3)


@needs_ffmpeg
def test_prepare_timeout_reports_failure(api, server, media, samples, tmp_path, monkeypatch):
    real_run = Media.run

    def slow_run(self, args, cancel, timeout=600):
        if self.ffprobe not in args:  # ffprobe 외(추출) 단계에서 시간 초과
            raise MediaTimeout("ffmpeg 시간 초과")
        return real_run(self, args, cancel, timeout)

    monkeypatch.setattr(Media, "run", slow_run)
    server.inputs["source_upload"] = (str(uuid.uuid4()), samples["src"].read_bytes())
    assert run_task(api, make_task("prepare"), tmp_path, media, 60) == "failed"
    assert server.finished[-1] == {
        "status": "failed",
        "error_stage": "prepare",
        "error_code": "unknown",
    }


# --- 3. 훅 음성 다운로드 상한 --------------------------------------------------------


@needs_ffmpeg
def test_hook_audio_over_20mb_rejected(api, server, media, samples, tmp_path):
    server.inputs["source"] = (str(uuid.uuid4()), samples["src"].read_bytes())
    server.inputs["hook_audio"] = (str(uuid.uuid4()), b"RIFF" + bytes(21 * 1024 * 1024))
    assert run_task(api, _render_task(), tmp_path, media, 60) == "failed"
    assert server.finished[-1]["error_code"] == "render_failed"


# --- 4. 매직 바이트 선별 ---------------------------------------------------------------


@needs_ffmpeg
def test_sniff_magic_bytes(samples, tmp_path):
    assert sniff(samples["src"]) == "mov"
    assert sniff(samples["hook"]) == "wav"
    assert sniff(samples["note"]) is None
    fake = tmp_path / "fake.mp4"  # 확장자만 mp4
    fake.write_bytes(b"<html>not a video</html>")
    assert sniff(fake) is None
    ebml = tmp_path / "x.bin"
    ebml.write_bytes(bytes.fromhex("1a45dfa3") + bytes(12))
    assert sniff(ebml) == "matroska"


@needs_ffmpeg
def test_probe_rejects_magic_mismatch(media, tmp_path):
    fake = tmp_path / "fake.bin"
    fake.write_bytes(bytes(4) + b"ftyp" + b"garbage" * 10)  # mp4 머리 + 쓰레기
    with pytest.raises(MediaError):
        media.probe(fake, Cancel())


# --- 5. https 전용 ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://api.example.com", True),
        ("http://127.0.0.1:8000", True),
        ("http://localhost:8000", True),
        ("http://api.example.com", False),
        ("ftp://api.example.com", False),
        ("file:///etc/passwd", False),
    ],
)
def test_api_base_url_scheme(monkeypatch, url, ok):
    monkeypatch.setenv("WORKER_API_BASE_URL", url)
    monkeypatch.setenv("WORKER_TOKEN", "x" + "y")
    if ok:
        assert Settings().api_base_url == url  # type: ignore[call-arg]
    else:
        with pytest.raises(ValueError):
            Settings()  # type: ignore[call-arg]


def test_signed_url_must_be_https(api, server):
    server.storage_base = "http://storage.example"
    server.inputs["source_upload"] = (str(uuid.uuid4()), b"x")
    with pytest.raises(ApiCallError) as exc:
        api.inputs(make_task("prepare"))
    assert "storage.example" not in str(exc.value)
    with pytest.raises(ValueError):
        SignedUrl(
            asset_id=uuid.uuid4(), kind="k", url="javascript:x", expires_at="2030-01-01T00:00Z"
        )


# --- 6. 시작 시 작업 폴더 정리 ----------------------------------------------------------


def test_clean_root_removes_subfolders(tmp_path):
    for _ in range(2):
        WorkDir(tmp_path, uuid.uuid4()).reset()
    assert clean_root(tmp_path) == 2
    assert not [p for p in tmp_path.iterdir() if p.is_dir()]
    assert clean_root(tmp_path / "new") == 0  # 없으면 만든다


# --- 7. 예외 격리 ------------------------------------------------------------------


def test_claim_parse_error_is_api_error():
    def handler(request):
        return httpx.Response(200, json={"task": {"kind": "weird"}})

    client = WorkerApi("https://api.test", "t", transport=httpx.MockTransport(handler))
    with pytest.raises(ApiCallError):
        client.claim()
    client.close()


def test_step_swallows_unexpected_errors(caplog, tmp_path, monkeypatch):
    monkeypatch.setenv("WORKER_API_BASE_URL", "https://api.test")
    monkeypatch.setenv("WORKER_TOKEN", "x" + "y")

    class Boom:
        def claim(self):
            raise RuntimeError("secret-path C:/x")

    caplog.set_level(logging.INFO)
    assert worker_main.step(Boom(), Settings(), None) is False  # type: ignore[arg-type,call-arg]
    assert "RuntimeError" in caplog.text and "secret-path" not in caplog.text


def test_workdir_reset_oserror_aborts(api, server, media, tmp_path, monkeypatch):
    def fail(self):
        raise PermissionError("locked")

    monkeypatch.setattr(WorkDir, "reset", fail)
    assert run_task(api, make_task("prepare"), tmp_path, media, 60) == "aborted"
    assert server.finished == []


# --- 8. finish 재시도·400 -------------------------------------------------------------


@needs_ffmpeg
def test_finish_retries_5xx(api, server, media, samples, tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod, "FINISH_BACKOFF", (0, 0))
    server.inputs["source_upload"] = (str(uuid.uuid4()), samples["src"].read_bytes())
    server.finish_statuses = [503, 502]
    assert run_task(api, make_task("prepare", segment_len_sec=1.0), tmp_path, media, 60) == "done"
    assert len(server.finished) == 3


def test_finish_gives_up_after_3(api, server, monkeypatch):
    monkeypatch.setattr(api_mod, "FINISH_BACKOFF", (0, 0))
    server.finish_status = 500
    with pytest.raises(ApiCallError):
        api.finish(make_task("render"), {"status": "failed"})
    assert len(server.finished) == 3


@needs_ffmpeg
def test_finish_400_reports_failed_once(api, server, media, samples, tmp_path):
    server.inputs["source"] = (str(uuid.uuid4()), samples["src"].read_bytes())
    server.inputs["hook_audio"] = (str(uuid.uuid4()), samples["hook"].read_bytes())
    server.finish_statuses = [400]
    assert run_task(api, _render_task(), tmp_path, media, 60) == "failed"
    assert [b["status"] for b in server.finished] == ["done", "failed"]
    assert server.finished[-1] == {
        "status": "failed",
        "error_stage": "render",
        "error_code": "render_failed",
    }


# --- 9. 전송 중 중단 ---------------------------------------------------------------


def test_download_and_upload_check_cancel(api, server, tmp_path):
    server.inputs["source_upload"] = (str(uuid.uuid4()), b"data" * 10)
    task = make_task("prepare")
    signed = api.inputs(task)["source_upload"]
    cancel = Cancel()
    cancel.trigger()
    with pytest.raises(TaskCancelled):
        api.download(signed, tmp_path / "in.bin", 1024, cancel)
    src = tmp_path / "a.json"
    src.write_text("{}")
    up = api.outputs(task, [{"kind": "analysis", "size_bytes": 2, "mime": "application/json"}])[0]
    with pytest.raises(TaskCancelled):
        api.upload(up, src, "application/json", cancel)
    assert server.uploaded == {}
