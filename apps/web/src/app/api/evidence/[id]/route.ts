import { NextResponse } from "next/server";
import { ApiError } from "@/server/api/client";
import { getEvidence } from "@/server/api/monitor";
import { pickEvidence } from "@/components/evidence/evidence";
import { isUuid } from "@/components/monitoring/query";

// MON-D2 관측 근거 중계: 브라우저 → 이 Route Handler → (JWT) FastAPI A-06. 화면 필드만, reason 10종 밖은 null.
// 근거: tasks/task-015.md#착수 결정.

const NO_STORE = { "Cache-Control": "no-store" };

function json(status: number, body: unknown) {
  return NextResponse.json(body, { status, headers: NO_STORE });
}

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) return json(400, { code: "VALIDATION", message: "잘못된 후보 id입니다." });
  try {
    const evidence = pickEvidence(await getEvidence(id));
    if (!evidence) return json(502, { code: "INTERNAL", message: "관측 근거를 해석하지 못했습니다." });
    return json(200, { evidence });
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401) return json(401, { code: "UNAUTHENTICATED", message: e.message });
      // upstream 문구를 그대로 내보내지 않는다(타 워크스페이스 존재 여부 노출 방지).
      if (e.status === 404) return json(404, { code: "NOT_FOUND", message: "후보를 찾을 수 없습니다." });
      if (e.status === 403) return json(403, { code: "FORBIDDEN", message: "이 후보를 볼 권한이 없습니다." });
    }
    return json(502, { code: "INTERNAL", message: "관측 근거를 불러오지 못했습니다." });
  }
}
