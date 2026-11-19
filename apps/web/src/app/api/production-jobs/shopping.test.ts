import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({ calls: [] as string[], bodies: [] as unknown[] }));
vi.mock("server-only", () => ({}));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: vi.fn() }));
vi.mock("@/server/api/production", () => ({
  createProductionJob: async (b: unknown, key: string) => {
    h.calls.push(`create:${key}`);
    h.bodies.push(b);
    return { id: "j1", status: "draft" };
  },
  patchProductionJob: async (_id: string, b: unknown) => {
    h.calls.push("patch");
    h.bodies.push(b);
    return { id: "j1", status: "draft" };
  },
  requestProductionUpload: async (_id: string, b: unknown) => {
    h.calls.push("upload");
    h.bodies.push(b);
    return { asset: { id: "a1", kind: "image", status: "pending" }, upload_url: ["https://s", "/u"].join(""), expires_at: "2026-11-20T02:00:00Z" };
  },
  deleteProductionAsset: async (_id: string, assetId: string) => {
    h.calls.push(`delete:${assetId}`);
  },
  getProductionPublishText: async (_id: string, lang: string, run?: string) => {
    h.calls.push(`publish:${lang}:${run ?? ""}`);
    return { text: { caption: "c", pinned_comment: "p", recommended_time: "t" }, render_run_id: "r1", lang, extra: "x" };
  },
}));

const create = await import("./route");
const patch = await import("./[id]/route");
const uploads = await import("./[id]/uploads/route");
const del = await import("./[id]/assets/[assetId]/route");
const publish = await import("./[id]/publish-text/route");

const ORIGIN = "https://studio.example.com";
const ID = "00000000-0000-4000-8000-0000000000e1";
const AID = "00000000-0000-4000-8000-0000000000e2";
const RUN = "00000000-0000-4000-8000-0000000000e3";
const req = (method: string, body?: unknown, origin: string | null = ORIGIN, extra: Record<string, string> = {}) => {
  const headers: Record<string, string> = { "content-type": "application/json", ...extra };
  if (origin !== null) headers.origin = origin;
  return new Request(`${ORIGIN}/api/production-jobs`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
};
const ctx = { params: Promise.resolve({ id: ID }) };
const ctx2 = { params: Promise.resolve({ id: ID, assetId: AID }) };
const KEY = { "idempotency-key": ["key-", "1234", "5678"].join("") };
const SHOP = {
  title: "텀블러",
  kind: "shopping",
  format: "shopping",
  vertical: "product",
  not_banned_confirmed: true,
  source_kind: "upload",
  rights_confirmed: false,
  source_start_sec: 0,
  segment_len_sec: 30,
  brief: { product_name: "텀블러", pain: "미지근", scenes: ["a", "b", "c"], facts: [] },
  affiliates: [{ lang: "ko", partner: "쿠팡", url: "https://example.com/p" }],
  comment_keyword: "텀블러",
};

const handlers: [string, (origin: string | null) => Promise<Response>][] = [
  ["POST / (쇼핑)", (o) => create.POST(req("POST", SHOP, o, KEY))],
  ["PATCH /[id] (쇼핑 필드)", (o) => patch.PATCH(req("PATCH", { brief: { product_name: "a" } }, o), ctx)],
  ["POST uploads (image)", (o) => uploads.POST(req("POST", { kind: "image", size_bytes: 1, mime: "image/jpeg", rights: { basis: "own" } }, o), ctx)],
  ["DELETE assets/[assetId]", (o) => del.DELETE(req("DELETE", undefined, o), ctx2)],
  ["POST publish-text", (o) => publish.POST(req("POST", { lang: "ko" }, o), ctx)],
];

describe("쇼핑 Route Handler", () => {
  beforeEach(() => {
    vi.stubEnv("APP_ORIGIN", ORIGIN);
    h.calls = [];
    h.bodies = [];
  });

  describe.each(handlers)("%s", (_n, call) => {
    it.each([["https://evil.com"], [null]])("Origin이 다르거나 없으면 403, API 호출 없음: %s", async (origin) => {
      expect((await call(origin)).status).toBe(403);
      expect(h.calls).toHaveLength(0);
    });
    it("성공은 no-store", async () => {
      const res = await call(ORIGIN);
      expect(res.status).toBeLessThan(300);
      expect(res.headers.get("cache-control")).toBe("no-store");
    });
  });

  it("생성: 쇼핑 필드를 API로 넘기고 형식은 shopping, 작업 권리는 false 그대로", async () => {
    const res = await create.POST(req("POST", SHOP, ORIGIN, KEY));
    expect(await res.json()).toEqual({ job: { id: "j1", status: "draft" } });
    expect(h.bodies[0]).toMatchObject({ kind: "shopping", format: "shopping", vertical: "product", not_banned_confirmed: true, rights_confirmed: false, comment_keyword: "텀블러" });
    expect((h.bodies[0] as { affiliates: unknown[] }).affiliates).toHaveLength(1);
  });

  it.each([
    ["분야 없음", { ...SHOP, vertical: undefined }, "vertical"],
    ["금지 품목 확인 안 함", { ...SHOP, not_banned_confirmed: false }, "not_banned_confirmed"],
    ["URL 원본", { ...SHOP, source_kind: "url", source_url: "https://youtu.be/a" }, "source_kind"],
    ["유형과 형식 불일치", { ...SHOP, format: "category" }, "format"],
    ["제휴 링크 http", { ...SHOP, affiliates: [{ lang: "ko", partner: "a", url: "http://example.com" }] }, "affiliates"],
    ["제휴 링크 사용자 정보", { ...SHOP, affiliates: [{ lang: "ko", partner: "a", url: "https://u:p@example.com" }] }, "affiliates"],
    ["제휴 링크 21건", { ...SHOP, affiliates: Array.from({ length: 21 }, () => ({ lang: "ko", partner: "a", url: "https://example.com" })) }, "affiliates"],
    ["장면 6개", { ...SHOP, brief: { scenes: ["1", "2", "3", "4", "5", "6"] } }, "brief.scenes"],
    ["상품 종류 오류", { ...SHOP, brief: { product_type: "hotel" } }, "brief.product_type"],
    ["제어 문자", { ...SHOP, brief: { product_name: "a b" } }, "brief.product_name"],
  ])("생성 400: %s", async (_n, body, field) => {
    const res = await create.POST(req("POST", body, ORIGIN, KEY));
    expect(res.status).toBe(400);
    expect((await res.json()).field).toBe(field);
    expect(h.calls).toHaveLength(0);
  });

  it("일반 작업 생성은 기존대로(권리 확인 필수·kind 생략)", async () => {
    const general = { title: "t", rights_confirmed: true, source_kind: "upload", source_start_sec: 0, segment_len_sec: 30 };
    expect((await create.POST(req("POST", { ...general, rights_confirmed: false }, ORIGIN, KEY))).status).toBe(400);
    expect((await create.POST(req("POST", general, ORIGIN, KEY))).status).toBe(200);
    expect(h.bodies[0]).toMatchObject({ format: "category", rights_confirmed: true });
    expect(h.bodies[0]).not.toHaveProperty("kind");
  });

  it("PATCH: 쇼핑 필드만 보낼 수 있고 형식 오류는 400", async () => {
    expect((await patch.PATCH(req("PATCH", { vertical: "travel", comment_keyword: null }), ctx)).status).toBe(200);
    expect(h.bodies[0]).toEqual({ vertical: "travel", comment_keyword: null });
    expect((await patch.PATCH(req("PATCH", { vertical: "space" }), ctx)).status).toBe(400);
    expect((await patch.PATCH(req("PATCH", { affiliates: "x" }), ctx)).status).toBe(400);
    expect((await patch.PATCH(req("PATCH", {}), ctx)).status).toBe(400);
    expect(h.calls).toEqual(["patch"]);
  });

  it("업로드: image·narration·bgm과 rights를 전달하고 상한은 종류별", async () => {
    const ok = await uploads.POST(req("POST", { kind: "narration", size_bytes: 1000, mime: "audio/wav", rights: { basis: "own", has_person: false } }), ctx);
    expect(ok.status).toBe(200);
    expect(h.bodies[0]).toMatchObject({ kind: "narration", rights: { basis: "own", has_person: false } });
    const big = await uploads.POST(req("POST", { kind: "image", size_bytes: 21 * 1024 * 1024, mime: "image/png", rights: { basis: "own" } }), ctx);
    expect(big.status).toBe(400);
    const hook = await uploads.POST(req("POST", { kind: "hook_audio", size_bytes: 1, mime: "audio/wav" }), ctx);
    expect(hook.status).toBe(400); // 훅 음성은 전용 경로
  });

  it.each([
    ["근거 없음", { kind: "image", size_bytes: 1, mime: "image/png", rights: {} }, "rights.basis"],
    ["허용 외 필드(gen)", { kind: "image", size_bytes: 1, mime: "image/png", rights: { basis: "own", gen: {} } }, "rights"],
    ["AI 생성 근거", { kind: "image", size_bytes: 1, mime: "image/png", rights: { basis: "ai_generated" } }, "rights.basis"],
    ["초상권 미동의", { kind: "image", size_bytes: 1, mime: "image/png", rights: { basis: "own", has_person: true, portrait_consent: false } }, "rights.portrait_consent"],
    ["출처 URL 형식", { kind: "image", size_bytes: 1, mime: "image/png", rights: { basis: "own", source_url: "ftp://x" } }, "rights.source_url"],
  ])("업로드 권리 400: %s", async (_n, body, field) => {
    const res = await uploads.POST(req("POST", body), ctx);
    expect(res.status).toBe(400);
    expect((await res.json()).field).toBe(field);
    expect(h.calls).toHaveLength(0);
  });

  it("삭제: id 검증 후 중계", async () => {
    expect((await del.DELETE(req("DELETE"), ctx2)).status).toBe(200);
    expect(h.calls).toEqual([`delete:${AID}`]);
    expect((await del.DELETE(req("DELETE"), { params: Promise.resolve({ id: ID, assetId: "x" }) })).status).toBe(400);
  });

  it("게시 문구: 기본 ko, 필요한 필드만 응답, 잘못된 언어·run은 400", async () => {
    const res = await publish.POST(req("POST", { render_run_id: RUN }), ctx);
    expect(await res.json()).toEqual({ text: { caption: "c", pinned_comment: "p", recommended_time: "t" }, render_run_id: "r1", lang: "ko" });
    expect(h.calls).toEqual([`publish:ko:${RUN}`]);
    expect((await publish.POST(req("POST", { lang: "en" }), ctx)).status).toBe(400);
    expect((await publish.POST(req("POST", { render_run_id: "x" }), ctx)).status).toBe(400);
  });
});
