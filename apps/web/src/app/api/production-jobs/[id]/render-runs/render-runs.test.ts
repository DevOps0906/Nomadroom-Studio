import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({ calls: [] as string[], fail: null as number | null, assets: [] as { id: string; kind: string; status: string }[] }));
vi.mock("server-only", () => ({}));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: vi.fn() }));

const { ApiError } = await import("@/server/api/client");
const maybeFail = () => {
  if (h.fail) throw new ApiError(h.fail, `UPSTREAM_${h.fail}`, h.fail === 409 ? "동시 렌더 1건" : "upstream detail");
};
vi.mock("@/server/api/production", () => ({
  requestProductionRender: async (_id: string, rev: string, lang: string, key: string) => {
    h.calls.push(`render:${rev}:${lang}:${key}`);
    maybeFail();
    return { id: "run1", status: "queued", attempt: 1, secret: "x" };
  },
  retryProductionRender: async (_id: string, runId: string) => {
    h.calls.push(`retry:${runId}`);
    maybeFail();
    return { id: "run2", status: "queued", attempt: 2, secret: "x" };
  },
  approveProductionReview: async () => {
    h.calls.push("approve");
    maybeFail();
    return { id: "j1", status: "done", secret: "x" };
  },
  getProductionJob: async () => ({ assets: h.assets }),
  getProductionDownloadUrl: async () => {
    h.calls.push("url");
    return { url: "https://s/signed", expires_at: "x", kind: "output_mp4" };
  },
}));

const render = await import("./route");
const retry = await import("./[runId]/retry/route");
const approve = await import("../review/approve/route");
const download = await import("../assets/[assetId]/download-url/route");

const ORIGIN = "https://studio.example.com";
const ID = "00000000-0000-4000-8000-0000000000e1";
const RID = "00000000-0000-4000-8000-0000000000e2";
const AID = "00000000-0000-4000-8000-0000000000e3";
const req = (method: string, body?: unknown, origin: string | null = ORIGIN, extra: Record<string, string> = {}) => {
  const headers: Record<string, string> = { "content-type": "application/json", ...extra };
  if (origin !== null) headers.origin = origin;
  return new Request(`${ORIGIN}/api/x`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
};
const ctx = { params: Promise.resolve({ id: ID }) };
const ctxRun = { params: Promise.resolve({ id: ID, runId: RID }) };
const KEY = { "idempotency-key": ["key-", "1234", "5678"].join("") };
const BODY = { revision_id: RID, lang: "ko" };

const handlers: [string, (origin: string | null) => Promise<Response>][] = [
  ["POST render-runs", (o) => render.POST(req("POST", BODY, o, KEY), ctx)],
  ["POST retry", (o) => retry.POST(req("POST", undefined, o), ctxRun)],
  ["POST review/approve", (o) => approve.POST(req("POST", undefined, o), ctx)],
];

describe("PROD-03 중계 Route Handler", () => {
  beforeEach(() => {
    vi.stubEnv("APP_ORIGIN", ORIGIN);
    h.calls = [];
    h.fail = null;
    h.assets = [];
  });

  describe.each(handlers)("%s", (_n, call) => {
    it.each([["https://evil.com"], [null]])("Origin이 다르거나 없으면 403, API 호출 없음: %s", async (origin) => {
      expect((await call(origin)).status).toBe(403);
      expect(h.calls).toHaveLength(0);
    });
    it("성공은 no-store, 응답 최소화", async () => {
      const res = await call(ORIGIN);
      expect(res.status).toBeLessThan(300);
      expect(res.headers.get("cache-control")).toBe("no-store");
      expect(JSON.stringify(await res.json())).not.toContain("secret");
    });
  });

  it("렌더 요청: 멱등 키·리비전 전달", async () => {
    await render.POST(req("POST", BODY, ORIGIN, KEY), ctx);
    expect(h.calls).toEqual([`render:${RID}:ko:key-12345678`]);
  });

  it("렌더 요청: lang=ja도 그대로 전달(형식·상태 판정은 API 409)", async () => {
    const res = await render.POST(req("POST", { ...BODY, lang: "ja" }, ORIGIN, KEY), ctx);
    expect(res.status).toBe(202);
    expect(h.calls).toEqual([`render:${RID}:ja:key-12345678`]);
  });

  it.each([
    ["키 없음", BODY, {}],
    ["지원하지 않는 언어", { ...BODY, lang: "en" }, KEY],
    ["리비전 id 아님", { ...BODY, revision_id: "nope" }, KEY],
  ])("렌더 요청 400: %s", async (_n, body, extra) => {
    expect((await render.POST(req("POST", body, ORIGIN, extra), ctx)).status).toBe(400);
    expect(h.calls).toHaveLength(0);
  });

  it("409는 API 문구 그대로, 404는 일반 문구, 그 외 502", async () => {
    h.fail = 409;
    const r409 = await retry.POST(req("POST"), ctxRun);
    expect(r409.status).toBe(409);
    expect((await r409.json()).message).toContain("동시 렌더");
    h.fail = 404;
    expect(JSON.stringify(await (await retry.POST(req("POST"), ctxRun)).json())).not.toContain("upstream detail");
    h.fail = 500;
    expect((await approve.POST(req("POST"), ctx)).status).toBe(502);
  });

  it("다운로드 URL: ready MP4·리포트만 열고 그 외는 404", async () => {
    const dctx = { params: Promise.resolve({ id: ID, assetId: AID }) };
    h.assets = [{ id: AID, kind: "source_upload", status: "ready" }];
    expect((await download.GET(req("GET"), dctx)).status).toBe(404);
    h.assets = [{ id: AID, kind: "output_mp4", status: "pending" }];
    expect((await download.GET(req("GET"), dctx)).status).toBe(404);
    expect(h.calls).toHaveLength(0);
    h.assets = [{ id: AID, kind: "output_mp4", status: "ready" }];
    const ok = await download.GET(req("GET"), dctx);
    expect(await ok.json()).toEqual({ url: "https://s/signed" });
    expect(ok.headers.get("cache-control")).toBe("no-store");
  });
});
