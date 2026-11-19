import { approveProductionReview } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { fromApiError, json } from "../../../_shared";

// PROD-03 검수 승인 중계(A-17, inspect → done).

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id } = await params;
  if (!isUuid(id)) return json(400, { code: "VALIDATION", message: "잘못된 작업 id입니다." });
  try {
    const job = await approveProductionReview(id);
    return json(200, { job: { id: job.id, status: job.status } });
  } catch (e) {
    return fromApiError(e, "검수 승인을 하지 못했습니다.");
  }
}
