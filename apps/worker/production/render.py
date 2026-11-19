"""카테고리형 쇼츠 렌더러(배포본 scripts/render.py 이식, 출처 licenses/THIRD_PARTY.md).

변경점: 입력·출력은 작업 폴더 고정 이름, ffmpeg 입력 보안(F3), 문구 폭 초과 → TextTooLong,
훅 길이 초과 → HookTooLong, 중단(F2) 시 ffmpeg kill, 진행 콜백.
P0는 ko만(일본어 폰트 없음, task-050).
"""

import math
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from production.errors import HookTooLong, RenderFailed, TextTooLong
from production.media import Cancel, Media, MediaError, file_input

W, H, FPS = 608, 1080, 30
FONTS = Path(__file__).resolve().parent.parent / "fonts"
TITLE_FONT = FONTS / "Pretendard-Black.otf"
CAPTION_FONT = FONTS / "NotoSansCJKkr-Bold.otf"
Progress = Callable[[str, int], None]


def numeric(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise RenderFailed(label + " must be a finite number.")
    return float(value)


def validate(project: dict, source_meta: dict) -> float:
    """배포본 validate와 같은 규칙(실패는 RenderFailed). 반환: duration."""
    if project.get("lang") != "ko":
        raise RenderFailed("lang must be ko (P0).")
    header = project.get("header")
    if (
        not isinstance(header, list)
        or len(header) != 2
        or not all(isinstance(x, str) and x.strip() for x in header)
    ):
        raise RenderFailed("header must contain two nonempty strings.")
    if source_meta.get("width") is None:
        raise RenderFailed("Source must contain video.")
    duration = numeric(project.get("duration", source_meta["duration"]), "duration")
    if not 0.1 <= duration <= min(180, source_meta["duration"] + 0.05):
        raise RenderFailed("duration is outside source bounds (maximum 180s).")
    shots = project.get("shots", [])
    if not shots:
        raise RenderFailed("shots must cover the full timeline.")
    previous = 0.0
    for shot in shots:
        if not isinstance(shot, list) or len(shot) != 4:
            raise RenderFailed("shot format: [start, end, zoom, y]")
        start, end, zoom, y = [numeric(v, "shot value") for v in shot]
        if abs(start - previous) > 0.001 or end <= start or end > duration + 0.001:
            raise RenderFailed("Shots must be continuous, ordered and within duration.")
        if not 1 <= zoom <= 3 or y > 280 or y + H * zoom < H - 0.01:
            raise RenderFailed("Shot transform leaves a blank area or uses zoom outside 1..3.")
        previous = end
    if abs(previous - duration) > 0.001:
        raise RenderFailed("Shots must end at duration.")
    items = project.get("items", [])
    if not items:
        raise RenderFailed("At least one caption is required.")
    previous = 0.0
    for item in items:
        if not isinstance(item, list) or len(item) not in (4, 5):
            raise RenderFailed("caption format: [start, end, white|paren|emph, text, optional_y]")
        start, end = numeric(item[0], "caption start"), numeric(item[1], "caption end")
        if start < previous - 0.001 or end <= start or end > duration + 0.001:
            raise RenderFailed("Captions must be ordered, nonoverlapping and within duration.")
        if item[2] not in ("white", "paren", "emph") or not isinstance(item[3], str):
            raise RenderFailed("Invalid caption kind/text.")
        if not item[3].strip():
            raise RenderFailed("Invalid caption kind/text.")
        if len(item) == 5 and not 310 <= numeric(item[4], "caption y") <= 1030:
            raise RenderFailed("caption y must be between 310 and 1030.")
        previous = end
    if abs(items[0][0]) > 0.001:
        raise RenderFailed("First hook caption must start at zero.")
    if not str(project.get("hook", "")).strip():
        raise RenderFailed("hook text is required.")
    if any("\n" in text for text in [*header, *(i[3] for i in items)]):
        raise RenderFailed("Each header/caption is one line; remove embedded newlines.")
    return duration


def text_center(draw, text, font_path, size, width, cy, fill, stroke=0, box=False) -> None:
    for current in range(size, 11, -1):
        font = ImageFont.truetype(str(font_path), current)
        bounds = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
        if bounds[2] - bounds[0] <= width:
            break
    else:
        raise TextTooLong("자동 축소 후에도 폭 초과")
    tw, th = bounds[2] - bounds[0], bounds[3] - bounds[1]
    x, y = (W - tw) / 2 - bounds[0], cy - th / 2 - bounds[1]
    if box:
        draw.rounded_rectangle(
            ((W - tw) / 2 - 16, cy - th / 2 - 10, (W + tw) / 2 + 16, cy + th / 2 + 10),
            radius=12,
            fill=(0, 0, 0, 235),
        )
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke, stroke_fill="black")


def overlays(project: dict) -> tuple[Image.Image, list[Image.Image]]:
    title = Image.new("RGBA", (W, H))
    draw = ImageDraw.Draw(title)
    draw.rectangle((0, 0, W, 279), fill="black")
    for index, text in enumerate(project["header"]):
        text_center(
            draw, text, TITLE_FONT, 66, 570, [155, 228][index], "#FFDC00" if index else "white"
        )
    layers = []
    sizes = {"white": 28, "paren": 34, "emph": 36}
    colors = {"white": "white", "paren": "#FCCC2C", "emph": "#04FC04"}
    strokes = {"white": 2, "paren": 4, "emph": 0}
    for item in project["items"]:
        layer = Image.new("RGBA", (W, H))
        draw = ImageDraw.Draw(layer)
        kind, text = item[2:4]
        cy = item[4] if len(item) == 5 else (390 if kind == "emph" else 700)
        text_center(
            draw,
            text,
            CAPTION_FONT,
            sizes[kind],
            520 if kind == "emph" else 560,
            cy,
            colors[kind],
            strokes[kind],
            kind == "emph",
        )
        layers.append(layer)
    return title, layers


def check_hook(hook_duration: float, duration: float, first_caption_end: float) -> float:
    """04_API.md W-09 정본: 훅 길이+0.08 > min(duration, 첫 자막 종료)+0.02 → hook_too_long."""
    hook_end = hook_duration + 0.08
    if hook_end > min(duration, first_caption_end) + 0.02:
        raise HookTooLong(f"훅 {hook_end:.2f}s > 첫 자막 {first_caption_end:.2f}s")
    return hook_end


def read_exact(stream, size: int) -> bytes:
    chunks, remaining = [], size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def render(
    project: dict,
    source: Path,
    source_meta: dict,
    hook: Path,
    hook_duration: float,
    output: Path,
    media: Media,
    cancel: Cancel,
    on_progress: Progress,
) -> dict:
    """source(작업 폴더의 source.mp4)와 정리된 hook(WAV)로 output을 만들고 측정 결과를 돌려준다."""
    duration = validate(project, source_meta)
    title, captions = overlays(project)
    hook_end = check_hook(hook_duration, duration, float(project["items"][0][1]))
    frames = math.ceil(duration * FPS - 1e-6)
    encoded_duration = frames / FPS
    decoder_args = media.ffmpeg_cmd(
        "-loglevel",
        "error",
        *file_input(source, source_meta["demuxer"]),
        "-an",
        "-vf",
        "fps=30,scale=608:1080:force_original_aspect_ratio=increase,"
        "crop=608:1080,setsar=1,eq=saturation=1.15:contrast=1.08,"
        "tpad=stop_mode=clone:stop_duration=0.1",
        "-frames:v",
        str(frames),
        "-pix_fmt",
        "rgb24",
        "-f",
        "rawvideo",
        "pipe:1",
    )
    encoder_args = media.ffmpeg_cmd(
        "-loglevel",
        "error",
        "-y",
        "-protocol_whitelist",
        "pipe",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{W}x{H}",
        "-r",
        str(FPS),
        "-i",
        "pipe:0",
    )
    if source_meta["has_audio"]:
        encoder_args += file_input(source, source_meta["demuxer"])
    else:
        encoder_args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    encoder_args += [
        *file_input(hook, "wav"),
        "-filter_complex",
        f"[1:a]asetpts=PTS-STARTPTS,volume='if(lt(t,{hook_end}),0.2,1)':eval=frame[bg];"
        "[2:a]asetpts=PTS-STARTPTS[voice];"
        "[bg][voice]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
        f"loudnorm=I=-14:TP=-1:LRA=11,apad,atrim=duration={encoded_duration}[audio]",
        "-map",
        "0:v:0",
        "-map",
        "[audio]",
        "-t",
        str(encoded_duration),
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(FPS),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        "file:" + str(output),
    ]
    on_progress("compose", 0)
    decoder = encoder = None
    shots = project["shots"]
    try:
        decoder = subprocess.Popen(
            [str(x) for x in decoder_args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        cancel.register(decoder)
        encoder = subprocess.Popen(
            [str(x) for x in encoder_args],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cancel.register(encoder)
        shot_index = 0
        for n in range(frames):
            cancel.check()
            raw = read_exact(decoder.stdout, W * H * 3)
            if len(raw) != W * H * 3:
                cancel.check()
                raise RenderFailed(f"decoder stopped at frame {n}/{frames}")
            t = n / FPS
            while shot_index + 1 < len(shots) and t >= shots[shot_index][1] - 1e-6:
                shot_index += 1
            _, _, zoom, y = shots[shot_index]
            frame = Image.frombytes("RGB", (W, H), raw)
            frame = frame.resize((round(W * zoom), round(H * zoom)), Image.Resampling.LANCZOS)
            frame = frame.filter(ImageFilter.UnsharpMask(radius=2, percent=100, threshold=3))
            canvas = Image.new("RGB", (W, H), "black")
            canvas.paste(frame, ((W - frame.width) // 2, round(y)))
            canvas.paste(title, (0, 0), title)
            for index, item in enumerate(project["items"]):
                if item[0] <= t < item[1]:
                    canvas.paste(captions[index], (0, 0), captions[index])
                    break
            encoder.stdin.write(canvas.tobytes())
            if n % FPS == 0:
                on_progress("compose", n * 100 // frames)
        encoder.stdin.close()
        decoder.stdout.close()
        on_progress("encode", 100)
        if decoder.wait(timeout=60) != 0 or encoder.wait(timeout=600) != 0:
            cancel.check()
            raise RenderFailed("ffmpeg 종료 코드 오류")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        cancel.check()
        raise RenderFailed(type(exc).__name__) from None
    finally:
        for proc in (decoder, encoder):
            if proc is not None:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                cancel.unregister(proc)
    cancel.check()
    try:
        result = media.probe(output, cancel)
    except MediaError:
        raise RenderFailed("출력 확인 실패") from None
    if (result["width"], result["height"]) != (W, H) or not result["has_audio"]:
        raise RenderFailed("Output validation failed.")
    if abs(result["duration"] - encoded_duration) > 0.15:
        raise RenderFailed("Output duration does not match project.")
    return {
        "duration": result["duration"],
        "width": W,
        "height": H,
        "fps": FPS,
        "has_audio": True,
        "hook_duration": hook_duration,
        "hook_end": hook_end,
    }
