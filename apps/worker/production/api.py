"""FastAPI 제작 워커 API(W-05~W-09) 클라이언트와 서명 URL 전송.

- 워커 토큰은 API 호출에만 붙인다. 서명 URL(Storage)에는 토큰 없는 별도 클라이언트를 쓴다.
- 토큰·서명 URL은 로그·예외 메시지에 넣지 않는다(F4). httpx·httpcore 로거는 WARNING.
"""

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from production.config import is_allowed_url
from production.errors import ApiCallError, TaskCancelled, TransferError
from production.media import Cancel

logger = logging.getLogger("nomadroom.worker.api")
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

API_PREFIX = "/worker/v1/production"
URL_MARGIN = timedelta(seconds=30)  # 남은 시간이 이보다 짧으면 만료로 보고 재발급(F6)
REFRESH_STATUS = {400, 401, 403}  # Storage가 만료·서명 오류에 돌려주는 코드
CHUNK = 1024 * 1024
FINISH_BACKOFF = (1.0, 3.0)  # finish 재시도 간격(초) — 시도는 최대 3회
PARSE_ERRORS = (ValidationError, ValueError, KeyError, TypeError)
# task-045 R4: 이 워커가 처리할 수 있는 형식(W-05). 서버는 알린 워커에게만 쇼핑 task를 준다
CAPABILITIES = ["shopping"]


class Task(BaseModel):
    """W-05 task(04_API.md W-05). 알 수 없는 필드는 무시한다."""

    model_config = ConfigDict(extra="ignore")

    kind: Literal["prepare", "render"]
    id: uuid.UUID
    job_id: uuid.UUID
    job_kind: str
    format: str
    preset_version: str
    lang: str | None = None
    source_start_sec: float | None = None
    segment_len_sec: float | None = None
    source_kind: str | None = None
    source_url: str | None = None  # task-031: rights_confirmed URL 작업의 prepare만
    spec: dict[str, Any] | None = None


class SignedUrl(BaseModel):
    model_config = ConfigDict(extra="ignore")

    asset_id: uuid.UUID
    kind: str
    url: str
    expires_at: datetime
    parent_asset_id: uuid.UUID | None = None  # task-045 R5: 쇼핑 render 파생 source의 원본

    @field_validator("url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        if not is_allowed_url(value):
            raise ValueError("서명 URL scheme 거부")  # URL 원문은 메시지에 넣지 않는다
        return value

    def expired(self) -> bool:
        return self.expires_at - URL_MARGIN <= datetime.now(UTC)


class UrlRejected(Exception):
    """서명 URL이 만료·거부됨(재발급 대상)."""


class WorkerApi:
    def __init__(
        self,
        base_url: str,
        token: str,
        transport: httpx.BaseTransport | None = None,
        storage_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
            transport=transport,
        )
        # 서명 URL 전용: 워커 토큰 헤더 없음, 리다이렉트 따라가지 않음
        self._storage = httpx.Client(
            timeout=httpx.Timeout(60.0, connect=15.0),
            transport=storage_transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._api.close()
        self._storage.close()

    # --- W-05~W-09 ---------------------------------------------------------------

    def _call(self, method: str, path: str, name: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = self._api.request(method, API_PREFIX + path, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiCallError(f"{name}: {type(exc).__name__}") from None
        if resp.status_code == 409:
            raise TaskCancelled()
        if resp.status_code >= 400:
            raise ApiCallError(f"{name}: HTTP {resp.status_code}", resp.status_code)
        return resp

    def claim(self) -> Task | None:
        resp = self._call("POST", "/claim", "W-05", json={"capabilities": CAPABILITIES})
        if resp.status_code == 204:
            return None
        try:
            return Task.model_validate(resp.json()["task"])
        except PARSE_ERRORS:
            raise ApiCallError("W-05: 응답 형식 오류") from None

    def input_list(self, task: Task) -> list[SignedUrl]:
        """W-06 입력 목록(R2: asset_id 기준, 같은 kind 여러 건)."""
        resp = self._call("GET", f"/{task.kind}/{task.id}/inputs", "W-06")
        try:
            return [
                SignedUrl(
                    asset_id=item["asset_id"],
                    kind=item["kind"],
                    url=item["download_url"],
                    expires_at=item["expires_at"],
                    parent_asset_id=item.get("parent_asset_id"),
                )
                for item in resp.json()["inputs"]
            ]
        except PARSE_ERRORS:  # ValidationError 원문은 URL을 담을 수 있어 버린다
            raise ApiCallError("W-06: 응답 형식 오류") from None

    def inputs(self, task: Task) -> dict[str, SignedUrl]:
        """kind별 입력(일반·예능형: kind마다 1건). 같은 kind가 여럿이면 마지막 것."""
        return {s.kind: s for s in self.input_list(task)}

    def outputs(self, task: Task, items: list[dict[str, Any]]) -> list[SignedUrl]:
        resp = self._call("POST", f"/{task.kind}/{task.id}/outputs", "W-07", json={"items": items})
        try:
            got = [
                SignedUrl(
                    asset_id=i["asset_id"],
                    kind=i["kind"],
                    url=i["upload_url"],
                    expires_at=i["expires_at"],
                )
                for i in resp.json()["items"]
            ]
        except PARSE_ERRORS:
            raise ApiCallError("W-07: 응답 형식 오류") from None
        if len(got) != len(items):
            raise ApiCallError("W-07: 응답 건수 불일치")
        return got

    def progress(self, task: Task, stage: str, pct: int) -> None:
        self._call(
            "POST",
            f"/{task.kind}/{task.id}/progress",
            "W-08",
            json={"stage": stage, "progress_pct": max(0, min(100, int(pct)))},
        )

    def finish(self, task: Task, body: dict[str, Any]) -> bool:
        """W-09. 409는 직전 finish 응답 유실 = 이미 처리됨으로 해석(04_API.md W-09) → False.
        네트워크 오류·5xx는 짧은 백오프로 최대 3회(리뷰 반영 8).
        4xx(409 제외)는 즉시 ApiCallError."""
        for attempt, delay in enumerate((*FINISH_BACKOFF, None)):
            try:
                self._call("POST", f"/{task.kind}/{task.id}/finish", "W-09", json=body)
                return True
            except TaskCancelled:
                logger.info("finish 409: 이미 처리된 task로 본다 id=%s", task.id)
                return False
            except ApiCallError as exc:
                if (exc.status is not None and exc.status < 500) or delay is None:
                    raise
                logger.warning("finish 재시도 %d: %s", attempt + 1, exc)
                time.sleep(delay)
        raise AssertionError("unreachable")

    # --- 서명 URL 전송 ------------------------------------------------------------

    def download(
        self, signed: SignedUrl, dest: Path, max_bytes: int, cancel: Cancel | None = None
    ) -> None:
        """서명 GET으로 작업 폴더에 받는다. 만료·거부면 UrlRejected(호출자가 W-06 재호출)."""
        if signed.expired():
            raise UrlRejected()
        size = 0
        try:
            with self._storage.stream("GET", signed.url) as resp:
                if resp.status_code in REFRESH_STATUS:
                    raise UrlRejected()
                if resp.status_code != 200:
                    raise TransferError(f"다운로드: HTTP {resp.status_code}")
                with dest.open("wb") as f:
                    for chunk in resp.iter_bytes(CHUNK):
                        if cancel is not None:
                            cancel.check()  # 리뷰 반영 9
                        size += len(chunk)
                        if size > max_bytes:
                            raise TransferError("다운로드: 크기 상한 초과")
                        f.write(chunk)
        except httpx.HTTPError as exc:
            raise TransferError(f"다운로드: {type(exc).__name__}") from None

    def upload(self, signed: SignedUrl, src: Path, mime: str, cancel: Cancel | None = None) -> None:
        """서명 PUT 업로드. 만료·거부면 UrlRejected(호출자가 W-07 재호출 → 새 asset_id)."""
        if signed.expired():
            raise UrlRejected()

        def body():  # 청크마다 중단 신호 확인(리뷰 반영 9)
            with src.open("rb") as f:
                while chunk := f.read(CHUNK):
                    if cancel is not None:
                        cancel.check()
                    yield chunk

        try:
            resp = self._storage.put(
                signed.url,
                content=body(),
                headers={"Content-Type": mime, "Content-Length": str(src.stat().st_size)},
            )
        except httpx.HTTPError as exc:
            raise TransferError(f"업로드: {type(exc).__name__}") from None
        if resp.status_code in REFRESH_STATUS:
            raise UrlRejected()
        if resp.status_code >= 300:
            raise TransferError(f"업로드: HTTP {resp.status_code}")
