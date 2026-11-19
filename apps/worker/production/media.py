"""ffmpeg·ffprobe 호출(F3·F11). 시스템 ffmpeg를 subprocess로만 부르고,
입력은 작업 폴더의 로컬 파일만.

모든 입력에 `-protocol_whitelist file`과 형식 고정(`-f <허용 demuxer>`)을 붙인다.
서명 URL은 넘기지 않는다.
중단(409) 시 등록된 ffmpeg 프로세스를 모두 kill 한다(F2).
"""

import json
import subprocess
import threading
from pathlib import Path

from production.errors import TaskCancelled

# F3 허용 형식(ffprobe format_name 토큰 → -f에 넘길 demuxer)
ALLOWED_DEMUXERS = {
    "mov": "mov",
    "mp4": "mov",
    "matroska": "matroska",
    "webm": "matroska",
    "wav": "wav",
    "mp3": "mp3",
}


# task-045 R6: 쇼핑 사진은 매직 바이트로 고른 단일 이미지 demuxer만(image2 패턴 확장 금지)
IMAGE_DEMUXERS = ("jpeg_pipe", "png_pipe", "webp_pipe")
MAX_IMAGE_PIXELS = 40_000_000  # 사진 면적 상한(가정, 디코드 메모리 방어)

MAX_DIMENSION = 8192  # 리뷰 반영 1: 이보다 큰 영상은 거부(메모리·처리 시간 방어)
DEFAULT_TIMEOUT = 600  # 리뷰 반영 2: ffmpeg 한 번 실행 상한(초)
PROBE_TIMEOUT = 120


class MediaError(ValueError):
    """입력 파일이 허용 형식이 아니거나 읽을 수 없음."""


class MediaTimeout(MediaError):
    """ffmpeg·ffprobe 실행 시간 초과."""


def sniff(path: Path) -> str | None:
    """매직 바이트로 허용 형식의 demuxer를 고른다(리뷰 반영 4, ffprobe 전에 거른다)."""
    with Path(path).open("rb") as f:
        head = f.read(16)
    if len(head) >= 12 and head[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip"):
        return "mov"  # mp4·mov·m4a
    if head.startswith(bytes.fromhex("1a45dfa3")):
        return "matroska"  # mkv·webm(EBML)
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "wav"
    if head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "mp3"
    return None


def sniff_image(path: Path) -> str | None:
    """매직 바이트로 jpeg·png·webp만 고른다(확장자·ffprobe 추측을 믿지 않는다)."""
    with Path(path).open("rb") as f:
        head = f.read(16)
    if head.startswith(bytes.fromhex("ffd8ff")):
        return "jpeg_pipe"
    if head.startswith(bytes.fromhex("89504e470d0a1a0a")):
        return "png_pipe"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "webp_pipe"
    return None


class Cancel:
    """작업 중단 신호 + 실행 중 ffmpeg 프로세스 목록(진행 보고 스레드가 409를 받으면 trigger)."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._procs: set[subprocess.Popen] = set()

    @property
    def is_set(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise TaskCancelled()

    def register(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._procs.add(proc)
            if self._event.is_set():
                proc.kill()

    def unregister(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._procs.discard(proc)

    def trigger(self) -> None:
        with self._lock:
            self._event.set()
            for proc in list(self._procs):
                if proc.poll() is None:
                    proc.kill()


def file_input(path: Path, demuxer: str | None = None) -> list[str]:
    """로컬 파일 입력 인자. `file:` 접두로 프로토콜 해석을 막고 화이트리스트를 file로 고정."""
    args = ["-protocol_whitelist", "file"]
    if demuxer:
        args += ["-f", demuxer]
    return [*args, "-i", "file:" + str(Path(path).resolve())]


class Media:
    def __init__(self, ffmpeg: str, ffprobe: str) -> None:
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe

    def run(self, args: list, cancel: Cancel, timeout: float = DEFAULT_TIMEOUT) -> tuple[str, str]:
        """프로세스 실행 → (stdout, stderr).
        실패 시 MediaError(stderr 끝 — 로컬 경로가 있어 로그 금지)."""
        proc = subprocess.Popen(
            [str(a) for a in args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        cancel.register(proc)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise MediaTimeout("ffmpeg 시간 초과") from None
        finally:
            cancel.unregister(proc)
        cancel.check()
        if proc.returncode:
            raise MediaError(err.decode("utf-8", "replace")[-3000:])
        return out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    def ffmpeg_cmd(self, *args) -> list:
        return [self.ffmpeg, "-hide_banner", "-nostdin", *args]

    def probe(self, path: Path, cancel: Cancel) -> dict:
        """매직 바이트로 거른 뒤 형식을 지정해 ffprobe로 확인(확장자를 믿지 않는다).
        허용 형식이 아니거나 크기가 MAX_DIMENSION을 넘으면 MediaError."""
        sniffed = sniff(path)
        if sniffed is None:
            raise MediaError("허용되지 않은 형식")
        text, _ = self.run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                "-f",
                sniffed,
                "file:" + str(Path(path).resolve()),
            ],
            cancel,
            timeout=PROBE_TIMEOUT,
        )
        try:
            data = json.loads(text)
        except ValueError:
            raise MediaError("ffprobe 결과를 읽을 수 없음") from None
        fmt = data.get("format") or {}
        names = str(fmt.get("format_name", "")).split(",")
        demuxer = next((ALLOWED_DEMUXERS[n] for n in names if n in ALLOWED_DEMUXERS), None)
        if demuxer != sniffed:
            raise MediaError("허용되지 않은 형식")
        streams = data.get("streams") or []
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        try:
            duration = float(fmt.get("duration"))
        except TypeError, ValueError:
            raise MediaError("길이를 읽을 수 없음") from None
        try:
            width = int(video["width"]) if video else None
            height = int(video["height"]) if video else None
        except KeyError, TypeError, ValueError:
            raise MediaError("크기를 읽을 수 없음") from None
        if video and not (0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION):
            raise MediaError("영상 크기 상한 초과")
        return {
            "demuxer": demuxer,
            "duration": duration,
            "has_audio": any(s.get("codec_type") == "audio" for s in streams),
            "has_video": video is not None,
            "width": width,
            "height": height,
            "streams": streams,
        }

    def probe_image(self, path: Path, cancel: Cancel) -> dict:
        """사진(R6): 매직 바이트 → `-f *_pipe` 고정 ffprobe. 크기·면적 상한을 넘으면 MediaError."""
        demuxer = sniff_image(path)
        if demuxer is None:
            raise MediaError("허용되지 않은 형식")
        text, _ = self.run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                "-f",
                demuxer,
                "file:" + str(Path(path).resolve()),
            ],
            cancel,
            timeout=PROBE_TIMEOUT,
        )
        try:
            data = json.loads(text)
        except ValueError:
            raise MediaError("ffprobe 결과를 읽을 수 없음") from None
        if (data.get("format") or {}).get("format_name") != demuxer:
            raise MediaError("허용되지 않은 형식")
        video = next((s for s in data.get("streams") or [] if s.get("codec_type") == "video"), None)
        try:
            width, height = int(video["width"]), int(video["height"])
        except KeyError, TypeError, ValueError:
            raise MediaError("크기를 읽을 수 없음") from None
        if not (0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION):
            raise MediaError("사진 크기 상한 초과")
        if width * height > MAX_IMAGE_PIXELS:
            raise MediaError("사진 면적 상한 초과")
        return {"demuxer": demuxer, "width": width, "height": height}
