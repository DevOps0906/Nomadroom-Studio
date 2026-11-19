import { retryProductionRender } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { fromApiError, json } from "../../../../_shared";

// PROD-03 실패 렌더 재시도 중계(A-16).

export async function POST(request: Request, { params }: { params: Promise<{ id: string; runId: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id, runId } = await params;
  if (!isUuid(id) || !isUuid(runId)) return json(400, { code: "VALIDATION", message: "잘못된 id입니다." });
  try {
    const run = await retryProductionRender(id, runId);
    return json(202, { run: { id: run.id, status: run.status, attempt: run.attempt } });
  } catch (e) {
    return fromApiError(e, "재시도를 시작하지 못했습니다.");
  }
}
