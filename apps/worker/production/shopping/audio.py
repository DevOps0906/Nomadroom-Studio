"""쇼핑 소리: 문장별 음성(TTS 4회 또는 첨부 녹음 4개) 실측·이어 붙이기, 원본 소리 duck, BGM.

- 음성은 문장마다 48k 스테레오 WAV로 정리(hook_audio.make_hook: 앞뒤 무음 정리)하고 길이를 잰다.
  TTS는 4회 합계 deadline 안에서 만든다. 하나라도 실패하면 tts_failed(대체·무음 금지).
- 이어 붙인 음성 PCM은 출력 프레임 수 × 1600샘플에 맞춰 끝만 자르거나 무음으로 채운다
  (문장 경계는 누적 시각 반올림이라 오차는 반 프레임 이내).
- 모든 파일 입력은 file_input()(F3). 경로·문구·voice는 로그에 쓰지 않는다.
"""

import time
import wave
from pathlib import Path

from production.config import TtsSettings
from production.errors import AudioMissing, RenderFailed
from production.hook_audio import AUDIO_DEMUXERS, make_hook
from production.media import Cancel, Media, MediaError, file_input
from production.tts import Synth, TtsFailed, synthesize

FPS = 30
RATE = 48000
SPF = RATE // FPS  # 프레임당 샘플 1600
BYTES_PER_SAMPLE = 4  # s16 스테레오
DUCK_GAIN = 0.15  # 원본 소리 duck 음량(가정, 예능형 ja duck 15%와 같음)
BGM_GAIN = 0.12  # BGM 음량(가정)
MAX_SENTENCE_SEC = 60.0  # 리뷰 반영 1: 문장 음성(녹음·TTS) 1개 길이 상한


def _pcm(path: Path) -> bytes:
    try:
        with wave.open(str(path), "rb") as f:
            if f.getframerate() != RATE or f.getnchannels() != 2 or f.getsampwidth() != 2:
                raise RenderFailed("음성 형식 오류")
            return f.readframes(f.getnframes())
    except wave.Error, EOFError:
        raise RenderFailed("음성을 읽을 수 없음") from None


def _write(path: Path, pcm: bytes) -> Path:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(pcm)
    return path


def _capped(duration: float) -> float:
    if duration > MAX_SENTENCE_SEC:
        raise RenderFailed("문장 음성 길이 상한 초과")
    return duration


def tts_sentences(
    texts: list[str],
    tts: dict,
    work_dir: Path,
    media: Media,
    cancel: Cancel,
    cfg: TtsSettings,
    synth: Synth | None = None,
) -> tuple[list[Path], list[float], str]:
    """문장마다 TTS 1회(4회). 합계 상한 cfg.timeout_sec. 반환 (wav 목록, 길이 목록, 경로 설명)."""
    deadline = time.monotonic() + cfg.timeout_sec
    wavs, durations, note = [], [], ""
    for i, text in enumerate(texts):
        left = deadline - time.monotonic()
        if left <= 0:
            raise TtsFailed("TimeoutError")
        raw = work_dir / f"tts_{i + 1}.mp3"
        note = synthesize(
            text, tts, raw, cancel, cfg.model_copy(update={"timeout_sec": left}), synth
        )
        wav = work_dir / f"voice_{i + 1}.wav"
        try:
            durations.append(_capped(make_hook(media, raw, wav, cancel)))
        except AudioMissing:
            raise TtsFailed("생성 음성을 읽을 수 없음") from None
        wavs.append(wav)
    return wavs, durations, note


def recorded_sentences(
    raws: list[Path], work_dir: Path, media: Media, cancel: Cancel
) -> tuple[list[Path], list[float]]:
    """첨부 녹음 4개(문장 순서) → wav·실측 길이. 읽을 수 없으면 audio_missing."""
    wavs, durations = [], []
    for i, raw in enumerate(raws):
        wav = work_dir / f"voice_{i + 1}.wav"
        durations.append(_capped(make_hook(media, raw, wav, cancel)))
        wavs.append(wav)
    return wavs, durations


def voice_track(wavs: list[Path], frames: int, out: Path) -> Path:
    """문장 음성을 이어 붙여 정확히 frames×1600샘플로."""
    pcm = b"".join(_pcm(w) for w in wavs)
    size = frames * SPF * BYTES_PER_SAMPLE
    return _write(out, pcm[:size] + bytes(max(size - len(pcm), 0)))


def duck_track(
    media: Media,
    timeline: list[dict],
    sources: dict[str, tuple[Path, dict]],
    frames: int,
    out: Path,
    cancel: Cancel,
) -> Path | None:
    """원본 소리(duck): 영상 컷마다 같은 구간의 소리를 출력 위치에 놓는다. 사진 컷·정지 프레임
    구간·소리 없는 원본은 무음. 쓸 소리가 하나도 없으면 None."""
    total = bytearray(frames * SPF * BYTES_PER_SAMPLE)
    used = False
    for n, cut in enumerate(timeline):
        src = sources.get(cut["input_id"])
        if cut["kind"] != "source" or src is None or not src[1]["has_audio"] or cut["frames"] <= 0:
            continue
        path, meta = src
        part = out.parent / f"duck_{n:03d}.wav"
        length = min(cut["frames"], cut["natural_frames"]) / FPS
        try:
            media.run(
                media.ffmpeg_cmd(
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    f"{cut['src_start']:.6f}",
                    *file_input(path, meta["demuxer"]),
                    "-t",
                    f"{length:.6f}",
                    "-vn",
                    "-map",
                    "0:a:0",
                    "-af",
                    f"aresample={RATE}:async=1:first_pts=0",
                    "-ac",
                    "2",
                    "-c:a",
                    "pcm_s16le",
                    "file:" + str(part),
                ),
                cancel,
            )
        except MediaError:
            raise RenderFailed("원본 소리를 읽을 수 없음") from None
        pcm = _pcm(part)[: round(length * RATE) * BYTES_PER_SAMPLE]
        start = cut["frame_start"] * SPF * BYTES_PER_SAMPLE
        total[start : start + len(pcm)] = pcm
        part.unlink()
        used = True
    return _write(out, bytes(total)) if used else None


def bgm_track(media: Media, raw: Path, frames: int, out: Path, cancel: Cancel) -> Path:
    """BGM을 출력 길이만큼 반복·자르기(-stream_loop). 음성 형식이 아니면 render_failed."""
    try:
        meta = media.probe(raw, cancel)
        if meta["demuxer"] not in AUDIO_DEMUXERS or not meta["has_audio"]:
            raise RenderFailed("BGM 형식이 아님")
        media.run(
            media.ffmpeg_cmd(
                "-loglevel",
                "error",
                "-y",
                "-stream_loop",
                "-1",
                *file_input(raw, meta["demuxer"]),
                "-t",
                f"{frames / FPS:.6f}",
                "-vn",
                "-map",
                "0:a:0",
                "-ar",
                str(RATE),
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                "file:" + str(out),
            ),
            cancel,
        )
    except MediaError:
        raise RenderFailed("BGM을 읽을 수 없음") from None
    size = frames * SPF * BYTES_PER_SAMPLE
    pcm = _pcm(out)
    return _write(out, pcm[:size] + bytes(max(size - len(pcm), 0)))


def mix_filter(has_duck: bool, has_bgm: bool, frames: int) -> str:
    """encoder filter_complex. 입력 1=음성, 그다음 duck·BGM(있는 것만) → [audio](정확히 frames)."""
    chains, labels, idx = [], ["[1:a]"], 2
    if has_duck:
        chains.append(f"[{idx}:a]volume={DUCK_GAIN}[d]")
        labels.append("[d]")
        idx += 1
    if has_bgm:
        chains.append(f"[{idx}:a]volume={BGM_GAIN}[b]")
        labels.append("[b]")
    head = "".join(labels)
    if len(labels) > 1:
        head += f"amix=inputs={len(labels)}:normalize=0:duration=first,"
    tail = f"loudnorm=I=-14:TP=-1:LRA=11,aresample={RATE},apad,atrim=end_sample={frames * SPF}"
    return ";".join([*chains, f"{head}{tail}[audio]"])
