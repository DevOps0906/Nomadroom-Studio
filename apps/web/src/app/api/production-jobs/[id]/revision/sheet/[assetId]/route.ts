import { getProductionDownloadUrl, getProductionJob } from "@/server/api/production";
import { isUuid } from "@/components/monitoring/query";
import { fromApiError, json } from "../../../../_shared";

// PROD-02 분석 시트 보기용 서명 GET URL 중계(A-18). 읽기 전용, 응답으로만 전달한다.

export async function GET(_request: Request, { params }: { params: Promise<{ id: string; assetId: string }> }) {
  const { id, assetId } = await params;
  if (!isUuid(id) || !isUuid(assetId)) return json(400, { code: "VALIDATION", message: "잘못된 id입니다." });
  try {
    // A-18은 자산 kind를 가리지 않으므로, 이 작업의 ready sheet 자산(화면이 쓰는 같은 목록)만 연다.
    const { assets } = await getProductionJob(id);
    if (!assets.some((a) => a.id === assetId && a.kind === "sheet" && a.status === "ready")) {
      return json(404, { code: "NOT_FOUND", message: "시트를 찾을 수 없습니다." });
    }
    const r = await getProductionDownloadUrl(id, assetId);
    return json(200, { url: r.url });
  } catch (e) {
    return fromApiError(e, "시트를 불러오지 못했습니다.");
  }
}
