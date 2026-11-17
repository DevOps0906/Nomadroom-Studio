import { beforeEach, describe, expect, it, vi } from "vitest";

// evidence route.test.ts와 같은 방식(vi.fn 대신 단순 함수).
const h = vi.hoisted(() => ({
  impl: (async () => undefined) as (id: string, used: boolean) => Promise<unknown>,
  calls: [] as [string, boolean][],
}));
vi.mock("server-only", () => ({}));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: vi.fn() }));
vi.mock("@/server/api/monitor", () => ({
  setUsed: (id: string, used: boolean) => {
    h.calls.push([id, used]);
    return h.impl(id, used);
  },
}));

const { ApiError } = await import("@/server/api/client");
const { PATCH } = await import("./route");

const ORIGIN = "https://studio.example.com";
const ID = "00000000-0000-4000-8000-0000000000e1";
const call = (id: string, body: string | null, origin: string | null = ORIGIN) => {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (origin !== null) headers.origin = origin;
  return PATCH(new Request(`${ORIGIN}/api/candidates/${id}/used`, { method: "PATCH", headers, body }), {
    params: Promise.resolve({ id }),
  });
};
const fail = (status: number) => async () => {
  throw new ApiError(status, `UPSTREAM_${status}`, "upstream detail");
};

describe("PATCH /api/candidates/[id]/used", () => {
  beforeEach(() => {
    vi.stubEnv("APP_ORIGIN", ORIGIN);
    h.calls = [];
    h.impl = async (id, used) => ({ id, used, used_at: used ? "2026-11-18T00:00:00Z" : null, extra: "x" });
  });

  it.each([["https://evil.com"], [null]])("Origin이 다르거나 없으면 403, API 호출 없음: %s", async (origin) => {
    expect((await call(ID, '{"used":true}', origin)).status).toBe(403);
    expect(h.calls).toHaveLength(0);
  });

  it.each(["not-a-uuid", `${ID}x`])("UUID가 아니면 400: %s", async (id) => {
    expect((await call(id, '{"used":true}')).status).toBe(400);
    expect(h.calls).toHaveLength(0);
  });

  it.each(['{"used":"true"}', '{"used":1}', "{}", "null", "{broken", ""])("본문이 boolean이 아니거나 깨지면 400: %s", async (b) => {
    expect((await call(ID, b)).status).toBe(400);
    expect(h.calls).toHaveLength(0);
  });

  it("성공: 계약 필드만 + no-store", async () => {
    const res = await call(ID, '{"used":false}');
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(await res.json()).toEqual({ id: ID, used: false, used_at: null });
    expect(h.calls).toEqual([[ID, false]]);
  });

  it("오류 매핑: 401·403·404·422→400·그 외 502", async () => {
    h.impl = fail(401);
    const un = await call(ID, '{"used":true}');
    expect(un.status).toBe(401);
    expect(un.headers.get("location")).toBeNull();
    h.impl = fail(403);
    expect(await (await call(ID, '{"used":true}')).json()).toEqual({ code: "FORBIDDEN", message: "이 후보를 바꿀 권한이 없습니다." });
    h.impl = fail(404);
    const nf = await call(ID, '{"used":true}');
    expect(nf.status).toBe(404);
    expect(await nf.json()).toEqual({ code: "NOT_FOUND", message: "후보를 찾을 수 없습니다." });
    h.impl = fail(422);
    expect((await call(ID, '{"used":true}')).status).toBe(400);
    h.impl = fail(500);
    expect((await call(ID, '{"used":true}')).status).toBe(502);
    h.impl = fail(0);
    expect((await call(ID, '{"used":true}')).status).toBe(502);
  });
});
