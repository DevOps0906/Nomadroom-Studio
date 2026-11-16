import { beforeEach, describe, expect, it, vi } from "vitest";

const { verifyOtp, getVerifiedClaims, set, redirect } = vi.hoisted(() => ({
  verifyOtp: vi.fn(),
  getVerifiedClaims: vi.fn(),
  set: vi.fn(),
  redirect: vi.fn((to: string) => {
    throw new Error(`REDIRECT:${to}`);
  }),
}));
vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({ cookies: async () => ({ set }) }));
vi.mock("next/navigation", () => ({ redirect }));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: async () => ({ auth: { verifyOtp } }), SESSION_COOKIE_OPTIONS: { httpOnly: true } }));
vi.mock("@/server/auth/session", () => ({ getVerifiedClaims }));

const { confirmRecovery } = await import("./actions");
const form = (fields: Record<string, string>) => {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.set(k, v);
  return fd;
};

describe("confirmRecovery (POST)", () => {
  beforeEach(() => {
    verifyOtp.mockReset();
    getVerifiedClaims.mockReset();
    set.mockReset();
  });

  it("recovery 토큰 검증 성공 → 표식 쿠키 + /reset-password", async () => {
    verifyOtp.mockResolvedValue({ error: null });
    getVerifiedClaims.mockResolvedValue({ sub: "u", session_id: "s1" });
    await expect(confirmRecovery(form({ token_hash: "h", type: "recovery" }))).rejects.toThrow("REDIRECT:/reset-password");
    expect(verifyOtp).toHaveBeenCalledWith({ type: "recovery", token_hash: "h" });
    expect(set).toHaveBeenCalledWith("pw_recovery", "s1", expect.objectContaining({ httpOnly: true, maxAge: 600 }));
  });

  it.each([
    ["type이 recovery가 아님", { token_hash: "h", type: "magiclink" }],
    ["token_hash 없음", { type: "recovery" }],
  ])("%s → 검증 없이 /forgot-password?error=link", async (_n, fields) => {
    await expect(confirmRecovery(form(fields))).rejects.toThrow("REDIRECT:/forgot-password?error=link");
    expect(verifyOtp).not.toHaveBeenCalled();
  });

  it("토큰 무효 → /forgot-password?error=link, 쿠키 없음", async () => {
    verifyOtp.mockResolvedValue({ error: { status: 403 } });
    await expect(confirmRecovery(form({ token_hash: "h", type: "recovery" }))).rejects.toThrow("REDIRECT:/forgot-password?error=link");
    expect(set).not.toHaveBeenCalled();
  });
});
