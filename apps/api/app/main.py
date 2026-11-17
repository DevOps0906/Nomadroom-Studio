"""FastAPI 앱 뼈대. 실행: `uv run python -m app` (루트 로깅 마스킹 적용 후 uvicorn 기동)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from app.auth.jwks import JwksCache
from app.config import Settings
from app.errors import install_error_handlers
from app.logging_mask import setup_logging
from app.routes import (
    candidates,
    candidates_used,
    collect_jobs,
    dashboard,
    profiles,
    verify_runs,
    worker,
)

HTTP_TIMEOUT_SECONDS = 5.0


class HealthOut(BaseModel):
    status: Literal["ok"]


def create_app(settings: Settings | None = None) -> FastAPI:
    # `uvicorn --factory` 경로에서도 마스킹이 걸리도록 여기서 보장한다(멱등).
    setup_logging()
    settings = settings or Settings()  # type: ignore[call-arg]  # 필수 값은 환경변수에서
    docs = settings.api_docs_enabled

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            app.state.http = client
            yield

    app = FastAPI(
        title="Nomadroom Studio API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.jwks = JwksCache(settings.jwks_url)
    install_error_handlers(app)
    app.include_router(profiles.router)
    app.include_router(candidates.router)
    app.include_router(candidates_used.router)
    app.include_router(dashboard.router)
    app.include_router(verify_runs.router)
    app.include_router(collect_jobs.router)
    app.include_router(worker.router)
    app.add_middleware(worker.WorkerBodyLimit)

    @app.get("/healthz", response_model=HealthOut)
    async def healthz() -> HealthOut:
        return HealthOut(status="ok")

    return app
