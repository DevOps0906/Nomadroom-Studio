"""훅 TTS(edge-tts, task-030). 로컬 워커 전용·기본 꺼짐(WORKER_TTS_ENABLED, docs/01_PRD.md#7 Q6).

외부로 나가는 값은 hook.text·voice·rate뿐. 문구·voice는 로그에 쓰지 않고 예외는 종류 이름만 남긴다.
실패하면 tts_failed — 첨부 음성·무음으로 대체하지 않는다(승인본과 다른 음성 금지, I1).
"""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from production.config import TtsSettings
from production.errors import TaskFailed
from production.media import Cancel

DEFAULT_RATE = "+50%"  # docs/05_DATA_MODEL.md hook.tts rate 기본
CANCEL_POLL_SEC = 0.2
# 리뷰 반영(SSML 주입): edge-tts가 voice·rate를 이스케이프 없이 SSML에 넣으므로 형식을 고정한다.
# API spec.py Tts 모델과 같은 패턴. fullmatch라 끝 개행도 거부한다.
VOICE_RE = re.compile(r"[a-z]{2,3}-[A-Z]{2,4}-[A-Za-z0-9]+Neural")
RATE_RE = re.compile(r"[+-]\d{1,3}%")

for _name in ("edge_tts", "aiohttp"):  # 요청 내용(문구·voice)이 디버그 로그에 남지 않게
    logging.getLogger(_name).setLevel(logging.WARNING)


class TtsFailed(TaskFailed):
    def __init__(self, detail: str = "") -> None:
        super().__init__("audio", "tts_failed", detail)


Synth = Callable[[str, str, str, Path, TtsSettings], Awaitable[None]]


async def edge_save(text: str, voice: str, rate: str, out: Path, cfg: TtsSettings) -> None:
    import edge_tts  # 꺼져 있으면 불러오지 않는다

    communicate = edge_tts.Communicate(
        text,
        voice,
        rate=rate,
        connect_timeout=cfg.connect_timeout_sec,
        receive_timeout=cfg.receive_timeout_sec,
    )
    await communicate.save(str(out))


async def _watch(job: Awaitable[None], cancel: Cancel) -> None:
    """job을 돌리며 중단 신호(409)를 확인한다. 신호가 오면 job을 취소한다."""
    task = asyncio.ensure_future(job)
    try:
        while not task.done():
            if cancel.is_set:
                task.cancel()
                break
            await asyncio.wait({task}, timeout=CANCEL_POLL_SEC)
        await task
    finally:
        if not task.done():
            task.cancel()


def synthesize(
    text: str, tts: object, out: Path, cancel: Cancel, cfg: TtsSettings, synth: Synth | None = None
) -> str:
    """spec.hook.tts로 out(mp3)을 만든다. 반환: report용 경로 설명. 실패는 TtsFailed."""
    if not cfg.enabled:
        raise TtsFailed("TTS 비활성(WORKER_TTS_ENABLED)")
    voice = tts.get("voice") if isinstance(tts, dict) else None
    rate = tts.get("rate", DEFAULT_RATE) if isinstance(tts, dict) else None
    if not (isinstance(voice, str) and VOICE_RE.fullmatch(voice)):
        raise TtsFailed("ValueError")
    if not (isinstance(rate, str) and RATE_RE.fullmatch(rate)):
        raise TtsFailed("ValueError")
    cancel.check()
    try:
        asyncio.run(
            asyncio.wait_for(
                _watch((synth or edge_save)(text, voice, rate, out, cfg), cancel), cfg.timeout_sec
            )
        )
    except asyncio.CancelledError:
        cancel.check()
        raise TtsFailed("CancelledError") from None
    except Exception as exc:  # 원문은 문구·voice를 담을 수 있어 종류만
        raise TtsFailed(type(exc).__name__) from None
    cancel.check()
    if not out.is_file() or out.stat().st_size == 0:
        raise TtsFailed("생성 음성 없음")
    return f"edge-tts voice={voice} rate={rate}"
