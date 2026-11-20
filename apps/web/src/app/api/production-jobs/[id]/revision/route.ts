import { saveProductionRevision } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { INVALID, json, readBody } from "../../_shared";
import { fromRevisionError } from "./_revision";

// PROD-02 편집안 저장 중계(A-12 PUT). 의미 오류는 저장되고 validation으로 돌아온다. 구조 검증은 서버가 정본.

export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id } = await params;
  if (!isUuid(id)) return json(400, { code: "VALIDATION", message: "잘못된 작업 id입니다." });
  const b = await readBody(request);
  if (!b) return json(400, INVALID);
  const spec = b.spec;
  const base = b.base_rev_no;
  if (typeof spec !== "object" || spec === null || Array.isArray(spec)) return json(400, INVALID);
  if (typeof base !== "number" || !Number.isInteger(base) || base < 1) return json(400, INVALID);
  const lang = b.lang === undefined ? "ko" : b.lang;
  if (lang !== "ko" && lang !== "ja") return json(400, { code: "VALIDATION", message: "언어가 올바르지 않습니다.", field: "lang" });
  try {
    const r = await saveProductionRevision(id, spec as Record<string, unknown>, base, lang);
    return json(200, { revision: { id: r.id, rev_no: r.rev_no, validation: r.validation, approved_at: r.approved_at } });
  } catch (e) {
    return fromRevisionError(e, "편집안을 저장하지 못했습니다.");
  }
}
