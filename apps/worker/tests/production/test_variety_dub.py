# ruff: noqa: F811  (vsamples fixture를 인자로 받는다)
"""task-051 예능형 일본어 더빙(가짜 API·Storage, 실제 ffmpeg, TTS는 목).

D3 대사 자막만·상한 60, D4 frame_of 격자 배치·허용 창·atempo 1.3·overflow 자르기,
D5 더빙 구간만 duck(±50ms)·원본 무음이면 TTS만, D6 tts_failed·dub_none, D1 JP 글꼴·result_ja.
"""

import json
import subprocess
import time
import uuid
from array import array

import pytest
from test_variety_render import LAND_SCALE, vsamples, vspec, vtask  # noqa: F401  (fixture 등록)
from worker_fakes import FFMPEG, ffprobe_streams, needs_ffmpeg

from production import tts as tts_mod
from production.adapter_variety import frame_of, to_variety_project
from production.config import TtsSettings
from production.errors import RenderFailed, TextTooLong
from production.media import Cancel
from production.runner import run_task
from production.variety import dub
from production.variety.dub import DUCK_FADE, DUCK_GAIN, build_dub, dub_lines, fit_clip, mix
from production.variety.text import (
    TITLE_SIZE,
    TITLE_STROKE,
    _stroked,
    title_layer,
    title_tops,
)

RATE = 48000
META = {"width": 640, "height": 360, "duration": 2.0, "has_audio": True, "demuxer": "mov"}
CUT = {"src_start": 0.0, "src_end": 2.0, "scale": LAND_SCALE, "x": 0, "y": 0}
ON = TtsSettings(enabled=True, timeout_sec=30)
# 목 TTS: 문구 → 음성 길이(초)
LENS = {"こんにちは": 0.5, "長いセリフです": 1.2, "とても長いセリフです": 2.0, "短い": 0.5}


def jspec(subs, **over) -> dict:
    return vspec(
        lang="ja",
        header={"lines": ["テストタイトル", "二行目です"]},
        cuts=[CUT],
        subtitles=subs,
        **over,
    )


def line(start, end, text, style="line"):
    return {"start": start, "end": end, "style": style, "text": text}


@pytest.fixture(scope="module")
def tones(tmp_path_factory) -> dict:
    """길이별 3kHz 톤 WAV(48k 스테레오). TTS 목이 문구 길이표대로 돌려준다."""
    if not FFMPEG:
        pytest.skip("ffmpeg 없음")
    d = tmp_path_factory.mktemp("tones")
    out = {}
    for sec in sorted(set(LENS.values())):
        path = d / f"tone_{sec}.wav"
        subprocess.run(
            [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i"]
            + [f"sine=frequency=3000:duration={sec}", "-ar", "48000", "-ac", "2", str(path)],
            check=True,
        )
        out[sec] = path
    return out


@pytest.fixture
def fake_tts(monkeypatch, tones) -> list:
    calls: list = []

    async def synth(text, voice, rate, out, cfg):
        calls.append((text, voice, rate))
        if text == "失敗":
            raise ConnectionError("x")
        out.write_bytes(tones[LENS[text]].read_bytes())

    monkeypatch.setattr(tts_mod, "edge_save", synth)
    return calls


def _go(api, server, media, tmp_path, source, spec, cfg=ON):
    server.inputs["source"] = (str(uuid.uuid4()), source.read_bytes())
    status = run_task(api, vtask(spec, lang="ja"), tmp_path, media, 60, tts_cfg=cfg)
    return status, server.finished[-1]


def _uploaded(server, kind):
    return next(b for a, b in server.uploaded.items() if server.issued[a]["kind"] == kind)


def _pcm_of(path) -> bytes:
    import wave

    with wave.open(str(path), "rb") as f:
        return f.readframes(f.getnframes())


# --- D3·D4 배치 ---------------------------------------------------------------------


def test_dub_lines_only_dialogue_on_frame_grid_and_windows():
    subs = [
        line(1.01, 1.5, "長いセリフです"),
        line(0.0, 0.6, "こん\nにちは"),
        line(0.6, 0.8, "すごい", "punch"),  # punch는 더빙 안 함
    ]
    project = to_variety_project(jspec(subs, reactions=[]), "ja", META)
    got = dub_lines(project)
    assert [x["line"] for x in got] == [1, 2]
    assert got[0]["text"] == "こんにちは"  # 자막 줄바꿈은 붙여 읽는다
    assert got[0]["start"] == 0 and got[0]["end"] == frame_of(1.01) * 1600  # 다음 대사 시작까지
    assert got[1]["start"] == frame_of(1.01) * 1600 == 30 * 1600
    assert got[1]["end"] == project["frames"] * 1600  # 마지막은 영상 끝


def test_over_60_lines_is_render_failed_before_tts():
    subs = [
        {"start": i * 0.02, "end": i * 0.02 + 0.01, "style": "line", "text": "短い"}
        for i in range(61)
    ]
    project = {"frames": 60, "subtitles": subs}
    with pytest.raises(RenderFailed):
        build_dub(project, None, None, None, None, ON, 1e18)


# --- D4 atempo·overflow (실제 ffmpeg) --------------------------------------------------


@needs_ffmpeg
def test_fit_clip_atempo_within_window(media, tones, tmp_path):
    wav = tmp_path / "v.wav"
    wav.write_bytes(tones[1.2].read_bytes())
    pcm, tempo, over = fit_clip(_pcm_of(wav), RATE, wav, media, Cancel())
    assert tempo == pytest.approx(1.2, abs=0.01) and over == 0.0
    assert len(pcm) // 4 <= RATE


@needs_ffmpeg
def test_fit_clip_overflow_cut_with_fade(media, tones, tmp_path):
    wav = tmp_path / "v.wav"
    wav.write_bytes(tones[2.0].read_bytes())
    pcm, tempo, over = fit_clip(_pcm_of(wav), RATE, wav, media, Cancel())
    assert tempo == 1.3
    assert over == pytest.approx(2.0 / 1.3 - 1.0, abs=0.02)
    assert len(pcm) == RATE * 4  # 창 끝에서 자름
    tail = array("h", pcm[-40:])
    assert max(abs(v) for v in tail) < 300  # 30ms 페이드아웃


def test_fit_clip_short_untouched():
    pcm = bytes(4 * 100)
    assert fit_clip(pcm, 200, None, None, None) == (pcm, 1.0, 0.0)


# --- D5 duck ------------------------------------------------------------------------


def test_mix_ducks_only_dub_regions_with_fades_and_merges_close_gaps():
    total = RATE * 3
    orig = array("h", [10000] * (2 * total)).tobytes()
    clip = bytes(4 * 12000)  # 0.25초 무음 음성(duck만 보기)
    near = 12000 + 2000  # 첫 음성 끝에서 2000샘플(<100ms) 뒤 → 한 구간으로 합침
    out = array(
        "h", mix(orig, [(RATE, clip), (RATE + near, clip), (RATE * 2 + 10000, clip)], total)
    )

    def at(i):
        return out[2 * i]

    assert at(0) == 10000 and at(RATE - DUCK_FADE - 1) == 10000  # 구간 밖 원음
    assert at(RATE + 100) == int(10000 * DUCK_GAIN)  # 구간 안 0.15
    assert int(10000 * DUCK_GAIN) < at(RATE - DUCK_FADE // 2) < 10000  # 페이드 안
    assert at(RATE + 12000 + 1000) == int(10000 * DUCK_GAIN)  # 가까운 두 구간 사이도 duck 유지
    gap = RATE + near + 12000 + DUCK_FADE + 10
    assert at(gap) == 10000  # 구간 사이 원음 복귀(분산 배치)
    assert at(RATE * 2 + 10000 + 100) == int(10000 * DUCK_GAIN)
    assert at(total - 1) == 10000


def test_mix_without_original_is_tts_only_and_saturates():
    total = 1000
    loud = array("h", [30000] * 400).tobytes()
    out = array("h", mix(None, [(100, loud), (150, loud)], total))
    assert out[0] == 0 and out[2 * 100] == 30000
    assert out[2 * 160] == 32767  # 겹친 부분 포화(클리핑 대신 상한)
    assert len(out) == 2 * total


# --- 종단(run_task) ----------------------------------------------------------------


@needs_ffmpeg
def test_ja_dub_render_end_to_end(api, server, media, vsamples, tmp_path, fake_tts):
    subs = [
        line(0.0, 0.6, "こんにちは"),
        line(0.6, 0.8, "すごい", "punch"),
        line(1.0, 1.5, "長いセリフです"),
    ]
    reacts = [{"start": 0.2, "end": 1.0, "text": "（緊張…）", "x": 300, "y": 700}]
    status, body = _go(
        api, server, media, tmp_path, vsamples["green"], jspec(subs, reactions=reacts)
    )
    assert status == "done", body
    assert fake_tts == [
        ("こんにちは", "ja-JP-NanamiNeural", "+0%"),
        ("長いセリフです", "ja-JP-NanamiNeural", "+0%"),
    ]
    report = json.loads(_uploaded(server, "report"))
    assert report["output"] == "result_ja.mp4" and report["lang"] == "ja"
    assert report["fonts"] == ["NotoSansCJKjp-Black", "NotoSansCJKjp-Bold"]
    assert report["warnings"] == []
    lines = report["dub"]["lines"]
    assert [x["start"] for x in lines] == [0.0, 1.0]
    assert lines[0]["tempo"] == 1.0 and lines[0]["length"] <= lines[0]["window"]
    assert 1.1 < lines[1]["tempo"] <= 1.2  # 창 1.0초에 약 1.2초 음성(앞뒤 무음 정리 후 실측)
    assert lines[1]["length"] <= lines[1]["window"] == 1.0
    mp4 = tmp_path / "ja.mp4"
    mp4.write_bytes(_uploaded(server, "output_mp4"))
    kinds = {s["codec_type"] for s in ffprobe_streams(mp4)}
    assert kinds == {"video", "audio"}


@needs_ffmpeg
def test_ja_dub_overflow_warning(api, server, media, vsamples, tmp_path, fake_tts):
    subs = [line(0.0, 0.9, "とても長いセリフです"), line(1.0, 1.5, "短い")]
    status, body = _go(api, server, media, tmp_path, vsamples["green"], jspec(subs))
    assert status == "done", body
    warnings = json.loads(_uploaded(server, "report"))["warnings"]
    assert len(warnings) == 1 and warnings[0]["code"] == "dub_overflow"
    assert warnings[0]["line"] == 1
    assert warnings[0]["overflow_sec"] == pytest.approx(2.0 / 1.3 - 1.0, abs=0.03)


@needs_ffmpeg
def test_ja_no_dialogue_is_dub_none_without_tts(api, server, media, vsamples, tmp_path, fake_tts):
    subs = [line(0.0, 0.5, "すごい", "punch")]
    off = TtsSettings()  # 대사 0개면 TTS 꺼져 있어도 원본 그대로
    status, body = _go(api, server, media, tmp_path, vsamples["green"], jspec(subs), cfg=off)
    assert status == "done", body
    assert fake_tts == []
    assert json.loads(_uploaded(server, "report"))["warnings"] == [{"code": "dub_none"}]


@needs_ffmpeg
def test_ja_tts_disabled_with_dialogue_is_tts_failed(api, server, media, vsamples, tmp_path):
    subs = [line(0.0, 0.5, "こんにちは")]
    status, body = _go(api, server, media, tmp_path, vsamples["green"], jspec(subs), TtsSettings())
    assert status == "failed"
    assert body == {"status": "failed", "error_stage": "audio", "error_code": "tts_failed"}
    assert not server.uploaded


@needs_ffmpeg
def test_ja_any_tts_failure_fails_whole(api, server, media, vsamples, tmp_path, fake_tts):
    subs = [line(0.0, 0.5, "こんにちは"), line(1.0, 1.5, "失敗")]
    status, body = _go(api, server, media, tmp_path, vsamples["green"], jspec(subs))
    assert status == "failed"
    assert body["error_code"] == "tts_failed" and not server.uploaded


@needs_ffmpeg
def test_ja_mute_source_gets_tts_only(api, server, media, vsamples, tmp_path, fake_tts):
    cuts = [{"src_start": 0.2, "src_end": 1.0, "scale": 1, "x": 0, "y": 0}] * 2
    subs = [line(0.0, 0.5, "こんにちは")]
    status, body = _go(api, server, media, tmp_path, vsamples["mute"], jspec(subs) | {"cuts": cuts})
    assert status == "done", body
    report = json.loads(_uploaded(server, "report"))
    assert report["source_has_audio"] is False and report["has_audio"] is True
    assert len(report["dub"]["lines"]) == 1


def test_dub_constants_match_decisions():
    assert (dub.VOICE, dub.BASE_RATE, dub.MAX_LINES, dub.MAX_TEMPO) == (
        "ja-JP-NanamiNeural",
        "+0%",
        60,
        1.3,
    )
    assert DUCK_GAIN == 0.15


# --- 리뷰 반영: 배치 구간 없음·시간 상한·ja 제목 겹침 -------------------------------------


@pytest.mark.parametrize(
    "subs",
    [
        [line(0.50, 0.505, "こんにちは"), line(0.51, 0.7, "短い")],  # 같은 시작 프레임(15)
        [line(0.0, 0.5, "こんにちは"), line(1.99, 2.0, "短い")],  # 영상 끝 프레임에서 시작
    ],
)
def test_zero_window_is_render_failed_before_tts(subs):
    project = to_variety_project(jspec(subs), "ja", META)
    with pytest.raises(RenderFailed):
        build_dub(project, None, None, None, None, ON, 1e18)


def test_mix_checks_cancel_or_deadline_in_pcm_loop():
    class Stop(Exception):
        pass

    def stop():
        raise Stop

    with pytest.raises(Stop):
        mix(bytes(4 * RATE * 2), [(0, bytes(4 * RATE))], RATE * 2, stop)


@needs_ffmpeg
def test_ffmpeg_steps_respect_render_deadline(media, tones, tmp_path):
    wav = tmp_path / "v.wav"
    wav.write_bytes(tones[2.0].read_bytes())
    with pytest.raises(RenderFailed):
        fit_clip(_pcm_of(wav), RATE, wav, media, Cancel(), time.monotonic() - 1)


def test_ja_long_titles_stack_without_overlap():
    parts = [_stroked("あ" * 20, TITLE_SIZE, TITLE_STROKE, [], "ja", title=True) for _ in range(2)]
    hs = [h for _, h, _ in parts]
    tops = title_tops(hs)
    assert tops[0] >= 0 and tops[0] + hs[0] <= tops[1]  # 겹치지 않음
    assert tops[1] + hs[1] <= 560  # 영상 띠 위
    fonts: list = []
    title_layer(["あ" * 20, "あ" * 20], fonts, "ja")
    assert fonts == ["NotoSansCJKjp-Black"] * 2
    assert title_tops([81, 81]) == [330, 414]  # 한 줄씩이면 기본 위치(370·454 중심)


def test_ja_titles_too_tall_are_text_too_long():
    with pytest.raises(TextTooLong):
        title_layer(["あ" * 30, "あ" * 30], [], "ja")
