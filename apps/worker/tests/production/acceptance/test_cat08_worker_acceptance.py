"""task-033 인수 테스트(워커 쪽): CAT-08 오버레이 실제 출력 + TTS 실패 복귀 + URL 원본(목 다운로더).

가짜 FastAPI·Storage + 실제 ffmpeg. yt-dlp·edge-tts·네트워크는 목(실제 외부 호출 없음).
샘플은 lavfi 합성(저작물 없음). 근거: Nomadroom_Category_Shorts_PRD.md#5 CAT-08, task-030~032.
"""

import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat
from worker_fakes import FFMPEG, ffprobe_streams, make_spec, make_task, needs_ffmpeg

from production import runner as runner_mod
from production import tts as tts_mod
from production.config import TtsSettings
from production.errors import TaskFailed
from production.fetch_url import check_url
from production.runner import run_task

pytestmark = needs_ffmpeg

YT = "https://www.youtube.com/watch?v=abcDEF12345"
VOICE, RATE = "ko-KR-SunHiNeural", "+50%"
ON = TtsSettings(enabled=True, timeout_sec=30)
COMMENT = {
    "kind": "comment",
    "text": "댓글 이거 실화냐",
    "start": 0.2,
    "end": 1.0,
    "x": 304,
    "y": 200,
}
SOURCE = {"kind": "source", "text": "출처 합성 영상", "start": 0.0, "end": 2.0, "x": 304, "y": 950}
TTS_HOOK = {"text": "이렇게 된다고?", "tts": {"voice": VOICE, "rate": RATE}}


def _ff(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def frame_at(path: Path, t: float, tmp: Path) -> Image.Image:
    png = tmp / f"f_{t}_{uuid.uuid4().hex[:6]}.png"
    _ff("-ss", str(t), "-i", str(path), "-frames:v", "1", str(png))
    return Image.open(png).convert("RGB")


def region_diff(a: Image.Image, b: Image.Image, y0: int, y1: int) -> float:
    box = (0, y0, a.width, y1)
    d = ImageChops.difference(a.crop(box), b.crop(box)).convert("L")
    return ImageStat.Stat(d).mean[0]


def uploaded(server, kind):
    return [b for a, b in server.uploaded.items() if server.issued[a]["kind"] == kind]


def render(api, server, media, samples, tmp, spec, synth=None, monkeypatch=None, attach=True):
    server.inputs["source"] = (str(uuid.uuid4()), samples["src"].read_bytes())
    server.inputs.pop("hook_audio", None)
    if attach:
        server.inputs["hook_audio"] = (str(uuid.uuid4()), samples["hook"].read_bytes())
    if synth is not None:
        monkeypatch.setattr(tts_mod, "edge_save", synth)
    return run_task(api, make_task("render", spec=spec), tmp, media, 60, ON)


def out_mp4(server, tmp: Path, name: str) -> Path:
    p = tmp / name
    p.write_bytes(uploaded(server, "output_mp4")[-1])
    return p


def assert_spec_608(mp4: Path) -> None:
    streams = ffprobe_streams(mp4)
    v = next(s for s in streams if s["codec_type"] == "video")
    a = next(s for s in streams if s["codec_type"] == "audio")
    got = (v["width"], v["height"], v["r_frame_rate"], v["codec_name"])
    assert got == (608, 1080, "30/1", "h264")
    assert a["codec_name"] == "aac"


@pytest.fixture
def mp3_bytes(tmp_path_factory) -> bytes:
    p = tmp_path_factory.mktemp("tts08") / "tts.mp3"
    _ff("-f", "lavfi", "-i", "sine=frequency=520:duration=0.6", "-c:a", "libmp3lame", str(p))
    return p.read_bytes()


def _synth(data: bytes, calls: list):
    async def synth(text, voice, rate, out, cfg):
        calls.append((voice, rate))
        out.write_bytes(data)

    return synth


# === CAT-08: 오버레이가 출력물에 실제로 들어가고 자막과 겹치지 않는다 ================


def test_cat08_overlays_are_in_output_pixels_and_captions_untouched(
    api, server, media, samples, tmp_path
):
    assert render(api, server, media, samples, tmp_path, make_spec()) == "done"
    plain = out_mp4(server, tmp_path, "plain.mp4")
    server.uploaded.clear()
    spec = make_spec(overlays=[COMMENT, SOURCE])
    assert render(api, server, media, samples, tmp_path, spec) == "done"
    ovl = out_mp4(server, tmp_path, "ov.mp4")
    assert_spec_608(ovl)
    # t=0.6: 댓글(y200)·출처(y950) 있음, 자막(white y700)은 오버레이와 안 겹쳐 같다
    a, b = frame_at(plain, 0.6, tmp_path), frame_at(ovl, 0.6, tmp_path)
    assert region_diff(a, b, 150, 250) > 8, "댓글 카드가 출력에 없음"
    assert region_diff(a, b, 900, 1000) > 8, "출처 띠가 출력에 없음"
    assert region_diff(a, b, 650, 750) < 2, "자막 영역이 오버레이 때문에 변함"
    # t=1.6: 댓글 구간(0.2~1.0)이 끝나 사라지고 출처만 남는다
    a2, b2 = frame_at(plain, 1.6, tmp_path), frame_at(ovl, 1.6, tmp_path)
    assert region_diff(a2, b2, 150, 250) < 2, "댓글이 구간 밖에도 남음"
    assert region_diff(a2, b2, 900, 1000) > 4


def test_cat08_overlay_too_wide_text_fails_render_without_upload(
    api, server, media, samples, tmp_path
):
    bad = make_spec(overlays=[{**COMMENT, "text": "가" * 59}])
    assert render(api, server, media, samples, tmp_path, bad) == "failed"
    assert server.finished[-1]["status"] == "failed" and server.uploaded == {}


# === TTS: 성공(오버레이 포함) · 실패 → 첨부로 복귀 ====================================


def test_cat08_tts_with_overlays_renders_and_reports_route(
    api, server, media, samples, tmp_path, monkeypatch, mp3_bytes
):
    calls: list = []
    spec = make_spec(hook=TTS_HOOK, overlays=[COMMENT, SOURCE])
    synth = _synth(mp3_bytes, calls)
    assert render(api, server, media, samples, tmp_path, spec, synth, monkeypatch, False) == "done"
    assert calls == [(VOICE, RATE)]
    assert_spec_608(out_mp4(server, tmp_path, "tts.mp4"))
    report = json.loads(uploaded(server, "report")[-1])
    assert report["tts"] == f"edge-tts voice={VOICE} rate={RATE}"
    assert report["hook_audio_asset_id"] is None and report["source_asset_id"]


def test_cat08_tts_failure_then_attached_voice_succeeds_same_worker(
    api, server, media, samples, tmp_path, monkeypatch
):
    async def boom(text, voice, rate, out, cfg):
        raise ConnectionError("offline")

    tts_spec = make_spec(hook=TTS_HOOK, overlays=[COMMENT])
    assert render(api, server, media, samples, tmp_path, tts_spec, boom, monkeypatch, False) == (
        "failed"
    )
    expected = {"status": "failed", "error_stage": "audio", "error_code": "tts_failed"}
    assert server.finished[-1] == expected
    assert server.uploaded == {}  # 첨부·무음으로 몰래 대체하지 않는다
    # 사용자가 첨부 음성으로 바꿔 재승인한 편집안(tts 없음, audio_asset_id)을 같은 워커가 처리
    attached = make_spec(overlays=[COMMENT])
    assert render(api, server, media, samples, tmp_path, attached) == "done"
    assert server.finished[-1]["status"] == "done"
    assert_spec_608(out_mp4(server, tmp_path, "attached.mp4"))
    report = json.loads(uploaded(server, "report")[-1])
    assert report["tts"] == "supplied recording" and report["hook_audio_asset_id"]


def test_cat08_tts_disabled_is_tts_failed_not_silent(api, server, media, samples, tmp_path):
    spec = make_spec(hook={"text": "훅", "tts": {"voice": VOICE, "rate": RATE}})
    server.inputs["source"] = (str(uuid.uuid4()), samples["src"].read_bytes())
    st = run_task(api, make_task("render", spec=spec), tmp_path, media, 60, TtsSettings())
    assert st == "failed" and server.finished[-1]["error_code"] == "tts_failed"


# === URL 원본(목 다운로더) → prepare → 오버레이 렌더 ===================================


def _fake_fetch(samples, calls: list):
    def fetch(url, work, cancel, on_progress, start=0.0, length=None, **kw):
        check_url(url)  # 실제 워커 검사는 그대로
        calls.append((url, start, length))
        out = work.path("url_download")
        out.mkdir()
        shutil.copy(samples["src"], out / "source.mp4")
        on_progress("download", 100)
        return out / "source.mp4"

    return fetch


def test_cat08_url_source_prepare_then_overlay_render_keeps_reference(
    api, server, media, samples, tmp_path, monkeypatch
):
    calls: list = []
    monkeypatch.setattr(runner_mod, "fetch_url", _fake_fetch(samples, calls))
    task = make_task(
        "prepare", source_kind="url", source_url=YT, source_start_sec=1.0, segment_len_sec=2.0
    )
    assert run_task(api, task, tmp_path, media, 60) == "done"
    assert calls == [(YT, 1.0, 2.0)]
    assert not [c for c in server.calls if c[1].endswith("/inputs")]  # source_upload 요청 없음
    assert json.loads(uploaded(server, "analysis")[0])["source_start"] == 1.0
    src = tmp_path / "prepared.mp4"
    src.write_bytes(uploaded(server, "source")[0])
    fmt = next(s for s in ffprobe_streams(src) if s["codec_type"] == "video")
    assert abs(float(fmt["duration"]) - 2.0) < 0.2
    # 준비된 source로 오버레이 렌더(원본 asset id가 리포트에 남는다)
    server.inputs["source"] = (str(uuid.uuid4()), src.read_bytes())
    server.inputs["hook_audio"] = (str(uuid.uuid4()), samples["hook"].read_bytes())
    server.uploaded.clear()
    spec = make_spec(overlays=[COMMENT, SOURCE])
    assert run_task(api, make_task("render", spec=spec), tmp_path, media, 60) == "done"
    assert_spec_608(out_mp4(server, tmp_path, "url_ov.mp4"))
    report = json.loads(uploaded(server, "report")[-1])
    assert report["source_asset_id"] == server.inputs["source"][0]


@pytest.mark.parametrize(
    "url", ["https://example.com/v.mp4", "http://www.youtube.com/watch?v=x", "https://10.0.0.1/x"]
)
def test_cat08_worker_rejects_non_youtube_url_before_download(
    api, server, media, samples, tmp_path, monkeypatch, url
):
    monkeypatch.setattr(runner_mod, "fetch_url", _fake_fetch(samples, []))
    task = make_task("prepare", source_kind="url", source_url=url, segment_len_sec=2.0)
    assert run_task(api, task, tmp_path, media, 60) == "failed"
    f = server.finished[-1]
    assert (f["error_stage"], f["error_code"]) == ("prepare", "url_unavailable")
    assert server.uploaded == {}


def test_cat08_url_download_failure_is_url_unavailable_with_upload_fallback(
    api, server, media, samples, tmp_path, monkeypatch
):
    def fail(*a, **k):
        raise TaskFailed("prepare", "url_unavailable", "host=www.youtube.com 추출·다운로드 실패")

    monkeypatch.setattr(runner_mod, "fetch_url", fail)
    task = make_task("prepare", source_kind="url", source_url=YT, segment_len_sec=2.0)
    assert run_task(api, task, tmp_path, media, 60) == "failed"
    assert server.finished[-1]["error_code"] == "url_unavailable"
