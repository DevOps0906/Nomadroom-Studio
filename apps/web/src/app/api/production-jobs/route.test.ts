import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  calls: [] as string[],
  bodies: [] as unknown[],
  fail: null as number | null,
}));
vi.mock("server-only", () => ({}));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: vi.fn() }));

const { ApiError } = await import("@/server/api/client");
const maybeFail = () => {
  if (h.fail) throw new ApiError(h.fail, `UPSTREAM_${h.fail}`, h.fail === 409 ? "상태 불가: preparing" : "upstream detail");
};
vi.mock("@/server/api/production", () => ({
  createProductionJob: async (b: unknown, key: string) => {
    h.calls.push(`create:${key}`);
    h.bodies.push(b);
    maybeFail();
    return { id: "j1", status: "draft", secret: "x" };
  },
  patchProductionJob: async (_id: string, b: unknown) => {
    h.calls.push("patch");
    h.bodies.push(b);
    maybeFail();
    return { id: "j1", status: "draft" };
  },
  requestProductionUpload: async () => {
    h.calls.push("upload");
    maybeFail();
    return { asset: { id: "a1", kind: "source_upload", status: "pending" }, upload_url: "https://s/u", expires_at: "2026-11-19T02:00:00Z" };
  },
  completeProductionUpload: async () => {
    h.calls.push("complete");
    maybeFail();
    return { id: "a1", status: "ready", size_bytes: 1 };
  },
  prepareProductionJob: async () => {
    h.calls.push("prepare");
    maybeFail();
    return { id: "j1", status: "preparing" };
  },
}));

const create = await import("./route");
const patch = await import("./[id]/route");
const uploads = await import("./[id]/uploads/route");
const complete = await import("./[id]/uploads/[assetId]/complete/route");
const prepare = await import("./[id]/prepare/route");

const ORIGIN = "https://studio.example.com";
const ID = "00000000-0000-4000-8000-0000000000e1";
const AID = "00000000-0000-4000-8000-0000000000e2";
const req = (method: string, body?: unknown, origin: string | null = ORIGIN, extra: Record<string, string> = {}) => {
  const headers: Record<string, string> = { "content-type": "application/json", ...extra };
  if (origin !== null) headers.origin = origin;
  return new Request(`${ORIGIN}/api/production-jobs`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
};
const ctx = { params: Promise.resolve({ id: ID }) };
const ctx2 = { params: Promise.resolve({ id: ID, assetId: AID }) };
const VALID = { title: "제목", rights_confirmed: true, source_kind: "upload", source_start_sec: 0, segment_len_sec: 30 };
const KEY = { "idempotency-key": ["key-", "1234", "5678"].join("") };

const handlers: [string, (origin: string | null) => Promise<Response>][] = [
  ["POST /", (o) => create.POST(req("POST", VALID, o, KEY))],
  ["PATCH /[id]", (o) => patch.PATCH(req("PATCH", { credit: "a" }, o), ctx)],
  ["POST uploads", (o) => uploads.POST(req("POST", { kind: "source_upload", size_bytes: 1, mime: "video/mp4" }, o), ctx)],
  ["POST complete", (o) => complete.POST(req("POST", undefined, o), ctx2)],
  ["POST prepare", (o) => prepare.POST(req("POST", undefined, o), ctx)],
];

describe("/api/production-jobs/*", () => {
  beforeEach(() => {
    vi.stubEnv("APP_ORIGIN", ORIGIN);
    h.calls = [];
    h.bodies = [];
    h.fail = null;
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

  it("생성: 멱등 키 전달, 응답은 id·status만", async () => {
    const res = await create.POST(req("POST", VALID, ORIGIN, KEY));
    expect(await res.json()).toEqual({ job: { id: "j1", status: "draft" } });
    expect(h.calls).toEqual(["create:key-12345678"]);
  });

  it.each([
    ["키 없음", VALID, {}],
    ["권한 미확인", { ...VALID, rights_confirmed: false }, KEY],
    ["URL 원본인데 URL 없음", { ...VALID, source_kind: "url" }, KEY],
    ["URL 원본 http", { ...VALID, source_kind: "url", source_url: "http://www.youtube.com/watch?v=a" }, KEY],
    ["URL 원본 사설 IP", { ...VALID, source_kind: "url", source_url: "https://10.0.0.1/v" }, KEY],
    ["URL 원본 file:", { ...VALID, source_kind: "url", source_url: "file:///etc/passwd" }, KEY],
    ["URL 원본 비 YouTube", { ...VALID, source_kind: "url", source_url: "https://vimeo.com/1" }, KEY],
    ["업로드인데 URL", { ...VALID, source_url: "https://youtu.be/a" }, KEY],
    ["원본 방식 오류", { ...VALID, source_kind: "ftp" }, KEY],
    ["길이 181", { ...VALID, segment_len_sec: 181 }, KEY],
    ["길이 0", { ...VALID, segment_len_sec: 0 }, KEY],
    ["시작 음수", { ...VALID, source_start_sec: -1 }, KEY],
    ["빈 제목", { ...VALID, title: " " }, KEY],
  ])("생성 400: %s", async (_n, body, extra) => {
    expect((await create.POST(req("POST", body, ORIGIN, extra))).status).toBe(400);
    expect(h.calls).toHaveLength(0);
  });

  it("생성: URL 원본은 source_kind·source_url을 API로 전달, 응답은 id·status만", async () => {
    const body = { ...VALID, source_kind: "url", source_url: " https://www.youtube.com/watch?v=abc " };
    const res = await create.POST(req("POST", body, ORIGIN, KEY));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ job: { id: "j1", status: "draft" } });
    expect(h.bodies[0]).toMatchObject({ source_kind: "url", source_url: "https://www.youtube.com/watch?v=abc", rights_confirmed: true });
  });

  it("생성: 업로드 원본은 source_url null", async () => {
    await create.POST(req("POST", VALID, ORIGIN, KEY));
    expect(h.bodies[0]).toMatchObject({ source_kind: "upload", source_url: null });
  });

  it("URL 생성·PATCH: 다른 Origin이면 403, API 호출 없음", async () => {
    const body = { ...VALID, source_kind: "url", source_url: "https://youtu.be/abc" };
    expect((await create.POST(req("POST", body, "https://evil.com", KEY))).status).toBe(403);
    expect((await patch.PATCH(req("PATCH", { source_kind: "url", source_url: "https://youtu.be/abc" }, "https://evil.com"), ctx)).status).toBe(403);
    expect(h.calls).toHaveLength(0);
  });

  it("PATCH: source_kind·source_url 전달(보낸 필드만), null은 지우기", async () => {
    const res = await patch.PATCH(req("PATCH", { source_kind: "url", source_url: "https://m.youtube.com/watch?v=a", rights_confirmed: true }), ctx);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ job: { id: "j1", status: "draft" } });
    expect(h.bodies[0]).toEqual({ source_kind: "url", source_url: "https://m.youtube.com/watch?v=a", rights_confirmed: true });
    await patch.PATCH(req("PATCH", { source_kind: "upload", source_url: null }), ctx);
    expect(h.bodies[1]).toEqual({ source_kind: "upload", source_url: null });
  });

  it.each([
    ["사설 IP", { source_url: "https://127.0.0.1/v" }],
    ["IPv6 루프백", { source_url: "https://[::1]/v" }],
    ["비 YouTube", { source_url: "https://example.com/v" }],
    ["문자열 아님", { source_url: 1 }],
    ["원본 방식 오류", { source_kind: "x" }],
  ])("PATCH 400: %s", async (_n, body) => {
    expect((await patch.PATCH(req("PATCH", body), ctx)).status).toBe(400);
    expect(h.calls).toHaveLength(0);
  });

  it("업로드: 500MB 초과·잘못된 kind는 400", async () => {
    const big = { kind: "source_upload", size_bytes: 500 * 1024 * 1024 + 1, mime: "video/mp4" };
    expect((await uploads.POST(req("POST", big), ctx)).status).toBe(400);
    expect((await uploads.POST(req("POST", { kind: "hook_audio", size_bytes: 1, mime: "audio/wav" }), ctx)).status).toBe(400);
    expect(h.calls).toHaveLength(0);
  });

  it("업로드 서명 응답", async () => {
    const res = await uploads.POST(req("POST", { kind: "source_upload", size_bytes: 10, mime: "video/mp4" }), ctx);
    expect(await res.json()).toEqual({ asset: { id: "a1" }, upload_url: "https://s/u", expires_at: "2026-11-19T02:00:00Z" });
  });

  it("UUID가 아니면 400", async () => {
    const bad = { params: Promise.resolve({ id: "nope" }) };
    expect((await prepare.POST(req("POST"), bad)).status).toBe(400);
    expect(h.calls).toHaveLength(0);
  });

  it("409는 상태가 담긴 문구를 그대로, 404는 일반 문구, 그 외는 502", async () => {
    h.fail = 409;
    const r409 = await prepare.POST(req("POST"), ctx);
    expect(r409.status).toBe(409);
    expect((await r409.json()).message).toContain("preparing");
    h.fail = 404;
    const r404 = await prepare.POST(req("POST"), ctx);
    expect(r404.status).toBe(404);
    expect(JSON.stringify(await r404.json())).not.toContain("upstream detail");
    h.fail = 500;
    expect((await prepare.POST(req("POST"), ctx)).status).toBe(502);
  });
});
