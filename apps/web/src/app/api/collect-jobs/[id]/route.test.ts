import { beforeEach, describe, expect, it, vi } from "vitest";

// vi.fn이 거부 Promise를 돌려주면 vitest 4.1이 처리된 거부도 실패로 보고해(원인 미확인) 단순 함수로 흉내 낸다.
const h = vi.hoisted(() => ({ impl: (async () => undefined) as (id: string) => Promise<unknown>, calls: 0 }));
vi.mock("server-only", () => ({}));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: vi.fn() }));
vi.mock("@/server/api/monitor", () => ({
  getCollectJob: (id: string) => {
    h.calls += 1;
    return h.impl(id);
  },
}));

const { ApiError } = await import("@/server/api/client");
const { GET } = await import("./route");

const ID = "00000000-0000-4000-8000-0000000000f1";
const call = (id: string) => GET(new Request(`https://studio.example.com/api/collect-jobs/${id}`), { params: Promise.resolve({ id }) });

describe("GET /api/collect-jobs/[id]", () => {
  beforeEach(() => {
    h.calls = 0;
    h.impl = async () => undefined;
  });

  it.each(["not-a-uuid", "..%2F..%2Fv1%2Fdashboard", `${ID}x`])("UUID가 아니면 400, API 호출 없음: %s", async (id) => {
    const res = await call(id);
    expect(res.status).toBe(400);
    expect(h.calls).toBe(0);
  });

  it("API 401 → JSON 401(리다이렉트 아님)", async () => {
    h.impl = async () => {
      throw new ApiError(401, "UNAUTHENTICATED", "로그인이 필요합니다.");
    };
    const res = await call(ID);
    expect(res.status).toBe(401);
    expect(res.headers.get("location")).toBeNull();
    expect(await res.json()).toMatchObject({ code: "UNAUTHENTICATED" });
  });

  it("성공: 화면 필드만 + no-store", async () => {
    h.impl = async () => ({
      id: ID,
      status: "running",
      error: null,
      stop_requested: false,
      retry_count: 0,
      profiles: [],
      result: { candidates: 1, producible: 0, pending: 1 },
      worker_last_seen_at: "2026-11-17T00:00:00Z",
      worker_online: true,
      claimed_by: "w",
    });
    const res = await call(ID);
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    const body = await res.json();
    expect(body.job.id).toBe(ID);
    expect(body.job).not.toHaveProperty("claimed_by");
    expect(body.job).not.toHaveProperty("worker_last_seen_at");
  });

  it("404는 그대로, 그 밖의 오류는 502", async () => {
    h.impl = async () => {
      throw new ApiError(404, "NOT_FOUND", "찾을 수 없습니다.");
    };
    expect((await call(ID)).status).toBe(404);
    h.impl = async () => {
      throw new ApiError(0, "TIMEOUT", "t");
    };
    expect((await call(ID)).status).toBe(502);
  });
});
