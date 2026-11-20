import { ApiError } from "@/server/api/client";
import type { GenerationEnvelope, GenerationRun } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { fromApiError, json } from "../../_shared";

// PROD-01S AI 영상 생성 중계 공용(A-22). 프롬프트·URL은 로그에 남기지 않는다. 업스트림 사유는 고정 문구로 바꾼다.

export const KEY = /^[A-Za-z0-9._:-]{8,128}$/;

/** 오류 매핑: 403(owner만 확인)·409(예산 field 포함)·503(서비스 꺼짐)을 구분해 전달하고 나머지는 공용 규칙. */
export function fromGenerationError(e: unknown, fallback: string) {
  if (e instanceof ApiError) {
    if (e.status === 403 && e.code === "FORBIDDEN") return json(403, { code: "FORBIDDEN", message: "AI 영상 생성 확인(과금)은 워크스페이스 소유자만 할 수 있습니다." });
    if (e.status === 409) return json(409, { code: e.code, message: e.message, field: e.field });
    if (e.status === 503) return json(503, { code: "UNAVAILABLE", message: "AI 영상 생성은 사용 안 함 상태입니다. 사진 모션을 쓰세요." });
    if (e.status === 502) return json(502, { code: "INTERNAL", message: "영상 생성 서비스 응답에 문제가 있습니다. 잠시 후 상태를 다시 확인하세요." });
  }
  return fromApiError(e, fallback);
}

/** 같은 출처·UUID 검사. 통과하면 id(들), 아니면 error 응답. */
export async function guard(request: Request, params: Promise<{ id: string; runId?: string }>) {
  // 읽기(GET)는 같은 출처 요청에 Origin이 없으므로 검사하지 않는다(인증은 세션 쿠키).
  const denied = request.method === "GET" ? null : assertSameOrigin(request);
  if (denied) return { error: denied } as const;
  const { id, runId } = await params;
  if (!isUuid(id) || (runId !== undefined && !isUuid(runId))) return { error: json(400, { code: "VALIDATION", message: "잘못된 id입니다." }) } as const;
  return { error: null, id, runId } as const;
}

/** 브라우저로 내보내는 필드만(플랫폼 요청 ID 등은 넘기지 않는다). */
export function pickRun(x: GenerationRun) {
  return {
    id: x.id, job_id: x.job_id, source_asset_id: x.source_asset_id, result_asset_id: x.result_asset_id, cut_ref: x.cut_ref, prompt: x.prompt, duration_sec: x.duration_sec,
    est_cost_krw: x.est_cost_krw, actual_cost_krw: x.actual_cost_krw, status: x.status, error_code: x.error_code, created_at: x.created_at, confirmed_at: x.confirmed_at, finished_at: x.finished_at,
  };
}

export const envelope = (r: GenerationEnvelope) => ({ run: pickRun(r.run), budget: r.budget ?? null, replay: !!r.replay });
