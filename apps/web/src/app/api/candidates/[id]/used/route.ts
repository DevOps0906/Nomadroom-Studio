import { NextResponse } from "next/server";
import { ApiError } from "@/server/api/client";
import { setUsed } from "@/server/api/monitor";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";

// MON-01 "사용한 소재" 표시/해제 중계: 브라우저 → 이 Route Handler → (JWT) FastAPI A-08.
// 근거: tasks/task-017.md#착수 결정.

const NO_STORE = { "Cache-Control": "no-store" };

function json(status: number, body: unknown) {
  return NextResponse.json(body, { status, headers: NO_STORE });
}

const INVALID = { code: "VALIDATION", message: "잘못된 요청입니다." };

export async function PATCH(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id } = await params;
  if (!isUuid(id)) return json(400, { code: "VALIDATION", message: "잘못된 후보 id입니다." });
  let used: unknown;
  try {
    used = ((await request.json()) as { used?: unknown } | null)?.used;
  } catch {
    return json(400, INVALID);
  }
  if (typeof used !== "boolean") return json(400, INVALID);
  try {
    const r = await setUsed(id, used);
    return json(200, { id: r.id, used: r.used, used_at: r.used_at });
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 400 || e.status === 422) return json(400, INVALID);
      if (e.status === 401) return json(401, { code: "UNAUTHENTICATED", message: e.message });
      // upstream 문구를 그대로 내보내지 않는다(타 워크스페이스 존재 여부 노출 방지).
      if (e.status === 404) return json(404, { code: "NOT_FOUND", message: "후보를 찾을 수 없습니다." });
      if (e.status === 403) return json(403, { code: "FORBIDDEN", message: "이 후보를 바꿀 권한이 없습니다." });
    }
    return json(502, { code: "INTERNAL", message: "사용 표시를 바꾸지 못했습니다." });
  }
}
