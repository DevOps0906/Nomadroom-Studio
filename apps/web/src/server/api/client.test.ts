import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: vi.fn() }));

const { ApiError, apiFetch, buildApiUrl, classifyApiError, parseApiBaseUrl, sendApiRequest, toApiError } = await import("./client");
const { createServerSupabase } = await import("@/server/supabase/client");

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const send = (fetchImpl: typeof fetch, timeoutMs?: number) =>
  sendApiRequest("/v1/dashboard/summary", { query: { period: "24h", skip: undefined } }, {
    baseUrl: "http://api.test",
    token: "tok",
    fetchImpl,
    timeoutMs,
  });

const caught = (p: Promise<unknown>) => p.then(() => { throw new Error("성공하면 안 됨"); }, (e: unknown) => e as InstanceType<typeof ApiError>);

describe("sendApiRequest", () => {
  it("Bearer 토큰·쿼리를 붙여 GET하고 본문을 돌려준다", async () => {
    const fetchImpl = vi.fn(async () => json(200, { ok: 1 })) as unknown as typeof fetch;
    await expect(send(fetchImpl)).resolves.toEqual({ ok: 1 });
    const [url, init] = vi.mocked(fetchImpl).mock.calls[0] as [URL, RequestInit];
    expect(url.toString()).toBe("http://api.test/v1/dashboard/summary?period=24h");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
    expect(init.cache).toBe("no-store");
  });

  it("401은 UNAUTHENTICATED → login", async () => {
    const e = await caught(send((async () => json(401, { code: "UNAUTHENTICATED", message: "인증이 필요합니다." })) as typeof fetch));
    expect(e).toBeInstanceOf(ApiError);
    expect([e.status, e.code]).toEqual([401, "UNAUTHENTICATED"]);
    expect(classifyApiError(e)).toBe("login");
  });

  it("403 FORBIDDEN → forbidden, field 유지", async () => {
    const e = await caught(send((async () => json(403, { code: "FORBIDDEN", message: "권한 없음", field: "x" })) as typeof fetch));
    expect([e.status, e.code, e.message, e.field]).toEqual([403, "FORBIDDEN", "권한 없음", "x"]);
    expect(classifyApiError(e)).toBe("forbidden");
  });

  it("5xx·형식 아닌 본문은 상태 코드 기본값 → error", async () => {
    const e = await caught(send((async () => new Response("<html>bad gateway</html>", { status: 502 })) as typeof fetch));
    expect([e.status, e.code]).toEqual([502, "INTERNAL"]);
    expect(e.message).not.toContain("html");
    expect(classifyApiError(e)).toBe("error");
    const up = await caught(send((async () => json(503, { code: "UPSTREAM_ERROR", message: "데이터 저장소 요청에 실패했습니다." })) as typeof fetch));
    expect([up.status, up.code]).toEqual([503, "UPSTREAM_ERROR"]);
  });

  it("타임아웃이면 status 0 TIMEOUT", async () => {
    const hang = ((_: unknown, init: RequestInit) =>
      new Promise((_r, reject) => init.signal!.addEventListener("abort", () => reject(init.signal!.reason)))) as unknown as typeof fetch;
    const e = await caught(send(hang, 20));
    expect([e.status, e.code]).toEqual([0, "TIMEOUT"]);
    expect(classifyApiError(e)).toBe("error");
  });

  it("연결 실패면 status 0 NETWORK", async () => {
    const e = await caught(send((async () => { throw new TypeError("fetch failed"); }) as typeof fetch));
    expect([e.status, e.code]).toEqual([0, "NETWORK"]);
  });
});

describe("toApiError·classifyApiError", () => {
  it("403이지만 FORBIDDEN이 아니면 error", () => {
    expect(classifyApiError(toApiError(403, { code: "OTHER", message: "m" }))).toBe("error");
  });
  it("ApiError가 아니면 error", () => {
    expect(classifyApiError(new Error("x"))).toBe("error");
  });
  it("본문이 없으면 401 기본 문구", () => {
    const e = toApiError(401, null);
    expect([e.code, e.message]).toEqual(["UNAUTHENTICATED", "로그인이 필요합니다."]);
  });
});

describe("응답 본문 오류", () => {
  it("2xx인데 본문을 해석하지 못하면 INTERNAL(status 유지)", async () => {
    const e = await caught(send((async () => new Response("not json", { status: 200 })) as typeof fetch));
    expect([e.status, e.code]).toEqual([200, "INTERNAL"]);
    expect(classifyApiError(e)).toBe("error");
  });

  it("204는 본문 없이 성공", async () => {
    await expect(send((async () => new Response(null, { status: 204 })) as typeof fetch)).resolves.toBeUndefined();
  });

  it("본문을 읽다가 시간이 다 되면 TIMEOUT", async () => {
    const stalled = (async (_: unknown, init: RequestInit) =>
      new Response(
        new ReadableStream({
          start(c) {
            c.enqueue(new TextEncoder().encode("{"));
            init.signal!.addEventListener("abort", () => c.error(init.signal!.reason));
          },
        }),
        { status: 200 },
      )) as unknown as typeof fetch;
    const e = await caught(send(stalled, 20));
    expect([e.status, e.code]).toEqual([0, "TIMEOUT"]);
  });
});

describe("URL 조립·API_BASE_URL 검증", () => {
  it("base 경로 접두사를 유지한다", () => {
    expect(buildApiUrl("https://api.test/prefix", "/v1/x").toString()).toBe("https://api.test/prefix/v1/x");
    expect(buildApiUrl("https://api.test/prefix/", "/v1/x").toString()).toBe("https://api.test/prefix/v1/x");
  });

  it.each(["https://evil.test/v1/x", "//evil.test/v1/x", "v1/x", "/v2/x", "/v1/../../x"])("허용하지 않는 path %s는 throw", (path) => {
    expect(() => buildApiUrl("https://api.test/prefix", path)).toThrow();
  });

  it("절대 경로는 요청을 보내지 않고 거부한다", async () => {
    const fetchImpl = vi.fn() as unknown as typeof fetch;
    await expect(sendApiRequest("https://evil.test/v1/x", {}, { baseUrl: "https://api.test", token: "t", fetchImpl })).rejects.toThrow();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("운영은 https만, userinfo·비 http 스킴 거부", () => {
    expect(parseApiBaseUrl("https://api.test", "production")).toBe("https://api.test");
    expect(parseApiBaseUrl("http://localhost:8000", "development")).toBe("http://localhost:8000");
    expect(() => parseApiBaseUrl("http://api.test", "production")).toThrow("https");
    expect(() => parseApiBaseUrl("https://u:p@api.test", "production")).toThrow("사용자 정보");
    expect(() => parseApiBaseUrl("https://u@api.test", "development")).toThrow("사용자 정보");
    expect(() => parseApiBaseUrl("ftp://api.test", "development")).toThrow();
    expect(() => parseApiBaseUrl("not a url", "development")).toThrow();
  });
});

describe("apiFetch", () => {
  const supa = (claims: object | null, token: string | null) => ({
    auth: {
      getClaims: async () => ({ data: claims ? { claims } : null, error: null }),
      getSession: async () => ({ data: { session: token ? { access_token: token } : null } }),
    },
  });
  const useSupabase = (claims: object | null, token: string | null) =>
    vi.mocked(createServerSupabase).mockResolvedValue(supa(claims, token) as never);

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("claims가 없으면 요청 없이 401", async () => {
    useSupabase(null, "tok");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const e = await caught(apiFetch("/v1/dashboard/summary"));
    expect([e.status, classifyApiError(e)]).toEqual([401, "login"]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("토큰이 없으면 요청 없이 401", async () => {
    useSupabase({ sub: "u" }, null);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const e = await caught(apiFetch("/v1/dashboard/summary"));
    expect(e.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("API_BASE_URL이 없으면 throw", async () => {
    useSupabase({ sub: "u" }, "tok");
    vi.stubEnv("API_BASE_URL", "");
    await expect(apiFetch("/v1/dashboard/summary")).rejects.toThrow("API_BASE_URL");
  });

  it("운영에서 http base면 throw", async () => {
    useSupabase({ sub: "u" }, "tok");
    vi.stubEnv("API_BASE_URL", "http://api.test");
    vi.stubEnv("NODE_ENV", "production");
    await expect(apiFetch("/v1/dashboard/summary")).rejects.toThrow("https");
  });

  it("세션 토큰을 Bearer로 base 아래 경로에 보낸다", async () => {
    useSupabase({ sub: "u" }, "tok");
    vi.stubEnv("API_BASE_URL", "https://api.test/base");
    const fetchMock = vi.fn(async () => json(200, { ok: 1 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiFetch("/v1/profiles")).resolves.toEqual({ ok: 1 });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
    expect(url.toString()).toBe("https://api.test/base/v1/profiles");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
  });

  it("ok인데 본문 오류면 INTERNAL", async () => {
    useSupabase({ sub: "u" }, "tok");
    vi.stubEnv("API_BASE_URL", "https://api.test");
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>", { status: 200 })));
    const e = await caught(apiFetch("/v1/profiles"));
    expect([e.status, e.code]).toEqual([200, "INTERNAL"]);
  });
});
