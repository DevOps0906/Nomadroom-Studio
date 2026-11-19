"""task-038 인수 테스트(워커 쪽): 예능형 VAR-01~04 실제 ffmpeg 렌더.

가짜 FastAPI·Storage + 실제 ffmpeg. 원본은 lavfi 합성(저작물 없음, 가로 16:9 1280x720 포함).
컷 표는 분석 문서 #2의 예제 14개(컷 3은 속도 1.0·길이 1.37초).
근거: tasks/plan-variety-shorts.md#인수 기준.
"""

import json
import subprocess
import uuid

import pytest
from PIL import Image, ImageChops
from worker_fakes import FFMPEG, ffprobe_streams, make_task, needs_ffmpeg

from production.adapter_variety import PRESET_VERSION, frame_of
from production.runner import run_task

pytestmark = needs_ffmpeg

FPS = 30
SEGMENT = 51.5
# (출력 길이, 원본 시작, 배율, x 정규화) — x px = x×540
EXAMPLE = [
    (1.60, 24.77, 1.48, 0),
    (0.43, 27.17, 1.48, 0),
    (1.37, 2.00, 1.48, 0.48),
    (3.93, 15.40, 1.48, 0),
    (1.93, 19.33, 1.48, 0.28),
    (0.90, 21.27, 1.48, 0.28),
    (3.07, 24.73, 1.66, -0.06),
    (2.77, 33.10, 1.48, 0.45),
    (0.63, 39.13, 1.48, 0),
    (1.10, 39.80, 1.48, 0),
    (2.20, 41.00, 1.48, 0),
    (0.70, 43.30, 1.48, 0),
    (0.90, 44.00, 1.48, 0),
    (2.47, 46.13, 1.48, 0.28),
]
INSIDE = range(562, 1374)


def cuts14() -> list[dict]:
    return [
        {"src_start": s, "src_end": round(s + d, 4), "scale": sc, "x": x * 540, "y": 0}
        for d, s, sc, x in EXAMPLE
    ]


def vspec(**over) -> dict:
    spec = {
        "lang": "ko",
        "preset_version": PRESET_VERSION,
        "header": {"lines": ["끼는 넘치는데", "바람은 못 피우는 사주ㅋㅋ"]},
        "cuts": cuts14(),
        "subtitles": [],
        "reactions": [],
    }
    spec.update(over)
    return spec


def _ff(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def landscape(tmp_path_factory):
    """초록 단색 1280x720(16:9) 51.5초 + 사인 소리."""
    d = tmp_path_factory.mktemp("var_src")
    _ff(
        *("-f", "lavfi", "-i", f"color=c=0x00FF00:size=1280x720:rate=30:duration={SEGMENT}"),
        *("-f", "lavfi", "-i", f"sine=frequency=440:duration={SEGMENT}"),
        *("-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-g", "30"),
        *("-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest"),
        str(d / "land.mp4"),
    )
    return d / "land.mp4"


def render(api, server, media, tmp_path, source, spec):
    server.uploaded.clear()
    server.inputs["source"] = (str(uuid.uuid4()), source.read_bytes())
    task = make_task("render", spec=spec, format="variety", preset_version=PRESET_VERSION)
    status = run_task(api, task, tmp_path, media, 120)
    return status, server.finished[-1]


def output(server, kind="output_mp4") -> bytes:
    return next(b for a, b in server.uploaded.items() if server.issued[a]["kind"] == kind)


def frame(path, t: float) -> Image.Image:
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", f"{t:.4f}", "-i", str(path), "-frames:v", "1"]
        + ["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        check=True,
        capture_output=True,
    ).stdout
    return Image.frombytes("RGB", (1080, 1920), raw)


def count(img: Image.Image, box: tuple[int, int, int, int], r, g, b) -> int:
    """box 안에서 R·G·B가 각각 (lo, hi) 범위인 픽셀 수."""
    chans = img.crop(box).split()
    mask = None
    for ch, (lo, hi) in zip(chans, (r, g, b), strict=True):
        m = ch.point(lambda v, lo=lo, hi=hi: 255 if lo <= v <= hi else 0)
        mask = m if mask is None else ImageChops.multiply(mask, m)
    return mask.histogram()[255]


GREEN = ((0, 110), (150, 255), (0, 110))
WHITE = ((226, 255), (226, 255), (226, 255))
BLACK = ((0, 40), (0, 40), (0, 40))
RED = ((190, 255), (0, 90), (0, 90))


def rows(img, ys, color, x0=0, x1=1080) -> int:
    return count(img, (x0, ys.start, x1, ys.stop), *color)


@pytest.fixture(scope="module")
def full(request, landscape, tmp_path_factory):
    """VAR-01·02 공용: 예제 14컷(자막 없음) 렌더 1회."""
    import httpx
    from worker_fakes import API_BASE, FFPROBE, FakeServer, fake_token

    from production.api import WorkerApi
    from production.media import Media

    server = FakeServer(fake_token())
    api = WorkerApi(
        API_BASE,
        server.token,
        transport=httpx.MockTransport(server.api_handler),
        storage_transport=httpx.MockTransport(server.storage_handler),
    )
    media = Media(FFMPEG, FFPROBE)
    tmp = tmp_path_factory.mktemp("var_full")
    status, body = render(api, server, media, tmp, landscape, vspec())
    api.close()
    out = tmp / "full.mp4"
    out.write_bytes(output(server))
    return {
        "status": status,
        "body": body,
        "mp4": out,
        "report": json.loads(output(server, "report")),
        "kinds": sorted(server.issued[a]["kind"] for a in body.get("asset_ids", [])),
    }


# === VAR-01 =====================================================================


def test_var01_fourteen_cuts_output_spec_length_and_report_table(full):
    assert full["status"] == "done", full["body"]
    assert full["kinds"] == ["output_mp4", "report"]
    streams = ffprobe_streams(full["mp4"])
    v = next(s for s in streams if s["codec_type"] == "video")
    a = next(s for s in streams if s["codec_type"] == "audio")
    assert (v["width"], v["height"], v["r_frame_rate"], v["codec_name"]) == (
        1080,
        1920,
        "30/1",
        "h264",
    )
    assert a["codec_name"] == "aac"
    total = sum(d for d, *_ in EXAMPLE)
    assert abs(float(v["duration"]) - total) <= 1 / FPS + 1e-6  # 컷 합계 ±1프레임
    assert abs(float(a["duration"]) - float(v["duration"])) <= 1 / FPS + 1e-6
    rep = full["report"]
    assert (rep["width"], rep["height"], rep["fps"]) == (1080, 1920, 30)
    assert rep["has_audio"] is True and rep["cut_count"] == 14
    acc, expect = 0.0, []
    for d, s, *_ in EXAMPLE:
        expect.append(
            {
                "out_start": frame_of(acc) / FPS,
                "src_start": s,
                "length": d,
                "frames": frame_of(acc + d) - frame_of(acc),
            }
        )
        acc += d
    got = [{k: c[k] for k in ("out_start", "src_start", "length", "frames")} for c in rep["cuts"]]
    assert len(got) == 14
    for g, e in zip(got, expect, strict=True):  # 리포트 컷 표 = 편집안(프레임 격자 반올림)
        assert g["src_start"] == e["src_start"] and g["frames"] == e["frames"]
        assert abs(g["out_start"] - e["out_start"]) <= 1 / FPS  # 리포트는 소수 2자리·누적 길이 기준
        assert abs(g["length"] - e["length"]) < 0.02
    assert sum(g["frames"] for g in got) == frame_of(total)


# === VAR-02 =====================================================================


def test_var02_no_source_pixels_outside_band_and_no_hole_inside(full):
    """16:9 원본 14컷 전부(컷 중간 시각)에서 띠 밖 초록 0, 띠 안 흰색(빈 곳) 0."""
    acc = 0.0
    for d, *_ in EXAMPLE:
        img = frame(full["mp4"], acc + d / 2)
        assert rows(img, range(0, 558), GREEN) + rows(img, range(1379, 1920), GREEN) == 0, acc
        assert rows(img, INSIDE, WHITE) == 0, acc
        acc += d
    # 띠 바로 안쪽 첫·끝 줄은 원본, 바로 밖은 흰 캔버스(좌우 끝 열 포함)
    img = frame(full["mp4"], 0.4)
    for y in (561, 1374):
        assert all(count(img, (x, y, x + 1, y + 1), *GREEN) for x in (0, 540, 1079))
    for y in (556, 1379):
        assert count(img, (540, y, 541, y + 1), *WHITE) == 1


def test_var02_boundary_scale_for_landscape_fills_band_exactly(
    api, server, media, landscape, tmp_path
):
    """16:9 경계 배율(816/607.5=1.343): 통과하고 빈 곳 0, 조금 작으면 막힌다."""
    edge = 816 / (1080 * 720 / 1280) + 0.002
    cut = {"src_start": 1.0, "src_end": 2.0, "scale": edge, "x": 0, "y": 0}
    status, body = render(api, server, media, tmp_path, landscape, vspec(cuts=[cut]))
    assert status == "done", body
    out = tmp_path / "edge.mp4"
    out.write_bytes(output(server))
    img = frame(out, 0.5)
    assert (
        rows(img, INSIDE, WHITE) == 0
        and rows(img, range(0, 558), GREEN) + rows(img, range(1379, 1920), GREEN) == 0
    )
    small = {**cut, "scale": edge - 0.05}
    status, body = render(api, server, media, tmp_path, landscape, vspec(cuts=[small]))
    assert status == "failed" and body["error_code"] == "render_failed"
    assert not server.uploaded


# === VAR-03 =====================================================================


def test_var03_line_punch_reaction_and_title_visible_together(
    api, server, media, landscape, tmp_path
):
    cut = {"src_start": 2.0, "src_end": 6.0, "scale": 1.5, "x": 0, "y": 0}
    spec = vspec(
        cuts=[cut],
        subtitles=[
            {"start": 0.0, "end": 1.6, "style": "line", "text": "관상을 보면"},
            {"start": 2.0, "end": 3.6, "style": "punch", "text": "바람기를 안다?"},
        ],
        reactions=[{"start": 0.5, "end": 1.4, "text": "(긴장...)", "x": 540, "y": 800}],
    )
    status, body = render(api, server, media, tmp_path, landscape, spec)
    assert status == "done", body
    out = tmp_path / "v3.mp4"
    out.write_bytes(output(server))
    sub_box = (0, 1190, 1080, 1290)
    react_box = (240, 740, 840, 860)
    title_box = (0, 328, 1080, 497)

    both = frame(out, 1.0)  # 대사(line) + 반응 동시
    assert count(both, sub_box, *BLACK) > 2000, "대사 검정 알약 없음"
    assert count(both, react_box, *RED) > 300, "반응 자막(빨강) 없음"
    assert count(both, react_box, *WHITE) > 100, "반응 흰 테두리 없음"
    punch = frame(out, 2.8)  # 펀치(빨강 알약), 검정 알약 없음, 반응 없음
    assert count(punch, sub_box, *RED) > 2000, "펀치 빨강 알약 없음"
    assert count(punch, sub_box, *BLACK) < 200
    assert count(punch, react_box, *RED) == 0
    gap = frame(out, 1.8)  # 자막 공백: 알약도 반응도 없다
    assert count(gap, sub_box, *RED) + count(gap, sub_box, *BLACK) == 0
    for t in (0.05, 1.0, 2.8, 3.9):  # 제목은 영상 내내
        assert count(frame(out, t), title_box, *RED) > 1500, t


# === VAR-04 (워커 재검증) ===========================================================


def test_var04_worker_rejects_empty_area_and_range_with_no_output(
    api, server, media, landscape, tmp_path
):
    for cut in (
        {"src_start": 0, "src_end": 1, "scale": 1.0, "x": 0, "y": 0},  # 16:9 배율 1 빈 화면
        {"src_start": 0, "src_end": 1, "scale": 1.5, "x": 900, "y": 0},  # 이동 초과
        {"src_start": 50, "src_end": 53, "scale": 1.5, "x": 0, "y": 0},  # 원본 범위 초과
        {"src_start": 0, "src_end": 0.19, "scale": 1.5, "x": 0, "y": 0},  # 0.2초 미만
    ):
        status, body = render(api, server, media, tmp_path, landscape, vspec(cuts=[cut]))
        assert status == "failed", cut
        assert body == {"status": "failed", "error_stage": "render", "error_code": "render_failed"}
        assert not server.uploaded


def test_var04_boundary_0_2s_cut_and_short_items_render(api, server, media, landscape, tmp_path):
    """0.2초 컷(6프레임)·1.4초 미만 자막·0.5초 미만 컷은 경고 수준이라 렌더된다."""
    cuts = [
        {"src_start": 0, "src_end": 0.2, "scale": 1.5, "x": 0, "y": 0},
        {"src_start": 3, "src_end": 3.45, "scale": 1.5, "x": 0, "y": 0},
    ]
    subs = [{"start": 0.0, "end": 0.4, "style": "line", "text": "짧게"}]
    status, body = render(api, server, media, tmp_path, landscape, vspec(cuts=cuts, subtitles=subs))
    assert status == "done", body
    rep = json.loads(output(server, "report"))
    assert [c["frames"] for c in rep["cuts"]] == [6, 14]  # 0.45초 = 13.5프레임 → 0.5 올림 격자
