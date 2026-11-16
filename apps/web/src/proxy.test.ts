import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest, type NextResponse } from "next/server";

const { state } = vi.hoisted(() => ({ state: { claims: null as object | null, refresh: false } }));
vi.mock("server-only", () => ({}));
vi.mock("@/server/auth/session", () => ({ getVerifiedClaims: async () => state.claims }));
// 세션 갱신 흉내: setAll이 쿠키와 Cache-Control 헤더를 응답에 쓴다.
vi.mock("@/server/supabase/client", () => ({
  createProxySupabase: (_req: NextRequest, getResponse: () => NextResponse) => {
    if (state.refresh) {
      const res = getResponse();
      res.cookies.set("sb-x-auth-token", "new", { httpOnly: true });
      res.headers.set("cache-control", "private, no-cache, no-store, must-revalidate, max-age=0");
    }
    return {};
  },
}));

const { proxy, config } = await import("./proxy");
const ORIGIN = "https://studio.example.com";
const req = (path: string) => new NextRequest(`${ORIGIN}${path}`);

describe("proxy", () => {
  beforeEach(() => {
    vi.stubEnv("APP_ORIGIN", ORIGIN);
    state.claims = null;
    state.refresh = false;
  });

  it.each(["/login", "/forgot-password", "/auth/confirm", "/terms"])("미로그인 공개 경로 %s는 통과", async (path) => {
    const res = await proxy(req(path));
    expect(res.headers.get("location")).toBeNull();
  });

  it("미로그인 보호 경로 → /login?next=인코딩 경로", async () => {
    const res = await proxy(req("/monitor?tab=a"));
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe(`${ORIGIN}/login?next=${encodeURIComponent("/monitor?tab=a")}`);
  });

  it("미로그인 / → next 없이 /login", async () => {
    expect((await proxy(req("/"))).headers.get("location")).toBe(`${ORIGIN}/login`);
  });

  it("로그인 상태에서 /login·/forgot-password → /", async () => {
    state.claims = { sub: "u" };
    for (const path of ["/login", "/forgot-password"]) expect((await proxy(req(path))).headers.get("location")).toBe(`${ORIGIN}/`);
    expect((await proxy(req("/terms"))).headers.get("location")).toBeNull();
  });

  it("리다이렉트 응답에도 갱신 쿠키와 Cache-Control을 옮기고 내부 헤더는 옮기지 않는다", async () => {
    state.refresh = true;
    const res = await proxy(req("/dashboard"));
    expect(res.status).toBe(307);
    expect(res.cookies.get("sb-x-auth-token")?.value).toBe("new");
    expect(res.headers.get("cache-control")).toContain("no-store");
    // NextResponse.next({ request })의 내부 헤더(x-middleware-next·override·request-*)는 리다이렉트에 없어야 한다.
    const internal = [...res.headers.keys()].filter((k) => k.startsWith("x-middleware-") && k !== "x-middleware-set-cookie");
    expect(internal).toEqual([]);
  });

  it("matcher는 점(.)을 이스케이프한 정규식이다", () => {
    const inner = config.matcher[0].slice(1).replace(/^\(\(\?!/, "^(?!").replace(/\)\.\*\)$/, ")");
    const excluded = new RegExp(inner);
    expect(excluded.test("logo.png")).toBe(false);
    expect(excluded.test("loginpng")).toBe(true);
    expect(excluded.test("login")).toBe(true);
  });
});
