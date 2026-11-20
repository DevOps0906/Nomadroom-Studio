"""쇼핑 P0 인수 테스트(워커 쪽): SHOP-01 렌더 길이·자막 구간, SHOP-02 마스크 블러.

가짜 API·Storage + 실제 ffmpeg. 원본·녹음은 lavfi로 합성(저작물 없음), TTS 대신 첨부 녹음.
근거: tasks/plan-shopping-japanese.md#인수 기준.
"""

import json
import subprocess
import uuid
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat
from worker_fakes import FFMPEG, ffprobe_streams, make_task, needs_ffmpeg

from production.adapter_shopping import PRESET_VERSION
from production.adapter_variety import frame_of
from production.errors import RenderFailed
from production.runner import run_task

pytestmark = needs_ffmpeg

FPS = 30
# 글자 수가 서로 달라 자막 알약 폭이 문장마다 다르다(구간 판별용)
SCRIPT = ["아팠어요", "이 깔창을 넣고 걸었어요", "덜 피곤해요", "링크에서 확인하세요 지금"]
NARR_SEC = [1.0, 1.4, 1.2, 1.0]
MASK = {"x": 0, "y": 300, "w": 1080, "h": 600}


def _ff(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def media_files(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("shop_acc")
    vsrc = {
        "white": "color=c=white:size=540x960:rate=30:duration=6",  # 자막 알약(검정) 검출용
        "noise": "color=c=gray:size=540x960:rate=30:duration=6,noise=alls=90:allf=t",
    }
    for name, expr in vsrc.items():
        _ff(
            *("-f", "lavfi", "-i", expr, "-f", "lavfi", "-i", "sine=frequency=330:duration=6"),
            *("-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"),
            str(d / f"{name}.mp4"),
        )
    for i, sec in enumerate(NARR_SEC):
        _ff(
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={400 + 100 * i}:duration={sec},volume=4",
            str(d / f"n{i}.wav"),
        )
    return {p.name: p for p in d.iterdir()}


def _id() -> str:
    return str(uuid.uuid4())


def _spec(server, files, srcs: list[str], masks=None) -> dict:
    """원본 업로드 N개(→ 파생 source, parent=업로드) + 녹음 4개를 W-06 목록에 넣고 4문장 spec을 만든다."""  # noqa: E501
    narr = [_id() for _ in range(4)]
    uploads = [_id() for _ in srcs]
    for up, name in zip(uploads, srcs, strict=True):
        server.input_items.append(
            {
                "asset_id": _id(),
                "kind": "source",
                "body": files[f"{name}.mp4"].read_bytes(),
                "parent": up,
            }
        )
    for n, i in zip(narr, range(4), strict=True):
        server.input_items.append(
            {"asset_id": n, "kind": "narration", "body": files[f"n{i}.wav"].read_bytes()}
        )
    order = [0, 1, 2, 0]  # 문장 → 원본 번호(원본 3개 모두 사용)
    cuts = []
    for s, k in enumerate(order[: len(order)], start=1):
        cut = {
            "source_asset_id": uploads[k % len(uploads)],
            "src_start": 0.0,
            "src_end": 1.0,
            "scale": 1.0,
            "x": 0,
            "y": 0,
            "sentence": s,
        }
        if masks and s == 1:
            cut["masks"] = masks
        cuts.append(cut)
    return {
        "lang": "ko",
        "preset_version": PRESET_VERSION,
        "script": [{"text": t} for t in SCRIPT],
        "cuts": cuts,
        "voice": {"narration_asset_ids": narr},
        "source_audio": "mute",
        "cta": {"text": "프로필 링크 확인"},
        "disclosure": {"text": "제휴 링크 포함"},
    }


def _render(api, server, media, tmp_path, spec) -> tuple[str, dict]:
    server.uploaded.clear()
    task = make_task(
        "render", job_kind="shopping", format="shopping", preset_version=PRESET_VERSION, spec=spec
    )
    status = run_task(api, task, tmp_path, media, 60)
    return status, server.finished[-1]


def _out(server, tmp_path, name="out.mp4") -> Path:
    body = next(b for a, b in server.uploaded.items() if server.issued[a]["kind"] == "output_mp4")
    p = tmp_path / name
    p.write_bytes(body)
    return p


def _report(server) -> dict:
    return json.loads(
        next(b for a, b in server.uploaded.items() if server.issued[a]["kind"] == "report")
    )


def _frame(path: Path, frame_no: int) -> Image.Image:
    t = (frame_no + 0.5) / FPS
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", f"{t:.4f}", "-i", str(path), "-frames:v", "1"]
        + ["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        check=True,
        capture_output=True,
    ).stdout
    return Image.frombytes("RGB", (1080, 1920), raw)


def _pill_extent(img: Image.Image) -> tuple[int, int] | None:
    """자막 영역(y 1250~1510)에서 어두운 픽셀이 있는 가로 범위. 없으면 None."""
    luma = img.crop((0, 1250, 1080, 1510)).convert("L").point(lambda v: 255 if v < 100 else 0)
    box = luma.getbbox()
    return None if box is None else (box[0], box[2])


def _var(img: Image.Image, box) -> float:
    return sum(ImageStat.Stat(img.crop(box).convert("L")).var)


# === SHOP-01 ====================================================================


def test_shop01_three_sources_four_sentences_length_and_subtitle_intervals(
    api, server, media, media_files, tmp_path
):
    spec = _spec(server, media_files, ["white", "white", "white"])
    status, body = _render(api, server, media, tmp_path, spec)
    assert status == "done", body
    out = _out(server, tmp_path)
    rep = _report(server)

    v = next(s for s in ffprobe_streams(out) if s["codec_type"] == "video")
    a = next(s for s in ffprobe_streams(out) if s["codec_type"] == "audio")
    assert (v["width"], v["height"], v["r_frame_rate"], v["codec_name"]) == (
        1080,
        1920,
        "30/1",
        "h264",
    )
    # 길이: 입력 녹음 합 대비 짧아짐 범위 + 정리 후 문장 실측 합 ±1프레임
    rec = sum(
        float(next(x for x in ffprobe_streams(media_files[f"n{i}.wav"]))["duration"])
        for i in range(4)
    )
    durs = [s["duration"] for s in rep["sentences"]]
    # 기준(사용자 결정 2026-11-20): 무음 정리 후 내레이션 합 ±1프레임.
    # 정리로 녹음당 약 0.04초 짧아짐은 허용
    assert 0 <= rec - float(v["duration"]) <= 4 * 0.05 + 1 / FPS
    assert 0 <= rec - float(a["duration"]) <= 4 * 0.05 + 1 / FPS
    assert abs(float(v["duration"]) - sum(durs)) <= 1 / FPS + 1e-6
    # 원본 3개 모두 쓰였다
    assert len({c["source_asset_id"] for c in rep["cuts"]}) == 3

    # 자막 = 문장 구간: 구간 안에서는 같은 알약, 경계를 넘으면 다음 문장의 알약(폭이 다르다)
    bounds = [s["frame_start"] for s in rep["sentences"]] + [rep["sentences"][-1]["frame_end"]]
    cum, expect = 0.0, [0]
    for d in durs:
        cum += d
        expect.append(frame_of(cum))
    assert bounds == expect
    ext = []
    for i in range(4):
        inside = [
            _pill_extent(_frame(out, f))
            for f in (bounds[i] + 3, (bounds[i] + bounds[i + 1]) // 2, bounds[i + 1] - 4)
        ]
        assert inside[0] is not None and inside[0] == inside[1] == inside[2], (i, inside)
        ext.append(inside[0])
    # 자막 없는 같은 원본(순백)과 비교: 자막 영역만 실제로 달라진다
    white = Image.new("RGB", (1080, 1920), "white")
    shot = _frame(out, (bounds[0] + bounds[1]) // 2)
    sub, away = (0, 1250, 1080, 1510), (0, 600, 1080, 1000)
    assert ImageChops.difference(shot.crop(sub), white.crop(sub)).getbbox() is not None
    assert (
        sum(ImageStat.Stat(ImageChops.difference(shot.crop(sub), white.crop(sub)).convert("L")).sum)
        > 20000
    )
    assert (
        max(ImageChops.difference(shot.crop(away), white.crop(away)).convert("L").getextrema()) <= 8
    )  # yuv 반올림
    assert len(set(ext)) == 4, ext  # 문장마다 다른 자막
    for i in (1, 2, 3):  # 경계 직전 = 앞 문장, 직후 = 다음 문장
        assert _pill_extent(_frame(out, bounds[i] - 3)) == ext[i - 1]
        assert _pill_extent(_frame(out, bounds[i] + 3)) == ext[i]


def test_shop01_boundary_fewer_than_four_recordings_fails_without_output(
    api, server, media, media_files, tmp_path
):
    """경계·실패: 녹음 3개(4문장 아님)는 렌더 실패, 산출물 없음."""
    spec = _spec(server, media_files, ["white", "white", "white"])
    spec["voice"]["narration_asset_ids"] = spec["voice"]["narration_asset_ids"][:3]
    status, body = _render(api, server, media, tmp_path, spec)
    assert status == "failed" and body["error_code"] == "render_failed"
    assert not server.uploaded


# === SHOP-02 ====================================================================


def test_shop02_mask_area_variance_drops_only_inside(api, server, media, media_files, tmp_path):
    base = _spec(server, media_files, ["noise", "noise", "noise"])
    status, body = _render(api, server, media, tmp_path, base)
    assert status == "done", body
    plain = _out(server, tmp_path, "plain.mp4")
    masked_spec = _spec(server, media_files, ["noise", "noise", "noise"], masks=[MASK])
    status, body = _render(api, server, media, tmp_path, masked_spec)
    assert status == "done", body
    masked = _out(server, tmp_path, "masked.mp4")

    mid = 15  # 문장 1 구간 안(1.0초 = 30프레임)
    inside, outside = (0, 320, 1080, 880), (0, 960, 1080, 1260)
    before, after = _frame(plain, mid), _frame(masked, mid)
    assert _var(after, inside) < _var(before, inside) * 0.3  # 마스크 안: 원본보다 확연히 낮다
    assert _var(after, outside) > _var(before, outside) * 0.7  # 마스크 밖은 그대로
    rep = _report(server)
    assert rep["cuts"][0]["source_asset_id"]  # 마스크 컷이 문장 1에 있었다


def test_shop02_boundary_mask_out_of_canvas_rejected(api, server, media, media_files, tmp_path):
    """경계: 캔버스 밖으로 나가는 마스크(y 1800+200)는 렌더 실패, 산출물 없음."""
    bad = _spec(
        server,
        media_files,
        ["noise", "noise", "noise"],
        masks=[{"x": 0, "y": 1800, "w": 100, "h": 200}],
    )
    status, body = _render(api, server, media, tmp_path, bad)
    assert status == "failed" and body["error_code"] == "render_failed"
    assert not server.uploaded
    with pytest.raises(RenderFailed):
        from production.adapter_shopping import to_shopping_project

        to_shopping_project(bad, "ko")
