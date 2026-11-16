"""로그 마스킹.

루트 핸들러에 필터를 붙여, 포매팅이 끝난 문자열(traceback 포함)에서 비밀을 지운다.
"""

import logging
import re
import sys
from typing import TextIO

MASK = "***"

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\bbearer\s+\S+"), f"Bearer {MASK}"),
    (re.compile(r"eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), MASK),
    (re.compile(r"sb_(secret|publishable)_\S+"), rf"sb_\1_{MASK}"),
    (re.compile(rf"({_UUID})\.[A-Za-z0-9_-]{{20,}}"), rf"\1.{MASK}"),
    # 워커 secret 단독(secrets.token_urlsafe(32) = 43자)
    (re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])"), MASK),
    (
        re.compile(r"(?i)(\b(?:x-)?api[-_]?key['\"]?\s*[:=,]\s*b?['\"]?)[^'\"\s,;)}]+"),
        rf"\1{MASK}",
    ),
    # Google API 키(AIza + 35자)와 쿼리 key= 값
    (re.compile(r"AIza[0-9A-Za-z_-]{35}"), MASK),
    (re.compile(r"(?i)\bkey=\S+"), f"key={MASK}"),
    (
        re.compile(r"(?i)(\b(?:set-)?cookie['\"]?\s*[:=,]\s*b?['\"]?)[^'\"\r\n]+"),
        rf"\1{MASK}",
    ),
]


def mask(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class SecretMaskingFilter(logging.Filter):
    """메시지·예외·스택을 먼저 문자열로 만든 뒤 마스킹해 레코드에 되돌려 놓는다."""

    _formatter = logging.Formatter()

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask(record.getMessage())
        record.args = None
        if record.exc_info:
            record.exc_text = self._formatter.formatException(record.exc_info)
            record.exc_info = None
        if record.exc_text:
            record.exc_text = mask(record.exc_text)
        if record.stack_info:
            record.stack_info = mask(record.stack_info)
        return True


_HANDLER_NAME = "nomadroom-masked"


def setup_logging(stream: TextIO | None = None, level: int = logging.INFO) -> logging.Handler:
    """루트 핸들러 하나에 마스킹 필터를 단다. uvicorn·httpx 로거는 루트로 전달되게 한다.

    멱등: 이미 설치돼 있으면 그 핸들러를 다시 쓴다(stream을 주면 출력 대상만 바꾼다).
    """
    root = logging.getLogger()
    handler = next((h for h in root.handlers if h.get_name() == _HANDLER_NAME), None)
    if handler is None:
        handler = logging.StreamHandler(stream or sys.stderr)
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler.addFilter(SecretMaskingFilter())
        root.addHandler(handler)
    elif stream is not None and isinstance(handler, logging.StreamHandler):
        handler.setStream(stream)
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    # httpx는 요청마다 URL을 INFO로 남긴다. WARNING 이상만.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return handler
