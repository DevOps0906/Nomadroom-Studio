"""예능형 일본어 더빙(task-051 D2~D6). 대사 자막마다 ja TTS 1회 → 자막 구간에 배치.

- 대상(D3): `subtitles[]` 중 style=`line`만(punch·반응 자막은 더빙 안 함). 상한 60개(넘으면
  render_failed). 0개면 원본 그대로 + warning `dub_none`.
- 배치(D4): 시작 샘플 = frame_of(start)×1600(화면 자막 격자와 같음). 허용 창 = 다음 대사 시작
  (마지막은 영상 끝)까지. 실측 길이가 창보다 길면 로컬 atempo로 최대 1.3배, 그래도 길면 창 끝에서
  30ms 페이드아웃으로 자르고 warning `dub_overflow`(line=대사 순번 1부터, overflow_sec).
- 소리(D5): 원본은 loudnorm 후 더빙 실제 구간(±50ms 페이드)만 이득 0.15로 duck, 그 위에 TTS를
  더한다(포화 덧셈). 믹스 뒤 loudnorm 없음 — 렌더러가 리미터만 건다. 원본 소리 없으면 TTS만.
- 실패(D6): TTS 하나라도 실패하거나 TTS 꺼짐 + 대사 ≥1이면 tts_failed(대체·무음 금지).
  TTS 시간은 렌더 전체 DEADLINE 안(deadline 인자).
- 목소리(D2): 워커 상수(spec 변경 없음). 녹음 대체 경로 없음.
- 리뷰 반영: 허용 창 0샘플(시작 프레임이 같은 대사·영상 끝 시작)은 render_failed. ffmpeg 단계마다
  렌더 남은 시간으로 timeout, PCM 루프는 1초 분량마다 중단·시간 초과를 확인한다.
문구·voice는 로그에 쓰지 않는다. 모든 파일 입력은 file_input()(F3).
"""

import math
import time
from array import array
from collections.abc import Callable
from pathlib import Path

from production.adapter_variety import FPS, frame_of
from production.config import TtsSettings
from production.errors import RenderFailed
from production.hook_audio import AUDIO_DEMUXERS, TRIM
from production.media import DEFAULT_TIMEOUT, Cancel, Media, MediaError, file_input
from production.shopping.audio import _pcm as read_pcm
from production.shopping.audio import _write as write_wav
from production.tts import TtsFailed, synthesize

VOICE = "ja-JP-NanamiNeural"
BASE_RATE = "+0%"
MAX_LINES = 60  # 가정
MAX_TEMPO = 1.3  # rate 상한 +30%(가정)
DUCK_GAIN = 0.15  # 가정
RATE = 48000
SPF = RATE // FPS  # 1600
DUCK_FADE = RATE * 50 // 1000  # ±50ms
CUT_FADE = RATE * 30 // 1000  # 30ms
LOUDNORM = "loudnorm=I=-14:TP=-1:LRA=11"  # 기존 예능형 음량과 같은 값
LIMITER = "alimiter=limit=0.95:level=0"  # 믹스 뒤 클리핑 방지만(자동 음량 끔)
CHUNK = RATE  # PCM 루프 확인 간격(샘플)


def _left(deadline: float) -> float:
    """렌더 남은 시간(초, ffmpeg timeout). 다 썼으면 render_failed."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise RenderFailed("렌더 시간 초과")
    return min(left, DEFAULT_TIMEOUT)


def _checker(cancel: Cancel, deadline: float) -> Callable[[], None]:
    def check() -> None:
        cancel.check()
        _left(deadline)

    return check


def dub_lines(project: dict) -> list[dict]:
    """대사 자막 → [{line, text, start, end}] (start·end는 48k 샘플, end = 허용 창 끝)."""
    total = project["frames"] * SPF
    subs = sorted(
        (s for s in project["subtitles"] if s["style"] == "line"), key=lambda s: s["start"]
    )
    starts = [min(frame_of(s["start"]) * SPF, total) for s in subs]
    return [
        {
            "line": i + 1,
            "text": s["text"].replace("\n", ""),
            "start": starts[i],
            "end": starts[i + 1] if i + 1 < len(subs) else total,
        }
        for i, s in enumerate(subs)
    ]


def _atempo(media: Media, wav: Path, tempo: float, cancel: Cancel, deadline: float) -> bytes:
    out = wav.with_name(wav.stem + "_fast.wav")
    try:
        media.run(
            media.ffmpeg_cmd(
                "-loglevel",
                "error",
                "-y",
                *file_input(wav, "wav"),
                "-af",
                f"atempo={tempo:.6f}",
                "-ar",
                str(RATE),
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                "file:" + str(out),
            ),
            cancel,
            timeout=_left(deadline),
        )
    except MediaError:
        raise RenderFailed("더빙 속도 조절 실패") from None
    return read_pcm(out)


def _fade_out(pcm: bytes) -> bytes:
    s = array("h", pcm)
    n = len(s) // 2
    k = min(CUT_FADE, n)
    for i in range(k):
        g = (k - i) / (k + 1)
        j = 2 * (n - k + i)
        s[j], s[j + 1] = int(s[j] * g), int(s[j + 1] * g)
    return s.tobytes()


def fit_clip(
    pcm: bytes, window: int, wav: Path, media: Media, cancel: Cancel, deadline: float = math.inf
) -> tuple[bytes, float, float]:
    """창(샘플)에 맞춘 PCM, 적용 배속, 1.3배 후에도 넘친 초(0이면 경고 없음)."""
    n = len(pcm) // 4
    if n <= window:
        return pcm, 1.0, 0.0
    tempo = min(n / window, MAX_TEMPO) if window > 0 else MAX_TEMPO
    fast = _atempo(media, wav, tempo, cancel, deadline)
    over = len(fast) // 4 - window
    if over <= 0:
        return fast, tempo, 0.0
    # 1.3배 미만으로 맞춘 경우의 몇 샘플 차이는 반올림 오차라 경고하지 않는다
    over_sec = round(over / RATE, 3) if tempo >= MAX_TEMPO else 0.0
    return _fade_out(fast[: window * 4]), tempo, over_sec


def _regions(clips: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """더빙 실제 구간(샘플). 페이드가 겹치는(간격 100ms 미만) 구간은 하나로 합친다."""
    out: list[list[int]] = []
    for a, b in sorted(clips):
        if b <= a:
            continue
        if out and a - DUCK_FADE <= out[-1][1] + DUCK_FADE:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def mix(
    orig: bytes | None,
    clips: list[tuple[int, bytes]],
    total: int,
    check: Callable[[], None] = lambda: None,
) -> bytes:
    """orig(48k 스테레오 s16, 없으면 무음)를 더빙 구간만 duck하고 clips(시작 샘플, PCM)를 더한다.
    결과는 정확히 total 샘플. check는 1초 분량마다 부른다(중단·시간 초과)."""
    size = total * 4
    base = array("h", (orig or b"")[:size] + bytes(max(size - len(orig or b""), 0)))
    if orig is not None:
        for a, b in _regions([(s, s + len(p) // 4) for s, p in clips]):
            for i in range(max(a - DUCK_FADE, 0), a):  # 1 → 0.15
                g = 1 - (1 - DUCK_GAIN) * (i - (a - DUCK_FADE) + 1) / (DUCK_FADE + 1)
                base[2 * i], base[2 * i + 1] = int(base[2 * i] * g), int(base[2 * i + 1] * g)
            for c in range(a, min(b, total), CHUNK):
                check()
                hi = min(c + CHUNK, b, total)
                base[2 * c : 2 * hi] = array(
                    "h", [int(v * DUCK_GAIN) for v in base[2 * c : 2 * hi]]
                )
            for i in range(b, min(b + DUCK_FADE, total)):  # 0.15 → 1
                g = DUCK_GAIN + (1 - DUCK_GAIN) * (i - b + 1) / (DUCK_FADE + 1)
                base[2 * i], base[2 * i + 1] = int(base[2 * i] * g), int(base[2 * i + 1] * g)
    for start, pcm in clips:
        voice = array("h", pcm)
        end = min(start * 2 + len(voice), total * 2)
        for c in range(start * 2, end, 2 * CHUNK):
            check()
            hi = min(c + 2 * CHUNK, end)
            part = voice[c - start * 2 : hi - start * 2]
            base[c:hi] = array(
                "h", [max(-32768, min(32767, x + y)) for x, y in zip(base[c:hi], part, strict=True)]
            )
    return base.tobytes()


def _loudnorm(media: Media, audio: Path, total: int, cancel: Cancel, deadline: float) -> bytes:
    out = audio.with_name("audio_norm.wav")
    try:
        media.run(
            media.ffmpeg_cmd(
                "-loglevel",
                "error",
                "-y",
                *file_input(audio, "wav"),
                "-af",
                f"{LOUDNORM},aresample={RATE}",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                "file:" + str(out),
            ),
            cancel,
            timeout=_left(deadline),
        )
    except MediaError:
        raise RenderFailed("원본 소리 음량 정리 실패") from None
    pcm = read_pcm(out)[: total * 4]
    out.unlink()
    return pcm


def _clean(media: Media, raw: Path, wav: Path, cancel: Cancel, deadline: float) -> bytes:
    """TTS 음성 → 48k 스테레오 PCM(앞뒤 무음 정리, hook_audio.make_hook과 같은 필터)에
    렌더 남은 시간 timeout. 읽을 수 없거나 0.1초 미만이면 tts_failed."""
    timeout = _left(deadline)  # 시간 초과는 render_failed 그대로
    try:
        meta = media.probe(raw, cancel)
        if meta["demuxer"] not in AUDIO_DEMUXERS or not meta["has_audio"]:
            raise TtsFailed("생성 음성 형식 오류")
        media.run(
            media.ffmpeg_cmd(
                "-loglevel",
                "error",
                "-y",
                *file_input(raw, meta["demuxer"]),
                "-vn",
                "-af",
                TRIM,
                "-ar",
                str(RATE),
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                "file:" + str(wav),
            ),
            cancel,
            timeout=timeout,
        )
        pcm = read_pcm(wav)
    except MediaError, RenderFailed:  # read_pcm 형식 오류도 생성 음성 문제
        raise TtsFailed("생성 음성을 읽을 수 없음") from None
    if len(pcm) // 4 < RATE // 10:
        raise TtsFailed("생성 음성이 비었거나 무음")
    return pcm


def build_dub(
    project: dict,
    audio: Path | None,
    work_dir: Path,
    media: Media,
    cancel: Cancel,
    cfg: TtsSettings,
    deadline: float,
) -> tuple[Path | None, list[dict], dict]:
    """반환 (믹스 WAV 또는 None(dub_none → 원본 그대로), report warnings, report dub 요약)."""
    lines = dub_lines(project)
    if not lines:
        return None, [{"code": "dub_none"}], {"lines": []}
    if len(lines) > MAX_LINES:
        raise RenderFailed("대사 수 상한 초과")
    if any(x["end"] <= x["start"] for x in lines):  # 리뷰 반영: 시작 프레임이 같거나 영상 끝
        raise RenderFailed("대사 배치 구간 없음")
    if not cfg.enabled:
        raise TtsFailed("TTS 비활성(WORKER_TTS_ENABLED)")
    total = project["frames"] * SPF
    check = _checker(cancel, deadline)
    clips, warnings, placed, note = [], [], [], ""
    for line in lines:
        left = min(deadline - time.monotonic(), cfg.timeout_sec)
        if left <= 0:
            raise TtsFailed("TimeoutError")
        raw = work_dir / f"dub_{line['line']:02d}.mp3"
        wav = work_dir / f"dub_{line['line']:02d}.wav"
        tts = {"voice": VOICE, "rate": BASE_RATE}
        note = synthesize(
            line["text"], tts, raw, cancel, cfg.model_copy(update={"timeout_sec": left})
        )
        pcm = _clean(media, raw, wav, cancel, deadline)
        window = line["end"] - line["start"]
        pcm, tempo, over = fit_clip(pcm, window, wav, media, cancel, deadline)
        if over > 0:
            warnings.append({"code": "dub_overflow", "line": line["line"], "overflow_sec": over})
        clips.append((line["start"], pcm))
        placed.append(
            {
                "line": line["line"],
                "start": round(line["start"] / RATE, 3),
                "length": round(len(pcm) / 4 / RATE, 3),
                "window": round(window / RATE, 3),
                "tempo": round(tempo, 3),
            }
        )
    if len(placed) != len(lines):  # 리뷰 반영: 대사마다 정확히 1개 배치
        raise RenderFailed("더빙 배치 수 불일치")
    orig = _loudnorm(media, audio, total, cancel, deadline) if audio is not None else None
    out = write_wav(work_dir / "audio_dub.wav", mix(orig, clips, total, check))
    return out, warnings, {"tts": note, "duck_gain": DUCK_GAIN, "lines": placed}
