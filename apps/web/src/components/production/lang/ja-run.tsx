"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { EVIDENCE_SESSION_EXPIRED_PATH as SESSION_EXPIRED_PATH } from "@/components/evidence/evidence";
import { createIntentKey } from "@/components/monitoring/intent-key";
import type { RunSummary } from "@/server/api/production";
import { requestRender } from "../run/api";
import { stageLabel } from "../run/model";
import { Player } from "../run/run-view";
import { PublishTextCard } from "../run/shopping-extras";
import { ReportWarnings } from "./report-warnings";
import { TTS_DISCLOSURE, jaRunState } from "./run-model";

// PROD-03 ja 탭: ja 리비전 상태·렌더 요청(A-15 lang=ja)·검수 리포트 경고·쇼핑 게시 문구(A-21 lang=ja).
// 예능형 ja는 API가 허용하는 시점부터 열리므로 버튼을 막지 않고 API 409 응답 문구를 그대로 안내한다.
// task-060: A-09 상세의 latest_runs.ja·자산 render_lang으로 ja 진행률·MP4·리포트를 ko와 구분한다.
const POLL_MS = 4000;

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
const BTN = "inline-flex min-h-11 items-center justify-center rounded-control px-4 text-body font-semibold disabled:cursor-not-allowed disabled:opacity-55";
const PRIMARY = cn(BTN, "bg-primary text-primary-fg hover:bg-primary-hover", FOCUS);
const SECONDARY = cn(BTN, "border border-border bg-surface text-text hover:bg-surface-alt", FOCUS);
const CARD = "rounded-panel border border-border bg-surface p-4 tablet:p-5";

export function JaRunView({
  job,
  ja,
  run,
  mp4Id,
  reportId,
}: {
  job: { id: string; shopping: boolean };
  ja: { id: string; rev_no: number; approved_at: string | null } | null;
  run: RunSummary | null;
  mp4Id: string | null;
  reportId: string | null;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [pending, startTransition] = useTransition();
  const [msg, setMsg] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const intent = useRef(createIntentKey());
  const editHref = `/production/${encodeURIComponent(job.id)}/edit?lang=ja`;
  const st = jaRunState(ja);
  const locked = busy || pending;
  const active = run?.status === "queued" || run?.status === "running";

  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => {
      if (document.visibilityState !== "hidden") router.refresh();
    }, POLL_MS);
    return () => clearInterval(t);
  }, [active, router]);

  async function onRequest() {
    if (locked || !ja || !st.canRequest) return;
    setBusy(true);
    setMsg(null);
    const r = await requestRender(job.id, ja.id, intent.current.current(ja.id), undefined, "ja");
    intent.current.settle(!r.ok && r.keepKey);
    setBusy(false);
    if (!r.ok) {
      if (r.status === 401) return window.location.assign(SESSION_EXPIRED_PATH);
      return setMsg({ tone: "error", text: r.message });
    }
    setMsg({ tone: "ok", text: "일본어판 렌더를 요청했습니다. 완료되면 아래 리포트·게시 문구를 새로고침으로 확인하세요." });
    startTransition(() => router.refresh());
  }

  return (
    <div className="flex flex-col gap-4">
      <section aria-label="일본어판 렌더" className={cn(CARD, "flex flex-col items-start gap-3")}>
        <h2 className="text-h2 font-bold">일본어판</h2>
        <p className="text-body text-text-muted">{st.message}</p>
        {st.canRequest && <p className="text-caption text-text-muted">{TTS_DISCLOSURE}</p>}
        {st.canRequest ? (
          <button type="button" disabled={locked} aria-busy={busy} onClick={() => void onRequest()} className={PRIMARY}>
            {busy ? "요청 중…" : "렌더 요청"}
          </button>
        ) : (
          <Link href={editHref} className={SECONDARY}>
            {ja ? "일본어판 편집으로" : "일본어판 만들기(편집안으로)"}
          </Link>
        )}
        {msg && (
          <p role={msg.tone === "error" ? "alert" : "status"} className={cn("text-body", msg.tone === "error" ? "text-danger" : "text-success")}>
            {msg.text}
          </p>
        )}
      </section>

      {run && (
        <section aria-label="일본어판 진행" className={cn(CARD, "flex flex-col gap-2")}>
          <h2 className="text-h2 font-bold">일본어판 렌더 상태</h2>
          {active && (
            <div className="flex flex-col gap-1" role="status">
              <progress max={100} value={run.progress_pct} className="h-2 w-full" aria-label="일본어판 렌더 진행률" />
              <p className="text-caption text-text-muted">
                {run.status === "queued" ? "대기 중" : `${stageLabel(run.progress_stage) || "진행"} 중`} · {run.progress_pct}%
              </p>
            </div>
          )}
          {run.status === "failed" && (
            <p role="alert" className="text-body text-danger">
              일본어판 렌더에 실패했습니다{run.error_code ? ` (${run.error_code})` : ""}. 다시 요청할 수 있습니다.
            </p>
          )}
          {run.status === "done" && <p className="text-body text-text-muted">일본어판 렌더 완료 · 시도 {run.attempt}</p>}
          {mp4Id && <Player key={mp4Id} jobId={job.id} assetId={mp4Id} />}
        </section>
      )}

      {ja?.approved_at && (
        <section aria-label="일본어판 검수 리포트" className={cn(CARD, "flex flex-col gap-2")}>
          <h2 className="text-h2 font-bold">검수 리포트 경고</h2>
          {reportId ? <ReportWarnings jobId={job.id} assetId={reportId} lang="ja" /> : <p className="text-body text-text-muted">리포트가 아직 없습니다.</p>}
        </section>
      )}

      {job.shopping && ja?.approved_at && <PublishTextCard key="ja" jobId={job.id} lang="ja" />}
    </div>
  );
}
