import { confirmGenerationRun } from "@/server/api/production";
import { json } from "../../../../_shared";
import { envelope, fromGenerationError, guard } from "../../_generation";

// PROD-01S AI 영상 생성 확인 중계(A-22). owner 확인은 API가 강제한다(403). 이 호출에서 과금이 계상된다.

export async function POST(request: Request, { params }: { params: Promise<{ id: string; runId: string }> }) {
  const g = await guard(request, params);
  if (g.error) return g.error;
  try {
    const r = await confirmGenerationRun(g.id, g.runId!);
    return json(r.replay ? 200 : 202, envelope(r));
  } catch (e) {
    return fromGenerationError(e, "생성 확인을 처리하지 못했습니다. 진행 상태를 확인하세요.");
  }
}
