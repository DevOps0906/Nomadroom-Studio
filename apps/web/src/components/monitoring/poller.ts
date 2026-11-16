// 수집 진행 폴링(순수 로직, 타이머·가시성 주입). 근거: tasks/task-013.md#구현 결정(폴링 클라이언트).
// 3초 간격 · 탭 숨김이면 멈춤 · 이전 요청이 끝나기 전 새 요청 없음 · 오류면 간격 2배(최대 30초)
// · 종료 상태면 멈추고 onFinished · queued + 워커 오프라인이면 10초.
import { isTerminal, type JobView } from "./job";

export const POLL_MS = 3_000;
export const OFFLINE_POLL_MS = 10_000;
export const MAX_BACKOFF_MS = 30_000;

/** gone: 403·404(job이 없어졌거나 권한 밖) → 멈추고 활성 job을 다시 받는다. */
export type FetchResult = { kind: "ok"; job: JobView } | { kind: "unauthorized" } | { kind: "gone" } | { kind: "error" };

export type PollerDeps = {
  fetchJob: (id: string) => Promise<FetchResult>;
  onJob: (job: JobView) => void;
  onFinished: (job: JobView) => void;
  onUnauthorized: () => void;
  onGone: () => void;
  isHidden: () => boolean;
  /** 가시성 변경 구독. 해제 함수를 돌려준다. */
  onVisibilityChange: (cb: () => void) => () => void;
  setTimer?: (cb: () => void, ms: number) => unknown;
  clearTimer?: (handle: unknown) => void;
};

export type Poller = { start(jobId: string): void; stop(): void; readonly running: boolean };

/** 다음 간격: 오류 연속이면 base×2ⁿ(최대 30초), queued·워커 오프라인이면 10초. */
export function nextDelay(job: JobView | null, errorStreak: number): number {
  if (errorStreak > 0) return Math.min(POLL_MS * 2 ** errorStreak, MAX_BACKOFF_MS);
  if (job && job.status === "queued" && !job.worker_online) return OFFLINE_POLL_MS;
  return POLL_MS;
}

export function createPoller(deps: PollerDeps): Poller {
  const setTimer = deps.setTimer ?? ((cb, ms) => setTimeout(cb, ms));
  const clearTimer = deps.clearTimer ?? ((h) => clearTimeout(h as ReturnType<typeof setTimeout>));
  let jobId: string | null = null;
  let timer: unknown = null;
  let inFlight = false;
  let errors = 0;
  let last: JobView | null = null;
  let unsubscribe: (() => void) | null = null;
  let generation = 0;

  function cancelTimer() {
    if (timer !== null) clearTimer(timer);
    timer = null;
  }

  function schedule(ms: number) {
    cancelTimer();
    if (jobId === null || deps.isHidden()) return;
    timer = setTimer(tick, ms);
  }

  async function tick() {
    timer = null;
    if (jobId === null || deps.isHidden()) return;
    if (inFlight) {
      // 이전 job의 요청이 아직 끝나지 않았다(재시작 직후). 겹치지 않게 다음 간격으로 미룬다.
      schedule(POLL_MS);
      return;
    }
    inFlight = true;
    const gen = generation;
    const id = jobId;
    let res: FetchResult;
    try {
      res = await deps.fetchJob(id);
    } catch {
      res = { kind: "error" };
    }
    inFlight = false;
    if (gen !== generation || jobId === null) return; // 멈췄거나 다른 job으로 바뀜
    if (res.kind === "unauthorized") {
      stop();
      deps.onUnauthorized();
      return;
    }
    if (res.kind === "gone") {
      stop();
      deps.onGone();
      return;
    }
    if (res.kind === "error") {
      errors += 1;
      schedule(nextDelay(last, errors));
      return;
    }
    errors = 0;
    last = res.job;
    deps.onJob(res.job);
    if (isTerminal(res.job.status)) {
      const done = res.job;
      stop();
      deps.onFinished(done);
      return;
    }
    schedule(nextDelay(last, 0));
  }

  function onVisibility() {
    if (jobId === null) return;
    if (deps.isHidden()) cancelTimer();
    else if (!inFlight && timer === null) void tick();
  }

  function stop() {
    generation += 1;
    jobId = null;
    cancelTimer();
    unsubscribe?.();
    unsubscribe = null;
  }

  return {
    start(id) {
      stop();
      jobId = id;
      errors = 0;
      last = null;
      unsubscribe = deps.onVisibilityChange(onVisibility);
      schedule(POLL_MS);
    },
    stop,
    get running() {
      return jobId !== null;
    },
  };
}
