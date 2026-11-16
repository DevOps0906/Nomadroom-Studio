"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import type { Profile, SaveResult } from "@/components/profiles/conditions";
import type { SaveConditionsAction } from "@/components/profiles/conditions-dialog";
import { ProfileList, type SaveSelectionAction } from "@/components/profiles/profile-list";
import { createIntentRunner, idsFingerprint } from "./intent-key";
import { isTerminal, pickJob, type JobView } from "./job";
import { JobPanel } from "./job-panel";
import { FAILED_MESSAGE, jobErrorLabel, type ActionFailure } from "./messages";
import { CandidateSkeleton, FOCUS, MonitorError } from "./monitor-view";
import { createPoller, type FetchResult } from "./poller";

type JobResult = { ok: true; job: JobView } | ActionFailure;
type VerifyResult = { ok: true; checked: number; skipped: number; failed: number } | ActionFailure;

export type MonitorActions = {
  startCollect: (key: string, ids: string[]) => Promise<JobResult>;
  retryCollect: (jobId: string) => Promise<JobResult>;
  stopCollect: (jobId: string) => Promise<JobResult>;
  verifyRecords: (key: string, ids: string[]) => Promise<VerifyResult>;
  saveConditions: SaveConditionsAction;
  saveSelection: SaveSelectionAction;
};

type Props = {
  profiles: Profile[] | null;
  profilesError: string | null;
  activeJob: JobView | null;
  actions: MonitorActions;
  sessionExpiredPath: string;
  updated: ReactNode;
  children: ReactNode;
};

type Notice = { tone: "success" | "error" | "info"; text: string };
type Busy = "collect" | "verify" | "retry" | "stop" | null;

const BTN = cn("inline-flex min-h-11 items-center justify-center rounded-control px-4 text-body font-semibold disabled:cursor-not-allowed disabled:opacity-55", FOCUS);

/** 폴링 응답 → 결과. 401은 세션 정리, 그 외 실패는 백오프. */
export async function fetchJobStatus(id: string, fetchImpl: typeof fetch = fetch): Promise<FetchResult> {
  const res = await fetchImpl(`/api/collect-jobs/${encodeURIComponent(id)}`, { cache: "no-store", headers: { Accept: "application/json" } });
  if (res.status === 401) return { kind: "unauthorized" };
  if (res.status === 403 || res.status === 404) return { kind: "gone" };
  if (!res.ok) return { kind: "error" };
  const job = pickJob(((await res.json()) as { job?: unknown }).job);
  return job ? { kind: "ok", job } : { kind: "error" };
}

export function finishedNotice(job: JobView): Notice {
  if (job.status === "done") {
    const r = job.result ?? { candidates: 0, producible: 0, pending: 0 };
    return { tone: "success", text: `후보 ${r.candidates}개 가져옴 · 제작 가능 ${r.producible} · 근거 대기 ${r.pending}` };
  }
  if (job.status === "stopped") return { tone: "info", text: "수집을 중지했습니다. 이미 가져온 후보는 유지됩니다." };
  return { tone: "error", text: `수집 실패: ${jobErrorLabel(job.error) ?? "알 수 없는 원인"}. 아래에서 다시 시도하세요.` };
}

/** MON-01 실행 영역: 두 실행 버튼 · 프로필 선택(MON-D1 다이얼로그) · Chrome 준비 결과 · 진행 폴링. */
export function MonitorWorkbench({ profiles, profilesError, activeJob, actions, sessionExpiredPath, updated, children }: Props) {
  const router = useRouter();
  const [job, setJob] = useState<JobView | null>(activeJob);
  const [prevActive, setPrevActive] = useState(activeJob);
  if (prevActive !== activeJob) {
    // router.refresh 뒤 서버가 찾은 활성 job으로 맞춘다(없으면 마지막 결과를 유지).
    setPrevActive(activeJob);
    if (activeJob) setJob(activeJob);
  }
  const [savingSel, setSavingSel] = useState(false);
  const [savedIds, setSavedIds] = useState<string[] | null>(null);
  const [prevProfiles, setPrevProfiles] = useState(profiles);
  if (prevProfiles !== profiles) {
    setPrevProfiles(profiles);
    setSavedIds(null);
  }
  const [busy, setBusy] = useState<Busy>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const collectRunner = useRef(createIntentRunner());
  const verifyRunner = useRef(createIntentRunner());

  const selectedIds = useMemo(
    () => savedIds ?? (profiles ?? []).filter((p) => p.selected).map((p) => p.id),
    [savedIds, profiles],
  );
  const profileNames = useMemo(() => Object.fromEntries((profiles ?? []).map((p) => [p.id, p.name])), [profiles]);
  const active = job !== null && !isTerminal(job.status);
  const pollId = active ? job.id : null;
  const blocked = busy !== null || savingSel || active || selectedIds.length === 0;

  useEffect(() => {
    if (!pollId) return;
    const poller = createPoller({
      fetchJob: (id) => fetchJobStatus(id),
      onJob: setJob,
      onFinished: (done) => {
        setJob(done);
        setNotice(finishedNotice(done));
        router.refresh();
      },
      onUnauthorized: () => window.location.assign(sessionExpiredPath),
      onGone: () => {
        // job이 없어졌다(다른 곳에서 정리 등). 폴링을 멈추고 서버에서 활성 job을 다시 받는다.
        setJob(null);
        router.refresh();
      },
      isHidden: () => document.visibilityState === "hidden",
      onVisibilityChange: (cb) => {
        document.addEventListener("visibilitychange", cb);
        return () => document.removeEventListener("visibilitychange", cb);
      },
    });
    poller.start(pollId);
    return () => poller.stop();
  }, [pollId, router, sessionExpiredPath]);

  const saveSelection: SaveSelectionAction = async (ids) => {
    setSavingSel(true);
    try {
      const res: SaveResult = await actions.saveSelection(ids);
      if (res.ok) setSavedIds(ids);
      return res;
    } finally {
      setSavingSel(false);
    }
  };

  async function guarded<T>(kind: Exclude<Busy, null>, run: () => Promise<T>): Promise<T | null> {
    setBusy(kind);
    setNotice(null);
    try {
      return await run();
    } catch {
      setNotice({ tone: "error", text: FAILED_MESSAGE });
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function collect() {
    if (blocked) return;
    const ids = selectedIds;
    const res = await guarded("collect", () => collectRunner.current.run(idsFingerprint(ids), (key) => actions.startCollect(key, ids)));
    if (!res) return;
    if (!res.ok) return setNotice({ tone: "error", text: res.message });
    setJob(res.job);
    setNotice({ tone: "info", text: "후보를 가져오는 중입니다. 프로필별 진행은 Chrome 준비 결과에서 확인하세요." });
  }

  async function verify() {
    if (blocked) return;
    const ids = selectedIds;
    const res = await guarded("verify", () => verifyRunner.current.run(idsFingerprint(ids), (key) => actions.verifyRecords(key, ids)));
    if (!res) return;
    if (!res.ok) return setNotice({ tone: res.keepKey ? "info" : "error", text: res.message });
    setNotice({
      tone: "success",
      text: `기록 검증 완료 · 확인 ${res.checked} · 24시간 미만 건너뜀 ${res.skipped} · 실패 ${res.failed}`,
    });
    router.refresh();
  }

  async function control(kind: "retry" | "stop") {
    if (!job || busy) return;
    const id = job.id;
    const res = await guarded(kind, () => (kind === "retry" ? actions.retryCollect(id) : actions.stopCollect(id)));
    if (!res) return;
    if (!res.ok) return setNotice({ tone: "error", text: res.message });
    setJob(res.job); // retrying이면 pollId가 다시 생겨 폴링이 재시작된다
    if (isTerminal(res.job.status)) {
      setNotice(finishedNotice(res.job));
      router.refresh();
    } else if (kind === "stop") {
      setNotice({ tone: "info", text: "중지를 요청했습니다. 진행 중인 프로필을 마치면 멈춥니다." });
    }
  }

  return (
    <>
      <div className="flex flex-col gap-3 tablet:flex-row tablet:items-start tablet:justify-between">
        <div>
          <h1 className="text-h1 font-bold">소재수집(정체)</h1>
          <p className="mt-1 text-body text-text-muted">프로필별 조건으로 후보를 가져와 기록으로 검증하고, 제작 가능한 소재를 고르세요.</p>
          <div className="mt-1">{updated}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={collect} disabled={blocked} className={cn(BTN, "border border-border bg-surface text-text hover:border-input")}>
            {busy === "collect" ? "요청 중…" : active ? "후보 가져오는 중…" : "후보 가져오기"}
          </button>
          <button type="button" onClick={verify} disabled={blocked} className={cn(BTN, "bg-primary text-primary-fg hover:bg-primary-hover")}>
            {busy === "verify" ? "검증 중…" : "기록 검증 실행"}
          </button>
        </div>
      </div>

      {notice && (
        <p
          role={notice.tone === "error" ? "alert" : "status"}
          className={cn(
            "rounded-control px-3 py-2 text-body",
            notice.tone === "error" && "bg-danger-soft text-danger-soft-fg",
            notice.tone === "success" && "bg-success-soft text-success-soft-fg",
            notice.tone === "info" && "bg-primary-soft text-primary-soft-fg",
          )}
        >
          {notice.text}
        </p>
      )}

      {profiles ? (
        <>
          {profiles.length > 0 && selectedIds.length === 0 && (
            <p className="rounded-control bg-warning-soft px-3 py-2 text-body text-warning-soft-fg">
              검증할 프로필을 선택하고 &apos;조건 설정&apos;으로 수집 조건을 확인하세요. 선택한 프로필이 있어야 후보를 가져올 수 있습니다.
            </p>
          )}
          <ProfileList profiles={profiles} saveConditions={actions.saveConditions} saveSelection={saveSelection} />
        </>
      ) : (
        <MonitorError title="프로필을 불러오지 못했습니다" message={profilesError ?? FAILED_MESSAGE} />
      )}

      <JobPanel job={job} profileNames={profileNames} busy={busy === "retry" || busy === "stop" ? busy : null} onRetry={() => control("retry")} onStop={() => control("stop")} />

      {active && <CandidateSkeleton label="후보 가져오는 중" />}
      {children}
    </>
  );
}
