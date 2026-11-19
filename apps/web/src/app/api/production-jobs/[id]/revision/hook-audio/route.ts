import { requestProductionUpload } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { INVALID, fromApiError, json, readBody } from "../../../_shared";

// PROD-02 훅 음성 업로드 서명 발급 중계(A-10 kind=hook_audio). 완료 확인은 uploads/{assetId}/complete를 쓴다.
// upload_url은 응답으로만 전달하고 저장·로그하지 않는다.

const MAX_BYTES = 50 * 1024 * 1024;

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id } = await params;
  if (!isUuid(id)) return json(400, { code: "VALIDATION", message: "잘못된 작업 id입니다." });
  const b = await readBody(request);
  if (!b) return json(400, INVALID);
  const size = b.size_bytes;
  if (typeof b.mime !== "string" || !b.mime || b.mime.length > 100) return json(400, INVALID);
  if (typeof size !== "number" || !Number.isInteger(size) || size <= 0 || size > MAX_BYTES) {
    return json(400, { code: "VALIDATION", message: "음성 파일은 50MB 이하여야 합니다.", field: "file" });
  }
  try {
    const t = await requestProductionUpload(id, { kind: "hook_audio", size_bytes: size, mime: b.mime });
    return json(200, { asset: { id: t.asset.id }, upload_url: t.upload_url, expires_at: t.expires_at });
  } catch (e) {
    return fromApiError(e, "업로드를 준비하지 못했습니다.");
  }
}
