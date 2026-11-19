import { requestProductionUpload, type UploadKind } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { INVALID, fromApiError, json, readBody } from "../../_shared";
import { parseRights } from "../../_shopping";

// PROD-01·01S·02S 업로드 서명 발급 중계(A-10). 일반은 source_upload, 쇼핑은 image·bgm·narration과 자산별 rights.
// upload_url은 응답으로만 전달하고 저장·로그하지 않는다.

const MiB = 1024 * 1024;
const MAX_BYTES: Record<string, number> = { source_upload: 500 * MiB, image: 20 * MiB, bgm: 50 * MiB, narration: 50 * MiB };
const KINDS = Object.keys(MAX_BYTES);

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id } = await params;
  if (!isUuid(id)) return json(400, { code: "VALIDATION", message: "잘못된 작업 id입니다." });
  const b = await readBody(request);
  if (!b) return json(400, INVALID);
  const size = b.size_bytes;
  if (typeof b.kind !== "string" || !KINDS.includes(b.kind) || typeof b.mime !== "string" || !b.mime || b.mime.length > 100) return json(400, INVALID);
  const kind = b.kind as UploadKind;
  const max = MAX_BYTES[kind]!;
  if (typeof size !== "number" || !Number.isInteger(size) || size <= 0 || size > max) {
    return json(400, { code: "VALIDATION", message: "파일 크기는 " + max / MiB + "MB 이하여야 합니다.", field: "file" });
  }
  let rights;
  if (b.rights !== undefined) {
    const r = parseRights(b.rights);
    if (!r.ok) return json(400, { code: "VALIDATION", message: r.message, field: r.field });
    rights = r.value;
  }
  try {
    const t = await requestProductionUpload(id, { kind, size_bytes: size, mime: b.mime, ...(rights ? { rights } : {}) });
    return json(200, { asset: { id: t.asset.id }, upload_url: t.upload_url, expires_at: t.expires_at });
  } catch (e) {
    return fromApiError(e, "업로드를 준비하지 못했습니다.");
  }
}
