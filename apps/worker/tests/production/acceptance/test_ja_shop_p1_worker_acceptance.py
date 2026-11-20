# ruff: noqa: F811, F401  (다른 테스트 모듈의 fixture를 인자로 받는다)
"""일본어판·쇼핑 P1 인수(워커 쪽): JA-01~04, SHOP-08.

가짜 API·Storage + 실제 ffmpeg(원본은 lavfi 합성), TTS는 목.
근거: tasks/plan-shopping-japanese.md#인수 기준.
"""

import json
import subprocess
import uuid
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat
from test_ja_render import (
    JA_SCRIPT,
    JP,
    _category_inputs,
    _ja_category_spec,
    _ja_shopping_spec,
    used_fonts,
)
from test_shopping_render import SCRIPT as KO_SCRIPT
from test_shopping_render import _cut, _setup, _task, ssamples
from test_variety_dub import _go, fake_tts, jspec, line, tones
from test_variety_render import vsamples
from worker_fakes import FFMPEG, ffprobe_streams, make_spec, make_task, needs_ffmpeg

from production import fonts as fonts_mod
from production import tts as tts_mod
from production.adapter_shopping import PRESET_VERSION
from production.config import TtsSettings
from production.runner import run_task

pytestmark = needs_ffmpeg
FPS = 30
ON = TtsSettings(enabled=True, timeout_sec=30)


def _up(server, kind) -> list[bytes]:
    return [b for a, b in server.uploaded.items() if server.issued[a]["kind"] == kind]


def _report(server) -> dict:
    return json.loads(_up(server, "report")[0])


def _frame(path: Path, frame_no: int) -> Image.Image:
    t = (frame_no + 0.5) / FPS
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", f"{t:.4f}", "-i", str(path), "-frames:v", "1"]
        + ["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        check=True,
        capture_output=True,
    ).stdout
    return Image.frombytes("RGB", (1080, 1920), raw)


def _mad(a: Image.Image, b: Image.Image) -> float:
    """두 프레임의 평균 절대 차(0~255)."""
    return ImageStat.Stat(ImageChops.difference(a, b).convert("L")).mean[0]


def _shop_render(api, server, media, tmp_path, spec, lang, **kw):
    server.uploaded.clear()
    status = run_task(api, _task(spec, lang=lang), tmp_path, media, 60, **kw)
    return status, server.finished[-1]


# === JA-01 ======================================================================


def test_ja01_ko_and_ja_same_cuts_render_result_files_with_identical_timing(
    api, server, media, ssamples, tmp_path
):
    ja_spec = _ja_shopping_spec(server, ssamples)
    ko_spec = json.loads(json.dumps(ja_spec))
    ko_spec["lang"] = "ko"
    ko_spec["script"] = [{"text": t} for t in KO_SCRIPT]
    ko_spec["cta"] = {"text": "프로필 링크 확인"}
    ko_spec["disclosure"] = {"text": "제휴 링크 포함"}
    assert ko_spec["cuts"] == ja_spec["cuts"]  # 컷 구성 동일, 텍스트만 다르다

    status, body = _shop_render(api, server, media, tmp_path, ko_spec, "ko")
    assert status == "done", body
    ko_rep, ko_mp4 = _report(server), _up(server, "output_mp4")[0]
    status, body = _shop_render(api, server, media, tmp_path, ja_spec, "ja")
    assert status == "done", body
    ja_rep, ja_mp4 = _report(server), _up(server, "output_mp4")[0]

    assert (ko_rep["output"], ja_rep["output"]) == ("result_ko.mp4", "result_ja.mp4")
    assert (ko_rep["lang"], ja_rep["lang"]) == ("ko", "ja")
    # 같은 녹음·컷 → 컷 프레임 수·문장 구간이 같다
    assert [c["frames"] for c in ko_rep["cuts"]] == [c["frames"] for c in ja_rep["cuts"]]
    assert [(s["frame_start"], s["frame_end"]) for s in ko_rep["sentences"]] == [
        (s["frame_start"], s["frame_end"]) for s in ja_rep["sentences"]
    ]
    durs = []
    for name, body_ in (("ko.mp4", ko_mp4), ("ja.mp4", ja_mp4)):
        p = tmp_path / name
        p.write_bytes(body_)
        v = next(s for s in ffprobe_streams(p) if s["codec_type"] == "video")
        durs.append(float(v["duration"]))
    assert abs(durs[0] - durs[1]) <= 1 / FPS + 1e-6


def test_ja01_boundary_lang_mismatch_between_task_and_spec_fails(
    api, server, media, ssamples, tmp_path
):
    spec = _ja_shopping_spec(server, ssamples)
    status, body = _shop_render(api, server, media, tmp_path, spec, "ko")
    assert status == "failed" and body["error_code"] == "render_failed"
    assert not server.uploaded


# === JA-02 ======================================================================


def test_ja02_category_hook_tts_uses_ja_voice_and_report_fonts_jp(
    api, server, media, samples, tmp_path, monkeypatch, used_fonts
):
    calls: list = []

    async def synth(text, voice, rate, out, cfg):
        calls.append((text, voice))
        out.write_bytes(samples["hook"].read_bytes())

    monkeypatch.setattr(tts_mod, "edge_save", synth)
    server.inputs["source"] = (str(uuid.uuid4()), samples["src"].read_bytes())
    spec = _ja_category_spec(hook={"text": "こうなるの？", "tts": {"voice": "ja-JP-NanamiNeural"}})
    task = make_task("render", lang="ja", spec=spec)
    assert run_task(api, task, tmp_path, media, 60, tts_cfg=ON) == "done", server.finished
    assert calls == [("こうなるの？", "ja-JP-NanamiNeural")]
    rep = _report(server)
    assert rep["output"] == "result_ja.mp4"
    assert rep["fonts"] == ["NotoSansCJKjp-Black", "NotoSansCJKjp-Bold"]
    assert used_fonts <= {str(p) for p in JP}


def test_ja02_shopping_narration_tts_ja_voice_and_jp_font(
    api, server, media, ssamples, tmp_path, monkeypatch, used_fonts
):
    calls: list = []

    async def synth(text, voice, rate, out, cfg):
        calls.append((text, voice))
        out.write_bytes(ssamples["tts.mp3"].read_bytes())

    monkeypatch.setattr(tts_mod, "edge_save", synth)
    spec = _ja_shopping_spec(server, ssamples)
    spec["voice"] = {"tts": {"voice": "ja-JP-NanamiNeural"}}
    spec["source_audio"] = "mute"
    spec.pop("bgm_asset_id", None)
    status, body = _shop_render(api, server, media, tmp_path, spec, "ja", tts_cfg=ON)
    assert status == "done", body
    assert calls == [(t, "ja-JP-NanamiNeural") for t in JA_SCRIPT]  # 문장마다 ja 목소리
    rep = _report(server)
    assert rep["voice"] == "tts" and rep["output"] == "result_ja.mp4"
    assert rep["fonts"] == ["NotoSansCJKjp-Bold"]
    assert used_fonts == {str(fonts_mod.NOTO_JP_BOLD)}


def test_ja02_failure_category_hook_tts_off_does_not_fall_back_to_recording(
    api, server, media, samples, tmp_path
):
    _category_inputs(server, samples)
    spec = _ja_category_spec(hook={"text": "こうなるの？", "tts": {"voice": "ja-JP-NanamiNeural"}})
    task = make_task("render", lang="ja", spec=spec)
    assert run_task(api, task, tmp_path, media, 60, tts_cfg=TtsSettings()) == "failed"
    assert server.finished[-1]["error_code"] == "tts_failed" and not server.uploaded


# === JA-03 ======================================================================


def test_ja03_dub_lines_inside_subtitle_window_no_warning(
    api, server, media, vsamples, tmp_path, fake_tts
):
    subs = [line(0.0, 0.6, "こんにちは"), line(1.0, 1.5, "長いセリフです")]
    status, body = _go(api, server, media, tmp_path, vsamples["green"], jspec(subs))
    assert status == "done", body
    rep = _report(server)
    assert rep["output"] == "result_ja.mp4" and rep["warnings"] == []
    for ln in rep["dub"]["lines"]:
        assert ln["length"] <= ln["window"] + 1e-6, ln  # 대사 음성이 창 안
    assert [x["start"] for x in rep["dub"]["lines"]] == [0.0, 1.0]


def test_ja03_boundary_dub_overflow_warning_when_speech_exceeds_window(
    api, server, media, vsamples, tmp_path, fake_tts
):
    subs = [line(0.0, 0.9, "とても長いセリフです"), line(1.0, 1.5, "短い")]
    status, body = _go(api, server, media, tmp_path, vsamples["green"], jspec(subs))
    assert status == "done", body
    rep = _report(server)
    assert [w["code"] for w in rep["warnings"]] == ["dub_overflow"]
    assert rep["warnings"][0]["line"] == 1
    # 경고가 나도 음성은 창 안에서 잘려 다음 대사를 침범하지 않는다
    first = rep["dub"]["lines"][0]
    assert first["length"] <= first["window"] + 1e-6


def test_ja03_failure_tts_off_with_dialogue_fails_without_output(
    api, server, media, vsamples, tmp_path
):
    status, body = _go(
        api, server, media, tmp_path, vsamples["green"],
        jspec([line(0.0, 0.5, "こんにちは")]), TtsSettings(),
    )  # fmt: skip
    assert status == "failed" and body["error_code"] == "tts_failed"
    assert not server.uploaded


# === JA-04 (워커 측) ==============================================================


def test_ja04_tts_off_is_tts_failed_never_silent_output(api, server, media, ssamples, tmp_path):
    spec = _ja_shopping_spec(server, ssamples)
    spec["voice"] = {"tts": {"voice": "ja-JP-NanamiNeural"}}  # 녹음이 목록에 있어도 대체하지 않음
    status, body = _shop_render(api, server, media, tmp_path, spec, "ja", tts_cfg=TtsSettings())
    assert status == "failed"
    assert (body["error_stage"], body["error_code"]) == ("audio", "tts_failed")
    assert not server.uploaded  # 무음 산출물 없음


def test_ja04_attached_recordings_render_ja_with_audio(api, server, media, ssamples, tmp_path):
    spec = _ja_shopping_spec(server, ssamples)  # 녹음 4개 첨부(narration_asset_ids)
    assert "narration_asset_ids" in spec["voice"]
    spec["source_audio"] = "mute"  # 원본 소리·BGM 없음 → 소리는 녹음에서만 나온다
    spec.pop("bgm_asset_id", None)
    status, body = _shop_render(api, server, media, tmp_path, spec, "ja", tts_cfg=TtsSettings())
    assert status == "done", body  # TTS가 꺼져 있어도 녹음으로 렌더
    rep = _report(server)
    assert rep["output"] == "result_ja.mp4" and rep["voice"] != "tts"
    mp4 = tmp_path / "rec.mp4"
    mp4.write_bytes(_up(server, "output_mp4")[0])
    a = next(s for s in ffprobe_streams(mp4) if s["codec_type"] == "audio")
    assert float(a["duration"]) > 2.0
    # 녹음이 실제로 들어갔다: 평균 볼륨이 무음이 아니다
    out = subprocess.run(
        [FFMPEG, "-v", "info", "-i", str(mp4), "-af", "volumedetect", "-vn", "-f", "null", "-"],
        capture_output=True,
        text=True,
    ).stderr
    mean = float(out.split("mean_volume:")[1].split("dB")[0])
    assert mean > -40, mean  # 녹음(사인파) 구간 음량: 무음(-91dB)이 아니다


def test_ja04_boundary_recording_count_not_four_fails(api, server, media, ssamples, tmp_path):
    spec = _ja_shopping_spec(server, ssamples)
    spec["voice"]["narration_asset_ids"] = spec["voice"]["narration_asset_ids"][:3]
    status, body = _shop_render(api, server, media, tmp_path, spec, "ja")
    assert status == "failed" and body["error_code"] == "render_failed"
    assert not server.uploaded


# === SHOP-08 (워커 측) ============================================================


def _photo_spec(server, ss, motions: list[str | None]) -> dict:
    """사진 4컷(문장 1~4, 컷마다 모션)을 녹음 4개와 묶는다."""
    ids = [str(uuid.uuid4()) for _ in motions]
    narr = [str(uuid.uuid4()) for _ in motions]
    for i in ids:
        server.input_items.append(
            {"asset_id": i, "kind": "image", "body": ss["img.png"].read_bytes()}
        )
    for n, k in zip(narr, range(4), strict=True):
        server.input_items.append(
            {"asset_id": n, "kind": "narration", "body": ss[f"n{k}.wav"].read_bytes()}
        )
    cuts = [
        _cut(i, s, 0.0, 1.0, **({"motion": {"type": m}} if m else {}))
        for s, (i, m) in enumerate(zip(ids, motions, strict=True), start=1)
    ]
    return {
        "lang": "ko",
        "preset_version": PRESET_VERSION,
        "script": [{"text": t} for t in KO_SCRIPT],
        "cuts": cuts,
        "voice": {"narration_asset_ids": narr},
        "source_audio": "mute",
        "cta": {"text": "프로필 링크 확인"},
        "disclosure": {"text": "제휴 링크 포함"},
    }


def test_shop08_photo_pan_zoom_change_across_frames_while_none_is_static(
    api, server, media, ssamples, tmp_path
):
    spec = _photo_spec(server, ssamples, ["zoom", "pan", "none", "zoom"])
    status, body = _shop_render(api, server, media, tmp_path, spec, "ko")
    assert status == "done", body
    rep = _report(server)
    assert [c["motion"] for c in rep["cuts"]] == ["zoom", "pan", "none", "zoom"]
    mp4 = tmp_path / "photo.mp4"
    mp4.write_bytes(_up(server, "output_mp4")[0])
    start = 0
    diffs = []
    for c in rep["cuts"]:
        end = start + c["frames"]
        # 같은 컷 안(자막은 문장 동안 동일, 테스트 이미지 중앙부만 비교)의 처음·끝 프레임
        box = (0, 400, 1080, 1200)
        a = _frame(mp4, start + 1).crop(box)
        b = _frame(mp4, end - 2).crop(box)
        diffs.append(_mad(a, b))
        start = end
    assert diffs[0] > 2 and diffs[1] > 2 and diffs[3] > 2, diffs  # pan·zoom은 프레임 간 변화
    assert diffs[2] < diffs[0] / 4 and diffs[2] < 1.0, diffs  # none은 정지


def test_shop08_travel_vertical_photo_pan_zoom_motion_renders(
    api, server, media, ssamples, tmp_path
):
    spec = _photo_spec(server, ssamples, ["pan", "zoom", "none", "pan"])
    spec["vertical"] = "travel"  # 여행 쇼핑 작업 spec
    status, body = _shop_render(api, server, media, tmp_path, spec, "ko")
    assert status == "done", body
    rep = _report(server)
    assert [c["motion"] for c in rep["cuts"]] == ["pan", "zoom", "none", "pan"]
    mp4 = tmp_path / "travel.mp4"
    mp4.write_bytes(_up(server, "output_mp4")[0])
    start, diffs = 0, []
    for c in rep["cuts"]:
        end = start + c["frames"]
        box = (0, 400, 1080, 1200)
        diffs.append(_mad(_frame(mp4, start + 1).crop(box), _frame(mp4, end - 2).crop(box)))
        start = end
    assert diffs[0] > 2 and diffs[1] > 2 and diffs[3] > 2, diffs
    assert diffs[2] < 1.0, diffs


def test_shop08_failure_unknown_motion_type_rejected(api, server, media, ssamples, tmp_path):
    spec = _photo_spec(server, ssamples, ["zoom", "spin", "none", "none"])
    status, body = _shop_render(api, server, media, tmp_path, spec, "ko")
    assert status == "failed" and body["error_code"] == "render_failed"
    assert not server.uploaded
