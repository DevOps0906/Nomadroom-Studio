import { beforeEach, describe, expect, it, vi } from "vitest";

// collect-jobs route.test.ts와 같은 이유로 vi.fn 대신 단순 함수로 흉내 낸다.
const h = vi.hoisted(() => ({ impl: (async () => undefined) as (id: string) => Promise<unknown>, calls: 0 }));
vi.mock("server-only", () => ({}));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: vi.fn() }));
vi.mock("@/server/api/monitor", () => ({
  getEvidence: (id: string) => {
    h.calls += 1;
    return h.impl(id);
  },
}));

const { ApiError } = await import("@/server/api/client");
const { GET } = await import("./route");

const ID = "00000000-0000-4000-8000-0000000000e1";
const call = (id: string) => GET(new Request(`https://studio.example.com/api/evidence/${id}`), { params: Promise.resolve({ id }) });
const body = (over: Record<string, unknown> = {}) => ({
  candidate: { id: ID, title: "t", status: "excluded" },
  prev: { observed_at: "2026-11-15T00:00:00Z", view_count: 10 },
  curr: { observed_at: "2026-11-16T00:00:00Z", view_count: 20 },
  growth_pct: 100,
  reason: "growth_out_of_range",
  needs_prev: false,
  next_observation_at: null,
  ...over,
});

describe("GET /api/evidence/[id]", () => {
  beforeEach(() => {
    h.calls = 0;
    h.impl = async () => undefined;
  });

  it.each(["not-a-uuid", "..%2F..%2Fv1%2Fdashboard", `${ID}x`])("UUID가 아니면 400, API 호출 없음: %s", async (id) => {
    expect((await call(id)).status).toBe(400);
    expect(h.calls).toBe(0);
  });

  it("성공: 화면 필드 + no-store", async () => {
    h.impl = async () => ({ ...body(), internal: "x" });
    const res = await call(ID);
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    const json = await res.json();
    expect(json.evidence.reason).toBe("growth_out_of_range");
    expect(json.evidence).not.toHaveProperty("internal");
  });

  it("10종 밖 reason → null", async () => {
    h.impl = async () => body({ reason: "new_rule" });
    expect((await (await call(ID)).json()).evidence.reason).toBeNull();
  });

  it("API 401 → JSON 401(리다이렉트 아님)", async () => {
    h.impl = async () => {
      throw new ApiError(401, "UNAUTHENTICATED", "로그인이 필요합니다.");
    };
    const res = await call(ID);
    expect(res.status).toBe(401);
    expect(res.headers.get("location")).toBeNull();
  });

  it("404·403은 고정 문구, 해석 실패·그 밖의 오류는 502", async () => {
    h.impl = async () => {
      throw new ApiError(404, "UPSTREAM_404", "upstream detail");
    };
    const nf = await call(ID);
    expect(nf.status).toBe(404);
    expect(await nf.json()).toEqual({ code: "NOT_FOUND", message: "후보를 찾을 수 없습니다." });
    h.impl = async () => {
      throw new ApiError(403, "UPSTREAM_403", "upstream detail");
    };
    const fb = await call(ID);
    expect(fb.status).toBe(403);
    expect(await fb.json()).toEqual({ code: "FORBIDDEN", message: "이 후보를 볼 권한이 없습니다." });
    h.impl = async () => {
      throw new ApiError(0, "TIMEOUT", "t");
    };
    expect((await call(ID)).status).toBe(502);
    h.impl = async () => ({ broken: true });
    expect((await call(ID)).status).toBe(502);
  });
});
