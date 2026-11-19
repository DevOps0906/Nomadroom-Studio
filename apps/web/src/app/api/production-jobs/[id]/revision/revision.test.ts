import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({ calls: [] as string[], fail: null as null | "400" | "409" }));
vi.mock("server-only", () => ({}));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: vi.fn() }));

const { ApiError } = await import("@/server/api/client");
const maybeFail = () => {
  if (h.fail === "400") {
    throw new ApiError(400, "VALIDATION", "편집안에 오류가 있어 승인할 수 없습니다.", "spec", [{ code: "shots.gap", path: "shots.1", message: "공백" }], [{ code: "items.too_short", path: "items.0", message: "짧음" }]);
  }
  if (h.fail === "409") throw new ApiError(409, "CONFLICT", "다른 곳에서 먼저 수정되었습니다.", "base_rev_no");
};
vi.mock("@/server/api/production", () => ({
  saveProductionRevision: async () => {
    h.calls.push("save");
    maybeFail();
    return { id: "r1", rev_no: 3, spec: { secret: 1 }, origin: "user", validation: { errors: [], warnings: [] }, approved_at: null };
  },
  approveProductionRevision: async () => {
    h.calls.push("approve");
    maybeFail();
    return { id: "r1", rev_no: 3, approved_at: "2026-11-19T02:00:00Z", approved_by: "u1" };
  },
  requestProductionUpload: async (_id: string, b: { kind: string }) => {
    h.calls.push(`upload:${b.kind}`);
    return { asset: { id: "a1", kind: b.kind, status: "pending" }, upload_url: "https://s/u", expires_at: "2026-11-19T02:00:00Z" };
  },
  getProductionJob: async () => ({ assets: [{ id: "00000000-0000-4000-8000-0000000000e2", kind: "sheet", status: "ready" }, { id: "00000000-0000-4000-8000-0000000000e3", kind: "source_upload", status: "ready" }] }),
  getProductionDownloadUrl: async () => ({ url: "https://s/get", expires_at: "x", kind: "sheet" }),
}));

const save = await import("./route");
const approve = await import("./approve/route");
const hook = await import("./hook-audio/route");
const sheet = await import("./sheet/[assetId]/route");

const ORIGIN = "https://studio.example.com";
const ID = "00000000-0000-4000-8000-0000000000e1";
const AID = "00000000-0000-4000-8000-0000000000e2";
const req = (method: string, body?: unknown, origin: string | null = ORIGIN) => {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (origin !== null) headers.origin = origin;
  return new Request(`${ORIGIN}/api/production-jobs/x`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
};
const ctx = { params: Promise.resolve({ id: ID }) };

describe("/api/production-jobs/[id]/revision*", () => {
  beforeEach(() => {
    vi.stubEnv("APP_ORIGIN", ORIGIN);
    h.calls = [];
    h.fail = null;
  });

  it("상태 변경 핸들러는 Origin이 다르거나 없으면 403, 업스트림을 부르지 않는다", async () => {
    for (const o of ["https://evil.example.com", null]) {
      expect((await save.PUT(req("PUT", { spec: {}, base_rev_no: 1 }, o), ctx)).status).toBe(403);
      expect((await approve.POST(req("POST", { rev_no: 1 }, o), ctx)).status).toBe(403);
      expect((await hook.POST(req("POST", { size_bytes: 1, mime: "audio/wav" }, o), ctx)).status).toBe(403);
    }
    expect(h.calls).toHaveLength(0);
  });

  it("저장 성공 응답은 spec을 되돌리지 않는다", async () => {
    const res = await save.PUT(req("PUT", { spec: { a: 1 }, base_rev_no: 2 }), ctx);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.revision).toEqual({ id: "r1", rev_no: 3, validation: { errors: [], warnings: [] }, approved_at: null });
  });

  it.each([
    ["spec 없음", { base_rev_no: 1 }],
    ["spec 배열", { spec: [], base_rev_no: 1 }],
    ["base 0", { spec: {}, base_rev_no: 0 }],
    ["base 소수", { spec: {}, base_rev_no: 1.5 }],
  ])("저장 400: %s", async (_n, body) => {
    expect((await save.PUT(req("PUT", body), ctx)).status).toBe(400);
    expect(h.calls).toHaveLength(0);
  });

  it("400은 errors[]·warnings[]를 전달하고 409는 충돌 문구를 전달한다", async () => {
    h.fail = "400";
    const bad = await approve.POST(req("POST", { rev_no: 3 }), ctx);
    expect(bad.status).toBe(400);
    const b = await bad.json();
    expect(b.errors).toEqual([{ code: "shots.gap", path: "shots.1", message: "공백" }]);
    expect(b.warnings).toHaveLength(1);
    h.fail = "409";
    const c = await save.PUT(req("PUT", { spec: {}, base_rev_no: 1 }), ctx);
    expect(c.status).toBe(409);
    expect((await c.json()).message).toContain("먼저 수정");
  });

  it("훅 음성 서명은 kind=hook_audio로만 발급하고 크기를 제한한다", async () => {
    const ok = await hook.POST(req("POST", { size_bytes: 10, mime: "audio/wav" }), ctx);
    expect(ok.status).toBe(200);
    expect(h.calls).toEqual(["upload:hook_audio"]);
    expect((await hook.POST(req("POST", { size_bytes: 51 * 1024 * 1024, mime: "audio/wav" }), ctx)).status).toBe(400);
  });

  it("시트 URL은 id 형식을 검사한다", async () => {
    const bad = await sheet.GET(req("GET"), { params: Promise.resolve({ id: ID, assetId: "x" }) });
    expect(bad.status).toBe(400);
    const ok = await sheet.GET(req("GET"), { params: Promise.resolve({ id: ID, assetId: AID }) });
    expect((await ok.json()).url).toBe("https://s/get");
    const other = await sheet.GET(req("GET"), { params: Promise.resolve({ id: ID, assetId: "00000000-0000-4000-8000-0000000000e3" }) });
    expect(other.status).toBe(404);
  });
});
