"""첨부 훅 음성의 앞뒤 무음 정리(배포본 tts.py의 make_hook 중 첨부 경로만, F7).

TTS는 task-030 몫이라 여기 없다. 음성이 없거나 비어 있으면 AudioMissing
— 무음·가짜 음성으로 대체하지 않는다.
"""

from pathlib import Path

from production.errors import AudioMissing
from production.media import Cancel, Media, MediaError, file_input

TRIM = (
    "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,"
    "areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,areverse"
)
AUDIO_DEMUXERS = {"wav", "mp3", "mov"}  # 04_API.md A-10 hook_audio: wav·mp3·m4a


def make_hook(media: Media, raw: Path, output: Path, cancel: Cancel) -> float:
    """raw(받은 첨부)를 48kHz 스테레오 WAV로 정리해 output에 쓰고 길이(초)를 돌려준다."""
    try:
        meta = media.probe(raw, cancel)
        if meta["demuxer"] not in AUDIO_DEMUXERS or not meta["has_audio"]:
            raise AudioMissing("훅 음성 형식이 아님")
        media.run(
            media.ffmpeg_cmd(
                "-y",
                *file_input(raw, meta["demuxer"]),
                "-vn",
                "-af",
                TRIM,
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                "file:" + str(output),
            ),
            cancel,
            timeout=300,
        )
        duration = media.probe(output, cancel)["duration"]
    except MediaError:
        raise AudioMissing("훅 음성을 읽을 수 없음") from None
    if duration < 0.1:
        raise AudioMissing("훅 음성이 비었거나 무음")
    return duration
