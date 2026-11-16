"""Supabase PostgREST 서버 전용 호출 헬퍼.

service_role 키 사용 이유: workers 테이블은 authenticated 조회 권한이 없고(grant·RLS),
소속 확인·워커 토큰 대조는 사용자 권한과 무관하게 서버가 판단해야 하기 때문이다.
"""

from app.config import Settings, is_jwt_format


def service_headers(settings: Settings) -> dict[str, str]:
    """새 형식 sb_secret_ 키는 apikey 헤더로만, 레거시 JWT 키는 apikey + Authorization."""
    key = settings.supabase_service_role_key.get_secret_value()
    headers = {"apikey": key}
    if is_jwt_format(key):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def rest_url(settings: Settings, table: str) -> str:
    return f"{settings.supabase_url}/rest/v1/{table}"
