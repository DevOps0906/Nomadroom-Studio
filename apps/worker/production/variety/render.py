"""예능형 렌더러(task-036). 근거: docs/research/variety-shorts-zip-analysis.md#2~#4,
docs/05_DATA_MODEL.md#예능형-spec-필드.

흐름: 컷별 decoder(-ss·-frames:v, 띠에 보이는 원본 영역만 crop→1080×816) → PIL로 흰 캔버스·
제목·대사 자막·반응 자막 합성 → rawvideo pipe → libx264(W5). 소리는 원본을 48k PCM으로 한 번
풀어 컷마다 같은 프레임 경계(1프레임=1600샘플)로 잘라 이어 붙이고 loudnorm(W2).
drawtext·concat demuxer·-safe 0을 쓰지 않고, 모든 파일 입력은 file_input()(F3).
lang=ja(task-051)는 대사 자막 TTS 더빙 믹스(variety/dub.py)를 쓰고 믹스 뒤에는 리미터만 건다.
"""

import math
import subprocess
import threading
import time
import wave
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from production.adapter_variety import BAND_BOTTOM, BAND_CX, BAND_CY, BAND_TOP, CANVAS_W, FPS
from production.config import TtsSettings
from production.errors import RenderFailed
from production.media import DEFAULT_TIMEOUT, Cancel, Media, MediaError, file_input
from production.render import read_exact
from production.variety.dub import LIMITER, build_dub
from production.variety.text import H, W, reaction_layer, subtitle_layer, title_layer

BAND_H = BAND_BOTTOM - BAND_TOP
RATE = 48000
SPF = RATE // FPS  # 프레임당 샘플 1600
FRAME_BYTES = W * BAND_H * 3
Progress = Callable[[str, int], None]
DEADLINE_SEC = DEFAULT_TIMEOUT  # 리뷰 반영: 렌더 전체 상한(시작+600초, media.run과 같은 기준)
MAX_ACTIVE_PIXELS = W * H * 2  # 리뷰 반영: 동시에 표시되는 자막·반응 레이어 면적 상한


def crop_filter(cut: dict, src_w: int, src_h: int) -> str:
    """띠(0~1080×560~1376)에 보이는 원본 영역만 잘라 1080×816으로(W4). 정수 상자는 바깥으로
    넓히고(floor·ceil) 확대 후 정확한 위치를 다시 자른다. 원본 밖으로는 넘지 않는다."""
    k = CANVAS_W * cut["scale"] / src_w  # 원본 1px당 화면 px
    left = BAND_CX + cut["x"] - src_w * k / 2
    top = BAND_CY + cut["y"] - src_h * k / 2
    sx, sy = -left / k, (BAND_TOP - top) / k
    x0, y0 = max(math.floor(sx), 0), max(math.floor(sy), 0)
    x1 = min(math.ceil(sx + CANVAS_W / k), src_w)
    y1 = min(math.ceil(sy + BAND_H / k), src_h)
    sw = max(math.ceil((x1 - x0) * k), CANVAS_W)
    sh = max(math.ceil((y1 - y0) * k), BAND_H)
    ox = min(max(round((sx - x0) * k), 0), sw - CANVAS_W)
    oy = min(max(round((sy - y0) * k), 0), sh - BAND_H)
    return (
        f"fps={FPS},crop={x1 - x0}:{y1 - y0}:{x0}:{y0}:exact=1,"
        f"scale={sw}:{sh}:flags=lanczos,crop={CANVAS_W}:{BAND_H}:{ox}:{oy},setsar=1,"
        "tpad=stop_mode=clone:stop_duration=1"
    )


def _cut_audio(media: Media, project: dict, source: Path, meta: dict, work_dir: Path, cancel):
    """원본 소리를 컷 경계대로 이어 붙인 48k 스테레오 WAV. 원본에 소리가 없으면 None."""
    if not meta["has_audio"]:
        return None
    full = work_dir / "audio_src.wav"
    try:
        media.run(
            media.ffmpeg_cmd(
                "-loglevel",
                "error",
                "-y",
                *file_input(source, meta["demuxer"]),
                "-vn",
                "-map",
                "0:a:0",
                "-af",
                f"aresample={RATE}:async=1:first_pts=0",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                "file:" + str(full),
            ),
            cancel,
        )
        with wave.open(str(full), "rb") as f:
            if f.getframerate() != RATE or f.getnchannels() != 2 or f.getsampwidth() != 2:
                raise RenderFailed("원본 소리 형식 오류")
            pcm = f.readframes(f.getnframes())
    except MediaError, wave.Error, EOFError:
        raise RenderFailed("원본 소리를 읽을 수 없음") from None
    out = work_dir / "audio_cut.wav"
    with wave.open(str(out), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(RATE)
        for cut in project["cuts"]:
            start = round(cut["src_start"] * RATE) * 4
            size = cut["frames"] * SPF * 4
            chunk = pcm[start : start + size]
            f.writeframes(chunk + bytes(size - len(chunk)))  # 원본 끝을 넘으면 무음
    full.unlink()
    return out


def _layers(project: dict) -> tuple[Image.Image, list, list[str]]:
    fonts: list[str] = []
    lang = project["lang"]
    title = title_layer(project["header"], fonts, lang)
    base = Image.new("RGB", (W, H), "white")
    base.paste(title, (0, 0), title)
    layers = [subtitle_layer(s, fonts, lang) for s in project["subtitles"]]
    layers += [reaction_layer(r, fonts, lang) for r in project["reactions"]]
    # 레이어 이미지는 표시될 때 그린다. 동시에 보이는 면적은 크기만으로 미리 막는다(끝 먼저)
    events = sorted([(x.fs, x.pixels) for x in layers] + [(x.fe, -x.pixels) for x in layers])
    active = 0
    for _, delta in events:
        active += delta
        if active > MAX_ACTIVE_PIXELS:
            raise RenderFailed("동시 표시 문구 면적 초과")
    return base, layers, fonts


def render_variety(
    project: dict,
    source: Path,
    meta: dict,
    output: Path,
    media: Media,
    cancel: Cancel,
    on_progress: Progress,
    tts_cfg: TtsSettings | None = None,
) -> dict:
    """project(adapter_variety)·source(작업 폴더 source.mp4) → output. 측정 결과를 돌려준다.
    ja는 더빙(TTS 포함 전체가 DEADLINE_SEC 안), 결과에 warnings·dub를 더한다."""
    began = time.monotonic()
    base, layers, fonts = _layers(project)
    frames = project["frames"]
    encoded = frames / FPS
    on_progress("audio", 0)
    audio = _cut_audio(media, project, source, meta, output.parent, cancel)
    extra: dict = {}
    dubbed = None
    if project["lang"] == "ja":
        dubbed, warnings, dub = build_dub(
            project,
            audio,
            output.parent,
            media,
            cancel,
            tts_cfg or TtsSettings(),
            began + DEADLINE_SEC,
        )
        extra = {"warnings": warnings, "dub": dub}
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
    if dubbed is not None:  # D5: 믹스 뒤 loudnorm 없이 리미터만
        encoder_args += file_input(dubbed, "wav")
        chain = f"{LIMITER},aresample={RATE},"
    elif audio is not None:
        encoder_args += file_input(audio, "wav")
        chain = f"loudnorm=I=-14:TP=-1:LRA=11,aresample={RATE},"
    else:  # W6: 소리 없는 원본도 AAC 트랙(무음)
        encoder_args += ["-f", "lavfi", "-i", f"anullsrc=r={RATE}:cl=stereo"]
        chain = ""
    encoder_args += [
        "-filter_complex",
        f"[1:a]{chain}apad,atrim=end_sample={frames * SPF}[audio]",
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
    encoder = decoder = None
    n = 0
    expired = threading.Event()
    procs: list[subprocess.Popen] = []

    def expire() -> None:  # 멈춘 decoder·encoder도 풀리도록 kill(읽기가 EOF로 끝난다)
        expired.set()
        for proc in procs:
            if proc.poll() is None:
                proc.kill()

    def check() -> None:
        cancel.check()
        if expired.is_set():
            raise RenderFailed("렌더 시간 초과")

    watchdog = threading.Timer(max(began + DEADLINE_SEC - time.monotonic(), 0), expire)
    watchdog.daemon = True
    watchdog.start()
    try:
        encoder = subprocess.Popen(  # noqa: S603 (고정 인자, 사용자 문자열 없음)
            [str(x) for x in encoder_args],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cancel.register(encoder)
        procs.append(encoder)
        for cut in project["cuts"]:
            decoder = subprocess.Popen(  # noqa: S603
                [
                    str(x)
                    for x in media.ffmpeg_cmd(
                        "-loglevel",
                        "error",
                        "-ss",
                        f"{cut['src_start']:.6f}",
                        *file_input(source, meta["demuxer"]),
                        "-an",
                        "-sn",
                        "-dn",
                        "-vf",
                        crop_filter(cut, meta["width"], meta["height"]),
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
                    raise RenderFailed(f"decoder stopped at frame {n}/{frames}")
                canvas = base.copy()
                canvas.paste(Image.frombytes("RGB", (W, BAND_H), raw), (0, BAND_TOP))
                for layer in layers:  # 표시 구간 [fs, fe)는 컷 격자와 같은 frame_of 기준
                    if layer.fs <= n < layer.fe:
                        img = layer.image
                        canvas.paste(img, (layer.x, layer.y), img)
                    elif n >= layer.fe:
                        layer.release()
                encoder.stdin.write(canvas.tobytes())
                n += 1
                if n % FPS == 0:
                    on_progress("compose", n * 100 // frames)
            decoder.stdout.close()
            if decoder.wait(timeout=60) != 0:
                check()
                raise RenderFailed("decoder 종료 코드 오류")
            cancel.unregister(decoder)
            decoder = None
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
        "has_audio": True,
        "source_has_audio": bool(meta["has_audio"]),
        "frames": frames,
        "fonts": sorted(set(fonts)),
        "render_sec": round(time.monotonic() - began, 2),
        **extra,
    }
