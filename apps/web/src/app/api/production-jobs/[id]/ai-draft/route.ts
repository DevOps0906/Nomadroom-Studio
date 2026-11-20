import { requestProductionAiDraft } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { json } from "../../_shared";
import { fromRevisionError } from "../revision/_revision";

// PROD-02 AI 초안 중계(A-14). Claude 호출·키는 FastAPI에만 있다. Idempotency-Key는 브라우저가 클릭 단위로 만든다.
// 502·503(Claude 오류·미설정)은 고정 문구로 바꾼다(업스트림 사유를 넘기지 않음). 초안은 승인하지 않는다.
// 상태 코드는 FastAPI 그대로: 새 초안 201, 같은 키 재요청 200(API 본문 replay로 구분).

const KEY = /^[A-Za-z0-9._:-]{8,128}$/;

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id } = await params;
  if (!isUuid(id)) return json(400, { code: "VALIDATION", message: "잘못된 작업 id입니다." });
  const key = request.headers.get("idempotency-key") ?? "";
  if (!KEY.test(key)) return json(400, { code: "VALIDATION", message: "요청 키가 올바르지 않습니다." });
  try {
    const r = await requestProductionAiDraft(id, key);
    const v = r.revision;
    return json(r.replay ? 200 : 201, {
      revision: { id: v.id, rev_no: v.rev_no, spec: v.spec, origin: v.origin, validation: v.validation, approved_at: v.approved_at },
      ai_draft_count: r.ai_draft_count,
      previous_rev_no: r.previous_rev_no,
      variants: r.variants ?? null,
      facts_to_check: r.facts_to_check ?? null,
    });
  } catch (e) {
    return fromRevisionError(e, "AI 초안을 만들지 못했습니다. 잠시 후 다시 시도하세요.");
  }
}
