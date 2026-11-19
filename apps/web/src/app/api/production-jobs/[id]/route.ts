import { patchProductionJob, type PatchProductionJob } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { URL_ONLY, isYoutubeUrl } from "@/components/production/api";
import { INVALID, fromApiError, isCredit, isLicense, json, readBody, segmentError } from "../_shared";

// PROD-01 저장 중계(A-09 PATCH). 보낸 필드만 전달한다.

export async function PATCH(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id } = await params;
  if (!isUuid(id)) return json(400, { code: "VALIDATION", message: "잘못된 작업 id입니다." });
  const b = await readBody(request);
  if (!b) return json(400, INVALID);

  const patch: PatchProductionJob = {};
  // task-031: 원본 방식·URL(1차 검사, 보낸 값과 저장 값의 조합 검사는 API)
  if ("source_kind" in b) {
    if (b.source_kind !== "upload" && b.source_kind !== "url") return json(400, { code: "VALIDATION", message: "원본 방식이 올바르지 않습니다.", field: "source_kind" });
    patch.source_kind = b.source_kind;
  }
  if ("source_url" in b) {
    if (b.source_url !== null && !(typeof b.source_url === "string" && isYoutubeUrl(b.source_url))) return json(400, { code: "VALIDATION", message: URL_ONLY, field: "source_url" });
    patch.source_url = typeof b.source_url === "string" ? b.source_url.trim() : null;
  }
  if ("rights_confirmed" in b) {
    if (typeof b.rights_confirmed !== "boolean") return json(400, INVALID);
    patch.rights_confirmed = b.rights_confirmed;
  }
  if ("source_start_sec" in b || "segment_len_sec" in b) {
    const seg = segmentError(b.source_start_sec, b.segment_len_sec);
    if (seg) return json(400, { code: "VALIDATION", message: seg, field: "segment_len_sec" });
    patch.source_start_sec = b.source_start_sec as number;
    patch.segment_len_sec = b.segment_len_sec as number;
  }
  if ("license_cc" in b) {
    if (!isLicense(b.license_cc)) return json(400, INVALID);
    patch.license_cc = b.license_cc as boolean | null;
  }
  if ("credit" in b) {
    if (!isCredit(b.credit)) return json(400, INVALID);
    patch.credit = (b.credit as string | null) || null;
  }
  if (Object.keys(patch).length === 0) return json(400, INVALID);

  try {
    const job = await patchProductionJob(id, patch);
    return json(200, { job: { id: job.id, status: job.status } });
  } catch (e) {
    return fromApiError(e, "저장하지 못했습니다.");
  }
}
