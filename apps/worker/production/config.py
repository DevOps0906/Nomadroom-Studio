"""워커 설정. 환경변수만(이름은 .env.example). 토큰·API 주소는 필수 — 누락 시 시작하지 않는다."""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def is_allowed_url(url: str) -> bool:
    """https만 허용. 로컬 개발 예외: http://127.0.0.1·localhost (리뷰 반영 5)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if not parts.hostname:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and parts.hostname in LOCAL_HOSTS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WORKER_", extra="ignore")

    api_base_url: str  # FastAPI 주소(예: https://api.example.com). /worker/v1/*만 호출
    token: SecretStr  # 워커 토큰 `<worker_id>.<secret>` — 로그 금지
    ffmpeg: str = "ffmpeg"  # 시스템 ffmpeg 경로(F11). imageio-ffmpeg 동봉 바이너리는 쓰지 않는다
    ffprobe: str = "ffprobe"
    work_dir: Path = Path.home() / ".nomadroom-worker" / "production"
    poll_interval_sec: float = 10.0  # W-05 폴링 간격(W-01과 같음)
    progress_interval_sec: float = 60.0  # F2: 단계 전환과 별도의 주기 보고

    @field_validator("api_base_url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        if not is_allowed_url(value):
            raise ValueError("api_base_url은 https만(로컬 http://127.0.0.1·localhost 예외)")
        return value


class TtsSettings(BaseSettings):
    """TTS(edge-tts, task-030) 설정. 이용 조건 미확인이라 기본 꺼짐(docs/01_PRD.md#7 Q6).
    필수 값이 없어 따로 읽는다(꺼져 있으면 spec.hook.tts 렌더는 tts_failed)."""

    model_config = SettingsConfigDict(env_prefix="WORKER_TTS_", extra="ignore")

    enabled: bool = False  # WORKER_TTS_ENABLED
    timeout_sec: float = 90.0  # 전체 상한(asyncio.wait_for)
    connect_timeout_sec: int = 10  # edge-tts 연결 타임아웃
    receive_timeout_sec: int = 30  # edge-tts 수신 타임아웃
