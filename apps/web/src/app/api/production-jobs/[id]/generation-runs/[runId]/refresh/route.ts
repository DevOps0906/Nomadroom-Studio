import { refreshGenerationRun } from "@/server/api/production";
import { json } from "../../../../_shared";
import { envelope, fromGenerationError, guard } from "../../_generation";

// PROD-01S AI 영상 생성 진행 확인 중계(A-22). 수동 버튼에서만 호출된다(자동 폴링 없음).

export async function POST(request: Request, { params }: { params: Promise<{ id: string; runId: string }> }) {
  const g = await guard(request, params);
  if (g.error) return g.error;
  try {
    return json(200, envelope(await refreshGenerationRun(g.id, g.runId!)));
  } catch (e) {
    return fromGenerationError(e, "진행 상태를 확인하지 못했습니다. 잠시 후 다시 시도하세요.");
  }
}
