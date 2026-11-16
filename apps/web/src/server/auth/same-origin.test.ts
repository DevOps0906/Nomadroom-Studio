import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
const { assertSameOrigin } = await import("./same-origin");

const ORIGIN = "https://studio.example.com";
const post = (headers: Record<string, string>) => new Request(`${ORIGIN}/auth/signout`, { method: "POST", headers });

describe("assertSameOrigin", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("같은 Origin이면 통과(null)", () => {
    expect(assertSameOrigin(post({ origin: ORIGIN }), ORIGIN)).toBeNull();
  });

  it.each([
    ["다른 Origin", { origin: "https://evil.com" }],
    ["포트만 다름", { origin: "https://studio.example.com:8443" }],
    ["Origin 없음", {}],
    ["null Origin", { origin: "null" }],
  ])("%s → 403", (_name, headers: Record<string, string>) => {
    expect(assertSameOrigin(post(headers), ORIGIN)?.status).toBe(403);
  });

  it("기본값은 APP_ORIGIN 환경변수", () => {
    vi.stubEnv("APP_ORIGIN", `${ORIGIN}/`);
    expect(assertSameOrigin(post({ origin: ORIGIN }))).toBeNull();
    expect(assertSameOrigin(post({ origin: "https://evil.com" }))?.status).toBe(403);
  });
});
