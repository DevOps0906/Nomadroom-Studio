"""URL 원본 검사(SSRF 1차). 근거: docs/01_PRD.md#8, tasks/task-031.md#착수-결정 G1·G2·G9.

API는 네트워크 요청을 하지 않는다(DNS 조회·리다이렉트 추적 금지 — API가 발사대가 되지 않게).
문자열만으로 스킴(https)·호스트 허용 목록(YouTube)·IP 리터럴·포트·사용자 정보를 검사한다.
연결별 실제 IP 재검사는 로컬 워커(apps/worker/production/fetch_url.py)가 한다.
오류 문구에는 입력 URL을 담지 않는다.
"""

import ipaddress
import re
from urllib.parse import urlsplit

from app.errors import ApiError

MAX_URL_LEN = 2048
ALLOWED_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"})
_BAD_CHARS = re.compile(r"[\x00-\x20\x7f\\]")


def _reject(message: str) -> ApiError:
    return ApiError(400, "VALIDATION", message, "source_url")


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def check_source_url(raw: str) -> str:
    """허용되면 앞뒤 공백을 뗀 URL을 돌려주고, 아니면 400 VALIDATION(field=source_url)."""
    url = raw.strip()
    if not url or len(url) > MAX_URL_LEN or _BAD_CHARS.search(url):
        raise _reject("URL 형식이 올바르지 않습니다.")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise _reject("URL 형식이 올바르지 않습니다.") from None
    if parts.scheme.lower() != "https":
        raise _reject("https 주소만 사용할 수 있습니다.")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise _reject("URL 형식이 올바르지 않습니다.")
    host = (parts.hostname or "").lower()
    if not host:
        raise _reject("URL 형식이 올바르지 않습니다.")
    if _is_ip_literal(host):
        raise _reject("IP 주소는 사용할 수 없습니다.")
    if port not in (None, 443):
        raise _reject("기본 포트(443)만 사용할 수 있습니다.")
    if host not in ALLOWED_HOSTS:
        raise _reject("YouTube 주소만 사용할 수 있습니다.")
    return url
