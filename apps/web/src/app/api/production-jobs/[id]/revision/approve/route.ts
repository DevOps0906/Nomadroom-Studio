import { approveProductionRevision } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { INVALID, json, readBody } from "../../../_shared";
import { fromRevisionError } from "../_revision";

// PROD-02 편집안 승인 중계(A-13). 서버가 spec을 다시 검증한다.

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id } = await params;
  if (!isUuid(id)) return json(400, { code: "VALIDATION", message: "잘못된 작업 id입니다." });
  const b = await readBody(request);
  if (!b) return json(400, INVALID);
  const rev = b.rev_no;
  if (typeof rev !== "number" || !Number.isInteger(rev) || rev < 1) return json(400, INVALID);
  const lang = b.lang === undefined ? "ko" : b.lang;
  if (lang !== "ko" && lang !== "ja") return json(400, { code: "VALIDATION", message: "언어가 올바르지 않습니다.", field: "lang" });
  try {
    const r = await approveProductionRevision(id, rev, lang);
    return json(200, { revision: { rev_no: r.rev_no, approved_at: r.approved_at } });
  } catch (e) {
    return fromRevisionError(e, "편집안을 승인하지 못했습니다.");
  }
}
