import { createProductionJob } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { URL_ONLY, isYoutubeUrl } from "@/components/production/api";
import { INVALID, fromApiError, isCredit, isLicense, json, readBody, segmentError } from "./_shared";
import { isVertical, parseShoppingFields } from "./_shopping";

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
  // 쇼핑(task-046): 권리는 자산마다 입력하므로 작업 단위 rights_confirmed는 true를 강제하지 않는다(서버 기록 오인 방지로 false 전송).
  const shopping = b.kind === "shopping";
  if (b.kind !== undefined && b.kind !== "general" && !shopping) return json(400, { code: "VALIDATION", message: "유형이 올바르지 않습니다.", field: "kind" });
  if (shopping ? typeof b.rights_confirmed !== "boolean" : b.rights_confirmed !== true)
    return json(400, { code: "VALIDATION", message: "사용 권한을 확인해야 합니다.", field: "rights_confirmed" });
  if (shopping && b.source_kind !== "upload") return json(400, { code: "VALIDATION", message: "쇼핑은 파일 업로드 원본만 쓸 수 있습니다.", field: "source_kind" });
  if (b.source_kind !== "upload" && b.source_kind !== "url") return json(400, { code: "VALIDATION", message: "원본 방식이 올바르지 않습니다.", field: "source_kind" });
  // task-031: URL 원본은 YouTube https만(1차 검사, 정본은 API url_guard). 업로드면 URL 없음.
  if (b.source_kind === "url" ? !(typeof b.source_url === "string" && isYoutubeUrl(b.source_url)) : b.source_url !== undefined && b.source_url !== null)
    return json(400, { code: "VALIDATION", message: URL_ONLY, field: "source_url" });
  if (b.candidate_id !== undefined && !isUuid(b.candidate_id)) return json(400, { code: "VALIDATION", message: "잘못된 후보 id입니다." });
  if (b.format !== undefined && b.format !== "category" && b.format !== "variety" && b.format !== "shopping")
    return json(400, { code: "VALIDATION", message: "형식이 올바르지 않습니다.", field: "format" });
  if (shopping !== (b.format === "shopping")) return json(400, { code: "VALIDATION", message: "유형과 형식이 맞지 않습니다.", field: "format" });
  let extra: Record<string, unknown> = {};
  if (shopping) {
    if (!isVertical(b.vertical)) return json(400, { code: "VALIDATION", message: "분야를 선택하세요.", field: "vertical" });
    if (b.not_banned_confirmed !== true) return json(400, { code: "VALIDATION", message: "금지 품목이 아님을 확인해야 합니다.", field: "not_banned_confirmed" });
    const f = parseShoppingFields(b);
    if (!f.ok) return json(400, { code: "VALIDATION", message: f.message, field: f.field });
    extra = { kind: "shopping", ...f.value, not_banned_confirmed: true };
  }
  const seg = segmentError(b.source_start_sec, b.segment_len_sec);
  if (seg) return json(400, { code: "VALIDATION", message: seg, field: "segment_len_sec" });
  if (!isLicense(b.license_cc) || !isCredit(b.credit)) return json(400, INVALID);

  try {
    const job = await createProductionJob(
      {
        title,
        format: shopping ? "shopping" : b.format === "variety" ? "variety" : "category", // 위에서 category·variety·shopping·미지정만 통과
        candidate_id: b.candidate_id as string | undefined,
        source_kind: b.source_kind,
        source_url: b.source_kind === "url" ? (b.source_url as string).trim() : null,
        rights_confirmed: b.rights_confirmed === true,
        license_cc: b.license_cc as boolean | null | undefined,
        credit: (b.credit as string | null | undefined) || null,
        source_start_sec: b.source_start_sec as number,
        segment_len_sec: b.segment_len_sec as number,
        ...extra,
      },
      key,
    );
    return json(200, { job: { id: job.id, status: job.status } });
  } catch (e) {
    return fromApiError(e, "작업을 만들지 못했습니다.");
  }
}
