"""쇼핑 렌더러(task-045). 근거: docs/05_DATA_MODEL.md#쇼핑-spec-필드, tasks/task-045.md R5·R6·R8.

흐름: 컷별로 영상은 decoder(-ss·-frames:v, 캔버스에 보이는 원본 영역만 crop→1080×1920, 모자란
뒤쪽은 tpad 정지 프레임), 사진은 ffmpeg `-f *_pipe`로 한 번 디코드해 PIL로 pan·zoom → 마스크
블러 → 자막·CTA·표기 합성 → rawvideo pipe → libx264. 소리는 audio.py가 만든 WAV를 섞는다.
drawtext·concat demuxer·image2를 쓰지 않고 모든 파일 입력은 file_input()(F3).
"""

import math
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from PIL import Image, ImageFilter

from production.adapter_shopping import CANVAS_H, CANVAS_W, FPS
from production.errors import RenderFailed
from production.media import DEFAULT_TIMEOUT, Cancel, Media, MediaError, file_input
from production.render import read_exact
from production.shopping.audio import RATE, SPF, mix_filter
from production.shopping.text import cta_layer, disclosure_layer, subtitle_layer

W, H = CANVAS_W, CANVAS_H
FRAME_BYTES = W * H * 3
DEADLINE_SEC = DEFAULT_TIMEOUT  # 합성·인코딩 전체 상한(예능형과 같은 기준)
MAX_ACTIVE_PIXELS = W * H * 2  # 동시에 보이는 문구 레이어 면적 상한
MAX_WORK_PIXELS = 24_000_000  # 사진 작업 해상도 면적 상한(가정)
MOTION_ZOOM = 1.1  # zoom: 1.0→1.1, pan: 1.1 고정 후 좌→우(가정)
PAN_SHIFT = 0.05 * W  # pan 최대 이동 px(가정)
BLUR_RADIUS = 24  # 마스크 블러 반경(가정)
Progress = Callable[[str, int], None]


def crop_filter(cut: dict, src_w: int, src_h: int, frames: int) -> str:
    """캔버스(0~1080×0~1920)에 보이는 원본 영역만 잘라 1080×1920으로(예능형 W4와 같은 방식,
    띠 대신 전체 캔버스). 원본 끝이 모자라면 마지막 프레임 정지(tpad)."""
    k = W * cut["scale"] / src_w
    left = W / 2 + cut["x"] - src_w * k / 2
    top = H / 2 + cut["y"] - src_h * k / 2
    sx, sy = -left / k, -top / k
    x0, y0 = max(math.floor(sx), 0), max(math.floor(sy), 0)
    x1 = min(math.ceil(sx + W / k), src_w)
    y1 = min(math.ceil(sy + H / k), src_h)
    sw = max(math.ceil((x1 - x0) * k), W)
    sh = max(math.ceil((y1 - y0) * k), H)
    ox = min(max(round((sx - x0) * k), 0), sw - W)
    oy = min(max(round((sy - y0) * k), 0), sh - H)
    return (
        f"fps={FPS},crop={x1 - x0}:{y1 - y0}:{x0}:{y0}:exact=1,"
        f"scale={sw}:{sh}:flags=lanczos,crop={W}:{H}:{ox}:{oy},setsar=1,"
        f"tpad=stop_mode=clone:stop_duration={frames / FPS + 1:.3f}"
    )


def decode_image(media: Media, path: Path, meta: dict, cut: dict, out: Path, cancel) -> Image.Image:
    """사진을 최대 확대 배율의 표시 크기로 한 번 디코드(R6: -f *_pipe, protocol file)."""
    zmax = MOTION_ZOOM if cut["motion"] in ("pan", "zoom") else 1.0
    ww = math.ceil(W * cut["scale"] * zmax)
    wh = math.ceil(W * meta["height"] / meta["width"] * cut["scale"] * zmax)
    if ww * wh > MAX_WORK_PIXELS:
        raise RenderFailed("사진 작업 면적 상한 초과")
    try:
        media.run(
            media.ffmpeg_cmd(
                "-loglevel",
                "error",
                "-y",
                *file_input(path, meta["demuxer"]),
                "-frames:v",
                "1",
                "-vf",
                f"scale={ww}:{wh}:flags=lanczos",
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "file:" + str(out),
            ),
            cancel,
        )
        data = out.read_bytes()
    except MediaError:
        raise RenderFailed("사진을 읽을 수 없음") from None
    if len(data) != ww * wh * 3:
        raise RenderFailed("사진 디코드 크기 오류")
    out.unlink()
    return Image.frombytes("RGB", (ww, wh), data)


def image_frames(img: Image.Image, cut: dict, frames: int) -> Iterator[Image.Image]:
    """사진 컷 프레임. 기준 배치(폭 1080×scale, 중심 540+x·960+y)를 캔버스 중심 기준으로 z배
    확대(덮임 유지)하고 pan은 덮임이 깨지지 않는 범위에서만 가로 이동."""
    motion = cut["motion"] or "zoom"
    zmax = MOTION_ZOOM if motion in ("pan", "zoom") else 1.0
    bw = W * cut["scale"]  # 기준 표시 폭(z=1)
    bh = bw * img.height / img.width
    cx0, cy0 = W / 2 + cut["x"], H / 2 + cut["y"]
    for n in range(frames):
        t = n / max(frames - 1, 1)
        z = 1 + (zmax - 1) * t if motion == "zoom" else zmax
        dw, dh = bw * z, bh * z
        cx, cy = W / 2 + z * (cx0 - W / 2), H / 2 + z * (cy0 - H / 2)
        if motion == "pan":
            lo = max(W - (cx + dw / 2), -PAN_SHIFT)  # 오른쪽 끝이 캔버스 안으로 들어오지 않게
            hi = min(-(cx - dw / 2), PAN_SHIFT)
            cx += lo + (hi - lo) * t
        sx = img.width / dw
        left, top = (0 - (cx - dw / 2)) * sx, (0 - (cy - dh / 2)) * sx
        box = (left, top, left + W * sx, top + H * sx)
        yield img.resize((W, H), Image.Resampling.BILINEAR, box=box)


def blur_masks(canvas: Image.Image, masks: list[tuple]) -> None:
    """원본 외국어 자막 가림: 캔버스 좌표 영역을 가우시안 블러로 덮는다."""
    for x, y, w, h in masks:
        box = (
            max(math.floor(x), 0),
            max(math.floor(y), 0),
            min(math.ceil(x + w), W),
            min(math.ceil(y + h), H),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        canvas.paste(canvas.crop(box).filter(ImageFilter.GaussianBlur(BLUR_RADIUS)), box)


def build_layers(project: dict, bounds: list[int]) -> tuple[list, list[str]]:
    fonts: list[str] = []
    lang = project["lang"]  # task-050: ja는 JP 글꼴·글자 단위 줄바꿈
    layers = [
        subtitle_layer(text, bounds[i], bounds[i + 1], fonts, lang)
        for i, text in enumerate(project["script"])
    ]
    layers.append(cta_layer(project["cta"], bounds[3], bounds[4], fonts, lang))
    layers.append(disclosure_layer(project["disclosure"], bounds[4], fonts, lang))
    events = sorted([(x.fs, x.pixels) for x in layers] + [(x.fe, -x.pixels) for x in layers])
    active = 0
    for _, delta in events:
        active += delta
        if active > MAX_ACTIVE_PIXELS:
            raise RenderFailed("동시 표시 문구 면적 초과")
    return layers, sorted(set(fonts))


def render_shopping(
    project: dict,
    timeline: list[dict],
    bounds: list[int],
    media_inputs: dict[str, tuple[Path, dict]],
    voice_wav: Path,
    duck_wav: Path | None,
    bgm_wav: Path | None,
    output: Path,
    media: Media,
    cancel: Cancel,
    on_progress: Progress,
) -> dict:
    """timeline(layout + input_id·kind) → output.
    media_inputs: input_id → (작업 폴더 파일, meta)."""
    began = time.monotonic()
    frames = bounds[-1]
    encoded = frames / FPS
    layers, fonts = build_layers(project, bounds)
    args = media.ffmpeg_cmd(
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
        *file_input(voice_wav, "wav"),
    )
    if duck_wav is not None:
        args += file_input(duck_wav, "wav")
    if bgm_wav is not None:
        args += file_input(bgm_wav, "wav")
    args += [
        "-filter_complex",
        mix_filter(duck_wav is not None, bgm_wav is not None, frames),
        "-map",
        "0:v:0",
        "-map",
        "[audio]",
        "-t",
        str(encoded),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
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
        str(RATE),
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        "file:" + str(output),
    ]
    on_progress("compose", 0)
    expired = threading.Event()
    procs: list[subprocess.Popen] = []
    encoder = decoder = None
    n = 0

    def expire() -> None:
        expired.set()
        for proc in procs:
            if proc.poll() is None:
                proc.kill()

    def check() -> None:
        cancel.check()
        if expired.is_set():
            raise RenderFailed("렌더 시간 초과")

    def emit(canvas: Image.Image, masks: list[tuple]) -> None:
        nonlocal n
        check()
        blur_masks(canvas, masks)
        for layer in layers:  # 표시 구간 [fs, fe)는 문장 경계와 같은 프레임 격자
            if layer.fs <= n < layer.fe:
                canvas.paste(layer.image, (layer.x, layer.y), layer.image)
            elif n >= layer.fe:
                layer.release()
        encoder.stdin.write(canvas.tobytes())
        n += 1
        if n % FPS == 0:
            on_progress("compose", n * 100 // frames)

    watchdog = threading.Timer(max(began + DEADLINE_SEC - time.monotonic(), 0), expire)
    watchdog.daemon = True
    watchdog.start()
    try:
        encoder = subprocess.Popen(  # noqa: S603 (고정 인자, 사용자 문자열 없음)
            [str(x) for x in args],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cancel.register(encoder)
        procs.append(encoder)
        for i, cut in enumerate(timeline):
            if cut["frames"] <= 0:
                continue
            path, meta = media_inputs[cut["input_id"]]
            if cut["kind"] == "image":
                img = decode_image(media, path, meta, cut, output.parent / "image.rgb", cancel)
                for frame in image_frames(img, cut, cut["frames"]):
                    emit(frame, cut["masks"])
                del img
                continue
            decoder = subprocess.Popen(  # noqa: S603
                [
                    str(x)
                    for x in media.ffmpeg_cmd(
                        "-loglevel",
                        "error",
                        "-ss",
                        f"{cut['src_start']:.6f}",
                        *file_input(path, meta["demuxer"]),
                        "-an",
                        "-sn",
                        "-dn",
                        "-vf",
                        crop_filter(cut, meta["width"], meta["height"], cut["frames"]),
                        "-frames:v",
                        str(cut["frames"]),
                        "-pix_fmt",
                        "rgb24",
                        "-f",
                        "rawvideo",
                        "pipe:1",
                    )
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            cancel.register(decoder)
            procs.append(decoder)
            if expired.is_set():
                decoder.kill()
            for _ in range(cut["frames"]):
                check()
                raw = read_exact(decoder.stdout, FRAME_BYTES)
                if len(raw) != FRAME_BYTES:
                    check()
                    raise RenderFailed(f"decoder stopped at cut {i}")
                emit(Image.frombytes("RGB", (W, H), raw), cut["masks"])
            decoder.stdout.close()
            if decoder.wait(timeout=60) != 0:
                check()
                raise RenderFailed("decoder 종료 코드 오류")
            cancel.unregister(decoder)
            decoder = None
        if n != frames:
            raise RenderFailed("프레임 수 불일치")
        encoder.stdin.close()
        on_progress("encode", 100)
        if encoder.wait(timeout=max(began + DEADLINE_SEC - time.monotonic(), 1)) != 0:
            check()
            raise RenderFailed("ffmpeg 종료 코드 오류")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        check()
        raise RenderFailed(type(exc).__name__) from None
    finally:
        watchdog.cancel()
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
    if abs(result["duration"] - encoded) > 0.15:
        raise RenderFailed("Output duration does not match project.")
    return {
        "duration": result["duration"],
        "width": W,
        "height": H,
        "fps": FPS,
        "frames": frames,
        "audio_samples": frames * SPF,
        "fonts": fonts,
        "render_sec": round(time.monotonic() - began, 2),
    }
