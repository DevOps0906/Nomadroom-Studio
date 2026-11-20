import { getProductionDownloadUrl, getProductionJob } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { fromApiError, json, readBody } from "../../_shared";
import { pickReportWarnings } from "./pick";

// PROD-03 검수 리포트의 warnings(dub_overflow·dub_none 등)만 꺼내 준다. 서명 URL은 서버에서만 쓰고 응답에 넣지 않는다.
// 이 작업의 ready report 자산만 허용하고, 본문 크기·시간을 제한한다(리포트는 API가 만든 JSON).

const MAX_BYTES = 2_000_000;
const TIMEOUT_MS = 8_000;

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id } = await params;
  if (!isUuid(id)) return json(400, { code: "VALIDATION", message: "잘못된 작업 id입니다." });
  const b = await readBody(request);
  if (!b || !isUuid(b.asset_id)) return json(400, { code: "VALIDATION", message: "잘못된 자산 id입니다." });
  try {
    const detail = await getProductionJob(id);
    if (!detail.assets.some((a) => a.id === b.asset_id && a.kind === "report" && a.status === "ready")) {
      return json(404, { code: "NOT_FOUND", message: "리포트를 찾을 수 없습니다." });
    }
    const signed = await getProductionDownloadUrl(id, b.asset_id as string);
    // 리다이렉트 금지, 스트림으로 읽다가 누적 바이트가 상한을 넘으면 중단한다.
    const res = await fetch(signed.url, { cache: "no-store", redirect: "error", signal: AbortSignal.timeout(TIMEOUT_MS) });
    if (!res.ok || !res.body) return json(502, { code: "INTERNAL", message: "리포트를 읽지 못했습니다." });
    const reader = res.body.getReader();
    const chunks: Uint8Array[] = [];
    let total = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_BYTES) {
        await reader.cancel();
        return json(502, { code: "INTERNAL", message: "리포트가 너무 큽니다." });
      }
      chunks.push(value);
    }
    const text = new TextDecoder().decode(Buffer.concat(chunks));
    return json(200, pickReportWarnings(JSON.parse(text) as unknown));
  } catch (e) {
    return fromApiError(e, "리포트를 읽지 못했습니다.");
  }
}
