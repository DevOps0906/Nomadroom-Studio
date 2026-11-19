"""설정: 환경변수 한 곳에서 읽는다. 필수 값이 없으면 기동 실패(조용한 기본값 금지)."""

import re
from functools import cached_property
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_GOOGLE_API_KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{35}")


def is_jwt_format(value: str) -> bool:
    return value.startswith("eyJ") and value.count(".") == 2


class Settings(BaseSettings):
    # hide_input_in_errors: 검증 오류 문자열에 입력값(키 원문)을 넣지 않는다.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    supabase_url: str
    # service_role(또는 sb_secret_) 키: 서버 환경변수로만 받는다. 로그·응답에 쓰지 않는다.
    supabase_service_role_key: SecretStr
    # 비우면 {SUPABASE_URL}/auth/v1
    supabase_jwt_issuer: str | None = None
    # YouTube Data API v3 키: 서버 환경변수로만. 없으면 기록 검증(A-07)만 502로 거부한다.
    youtube_api_key: SecretStr | None = None
    # Anthropic(Claude) 키: AI 초안(A-14) 전용, 서버 환경변수로만. 없으면 A-14만 503(기동은 정상).
    anthropic_api_key: SecretStr | None = None
    # A-14 설정값(tasks/task-029.md#착수-결정 H1·H5). 상한 3회는 01_PRD.md#7 Q7 확정값.
    ai_draft_model: str = "claude-sonnet-5-5"
    ai_draft_max_per_job: int = 3
    ai_draft_max_sheets: int = 16
    ai_draft_max_tokens: int = 8192
    ai_draft_max_items: int = 80
    ai_draft_max_shots: int = 40
    ai_draft_timeout_sec: float = 90.0
    # /docs·/redoc·/openapi.json 노출. 기본은 끈다.
    api_docs_enabled: bool = False

    @field_validator("supabase_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        parts = urlsplit(v)
        if parts.scheme == "https" and parts.hostname:
            return v
        if parts.scheme == "http" and parts.hostname in _LOCAL_HOSTS:
            return v
        raise ValueError("SUPABASE_URL은 https URL이어야 합니다(로컬 주소만 http 허용)")

    @field_validator("supabase_service_role_key")
    @classmethod
    def _check_key_kind(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        if not (raw.startswith("sb_secret_") or is_jwt_format(raw)):
            raise ValueError(
                "SUPABASE_SERVICE_ROLE_KEY는 sb_secret_ 키 또는 service_role JWT여야 합니다"
            )
        return v

    @field_validator("youtube_api_key")
    @classmethod
    def _check_youtube_key(cls, v: SecretStr | None) -> SecretStr | None:
        # 값이 있으면 Google API 키 형식만 허용(오류 메시지에 값을 넣지 않는다). 빈 값은 미설정
        if v is None or v.get_secret_value() == "":
            return None
        if not _GOOGLE_API_KEY_RE.fullmatch(v.get_secret_value()):
            raise ValueError("YOUTUBE_API_KEY 형식이 올바르지 않습니다(AIza로 시작하는 39자)")
        return v

    @field_validator("anthropic_api_key")
    @classmethod
    def _blank_anthropic_key(cls, v: SecretStr | None) -> SecretStr | None:
        # 빈 값은 미설정(A-14 503). 형식 검사는 하지 않는다(값을 메시지에 넣지 않음).
        if v is None or not v.get_secret_value().strip():
            return None
        return v

    @cached_property
    def jwt_issuer(self) -> str:
        return self.supabase_jwt_issuer or f"{self.supabase_url}/auth/v1"

    @cached_property
    def jwks_url(self) -> str:
        return f"{self.supabase_url}/auth/v1/.well-known/jwks.json"
