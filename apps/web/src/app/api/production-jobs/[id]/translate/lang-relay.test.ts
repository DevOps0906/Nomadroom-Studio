import { beforeEach, describe, expect, it, vi } from "vitest";

// task-052 언어 탭 중계: 번역(A-20)·ja 저장/승인(A-12·A-13 lang)·리포트 warnings.

const h = vi.hoisted(() => ({ calls: [] as string[], fail: null as null | 409 | 429 | 0 | 502, assets: [] as { id: string; kind: string; status: string }[] }));
vi.mock("server-only", () => ({}));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: vi.fn() }));

const { ApiError } = await import("@/server/api/client");
const maybeFail = () => {
  if (h.fail === 0) throw new ApiError(0, "NETWORK", "연결 실패");
  if (h.fail === 502) throw new ApiError(502, "UPSTREAM_ERROR", "upstream detail");
  if (h.fail) throw new ApiError(h.fail, h.fail === 409 ? "CONFLICT" : "QUOTA_EXCEEDED", h.fail === 409 ? "예능형 일본어판 렌더는 아직 지원하지 않습니다." : "번역 횟수 초과");
};
vi.mock("@/server/api/production", () => ({
  requestProductionTranslate: async (_id: string, rev: string, key: string) => {
    h.calls.push(`translate:${rev}:${key}`);
    maybeFail();
    return { revision: { id: "j1", rev_no: 1, spec: { lang: "ja" }, origin: "ai_draft", validation: { errors: [], warnings: [] }, approved_at: null, derived_from: "k1", secret: "x" }, translate_count: 1, replay: false };
  },
  saveProductionRevision: async (_id: string, _spec: unknown, base: number, lang: string) => {
    h.calls.push(`save:${base}:${lang}`);
    return { id: "j1", rev_no: 2, validation: { errors: [], warnings: [] }, approved_at: null };
  },
  approveProductionRevision: async (_id: string, rev: number, lang: string) => {
    h.calls.push(`approve:${rev}:${lang}`);
    return { id: "j1", rev_no: rev, approved_at: "2026-11-20T00:00:00Z", approved_by: "u" };
  },
  getProductionJob: async () => ({ assets: h.assets }),
  getProductionDownloadUrl: async () => ({ url: "https://s/signed", expires_at: "x", kind: "report" }),
}));

const translate = await import("./route");
const save = await import("../revision/route");
const approve = await import("../revision/approve/route");
const reportWarnings = await import("../report-warnings/route");

const ORIGIN = "https://studio.example.com";
const ID = "00000000-0000-4000-8000-0000000000e1";
const RID = "00000000-0000-4000-8000-0000000000e2";
const AID = "00000000-0000-4000-8000-0000000000e3";
const KEY = { "idempotency-key": ["tr-", "1234", "5678"].join("") };
const req = (method: string, body?: unknown, origin: string | null = ORIGIN, extra: Record<string, string> = {}) => {
  const headers: Record<string, string> = { "content-type": "application/json", ...extra };
  if (origin !== null) headers.origin = origin;
  return new Request(`${ORIGIN}/api/x`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
};
const ctx = { params: Promise.resolve({ id: ID }) };

describe("언어 탭 중계", () => {
  beforeEach(() => {
    vi.stubEnv("APP_ORIGIN", ORIGIN);
    h.calls = [];
    h.fail = null;
    h.assets = [];
  });

  it("번역: Origin 403, 키·리비전 id 검증 400, 호출 없음", async () => {
    expect((await translate.POST(req("POST", { revision_id: RID }, "https://evil.com", KEY), ctx)).status).toBe(403);
    expect((await translate.POST(req("POST", { revision_id: RID }, ORIGIN, {}), ctx)).status).toBe(400);
    expect((await translate.POST(req("POST", { revision_id: "nope" }, ORIGIN, KEY), ctx)).status).toBe(400);
    expect(h.calls).toHaveLength(0);
  });

  it("번역: 키·리비전 전달, 201, 응답 최소화·no-store", async () => {
    const res = await translate.POST(req("POST", { revision_id: RID }, ORIGIN, KEY), ctx);
    expect(res.status).toBe(201);
    expect(res.headers.get("cache-control")).toBe("no-store");
    const body = await res.json();
    expect(body.revision.derived_from).toBe("k1");
    expect(JSON.stringify(body)).not.toContain("secret");
    expect(h.calls).toEqual([`translate:${RID}:tr-12345678`]);
  });

  it("번역 429·409는 API 문구 그대로", async () => {
    h.fail = 429;
    expect((await translate.POST(req("POST", { revision_id: RID }, ORIGIN, KEY), ctx)).status).toBe(429);
    h.fail = 409;
    expect((await (await translate.POST(req("POST", { revision_id: RID }, ORIGIN, KEY), ctx)).json()).message).toContain("예능형");
  });

  it("통신 실패·타임아웃은 504 NETWORK, 서버가 확정한 502는 UPSTREAM_ERROR(사유 비노출)", async () => {
    h.fail = 0;
    const net = await translate.POST(req("POST", { revision_id: RID }, ORIGIN, KEY), ctx);
    expect(net.status).toBe(504);
    expect((await net.json()).code).toBe("NETWORK");
    h.fail = 502;
    const up = await translate.POST(req("POST", { revision_id: RID }, ORIGIN, KEY), ctx);
    expect(up.status).toBe(502);
    const body = await up.json();
    expect(body.code).toBe("UPSTREAM_ERROR");
    expect(JSON.stringify(body)).not.toContain("upstream detail");
  });

  it("A-12 PUT·A-13 승인: lang 전달, 기본 ko, 잘못된 값 400", async () => {
    await save.PUT(req("PUT", { spec: {}, base_rev_no: 1, lang: "ja" }), ctx);
    await save.PUT(req("PUT", { spec: {}, base_rev_no: 1 }), ctx);
    await approve.POST(req("POST", { rev_no: 2, lang: "ja" }), ctx);
    await approve.POST(req("POST", { rev_no: 2 }), ctx);
    expect(h.calls).toEqual(["save:1:ja", "save:1:ko", "approve:2:ja", "approve:2:ko"]);
    expect((await save.PUT(req("PUT", { spec: {}, base_rev_no: 1, lang: "en" }), ctx)).status).toBe(400);
    expect((await approve.POST(req("POST", { rev_no: 2, lang: "en" }), ctx)).status).toBe(400);
  });

  it("리포트 warnings: 상한을 넘으면 중단(502), 리다이렉트 금지 옵션", async () => {
    h.assets = [{ id: AID, kind: "report", status: "ready" }];
    let opts: RequestInit | undefined;
    vi.stubGlobal("fetch", async (_u: string, o: RequestInit) => {
      opts = o;
      return new Response(new Uint8Array(2_100_000));
    });
    const res = await reportWarnings.POST(req("POST", { asset_id: AID }), ctx);
    vi.unstubAllGlobals();
    expect(res.status).toBe(502);
    expect(opts?.redirect).toBe("error");
  });

  it("리포트 warnings: 이 작업의 ready report만, 서명 URL은 응답에 없음", async () => {
    expect((await reportWarnings.POST(req("POST", { asset_id: AID }), ctx)).status).toBe(404);
    h.assets = [{ id: AID, kind: "report", status: "ready" }];
    const report = { lang: "ja", warnings: [{ code: "dub_overflow", line: 3, overflow_sec: 0.4 }, { code: "dub_none" }], other: "x" };
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify(report)));
    const res = await reportWarnings.POST(req("POST", { asset_id: AID }), ctx);
    vi.unstubAllGlobals();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.lang).toBe("ja");
    expect(body.warnings).toHaveLength(2);
    expect(body.warnings[0]).toMatchObject({ code: "dub_overflow", line: 3, overflow_sec: 0.4 });
    expect(JSON.stringify(body)).not.toContain("signed");
    expect(JSON.stringify(body)).not.toContain("other");
  });
});
