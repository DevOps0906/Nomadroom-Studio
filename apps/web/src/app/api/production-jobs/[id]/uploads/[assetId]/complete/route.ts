import { completeProductionUpload } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { fromApiError, json } from "../../../../_shared";

// PROD-01 업로드 완료 확인 중계(A-10 complete).

export async function POST(request: Request, { params }: { params: Promise<{ id: string; assetId: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id, assetId } = await params;
  if (!isUuid(id) || !isUuid(assetId)) return json(400, { code: "VALIDATION", message: "잘못된 id입니다." });
  try {
    const a = await completeProductionUpload(id, assetId);
    return json(200, { asset: { id: a.id, status: a.status } });
  } catch (e) {
    return fromApiError(e, "업로드를 확인하지 못했습니다.");
  }
}
