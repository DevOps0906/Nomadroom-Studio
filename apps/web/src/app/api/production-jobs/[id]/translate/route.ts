import { requestProductionTranslate } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { INVALID, json, readBody } from "../../_shared";
import { fromRevisionError } from "../revision/_revision";

// PROD-02 일본어판 번역 초안 중계(A-20). Claude 호출·키는 FastAPI에만 있다. Idempotency-Key는 브라우저가 의도 단위로 만든다.
// 502·503은 고정 문구로 바꾼다. 초안은 승인하지 않는다. 새 초안 201, 같은 키 재요청 200(본문 replay).

const KEY = /^[A-Za-z0-9._:-]{8,128}$/;

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id } = await params;
  if (!isUuid(id)) return json(400, { code: "VALIDATION", message: "잘못된 작업 id입니다." });
  const key = request.headers.get("idempotency-key") ?? "";
  if (!KEY.test(key)) return json(400, { code: "VALIDATION", message: "요청 키가 올바르지 않습니다." });
  const b = await readBody(request);
  if (!b || !isUuid(b.revision_id)) return json(400, INVALID);
  try {
    const r = await requestProductionTranslate(id, b.revision_id as string, key);
    const v = r.revision;
    return json(r.replay ? 200 : 201, {
      revision: { id: v.id, rev_no: v.rev_no, spec: v.spec, origin: v.origin, validation: v.validation, approved_at: v.approved_at, updated_at: v.updated_at, derived_from: v.derived_from ?? null },
      translate_count: r.translate_count,
      replay: r.replay,
    });
  } catch (e) {
    return fromRevisionError(e, "번역 초안을 만들지 못했습니다. 잠시 후 다시 시도하세요.");
  }
}
