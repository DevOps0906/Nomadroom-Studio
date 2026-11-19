"""Nomadroom 로컬 워커 실행 파일. FastAPI `/worker/v1/*`만 아웃바운드로 호출한다(포트 개방 없음).

W-05 폴링 → 작업 종류 분기(prepare·render). 수집 작업 종류는 task-009 재개 때 같은 파일에 추가한다.
실행: `uv run python main.py` (환경변수 WORKER_API_BASE_URL·WORKER_TOKEN 필수, .env.example)
"""

import logging
import shutil
import sys
import time

from production.api import WorkerApi
from production.config import Settings
from production.errors import ApiCallError, TaskCancelled
from production.media import Media
from production.paths import clean_root
from production.runner import run_task

logger = logging.getLogger("nomadroom.worker")


def poll_once(api: WorkerApi, settings: Settings, media: Media) -> bool:
    """task 1건 수령·처리. 정상 종료(done·failed)면 True(바로 다음 수령), 그 밖에는 False(대기)."""
    task = api.claim()
    if task is None:
        return False
    status = run_task(api, task, settings.work_dir, media, settings.progress_interval_sec)
    return status in ("done", "failed")


def step(api: WorkerApi, settings: Settings, media: Media) -> bool:
    """폴링 1회. 어떤 예외도 루프를 끝내지 않는다. True면 바로 다음 수령, False면 대기."""
    try:
        return poll_once(api, settings, media)
    except (ApiCallError, TaskCancelled) as exc:
        logger.warning("수령 실패: %s", str(exc) or type(exc).__name__)
    except Exception as exc:  # 리뷰 반영 7: 원문은 경로·URL을 담을 수 있어 종류만
        logger.error("폴링 예외: %s", type(exc).__name__)
    return False


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()  # type: ignore[call-arg]  # 필수 값은 환경변수
    for name in (settings.ffmpeg, settings.ffprobe):
        if shutil.which(name) is None:
            logger.error("ffmpeg·ffprobe를 찾을 수 없습니다(WORKER_FFMPEG·WORKER_FFPROBE).")
            return 1
    media = Media(settings.ffmpeg, settings.ffprobe)
    removed = clean_root(settings.work_dir)  # 단일 워커: 이전 실행의 작업 폴더 정리
    logger.info("작업 폴더 정리: %d개", removed)
    api = WorkerApi(settings.api_base_url, settings.token.get_secret_value())
    logger.info("워커 시작: 폴링 %.0f초", settings.poll_interval_sec)
    try:
        while True:
            if not step(api, settings, media):
                time.sleep(settings.poll_interval_sec)
    except KeyboardInterrupt:
        logger.info("워커 종료")
    finally:
        api.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
