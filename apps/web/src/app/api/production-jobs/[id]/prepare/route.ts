import { prepareProductionJob } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { fromApiError, json } from "../../_shared";

// PROD-01 원본 준비 시작·재시도 중계(A-11).

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id } = await params;
  if (!isUuid(id)) return json(400, { code: "VALIDATION", message: "잘못된 작업 id입니다." });
  try {
    const job = await prepareProductionJob(id);
    return json(202, { job: { id: job.id, status: job.status } });
  } catch (e) {
    return fromApiError(e, "원본 준비를 시작하지 못했습니다.");
  }
}
