import { requestProductionRender } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { INVALID, fromApiError, json, readBody } from "../../_shared";

// PROD-03 렌더 요청 중계(A-15). Idempotency-Key는 브라우저가 의도 단위로 만든다. lang은 ko·ja(ja 형식·상태 조건은 API가 409로 판정).

const KEY = /^[A-Za-z0-9._:-]{8,128}$/;

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id } = await params;
  if (!isUuid(id)) return json(400, { code: "VALIDATION", message: "잘못된 작업 id입니다." });
  const key = request.headers.get("idempotency-key") ?? "";
  if (!KEY.test(key)) return json(400, { code: "VALIDATION", message: "요청 키가 올바르지 않습니다." });
  const b = await readBody(request);
  if (!b || !isUuid(b.revision_id) || (b.lang !== "ko" && b.lang !== "ja")) return json(400, INVALID);
  try {
    const run = await requestProductionRender(id, b.revision_id as string, b.lang, key);
    return json(202, { run: { id: run.id, status: run.status, attempt: run.attempt } });
  } catch (e) {
    return fromApiError(e, "렌더를 요청하지 못했습니다.");
  }
}
