// A-05 수집 작업의 화면용 모양(순수). 계약: docs/04_API.md#A-05. 서버(Route Handler)와 클라이언트가 같이 쓴다.

export type JobStatus = "queued" | "running" | "retrying" | "stopped" | "failed" | "done";
export type ChromeState = "ready" | "resize_needed" | "login_needed" | "error";
export type RunStatus = "pending" | "running" | "done" | "failed";
/** 수집 방식. youtube_search는 서버가 동기로 처리해 끝난 job이 온다(워커·Chrome 없음). */
export type JobSource = "vidiq" | "youtube_search";

export type JobProfileRun = {
  profile_id: string;
  chrome_state: ChromeState | null;
  detail: string | null;
  status: RunStatus;
  collected_count: number;
};

/** 화면에 필요한 필드만. GET /v1/collect-jobs/{id}·/active 응답의 부분집합. */
export type JobView = {
  id: string;
  source: JobSource;
  status: JobStatus;
  error: string | null;
  stop_requested: boolean;
  retry_count: number;
  profiles: JobProfileRun[];
  result: { candidates: number; producible: number; pending: number } | null;
  worker_online: boolean;
};

const JOB_STATUSES: JobStatus[] = ["queued", "running", "retrying", "stopped", "failed", "done"];
const CHROME_STATES: ChromeState[] = ["ready", "resize_needed", "login_needed", "error"];
const RUN_STATUSES: RunStatus[] = ["pending", "running", "done", "failed"];
const SOURCES: JobSource[] = ["vidiq", "youtube_search"];
export const TERMINAL: JobStatus[] = ["done", "failed", "stopped"];
export const RETRY_LIMIT = 3;

export function isTerminal(status: JobStatus): boolean {
  return TERMINAL.includes(status);
}

function oneOf<T extends string>(v: unknown, list: T[]): T | null {
  return typeof v === "string" && (list as string[]).includes(v) ? (v as T) : null;
}

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 0);
const strOrNull = (v: unknown) => (typeof v === "string" ? v : null);

/** API 응답의 job 객체에서 화면 필드만 뽑는다. 모양이 맞지 않으면 null. */
export function pickJob(raw: unknown): JobView | null {
  if (typeof raw !== "object" || raw === null) return null;
  const j = raw as Record<string, unknown>;
  const status = oneOf(j.status, JOB_STATUSES);
  if (typeof j.id !== "string" || !status) return null;
  const profiles: JobProfileRun[] = Array.isArray(j.profiles)
    ? j.profiles.flatMap((p) => {
        if (typeof p !== "object" || p === null) return [];
        const r = p as Record<string, unknown>;
        if (typeof r.profile_id !== "string") return [];
        return [
          {
            profile_id: r.profile_id,
            chrome_state: oneOf(r.chrome_state, CHROME_STATES),
            detail: strOrNull(r.detail),
            status: oneOf(r.status, RUN_STATUSES) ?? "pending",
            collected_count: num(r.collected_count),
          },
        ];
      })
    : [];
  const res = typeof j.result === "object" && j.result !== null ? (j.result as Record<string, unknown>) : null;
  return {
    id: j.id,
    source: oneOf(j.source, SOURCES) ?? "vidiq",
    status,
    error: strOrNull(j.error),
    stop_requested: j.stop_requested === true,
    retry_count: num(j.retry_count),
    profiles,
    result: res ? { candidates: num(res.candidates), producible: num(res.producible), pending: num(res.pending) } : null,
    worker_online: j.worker_online === true,
  };
}
