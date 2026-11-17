import { cn } from "@/lib/utils";
import { RETRY_LIMIT, isTerminal, type JobView } from "./job";
import { CHROME_STATE_LABEL, UNKNOWN_CAUSE, VIDIQ_PENDING_MESSAGE, WORKER_OFFLINE_MESSAGE, chromeDetailLabel, jobErrorLabel } from "./messages";
import { FOCUS, PANEL } from "./monitor-view";

// Chrome 준비 결과 카드(상태 없는 뷰): 프로필별 Chrome 상태·원인·진행 + 재시도·수집 중지.
// YouTube 검색 수집(source=youtube_search)은 Chrome·워커가 없다: Chrome 상태·워커 오프라인·중지를 숨기고 vidIQ 준비 중 안내만.

const JOB_STATUS_LABEL: Record<JobView["status"], string> = {
  queued: "대기 중",
  running: "후보 가져오는 중",
  retrying: "재시도 대기 중",
  stopped: "중지됨",
  failed: "수집 실패",
  done: "완료",
};

const RUN_STATUS_LABEL = { pending: "대기", running: "가져오는 중", done: "완료", failed: "실패" } as const;

const BTN = cn("inline-flex min-h-11 items-center justify-center rounded-control px-4 text-body font-semibold disabled:opacity-55", FOCUS);

export type JobPanelProps = {
  job: JobView | null;
  profileNames: Record<string, string>;
  busy: "retry" | "stop" | null;
  onRetry: () => void;
  onStop: () => void;
};

export function JobPanel({ job, profileNames, busy, onRetry, onStop }: JobPanelProps) {
  const active = job !== null && !isTerminal(job.status);
  const search = job?.source === "youtube_search";
  const offline = !search && job !== null && job.status === "queued" && !job.worker_online;
  const canStop = !search && active && job !== null && !job.stop_requested;
  const canRetry = job !== null && job.status === "failed" && job.retry_count < RETRY_LIMIT && !job.stop_requested;
  const errorText = job?.status === "failed" ? (jobErrorLabel(job.error) ?? UNKNOWN_CAUSE) : null;

  return (
    <section aria-labelledby="chrome-title" aria-busy={active || undefined} className={PANEL}>
      {/* 진행 상태(배지·프로필별 진행)는 바뀔 때 읽어 준다 */}
      <div aria-live="polite" data-live="job-progress">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id="chrome-title" className="text-h2 font-bold">
          {search ? "YouTube 검색 수집" : "Chrome 준비 결과"}
        </h2>
        {job && (
          <span
            className={cn(
              "rounded-chip px-2 py-0.5 text-caption font-semibold",
              job.status === "failed"
                ? "bg-danger-soft text-danger-soft-fg"
                : job.status === "done"
                  ? "bg-success-soft text-success-soft-fg"
                  : "bg-neutral-soft text-neutral-soft-fg",
            )}
          >
            {job.stop_requested && active ? "중지 요청됨" : JOB_STATUS_LABEL[job.status]}
          </span>
        )}
      </div>

      {!job ? (
        <p className="text-body text-text-muted">
          아직 실행한 수집이 없습니다. &apos;후보 가져오기&apos;를 누르면 프로필별 Chrome 준비 상태가 여기에 표시됩니다.
        </p>
      ) : (
        <>
          {search && <p className="mb-3 text-body text-text-muted">{VIDIQ_PENDING_MESSAGE}</p>}
          {offline && (
            <p role="alert" className="mb-3 rounded-control bg-warning-soft px-3 py-2 text-body text-warning-soft-fg">
              {WORKER_OFFLINE_MESSAGE}
            </p>
          )}
          {errorText && (
            <p role="alert" className="mb-3 rounded-control bg-danger-soft px-3 py-2 text-body text-danger-soft-fg">
              수집 실패: {errorText}
              {!canRetry && job.retry_count >= RETRY_LIMIT && ` · 재시도 한도(${RETRY_LIMIT}회)에 도달했습니다. 후보를 새로 가져오세요.`}
            </p>
          )}
          <ul className="flex flex-col gap-2">
            {job.profiles.map((p) => {
              const detail = chromeDetailLabel(p.detail);
              const bad = !search && p.chrome_state !== null && p.chrome_state !== "ready";
              return (
                <li key={p.profile_id} className="flex flex-col gap-1 rounded-card border border-border p-3 tablet:flex-row tablet:items-center tablet:justify-between">
                  <div className="min-w-0">
                    <p className="truncate text-body font-semibold">{profileNames[p.profile_id] ?? "프로필"}</p>
                    {detail && bad && <p className="text-caption text-danger">{detail}</p>}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-caption">
                    {!search && (
                      <span
                        className={cn(
                          "rounded-chip px-2 py-0.5 font-semibold",
                          bad ? "bg-danger-soft text-danger-soft-fg" : p.chrome_state === "ready" ? "bg-success-soft text-success-soft-fg" : "bg-neutral-soft text-neutral-soft-fg",
                        )}
                      >
                        {p.chrome_state ? CHROME_STATE_LABEL[p.chrome_state] : "확인 전"}
                      </span>
                    )}
                    <span className="text-text-muted">
                      {RUN_STATUS_LABEL[p.status]} · {p.collected_count.toLocaleString("ko-KR")}개
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}
      </div>
      {job && (canRetry || canStop) && (
            <div className="mt-3 flex flex-wrap gap-2">
              {canRetry && (
                <button type="button" onClick={onRetry} disabled={busy !== null} className={cn(BTN, "bg-primary text-primary-fg hover:bg-primary-hover")}>
                  {busy === "retry" ? "재시도 요청 중…" : "해당 후보부터 재시도"}
                </button>
              )}
              {canStop && (
                <button type="button" onClick={onStop} disabled={busy !== null} className={cn(BTN, "border border-border bg-surface text-text hover:border-input")}>
                  {busy === "stop" ? "중지 요청 중…" : "수집 중지"}
                </button>
              )}
            </div>
          )}
    </section>
  );
}
