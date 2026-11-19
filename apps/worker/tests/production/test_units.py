"""경로 보안·어댑터·문구 폭·훅 길이·중단·진행 보고 단위 테스트."""

import sys
import threading
import time
import uuid

import pytest
from worker_fakes import make_spec, make_task, needs_ffmpeg

from production.adapter import PRESET_VERSION, to_project
from production.config import Settings
from production.errors import (
    AudioMissing,
    HookTooLong,
    RenderFailed,
    TaskCancelled,
    TextTooLong,
)
from production.media import Cancel, MediaError, file_input
from production.paths import UnsafePath, WorkDir
from production.render import check_hook, overlays
from production.runner import Reporter

# --- 경로 보안 -------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "../x",
        "..",
        "a/../../b",
        "/etc/passwd",
        "C:\\x",
        "C:x",
        "a/b",
        "a\\b",
        "",
        ".env",
        "~x",
        "x" * 101,
        "file:x",
    ],
)
def test_workdir_rejects_unsafe_names(tmp_path, name):
    work = WorkDir(tmp_path, uuid.uuid4())
    work.reset()
    with pytest.raises(UnsafePath):
        work.path(name)


def test_workdir_stays_inside_and_resets(tmp_path):
    tid = uuid.uuid4()
    work = WorkDir(tmp_path, tid)
    work.reset()
    p = work.path("source.mp4")
    assert p.parent == tmp_path.resolve() / str(tid)
    p.write_text("old")
    work.reset()  # F5: 다시 받은 task는 폴더를 지우고 처음부터
    assert not p.exists()
    work.remove()
    assert not work.dir.exists()


def test_workdir_requires_uuid(tmp_path):
    with pytest.raises(UnsafePath):
        WorkDir(tmp_path, "../escape")  # type: ignore[arg-type]


def test_file_input_whitelists_file_protocol(tmp_path):
    args = file_input(tmp_path / "a.mp4", "mov")
    assert args[:4] == ["-protocol_whitelist", "file", "-f", "mov"]
    assert args[-1].startswith("file:")


# --- 어댑터 ----------------------------------------------------------------------


def test_adapter_maps_spec_to_project():
    project = to_project(make_spec(), "ko")
    assert project["header"] == ["테스트 제목", "둘째 줄"]
    assert project["shots"][1] == [1, 2, 1.2, -100]
    assert project["items"][0] == [0, 1.2, "white", "이렇게 된다고?"]
    assert project["items"][1] == [1.2, 2, "emph", "완성", 400]
    assert "source" not in project and "output" not in project  # 경로 필드 없음


def test_adapter_tts_hook_is_audio_missing():
    with pytest.raises(AudioMissing):
        to_project(make_spec(hook={"text": "a", "tts": {"voice": "v", "rate": "+50%"}}), "ko")


@pytest.mark.parametrize(
    "spec",
    [
        make_spec(preset_version="other-v9"),
        make_spec(overlays=[{"kind": "comment"}]),
        {"lang": "ko"},
        None,
    ],
)
def test_adapter_rejects(spec):
    with pytest.raises(RenderFailed):
        to_project(spec, "ko")


def test_adapter_accepts_same_preset():
    assert to_project(make_spec(preset_version=PRESET_VERSION), "ko")["lang"] == "ko"


# --- text_too_long · hook_too_long -------------------------------------------------


def test_text_too_long():
    project = to_project(make_spec(), "ko")
    project["header"] = ["아주 긴 제목" * 30, "둘째"]
    with pytest.raises(TextTooLong) as exc:
        overlays(project)
    assert (exc.value.stage, exc.value.code) == ("render", "text_too_long")


def test_caption_too_long():
    project = to_project(make_spec(), "ko")
    project["items"][0][3] = "자막이 너무 길어서" * 40
    with pytest.raises(TextTooLong):
        overlays(project)


def test_hook_rule_matches_w09_formula():
    # 훅+0.08 > min(duration, 첫 자막 종료)+0.02 → hook_too_long
    assert check_hook(1.1, 2.0, 1.2) == pytest.approx(1.18)
    with pytest.raises(HookTooLong) as exc:
        check_hook(1.15, 2.0, 1.2)
    assert (exc.value.stage, exc.value.code) == ("audio", "hook_too_long")


# --- 중단(F2) ----------------------------------------------------------------------


def test_cancel_kills_running_process(media):
    cancel = Cancel()
    threading.Timer(0.3, cancel.trigger).start()
    started = time.monotonic()
    with pytest.raises(TaskCancelled):
        media.run([sys.executable, "-c", "import time; time.sleep(30)"], cancel)
    assert time.monotonic() - started < 10


@needs_ffmpeg
def test_probe_rejects_non_media(media, samples):
    with pytest.raises(MediaError):
        media.probe(samples["note"], Cancel())


# --- 진행 보고(F2) -----------------------------------------------------------------


class _ProgressApi:
    def __init__(self, status: int = 200) -> None:
        self.calls: list[tuple[str, int]] = []
        self.status = status

    def progress(self, task, stage, pct):
        self.calls.append((stage, pct))
        if self.status == 409:
            raise TaskCancelled()


def test_default_progress_interval_is_60s(monkeypatch):
    monkeypatch.setenv("WORKER_API_BASE_URL", "https://api.test")
    monkeypatch.setenv("WORKER_TOKEN", "x" + "y")
    assert Settings().progress_interval_sec == 60.0  # type: ignore[call-arg]


def test_reporter_sends_periodically_besides_stage_changes():
    api = _ProgressApi()
    reporter = Reporter(api, make_task("render"), Cancel(), interval=0.05)  # 60초를 축소
    reporter.start()
    reporter.set("compose", 10)
    reporter.set("compose", 20)  # 같은 단계: 즉시 보내지 않음
    time.sleep(0.4)
    reporter.stop()
    assert api.calls[0] == ("compose", 10)
    assert len(api.calls) >= 4  # 단계 전환 1회 + 주기 보고
    assert api.calls[-1] == ("compose", 20)


def test_reporter_409_cancels():
    cancel = Cancel()
    reporter = Reporter(_ProgressApi(409), make_task("render"), cancel, interval=60)
    with pytest.raises(TaskCancelled):
        reporter.set("download", 0)
    assert cancel.is_set
