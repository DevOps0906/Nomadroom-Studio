"""task-045 쇼핑 렌더러(가짜 API·Storage, 실제 ffmpeg). 합성 미디어만(lavfi, 저작물 없음).

R1 원본별 prepare·parent, R2 asset_id 기준 입력·재발급, R3 W-06 미제공 id 거부, R5 컷 원본 →
파생 source, R6 사진 매직 바이트·`-f *_pipe`(image2 금지)·면적 상한, R8 문장 경계·스트림 길이.
"""

import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from PIL import Image, ImageStat
from worker_fakes import FFMPEG, FFPROBE, ffprobe_streams, make_task, needs_ffmpeg

from production import api as api_mod
from production import media as media_mod
from production import tts as tts_mod
from production.adapter_shopping import (
    PRESET_VERSION,
    bind_inputs,
    layout,
    sentence_frames,
    to_shopping_project,
)
from production.adapter_variety import frame_of
from production.api import SignedUrl
from production.config import TtsSettings
from production.errors import RenderFailed
from production.media import Cancel, MediaError, sniff_image
from production.runner import run_task
from production.shopping.render import blur_masks, decode_image, image_frames

FPS = 30
SCRIPT = [
    "발이 아픈 날이 많았어요.",
    "이 깔창을 넣고 걸어 봤어요.",
    "오래 걸어도 덜 피곤해요.",
    "프로필 링크에서 확인하세요.",
]
NARR_SEC = [0.7, 0.9, 1.1, 0.8]
ON = TtsSettings(enabled=True, timeout_sec=30)


def _ff(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def ssamples(tmp_path_factory) -> dict[str, Path]:
    if not FFMPEG:
        pytest.skip("ffmpeg 없음")
    d = tmp_path_factory.mktemp("shop")
    # 파생 source: 세로 540×960 노이즈(마스크 분산 비교용) + 소리, 6초
    _ff(
        *("-f", "lavfi", "-i", "color=c=gray:size=540x960:rate=30:duration=6,noise=alls=90:allf=t"),
        *("-f", "lavfi", "-i", "sine=frequency=330:duration=6"),
        *("-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"),
        str(d / "src.mp4"),
    )
    for ext in ("png", "jpg", "webp"):
        _ff("-f", "lavfi", "-i", "testsrc=size=720x1280", "-frames:v", "1", str(d / f"img.{ext}"))
    _ff("-f", "lavfi", "-i", "testsrc=size=64x64", "-frames:v", "1", str(d / "img.gif"))
    for i, sec in enumerate(NARR_SEC):
        _ff(
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={400 + 100 * i}:duration={sec}",
            str(d / f"n{i}.wav"),
        )
    _ff(
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=220:duration=1",
        "-c:a",
        "libmp3lame",
        str(d / "bgm.mp3"),
    )
    _ff(
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=520:duration=0.5",
        "-c:a",
        "libmp3lame",
        str(d / "tts.mp3"),
    )
    return {p.name: p for p in d.iterdir()}


def _id() -> str:
    return str(uuid.uuid4())


def _cut(aid, sentence, start, end, **over) -> dict:
    return {
        "source_asset_id": aid,
        "src_start": start,
        "src_end": end,
        "scale": 1.0,
        "x": 0,
        "y": 0,
        "sentence": sentence,
        **over,
    }


MASK = {"x": 0, "y": 300, "w": 1080, "h": 600}


def _setup(server, ss, tts: bool = False, duck_bgm: bool = True) -> tuple[dict, dict]:
    """원본 업로드 U(→ 파생 source S, parent=U)·사진 3장·녹음 4개·BGM을 W-06 목록에 넣는다."""
    ids = {k: _id() for k in ("U", "S", "png", "jpg", "webp", "bgm", "unused")}
    ids["narr"] = [_id() for _ in range(4)]
    items = [
        {
            "asset_id": ids["S"],
            "kind": "source",
            "body": ss["src.mp4"].read_bytes(),
            "parent": ids["U"],
        },
        *(
            {"asset_id": ids[e], "kind": "image", "body": ss[f"img.{e}"].read_bytes()}
            for e in ("png", "jpg", "webp")
        ),
        {"asset_id": ids["unused"], "kind": "image", "body": ss["img.png"].read_bytes()},
        {"asset_id": ids["bgm"], "kind": "bgm", "body": ss["bgm.mp3"].read_bytes()},
        *(
            {"asset_id": n, "kind": "narration", "body": ss[f"n{i}.wav"].read_bytes()}
            for i, n in enumerate(ids["narr"])
        ),
    ]
    server.input_items.extend(items)
    spec = {
        "lang": "ko",
        "preset_version": PRESET_VERSION,
        "script": [{"text": t} for t in SCRIPT],
        "cuts": [
            _cut(ids["U"], 1, 0.0, 2.0, masks=[MASK]),  # 원본 업로드 id → 파생 source(R5), 잘림
            _cut(ids["png"], 2, 0.0, 0.5, motion={"type": "zoom"}),
            _cut(ids["S"], 2, 1.0, 1.2),  # 파생 source 직접, 짧아서 늘림
            _cut(ids["jpg"], 3, 0.0, 1.1, motion={"type": "pan"}),
            _cut(ids["webp"], 4, 0.0, 0.3, motion={"type": "none"}),
        ],
        "voice": (
            {"tts": {"voice": "ko-KR-SunHiNeural", "rate": "+10%"}}
            if tts
            else {"narration_asset_ids": ids["narr"]}
        ),
        "source_audio": "duck" if duck_bgm else "mute",
        "cta": {"text": "프로필 링크 확인"},
        "disclosure": {"text": "제휴 링크 포함"},
    }
    if duck_bgm:
        spec["bgm_asset_id"] = ids["bgm"]
    return spec, ids


def _task(spec: dict, **kw):
    return make_task(
        "render",
        job_kind="shopping",
        format="shopping",
        preset_version=PRESET_VERSION,
        spec=spec,
        **kw,
    )


def _uploaded(server, kind):
    return [b for aid, b in server.uploaded.items() if server.issued[aid]["kind"] == kind]


def _frame(path: Path, t: float) -> Image.Image:
    out = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(path)]
        + ["-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        check=True,
        capture_output=True,
    )
    return Image.frombytes("RGB", (1080, 1920), out.stdout)


def _var(img: Image.Image, box) -> float:
    return sum(ImageStat.Stat(img.crop(box).convert("L")).var)


# --- 전체 렌더(녹음 4개) ------------------------------------------------------------


@needs_ffmpeg
def test_render_recordings_full(api, server, media, ssamples, tmp_path):
    spec, ids = _setup(server, ssamples)
    task = _task(spec)
    assert run_task(api, task, tmp_path, media, 60) == "done", server.finished
    body = server.finished[-1]
    kinds = sorted(server.issued[a]["kind"] for a in body["asset_ids"])
    assert kinds == ["output_mp4", "report"]  # 게시 문구·hook_audio 없음(R7)
    report = json.loads(_uploaded(server, "report")[0])
    out = tmp_path / "out.mp4"
    out.write_bytes(_uploaded(server, "output_mp4")[0])

    # 문장별 녹음 실측 → 자막 구간(누적 반올림, R8)
    durs = [s["duration"] for s in report["sentences"]]
    # 앞뒤 무음 정리(make_hook) 뒤 실측이라 합성 길이보다 수십 ms 짧을 수 있다
    assert all(abs(d - n) < 0.06 for d, n in zip(durs, NARR_SEC, strict=True)), durs
    cum, bounds = 0.0, [0]
    for d in durs:
        cum += d
        bounds.append(frame_of(cum))
    assert [s["frame_start"] for s in report["sentences"]] == bounds[:-1]
    assert [s["frame_end"] for s in report["sentences"]] == bounds[1:]
    total = bounds[-1] / FPS

    # 스트림별 길이를 따로 ffprobe(R8): 둘 다 실측 음성 합 ±1프레임
    streams = ffprobe_streams(out)
    v = next(s for s in streams if s["codec_type"] == "video")
    a = next(s for s in streams if s["codec_type"] == "audio")
    assert (v["width"], v["height"], v["r_frame_rate"], v["codec_name"]) == (
        1080,
        1920,
        "30/1",
        "h264",
    )
    assert a["codec_name"] == "aac"
    assert abs(float(v["duration"]) - sum(durs)) <= 1 / FPS + 1e-6
    assert abs(float(a["duration"]) - sum(durs)) <= 1 / FPS + 1e-6
    assert abs(float(v["duration"]) - total) <= 1 / FPS + 1e-6

    # 컷 맞춤 기록·원본 매핑(R5)·고정 표기·쓴 자산 id만
    cuts = report["cuts"]
    assert cuts[0]["source_asset_id"] == ids["U"] and cuts[0]["input_asset_id"] == ids["S"]
    assert cuts[0]["adjust"] == "trimmed" and cuts[2]["adjust"] == "extended"
    assert cuts[4]["adjust"] == "extended" and cuts[3]["motion"] == "pan"
    assert sum(c["frames"] for c in cuts) == bounds[-1]
    assert report["disclosure"] == "제휴 링크 포함"
    assert ids["unused"] not in report["assets_used"] and ids["U"] not in report["assets_used"]
    assert set(report["assets_used"]) >= {ids["S"], ids["bgm"], *ids["narr"]}
    assert report["source_audio"] == "duck" and report["bgm_gain"] is not None

    # 마스크(문장 1 컷): 같은 노이즈 원본의 가린 영역 분산이 안 가린 영역보다 크게 낮다
    f = _frame(out, (bounds[0] + bounds[1]) / 2 / FPS)
    masked = _var(f, (0, 320, 1080, 880))
    open_ = _var(f, (0, 960, 1080, 1260))
    assert masked < open_ * 0.3


# --- TTS 4회 ------------------------------------------------------------------------


def _fake_tts(calls: list, mp3: bytes, fail_at: int | None = None):
    async def synth(text, voice, rate, out, cfg):
        calls.append(text)
        if fail_at is not None and len(calls) == fail_at:
            raise RuntimeError("boom")
        out.write_bytes(mp3)

    return synth


@needs_ffmpeg
def test_tts_four_calls_one_failure_is_tts_failed(
    api, server, media, ssamples, tmp_path, monkeypatch
):
    calls: list = []
    monkeypatch.setattr(tts_mod, "edge_save", _fake_tts(calls, ssamples["tts.mp3"].read_bytes(), 3))
    spec, _ = _setup(server, ssamples, tts=True, duck_bgm=False)
    assert run_task(api, _task(spec), tmp_path, media, 60, tts_cfg=ON) == "failed"
    body = server.finished[-1]
    assert (body["error_stage"], body["error_code"]) == ("audio", "tts_failed")
    assert calls == SCRIPT[:3]  # 실패에서 멈춘다(대체·무음 없음)
    assert not server.uploaded


@needs_ffmpeg
def test_tts_four_sentences_success(api, server, media, ssamples, tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(tts_mod, "edge_save", _fake_tts(calls, ssamples["tts.mp3"].read_bytes()))
    spec, _ = _setup(server, ssamples, tts=True, duck_bgm=False)
    assert run_task(api, _task(spec), tmp_path, media, 60, tts_cfg=ON) == "done"
    assert calls == SCRIPT  # 문장마다 1회
    report = json.loads(_uploaded(server, "report")[0])
    assert report["voice"] == "tts" and len(report["sentences"]) == 4


def test_tts_disabled_is_tts_failed(api, server, media, ssamples, tmp_path):
    spec, _ = _setup(server, ssamples, tts=True, duck_bgm=False)
    assert run_task(api, _task(spec), tmp_path, media, 60, tts_cfg=TtsSettings()) == "failed"
    assert server.finished[-1]["error_code"] == "tts_failed"


# --- W-06 입력(R2·R3) ---------------------------------------------------------------


@needs_ffmpeg
def test_w06_missing_id_rejected(api, server, media, ssamples, tmp_path):
    spec, _ = _setup(server, ssamples)
    spec["cuts"][1]["source_asset_id"] = _id()  # W-06이 주지 않은 사진
    assert run_task(api, _task(spec), tmp_path, media, 60) == "failed"
    assert server.finished[-1]["error_code"] == "render_failed"
    assert not server.uploaded


def test_bind_rejects_unlisted_or_wrong_kind():
    spec, ids = _spec_only()
    project = to_shopping_project(spec, "ko")
    signed = [_signed(ids["S"], "source", parent=ids["U"]), _signed(ids["png"], "image")]
    signed += [_signed(n, "narration") for n in ids["narr"]]
    bound = bind_inputs(project, signed)
    assert [str(s.asset_id) for s in bound["cuts"]] == [ids["S"], ids["png"], ids["S"], ids["S"]]
    with pytest.raises(RenderFailed):  # 사진 id가 narration으로 오면 거부
        bind_inputs(project, [*signed[:1], _signed(ids["png"], "narration"), *signed[2:]])
    with pytest.raises(Exception, match="audio_missing"):
        bind_inputs(project, signed[:-1])


@needs_ffmpeg
def test_reissue_only_same_asset_id(api, server, media, ssamples, tmp_path):
    spec, ids = _setup(server, ssamples, duck_bgm=False)
    server.expire_first_inputs = True
    server.drop_on_reissue = {
        ids["png"]
    }  # 재발급 응답에 같은 id가 없으면 다른 자산으로 대체하지 않는다
    assert run_task(api, _task(spec), tmp_path, media, 60) == "failed"
    assert server.finished[-1]["error_code"] == "render_failed"


# --- 사진(R6) -----------------------------------------------------------------------


@needs_ffmpeg
def test_image_magic_bytes(media, ssamples, tmp_path):
    assert sniff_image(ssamples["img.png"]) == "png_pipe"
    assert sniff_image(ssamples["img.jpg"]) == "jpeg_pipe"
    assert sniff_image(ssamples["img.webp"]) == "webp_pipe"
    for bad in ("img.gif", "src.mp4", "n0.wav"):
        assert sniff_image(ssamples[bad]) is None
        with pytest.raises(MediaError):
            media.probe_image(ssamples[bad], Cancel())
    disguised = tmp_path / "photo.png"  # 확장자는 png지만 내용은 jpeg → jpeg로 읽는다
    shutil.copy(ssamples["img.jpg"], disguised)
    assert media.probe_image(disguised, Cancel())["demuxer"] == "jpeg_pipe"
    assert media.probe_image(ssamples["img.png"], Cancel())[("width")] == 720


@needs_ffmpeg
def test_image_area_cap(media, ssamples, monkeypatch):
    monkeypatch.setattr(media_mod, "MAX_IMAGE_PIXELS", 720 * 1280 - 1)
    with pytest.raises(MediaError):
        media.probe_image(ssamples["img.png"], Cancel())


@needs_ffmpeg
def test_image_decode_uses_pipe_demuxer_not_image2(media, ssamples, tmp_path, monkeypatch):
    seen: list[list[str]] = []
    real = media.run

    def spy(args, cancel, timeout=600):
        seen.append([str(a) for a in args])
        return real(args, cancel, timeout)

    monkeypatch.setattr(media, "run", spy)
    pattern = tmp_path / "img%03d.png"  # image2라면 패턴으로 해석될 이름
    shutil.copy(ssamples["img.png"], pattern)
    meta = media.probe_image(pattern, Cancel())
    cut = {"scale": 1.0, "x": 0, "y": 0, "motion": "zoom"}
    img = decode_image(media, pattern, meta, cut, tmp_path / "x.rgb", Cancel())
    assert img.size == (1188, 2112)  # 1080×1.1 확대 표시 크기
    for args in seen:
        assert "image2" not in args and "image2pipe" not in args
        i = args.index("-f")
        assert args[i + 1] == "png_pipe" and args[args.index("-protocol_whitelist") + 1] == "file"


# --- pan·zoom·masks 단위 ------------------------------------------------------------


def _gradient(w=720, h=1280) -> Image.Image:
    img = Image.new("RGB", (w, h))
    img.putdata([(x * 255 // w, y * 255 // h, 128) for y in range(h) for x in range(w)])
    return img


def test_zoom_enlarges_toward_end():
    img = _gradient().resize((1188, 2112))
    frames = list(image_frames(img, {"scale": 1.0, "x": 0, "y": 0, "motion": "zoom"}, 10))
    first, last = frames[0], frames[-1]
    assert first.size == last.size == (1080, 1920)
    # 확대될수록 왼쪽 끝 열이 가운데 쪽 색(R 값↑)이 된다
    assert last.getpixel((0, 960))[0] > first.getpixel((0, 960))[0] + 5
    assert first.getpixel((0, 960))[0] <= 3  # 처음은 원래 배치(왼쪽 끝 = 원본 왼쪽 끝)


def test_pan_moves_horizontally_and_keeps_cover():
    img = _gradient().resize((1188, 2112))
    frames = list(image_frames(img, {"scale": 1.0, "x": 0, "y": 0, "motion": "pan"}, 10))
    reds = [f.getpixel((540, 960))[0] for f in frames]
    assert reds[0] != reds[-1] and (reds == sorted(reds) or reds == sorted(reds, reverse=True))
    for f in (frames[0], frames[-1]):  # 가장자리에 빈(검은) 영역 없음
        assert f.getpixel((0, 960))[2] > 100 and f.getpixel((1079, 960))[2] > 100


def test_none_motion_is_static():
    img = _gradient().resize((1080, 1920))
    frames = list(image_frames(img, {"scale": 1.0, "x": 0, "y": 0, "motion": "none"}, 3))
    assert frames[0].tobytes() == frames[-1].tobytes()


def test_masks_reduce_variance_only_inside():
    noise = Image.effect_noise((1080, 1920), 80).convert("RGB")
    before_in, before_out = _var(noise, (0, 300, 1080, 900)), _var(noise, (0, 1000, 1080, 1600))
    blur_masks(noise, [(0, 300, 1080, 600)])
    assert _var(noise, (0, 300, 1080, 900)) < before_in * 0.2
    assert _var(noise, (0, 1000, 1080, 1600)) == pytest.approx(before_out)


# --- adapter·배치 단위 ---------------------------------------------------------------


def _signed(aid, kind, parent=None) -> SignedUrl:
    return SignedUrl(
        asset_id=aid,
        kind=kind,
        url="https://storage.test/x",
        expires_at="2999-01-01T00:00:00+00:00",
        parent_asset_id=parent,
    )


def _spec_only() -> tuple[dict, dict]:
    ids = {"U": _id(), "S": _id(), "png": _id(), "narr": [_id() for _ in range(4)]}
    spec = {
        "lang": "ko",
        "script": [{"text": t} for t in SCRIPT],
        "cuts": [_cut(ids["U"], s, 0, 1) for s in (1, 3, 4)] + [_cut(ids["png"], 2, 0, 1)],
        "voice": {"narration_asset_ids": ids["narr"]},
        "cta": {"text": "링크 확인"},
        "disclosure": {"text": "제휴 링크 포함"},
    }
    spec["cuts"] = [spec["cuts"][0], spec["cuts"][3], *spec["cuts"][1:3]]
    return spec, ids


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s["disclosure"].update(text="광고"),  # 고정 표기만(Q12)
        lambda s: s.update(script=s["script"][:3]),
        lambda s: s["voice"].update(narration_asset_ids=s["voice"]["narration_asset_ids"][:3]),
        lambda s: s["voice"].update(tts={"voice": "ko-KR-SunHiNeural"}),  # 둘 다
        lambda s: s["cuts"].pop(1),  # 2번 문장 컷 없음
        lambda s: s["cuts"][0].update(masks=[{"x": 0, "y": 1800, "w": 100, "h": 200}]),
        lambda s: s["cuts"][1].update(motion={"type": "spin"}),
        lambda s: s.update(preset_version="variety-1080-v1"),
        lambda s: s["script"][0].update(text="줄 바꿈"),
        lambda s: s.update(source_audio="loud"),
    ],
)
def test_untrusted_spec_rejected(mutate):
    spec, _ = _spec_only()
    mutate(spec)
    with pytest.raises(RenderFailed):
        to_shopping_project(spec, "ko")


def test_lang_ko_ja_and_preset_matches_api():
    spec, _ = _spec_only()
    with pytest.raises(RenderFailed):  # task-050: ja는 고정 표기 "PR"만
        to_shopping_project(spec, "ja")
    with pytest.raises(RenderFailed):
        to_shopping_project(spec, "en")
    spec["lang"] = "ja"
    spec["disclosure"] = {"text": "PR"}
    assert to_shopping_project(spec, "ja")["disclosure"] == "PR"
    assert PRESET_VERSION == "shopping-1080-v1"  # task-044 결정(API 작업 preset)과 같은 값


def test_motion_on_video_cut_rejected():
    spec, ids = _spec_only()
    spec["cuts"][0]["motion"] = {"type": "zoom"}
    project = to_shopping_project(spec, "ko")
    signed = [_signed(ids["S"], "source", parent=ids["U"]), _signed(ids["png"], "image")]
    signed += [_signed(n, "narration") for n in ids["narr"]]
    with pytest.raises(RenderFailed):
        bind_inputs(project, signed)


def test_sentence_frames_cumulative_rounding():
    # 각각 반올림하면 1+1+1=3프레임이지만 누적(0.05·0.1·0.15초)은 2·3·5 → 경계 오차가 쌓이지 않는다
    assert sentence_frames([0.05, 0.05, 0.05]) == [0, 2, 3, 5]
    with pytest.raises(RenderFailed):
        sentence_frames([0.7, 0.0, 1.0, 1.0])


def test_layout_trims_drops_and_extends():
    spec, _ = _spec_only()
    project = to_shopping_project(spec, "ko")
    project["cuts"] = [
        {**project["cuts"][0], "sentence": 1, "src_start": 0, "src_end": 0.5},
        {**project["cuts"][0], "sentence": 1, "src_start": 0, "src_end": 0.5},
        {**project["cuts"][0], "sentence": 1, "src_start": 0, "src_end": 0.5},
        {**project["cuts"][0], "sentence": 2, "src_start": 0, "src_end": 0.2},
        {**project["cuts"][0], "sentence": 3, "src_start": 0, "src_end": 1.0},
        {**project["cuts"][0], "sentence": 4, "src_start": 0, "src_end": 1.0},
    ]
    bounds = [0, 20, 50, 80, 110]  # 문장 1=20프레임, 2=30
    out = layout(project, bounds)
    assert [c["frames"] for c in out] == [15, 5, 0, 30, 30, 30]
    assert [c["adjust"] for c in out] == [None, "trimmed", "dropped", "extended", None, None]
    assert [c["frame_start"] for c in out] == [0, 15, 20, 20, 50, 80]


def test_claim_announces_shopping_capability(api, server):
    assert api.claim() is None
    assert json.loads(server.claim_bodies[-1]) == {"capabilities": api_mod.CAPABILITIES}
    assert "shopping" in api_mod.CAPABILITIES and "ja" in api_mod.CAPABILITIES  # task-050 K8


# --- prepare(R1) --------------------------------------------------------------------


@needs_ffmpeg
def test_prepare_shopping_per_source_with_parent(api, server, media, samples, tmp_path):
    ups = [_id(), _id()]
    for u in ups:
        server.input_items.append(
            {"asset_id": u, "kind": "source_upload", "body": samples["src"].read_bytes()}
        )
    task = make_task(
        "prepare",
        job_kind="shopping",
        format="shopping",
        preset_version=PRESET_VERSION,
        segment_len_sec=2.0,
    )
    assert run_task(api, task, tmp_path, media, 60) == "done", server.finished
    body = server.finished[-1]
    assert body["status"] == "done" and body["meta"]["has_audio"] is True
    groups: dict[str, list[str]] = {}
    for aid in body["asset_ids"]:
        it = server.issued[aid]
        groups.setdefault(it["parent_asset_id"], []).append(it["kind"])
    assert set(groups) == set(ups)
    for kinds in groups.values():
        assert kinds.count("source") == 1 and kinds.count("analysis") == 1 and "sheet" in kinds
    assert not (tmp_path / str(task.id)).exists()


@needs_ffmpeg
def test_prepare_shopping_reissue_same_id(api, server, media, samples, tmp_path):
    ups = [_id(), _id()]
    for u in ups:
        server.input_items.append(
            {"asset_id": u, "kind": "source_upload", "body": samples["src"].read_bytes()}
        )
    server.expire_first_inputs = True
    server.drop_on_reissue = {ups[0]}
    task = make_task("prepare", job_kind="shopping", format="shopping", segment_len_sec=1.0)
    assert run_task(api, task, tmp_path, media, 60) == "failed"
    assert server.finished[-1]["error_code"] == "download_failed"


@needs_ffmpeg
def test_general_prepare_sends_parent(api, server, media, samples, tmp_path):
    src = _id()
    server.inputs["source_upload"] = (src, samples["src"].read_bytes())
    task = make_task("prepare", segment_len_sec=1.0, source_kind="upload")
    assert run_task(api, task, tmp_path, media, 60) == "done"
    assert {server.issued[a].get("parent_asset_id") for a in server.finished[-1]["asset_ids"]} == {
        src
    }


def test_ffprobe_available():
    assert FFPROBE  # skip 0건 확인용(ffmpeg 없는 환경이면 위 테스트가 skip된다)


# --- 리뷰 반영(길이·개수·크기 상한, 원본 시각 기준) ------------------------------------


@needs_ffmpeg
def test_recording_over_60s_rejected(api, server, media, ssamples, tmp_path):
    spec, ids = _setup(server, ssamples, duck_bgm=False)
    long = tmp_path / "long.wav"
    _ff("-f", "lavfi", "-i", "sine=frequency=300:duration=61", "-ac", "1", "-ar", "8000", str(long))
    next(it for it in server.input_items if it["asset_id"] == ids["narr"][0])["body"] = (
        long.read_bytes()
    )
    assert run_task(api, _task(spec), tmp_path / "w", media, 60) == "failed"
    assert server.finished[-1]["error_code"] == "render_failed"
    assert not server.uploaded


def test_total_narration_over_180s_rejected():
    assert sentence_frames([45, 45, 45, 45])[-1] == 180 * FPS
    with pytest.raises(RenderFailed):
        sentence_frames([45, 45, 45, 45.1])


@needs_ffmpeg
def test_bgm_reads_only_output_length(media, tmp_path, monkeypatch):
    from production.shopping.audio import SPF, bgm_track

    raw = tmp_path / "bgm.wav"
    _ff("-f", "lavfi", "-i", "sine=frequency=200:duration=30", str(raw))
    seen: list[list[str]] = []
    real = media.run

    def spy(args, cancel, timeout=600):
        seen.append([str(a) for a in args])
        return real(args, cancel, timeout)

    monkeypatch.setattr(media, "run", spy)
    out = bgm_track(media, raw, 45, tmp_path / "bgm_out.wav", Cancel())
    decode = next(a for a in seen if "-stream_loop" in a)
    assert decode[decode.index("-t") + 1] == "1.500000"  # 출력 45프레임만큼만 읽는다
    import wave

    with wave.open(str(out), "rb") as f:
        assert f.getnframes() == 45 * SPF


def test_cut_assets_over_20_rejected():
    spec, ids = _spec_only()
    imgs = [_id() for _ in range(21)]
    spec["cuts"] = [_cut(i, n % 4 + 1, 0, 0.2) for n, i in enumerate(imgs)]
    project = to_shopping_project(spec, "ko")
    signed = [_signed(i, "image") for i in imgs] + [_signed(n, "narration") for n in ids["narr"]]
    with pytest.raises(RenderFailed):
        bind_inputs(project, signed)
    spec["cuts"] = spec["cuts"][:20]
    assert len(bind_inputs(to_shopping_project(spec, "ko"), signed)["cuts"]) == 20


@needs_ffmpeg
def test_total_input_bytes_cap(api, server, media, ssamples, tmp_path, monkeypatch):
    from production import runner as runner_mod

    spec, _ = _setup(server, ssamples, duck_bgm=False)
    monkeypatch.setattr(
        runner_mod, "MAX_TOTAL_INPUT_BYTES", ssamples["src.mp4"].stat().st_size + 10
    )
    assert run_task(api, _task(spec), tmp_path, media, 60) == "failed"
    assert server.finished[-1]["error_code"] == "render_failed"
    assert not server.uploaded


@needs_ffmpeg
@pytest.mark.parametrize("seconds,expected", [(40, 40.0), (70, 60.0)])
def test_prepare_shopping_whole_source_ignores_job_segment(
    api, server, media, tmp_path, seconds, expected
):
    # 팀장 결정: 쇼핑은 원본마다 0초부터 전체(최대 60초)를 파생 source로(job 구간 0/30 미적용)
    src = tmp_path / "long.mp4"
    _ff(
        *("-f", "lavfi", "-i", f"testsrc=size=160x90:rate=10:duration={seconds}"),
        *("-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"),
        *("-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac"),
        *("-shortest", str(src)),
    )
    up = _id()
    server.input_items.append({"asset_id": up, "kind": "source_upload", "body": src.read_bytes()})
    task = make_task(
        "prepare",
        job_kind="shopping",
        format="shopping",
        preset_version=PRESET_VERSION,
        source_start_sec=5.0,
        segment_len_sec=30.0,
    )
    assert run_task(api, task, tmp_path / "w", media, 60) == "done", server.finished
    source = next(
        server.issued[a]
        for a in server.finished[-1]["asset_ids"]
        if server.issued[a]["kind"] == "source"
    )
    assert source["parent_asset_id"] == up
    assert abs(source["duration_sec"] - expected) < 0.2
