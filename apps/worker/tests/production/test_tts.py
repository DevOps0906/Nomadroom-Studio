"""task-030 TTS(edge-tts) 목 테스트: 성공·실패·꺼짐·중단, voice·rate ValueError, 무음 대체 0건.
실제 edge-tts 네트워크 호출은 하지 않는다(I5: 이용 조건 미확인 → 사용자가 켜고 직접 확인)."""

import asyncio
import json
import logging
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

import edge_tts
import pytest
from worker_fakes import FFMPEG, FFPROBE, make_spec, make_task, needs_ffmpeg

from production import tts as tts_mod
from production.config import TtsSettings
from production.errors import TaskCancelled
from production.media import Cancel
from production.runner import run_task
from production.tts import TtsFailed, synthesize

HOOK = "TTS전용훅문구-비공개"
VOICE = "ko-KR-SunHiNeural"
RATE = "+40%"
ON = TtsSettings(enabled=True, timeout_sec=30)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """실수로라도 edge-tts가 서버에 붙지 않게 막는다."""

    def blocked(*_a, **_k):
        raise AssertionError("edge-tts 네트워크 호출 금지")

    monkeypatch.setattr(edge_tts.Communicate, "save", blocked)
    monkeypatch.setattr(edge_tts.Communicate, "stream", blocked)


def _mp3(path: Path, seconds: float, source: str = "sine=frequency=520") -> None:
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi"]
        + ["-i", f"{source}:duration={seconds}", "-c:a", "libmp3lame", str(path)],
        check=True,
    )


_MP3_CACHE: dict[tuple, bytes] = {}


def _fake(calls: list, seconds: float = 0.6, source: str = "sine=frequency=520"):
    """목 TTS: lavfi 합성 mp3를 미리 만들어 두고 out에 쓴다(타임아웃 안에서 ffmpeg 안 돌림)."""
    key = (seconds, source)
    if key not in _MP3_CACHE and FFMPEG:
        tmp = Path(tempfile.mkdtemp()) / "tts.mp3"
        _mp3(tmp, seconds, source)
        _MP3_CACHE[key] = tmp.read_bytes()

    async def synth(text, voice, rate, out, cfg):
        calls.append((text, voice, rate))
        out.write_bytes(_MP3_CACHE[key])

    return synth


def _tts_spec(**tts):
    return make_spec(hook={"text": HOOK, "tts": {"voice": VOICE, "rate": RATE, **tts}})


def _render_with_tts(server, samples, attached=True):
    server.inputs["source"] = (str(uuid.uuid4()), samples["src"].read_bytes())
    if attached:  # 첨부 음성이 있어도 TTS 경로는 쓰지 않는다(I3)
        server.inputs["hook_audio"] = (str(uuid.uuid4()), samples["hook"].read_bytes())
    return make_task("render", spec=_tts_spec())


def _kinds(server, kind):
    return [a for a in server.uploaded if server.issued[a]["kind"] == kind]


def _duration(path: Path) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(out.stdout.strip())


# --- 성공 ----------------------------------------------------------------------------


@needs_ffmpeg
def test_tts_success_uploads_hook_audio(api, server, media, samples, tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    calls: list = []
    monkeypatch.setattr(tts_mod, "edge_save", _fake(calls))
    task = _render_with_tts(server, samples)
    assert run_task(api, task, tmp_path, media, 60, ON) == "done"
    assert calls == [(HOOK, VOICE, RATE)]  # 외부로 가는 값은 문구·voice·rate뿐
    hook_ids = _kinds(server, "hook_audio")
    assert len(hook_ids) == 1
    wav = tmp_path / "hook.wav"
    wav.write_bytes(server.uploaded[hook_ids[0]])
    assert abs(_duration(wav) - 0.6) < 0.15  # make_hook로 정리·실측한 wav
    assert abs(server.issued[hook_ids[0]]["duration_sec"] - _duration(wav)) < 0.01
    report_id = _kinds(server, "report")[0]
    report = json.loads(server.uploaded[report_id])
    assert report["tts"] == f"edge-tts voice={VOICE} rate={RATE}"
    assert report["hook_audio_asset_id"] is None  # W-06 첨부를 쓰지 않음
    assert HOOK not in caplog.text and VOICE not in caplog.text


@needs_ffmpeg
def test_tts_default_rate(api, server, media, samples, tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(tts_mod, "edge_save", _fake(calls))
    server.inputs["source"] = (str(uuid.uuid4()), samples["src"].read_bytes())
    spec = make_spec(hook={"text": HOOK, "tts": {"voice": VOICE}})
    assert run_task(api, make_task("render", spec=spec), tmp_path, media, 60, ON) == "done"
    assert calls == [(HOOK, VOICE, "+50%")]


@needs_ffmpeg
def test_fake_mp3_ffprobe_duration(tmp_path):
    out = tmp_path / "tts.mp3"
    asyncio.run(_fake([], 0.6)(HOOK, VOICE, RATE, out, ON))
    proc = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", str(out)],
        check=True,
        capture_output=True,
        text=True,
    )
    print(proc.stdout.strip())
    assert "duration=" in proc.stdout
    assert abs(_duration(out) - 0.6) < 0.1


@needs_ffmpeg
def test_tts_too_long_is_hook_too_long(api, server, media, samples, tmp_path, monkeypatch):
    monkeypatch.setattr(tts_mod, "edge_save", _fake([], seconds=3.0))  # check_hook(W-09) 적용
    assert run_task(api, _render_with_tts(server, samples), tmp_path, media, 60, ON) == "failed"
    assert server.finished[-1] == {
        "status": "failed",
        "error_stage": "audio",
        "error_code": "hook_too_long",
    }


# --- 실패: 첨부 음성으로 대체하지 않고 무음도 만들지 않는다 ---------------------------------

FAILED = {"status": "failed", "error_stage": "audio", "error_code": "tts_failed"}


@needs_ffmpeg
def test_tts_failure_no_fallback(api, server, media, samples, tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)

    async def boom(text, voice, rate, out, cfg):
        raise RuntimeError(f"{text} {voice}")  # 원문에 문구·voice가 있어도 로그에 남지 않아야 함

    monkeypatch.setattr(tts_mod, "edge_save", boom)
    assert run_task(api, _render_with_tts(server, samples), tmp_path, media, 60, ON) == "failed"
    assert server.finished[-1] == FAILED
    assert not [c for c in server.calls if c[1].endswith("/outputs")]  # 업로드 0건
    assert server.uploaded == {}
    assert HOOK not in caplog.text and VOICE not in caplog.text
    assert "RuntimeError" in caplog.text


@needs_ffmpeg
@pytest.mark.parametrize("source", ["anullsrc=r=48000:cl=stereo", None])
def test_silent_or_empty_output_is_tts_failed(
    api, server, media, samples, tmp_path, monkeypatch, source
):
    async def empty(text, voice, rate, out, cfg):
        out.write_bytes(b"")

    monkeypatch.setattr(tts_mod, "edge_save", empty if source is None else _fake([], 0.6, source))
    assert run_task(api, _render_with_tts(server, samples), tmp_path, media, 60, ON) == "failed"
    assert server.finished[-1] == FAILED
    assert server.uploaded == {}


@needs_ffmpeg
def test_tts_disabled_is_tts_failed(api, server, media, samples, tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(tts_mod, "edge_save", _fake(calls))
    monkeypatch.delenv("WORKER_TTS_ENABLED", raising=False)
    assert run_task(api, _render_with_tts(server, samples), tmp_path, media, 60) == "failed"
    assert server.finished[-1] == FAILED
    assert calls == []
    assert server.uploaded == {}


def test_settings_default_off(monkeypatch):
    monkeypatch.delenv("WORKER_TTS_ENABLED", raising=False)
    assert TtsSettings().enabled is False
    monkeypatch.setenv("WORKER_TTS_ENABLED", "true")
    assert TtsSettings().enabled is True


def test_disabled_detail(tmp_path):
    with pytest.raises(TtsFailed) as e:
        synthesize(HOOK, {"voice": VOICE}, tmp_path / "x.mp3", Cancel(), TtsSettings())
    assert "비활성" in e.value.detail and (e.value.stage, e.value.code) == ("audio", "tts_failed")


@pytest.mark.parametrize("tts", [{"voice": "bad voice!"}, {"voice": VOICE, "rate": "fast"}])
def test_edge_value_error_is_tts_failed(tmp_path, tts):
    # 형식 검사에서 먼저 막힌다(리뷰 반영)
    with pytest.raises(TtsFailed) as e:
        synthesize(HOOK, tts, tmp_path / "x.mp3", Cancel(), ON)
    assert e.value.detail == "ValueError"
    # 형식 검사를 지나더라도 실제 edge_tts.Communicate 생성자가 ValueError(네트워크 전, save 막힘)
    with pytest.raises(ValueError):
        voice, rate = tts["voice"], tts.get("rate", "+50%")
        asyncio.run(tts_mod.edge_save(HOOK, voice, rate, tmp_path / "x.mp3", ON))


def test_edge_value_error_maps_to_tts_failed(tmp_path, monkeypatch):
    async def bad(*_a):
        raise ValueError("Invalid voice")

    with pytest.raises(TtsFailed) as e:
        synthesize(HOOK, {"voice": VOICE}, tmp_path / "x.mp3", Cancel(), ON, synth=bad)
    assert e.value.detail == "ValueError"


@pytest.mark.parametrize("tts", [{"voice": ""}, {"voice": 3}, {"voice": VOICE, "rate": 5}, "v"])
def test_malformed_tts_is_tts_failed(tmp_path, tts):
    with pytest.raises(TtsFailed):
        synthesize(HOOK, tts, tmp_path / "x.mp3", Cancel(), ON)


@pytest.mark.parametrize(
    "tts",
    [
        {"voice": "ko-KR-SunHiNeural'><break time='9s'/>"},
        {"voice": "ko-KR-<SunHi>Neural"},
        {"voice": "ko-KR-SunHiNeural\n"},
        {"voice": VOICE, "rate": "+50%'>"},
        {"voice": VOICE, "rate": "+50%\n"},
        {"voice": VOICE, "rate": "<prosody>"},
    ],
)
def test_ssml_injection_rejected_before_synth(tmp_path, tts):
    # 리뷰 반영: 형식이 다르면 합성(외부 전송) 전에 tts_failed
    calls: list = []
    with pytest.raises(TtsFailed) as e:
        synthesize(HOOK, tts, tmp_path / "x.mp3", Cancel(), ON, synth=_fake(calls))
    assert e.value.detail == "ValueError" and calls == []


def test_timeout_is_tts_failed(tmp_path, monkeypatch):
    async def slow(*_a):
        await asyncio.sleep(10)

    start = time.monotonic()
    with pytest.raises(TtsFailed) as e:
        synthesize(
            HOOK,
            {"voice": VOICE},
            tmp_path / "x.mp3",
            Cancel(),
            ON.model_copy(update={"timeout_sec": 0.3}),
            synth=slow,
        )
    assert e.value.detail == "TimeoutError" and time.monotonic() - start < 3


# --- 중단(409) --------------------------------------------------------------------------


def test_cancel_during_tts_stops(tmp_path):
    started = threading.Event()

    async def slow(*_a):
        started.set()
        await asyncio.sleep(10)

    cancel = Cancel()
    threading.Thread(target=lambda: started.wait(5) and cancel.trigger(), daemon=True).start()
    start = time.monotonic()
    with pytest.raises(TaskCancelled):
        synthesize(HOOK, {"voice": VOICE}, tmp_path / "x.mp3", cancel, ON, synth=slow)
    assert time.monotonic() - start < 3


def test_cancelled_before_start_does_not_call(tmp_path):
    calls: list = []
    cancel = Cancel()
    cancel.trigger()
    with pytest.raises(TaskCancelled):
        synthesize(HOOK, {"voice": VOICE}, tmp_path / "x.mp3", cancel, ON, synth=_fake(calls))
    assert calls == []


@needs_ffmpeg
def test_progress_409_cancels_without_tts(api, server, media, samples, tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(tts_mod, "edge_save", _fake(calls))
    server.progress_status = 409
    assert run_task(api, _render_with_tts(server, samples), tmp_path, media, 60, ON) == "cancelled"
    assert server.finished == [] and calls == []


def test_library_loggers_are_warning():
    for name in ("edge_tts", "aiohttp"):
        assert logging.getLogger(name).level == logging.WARNING
