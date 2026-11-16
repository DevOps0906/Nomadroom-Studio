import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { signInWithPassword, redirect, net } = vi.hoisted(() => ({
  signInWithPassword: vi.fn(),
  redirect: vi.fn((to: string) => {
    throw new Error(`REDIRECT:${to}`);
  }),
  net: { ip: "" },
}));

vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({ headers: async () => new Headers({ "x-forwarded-for": net.ip }) }));
vi.mock("next/navigation", () => ({ redirect }));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: async () => ({ auth: { signInWithPassword } }) }));

const { login } = await import("./actions");
const INITIAL = { error: null, email: "" };
const form = (email: string, password: string, next = "") => {
  const fd = new FormData();
  fd.set("email", email);
  fd.set("password", password);
  fd.set("next", next);
  return fd;
};

let testNo = 0;

describe("login 액션", () => {
  beforeEach(() => {
    vi.stubEnv("APP_ORIGIN", "https://studio.example.com");
    signInWithPassword.mockReset();
    // 테스트마다 다른 IP → 모듈 전역 limiter 상태가 테스트 사이에 섞이지 않는다.
    net.ip = `203.0.113.${++testNo}`;
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("성공하면 안전한 next로 이동(외부 next는 /)", async () => {
    signInWithPassword.mockResolvedValue({ error: null });
    await expect(login(INITIAL, form("a@b.c", "pw", "//evil.com"))).rejects.toThrow("REDIRECT:/");
  });

  it("안전한 next(/monitor)는 유지한다", async () => {
    signInWithPassword.mockResolvedValue({ error: null });
    await expect(login(INITIAL, form("a@b.c", "pw", "/monitor"))).rejects.toThrow("REDIRECT:/monitor");
  });

  it("점 세그먼트 우회(/%2E//evil.com) next는 /", async () => {
    signInWithPassword.mockResolvedValue({ error: null });
    await expect(login(INITIAL, form("a@b.c", "pw", "/%2E//evil.com"))).rejects.toThrow(/^REDIRECT:\/$/);
  });

  it("자격 불일치(400)는 credentials, 이메일만 돌려준다", async () => {
    signInWithPassword.mockResolvedValue({ error: { status: 400 } });
    expect(await login(INITIAL, form("a@b.c", "wrong"))).toEqual({ error: "credentials", email: "a@b.c" });
  });

  it("실패 로그는 event·reason만 남기고 이메일·IP·비밀번호를 남기지 않는다", async () => {
    signInWithPassword.mockResolvedValue({ error: { status: 400 } });
    await login(INITIAL, form("op@example.com", "Secret-pw-1"));
    expect(console.warn).toHaveBeenCalledOnce();
    const line = String(vi.mocked(console.warn).mock.calls[0][0]);
    expect(JSON.parse(line)).toEqual({ event: "login_failed", reason: "credentials" });
    for (const secret of ["op@example.com", "Secret-pw-1", net.ip]) expect(line).not.toContain(secret);
  });

  it("Supabase 429는 rate_limited", async () => {
    signInWithPassword.mockResolvedValue({ error: { status: 429 } });
    expect((await login(INITIAL, form("a@b.c", "pw"))).error).toBe("rate_limited");
  });

  it("같은 IP에서 10회를 넘기면 Supabase를 부르지 않고 rate_limited(429)", async () => {
    signInWithPassword.mockResolvedValue({ error: { status: 400 } });
    for (let i = 0; i < 10; i++) expect((await login(INITIAL, form("a@b.c", "x"))).error).toBe("credentials");
    signInWithPassword.mockClear();
    expect(await login(INITIAL, form("a@b.c", "x"))).toEqual({ error: "rate_limited", email: "a@b.c" });
    expect(signInWithPassword).not.toHaveBeenCalled();
  });
});
