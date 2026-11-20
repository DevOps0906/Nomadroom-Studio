import { getProductionDownloadUrl, listGenerationRuns } from "@/server/api/production";
import { json } from "../../../../_shared";
import { fromGenerationError, guard } from "../../_generation";

// PROD-01S 생성 결과 영상·입력 사진 보기용 서명 GET 주소 중계(A-18). 이 작업의 run이 가리키는 자산만 연다. 응답으로만 전달(저장·로그 없음).

export async function GET(request: Request, { params }: { params: Promise<{ id: string; runId: string }> }) {
  const g = await guard(request, params);
  if (g.error) return g.error;
  const which = new URL(request.url).searchParams.get("which");
  if (which !== "result" && which !== "source") return json(400, { code: "VALIDATION", message: "보기 대상이 올바르지 않습니다." });
  try {
    const run = (await listGenerationRuns(g.id)).items.find((r) => r.id === g.runId);
    const assetId = which === "result" ? (run?.status === "done" ? run.result_asset_id : null) : run?.source_asset_id;
    if (!assetId) return json(404, { code: "NOT_FOUND", message: "파일을 찾을 수 없습니다." });
    const r = await getProductionDownloadUrl(g.id, assetId);
    return json(200, { url: r.url });
  } catch (e) {
    return fromGenerationError(e, "파일 주소를 불러오지 못했습니다.");
  }
}
