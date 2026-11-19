"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { EVIDENCE_SESSION_EXPIRED_PATH as SESSION_EXPIRED_PATH } from "@/components/evidence/evidence";
import { createIntentKey } from "@/components/monitoring/intent-key";
import type { ProductionJobDetail } from "@/server/api/production";
import { STAGE_LABEL, STATUS_LABEL, STATUS_TONE } from "../format";
import { approveReview, assetUrl, requestRender, retryRender, type RunResult } from "./api";
import { HOOK_NEED_TEXT, REASON_TEXT, STEPS, latestAsset, stageLabel, stepStates, viewOf, type StepState } from "./model";

// PROD-03 작업·검수. 서버(A-09 GET)가 정본이고 렌더 요청·재시도·검수 승인은 Route Handler로 보낸다.
// 근거: docs/03_SCREENS_UX.md PROD-03, tasks/task-027.md. W4는 ko만(언어 탭·쇼핑 게시 문구·출처 목록은 범위 밖).

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
const BTN = "inline-flex min-h-11 items-center justify-center rounded-control px-4 text-body font-semibold disabled:cursor-not-allowed disabled:opacity-55";
const PRIMARY = cn(BTN, "bg-primary text-primary-fg hover:bg-primary-hover", FOCUS);
const SECONDARY = cn(BTN, "border border-border bg-surface text-text hover:bg-surface-alt", FOCUS);
const CARD = "rounded-panel border border-border bg-surface p-4 tablet:p-5";
const POLL_MS = 3000;

const STEP_TONE: Record<StepState, string> = {
  done: "border-success",
  active: "border-primary",
  todo: "border-border",
  failed: "border-danger",
};
const STEP_TEXT: Record<StepState, string> = { done: "완료", active: "진행 중", todo: "대기", failed: "실패" };

export function Stepper({ detail }: { detail: Pick<ProductionJobDetail, "job" | "latest_run"> }) {
  const states = stepStates(detail);
  return (
    <ol aria-label="진행 단계" className="grid grid-cols-3 gap-2">
      {STEPS.map((s) => (
        <li key={s.key} className={cn("border-t-4 pt-2 text-caption", STEP_TONE[states[s.key]])} aria-current={states[s.key] === "active" ? "step" : undefined}>
          <span className="font-semibold text-text">{s.label}</span>
          <span className={cn("block", states[s.key] === "failed" ? "text-danger" : "text-text-muted")}>{STEP_TEXT[states[s.key]]}</span>
        </li>
      ))}
    </ol>
  );
}

function Player({ jobId, assetId }: { jobId: string; assetId: string | null }) {
  const [src, setSrc] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const retried = useRef(false);
  useEffect(() => {
    // assetId가 바뀌면 부모의 key로 Player가 다시 만들어져 상태가 초기화된다.
    if (!assetId) return;
    let alive = true;
    void assetUrl(jobId, assetId).then((r) => {
      if (!alive) return;
      if (r.ok) setSrc(r.data.url);
      else setErr(r.message);
    });
    return () => {
      alive = false;
    };
  }, [jobId, assetId]);
  if (!assetId) return <p className="text-text-muted">완료된 MP4가 아직 없습니다.</p>;
  if (err) return <p role="alert" className="text-caption text-danger">{err}</p>;
  if (!src) return <p role="status" className="text-text-muted">영상을 불러오는 중…</p>;
  // 서명 URL 만료 등으로 재생이 실패하면 새 URL을 한 번만 다시 받는다.
  async function onError() {
    if (!assetId) return;
    if (retried.current) {
      setErr("영상을 재생하지 못했습니다. 새로고침하거나 MP4 다운로드를 이용하세요.");
      return;
    }
    retried.current = true;
    const r = await assetUrl(jobId, assetId);
    if (r.ok) setSrc(r.data.url);
    else setErr(r.message);
  }
  return <video controls preload="metadata" src={src} onError={() => void onError()} className="aspect-video w-full max-w-3xl rounded-card bg-neutral-soft" />;
}

/** 클릭 직후 동기로 빈 창을 열고 서명 URL을 받아 이동한다(URL 저장·로그 없음). 실패 시 문구를 돌려준다. */
async function openDownload(jobId: string, assetId: string): Promise<string | null> {
  const w = window.open("", "_blank");
  if (w) w.opener = null;
  const r = await assetUrl(jobId, assetId);
  if (!r.ok) {
    w?.close();
    return r.message;
  }
  if (!w) return "팝업이 차단되었습니다. 팝업을 허용한 뒤 다시 시도하세요.";
  w.location.href = r.data.url;
  return null;
}

export function RunView({ detail }: { detail: ProductionJobDetail }) {
  const router = useRouter();
  const { job, latest_run: run, current_revision: rev } = detail;
  const v = viewOf(detail);
  const [busy, setBusy] = useState<null | "request" | "retry" | "approve" | "download">(null);
  const [pending, startTransition] = useTransition();
  const [msg, setMsg] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const intent = useRef(createIntentKey());
  const editHref = `/production/${encodeURIComponent(job.id)}/edit`;
  const mp4 = latestAsset(detail.assets, "output_mp4");
  const report = latestAsset(detail.assets, "report");
  const locked = busy !== null || pending;
  const polling = job.status === "rendering" || run?.status === "queued" || run?.status === "running";

  useEffect(() => {
    if (!polling) return;
    const t = setInterval(() => {
      if (document.visibilityState !== "hidden") router.refresh();
    }, POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") router.refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(t);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [polling, router]);

  function fail(r: Extract<RunResult<unknown>, { ok: false }>) {
    if (r.status === 401) {
      window.location.assign(SESSION_EXPIRED_PATH);
      return;
    }
    setMsg({ tone: "error", text: r.message });
    setBusy(null);
  }

  async function onRequest() {
    if (locked || !rev.ko) return;
    setBusy("request");
    setMsg(null);
    const r = await requestRender(job.id, rev.ko.id, intent.current.current(rev.ko.id));
    intent.current.settle(!r.ok && r.keepKey);
    if (!r.ok) return fail(r);
    setMsg({ tone: "ok", text: "렌더를 요청했습니다." });
    startTransition(() => router.refresh());
    setBusy(null);
  }

  async function onRetry() {
    if (locked || !run) return;
    setBusy("retry");
    setMsg(null);
    const r = await retryRender(job.id, run.id);
    if (!r.ok) return fail(r);
    setMsg({ tone: "ok", text: "재시도를 시작했습니다." });
    startTransition(() => router.refresh());
    setBusy(null);
  }

  async function onApprove() {
    if (locked) return;
    setBusy("approve");
    setMsg(null);
    const r = await approveReview(job.id);
    if (!r.ok) return fail(r);
    setMsg({ tone: "ok", text: "검수를 승인했습니다. 작업이 완료되었습니다." });
    startTransition(() => router.refresh());
    setBusy(null);
  }

  async function onDownload(assetId: string) {
    if (locked) return;
    setBusy("download");
    setMsg(null);
    const err = await openDownload(job.id, assetId);
    if (err) setMsg({ tone: "error", text: err });
    setBusy(null);
  }

  const failCode = run?.error_code ?? job.error_code;
  const failStage = (run?.error_stage ?? job.failed_stage) as keyof typeof STAGE_LABEL | null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("rounded-chip px-2 py-0.5 text-caption font-semibold", STATUS_TONE[job.status])}>{STATUS_LABEL[job.status]}</span>
        <span className="text-caption text-text-muted">ko{run ? ` · 시도 ${run.attempt}` : ""}</span>
      </div>

      {(v.rendering || v.failed || v.inspect || v.done) && (
        <section aria-label="진행" className={CARD}>
          <Stepper detail={detail} />
          {v.rendering && (
            <div className="mt-3 flex flex-col gap-1" role="status">
              <progress max={100} value={run?.progress_pct ?? 0} className="h-2 w-full" aria-label="렌더 진행률" />
              <p className="text-caption text-text-muted">
                {run?.status === "queued" ? "대기 중" : `${stageLabel(run?.progress_stage ?? null) || "진행"} 중`} · {run?.progress_pct ?? 0}%
              </p>
            </div>
          )}
        </section>
      )}

      {v.workerOffline && (
        <p role="alert" className="rounded-card bg-warning-soft p-3 text-body text-warning-soft-fg">
          제작 워커가 오프라인입니다. 워커를 켜면 렌더가 이어집니다. 오래 응답이 없으면 실패로 표시되며 재시도할 수 있습니다.
        </p>
      )}

      {job.status === "review" && !v.editFirst && (
        <section aria-label="렌더 요청" className={cn(CARD, "flex flex-col items-start gap-3")}>
          {v.canRequest ? (
            <>
              <p className="text-body">승인됨 — 렌더 요청을 눌러 시작</p>
              <button type="button" onClick={() => void onRequest()} disabled={locked} className={PRIMARY}>
                {busy === "request" ? "요청 중…" : "렌더 요청"}
              </button>
            </>
          ) : (
            <>
              <p className="text-body text-text-muted">편집안이 아직 승인되지 않았습니다. 편집안을 승인하면 렌더를 요청할 수 있습니다.</p>
              <Link href={editHref} className={SECONDARY}>
                편집안으로
              </Link>
            </>
          )}
        </section>
      )}

      {v.rendering && (
        <div>
          <button type="button" disabled className={PRIMARY}>
            렌더 중
          </button>
        </div>
      )}

      {v.failed && (
        <section aria-label="실패" className={cn(CARD, "flex flex-col items-start gap-3 border-danger")}>
          <p role="alert" className="text-body font-semibold text-danger">
            실패 단계: {failStage ? STAGE_LABEL[failStage] : "알 수 없음"} · 사유 코드: <code>{failCode ?? "unknown"}</code>
          </p>
          {failCode && REASON_TEXT[failCode] && <p className="text-body text-text-muted">{REASON_TEXT[failCode]}</p>}
          {failCode === "hook_too_long" && <p className="text-body text-text-muted">{HOOK_NEED_TEXT}</p>}
          {v.canRetry && (
            <button type="button" onClick={() => void onRetry()} disabled={locked} className={PRIMARY}>
              {busy === "retry" ? "재시도 중…" : "재시도"}
            </button>
          )}
          {v.editFirst && (
            <Link href={editHref} className={PRIMARY}>
              편집안으로 돌아가 고치기
            </Link>
          )}
        </section>
      )}

      {(v.inspect || v.done) && (
        <>
          <section aria-label="MP4" className={CARD}>
            <Player key={mp4 ?? "none"} jobId={job.id} assetId={mp4} />
          </section>
          {v.inspect && (
            <section aria-label="검수 확인 항목" className={CARD}>
              <h2 className="mb-2 text-h2 font-bold">영상에서 확인하세요</h2>
              <ul className="list-disc pl-5 text-body">
                <li>글자 잘림: 제목·자막·댓글·출처 글자가 화면 밖으로 잘리거나 가려지지 않았는지</li>
                <li>검은 틈: 구도 가장자리나 장면 전환에 검은 줄·빈 화면이 없는지</li>
                <li>핵심 피사체 잘림: 사람·제품 등 핵심 피사체가 잘리지 않았는지</li>
              </ul>
              <p className="mt-2 text-caption text-text-muted">안내용 확인 목록입니다. 문제가 있으면 “편집안으로(새 리비전)”에서 고친 뒤 다시 렌더하세요.</p>
            </section>
          )}
          <section aria-label="검수 리포트" className={CARD}>
            <h2 className="mb-2 text-h2 font-bold">검수 리포트</h2>
            {report ? (
              <button type="button" disabled={locked} onClick={() => void onDownload(report)} className={SECONDARY}>
                리포트 열기
              </button>
            ) : (
              <p className="text-text-muted">리포트가 아직 없습니다.</p>
            )}
          </section>
          <div className="flex flex-wrap gap-2">
            {v.inspect && (
              <button type="button" disabled={locked || !mp4} onClick={() => void onApprove()} className={PRIMARY}>
                {busy === "approve" ? "승인 중…" : "검수 승인 → 완료"}
              </button>
            )}
            {mp4 && (
              <button type="button" disabled={locked} onClick={() => void onDownload(mp4)} className={SECONDARY}>
                MP4 다운로드
              </button>
            )}
            <Link href={editHref} className={SECONDARY}>
              편집안으로(새 리비전)
            </Link>
          </div>
        </>
      )}

      {msg && (
        <p role={msg.tone === "error" ? "alert" : "status"} className={cn("text-body", msg.tone === "error" ? "text-danger" : "text-success")}>
          {msg.text}
        </p>
      )}
      <p className="text-caption text-text-muted">
        <button type="button" onClick={() => router.refresh()} className={cn("rounded-control underline underline-offset-4", FOCUS)}>
          ↻ 새로고침
        </button>
      </p>
    </div>
  );
}
