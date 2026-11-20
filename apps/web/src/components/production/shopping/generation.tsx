"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { EVIDENCE_SESSION_EXPIRED_PATH as SESSION_EXPIRED_PATH } from "@/components/evidence/evidence";
import { createIntentRunner } from "@/components/monitoring/intent-key";
import type { GenerationBudget, GenerationStatus } from "@/server/api/production";
import { confirmGeneration, generationAssetUrl, listGeneration, quoteGeneration, refreshGeneration, reviewGeneration, type GenerationRunView, type Result } from "./api";
import { Field, INPUT, PRIMARY, SECONDARY } from "./ui";
import { NO_CHECKS, REVIEW_ITEMS, allChecked, canSubmitReview, createSingleFlight, quoteFingerprint, shouldReloadRuns, type ReviewKey, type ReviewState } from "./generation-logic";

export { NO_CHECKS, REVIEW_ITEMS, allChecked };

// PROD-01S 사진 행 "AI 영상 생성"(A-22): 프롬프트·길이 → 견적 → 확인 모달(과금) → 진행(수동 새로고침) → 검수 3항목 → review.
// 근거: tasks/task-057.md. 자동 폴링 없음. 프롬프트·URL은 로그에 남기지 않는다.

export const MAX_PROMPT = 500;
export const MAX_DURATION = 15;

export const GEN_STATUS_LABEL: Record<GenerationStatus, string> = {
  quoted: "견적(확인 전)",
  confirmed: "확인됨(제출 중)",
  running: "생성 중",
  finalizing: "결과 저장 중",
  done: "완료",
  failed: "실패",
  unknown: "상태 불명(진행 확인 필요)",
};

/** 진행 확인 버튼을 보이는 상태. */
export const isRefreshable = (s: GenerationStatus) => s === "confirmed" || s === "running" || s === "finalizing" || s === "unknown";


export const won = (n: number) => `${n.toLocaleString("ko-KR")}원`;

/** 입력 검증(서버와 같은 한도). 오류 문구 또는 null. */
export function validateGen(prompt: string, duration: number): { prompt?: string; duration?: string } {
  const e: { prompt?: string; duration?: string } = {};
  const p = prompt.trim();
  if (p.length < 1 || p.length > MAX_PROMPT) e.prompt = `프롬프트는 1~${MAX_PROMPT}자로 입력하세요.`;
  if (!Number.isInteger(duration) || duration < 1 || duration > MAX_DURATION) e.duration = `길이는 1~${MAX_DURATION}초 정수로 입력하세요.`;
  return e;
}

export function BudgetNote({ est, budget }: { est: number; budget: GenerationBudget | null }) {
  return (
    <ul className="flex flex-col gap-1 text-body">
      <li>예상 비용: {won(est)}</li>
      {budget && <li>월 예산 잔액: {won(budget.monthly_left_krw)}</li>}
      {budget && <li>작업당 상한 잔액: {won(budget.job_left_krw)}</li>}
    </ul>
  );
}

/** 확인 모달 본문(과금 안내). 열기·닫기는 부모가 한다. */
export function ConfirmDialog({
  dialogRef,
  est,
  budget,
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  dialogRef?: React.Ref<HTMLDialogElement>;
  est: number;
  budget: GenerationBudget | null;
  busy: boolean;
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <dialog ref={dialogRef} aria-labelledby="gen-confirm-title" onCancel={onCancel} className="m-auto w-11/12 max-w-lg rounded-panel border border-border bg-surface p-5 text-text backdrop:bg-text/40">
      <div className="flex flex-col gap-3">
        <h3 id="gen-confirm-title" className="text-h2 font-bold">
          AI 영상 생성 확인
        </h3>
        <p className="text-body">확인하면 예상 비용이 바로 계상되고 외부 영상 생성 서비스로 사진·프롬프트가 전송됩니다. 확인은 워크스페이스 소유자만 할 수 있습니다.</p>
        <BudgetNote est={est} budget={budget} />
        {error && (
          <p role="alert" className="rounded-control bg-danger-soft px-3 py-2 text-body text-danger-soft-fg">
            {error}
          </p>
        )}
        <div className="flex flex-col gap-2 tablet:flex-row">
          <button type="button" className={PRIMARY} disabled={busy} onClick={onConfirm}>
            {busy ? "확인하는 중…" : "생성 확인"}
          </button>
          <button type="button" className={SECONDARY} disabled={busy} onClick={onCancel}>
            취소
          </button>
        </div>
      </div>
    </dialog>
  );
}

/** 검수 3항목. 모두 체크해야 저장 버튼이 켜진다. */
export function ReviewChecks({ idPrefix, checks, disabled, busy, onChange, onSubmit }: { idPrefix: string; checks: ReviewState; disabled?: boolean; busy: boolean; onChange: (k: ReviewKey, v: boolean) => void; onSubmit: () => void }) {
  return (
    <fieldset className="flex flex-col gap-1" disabled={disabled}>
      <legend className="text-body font-medium text-text">검수(승인 전 필수)</legend>
      {REVIEW_ITEMS.map((i) => (
        <label key={i.key} htmlFor={`${idPrefix}-${i.key}`} className="inline-flex min-h-11 items-center gap-2 text-body">
          <input id={`${idPrefix}-${i.key}`} type="checkbox" className="size-5 accent-primary" checked={checks[i.key]} onChange={(ev) => onChange(i.key, ev.target.checked)} />
          {i.label}
        </label>
      ))}
      <div>
        <button type="button" className={SECONDARY} disabled={!allChecked(checks) || busy} onClick={onSubmit}>
          {busy ? "저장하는 중…" : "검수 완료 저장"}
        </button>
      </div>
    </fieldset>
  );
}

type Msg = { tone: "ok" | "error"; text: string } | null;

export function GenerationPanel({ jobId, sourceAssetId, canCreate }: { jobId: string; sourceAssetId: string; canCreate: boolean }) {
  const router = useRouter();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [runs, setRuns] = useState<GenerationRunView[] | null>(null);
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState(5);
  const [errors, setErrors] = useState<{ prompt?: string; duration?: string }>({});
  const [budget, setBudget] = useState<GenerationBudget | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"quote" | "confirm" | "refresh" | "review" | null>(null);
  const [busyRun, setBusyRun] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [message, setMessage] = useState<Msg>(null);
  const [checks, setChecks] = useState<Record<string, ReviewState>>({});
  const [reviewed, setReviewed] = useState<Record<string, boolean>>({});
  const quoteRunner = useRef(createIntentRunner());
  const flight = useRef(createSingleFlight());

  useEffect(() => {
    let live = true;
    void listGeneration(jobId).then((r) => {
      if (!live) return;
      if (r.ok) setRuns(r.data.items);
      else {
        setRuns([]);
        if (r.status === 401) window.location.assign(SESSION_EXPIRED_PATH);
      }
    });
    return () => {
      live = false;
    };
  }, [jobId]);

  useEffect(() => {
    const el = dialogRef.current;
    if (!el) return;
    if (confirming && !el.open) el.showModal();
    if (!confirming && el.open) el.close();
  }, [confirming]);

  const mine = (runs ?? []).filter((r) => r.source_asset_id === sourceAssetId);
  const confirmRun = mine.find((r) => r.id === confirming) ?? null;

  /** 공통 오류 처리: 401 로그인 이동, 503 사용 안 함, 409 예산, 그 밖은 문구. 처리했으면 문구를 돌려준다. */
  function errorText(r: Extract<Result<unknown>, { ok: false }>): string {
    if (r.status === 401) {
      window.location.assign(SESSION_EXPIRED_PATH);
      return r.message;
    }
    if (r.status === 503) {
      setUnavailable("AI 영상 생성은 사용 안 함입니다. 사진 모션은 그대로 쓸 수 있습니다.");
      return r.message;
    }
    if (r.status === 409 && r.field === "budget_exceeded") return `예산 부족: ${r.message} 사진 모션은 그대로 쓸 수 있습니다.`;
    if (r.status === 403) return "확인(과금)은 워크스페이스 소유자만 할 수 있습니다. 소유자에게 확인을 요청하세요.";
    return r.message;
  }

  const upsert = (run: GenerationRunView) => setRuns((rs) => [run, ...(rs ?? []).filter((x) => x.id !== run.id)]);

  /** 실패 뒤 목록을 다시 읽어 서버의 실제 상태(unknown 포함)를 반영한다. */
  async function reload() {
    const r = await listGeneration(jobId);
    if (r.ok) setRuns(r.data.items);
  }

  async function quote() {
    setMessage(null);
    const e = validateGen(prompt, duration);
    setErrors(e);
    if (e.prompt || e.duration) return;
    const body = { source_asset_id: sourceAssetId, prompt: prompt.trim(), duration_sec: duration };
    setBusy("quote");
    const r = await quoteRunner.current.run(quoteFingerprint(body), (key) => quoteGeneration(jobId, body, key));
    if (r === null) return; // 이중 호출 차단
    setBusy(null);
    if (!r.ok) {
      setMessage({ tone: "error", text: errorText(r) });
      if (shouldReloadRuns("quote", r)) await reload();
      return;
    }
    upsert(r.data.run);
    setBudget(r.data.budget);
    setDialogError(null);
    setConfirming(r.data.run.id);
  }

  async function confirm() {
    if (!confirming || flight.current.busy) return;
    const id = confirming;
    setBusy("confirm");
    const r = await flight.current.run(() => confirmGeneration(jobId, id));
    if (r === null) return;
    setBusy(null);
    if (!r.ok) {
      const text = errorText(r);
      setDialogError(text);
      if (r.status === 503 || r.status === 409) {
        setConfirming(null);
        setMessage({ tone: "error", text });
      }
      if (shouldReloadRuns("confirm", r)) await reload();
      return;
    }
    upsert(r.data.run);
    setConfirming(null);
    setBudget(null);
    setMessage({ tone: "ok", text: "생성을 요청했습니다. 진행 상태 확인 버튼으로 결과를 확인하세요." });
  }

  /** 서명 주소를 눌렀을 때만 받아 새 탭으로 연다(저장·로그 없음). */
  async function openAsset(runId: string, which: "result" | "source") {
    const r = await generationAssetUrl(jobId, runId, which);
    if (!r.ok) return setMessage({ tone: "error", text: errorText(r) });
    window.open(r.data.url, "_blank", "noopener,noreferrer");
  }

  async function refresh(runId: string) {
    if (flight.current.busy) return;
    setBusy("refresh");
    setBusyRun(runId);
    const r = await flight.current.run(() => refreshGeneration(jobId, runId));
    if (r === null) return;
    setBusy(null);
    setBusyRun(null);
    if (!r.ok) return setMessage({ tone: "error", text: errorText(r) });
    upsert(r.data.run);
    if (r.data.run.status === "done") {
      setMessage({ tone: "ok", text: "생성이 끝났습니다. 결과 영상이 원본에 추가되었습니다. 검수를 마쳐야 승인할 수 있습니다." });
      router.refresh();
    } else setMessage(null);
  }

  async function review(runId: string) {
    const c = checks[runId] ?? NO_CHECKS;
    if (!canSubmitReview(c, flight.current.busy)) return;
    setBusy("review");
    setBusyRun(runId);
    const r = await flight.current.run(() => reviewGeneration(jobId, runId, c));
    if (r === null) return;
    setBusy(null);
    setBusyRun(null);
    if (!r.ok) return setMessage({ tone: "error", text: errorText(r) });
    setReviewed((v) => ({ ...v, [runId]: r.data.reviewed }));
    setMessage(r.data.reviewed ? { tone: "ok", text: "검수를 저장했습니다." } : { tone: "error", text: "검수 3항목이 모두 확인되지 않아 저장되지 않았습니다." });
  }

  return (
    <div className="flex w-full flex-col gap-3 rounded-card border border-border bg-surface p-3" aria-label="AI 영상 생성">
      <h3 className="text-body font-semibold">AI 영상 생성(사진 → 영상)</h3>
      {!canCreate ? (
        <p className="text-caption text-text-muted">이 단계에서는 새 생성을 만들 수 없습니다. 이력 확인·검수만 할 수 있습니다.</p>
      ) : unavailable ? (
        <p role="status" className="text-body text-text-muted">
          {unavailable}
        </p>
      ) : (
        <div className="grid gap-3 tablet:grid-cols-3 tablet:items-start">
          <div className="tablet:col-span-2">
            <Field id={`gen-${sourceAssetId}-prompt`} label="프롬프트" required hint={`${MAX_PROMPT}자 이내. 외부 영상 생성 서비스로 전송됩니다.`} error={errors.prompt}>
              <textarea id={`gen-${sourceAssetId}-prompt`} className={cn(INPUT, "min-h-24 py-2")} value={prompt} maxLength={MAX_PROMPT} disabled={busy !== null} aria-invalid={!!errors.prompt} onChange={(ev) => setPrompt(ev.target.value)} />
            </Field>
          </div>
          <Field id={`gen-${sourceAssetId}-dur`} label="길이(초)" required hint={`1~${MAX_DURATION}`} error={errors.duration}>
            <input id={`gen-${sourceAssetId}-dur`} type="number" inputMode="numeric" min={1} max={MAX_DURATION} className={INPUT} value={duration} disabled={busy !== null} aria-invalid={!!errors.duration} onChange={(ev) => setDuration(Number(ev.target.value))} />
          </Field>
          <div className="tablet:col-span-2">
            <button type="button" className={SECONDARY} disabled={busy !== null} onClick={() => void quote()}>
              {busy === "quote" ? "견적 계산 중…" : "견적 보기"}
            </button>
          </div>
        </div>
      )}
      {message && (
        <p role={message.tone === "error" ? "alert" : "status"} className={cn("rounded-control px-3 py-2 text-body", message.tone === "error" ? "bg-danger-soft text-danger-soft-fg" : "bg-success-soft text-success-soft-fg")}>
          {message.text}
        </p>
      )}

      {runs === null ? (
        <p role="status" className="text-caption text-text-muted">
          생성 이력을 불러오는 중…
        </p>
      ) : mine.length === 0 ? (
        <p className="text-caption text-text-muted">이 사진의 생성 이력이 없습니다.</p>
      ) : (
        <ul aria-label="생성 이력" className="flex flex-col gap-2">
          {mine.map((r) => {
            const isBusy = busyRun === r.id;
            return (
              <li key={r.id} className="flex flex-col gap-2 rounded-card border border-border bg-bg p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-body font-semibold">{GEN_STATUS_LABEL[r.status]}</span>
                  <span className="text-caption text-text-muted">
                    {r.duration_sec}초 · 예상 {won(r.est_cost_krw)}
                    {r.actual_cost_krw !== null ? ` · 실제 ${won(r.actual_cost_krw)}` : ""}
                  </span>
                </div>
                {r.status === "failed" && (
                  <p role="alert" className="text-caption text-danger">
                    생성에 실패했습니다{r.error_code ? ` (${r.error_code})` : ""}. 사진 모션으로 계속할 수 있습니다.
                  </p>
                )}
                {r.status === "unknown" && <p className="text-caption text-text-muted">제출 결과를 알 수 없어 비용이 계상된 상태로 둡니다. 진행 상태를 확인하세요.</p>}
                <div className="flex flex-wrap gap-2">
                  {r.status === "quoted" && (
                    <button type="button" className={SECONDARY} disabled={busy !== null} onClick={() => { setBudget(null); setDialogError(null); setConfirming(r.id); }}>
                      생성 확인…
                    </button>
                  )}
                  {r.status === "done" && r.result_asset_id && (
                    <button type="button" className={SECONDARY} disabled={busy !== null} onClick={() => void openAsset(r.id, "result")}>
                      결과 영상 보기
                    </button>
                  )}
                  {r.source_asset_id && r.status !== "quoted" && (
                    <button type="button" className={SECONDARY} disabled={busy !== null} onClick={() => void openAsset(r.id, "source")}>
                      입력 사진 보기
                    </button>
                  )}
                  {isRefreshable(r.status) && (
                    <button type="button" className={SECONDARY} disabled={busy !== null} onClick={() => void refresh(r.id)}>
                      {isBusy ? "확인하는 중…" : "진행 상태 확인"}
                    </button>
                  )}
                </div>
                {r.status === "done" &&
                  (reviewed[r.id] ? (
                    <p role="status" className="text-body text-success-soft-fg">
                      검수 완료
                    </p>
                  ) : (
                    <ReviewChecks
                      idPrefix={`rv-${r.id}`}
                      checks={checks[r.id] ?? NO_CHECKS}
                      busy={isBusy && busy === "review"}
                      disabled={busy !== null}
                      onChange={(k, v) => setChecks((c) => ({ ...c, [r.id]: { ...(c[r.id] ?? NO_CHECKS), [k]: v } }))}
                      onSubmit={() => void review(r.id)}
                    />
                  ))}
              </li>
            );
          })}
        </ul>
      )}

      <ConfirmDialog dialogRef={dialogRef} est={confirmRun?.est_cost_krw ?? 0} budget={budget} busy={busy === "confirm"} error={dialogError} onConfirm={() => void confirm()} onCancel={() => busy !== "confirm" && setConfirming(null)} />
    </div>
  );
}
