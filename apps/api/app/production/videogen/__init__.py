"""AI 영상 생성(A-22, task-054). 기본 꺼짐: VIDEOGEN_ENABLED=1이고 키가 있어야 어댑터를 만든다."""

from fastapi import Request

from app.production.videogen.base import (
    PollResult,
    Rejected,
    Unknown,
    VideoGenAdapter,
    krw,
    not_configured,
    upstream_failed,
)
from app.production.videogen.xai import XaiAdapter

__all__ = [
    "PollResult",
    "Rejected",
    "Unknown",
    "VideoGenAdapter",
    "get_adapter",
    "krw",
    "not_configured",
    "require_enabled",
    "upstream_failed",
]


def require_enabled(request: Request) -> None:
    """꺼짐(VIDEOGEN_ENABLED≠1)·키 없음이면 503(계수·기록 없음, G0)."""
    settings = request.app.state.settings
    if not settings.videogen_enabled or settings.videogen_xai_api_key is None:
        raise not_configured()


def get_adapter(request: Request) -> VideoGenAdapter:
    """FastAPI 의존성. 테스트는 dependency_overrides로 모의 어댑터를 넣는다."""
    require_enabled(request)
    settings = request.app.state.settings
    return XaiAdapter(
        request.app.state.http, settings.videogen_xai_api_key, settings.videogen_timeout_sec
    )
