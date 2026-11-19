import { deleteProductionAsset } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { fromApiError, json } from "../../../_shared";

// PROD-01S·02S 자산 삭제 중계(A-10 DELETE, task-044 P9). 참조 중인 자산·준비 시작 뒤 원본은 API가 409로 거절한다.

export async function DELETE(request: Request, { params }: { params: Promise<{ id: string; assetId: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id, assetId } = await params;
  if (!isUuid(id) || !isUuid(assetId)) return json(400, { code: "VALIDATION", message: "잘못된 id입니다." });
  try {
    await deleteProductionAsset(id, assetId);
    return json(200, { ok: true });
  } catch (e) {
    return fromApiError(e, "파일을 지우지 못했습니다.");
  }
}
