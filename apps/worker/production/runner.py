"""제작 task 실행: 작업 폴더·진행 보고(F2)·URL 재발급(F6)·실패 코드(F7)·finish(F5).

로그에는 task kind·id·단계·코드만 쓴다. 토큰·서명 URL·로컬 경로·예외 원문은 쓰지 않는다(F4).
"""

import json
import logging
import threading
from pathlib import Path
from typing import Any

from production.adapter import PRESET_VERSION, to_project
from production.adapter_variety import PRESET_VERSION as VARIETY_PRESET
from production.adapter_variety import to_variety_project
from production.api import SignedUrl, Task, UrlRejected, WorkerApi
from production.config import TtsSettings
from production.errors import (
    ApiCallError,
    AudioMissing,
    RenderFailed,
    TaskCancelled,
    TaskFailed,
    TransferError,
)
from production.fetch_url import fetch_url
from production.hook_audio import make_hook
from production.media import Cancel, Media, MediaError
from production.paths import WorkDir
from production.prepare import prepare
from production.render import CAPTION_FONT, TITLE_FONT, render
from production.tts import TtsFailed, synthesize
from production.variety.render import render_variety

logger = logging.getLogger("nomadroom.worker.production")

MB = 1024 * 1024
MAX_INPUT_BYTES = 500 * MB  # 버킷 상한(04_API.md W-07)
MAX_HOOK_BYTES = 20 * MB  # 리뷰 반영 3: 훅 음성 다운로드 상한


class Reporter:
    """W-08 진행 보고. 단계가 바뀌면 즉시, 그 밖에는 interval마다 백그라운드로 보낸다.
    409를 받으면 cancel.trigger()로 ffmpeg를 kill 하고 작업을 멈춘다."""

    def __init__(self, api: WorkerApi, task: Task, cancel: Cancel, interval: float) -> None:
        self.api, self.task, self.cancel, self.interval = api, task, cancel, interval
        self.stage: str | None = None
        self.pct = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="progress", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=35)

    def set(self, stage: str, pct: int) -> None:
        changed = stage != self.stage
        self.stage, self.pct = stage, pct
        if changed:
            self._send()
        self.cancel.check()

    def _send(self) -> None:
        if self.stage is None or self.cancel.is_set:
            return
        with self._lock:
            try:
                self.api.progress(self.task, self.stage, self.pct)
            except TaskCancelled:
                logger.info("진행 보고 409: 작업 중단 kind=%s id=%s", self.task.kind, self.task.id)
                self.cancel.trigger()
            except ApiCallError as exc:
                logger.warning("진행 보고 실패: %s", exc)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self._send()


def _download(
    api: WorkerApi,
    task: Task,
    signed: SignedUrl,
    dest: Path,
    cancel: Cancel,
    max_bytes: int = MAX_INPUT_BYTES,
) -> SignedUrl:
    """서명 GET. 만료·거부면 W-06을 다시 불러 같은 자산의 새 URL로 1회 재시도(F6)."""
    try:
        api.download(signed, dest, max_bytes, cancel)
        return signed
    except UrlRejected:
        logger.info("입력 URL 만료: 재발급 kind=%s", signed.kind)
    cancel.check()
    # W-06이 주는 최신 ready 자산(그 사이 바뀌었으면 새 자산 — 실제로 쓴 id를 돌려준다)
    fresh = api.inputs(task).get(signed.kind)
    if fresh is None:
        raise TransferError("입력 자산 없음")
    try:
        api.download(fresh, dest, max_bytes, cancel)
    except UrlRejected:
        raise TransferError("입력 URL 재발급 후에도 거부") from None
    return fresh


def _upload_all(
    api: WorkerApi, task: Task, files: list[dict[str, Any]], reporter: Reporter, cancel: Cancel
) -> list[str]:
    """W-07로 한 번에 서명 PUT을 받고 올린다. 실패·만료 건은 W-07 재호출로 새 asset_id(F6).
    W-09에는 마지막으로 성공한 id만 보낸다."""
    items = []
    for f in files:
        item = {"kind": f["kind"], "size_bytes": f["path"].stat().st_size, "mime": f["mime"]}
        if f.get("duration") is not None:
            item["duration_sec"] = round(float(f["duration"]), 3)
        items.append(item)
    signed = api.outputs(task, items)
    ids: list[str] = []
    for n, (f, item, url) in enumerate(zip(files, items, signed, strict=True)):
        cancel.check()
        try:
            api.upload(url, f["path"], f["mime"], cancel)
        except UrlRejected:
            logger.info("업로드 URL 만료: 재발급 kind=%s", f["kind"])
            url = api.outputs(task, [item])[0]
            try:
                api.upload(url, f["path"], f["mime"], cancel)
            except UrlRejected:
                raise TransferError("업로드 URL 재발급 후에도 거부") from None
        ids.append(str(url.asset_id))
        reporter.set("upload", (n + 1) * 100 // len(files))
    return ids


def _prepare(
    api: WorkerApi, task: Task, work: WorkDir, media: Media, cancel: Cancel, reporter: Reporter
) -> dict:
    reporter.set("download", 0)
    start = float(task.source_start_sec or 0.0)
    if task.source_kind == "url":  # task-031: 로컬 yt-dlp(실패하면 url_unavailable → 업로드 안내)
        raw = fetch_url(task.source_url, work, cancel, reporter.set, start, task.segment_len_sec)
    else:
        src = api.inputs(task).get("source_upload")
        if src is None:
            raise TaskFailed("prepare", "input_invalid", "원본 업로드 없음")
        raw = work.path("input.bin")
        try:
            _download(api, task, src, raw, cancel)
        except TransferError as exc:
            raise TaskFailed("prepare", "download_failed", str(exc)) from None
    out = prepare(raw, work, start, task.segment_len_sec, media, cancel, reporter.set)
    reporter.set("upload", 0)
    files = [
        {
            "kind": "source",
            "path": out["source"],
            "mime": "video/mp4",
            "duration": out["meta"]["duration_sec"],
        },
        {"kind": "analysis", "path": out["analysis"], "mime": "application/json"},
        *({"kind": "sheet", "path": p, "mime": "image/jpeg"} for p in out["sheets"]),
    ]
    try:
        ids = _upload_all(api, task, files, reporter, cancel)
    except TransferError as exc:
        raise TaskFailed("prepare", "unknown", str(exc)) from None
    return {"status": "done", "asset_ids": ids, "meta": out["meta"]}


def _render(
    api: WorkerApi,
    task: Task,
    work: WorkDir,
    media: Media,
    cancel: Cancel,
    reporter: Reporter,
    tts_cfg: TtsSettings,
) -> dict:
    if task.format == "variety":  # W1: 형식 분기(preset·lang 확인은 형식별로 각 함수 안에서)
        return _render_variety(api, task, work, media, cancel, reporter)
    if task.preset_version != PRESET_VERSION:  # F9
        raise RenderFailed("preset_version 불일치")
    if task.format != "category":
        raise RenderFailed("지원하지 않는 형식")
    project = to_project(task.spec, task.lang)
    tts = task.spec["hook"].get("tts")  # I3: TTS면 W-06 hook_audio를 쓰지 않는다
    reporter.set("download", 0)
    inputs = api.inputs(task)
    if tts is None and "hook_audio" not in inputs:  # F8: W-06 최신 ready hook_audio가 정본
        raise AudioMissing("훅 음성 없음")
    if "source" not in inputs:
        raise RenderFailed("source 없음")
    source = work.path("source.mp4")
    hook_raw = work.path("hook_input.bin")
    hook_used = None
    try:
        src_used = _download(api, task, inputs["source"], source, cancel)
        reporter.set("download", 50)
        if tts is None:
            hook_used = _download(api, task, inputs["hook_audio"], hook_raw, cancel, MAX_HOOK_BYTES)
    except TransferError as exc:
        raise RenderFailed(str(exc)) from None

    reporter.set("audio", 0)
    try:
        source_meta = media.probe(source, cancel)
    except MediaError:
        raise RenderFailed("source를 읽을 수 없음") from None
    if source_meta["demuxer"] != "mov" or not source_meta["has_video"]:
        raise RenderFailed("source 형식 오류")
    hook_wav = work.path("hook.wav")
    tts_note = "supplied recording"
    if tts is None:
        hook_duration = make_hook(media, hook_raw, hook_wav, cancel)
    else:
        hook_raw = work.path("hook_tts.mp3")
        tts_note = synthesize(project["hook"], tts, hook_raw, cancel, tts_cfg)
        try:
            hook_duration = make_hook(media, hook_raw, hook_wav, cancel)
        except AudioMissing:
            raise TtsFailed("생성 음성을 읽을 수 없음") from None

    output = work.path("result_ko.mp4")
    result = render(
        project, source, source_meta, hook_wav, hook_duration, output, media, cancel, reporter.set
    )
    report = work.path("report.json")
    report.write_text(
        json.dumps(
            {
                "output": "result_ko.mp4",
                **result,
                "preset_version": PRESET_VERSION,
                "source_asset_id": str(src_used.asset_id),
                # F8: 실제로 쓴 음성(TTS면 입력 자산 없음)
                "hook_audio_asset_id": str(hook_used.asset_id) if hook_used else None,
                "spec_hook_audio_asset_id": (task.spec or {}).get("hook", {}).get("audio_asset_id"),
                "tts": tts_note,  # I3: 실제 경로(voice·rate 또는 supplied recording)
                "fonts": [TITLE_FONT.stem, CAPTION_FONT.stem],
                "review_required": "Watch final video and inspect every cut before delivery.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    reporter.set("upload", 0)
    files = [
        {"kind": "output_mp4", "path": output, "mime": "video/mp4", "duration": result["duration"]},
        {"kind": "report", "path": report, "mime": "application/json"},
        {"kind": "hook_audio", "path": hook_wav, "mime": "audio/wav", "duration": hook_duration},
    ]
    try:
        ids = _upload_all(api, task, files, reporter, cancel)
    except TransferError as exc:
        raise RenderFailed(str(exc)) from None
    return {"status": "done", "asset_ids": ids}


def _render_variety(
    api: WorkerApi, task: Task, work: WorkDir, media: Media, cancel: Cancel, reporter: Reporter
) -> dict:
    """예능형 렌더(task-036). 입력은 source만(훅 음성 없음), 산출물은 output_mp4·report."""
    if task.preset_version != VARIETY_PRESET:  # F9
        raise RenderFailed("preset_version 불일치")
    if task.lang != "ko":
        raise RenderFailed("지원하지 않는 언어")
    reporter.set("download", 0)
    inputs = api.inputs(task)
    if "source" not in inputs:
        raise RenderFailed("source 없음")
    source = work.path("source.mp4")
    try:
        src_used = _download(api, task, inputs["source"], source, cancel)
    except TransferError as exc:
        raise RenderFailed(str(exc)) from None
    try:
        source_meta = media.probe(source, cancel)
    except MediaError:
        raise RenderFailed("source를 읽을 수 없음") from None
    if source_meta["demuxer"] != "mov" or not source_meta["has_video"]:
        raise RenderFailed("source 형식 오류")
    project = to_variety_project(task.spec, task.lang, source_meta)  # W6·W3 재검증
    work.path("variety_project.json").write_text(
        json.dumps(project, ensure_ascii=False), encoding="utf-8"
    )
    output = work.path("result_ko.mp4")
    result = render_variety(project, source, source_meta, output, media, cancel, reporter.set)
    report = work.path("report.json")
    report.write_text(
        json.dumps(
            {
                "output": "result_ko.mp4",
                "format": "variety",
                **result,
                "preset_version": VARIETY_PRESET,
                "source_asset_id": str(src_used.asset_id),
                "cut_count": len(project["cuts"]),
                "cuts": [
                    {
                        "out_start": round(c["out_start"], 3),
                        "src_start": round(c["src_start"], 3),
                        "length": round(c["src_end"] - c["src_start"], 3),
                        "frames": c["frames"],
                    }
                    for c in project["cuts"]
                ],
                # W8: 예제 글꼴(Cafe24 Ohsquare·잘난체)은 라이선스 근거 없음 → Pretendard 대체
                "font_substituted": True,
                "review_required": "Watch final video and inspect every cut before delivery.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    reporter.set("upload", 0)
    files = [
        {"kind": "output_mp4", "path": output, "mime": "video/mp4", "duration": result["duration"]},
        {"kind": "report", "path": report, "mime": "application/json"},
    ]
    try:
        ids = _upload_all(api, task, files, reporter, cancel)
    except TransferError as exc:
        raise RenderFailed(str(exc)) from None
    return {"status": "done", "asset_ids": ids}


def _finish(api: WorkerApi, task: Task, body: dict) -> None:
    """W-09. done이 400으로 거부되면(산출물 확인 실패 등) failed로 1회 보고하고 끝낸다
    (리뷰 반영 8)."""
    try:
        api.finish(task, body)
    except ApiCallError as exc:
        if exc.status != 400 or body["status"] != "done":
            raise
        stage, code = (
            ("prepare", "unknown") if task.kind == "prepare" else ("render", "render_failed")
        )
        logger.warning("finish 400: failed로 보고 kind=%s id=%s code=%s", task.kind, task.id, code)
        body.clear()
        body.update({"status": "failed", "error_stage": stage, "error_code": code})
        api.finish(task, body)


def run_task(
    api: WorkerApi,
    task: Task,
    work_root: Path,
    media: Media,
    progress_interval: float,
    tts_cfg: TtsSettings | None = None,
) -> str:
    """task 1건을 처음부터 끝까지 처리한다. 반환: done·failed·cancelled·aborted.
    tts_cfg가 없으면 환경변수 WORKER_TTS_*에서 읽는다(기본 꺼짐)."""
    work = WorkDir(work_root, task.id)
    try:
        work.reset()  # F5: 다시 받은 task는 처음부터
    except OSError as exc:  # 리뷰 반영 7: 폴더 준비 실패는 finish 없이 대기 후 재수령
        logger.error("작업 폴더 준비 실패: id=%s type=%s", task.id, type(exc).__name__)
        return "aborted"
    cancel = Cancel()
    reporter = Reporter(api, task, cancel, progress_interval)
    reporter.start()
    logger.info("제작 task 시작: kind=%s id=%s", task.kind, task.id)
    try:
        try:
            if task.kind == "prepare":
                body = _prepare(api, task, work, media, cancel, reporter)
            else:
                body = _render(api, task, work, media, cancel, reporter, tts_cfg or TtsSettings())
        except TaskFailed as f:
            logger.info(
                "제작 task 실패 보고: kind=%s id=%s stage=%s code=%s (%s)",
                task.kind,
                task.id,
                f.stage,
                f.code,
                f.detail,
            )
            body = {"status": "failed", "error_stage": f.stage, "error_code": f.code}
        except TaskCancelled, ApiCallError:
            raise
        except Exception as exc:  # 예상 못 한 오류: 원문은 로컬 경로를 담을 수 있어 종류만
            cancel.check()
            logger.error(
                "제작 task 예외: kind=%s id=%s type=%s", task.kind, task.id, type(exc).__name__
            )
            stage = "prepare" if task.kind == "prepare" else "render"
            body = {"status": "failed", "error_stage": stage, "error_code": "unknown"}
        reporter.stop()
        cancel.check()
        _finish(api, task, body)
        logger.info("제작 task 종료: kind=%s id=%s status=%s", task.kind, task.id, body["status"])
        return body["status"]
    except TaskCancelled:
        logger.info("제작 task 중단(409): kind=%s id=%s", task.kind, task.id)
        return "cancelled"
    except ApiCallError as exc:
        logger.warning("제작 task API 오류로 중단: kind=%s id=%s %s", task.kind, task.id, exc)
        return "aborted"
    finally:
        reporter.stop()
        cancel.trigger()  # 남은 ffmpeg 정리
        try:
            work.remove()
        except OSError as exc:
            logger.warning("작업 폴더 삭제 실패: id=%s type=%s", task.id, type(exc).__name__)
