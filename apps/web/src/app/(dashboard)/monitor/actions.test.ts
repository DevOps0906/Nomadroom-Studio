import { beforeEach, describe, expect, it, vi } from "vitest";

const m = vi.hoisted(() => ({
  redirect: vi.fn((to: string) => {
    throw new Error(`REDIRECT:${to}`);
  }),
  createCollectJob: vi.fn(),
  getCollectJob: vi.fn(),
  retryCollectJob: vi.fn(),
  stopCollectJob: vi.fn(),
  runVerify: vi.fn(),
}));
vi.mock("server-only", () => ({}));
vi.mock("next/navigation", () => ({ redirect: m.redirect }));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: vi.fn() }));
vi.mock("@/server/api/monitor", () => ({
  createCollectJob: m.createCollectJob,
  getCollectJob: m.getCollectJob,
  retryCollectJob: m.retryCollectJob,
  stopCollectJob: m.stopCollectJob,
  runVerify: m.runVerify,
}));

const { ApiError, SESSION_EXPIRED_PATH } = await import("@/server/api/client");
const { startCollect, retryCollect, stopCollect, verifyRecords } = await import("./actions");
const { QUOTA_MESSAGE, VERIFY_TIMEOUT_MESSAGE } = await import("@/components/monitoring/messages");

const KEY = "00000000-0000-4000-8000-00000000c0de";
const JOB = "00000000-0000-4000-8000-0000000000f1";
const P = (n: number) => `00000000-0000-4000-8000-0000000000a${n}`;
const jobRow = { id: JOB, status: "queued", error: null, stop_requested: false, retry_count: 0, profiles: [] };

describe("MON-01 Server Actions", () => {
  beforeEach(() => {
    for (const f of Object.values(m)) f.mockReset();
    m.redirect.mockImplementation((to: string) => {
      throw new Error(`REDIRECT:${to}`);
    });
  });

  it("키·프로필 id가 UUID가 아니거나 4개 이상이면 API 호출 없이 거부", async () => {
    for (const [key, ids] of [
      ["not-uuid", [P(1)]],
      [KEY, ["x"]],
      [KEY, []],
      [KEY, [P(1), P(2), P(3), P(4)]],
      [KEY, "a"],
    ] as const) {
      expect(await startCollect(key, ids)).toMatchObject({ ok: false });
      expect(await verifyRecords(key, ids)).toMatchObject({ ok: false });
    }
    expect(await retryCollect("../x")).toMatchObject({ ok: false });
    expect(await stopCollect(1)).toMatchObject({ ok: false });
    expect(m.createCollectJob).not.toHaveBeenCalled();
    expect(m.runVerify).not.toHaveBeenCalled();
    expect(m.retryCollectJob).not.toHaveBeenCalled();
  });

  it("후보 가져오기: 키와 선택한 profile_ids(중복 제거)를 보내고 상세로 워커 상태를 채운다", async () => {
    m.createCollectJob.mockResolvedValue(jobRow);
    m.getCollectJob.mockResolvedValue({ ...jobRow, result: { candidates: 0, producible: 0, pending: 0 }, worker_online: false });
    const res = await startCollect(KEY, [P(1), P(2), P(1)]);
    expect(m.createCollectJob).toHaveBeenCalledWith(KEY, [P(1), P(2)]);
    expect(res).toMatchObject({ ok: true, job: { id: JOB, status: "queued", worker_online: false } });
  });

  it("401 → 세션 정리 경로", async () => {
    m.createCollectJob.mockRejectedValue(new ApiError(401, "UNAUTHENTICATED", "x"));
    await expect(startCollect(KEY, [P(1)])).rejects.toThrow(`REDIRECT:${SESSION_EXPIRED_PATH}`);
  });

  it("429 QUOTA_EXCEEDED 문구, 키 교체", async () => {
    m.runVerify.mockRejectedValue(new ApiError(429, "QUOTA_EXCEEDED", "x"));
    expect(await verifyRecords(KEY, [P(1)])).toEqual({ ok: false, message: QUOTA_MESSAGE, keepKey: false });
  });

  it("기록 검증 타임아웃: 진행 중 안내 + 키 유지", async () => {
    m.runVerify.mockRejectedValue(new ApiError(0, "TIMEOUT", "t"));
    expect(await verifyRecords(KEY, [P(1)])).toEqual({ ok: false, message: VERIFY_TIMEOUT_MESSAGE, keepKey: true });
  });

  it("기록 검증 성공 결과", async () => {
    m.runVerify.mockResolvedValue({ job: { id: JOB, kind: "verify", status: "done" }, checked: 4, skipped_recent: 1, failed: 0, counts: null });
    expect(await verifyRecords(KEY, [P(1)])).toEqual({ ok: true, checked: 4, skipped: 1, failed: 0 });
    expect(m.runVerify).toHaveBeenCalledWith(KEY, [P(1)]);
  });

  it("중지 409는 API 고정 문구", async () => {
    m.stopCollectJob.mockRejectedValue(new ApiError(409, "CONFLICT", "이미 종료된 작업입니다."));
    expect(await stopCollect(JOB)).toMatchObject({ ok: false, message: "이미 종료된 작업입니다." });
  });

  it("재시도 성공 → retrying job", async () => {
    m.retryCollectJob.mockResolvedValue({ ...jobRow, status: "retrying" });
    m.getCollectJob.mockRejectedValue(new ApiError(0, "NETWORK", "n"));
    expect(await retryCollect(JOB)).toMatchObject({ ok: true, job: { status: "retrying", worker_online: true } });
  });

  it("응답 job 모양이 틀리고 상세도 실패하면 빈 객체 대신 실패 결과", async () => {
    m.createCollectJob.mockResolvedValue({ unexpected: true });
    m.getCollectJob.mockRejectedValue(new ApiError(0, "NETWORK", "n"));
    const res = await startCollect(KEY, [P(1)]);
    expect(res).toMatchObject({ ok: false });
    expect(res).not.toHaveProperty("job");
    m.stopCollectJob.mockResolvedValue({ id: 1 });
    m.getCollectJob.mockResolvedValue({ id: JOB, status: "weird" });
    expect(await stopCollect(JOB)).toMatchObject({ ok: false });
  });
});
