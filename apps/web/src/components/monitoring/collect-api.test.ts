import { describe, expect, it, vi } from "vitest";

// A-05 실행 호출 타임아웃 고정: 검색 수집은 서버가 동기 처리해 기본 10초를 넘을 수 있다.
const apiFetch = vi.fn(async () => ({ job: { id: "j" } }));
vi.mock("server-only", () => ({}));
vi.mock("@/server/api/client", () => ({ apiFetch }));

const { createCollectJob, retryCollectJob, VERIFY_TIMEOUT_MS } = await import("@/server/api/monitor");
const { toActionFailure, RATE_LIMITED_MESSAGE } = await import("./messages");

describe("A-05 실행 타임아웃", () => {
  it("생성·재시도는 60초", async () => {
    await createCollectJob("k", ["p"]);
    await retryCollectJob("j");
    expect(VERIFY_TIMEOUT_MS).toBe(60_000);
    expect(apiFetch).toHaveBeenNthCalledWith(1, "/v1/collect-jobs", expect.objectContaining({ timeoutMs: VERIFY_TIMEOUT_MS }));
    expect(apiFetch).toHaveBeenNthCalledWith(2, "/v1/collect-jobs/j/retry", expect.objectContaining({ timeoutMs: VERIFY_TIMEOUT_MS }));
  });

  it("재시도 429 RATE_LIMITED는 기존 문구", () => {
    expect(toActionFailure({ status: 429, code: "RATE_LIMITED", message: "x" })).toEqual({ ok: false, message: RATE_LIMITED_MESSAGE, keepKey: false });
  });
});
