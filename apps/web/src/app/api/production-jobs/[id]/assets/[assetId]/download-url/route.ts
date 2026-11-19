import { getProductionDownloadUrl, getProductionJob } from "@/server/api/production";
import { isUuid } from "@/components/monitoring/query";
import { fromApiError, json } from "../../../../_shared";

// PROD-03 MP4 재생·다운로드용 서명 GET URL 중계(A-18). 읽기 전용, 응답으로만 전달한다(저장·로그 없음).

export async function GET(_request: Request, { params }: { params: Promise<{ id: string; assetId: string }> }) {
  const { id, assetId } = await params;
  if (!isUuid(id) || !isUuid(assetId)) return json(400, { code: "VALIDATION", message: "잘못된 id입니다." });
  try {
    // A-18은 자산 kind를 가리지 않으므로, 이 작업의 ready 산출물(MP4·리포트)만 연다.
    const { assets } = await getProductionJob(id);
    if (!assets.some((a) => a.id === assetId && (a.kind === "output_mp4" || a.kind === "report") && a.status === "ready")) {
      return json(404, { code: "NOT_FOUND", message: "파일을 찾을 수 없습니다." });
    }
    const r = await getProductionDownloadUrl(id, assetId);
    return json(200, { url: r.url });
  } catch (e) {
    return fromApiError(e, "파일 주소를 불러오지 못했습니다.");
  }
}
