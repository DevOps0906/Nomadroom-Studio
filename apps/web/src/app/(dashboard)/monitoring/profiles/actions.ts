"use server";

import { redirect } from "next/navigation";
import { ApiError, SESSION_EXPIRED_PATH, classifyApiError } from "@/server/api/client";
import { setProfileSelection, updateProfile } from "@/server/api/profiles";
import {
  MAX_SELECTED,
  SAVE_FAILED_MESSAGE,
  toSaveResult,
  validateConditions,
  type ConditionsInput,
  type SaveResult,
} from "@/components/profiles/conditions";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

/** 클라이언트에서 온 값은 신뢰하지 않는다: 모양을 다시 맞춘 뒤 같은 규칙으로 검증. */
function readInput(raw: unknown): ConditionsInput {
  const r = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>) : {};
  return {
    market: str(r.market),
    format: str(r.format),
    category: str(r.category),
    min_views: str(r.min_views),
    max_growth_pct: str(r.max_growth_pct),
    keywords: str(r.keywords),
    cc_only: r.cc_only === true,
    include_broadcast: r.include_broadcast === true,
  };
}

function fail(e: unknown): SaveResult {
  // API만 401이면 /login 대신 세션 정리 경로로(루프 방지). 근거: client.ts SESSION_EXPIRED_PATH.
  if (classifyApiError(e) === "login") redirect(SESSION_EXPIRED_PATH);
  if (e instanceof ApiError) return toSaveResult(e);
  return { ok: false, kind: "error", message: SAVE_FAILED_MESSAGE };
}

/** MON-D1 조건 저장(A-03 PUT /v1/profiles/{id}). */
export async function saveConditions(id: unknown, updatedAt: unknown, raw: unknown): Promise<SaveResult> {
  if (typeof id !== "string" || !UUID_RE.test(id) || typeof updatedAt !== "string") {
    return { ok: false, kind: "error", message: SAVE_FAILED_MESSAGE };
  }
  const { payload, errors } = validateConditions(readInput(raw), updatedAt);
  if (!payload) return { ok: false, kind: "field", errors };
  try {
    await updateProfile(id, payload);
  } catch (e) {
    return fail(e);
  }
  return { ok: true };
}

/** 검증 대상 선택(A-03 PUT /v1/profiles/selection, 최대 3). */
export async function saveSelection(ids: unknown): Promise<SaveResult> {
  if (!Array.isArray(ids) || !ids.every((x) => typeof x === "string" && UUID_RE.test(x))) {
    return { ok: false, kind: "error", message: SAVE_FAILED_MESSAGE };
  }
  const unique = [...new Set(ids as string[])];
  if (unique.length > MAX_SELECTED) {
    return { ok: false, kind: "error", message: `프로필은 최대 ${MAX_SELECTED}개까지 선택할 수 있습니다.` };
  }
  try {
    await setProfileSelection(unique);
  } catch (e) {
    return fail(e);
  }
  return { ok: true };
}
