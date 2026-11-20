"""task-028 인수 테스트(워커 쪽): CAT-02·04·05·06·07 + 배포본 validate 동등성(오류 메시지 고정).

가짜 FastAPI·Storage + 실제 ffmpeg. 샘플은 전부 lavfi 합성(저작물 없음).
근거: Nomadroom_Category_Shorts_PRD.md#5 인수 테스트 표.
"""

import json
import re
import subprocess
import uuid
from pathlib import Path

import pytest
from PIL import Image
from worker_fakes import (
    FFMPEG,
    FFPROBE,
    ffprobe_streams,
    make_spec,
    make_task,
    needs_ffmpeg,
)

from production.adapter import PRESET_VERSION, to_project
from production.errors import HookTooLong, RenderFailed
from production.render import check_hook, validate
from production.runner import run_task

pytestmark = needs_ffmpeg


def _ff(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def media_files(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("acc028")
    sine = ["-f", "lavfi", "-i", "sine=frequency=440:duration={}"]
    enc = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"]
    # 앞 30초 파랑 + 뒤 12초 빨강(구간 시작 30초 검증용), 오디오 있음
    _ff(
        "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=25:d=30",
        "-f", "lavfi", "-i", "color=c=red:s=640x360:r=25:d=12",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=42",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map", "[v]", "-map", "2:a", *enc, "-shortest", str(d / "two_color_42s.mp4"),
    )  # fmt: skip
    # 4초 소리 있음 / 소리 없음 / 왼쪽 가장자리에 흰 피사체
    _ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=4",
        *[a.format(4) for a in sine], *enc, "-shortest", str(d / "with_audio.mp4"))  # fmt: skip
    _ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=4",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(d / "silent.mp4"))  # fmt: skip
    _ff("-f", "lavfi",
        "-i", "color=c=black:s=640x360:r=25:d=4,drawbox=x=0:y=100:w=60:h=160:color=white:t=fill",
        *[a.format(4) for a in sine], *enc, "-shortest", str(d / "edge_subject.mp4"))  # fmt: skip
    _ff("-f", "lavfi", "-i", "sine=frequency=660:duration=0.6", str(d / "hook_ok.wav"))
    _ff("-f", "lavfi", "-i", "sine=frequency=660:duration=3", str(d / "hook_long.wav"))
    return {p.stem: p for p in d.iterdir()}


def spec4(**over) -> dict:
    """4초 편집안. 첫 자막 종료 1.2초(훅 0.6초 + 0.08 허용)."""
    s = make_spec(
        duration=4.0,
        shots=[
            {"start": 0, "end": 2, "scale": 1.0, "y": 0},
            {"start": 2, "end": 4, "scale": 1.2, "y": -100},
        ],
        items=[
            {"start": 0, "end": 1.2, "kind": "white", "text": "이렇게 된다고?"},
            {"start": 1.2, "end": 4, "kind": "emph", "text": "완성", "y": 400},
        ],
    )
    s.update(over)
    return s


def uploaded(server, kind):
    return [b for a, b in server.uploaded.items() if server.issued[a]["kind"] == kind]


def render_once(
    api, server, media, tmp_path, files, source="with_audio", hook="hook_ok", spec=None
):
    server.inputs["source"] = (str(uuid.uuid4()), files[source].read_bytes())
    if hook:
        server.inputs["hook_audio"] = (str(uuid.uuid4()), files[hook].read_bytes())
    task = make_task("render", spec=spec or spec4())
    status = run_task(api, task, tmp_path, media, 60)
    return task, status


def save_mp4(server, tmp_path) -> Path:
    mp4 = tmp_path / "out.mp4"
    mp4.write_bytes(uploaded(server, "output_mp4")[0])
    return mp4


def mean_volume(path: Path, start: float, length: float) -> float:
    r = subprocess.run(
        [FFMPEG, "-hide_banner", "-ss", str(start), "-t", str(length), "-i", str(path),
         "-vn", "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    m = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", r.stderr)
    assert m, r.stderr[-300:]
    return float("-inf") if m.group(1) == "-inf" else float(m.group(1))


def frame_at(path: Path, t: float, tmp_path: Path) -> Image.Image:
    png = tmp_path / f"f_{t}.png"
    _ff("-ss", str(t), "-i", str(path), "-frames:v", "1", str(png))
    return Image.open(png).convert("RGB")


# === CAT-02: 30초 지점부터 15초(합성은 10초) =========================================


def test_cat02_prepare_records_source_start_30_and_timeline_starts_at_zero(
    api, server, media, media_files, tmp_path
):
    server.inputs["source_upload"] = (str(uuid.uuid4()), media_files["two_color_42s"].read_bytes())
    task = make_task("prepare", source_start_sec=30.0, segment_len_sec=10.0)
    assert run_task(api, task, tmp_path, media, 60) == "done"
    analysis = json.loads(uploaded(server, "analysis")[0])
    assert analysis["source_start"] == 30.0  # 원본 시작은 30초로 기록
    body = server.finished[-1]
    assert abs(body["meta"]["duration_sec"] - 10.0) < 0.2  # 편집 타임라인은 0~10초
    seg = tmp_path / "seg.mp4"
    seg.write_bytes(uploaded(server, "source")[0])
    first = frame_at(seg, 0.2, tmp_path).getpixel((300, 180))
    assert first[0] > 150 and first[2] < 80, first  # 30초 이후(빨강)부터 잘렸다


def test_cat02_range_past_end_is_range_invalid(api, server, media, media_files, tmp_path):
    server.inputs["source_upload"] = (str(uuid.uuid4()), media_files["two_color_42s"].read_bytes())
    task = make_task("prepare", source_start_sec=45.0, segment_len_sec=10.0)
    assert run_task(api, task, tmp_path, media, 60) == "failed"
    assert server.finished[-1]["error_code"] == "range_invalid"


# === CAT-04: 훅 음성이 첫 자막에 안 들어감 ==========================================


def test_cat04_hook_too_long_reports_code_without_output(api, server, media, media_files, tmp_path):
    _, status = render_once(api, server, media, tmp_path, media_files, hook="hook_long")
    assert status == "failed"
    assert server.finished[-1] == {
        "status": "failed",
        "error_stage": "audio",
        "error_code": "hook_too_long",
    }
    assert server.uploaded == {}  # 산출물 없음(편집안은 서버가 보존)


@pytest.mark.parametrize(
    ("hook", "first_end", "duration", "ok"),
    [
        (0.93, 1.0, 10.0, True),  # 0.93+0.08=1.01 <= 1.02
        (0.96, 1.0, 10.0, False),  # 1.04 > 1.02
        (0.5, 5.0, 0.4, False),  # duration이 더 짧으면 duration 기준
    ],
)
def test_cat04_hook_formula_boundary(hook, first_end, duration, ok):
    if ok:
        assert check_hook(hook, duration, first_end) == pytest.approx(hook + 0.08)
    else:
        with pytest.raises(HookTooLong):
            check_hook(hook, duration, first_end)


# === CAT-05: 원본 음성 있음/없음 ====================================================


def test_cat05_source_audio_returns_after_hook(api, server, media, media_files, tmp_path):
    _, status = render_once(api, server, media, tmp_path, media_files, source="with_audio")
    assert status == "done"
    mp4 = save_mp4(server, tmp_path)
    assert mean_volume(mp4, 0.05, 0.45) > -45  # 훅 구간에 소리
    assert mean_volume(mp4, 1.5, 2.0) > -45  # 훅 이후 원본 소리 복귀


def test_cat05_silent_source_stays_silent_after_hook(api, server, media, media_files, tmp_path):
    _, status = render_once(api, server, media, tmp_path, media_files, source="silent")
    assert status == "done"
    mp4 = save_mp4(server, tmp_path)
    assert mean_volume(mp4, 0.05, 0.45) > -45  # 훅 음성은 들림
    assert mean_volume(mp4, 1.5, 2.0) < -70  # 훅 이후 무음 유지(가짜 소리 없음)
    assert {s["codec_type"] for s in ffprobe_streams(mp4)} == {"video", "audio"}


# === CAT-06: 긴 제목·자막, 가장자리 피사체, 실제 MP4 스트림 ===========================


def test_cat06_real_mp4_stream_spec(api, server, media, media_files, tmp_path):
    _, status = render_once(api, server, media, tmp_path, media_files)
    assert status == "done"
    mp4 = save_mp4(server, tmp_path)
    streams = ffprobe_streams(mp4)
    v = next(s for s in streams if s["codec_type"] == "video")
    a = next(s for s in streams if s["codec_type"] == "audio")
    assert (v["width"], v["height"], v["r_frame_rate"], v["codec_name"]) == (
        608,
        1080,
        "30/1",
        "h264",
    )
    assert a["codec_name"] == "aac"
    fmt = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(mp4)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert abs(float(json.loads(fmt.stdout)["format"]["duration"]) - 4.0) < 0.1
    report = json.loads(uploaded(server, "report")[0])
    assert report["preset_version"] == PRESET_VERSION
    assert "Watch final video" in report["review_required"]  # 사람이 검수하도록 리포트에 명시


def test_cat06_long_title_and_caption_shrink_but_stay_inside_frame(
    api, server, media, media_files, tmp_path
):
    spec = spec4(
        header={"lines": ["아주아주 긴 첫째 줄 제목 열여덟글자", "둘째 줄도 꽤 긴 제목 열여섯자"]},
        items=[
            {"start": 0, "end": 1.2, "kind": "white", "text": "화면 폭 안에 들어가도록 줄어들어야 하는 긴 자막입니다"},  # noqa: E501
            {"start": 1.2, "end": 4, "kind": "emph", "text": "강조 자막도 길게 써 봅니다 정말로", "y": 400},  # noqa: E501
        ],
    )  # fmt: skip
    _, status = render_once(api, server, media, tmp_path, media_files, spec=spec)
    assert status == "done"
    mp4 = save_mp4(server, tmp_path)
    img = frame_at(mp4, 0.5, tmp_path)
    for y in range(140, 250):  # 제목 띠: 글자 행 양 끝 6px 여백에 글자(밝은 픽셀)가 닿지 않는다
        edge = [img.getpixel((x, y)) for x in (*range(0, 6), *range(602, 608))]
        assert max(max(p) for p in edge) < 60, y
    # 제목 글자가 실제로 그려졌다(검은 띠에 흰·노랑 픽셀 존재)
    head = frame_at(mp4, 0.5, tmp_path).crop((0, 0, 608, 279))
    assert max(hi for _, hi in head.getextrema()) > 200


def test_cat06_no_black_gap_below_header(api, server, media, media_files, tmp_path):
    _, status = render_once(api, server, media, tmp_path, media_files)
    assert status == "done"
    mp4 = save_mp4(server, tmp_path)
    for t in (0.3, 1.5, 3.5):  # 구도 전환(2초) 앞뒤
        img = frame_at(mp4, t, tmp_path)
        for y in (285, 600, 1070, 1079):
            row = [sum(img.getpixel((x, y))) for x in range(0, 608, 8)]
            assert sum(row) / len(row) > 24, (t, y)  # 한 줄이 통째로 검정이면 틈


def test_cat06_edge_subject_is_cropped_and_needs_human_review(
    api, server, media, media_files, tmp_path
):
    """알려진 한계: 가로 원본을 중앙 크롭하므로 가장자리 피사체는 잘린다. 자동 탐지는 없고
    리포트의 review_required 로 사람이 확인하게 한다(PRD CAT-06 '검수')."""
    _, status = render_once(api, server, media, tmp_path, media_files, source="edge_subject")
    assert status == "done"
    img = frame_at(save_mp4(server, tmp_path), 0.5, tmp_path)
    left = [img.getpixel((x, y)) for x in range(0, 40) for y in range(300, 1000, 20)]
    assert max(max(p) for p in left) < 60  # 흰 피사체가 출력에 없다
    assert uploaded(server, "report")


def test_cat06_too_long_text_is_text_too_long(api, server, media, media_files, tmp_path):
    spec = spec4(header={"lines": ["너무 긴 제목" * 30, "둘째"]})
    _, status = render_once(api, server, media, tmp_path, media_files, spec=spec)
    assert status == "failed"
    assert server.finished[-1]["error_code"] == "text_too_long"
    assert server.uploaded == {}


# === CAT-07: 중복·재시도 ============================================================


def test_cat07_retry_from_failed_stage_with_same_task(api, server, media, media_files, tmp_path):
    """audio 단계 실패(훅 없음) 뒤 같은 task가 다시 오면 작업 폴더를 지우고 처음부터 → 성공."""
    task, status = render_once(api, server, media, tmp_path, media_files, hook=None)
    assert status == "failed" and server.finished[-1]["error_code"] == "audio_missing"
    assert not (tmp_path / str(task.id)).exists()
    server.inputs["hook_audio"] = (str(uuid.uuid4()), media_files["hook_ok"].read_bytes())
    assert run_task(api, task, tmp_path, media, 60) == "done"
    assert server.finished[-1]["status"] == "done"
    assert not (tmp_path / str(task.id)).exists()


def test_cat07_redelivered_task_does_not_duplicate_or_overwrite_outputs(
    api, server, media, media_files, tmp_path
):
    """W-05 재시작 복구로 같은 task가 두 번 오면 산출물은 매번 새 asset_id(덮어쓰기 없음),
    두 번째 finish 409(서버가 이미 처리)는 이미 처리됨으로 보고 끝낸다."""
    task, first = render_once(api, server, media, tmp_path, media_files)
    assert first == "done"
    first_ids = list(server.finished[-1]["asset_ids"])
    server.finish_status = 409
    assert run_task(api, task, tmp_path, media, 60) == "done"
    second_ids = server.finished[-1]["asset_ids"]
    assert not set(first_ids) & set(second_ids)
    assert len(server.finished) == 2  # 409 뒤 재시도 없음


def test_cat07_stop_on_409_leaves_no_finish_and_no_leftover(
    api, server, media, media_files, tmp_path
):
    server.progress_status = 409
    task, status = render_once(api, server, media, tmp_path, media_files)
    assert status == "cancelled"
    assert server.finished == [] and not (tmp_path / str(task.id)).exists()


# === 배포본 validate 동등성: 오류 메시지 고정(task-021 리뷰 🟡1) ======================
# 기대 메시지는 배포본 scripts/render.py validate()의 ValueError 메시지다(배포본 코드는 import하지
# 않고 값만 고정). 의도된 차이 1건: 훅은 첨부 음성이 정본이라 문구만 검사 →
# 'hook text is required.'(배포본: 'hook text or hook_audio is required.').

SRC_META = {"width": 640, "height": 360, "duration": 60.0, "has_audio": True, "demuxer": "mov"}


def proj(**over) -> dict:
    p = to_project(spec4(duration=4.0), "ko")
    p.update(over)
    return p


BAD = {
    "lang": (dict(lang="en"), "lang must be ko or ja."),  # 의도된 차이(ko·ja만, task-050)
    "header_one_line": (dict(header=["하나"]), "header must contain two nonempty strings."),
    "header_three_lines": (
        dict(header=["a", "b", "c"]),
        "header must contain two nonempty strings.",
    ),
    "header_blank": (dict(header=["a", "  "]), "header must contain two nonempty strings."),
    "duration_nan": (dict(duration=float("nan")), "duration must be a finite number."),
    "duration_inf": (dict(duration=float("inf")), "duration must be a finite number."),
    "duration_bool": (dict(duration=True), "duration must be a finite number."),
    "duration_over_source": (
        dict(duration=61.0),
        "duration is outside source bounds (maximum 180s).",
    ),
    "shots_empty": (dict(shots=[]), "shots must cover the full timeline."),
    "shot_five_values": (
        dict(shots=[[0, 4, 1.0, 0, 9]]),
        "shot format: [start, end, zoom, y]",
    ),
    "shot_gap": (
        dict(shots=[[0, 1.5, 1.0, 0], [2, 4, 1.0, 0]]),
        "Shots must be continuous, ordered and within duration.",
    ),
    "shot_zoom": (
        dict(shots=[[0, 4, 3.5, 0]]),
        "Shot transform leaves a blank area or uses zoom outside 1..3.",
    ),
    "shot_blank": (
        dict(shots=[[0, 4, 1.0, -100]]),
        "Shot transform leaves a blank area or uses zoom outside 1..3.",
    ),
    "shots_short": (dict(shots=[[0, 3, 1.0, 0]]), "Shots must end at duration."),
    "items_empty": (dict(items=[]), "At least one caption is required."),
    "item_len3": (
        dict(items=[[0, 4, "white"]]),
        "caption format: [start, end, white|paren|emph, text, optional_y]",
    ),
    "item_overlap": (
        dict(items=[[0, 2, "white", "a"], [1, 4, "white", "b"]]),
        "Captions must be ordered, nonoverlapping and within duration.",
    ),
    "item_kind": (dict(items=[[0, 4, "red", "a"]]), "Invalid caption kind/text."),
    "item_blank": (dict(items=[[0, 4, "white", " "]]), "Invalid caption kind/text."),
    "item_y_low": (
        dict(items=[[0, 4, "white", "a", 100]]),
        "caption y must be between 310 and 1030.",
    ),
    "item_y_high": (
        dict(items=[[0, 4, "white", "a", 1031]]),
        "caption y must be between 310 and 1030.",
    ),
    "item_y_nan": (
        dict(items=[[0, 4, "white", "a", float("nan")]]),
        "caption y must be a finite number.",
    ),
    "first_not_zero": (
        dict(items=[[0.5, 4, "white", "a"]]),
        "First hook caption must start at zero.",
    ),
    "hook_empty": (dict(hook=""), "hook text is required."),
    "hook_blank": (dict(hook="   "), "hook text is required."),
    "header_newline": (
        dict(header=["a\nb", "c"]),
        "Each header/caption is one line; remove embedded newlines.",
    ),
    "caption_newline": (
        dict(items=[[0, 4, "white", "a\nb"]]),
        "Each header/caption is one line; remove embedded newlines.",
    ),
}


@pytest.mark.parametrize("name", list(BAD))
def test_validate_error_messages_match_distributed_validate(name):
    over, message = BAD[name]
    with pytest.raises(RenderFailed) as exc:
        validate(proj(**over), SRC_META)
    assert (exc.value.stage, exc.value.code) == ("render", "render_failed")
    assert exc.value.detail == message


def test_validate_accepts_good_and_boundaries():
    assert validate(proj(), SRC_META) == 4.0
    # y 경계값 310·1030 포함, 소스 길이+0.05 허용
    assert validate(proj(items=[[0, 4, "white", "a", 310]]), SRC_META) == 4.0
    assert validate(proj(items=[[0, 4, "white", "a", 1030]]), SRC_META) == 4.0
    assert validate(proj(duration=60.05, shots=[[0, 60.05, 1.0, 0]], items=[[0, 60.05, "white", "a"]]), SRC_META) == 60.05  # fmt: skip  # noqa: E501
