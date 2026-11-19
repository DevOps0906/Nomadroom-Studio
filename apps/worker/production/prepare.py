"""원본 준비(배포본 scripts/prepare.py 이식, 출처 licenses/THIRD_PARTY.md).

변경점: URL 다운로드(yt-dlp)는 없음(task-031). 입력은 W-06으로 받은 작업 폴더의 파일만,
ffprobe로 형식 확인 후 형식 고정 입력(F3). 출력 이름은 작업 폴더 안 고정 이름.
"""

import json
import math
import re
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from production.errors import TaskFailed
from production.media import Cancel, Media, MediaError, MediaTimeout, file_input
from production.paths import WorkDir

LABEL_FONT = Path(__file__).resolve().parent.parent / "fonts" / "Pretendard-Black.otf"
MAX_SEGMENT_SEC = 180
VIDEO_DEMUXERS = {"mov", "matroska"}  # 원본 업로드: mp4·mov·webm·mkv


def _fail(code: str, detail: str) -> TaskFailed:
    return TaskFailed("prepare", code, detail)


def prepare(
    raw: Path,
    work: WorkDir,
    start: float,
    length: float | None,
    media: Media,
    cancel: Cancel,
    on_progress: Callable[[str, int], None],
) -> dict:
    """raw → source.mp4·analysis.json·sheet_NNN.jpg. 반환: {source, analysis, sheets, meta}."""
    try:
        meta = media.probe(raw, cancel)
    except MediaTimeout:
        raise _fail("unknown", "ffmpeg 시간 초과") from None
    except MediaError:
        raise _fail("input_invalid", "원본을 읽을 수 없음") from None
    if meta["demuxer"] not in VIDEO_DEMUXERS or not meta["has_video"]:
        raise _fail("input_invalid", "영상 원본이 아님")
    if not math.isfinite(start) or start < 0 or start >= meta["duration"]:
        raise _fail("range_invalid", "시작 시각이 원본 밖")
    duration = length if length is not None else meta["duration"] - start
    if not math.isfinite(duration) or not 0.1 <= duration <= meta["duration"] - start + 0.05:
        raise _fail("range_invalid", "구간 길이가 원본 밖")
    if duration > MAX_SEGMENT_SEC:
        raise _fail("range_invalid", "구간이 180초 초과")

    on_progress("extract", 0)
    source = work.path("source.mp4")
    try:
        media.run(
            media.ffmpeg_cmd(
                "-y",
                "-ss",
                str(start),
                *file_input(raw, meta["demuxer"]),
                "-t",
                str(duration),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1",
                "-r",
                "30",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-movflags",
                "+faststart",
                "file:" + str(source),
            ),
            cancel,
        )
        actual = media.probe(source, cancel)
        on_progress("extract", 60)
        _, scenes = media.run(
            media.ffmpeg_cmd(
                *file_input(source, "mov"),
                "-vf",
                "scale=270:-2,select='gt(scene,0.08)',showinfo",
                "-an",
                "-f",
                "null",
                "-",
            ),
            cancel,
        )
    except MediaTimeout:
        raise _fail("unknown", "ffmpeg 시간 초과") from None
    except MediaError:
        raise _fail("input_invalid", "구간 추출 실패") from None
    candidates = sorted({float(x) for x in re.findall(r"pts_time:([\d.]+)", scenes)})
    out_meta = {
        "duration_sec": actual["duration"],
        "width": actual["width"],
        "height": actual["height"],
        "has_audio": actual["has_audio"],
    }
    analysis = work.path("analysis.json")
    analysis.write_text(
        json.dumps(
            {
                **out_meta,
                "fps": 30,
                "source_start": start,
                "scene_candidates": candidates,
                "note": "Candidates only; visually verify. Sheet frames every 0.5 seconds.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    on_progress("sheet", 0)
    frames_dir = work.path("frames")
    frames_dir.mkdir()
    try:
        media.run(
            media.ffmpeg_cmd(
                "-y",
                *file_input(source, "mov"),
                "-vf",
                "fps=2,scale=180:320:force_original_aspect_ratio=decrease,"
                "pad=180:320:(ow-iw)/2:(oh-ih)/2",
                "file:" + str(frames_dir / "%05d.jpg"),
            ),
            cancel,
        )
    except MediaTimeout:
        raise _fail("unknown", "ffmpeg 시간 초과") from None
    except MediaError:
        raise _fail("input_invalid", "시트 프레임 추출 실패") from None
    frames = sorted(frames_dir.glob("*.jpg"))
    if not frames:
        raise _fail("input_invalid", "시트 프레임 없음")
    label_font = ImageFont.truetype(str(LABEL_FONT), 15)
    sheets: list[Path] = []
    pages = math.ceil(len(frames) / 24)
    for page in range(pages):
        cancel.check()
        sheet = Image.new("RGB", (6 * 180, 4 * 346), "#191919")
        draw = ImageDraw.Draw(sheet)
        for local, frame in enumerate(frames[page * 24 : (page + 1) * 24]):
            x, y = (local % 6) * 180, (local // 6) * 346
            with Image.open(frame) as im:
                sheet.paste(im, (x, y + 26))
            label = f"{(page * 24 + local) * 0.5:.1f}s"
            draw.text((x + 6, y + 4), label, font=label_font, fill="white")
        path = work.path(f"sheet_{page + 1:03d}.jpg")
        sheet.save(path, quality=90)
        sheets.append(path)
        on_progress("sheet", (page + 1) * 100 // pages)
    return {"source": source, "analysis": analysis, "sheets": sheets, "meta": out_meta}
