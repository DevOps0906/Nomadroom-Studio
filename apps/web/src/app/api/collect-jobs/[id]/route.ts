import { NextResponse } from "next/server";
import { ApiError } from "@/server/api/client";
import { getCollectJob } from "@/server/api/monitor";
import { pickJob } from "@/components/monitoring/job";
import { isUuid } from "@/components/monitoring/query";

// MON-01 진행 폴링 중계: 브라우저 → 이 Route Handler → (JWT) FastAPI A-05 GET. 화면 필드만 돌려준다.
// 근거: tasks/task-013.md#구현 결정(폴링 Route Handler).

const NO_STORE = { "Cache-Control": "no-store" };

function json(status: number, body: unknown) {
  return NextResponse.json(body, { status, headers: NO_STORE });
}

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) return json(400, { code: "VALIDATION", message: "잘못된 작업 id입니다." });
  try {
    const job = pickJob(await getCollectJob(id));
    if (!job) return json(502, { code: "INTERNAL", message: "작업 상태를 해석하지 못했습니다." });
    return json(200, { job });
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401) return json(401, { code: "UNAUTHENTICATED", message: e.message });
      if (e.status === 403 || e.status === 404) return json(e.status, { code: e.code, message: e.message });
    }
    return json(502, { code: "INTERNAL", message: "작업 상태를 불러오지 못했습니다." });
  }
}
