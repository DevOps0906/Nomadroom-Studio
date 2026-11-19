"""렌더 실행·제작 task RPC 공용 헬퍼. 근거: tasks/task-023.md#착수-결정 E1·E3,
supabase/migrations/20261119000017_production_render.sql.

RPC SQLSTATE → API 오류(000016 NR009~011을 잇는다). 409 상태 불가 문구는 RPC가 만든 것
(현재 상태 값만 담음)을 그대로 쓴다. 키·경로·입력 원문은 메시지에 없다.
"""

import logging
import uuid
from typing import Any

from fastapi import Request

from app.errors import ApiError, db_error, not_found
from app.production import storage
from app.routes.profiles import _send

logger = logging.getLogger("nomadroom.production.runs")

_STATE_FALLBACK = "현재 상태에서는 할 수 없습니다."


def _error_body(resp: Any) -> tuple[str | None, str | None]:
    try:
        body = resp.json()
    except ValueError:
        return None, None
    if not isinstance(body, dict):
        return None, None
    code, message = body.get("code"), body.get("message")
    return (
        code if isinstance(code, str) else None,
        message if isinstance(message, str) and len(message) <= 200 else None,
    )


def _map(code: str | None, message: str | None, field: str | None) -> ApiError | None:
    if code == "NR009":
        return not_found()
    if code == "NR010":
        return ApiError(409, "CONFLICT", message or _STATE_FALLBACK)
    if code == "NR011":
        return ApiError(409, "CONFLICT", "다른 작업에 이미 쓴 멱등 키입니다.", "Idempotency-Key")
    if code == "NR012":
        return ApiError(400, "VALIDATION", "입력값이 올바르지 않습니다.", field)
    if code == "NR013":
        return ApiError(
            429, "RATE_LIMITED", "렌더를 너무 자주 요청했습니다. 잠시 후 다시 시도해 주세요."
        )
    if code == "NR014":
        return ApiError(409, "CONFLICT", "진행 중이거나 완료된 렌더가 있습니다.")
    if code == "NR015":
        return ApiError(409, "CONFLICT", "재시도 횟수를 넘었습니다.")
    if code == "23505":
        # RPC 안 unique 경합(동시 요청)이 503으로 새지 않게(리뷰 반영 1)
        return ApiError(409, "CONFLICT", "다른 요청과 겹쳤습니다. 다시 시도해 주세요.")
    return None


async def rpc(request: Request, name: str, payload: dict, field: str | None = None) -> Any:
    """RPC 호출. 4xx의 NR 코드는 API 오류로, 그 밖 오류는 503."""
    path = f"rpc/{name}"
    resp = await _send(request, "POST", path, json=payload)
    if 400 <= resp.status_code < 500:
        err = _map(*_error_body(resp), field)
        if err is not None:
            raise err
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: POST %s", resp.status_code, path)
        raise db_error()
    try:
        return resp.json()
    except ValueError as exc:
        raise db_error() from exc


def _asset_id(path: str) -> str:
    """로그용: 경로 대신 자산 id(파일 이름)만."""
    return path.rsplit("/", 1)[-1].split(".", 1)[0]


async def delete_objects(request: Request, paths: object, op: str) -> None:
    """RPC가 지운 pending 산출물의 Storage 객체를 지운다. DB는 이미 확정이라 실패는 로그만(id)."""
    if not isinstance(paths, list):
        return
    for path in paths:
        try:
            await storage.delete_object(
                request.app.state.http, request.app.state.settings, str(path)
            )
        except ApiError:
            logger.warning("제작 산출물 객체 정리 실패(%s): asset=%s", op, _asset_id(str(path)))


async def expire_offline(request: Request, ws: uuid.UUID) -> None:
    """E3 오프라인 지연 평가(running·preparing 3분, queued 10분 → worker_offline).

    만료된 task의 pending 산출물 행은 RPC가 지우고, 객체는 여기서 지운다(리뷰 반영 4).
    """
    result = await rpc(request, "expire_production_offline", {"p_workspace": str(ws)})
    if not isinstance(result, dict):
        raise db_error()
    expired = result.get("expired")
    if isinstance(expired, int) and expired > 0:
        logger.info("제작 오프라인 만료 %d건", expired)
    await delete_objects(request, result.get("deleted_paths"), "만료")
