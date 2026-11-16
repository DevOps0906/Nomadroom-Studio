"""서버 실행: 루트 핸들러 마스킹을 먼저 설치하고 uvicorn 자체 로그 설정은 끈다(log_config=None)."""

import os

import uvicorn

from app.logging_mask import setup_logging
from app.main import create_app


def main() -> None:
    setup_logging()
    host = os.environ.get("API_HOST") or "127.0.0.1"
    port = int(os.environ.get("API_PORT") or "8000")
    uvicorn.run(create_app(), host=host, port=port, log_config=None)


if __name__ == "__main__":
    main()
