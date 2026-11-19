import { getProductionPublishText } from "@/server/api/production";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { isUuid } from "@/components/monitoring/query";
import { INVALID, fromApiError, json, readBody } from "../../_shared";

// PROD-03 게시 문구 중계(A-21, 쇼핑만). 제휴 링크가 응답에 들어 있어 POST로 받는다(주소·캐시·로그에 남기지 않기 + 같은 출처 확인).
// 응답은 no-store로 전달하고 저장·로그하지 않는다.

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const { id } = await params;
  if (!isUuid(id)) return json(400, { code: "VALIDATION", message: "잘못된 작업 id입니다." });
  const b = await readBody(request);
  if (!b) return json(400, INVALID);
  const lang = b.lang === undefined ? "ko" : b.lang;
  if (lang !== "ko" && lang !== "ja") return json(400, { code: "VALIDATION", message: "언어가 올바르지 않습니다.", field: "lang" });
  if (b.render_run_id !== undefined && !isUuid(b.render_run_id)) return json(400, { code: "VALIDATION", message: "잘못된 렌더 id입니다.", field: "render_run_id" });
  try {
    const r = await getProductionPublishText(id, lang, b.render_run_id as string | undefined);
    return json(200, { text: r.text, render_run_id: r.render_run_id, lang: r.lang });
  } catch (e) {
    return fromApiError(e, "게시 문구를 불러오지 못했습니다.");
  }
}
