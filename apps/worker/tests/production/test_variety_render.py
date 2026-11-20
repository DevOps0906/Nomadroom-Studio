"""예능형 렌더러(task-036): 재검증(W6)·덮임(W3)·글꼴(W8·W9)·실제 ffmpeg 렌더(W2·W7).

합성 원본만 쓴다(lavfi, 저작물 없음). 실제 렌더는 가짜 API·Storage로 run_task 전체 흐름.
"""

import json
import subprocess
import uuid

import pytest
from PIL import Image
from worker_fakes import FFMPEG, ffprobe_streams, make_spec, make_task, needs_ffmpeg

from production.adapter import PRESET_VERSION as CATEGORY_PRESET
from production.adapter_variety import PRESET_VERSION, covered, frame_of, to_variety_project
from production.errors import RenderFailed, TextTooLong
from production.runner import run_task
from production.variety.text import (
    FALLBACK_FONT,
    PRIMARY_FONT,
    pick_font,
    subtitle_layer,
    title_layer,
)

FPS = 30
META_V = {"width": 360, "height": 640, "duration": 6.0, "has_audio": True, "demuxer": "mov"}
LAND_SCALE = 816 / (1080 * 360 / 640)  # 640×360 원본이 띠 높이를 딱 채우는 배율(경계)


def vspec(**over) -> dict:
    spec = {
        "lang": "ko",
        "preset_version": PRESET_VERSION,
        "header": {"lines": ["끼는 넘치는데", "바람은 못 피우는 사주ㅋㅋ"]},
        "cuts": [{"src_start": 0.0, "src_end": 1.0, "scale": 1.0, "x": 0, "y": 0}],
        "subtitles": [],
        "reactions": [],
    }
    spec.update(over)
    return spec


def vtask(spec=None, **kw):
    base = {"format": "variety", "preset_version": PRESET_VERSION}
    return make_task("render", spec=spec if spec is not None else vspec(), **{**base, **kw})


# --- W6 비신뢰 spec 재검증 -----------------------------------------------------------


@pytest.mark.parametrize(
    "ch", ["\x00", "\x09", "\x1b", "\x7f", "\x85", "\u200b", "\u200f", "\u202e", "\u2066", "\ufeff"]
)
def test_control_chars_rejected_everywhere(ch):
    bad = "가" + ch + "나"
    for spec in (
        vspec(header={"lines": [bad]}),
        vspec(subtitles=[{"start": 0, "end": 0.5, "style": "line", "text": bad}]),
        vspec(reactions=[{"start": 0, "end": 0.5, "text": bad, "x": 10, "y": 10}]),
    ):
        with pytest.raises(RenderFailed):
            to_variety_project(spec, "ko", META_V)


def test_line_separators_and_header_newline_rejected_subtitle_newline_kept():
    for bad in ("가\u2028나", "가\u2029나", "가\n나", "가\r나"):
        with pytest.raises(RenderFailed):
            to_variety_project(vspec(header={"lines": [bad]}), "ko", META_V)
    sub = {"start": 0, "end": 0.5, "style": "punch", "text": "첫 줄\r\n둘째 줄"}
    project = to_variety_project(vspec(subtitles=[sub]), "ko", META_V)
    assert project["subtitles"][0]["text"] == "첫 줄\n둘째 줄"


@pytest.mark.parametrize(
    "over",
    [
        {"cuts": []},
        {"cuts": [{"src_start": 0.0, "src_end": 0.25, "scale": 1, "x": 0, "y": 0}] * 61},
        {"cuts": [{"src_start": 0.0, "src_end": 0.1, "scale": 1, "x": 0, "y": 0}]},
        {"cuts": [{"src_start": 1.0, "src_end": 6.2, "scale": 1, "x": 0, "y": 0}]},
        {"cuts": [{"src_start": -0.5, "src_end": 1.0, "scale": 1, "x": 0, "y": 0}]},
        {"cuts": [{"src_start": 0.0, "src_end": 1.0, "scale": 3.5, "x": 0, "y": 0}]},
        {"cuts": [{"src_start": 0.0, "src_end": 1.0, "scale": 1, "x": 1, "y": 0}]},
        {"cuts": [{"src_start": 0.0, "src_end": 1.0, "scale": True, "x": 0, "y": 0}]},
        {"cuts": [{"src_start": 0.0, "src_end": float("nan"), "scale": 1, "x": 0, "y": 0}]},
        {"subtitles": [{"start": 0, "end": 1.5, "style": "line", "text": "길이 초과"}]},
        {"subtitles": [{"start": 0, "end": 0.5, "style": "white", "text": "형식"}]},
        {"subtitles": [{"start": 0, "end": 0.5, "style": "line", "text": "   "}]},
        {"subtitles": [{"start": 0, "end": 0.5, "style": "line", "text": "가" * 201}]},
        {
            "subtitles": [
                {"start": 0, "end": 0.6, "style": "line", "text": "하나"},
                {"start": 0.5, "end": 0.9, "style": "punch", "text": "겹침"},
            ]
        },
        {"subtitles": [{"start": 0, "end": 0.5, "style": "line", "text": "x"}] * 201},
        {"reactions": [{"start": 0, "end": 0.5, "text": "(긴장...)", "x": 1081, "y": 10}]},
        {"reactions": [{"start": 0, "end": 0.5, "text": "(긴장...)", "x": 10, "y": -1}]},
        {"header": {"lines": ["가" * 61]}},
        {"header": {"lines": ["하나", "둘", "셋"]}},
        {"header": {"lines": []}},
        {"preset_version": CATEGORY_PRESET},
        {"lang": "ja"},
    ],
)
def test_untrusted_spec_rejected(over):
    with pytest.raises(RenderFailed):
        to_variety_project(vspec(**over), "ko", META_V)


def test_total_over_180_rejected():
    meta = {**META_V, "duration": 180.0}
    cut = {"src_start": 0.0, "src_end": 90.0, "scale": 1, "x": 0, "y": 0}
    to_variety_project(vspec(cuts=[cut, cut]), "ko", meta)  # 180초 정확히는 허용
    with pytest.raises(RenderFailed):
        to_variety_project(vspec(cuts=[cut, cut, {**cut, "src_end": 0.3}]), "ko", meta)


def test_job_lang_ko_or_ja():  # task-051: ja 허용(더빙), 그 밖의 언어는 거부
    assert to_variety_project(vspec(lang=None), "ja", META_V)["lang"] == "ja"
    with pytest.raises(RenderFailed):
        to_variety_project(vspec(lang=None), "en", META_V)


def test_cut_boundaries_on_frame_grid():
    """W2: 컷 경계 = 누적 출력 시각×30 반올림. 프레임 합 = 총길이×30 반올림."""
    lens = [0.217, 0.233, 0.25, 0.211, 0.3, 0.27]
    cuts, s = [], 0.0
    for n in lens:
        cuts.append({"src_start": s, "src_end": s + n, "scale": 1, "x": 0, "y": 0})
        s += 0.4
    p = to_variety_project(vspec(cuts=cuts), "ko", META_V)
    acc = 0.0
    for c, n in zip(p["cuts"], lens, strict=True):
        assert c["frame_start"] == frame_of(acc)
        acc += n
        assert c["frame_start"] + c["frames"] == frame_of(acc)
    assert p["frames"] == frame_of(sum(lens)) == 44


# --- W3 덮임(실제 원본 크기, 크기 ceil·위치 floor) ----------------------------------


def test_cover_boundary_scale_and_shift():
    assert covered(LAND_SCALE, 0, 0, 640, 360)
    assert not covered(LAND_SCALE - 0.01, 0, 0, 640, 360)
    max_x = (1080 * 2 - 1080) / 2
    assert covered(2, max_x, 0, 640, 360) and covered(2, -max_x, 0, 640, 360)
    assert not covered(2, max_x + 1, 0, 640, 360)
    assert covered(1, 0, 0, 360, 640)  # 세로 원본은 배율 1로 띠를 덮는다
    max_y = (1920 - 816) / 2
    assert covered(1, 0, max_y, 360, 640) and not covered(1, 0, max_y + 1, 360, 640)


def test_probed_size_rechecks_cover():
    """서버는 다른 크기를 믿었어도 워커가 probe한 실제 크기로 다시 판정한다."""
    spec = vspec(cuts=[{"src_start": 0, "src_end": 1, "scale": 1, "x": 0, "y": 0}])
    to_variety_project(spec, "ko", META_V)
    with pytest.raises(RenderFailed):
        to_variety_project(spec, "ko", {**META_V, "width": 640, "height": 360})


# --- W8·W9 글꼴 ----------------------------------------------------------------------


def test_font_fallback_order_and_glyph_missing():
    assert pick_font("바람은 못 피우는 사주ㅋㅋ (긴장...)") == PRIMARY_FONT
    assert pick_font("관상 觀相") == FALLBACK_FONT  # Pretendard에 한자 없음 → Noto
    with pytest.raises(RenderFailed) as exc:
        pick_font("웃음 \U0001f602")
    assert exc.value.detail == "glyph_missing"
    assert (PRIMARY_FONT.parent.parent / "licenses" / "Pretendard-OFL.txt").is_file()
    assert (PRIMARY_FONT.parent.parent / "licenses" / "NotoSansCJK-OFL.txt").is_file()


def test_text_too_long_after_shrink():
    with pytest.raises(TextTooLong):
        title_layer(["가" * 60], [])
    with pytest.raises(TextTooLong):
        subtitle_layer({"start": 0, "end": 1, "style": "line", "text": "가" * 200}, [])
    fonts: list[str] = []
    title_layer(["끼는 넘치는데", "바람은 못 피우는 사주ㅋㅋ"], fonts)
    assert fonts == ["Pretendard-Black", "Pretendard-Black"]


# --- 실제 렌더(가짜 API·Storage, 실제 ffmpeg) ------------------------------------------


def _ffmpeg(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def vsamples(tmp_path_factory):
    """green: 단색 초록 640×360(가로)+사인. ramp: 360×640 밝기=시간 램프, 4.0초부터 흰 화면 +
    같은 순간 1kHz 삐 소리. mute: 소리 없는 360×640."""
    if not FFMPEG:
        pytest.skip("ffmpeg 없음")
    d = tmp_path_factory.mktemp("variety")
    enc = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30"]
    aac = ["-c:a", "aac", "-ar", "48000", "-ac", "2"]
    _ffmpeg(
        *("-f", "lavfi", "-i", "color=c=0x00FF00:size=640x360:rate=30:duration=2"),
        *("-f", "lavfi", "-i", "sine=frequency=440:duration=2"),
        *enc,
        *aac,
        "-shortest",
        str(d / "green.mp4"),
    )
    _ffmpeg(
        *("-f", "lavfi", "-i", "nullsrc=size=360x640:rate=30:duration=6"),
        *("-f", "lavfi", "-i", "aevalsrc=exprs='if(between(t,4,4.3),0.8*sin(2*PI*1000*t),0)'"),
        "-vf",
        "format=yuv420p,geq=lum='if(gte(T,4),235,16+T*25)':cb=128:cr=128",
        *enc,
        *aac,
        "-t",
        "6",
        str(d / "ramp.mp4"),
    )
    _ffmpeg(
        *("-f", "lavfi", "-i", "color=c=gray:size=360x640:rate=30:duration=2"),
        *enc,
        str(d / "mute.mp4"),
    )
    return {p.stem: p for p in d.iterdir()}


def _run(api, server, media, tmp_path, source, spec, **kw):
    server.inputs["source"] = (str(uuid.uuid4()), source.read_bytes())
    task = vtask(spec, **kw)
    status = run_task(api, task, tmp_path, media, 60)
    return status, server.finished[-1]


def _output(server, kind="output_mp4"):
    return next(b for a, b in server.uploaded.items() if server.issued[a]["kind"] == kind)


def _frame(path, t: float) -> Image.Image:
    out = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", f"{t:.4f}", "-i", str(path), "-frames:v", "1"]
        + ["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        check=True,
        capture_output=True,
    ).stdout
    return Image.frombytes("RGB", (1080, 1920), out)


def _count(img: Image.Image, rows: range, pred) -> int:
    raw = img.tobytes()
    n = 0
    for y in rows:
        row = raw[y * 1080 * 3 : (y + 1) * 1080 * 3]
        n += sum(1 for i in range(0, len(row), 3) if pred(row[i], row[i + 1], row[i + 2]))
    return n


def is_green(r, g, b):
    return g > 150 and r < 110 and b < 110


def is_white(r, g, b):
    return r > 225 and g > 225 and b > 225


@needs_ffmpeg
def test_render_band_pixels_and_output_format(api, server, media, vsamples, tmp_path):
    """W7: 단색 초록 원본 → 띠 밖 초록 0, 띠 안 흰색 0(경계 2px 여유). W3: 경계 배율·이동 픽셀.
    산출물 ffprobe 1080×1920·30/1·h264/aac. 산출물은 output_mp4·report만(훅 음성 없음)."""
    cuts = [
        {"src_start": 0.0, "src_end": 0.8, "scale": LAND_SCALE, "x": 0, "y": 0},
        {"src_start": 0.5, "src_end": 1.5, "scale": 2.0, "x": 540, "y": -0.0},
    ]
    status, body = _run(api, server, media, tmp_path, vsamples["green"], vspec(cuts=cuts))
    assert status == "done", body
    kinds = sorted(server.issued[a]["kind"] for a in body["asset_ids"])
    assert kinds == ["output_mp4", "report"]
    out = tmp_path / "out.mp4"
    out.write_bytes(_output(server))
    streams = ffprobe_streams(out)
    video = next(s for s in streams if s["codec_type"] == "video")
    audio = next(s for s in streams if s["codec_type"] == "audio")
    assert (video["width"], video["height"]) == (1080, 1920)
    assert video["r_frame_rate"] == "30/1" and video["codec_name"] == "h264"
    assert audio["codec_name"] == "aac"
    outside = [*range(0, 558), *range(1379, 1920)]
    inside = range(562, 1374)
    for t in (0.4, 1.3):
        img = _frame(out, t)
        assert _count(img, outside, is_green) == 0
        assert _count(img, inside, is_white) == 0
        # 경계 배율: 띠 첫·끝 줄 바로 안쪽도 초록, 밖 3px은 흰색(좌우 끝 열 포함)
        for y in (561, 1374):
            assert all(is_green(*img.getpixel((x, y))) for x in (0, 1, 540, 1078, 1079))
        for y in (556, 1379):
            assert is_white(*img.getpixel((540, y)))
    report = json.loads(_output(server, "report"))
    assert report["width"] == 1080 and report["height"] == 1920 and report["fps"] == 30
    assert report["cut_count"] == 2 and report["has_audio"] is True
    assert report["cuts"] == [
        {"out_start": 0.0, "src_start": 0.0, "length": 0.8, "frames": 24},
        {"out_start": 0.8, "src_start": 0.5, "length": 1.0, "frames": 30},
    ]
    assert report["font_substituted"] is True and report["fonts"] == ["Pretendard-Black"]
    assert report["render_sec"] >= 0 and report["preset_version"] == PRESET_VERSION


def _luma(img: Image.Image) -> float:
    band = img.crop((0, 600, 1080, 1100)).convert("L").resize((1, 1), Image.Resampling.BOX)
    return band.getpixel((0, 0))


@needs_ffmpeg
def test_render_order_lengths_and_av_sync(api, server, media, vsamples, tmp_path):
    """W2: 짧은 컷 여러 개 뒤 마지막 컷의 화면(흰 전환)과 소리(삐) 오차 ≤ 1프레임.
    컷 순서(원본 뒤→앞)와 총길이(컷 합 ±1프레임)도 확인. 자막·반응을 함께 그린다."""
    lens = [0.5, 0.5, 0.217, 0.233, 0.25, 0.211, 0.27, 0.229]
    starts = [3.0, 0.5, 1.1, 1.45, 1.8, 2.15, 2.5, 2.85]
    cuts = [
        {"src_start": s, "src_end": s + n, "scale": 1.0, "x": 0, "y": 0}
        for s, n in zip(starts, lens, strict=True)
    ]
    cuts.append({"src_start": 3.61, "src_end": 5.0, "scale": 1.2, "x": 30, "y": -40})
    total = sum(lens) + 1.39
    spec = vspec(
        cuts=cuts,
        subtitles=[
            {"start": 0.0, "end": 1.0, "style": "line", "text": "관상을 보면"},
            {"start": 1.2, "end": total, "style": "punch", "text": "바람기를 안다?"},
        ],
        reactions=[{"start": 0.5, "end": 2.0, "text": "(긴장...)", "x": 300, "y": 720}],
    )
    status, body = _run(api, server, media, tmp_path, vsamples["ramp"], spec)
    assert status == "done", body
    out = tmp_path / "out.mp4"
    out.write_bytes(_output(server))
    streams = ffprobe_streams(out)
    vdur = float(next(s for s in streams if s["codec_type"] == "video")["duration"])
    adur = float(next(s for s in streams if s["codec_type"] == "audio")["duration"])
    assert abs(vdur - total) <= 1 / FPS + 1e-6
    assert abs(adur - vdur) <= 1 / FPS + 1e-6
    # 순서: 첫 컷(원본 3.0초대)이 둘째 컷(원본 0.5초대)보다 밝다
    assert _luma(_frame(out, 0.25)) > _luma(_frame(out, 0.75)) + 40
    # 화면 전환 프레임: 마지막 컷 근처를 한 장씩 디코드
    gray = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(out), "-vf", "crop=1080:400:0:600,scale=8:4"]
        + ["-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
        check=True,
        capture_output=True,
    ).stdout
    means = [sum(gray[i : i + 32]) / 32 for i in range(0, len(gray), 32)]
    flash = next(i for i, m in enumerate(means) if m > 200)
    pcm = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(out), "-vn", "-ac", "1", "-ar", "48000"]
        + ["-f", "s16le", "pipe:1"],
        check=True,
        capture_output=True,
    ).stdout
    samples = memoryview(pcm).cast("h")
    peak = max(abs(v) for v in samples)
    onset = next(i for i, v in enumerate(samples) if abs(v) > peak * 0.2)
    last_start = frame_of(sum(lens)) / FPS
    assert abs(flash / FPS - (last_start + 0.39)) <= 1 / FPS + 1e-6
    assert abs(flash / FPS - onset / 48000) <= 1 / FPS


@needs_ffmpeg
def test_render_mute_source_gets_aac_track(api, server, media, vsamples, tmp_path):
    cuts = [{"src_start": 0.2, "src_end": 1.0, "scale": 1, "x": 0, "y": 0}] * 2
    status, body = _run(api, server, media, tmp_path, vsamples["mute"], vspec(cuts=cuts))
    assert status == "done", body
    out = tmp_path / "out.mp4"
    out.write_bytes(_output(server))
    streams = ffprobe_streams(out)
    audio = [s for s in streams if s["codec_type"] == "audio"]
    assert len(audio) == 1 and audio[0]["codec_name"] == "aac"
    assert abs(float(audio[0]["duration"]) - 1.6) <= 1 / FPS + 1e-6
    report = json.loads(_output(server, "report"))
    assert report["source_has_audio"] is False and report["has_audio"] is True


@needs_ffmpeg
@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"header": {"lines": ["가" * 60]}}, "text_too_long"),
        ({"header": {"lines": ["웃음 \U0001f602"]}}, "render_failed"),
        ({"header": {"lines": ["제목\u202e"]}}, "render_failed"),
        ({"cuts": [{"src_start": 0, "src_end": 1, "scale": 1, "x": 0, "y": 0}]}, "render_failed"),
    ],
)
def test_render_failures_reported(api, server, media, vsamples, tmp_path, over, code):
    """마지막 행: 가로 원본(640×360)은 배율 1로 띠를 못 덮는다(W3 실제 크기 재검증)."""
    green_cut = {"src_start": 0, "src_end": 1, "scale": LAND_SCALE, "x": 0, "y": 0}
    spec = vspec(**{"cuts": [green_cut], **over})
    status, body = _run(api, server, media, tmp_path, vsamples["green"], spec)
    assert status == "failed"
    assert body == {"status": "failed", "error_stage": "render", "error_code": code}
    assert not server.uploaded


@needs_ffmpeg
@pytest.mark.parametrize(
    ("fmt", "preset", "lang"),
    [
        ("variety", CATEGORY_PRESET, "ko"),
        ("variety", PRESET_VERSION, "en"),
        ("category", PRESET_VERSION, "ko"),
        ("shopping", PRESET_VERSION, "ko"),
    ],
)
def test_preset_and_lang_checked_per_format(
    api, server, media, vsamples, tmp_path, fmt, preset, lang
):
    server.inputs["source"] = (str(uuid.uuid4()), vsamples["ramp"].read_bytes())
    spec = make_spec() if fmt != "variety" else vspec(lang=None)
    task = make_task("render", spec=spec, format=fmt, preset_version=preset, lang=lang)
    assert run_task(api, task, tmp_path, media, 60) == "failed"
    assert server.finished[-1]["error_code"] == "render_failed"
    assert not server.uploaded


# --- 리뷰 반영(task-036): 줄 수·높이·면적 상한, 원본 길이 상한, 프레임 격자, 전체 시간 상한 ----


def test_line_cap_attack_and_source_length_cap():
    for field_name, row in (
        ("subtitles", {"start": 0, "end": 0.5, "style": "line"}),
        ("reactions", {"start": 0, "end": 0.5, "x": 10, "y": 10}),
    ):
        ok = to_variety_project(
            vspec(**{field_name: [{**row, "text": "하나\n둘\r셋"}]}), "ko", META_V
        )
        assert ok[field_name][0]["text"] == "하나\n둘\n셋"
        for bad in ("a" + "\n" * 198, "하나\n둘\n셋\n넷", "하나\r\n둘\r\n셋\r\n넷"):
            with pytest.raises(RenderFailed):
                to_variety_project(vspec(**{field_name: [{**row, "text": bad}]}), "ko", META_V)
    with pytest.raises(RenderFailed):
        to_variety_project(vspec(), "ko", {**META_V, "duration": 600.5})


def test_text_height_cap():
    from production.variety.text import _fit

    with pytest.raises(RenderFailed):
        _fit("\n".join(["가"] * 10), PRIMARY_FONT, 60, 0, 1000)


def _reactions(n: int, text: str, overlap: bool) -> list[dict]:
    return [
        {
            "start": 0.0 if overlap else i * 0.005,
            "end": 1.0 if overlap else i * 0.005 + 0.005,
            "text": text,
            "x": 540,
            "y": 900,
        }
        for i in range(n)
    ]


def test_reaction_flood_is_lazy_and_area_capped():
    from production.variety.render import _layers

    project = to_variety_project(vspec(reactions=_reactions(200, "(긴장...)", False)), "ko", META_V)
    _, layers, _ = _layers(project)
    assert len(layers) == 200 and all(x._image is None for x in layers)  # 표시 전에는 안 그린다
    long_text = "하...핳하ㅏㅏ핳;;;; 하...핳하ㅏㅏ핳;;;;\n둘째 줄 문구\n셋째 줄 문구"
    project = to_variety_project(vspec(reactions=_reactions(200, long_text, True)), "ko", META_V)
    with pytest.raises(RenderFailed):
        _layers(project)


def test_layer_frames_use_cut_grid():
    """자막 끝 = 컷 경계(부동소수 누적 0.45)일 때 두 기준이 같은 프레임."""
    cuts = [
        {"src_start": 0.4, "src_end": 0.4 + n, "scale": 1, "x": 0, "y": 0} for n in (0.217, 0.233)
    ]
    p = to_variety_project(vspec(cuts=cuts), "ko", META_V)
    boundary = p["cuts"][1]["frame_start"]
    layer = subtitle_layer({"start": 0.0, "end": 0.217, "style": "line", "text": "대사"}, [])
    assert (layer.fs, layer.fe) == (0, boundary) == (0, frame_of(0.217))
    layer = subtitle_layer({"start": 0.217, "end": 0.45, "style": "punch", "text": "펀치"}, [])
    assert (layer.fs, layer.fe) == (boundary, p["frames"])


@needs_ffmpeg
def test_stuck_decoder_hits_deadline(media, vsamples, tmp_path, monkeypatch):
    import sys
    import time

    import production.variety.render as vr
    from production.media import Cancel

    real = subprocess.Popen
    started = []

    def fake_popen(args, **kw):
        if "-ss" in args:  # 컷 decoder만 멈춘 프로세스로 바꾼다(출력 없음)
            proc = real([sys.executable, "-c", "import time; time.sleep(120)"], **kw)
            started.append(proc)
            return proc
        return real(args, **kw)

    monkeypatch.setattr(vr, "DEADLINE_SEC", 3)
    monkeypatch.setattr(vr.subprocess, "Popen", fake_popen)
    src = vsamples["green"]
    meta = media.probe(src, Cancel())
    cut = {"src_start": 0, "src_end": 1, "scale": LAND_SCALE, "x": 0, "y": 0}
    project = to_variety_project(vspec(cuts=[cut]), "ko", meta)
    began = time.monotonic()
    with pytest.raises(RenderFailed) as exc:
        vr.render_variety(project, src, meta, tmp_path / "o.mp4", media, Cancel(), lambda *_: None)
    assert exc.value.detail == "렌더 시간 초과"
    assert time.monotonic() - began < 30
    assert started and all(p.poll() is not None for p in started)  # 멈춘 decoder는 kill
