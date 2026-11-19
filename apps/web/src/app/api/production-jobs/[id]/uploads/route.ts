import { requestProductionUpload } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { INVALID, fromApiError, json, readBody } from "../../_shared";

// PROD-01 원본 업로드 서명 발급 중계(A-10). W4는 source_upload만. upload_url은 응답으로만 전달하고 저장·로그하지 않는다.

const MAX_BYTES = 500 * 1024 * 1024;

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id } = await params;
  if (!isUuid(id)) return json(400, { code: "VALIDATION", message: "잘못된 작업 id입니다." });
  const b = await readBody(request);
  if (!b) return json(400, INVALID);
  const size = b.size_bytes;
  if (b.kind !== "source_upload" || typeof b.mime !== "string" || !b.mime || b.mime.length > 100) return json(400, INVALID);
  if (typeof size !== "number" || !Number.isInteger(size) || size <= 0 || size > MAX_BYTES) {
    return json(400, { code: "VALIDATION", message: "파일 크기는 500MB 이하여야 합니다.", field: "file" });
  }
  try {
    const t = await requestProductionUpload(id, { kind: "source_upload", size_bytes: size, mime: b.mime });
    return json(200, { asset: { id: t.asset.id }, upload_url: t.upload_url, expires_at: t.expires_at });
  } catch (e) {
    return fromApiError(e, "업로드를 준비하지 못했습니다.");
  }
}
