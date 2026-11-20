import { listGenerationRuns, quoteGenerationRun } from "@/server/api/production";
import { isUuid } from "@/components/monitoring/query";
import { json } from "../../_shared";
import { KEY, envelope, fromGenerationError, guard, pickRun } from "./_generation";

// PROD-01S AI 영상 생성 목록(GET, 부작용 없음)·견적(POST, 과금 없음) 중계(A-22).

type Ctx = { params: Promise<{ id: string }> };

export async function GET(request: Request, { params }: Ctx) {
  const g = await guard(request, params);
  if (g.error) return g.error;
  try {
    const r = await listGenerationRuns(g.id);
    return json(200, { items: r.items.map(pickRun) });
  } catch (e) {
    return fromGenerationError(e, "AI 영상 생성 목록을 불러오지 못했습니다.");
  }
}

export async function POST(request: Request, { params }: Ctx) {
  const g = await guard(request, params);
  if (g.error) return g.error;
  const key = request.headers.get("idempotency-key") ?? "";
  if (!KEY.test(key)) return json(400, { code: "VALIDATION", message: "요청 키가 올바르지 않습니다." });
  const b = (await request.json().catch(() => null)) as Record<string, unknown> | null;
  const prompt = typeof b?.prompt === "string" ? b.prompt.trim() : "";
  const dur = b?.duration_sec;
  if (!b || typeof b.source_asset_id !== "string" || !isUuid(b.source_asset_id)) return json(400, { code: "VALIDATION", message: "입력 사진을 선택하세요.", field: "source_asset_id" });
  if (prompt.length < 1 || prompt.length > 500) return json(400, { code: "VALIDATION", message: "프롬프트는 1~500자로 입력하세요.", field: "prompt" });
  if (typeof dur !== "number" || !Number.isInteger(dur) || dur < 1 || dur > 15) return json(400, { code: "VALIDATION", message: "길이는 1~15초로 입력하세요.", field: "duration_sec" });
  try {
    const r = await quoteGenerationRun(g.id, { source_asset_id: b.source_asset_id, prompt, duration_sec: dur }, key);
    return json(r.replay ? 200 : 201, envelope(r));
  } catch (e) {
    return fromGenerationError(e, "견적을 만들지 못했습니다. 잠시 후 다시 시도하세요.");
  }
}
