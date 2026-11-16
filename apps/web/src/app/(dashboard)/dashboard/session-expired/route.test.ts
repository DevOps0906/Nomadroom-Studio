import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const { signOut, summary, store } = vi.hoisted(() => {
  const jar = new Map<string, string>();
  return {
    signOut: vi.fn(),
    summary: vi.fn(),
    store: {
      jar,
      getAll: () => [...jar].map(([name, value]) => ({ name, value })),
      delete: (name: string) => jar.delete(name),
    },
  };
});
vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({ cookies: async () => store }));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: async () => ({ auth: { signOut } }) }));
vi.mock("@/server/api/dashboard", () => ({ getDashboardSummary: summary }));

const { ApiError, SESSION_EXPIRED_PATH } = await import("@/server/api/client");
const { GET } = await import("./route");
const ORIGIN = "https://studio.example.com";
const get = () => GET(new NextRequest(`${ORIGIN}${SESSION_EXPIRED_PATH}`));

describe(`GET ${"/dashboard/session-expired"}`, () => {
  beforeEach(() => {
    signOut.mockReset();
    summary.mockReset();
    store.jar.clear();
    for (const name of ["sb-x-auth-token.0", "sb-x-auth-token.1", "other"]) store.jar.set(name, "v");
  });

  it("상수 경로와 이 라우트 위치가 같다", () => {
    expect(SESSION_EXPIRED_PATH).toBe("/dashboard/session-expired");
  });

  it("API가 401이면 signOut 실패와 무관하게 sb-* 쿠키를 지우고 /login으로 303", async () => {
    summary.mockRejectedValue(new ApiError(401, "UNAUTHENTICATED", "m"));
    signOut.mockRejectedValue(new Error("network"));
    const res = await get();
    expect(res.status).toBe(303);
    expect(res.headers.get("location")).toBe(`${ORIGIN}/login`);
    expect(signOut).toHaveBeenCalledOnce();
    // 세션 쿠키가 없으므로 proxy의 getClaims는 null → /login이 그대로 열린다(proxy.test "미로그인 공개 경로"). 루프 없음.
    expect([...store.jar.keys()]).toEqual(["other"]);
  });

  it("API가 이 세션을 받아 주면(위조 링크·프리페치) 로그아웃하지 않고 /dashboard로", async () => {
    summary.mockResolvedValue({});
    const res = await get();
    expect(res.headers.get("location")).toBe(`${ORIGIN}/dashboard`);
    expect(signOut).not.toHaveBeenCalled();
    expect(store.jar.size).toBe(3);
  });
});
