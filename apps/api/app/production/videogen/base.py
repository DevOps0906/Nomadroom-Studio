"""AI 영상 생성 플랫폼 어댑터 인터페이스(A-22, task-054 G0·G2).

어댑터는 플랫폼 호출만 한다(DB·Storage 모름). 결과 분류:
- `Rejected`: 플랫폼이 요청을 명확히 거부(4xx) → run failed·비계상.
- `Unknown`: 타임아웃·5xx·응답 불명 → run unknown·계상 유지(자동 재제출 없음).
오류 코드(`code`)는 `^[a-z0-9_]{1,40}$`(generation_runs.error_code), 응답 원문은 담지 않는다.
"""

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

from app.errors import ApiError


class AdapterError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Rejected(AdapterError):
    """플랫폼의 명확한 거부(제출되지 않음)."""


class Unknown(AdapterError):
    """제출 여부·결과를 알 수 없음."""


@dataclass(frozen=True)
class PollResult:
    status: Literal["pending", "done", "failed"]
    video_url: str | None = None
    cost_usd: Decimal | None = None  # 플랫폼이 알려준 실제 비용(없으면 견적 금액으로 계상)
    error: str | None = None


class VideoGenAdapter(Protocol):
    platform: str
    model: str
    result_hosts: frozenset[str]  # 결과 다운로드 허용 호스트(https, G6)

    def estimate_usd(self, duration_sec: int) -> Decimal: ...

    async def submit(self, image: bytes, mime: str, prompt: str, duration_sec: int) -> str:
        """요청 ID를 돌려준다. 입력 사진은 본문(base64)으로만 보낸다(서명 URL 금지, G6)."""
        ...

    async def poll(self, request_id: str) -> PollResult: ...


def krw(usd: Decimal, krw_per_usd: int) -> int:
    """USD → 정수 원(올림, G3). 최소 1원."""
    return max(1, math.ceil(usd * krw_per_usd))


def not_configured() -> ApiError:
    return ApiError(503, "UPSTREAM_ERROR", "AI 영상 생성 기능이 꺼져 있습니다.")


def upstream_failed() -> ApiError:
    return ApiError(502, "UPSTREAM_ERROR", "AI 영상 플랫폼 요청에 실패했습니다.")
