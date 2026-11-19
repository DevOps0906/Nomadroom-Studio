import { ApiError } from "@/server/api/client";
import { fromApiError, json } from "../../_shared";

// PROD-02 편집안 중계 공용. 400 VALIDATION이면 서버 검증 목록(코드·경로·문구)을 그대로 전달한다(입력 값 없음).

const MAX_ISSUES = 200;

export function fromRevisionError(e: unknown, fallback: string) {
  if (e instanceof ApiError && e.status === 400 && e.errors) {
    return json(400, {
      code: "VALIDATION",
      message: e.message,
      field: e.field,
      errors: e.errors.slice(0, MAX_ISSUES),
      warnings: (e.warnings ?? []).slice(0, MAX_ISSUES),
    });
  }
  return fromApiError(e, fallback);
}
