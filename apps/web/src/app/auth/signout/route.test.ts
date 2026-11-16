import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const { signOut, store } = vi.hoisted(() => {
  const jar = new Map<string, string>();
  return {
    signOut: vi.fn(),
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

const { POST } = await import("./route");
const URL_ = "https://studio.example.com/auth/signout";
const post = (origin: string) => POST(new NextRequest(URL_, { method: "POST", headers: { origin } }));

describe("POST /auth/signout", () => {
  beforeEach(() => {
    vi.stubEnv("APP_ORIGIN", "https://studio.example.com");
    signOut.mockReset();
    store.jar.clear();
    for (const name of ["sb-x-auth-token.0", "sb-x-auth-token.1", "pw_recovery", "other"]) store.jar.set(name, "v");
  });

  it("다른 Origin이면 403이고 로그아웃하지 않는다", async () => {
    const res = await post("https://evil.com");
    expect(res.status).toBe(403);
    expect(signOut).not.toHaveBeenCalled();
  });

  it("같은 Origin이면 로그아웃 후 /login으로 303", async () => {
    signOut.mockResolvedValue({ error: null });
    const res = await post("https://studio.example.com");
    expect(res.status).toBe(303);
    expect(res.headers.get("location")).toBe("https://studio.example.com/login");
    expect(signOut).toHaveBeenCalledOnce();
    expect(store.jar.has("pw_recovery")).toBe(false);
  });

  it("signOut 오류면 sb-* 쿠키를 직접 지운다(다른 쿠키는 유지)", async () => {
    signOut.mockResolvedValue({ error: { status: 500 } });
    const res = await post("https://studio.example.com");
    expect(res.status).toBe(303);
    expect([...store.jar.keys()]).toEqual(["other"]);
  });
});
