"""설정: 환경변수 한 곳에서 읽는다. 필수 값이 없으면 기동 실패(조용한 기본값 금지)."""

from functools import cached_property
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


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

    @cached_property
    def jwt_issuer(self) -> str:
        return self.supabase_jwt_issuer or f"{self.supabase_url}/auth/v1"

    @cached_property
    def jwks_url(self) -> str:
        return f"{self.supabase_url}/auth/v1/.well-known/jwks.json"
