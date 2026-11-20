"""xAI(그록) 영상 생성 어댑터(task-054 G0: 플랫폼 1개, economy 등급).

**가정(실제 호출·약관·요금 미확인, 사람 할 일)**: 엔드포인트·요청/응답 모양·모델 이름·초당 단가·
결과 호스트는 공개 문서 기준 추정이다. 테스트는 모의 응답으로만 검증한다(실제 xAI 호출 없음).
키는 Authorization 헤더로만 보내고 로그·예외에 넣지 않는다. 응답 원문은 기록하지 않는다.
"""

import base64
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from pydantic import SecretStr

from app.production.videogen.base import PollResult, Rejected, Unknown

logger = logging.getLogger("nomadroom.production.videogen.xai")

API_BASE = "https://api.x.ai/v1"  # 가정
MODEL = "grok-imagine-video"  # 가정
USD_PER_SEC = Decimal(
    "0.08"
)  # 가정: 18초 약 $1.44(tasks/plan-shopping-japanese.md#여행 영상 생성과 비용)
RESULT_HOSTS = frozenset({"vidgen.x.ai"})  # 가정: 결과 영상 호스트(https만)
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,200}")
# 제출 단계에서 "명확한 거부"로 보지 않는 4xx(서버가 받았는지 알 수 없음)
_AMBIGUOUS_4XX = frozenset({408, 409})


class XaiAdapter:
    platform = "xai"
    model = MODEL
    result_hosts = RESULT_HOSTS

    def __init__(self, client: httpx.AsyncClient, api_key: SecretStr, timeout: float) -> None:
        self._client = client
        self._key = api_key
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key.get_secret_value()}"}

    def estimate_usd(self, duration_sec: int) -> Decimal:
        return USD_PER_SEC * duration_sec

    async def submit(self, image: bytes, mime: str, prompt: str, duration_sec: int) -> str:
        data_uri = f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
        body = {
            "model": MODEL,
            "prompt": prompt,
            "duration": duration_sec,
            "image": {"url": data_uri},
        }
        try:
            resp = await self._client.post(
                f"{API_BASE}/videos/generations",
                json=body,
                headers=self._headers(),
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise Unknown("timeout") from exc
        except httpx.HTTPError as exc:
            raise Unknown("network") from exc
        if 400 <= resp.status_code < 500 and resp.status_code not in _AMBIGUOUS_4XX:
            logger.warning("xAI 제출 거부: %s", resp.status_code)
            raise Rejected(f"http_{resp.status_code}")
        if resp.status_code >= 300:
            logger.warning("xAI 제출 응답 불명: %s", resp.status_code)
            raise Unknown(f"http_{resp.status_code}")
        request_id = _field(resp, "request_id")
        if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
            raise Unknown("bad_response")
        return request_id

    async def poll(self, request_id: str) -> PollResult:
        if not _REQUEST_ID.fullmatch(request_id):
            raise Unknown("bad_request_id")
        try:
            resp = await self._client.get(
                f"{API_BASE}/videos/{request_id}", headers=self._headers(), timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise Unknown("network") from exc
        if resp.status_code >= 400:
            logger.warning("xAI 진행 확인 오류: %s", resp.status_code)
            raise Unknown(f"http_{resp.status_code}")
        status = _field(resp, "status")
        if status in ("pending", "queued", "processing", "in_progress"):
            return PollResult("pending")
        if status in ("failed", "expired", "error"):
            return PollResult("failed", error="platform_failed", cost_usd=_cost(resp))
        if status == "done":
            video = _field(resp, "video")
            url = video.get("url") if isinstance(video, dict) else None
            if not isinstance(url, str):
                raise Unknown("bad_response")
            return PollResult("done", video_url=url, cost_usd=_cost(resp))
        raise Unknown("bad_response")


def _field(resp: httpx.Response, name: str) -> Any:
    try:
        body = resp.json()
    except ValueError:
        return None
    return body.get(name) if isinstance(body, dict) else None


def _cost(resp: httpx.Response) -> Decimal | None:
    raw = _field(resp, "cost_usd")  # 가정: 플랫폼이 실제 비용을 주면 사용
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        return None
    try:
        value = Decimal(str(raw))
    except InvalidOperation:
        return None
    return value if value.is_finite() and value >= 0 else None
