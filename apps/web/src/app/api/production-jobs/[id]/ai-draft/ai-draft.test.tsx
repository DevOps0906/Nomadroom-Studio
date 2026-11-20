import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

// task-029 AI 초안 중계(A-14) Route Handler + PROD-02 "AI 초안 채우기" 버튼·브라우저 호출.

const h = vi.hoisted(() => ({ calls: [] as string[], fail: null as number | null, replay: false, variants: null as { hook_type: string; sentences: string[]; char_count: number }[] | null }));
vi.mock("server-only", () => ({}));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: vi.fn() }));

const { ApiError } = await import("@/server/api/client");
vi.mock("@/server/api/production", () => ({
  requestProductionAiDraft: async (id: string, key: string) => {
    h.calls.push(`ai:${id}:${key}`);
    if (h.fail) throw new ApiError(h.fail, h.fail === 429 ? "QUOTA_EXCEEDED" : "UPSTREAM_ERROR", h.fail === 429 ? "횟수를 모두 썼습니다." : "upstream detail");
    return {
      revision: { id: "r2", rev_no: 2, spec: { lang: "ko" }, origin: "ai_draft", validation: { errors: [], warnings: [] }, approved_at: null, secret: "x" },
      ai_draft_count: 1,
      previous_rev_no: 1,
      replay: h.replay,
      ...(h.variants ? { variants: h.variants, facts_to_check: ["가격 확인"] } : {}),
      secret: "x",
    };
  },
}));

const route = await import("./route");
const { AiDraftButton, aiDraftNotice } = await import("@/components/production/edit/AiDraftButton");
const { requestAiDraft } = await import("@/components/production/edit/api");

const ORIGIN = "https://studio.example.com";
const ID = "00000000-0000-4000-8000-0000000000e1";
const KEY = ["ai-", "1234", "5678"].join("");
const ctx = { params: Promise.resolve({ id: ID }) };
const req = (origin: string | null = ORIGIN, key: string | null = KEY) => {
  const headers: Record<string, string> = {};
  if (origin !== null) headers.origin = origin;
  if (key !== null) headers["idempotency-key"] = key;
  return new Request(`${ORIGIN}/api/x`, { method: "POST", headers });
};

describe("A-14 AI 초안 중계", () => {
  beforeEach(() => {
    vi.stubEnv("APP_ORIGIN", ORIGIN);
    h.calls = [];
    h.fail = null;
    h.replay = false;
    h.variants = null;
  });

  it("쇼핑 3안·확인할 사실을 브라우저까지 전달, 그 밖은 null", async () => {
    h.variants = [{ hook_type: "질문형", sentences: ["a", "b", "c", "d"], char_count: 4 }];
    const body = await (await route.POST(req(), ctx)).json();
    expect(body.variants).toEqual(h.variants);
    expect(body.facts_to_check).toEqual(["가격 확인"]);
    h.variants = null;
    const plain = await (await route.POST(req(), ctx)).json();
    expect(plain.variants).toBeNull();
    expect(plain.facts_to_check).toBeNull();
  });

  it.each([["https://evil.com"], [null]])("Origin이 다르거나 없으면 403, API 호출 없음: %s", async (origin) => {
    expect((await route.POST(req(origin), ctx)).status).toBe(403);
    expect(h.calls).toHaveLength(0);
  });

  it("멱등 키가 없거나 형식이 틀리면 400, API 호출 없음", async () => {
    expect((await route.POST(req(ORIGIN, null), ctx)).status).toBe(400);
    expect((await route.POST(req(ORIGIN, "bad key!"), ctx)).status).toBe(400);
    expect(h.calls).toHaveLength(0);
  });

  it("성공: 키 전달·no-store·필요 필드만(새 초안 201)", async () => {
    const res = await route.POST(req(), ctx);
    expect(res.status).toBe(201);
    expect(res.headers.get("cache-control")).toBe("no-store");
    const body = await res.json();
    expect(h.calls).toEqual([`ai:${ID}:${KEY}`]);
    expect(body.revision.origin).toBe("ai_draft");
    expect(body.revision.approved_at).toBeNull();
    expect(body.previous_rev_no).toBe(1);
    expect(JSON.stringify(body)).not.toContain("secret");
  });

  it("같은 키 재요청은 FastAPI처럼 200", async () => {
    h.replay = true;
    expect((await route.POST(req(), ctx)).status).toBe(200);
  });

  it("429는 API 문구 그대로, 502는 고정 문구(업스트림 사유 숨김)", async () => {
    h.fail = 429;
    const q = await route.POST(req(), ctx);
    expect(q.status).toBe(429);
    expect((await q.json()).code).toBe("QUOTA_EXCEEDED");
    h.fail = 502;
    const u = await route.POST(req(), ctx);
    expect(u.status).toBe(502);
    expect(JSON.stringify(await u.json())).not.toContain("upstream detail");
  });
});

describe("AI 초안 버튼·브라우저 호출", () => {
  it("버튼 문구와 비활성", () => {
    const props = { jobId: ID, dirty: false, onBusy: () => {}, onApplied: () => {}, onFail: () => {} };
    expect(renderToStaticMarkup(<AiDraftButton {...props} disabled={false} />)).toContain("AI 초안 채우기");
    expect(renderToStaticMarkup(<AiDraftButton {...props} disabled />)).toMatch(/<button type="button" disabled=""/);
  });

  it("성공 안내에 새 rev와 보관된 이전 rev를 적는다", () => {
    const text = aiDraftNotice({ revision: { rev_no: 3 }, previous_rev_no: 2, ai_draft_count: 2 });
    expect(text).toContain("rev 3");
    expect(text).toContain("이전 편집안 rev 2은 보관됨");
  });

  it("브라우저 호출은 Route Handler로 Idempotency-Key 헤더를 보낸다", async () => {
    const f = vi.fn(async () => new Response(JSON.stringify({ revision: { rev_no: 2 }, ai_draft_count: 1, previous_rev_no: 1 }), { status: 200 }));
    const r = await requestAiDraft(ID, KEY, f as unknown as typeof fetch);
    expect(r.ok).toBe(true);
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`/api/production-jobs/${ID}/ai-draft`);
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBe(KEY);
  });
});
