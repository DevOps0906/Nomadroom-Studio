import { NextResponse } from "next/server";
import { ApiError } from "@/server/api/client";

// 제작 작업 중계 Route Handler 공용(브라우저 → 이 핸들러 → (JWT) FastAPI A-09~A-11). 근거: tasks/task-025.md.

export const NO_STORE = { "Cache-Control": "no-store" };

export function json(status: number, body: unknown) {
  return NextResponse.json(body, { status, headers: NO_STORE });
}

export const INVALID = { code: "VALIDATION", message: "잘못된 요청입니다." };

/** 업스트림 오류 → 화면용 응답. 400·409·429는 API 고정 문구(상태 포함)를 그대로, 404는 존재 여부를 숨기는 문구로 바꾼다. */
export function fromApiError(e: unknown, fallback: string) {
  if (e instanceof ApiError) {
    if (e.status === 401) return json(401, { code: "UNAUTHENTICATED", message: e.message });
    if (e.status === 403) return json(403, { code: "FORBIDDEN", message: "이 작업을 바꿀 권한이 없습니다." });
    if (e.status === 404) return json(404, { code: "NOT_FOUND", message: "작업을 찾을 수 없습니다." });
    if (e.status === 400 || e.status === 422) return json(400, { code: "VALIDATION", message: e.message || INVALID.message, field: e.field });
    if (e.status === 409) return json(409, { code: e.code, message: e.message });
    if (e.status === 429) return json(429, { code: e.code, message: e.message });
  }
  return json(502, { code: "INTERNAL", message: fallback });
}

export async function readBody(request: Request): Promise<Record<string, unknown> | null> {
  try {
    const b = (await request.json()) as unknown;
    return typeof b === "object" && b !== null && !Array.isArray(b) ? (b as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** 구간 값 검증(원본 시작 ≥0, 길이 0 초과 180 이하). 실패 시 필드 오류 문구. */
export function segmentError(start: unknown, len: unknown): string | null {
  if (!num(start) || start < 0) return "원본 시작은 0 이상이어야 합니다.";
  if (!num(len) || len <= 0 || len > 180) return "길이는 0 초과 180 이하여야 합니다.";
  return null;
}

export const isLicense = (v: unknown) => v === null || v === undefined || typeof v === "boolean";
export const isCredit = (v: unknown) => v === null || v === undefined || (typeof v === "string" && v.length <= 200);
