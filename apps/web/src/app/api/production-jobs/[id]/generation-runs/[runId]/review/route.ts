import { reviewGenerationRun } from "@/server/api/production";
import { json, readBody } from "../../../../_shared";
import { fromGenerationError, guard } from "../../_generation";

// PROD-01S AI 영상 생성 검수 중계(A-22). 3항목이 모두 true일 때만 API가 reviewed=true로 기록한다.

export async function POST(request: Request, { params }: { params: Promise<{ id: string; runId: string }> }) {
  const g = await guard(request, params);
  if (g.error) return g.error;
  const b = await readBody(request);
  if (!b || typeof b.physics !== "boolean" || typeof b.angle !== "boolean" || typeof b.compare !== "boolean") return json(400, { code: "VALIDATION", message: "검수 3항목 값이 필요합니다." });
  try {
    const r = await reviewGenerationRun(g.id, g.runId!, { physics: b.physics, angle: b.angle, compare: b.compare });
    return json(200, { run_id: r.run.id, reviewed: r.reviewed });
  } catch (e) {
    return fromGenerationError(e, "검수를 저장하지 못했습니다. 잠시 후 다시 시도하세요.");
  }
}
