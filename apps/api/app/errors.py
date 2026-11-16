"""공통 오류 형식 {code, message, field?}. 내부 경로·예외 원문·입력 값은 응답에 넣지 않는다."""

import logging
import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("nomadroom.errors")

# field는 요청 본문 키에서 올 수 있다(사용자 입력). 허용 문자·길이를 벗어나면 생략한다.
_FIELD_RE = re.compile(r"[A-Za-z0-9_.]{1,64}")


class ErrorBody(BaseModel):
    code: str
    message: str
    field: str | None = None


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, field: str | None = None):
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field = field


def unauthenticated() -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", "인증이 필요합니다.")


def forbidden() -> ApiError:
    return ApiError(403, "FORBIDDEN", "이 작업 공간에 접근할 권한이 없습니다.")


def not_found() -> ApiError:
    return ApiError(404, "NOT_FOUND", "찾을 수 없습니다.")


def upstream_error() -> ApiError:
    return ApiError(503, "UPSTREAM_ERROR", "인증 서버에 일시적으로 연결할 수 없습니다.")


_HTTP_CODES = {
    400: ("VALIDATION", "요청이 올바르지 않습니다."),
    401: ("UNAUTHENTICATED", "인증이 필요합니다."),
    403: ("FORBIDDEN", "권한이 없습니다."),
    404: ("NOT_FOUND", "찾을 수 없습니다."),
    405: ("METHOD_NOT_ALLOWED", "허용되지 않은 메서드입니다."),
}


def _body(code: str, message: str, field: str | None = None) -> dict:
    return ErrorBody(code=code, message=message, field=field).model_dump(exclude_none=True)


async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse(
        _body(exc.code, exc.message, exc.field), status_code=exc.status_code, headers=headers
    )


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # 입력 값(input)은 응답·로그 어디에도 쓰지 않는다. 위치(field)만.
    errors = exc.errors()
    field = None
    if errors:
        loc = [str(p) for p in errors[0].get("loc", ())]
        field = ".".join(loc[1:] if len(loc) > 1 else loc)
        if not _FIELD_RE.fullmatch(field):
            field = None
    return JSONResponse(_body("VALIDATION", "입력값이 올바르지 않습니다.", field), status_code=400)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code, message = _HTTP_CODES.get(exc.status_code, ("ERROR", "요청을 처리할 수 없습니다."))
    return JSONResponse(_body(code, message), status_code=exc.status_code)


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.error("처리되지 않은 예외: %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(_body("INTERNAL", "서버 오류가 발생했습니다."), status_code=500)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
