import { createProductionJob } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { INVALID, fromApiError, isCredit, isLicense, json, readBody, segmentError } from "./_shared";

// PROD-01 작업 생성 중계(A-09 POST). Idempotency-Key는 브라우저가 의도 단위로 만든다.

const KEY = /^[A-Za-z0-9._:-]{8,128}$/;

export async function POST(request: Request) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const key = request.headers.get("idempotency-key") ?? "";
  if (!KEY.test(key)) return json(400, { code: "VALIDATION", message: "요청 키가 올바르지 않습니다." });
  const b = await readBody(request);
  if (!b) return json(400, INVALID);

  const title = typeof b.title === "string" ? b.title.trim() : "";
  if (title.length < 1 || title.length > 200) return json(400, { code: "VALIDATION", message: "제목은 1~200자로 입력하세요.", field: "title" });
  if (b.rights_confirmed !== true) return json(400, { code: "VALIDATION", message: "사용 권한을 확인해야 합니다.", field: "rights_confirmed" });
  if (b.source_kind !== "upload") return json(400, { code: "VALIDATION", message: "원본은 파일 업로드만 지원합니다.", field: "source_kind" });
  if (b.candidate_id !== undefined && !isUuid(b.candidate_id)) return json(400, { code: "VALIDATION", message: "잘못된 후보 id입니다." });
  const seg = segmentError(b.source_start_sec, b.segment_len_sec);
  if (seg) return json(400, { code: "VALIDATION", message: seg, field: "segment_len_sec" });
  if (!isLicense(b.license_cc) || !isCredit(b.credit)) return json(400, INVALID);

  try {
    const job = await createProductionJob(
      {
        title,
        format: "category",
        candidate_id: b.candidate_id as string | undefined,
        source_kind: "upload",
        rights_confirmed: true,
        license_cc: b.license_cc as boolean | null | undefined,
        credit: (b.credit as string | null | undefined) || null,
        source_start_sec: b.source_start_sec as number,
        segment_len_sec: b.segment_len_sec as number,
      },
      key,
    );
    return json(200, { job: { id: job.id, status: job.status } });
  } catch (e) {
    return fromApiError(e, "작업을 만들지 못했습니다.");
  }
}
