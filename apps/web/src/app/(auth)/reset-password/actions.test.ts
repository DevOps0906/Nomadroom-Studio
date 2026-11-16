import { beforeEach, describe, expect, it, vi } from "vitest";

const { auth, store, redirect } = vi.hoisted(() => {
  const jar = new Map<string, string>();
  return {
    auth: { updateUser: vi.fn(), signOut: vi.fn() },
    store: {
      jar,
      getAll: () => [...jar].map(([name, value]) => ({ name, value })),
      delete: (name: string) => jar.delete(name),
    },
    redirect: vi.fn((to: string) => {
      throw new Error(`REDIRECT:${to}`);
    }),
  };
});
vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({ cookies: async () => store }));
vi.mock("next/navigation", () => ({ redirect }));
vi.mock("@/server/auth/recovery-session", () => ({ getRecoverySession: async () => ({ auth }) }));

const { resetPassword } = await import("./actions");
const form = (password: string, confirm = password) => {
  const fd = new FormData();
  fd.set("password", password);
  fd.set("confirm", confirm);
  return fd;
};

describe("resetPassword 액션", () => {
  beforeEach(() => {
    auth.updateUser.mockReset().mockResolvedValue({ error: null });
    auth.signOut.mockReset();
    store.jar.clear();
    for (const name of ["sb-x-auth-token", "pw_recovery"]) store.jar.set(name, "v");
  });

  it("변경 후 전역 로그아웃(scope=global)하고 /login?reset=done", async () => {
    auth.signOut.mockResolvedValue({ error: null });
    await expect(resetPassword({ error: null }, form("NewPassw0rd!y"))).rejects.toThrow("REDIRECT:/login?reset=done");
    expect(auth.signOut).toHaveBeenCalledWith({ scope: "global" });
    expect(store.jar.has("pw_recovery")).toBe(false);
  });

  it("전역 로그아웃이 실패하면 sb-* 쿠키를 직접 지운다", async () => {
    auth.signOut.mockResolvedValue({ error: { status: 500 } });
    await expect(resetPassword({ error: null }, form("NewPassw0rd!y"))).rejects.toThrow("REDIRECT:/login?reset=done");
    expect(store.jar.size).toBe(0);
  });

  it("확인 불일치면 변경하지 않는다", async () => {
    expect((await resetPassword({ error: null }, form("a", "b"))).error).toContain("일치하지 않습니다");
    expect(auth.updateUser).not.toHaveBeenCalled();
  });
});
