"""AI 초안 A-14 `POST /v1/production-jobs/{id}/ai-draft`. 근거: docs/04_API.md#A-14,
tasks/task-029.md#착수-결정 H1~H8, supabase/migrations/20261119000018_production_ai_draft.sql,
예능형 분기 tasks/task-040.md#착수-결정 A1~A5(000022: variety·ko만 예약),
쇼핑 분기 tasks/task-048.md#착수-결정 S1~S6(000025: shopping·ko 예약, 3안은 요청 기록에 저장).

순서: 키 확인(없으면 503, 계수 없음) → reserve_ai_draft(잠금·상태·형식·상한·60초·멱등, 횟수+1, 커밋)
→ 잠금 없이 입력 수집·Claude 호출(형식 불일치·오류는 1회 재시도) → create_ai_draft_revision
(항상 새 rev_no, origin=ai_draft). 실패는 fail_ai_draft로 기록하고 502(고정 문구).
초안은 승인하지 않는다(승인은 A-13 사람만).
"""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel

from app.auth.user import CurrentUser, get_current_user
from app.errors import ApiError, db_error
from app.production import ai_draft, ai_draft_shopping, ai_draft_variety, runs
from app.production.validation_variety import MAX_TEXT_CHARS
from app.routes.production_jobs import (
    RevisionOut,
    _get_job,
    _rejected,
    _rows,
    _shopping_assets,
    _source_duration,
    _source_size,
    _validate,
)
from app.routes.profiles import _send
from app.routes.verify_runs import _KEY_RE

logger = logging.getLogger("nomadroom.production_ai")

router = APIRouter(prefix="/v1/production-jobs", tags=["production-jobs"])

MAX_ANALYSIS_BYTES = 50 * 1024 * 1024  # W-07 analysis 상한과 같은 값
ATTEMPTS = 2  # 첫 호출 + 재시도 1회(H4)
MAX_TITLE_CHARS = MAX_TEXT_CHARS  # 후보 제목 프롬프트 상한(자막 문구 상한과 같은 값)


class ShoppingVariantOut(BaseModel):
    hook_type: str
    sentences: list[str]
    char_count: int  # 서버가 센 공백 포함 글자 수 합([확인 필요] 표기 제외)


class AiDraftOut(BaseModel):
    revision: RevisionOut
    ai_draft_count: int
    previous_rev_no: int | None
    replay: bool  # 같은 키 재요청(200)이면 true. 웹 중계가 상태 코드를 그대로 옮기는 데 쓴다
    # 쇼핑(task-048 S5): 대본 3안·확인할 사실. spec 밖(요청 기록)에 저장, replay 때도 같은 값
    variants: list[ShoppingVariantOut] | None = None
    facts_to_check: list[str] | None = None


async def _fail(request: Request, ids: dict) -> None:
    """실패 기록(정리용). 여기서 난 오류는 로그(예외 이름만)로 남기고 원래 오류를 살린다."""
    try:
        await _rpc(request, "fail_ai_draft", ids)
    except Exception as exc:  # noqa: BLE001 - 정리 실패가 원래 오류를 가리면 안 된다
        logger.warning("AI 초안 실패 기록 실패: job=%s err=%s", ids["p_job"], type(exc).__name__)


async def _rpc(request: Request, name: str, payload: dict) -> Any:
    """000018 RPC. NR016~018은 여기서, 나머지 NR 코드는 runs._map으로 옮긴다."""
    path = f"rpc/{name}"
    resp = await _send(request, "POST", path, json=payload)
    if 400 <= resp.status_code < 500:
        code, message = runs._error_body(resp)
        if code == "NR016":
            raise ApiError(429, "QUOTA_EXCEEDED", "이 작업의 AI 초안 횟수를 모두 썼습니다.")
        if code == "NR017":
            raise ApiError(
                429, "RATE_LIMITED", "AI 초안을 너무 자주 요청했습니다. 잠시 후 다시 시도하세요."
            )
        if code == "NR018":
            raise ApiError(409, "CONFLICT", "같은 요청을 처리 중입니다.", "Idempotency-Key")
        err = runs._map(code, message, "Idempotency-Key")
        if err is not None:
            raise err
    if resp.status_code >= 400:
        logger.warning("데이터 저장소 오류 %s: POST %s", resp.status_code, path)
        raise db_error()
    if not resp.content:  # void 함수(fail_ai_draft)는 본문 없음(204)
        return None
    try:
        return resp.json()
    except ValueError as exc:
        raise db_error() from exc


def _out(result: Any) -> AiDraftOut:
    if not isinstance(result, dict) or not isinstance(result.get("revision"), dict):
        raise db_error()
    return AiDraftOut(
        revision=RevisionOut.model_validate(result["revision"]),
        ai_draft_count=result["ai_draft_count"],
        previous_rev_no=result.get("previous_rev_no"),
        replay=bool(result.get("replay")),
        variants=result.get("variants"),
        facts_to_check=result.get("facts_to_check"),
    )


def _asset_filter(ws: uuid.UUID, job: dict) -> dict[str, str]:
    return {"job_id": f"eq.{job['id']}", "workspace_id": f"eq.{ws}", "status": "eq.ready"}


async def _sheets(request: Request, ws: uuid.UUID, job: dict) -> list[tuple[int, bytes]]:
    """ready 시트(JPEG, 상한 장수) — (순번 0부터, 바이트). 경로에 페이지가 없으므로
    created_at·id 순번을 페이지로 본다(워커가 W-07을 시트마다 순서대로 호출하는 전제)."""
    state = request.app.state
    settings = state.settings
    sheet_rows = await _rows(
        request,
        "GET",
        "production_assets",
        params={
            **_asset_filter(ws, job),
            "select": "storage_path,mime",
            "kind": "eq.sheet",
            "order": "created_at.asc,id.asc",
            "limit": str(settings.ai_draft_max_sheets),
        },
    )
    sheets: list[tuple[int, bytes]] = []
    for idx, row in enumerate(sheet_rows):
        if row.get("mime") != ai_draft.SHEET_MIME:
            continue
        data = await ai_draft.download(
            state.http, settings, row["storage_path"], ai_draft.MAX_SHEET_BYTES
        )
        if ai_draft.is_jpeg(data):
            sheets.append((idx, data))
    return sheets


async def _inputs(request: Request, ws: uuid.UUID, job: dict) -> tuple[list[bytes], bytes | None]:
    """ready 시트(JPEG, 상한 장수)와 최신 ready analysis. 자산은 작업·워크스페이스 조건으로만."""
    state = request.app.state
    sheets = [data for _, data in await _sheets(request, ws, job)]
    analysis_rows = await _rows(
        request,
        "GET",
        "production_assets",
        params={
            **_asset_filter(ws, job),
            "select": "storage_path",
            "kind": "eq.analysis",
            "order": "created_at.desc",
            "limit": "1",
        },
    )
    analysis = None
    if analysis_rows:
        analysis = await ai_draft.download(
            state.http, state.settings, analysis_rows[0]["storage_path"], MAX_ANALYSIS_BYTES
        )
    return sheets, analysis


async def _candidate_title(request: Request, ws: uuid.UUID, job: dict) -> str | None:
    if not job.get("candidate_id"):
        return None
    rows = await _rows(
        request,
        "GET",
        "candidates",
        params={
            "select": "title",
            "id": f"eq.{job['candidate_id']}",
            "workspace_id": f"eq.{ws}",
        },
    )
    title = rows[0].get("title") if rows else None
    # 리뷰 반영 3: 비신뢰 텍스트 길이 상한(카테고리형·예능형 공통)
    return title[:MAX_TITLE_CHARS] if isinstance(title, str) else None


async def _base_spec(request: Request, ws: uuid.UUID, job: dict) -> dict | None:
    if not job.get("current_revision_id"):
        return None
    rows = await _rows(
        request,
        "GET",
        "edit_revisions",
        params={
            "select": "spec",
            "id": f"eq.{job['current_revision_id']}",
            "job_id": f"eq.{job['id']}",
            "workspace_id": f"eq.{ws}",
        },
    )
    spec = rows[0].get("spec") if rows else None
    return spec if isinstance(spec, dict) else None


async def _draft(request: Request, ws: uuid.UUID, job: dict) -> tuple[dict, dict]:
    """입력 수집 → Claude(최대 2회) → (spec, validation). 실패는 DraftFailed."""
    settings = request.app.state.settings
    sheets, analysis = await _inputs(request, ws, job)
    source_duration = await _source_duration(request, ws, job["id"])
    max_duration = 180.0 if source_duration is None else min(180.0, source_duration)
    content = ai_draft.build_content(
        sheets,
        ai_draft.analysis_text(analysis),
        await _candidate_title(request, ws, job),
        max_duration,
    )
    base_spec = await _base_spec(request, ws, job)
    reason = "schema"
    for _ in range(ATTEMPTS):
        try:
            out = await ai_draft.call_claude(settings, content)
        except ai_draft.DraftFailed as exc:
            reason = str(exc)
            continue
        spec = ai_draft.assemble_spec(out, job, base_spec, settings)
        if spec is None:
            reason = "limit"
            continue
        validation = _validate(spec, job, source_duration)
        if _rejected(validation):
            reason = "schema"
            continue
        return spec, validation
    raise ai_draft.DraftFailed(reason)


async def _draft_variety(request: Request, ws: uuid.UUID, job: dict) -> tuple[dict, dict]:
    """예능형(task-040): 사용자 대사·시트·후보 제목 → Claude(최대 2회) → (spec, validation).
    analysis·원본·음성은 읽지 않는다. 실패는 DraftFailed."""
    settings = request.app.state.settings
    sheets = await _sheets(request, ws, job)
    source_duration = await _source_duration(request, ws, job["id"])
    segment_len = float(job["segment_len_sec"]) if job.get("segment_len_sec") is not None else None
    if segment_len is not None and source_duration is not None:
        segment_len = min(segment_len, source_duration)
    lines = ai_draft_variety.dialogue(await _base_spec(request, ws, job))
    content = ai_draft_variety.build_content(
        sheets, lines, await _candidate_title(request, ws, job), segment_len, _source_size(job)
    )
    tool = ai_draft_variety.tool_schema(with_subtitles=bool(lines))
    reason = "schema"
    for _ in range(ATTEMPTS):
        try:
            out = await ai_draft.call_claude(
                settings, content, system=ai_draft_variety.SYSTEM_PROMPT, tool=tool
            )
        except ai_draft.DraftFailed as exc:
            reason = str(exc)
            continue
        assembled = ai_draft_variety.assemble_spec(out, job, lines)
        if assembled is None:
            reason = "limit"
            continue
        spec, notes = assembled
        validation = _validate(spec, job, source_duration)
        if _rejected(validation):
            reason = "schema"
            continue
        validation["warnings"].extend(notes)  # 사용자 자막 폴백 메모(리뷰 반영 2)
        return spec, validation
    raise ai_draft.DraftFailed(reason)


async def _draft_shopping(request: Request, ws: uuid.UUID, job: dict) -> tuple[dict, dict, dict]:
    """쇼핑(task-048): brief·target·comment_keyword·vertical → Claude(최대 2회) → 3안 검증 →
    직전 spec의 script만 1안으로 교체 → (spec, validation, {variants, facts_to_check}).
    이미지·시트·analysis·원본·음성은 읽지 않는다. 실패는 DraftFailed."""
    settings = request.app.state.settings
    base_spec = await _base_spec(request, ws, job)
    if base_spec is None:
        raise ai_draft.DraftFailed("no_base")
    assets = await _shopping_assets(request, ws, job["id"])
    content = ai_draft_shopping.build_content(job)
    tool = ai_draft_shopping.tool_schema()
    reason = "schema"
    for _ in range(ATTEMPTS):
        try:
            out = await ai_draft.call_claude(
                settings, content, system=ai_draft_shopping.SYSTEM_PROMPT, tool=tool
            )
        except ai_draft.DraftFailed as exc:
            reason = str(exc)
            continue
        draft = ai_draft_shopping.parse(out, job)
        if draft is None:
            reason = "schema"
            continue
        spec, notes = ai_draft_shopping.assemble_spec(draft, base_spec)
        validation = _validate(spec, job, None, assets)
        if _rejected(validation):
            reason = "schema"
            continue
        validation["warnings"].extend(notes)  # 문장별 녹음 안내(S5)
        return spec, validation, draft
    raise ai_draft.DraftFailed(reason)


@router.post("/{job_id}/ai-draft", response_model=AiDraftOut, status_code=201)
async def create_ai_draft(
    job_id: uuid.UUID,
    request: Request,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    user: CurrentUser = Depends(get_current_user),
) -> AiDraftOut:
    if idempotency_key is None or not _KEY_RE.fullmatch(idempotency_key):
        raise ApiError(400, "VALIDATION", "Idempotency-Key 헤더가 필요합니다.", "Idempotency-Key")
    if request.app.state.settings.anthropic_api_key is None:
        raise ai_draft.not_configured()  # H6: 키 없으면 503(호출·계수 없음)
    ws = user.workspace_id
    job = await _get_job(
        request,
        ws,
        job_id,
        "id,status,format,lang,source_start_sec,segment_len_sec,preset_version,source_meta,"
        "candidate_id,current_revision_id,vertical,brief,comment_keyword",
    )
    ids = {"p_workspace": str(ws), "p_job": str(job_id), "p_key": idempotency_key}
    reserved = await _rpc(
        request,
        "reserve_ai_draft",
        {
            **ids,
            "p_user": str(user.user_id),
            "p_limit": request.app.state.settings.ai_draft_max_per_job,
        },
    )
    if not isinstance(reserved, dict):
        raise db_error()
    if reserved.get("replay"):
        response.status_code = 200
        if reserved.get("request_status") != "done":
            raise ai_draft.upstream_failed()
        return _out(reserved)

    extra: dict[str, Any] = {}
    try:
        if job["format"] == "shopping":
            spec, validation, draft = await _draft_shopping(request, ws, job)
            extra = {"p_variants": draft["variants"], "p_facts": draft["facts_to_check"]}
        else:
            make = _draft_variety if job["format"] == "variety" else _draft
            spec, validation = await make(request, ws, job)
    except ai_draft.DraftFailed as exc:
        await _fail(request, ids)
        logger.warning("AI 초안 실패: job=%s reason=%s", job_id, exc)
        raise ai_draft.upstream_failed() from None
    except Exception:
        await _fail(request, ids)
        raise
    try:
        created = await _rpc(
            request,
            "create_ai_draft_revision",
            {
                **ids,
                "p_user": str(user.user_id),
                "p_spec": spec,
                "p_validation": validation,
                **extra,
            },
        )
    except ApiError:
        # 호출 사이에 상태가 바뀐 경우 등: 요청을 pending으로 남기지 않는다
        await _fail(request, ids)
        raise
    out = _out(created)
    logger.info(
        "AI 초안 생성: job=%s rev=%s count=%s errors=%d",
        job_id,
        out.revision.rev_no,
        out.ai_draft_count,
        len(validation["errors"]),
    )
    return out
