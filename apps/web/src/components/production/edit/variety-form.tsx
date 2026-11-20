"use client";

import { dubOrdinals } from "@/components/production/lang/model";
import { useLangDirty } from "@/components/production/lang/dirty-guard";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { EVIDENCE_SESSION_EXPIRED_PATH as SESSION_EXPIRED_PATH } from "@/components/evidence/evidence";
import type { SpecIssue, Validation } from "@/server/api/production";
import { AiDraftButton } from "./AiDraftButton";
import { approveRevision, saveRevision, type EditResult } from "./api";
import { approveBlockers, isEditableStatus, issuesAt } from "./model";
import { SheetPanel, type SheetInfo } from "./sheet-panel";
import {
  MAX_CUTS,
  MAX_HEADER_LINE_CHARS,
  MAX_REACTIONS,
  MAX_SUBTITLES,
  MAX_TEXT_CHARS,
  MAX_TOTAL_SEC,
  STYLE_LABEL,
  buildVarietySpec,
  cutSegments,
  emptyVarietyDraft,
  isShortCut,
  isShortSub,
  isTooShortCut,
  moveRow,
  outputTotal,
  timedSegments,
  toVarietyDraft,
  varietyIssueLabel,
  type CutDraft,
  type ReactionDraft,
  type Seg,
  type SubDraft,
  type SubStyle,
  type VarietyDraft,
} from "./variety-model";
import type { EditJob, EditRevision } from "./edit-form";

// PROD-02V 예능형 편집안. 서버 검증(validation)이 정본이다: 저장은 오류가 있어도 허용, 승인은 오류 0·저장 완료일 때만.
// 근거: docs/03_SCREENS_UX.md PROD-02V, tasks/task-037.md.

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
const INPUT =
  "min-h-11 w-full rounded-control border border-input bg-bg px-3 text-(length:--text-input) text-text outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";
const BTN = "inline-flex min-h-11 items-center justify-center rounded-control px-4 text-body font-semibold disabled:cursor-not-allowed disabled:opacity-55";
const PRIMARY = cn(BTN, "bg-primary text-primary-fg hover:bg-primary-hover", FOCUS);
const SECONDARY = cn(BTN, "border border-border bg-surface text-text hover:bg-surface-alt", FOCUS);
const CARD = "rounded-panel border border-border bg-surface p-4 tablet:p-5";

type Section = "cuts" | "subs" | "title";
const SECTIONS: { id: Section; label: string }[] = [
  { id: "cuts", label: "컷" },
  { id: "subs", label: "자막" },
  { id: "title", label: "제목" },
];

function IssueList({ list, tone = "error" }: { list: SpecIssue[]; tone?: "error" | "warn" }) {
  if (list.length === 0) return null;
  return (
    <ul className={cn("flex flex-col gap-0.5 text-caption", tone === "error" ? "text-danger" : "text-warning")}>
      {list.map((i, n) => (
        <li key={`${i.code}-${i.path}-${n}`} role={tone === "error" ? "alert" : undefined}>
          {varietyIssueLabel(i)}: {i.message}
        </li>
      ))}
    </ul>
  );
}

function Num({ id, label, value, onChange, disabled, bad }: { id: string; label: string; value: string; onChange: (v: string) => void; disabled: boolean; bad: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-caption text-text-muted">
        {label}
      </label>
      <input id={id} inputMode="decimal" className={INPUT} value={value} disabled={disabled} aria-invalid={bad} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function Text({ id, label, value, onChange, disabled, bad, max }: { id: string; label: string; value: string; onChange: (v: string) => void; disabled: boolean; bad: boolean; max: number }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-caption text-text-muted">
        {label}
      </label>
      <input id={id} className={INPUT} value={value} maxLength={max} disabled={disabled} aria-invalid={bad} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function Row({ title, badges, issues, actions, children }: { title: string; badges?: ReactNode; issues: SpecIssue[]; actions: ReactNode; children: ReactNode }) {
  return (
    <li className={cn("flex flex-col gap-2 rounded-card border bg-bg p-3", issues.length > 0 ? "border-danger" : "border-border")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-body font-semibold">
          {title}
          {badges}
        </span>
        <span className="flex flex-wrap gap-2">{actions}</span>
      </div>
      {children}
      <IssueList list={issues} />
    </li>
  );
}

const Badge = ({ tone, children }: { tone: "warn" | "bad"; children: ReactNode }) => (
  <span className={cn("rounded-chip px-2 py-0.5 text-caption font-semibold", tone === "warn" ? "bg-warning-soft text-warning-soft-fg" : "bg-danger-soft text-danger-soft-fg")}>{children}</span>
);

function Lane({ label, segs }: { label: string; segs: Seg[] }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-12 shrink-0 text-caption text-text-muted">{label}</span>
      <div className="relative h-6 grow overflow-hidden rounded-control bg-neutral-soft">
        {segs.map((s, i) => (
          <span
            key={i}
            title={`${label} ${i + 1}`}
            style={{ left: `${s.left}%`, width: `${Math.max(s.width, 0.5)}%` }}
            className={cn("absolute inset-y-0 border-x border-surface", s.bad ? "bg-danger" : s.warn ? "bg-warning" : "bg-primary")}
          />
        ))}
      </div>
    </div>
  );
}

export function VarietyTimeline({ draft }: { draft: VarietyDraft }) {
  const total = outputTotal(draft.cuts);
  if (!(total > 0)) return <p className="text-body text-text-muted">컷을 추가하면 출력 타임라인이 표시됩니다.</p>;
  const cuts = cutSegments(draft.cuts, total);
  const subs = timedSegments(draft.subtitles, total, true);
  const reacts = timedSegments(draft.reactions, total, false);
  const bad = [...cuts, ...subs, ...reacts].some((s) => s.bad);
  return (
    <div className="flex flex-col gap-2" role="img" aria-label={bad ? "출력 타임라인: 확인할 구간이 있습니다" : "출력 타임라인"}>
      <Lane label="컷" segs={cuts} />
      <Lane label="대사" segs={subs} />
      <Lane label="반응" segs={reacts} />
      <p className={cn("text-caption", total > MAX_TOTAL_SEC ? "text-danger" : "text-text-muted")}>
        출력 총길이 {total}초(상한 {MAX_TOTAL_SEC}초) · <span className="text-danger">빨강</span> 오류 구간 · <span className="text-warning">노랑</span> 경고
      </p>
    </div>
  );
}

// task-040 A6: 대사 전송 고지(PRD#8 팀장 결정 문구)
export const AI_DRAFT_SEND_NOTICE = "AI 초안을 만들면 입력한 대사·분석 시트·후보 제목이 Anthropic(Claude)으로 전송됩니다.";

export function VarietyEditForm({ job, revision, sheet }: { job: EditJob; revision: EditRevision | null; sheet: SheetInfo | null }) {
  const router = useRouter();
  const editable = isEditableStatus(job.status, job.failed_stage);
  const initial = useMemo(() => (revision ? toVarietyDraft(revision.spec) : emptyVarietyDraft()), [revision]);

  const [draft, setDraft] = useState<VarietyDraft>(initial);
  const [snapshot, setSnapshot] = useState(() => JSON.stringify(initial));
  const [revNo, setRevNo] = useState<number | null>(revision?.rev_no ?? null);
  // task-059: 읽은 리비전 updated_at(다음 저장의 base). 저장·AI 초안 성공 때 갱신, 가공하지 않는다
  const [updatedAt, setUpdatedAt] = useState<string | null>(revision?.updated_at ?? null);
  const [validation, setValidation] = useState<Validation>(revision?.validation ?? { errors: [], warnings: [] });
  const [approvedAt, setApprovedAt] = useState<string | null>(revision?.approved_at ?? null);
  const [localErr, setLocalErr] = useState<{ path: string; message: string } | null>(null);
  const [rejected, setRejected] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [phase, setPhase] = useState<"idle" | "saving" | "approving" | "drafting">("idle");
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [section, setSection] = useState<Section>("cuts");
  const busy = phase !== "idle";
  const lock = !editable || busy || conflict;

  const dirty = JSON.stringify(draft) !== snapshot;
  const { errors, warnings } = validation;
  const stale = dirty || rejected;

  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);
  useLangDirty(dirty);

  // 편집·삭제·순서 이동은 낡은 숫자 오류(밀린 행 인덱스 포함)를 지운다. 저장할 때 다시 검사한다.
  const set = (patch: Partial<VarietyDraft>) => {
    setLocalErr(null);
    setDraft((d) => ({ ...d, ...patch }));
  };
  const upd = <K extends "cuts" | "subtitles" | "reactions">(key: K, i: number, p: Partial<VarietyDraft[K][number]>) =>
    set({ [key]: (draft[key] as object[]).map((r, n) => (n === i ? { ...r, ...p } : r)) } as Partial<VarietyDraft>);
  const del = (key: "cuts" | "subtitles" | "reactions", i: number) => set({ [key]: (draft[key] as object[]).filter((_, n) => n !== i) } as Partial<VarietyDraft>);

  function handleFail<T>(r: Extract<EditResult<T>, { ok: false }>): void {
    if (r.status === 401) {
      window.location.assign(SESSION_EXPIRED_PATH);
      return;
    }
    if (r.status === 409) setConflict(true);
    setMessage({ tone: "error", text: r.message });
    if (r.status === 400 && r.errors) {
      setValidation({ errors: r.errors, warnings: r.warnings ?? [] });
      setRejected(true);
    }
  }

  async function save(): Promise<boolean> {
    if (lock || revNo === null || updatedAt === null) return false;
    setMessage(null);
    const built = buildVarietySpec(draft);
    if (!built.ok) {
      setLocalErr({ path: built.path, message: built.message });
      setMessage({ tone: "error", text: "숫자가 아닌 칸이 있어 저장하지 못했습니다." });
      return false;
    }
    setLocalErr(null);
    setPhase("saving");
    const r = await saveRevision(job.id, built.spec, revNo, updatedAt);
    setPhase("idle");
    if (!r.ok) {
      handleFail(r);
      return false;
    }
    const rev = r.data.revision;
    setRevNo(rev.rev_no);
    setUpdatedAt(rev.updated_at);
    setValidation(rev.validation);
    setApprovedAt(rev.approved_at);
    setRejected(false);
    setSnapshot(JSON.stringify(draft));
    setMessage({ tone: "ok", text: rev.validation.errors.length > 0 ? `저장했습니다. 검증 오류 ${rev.validation.errors.length}건이 있습니다.` : "저장했습니다." });
    return true;
  }

  // A-14 AI 초안(새 리비전)을 양식에 반영한다. 이전 편집안은 서버에 보관된다.
  function applyDraft(rev: EditRevision) {
    const d = toVarietyDraft(rev.spec);
    setDraft(d);
    setSnapshot(JSON.stringify(d));
    setRevNo(rev.rev_no);
    setUpdatedAt(rev.updated_at);
    setValidation(rev.validation);
    setApprovedAt(rev.approved_at);
    setRejected(false);
    setLocalErr(null);
  }

  const blockers = approveBlockers({ status: job.status, hasRevision: revNo !== null, dirty, approved: approvedAt !== null, errorCount: rejected ? Math.max(errors.length, 1) : errors.length, busy });

  async function approve() {
    if (blockers.length > 0 || conflict || revNo === null) return;
    setMessage(null);
    setPhase("approving");
    const r = await approveRevision(job.id, revNo);
    if (!r.ok) {
      setPhase("idle");
      return handleFail(r);
    }
    setMessage({ tone: "ok", text: "승인했습니다. 작업 화면으로 이동합니다." });
    router.push(`/production/${encodeURIComponent(job.id)}`);
  }

  function cancel() {
    if (dirty && !window.confirm("저장하지 않은 변경이 있습니다. 나가시겠습니까?")) return;
    router.push(`/production/${encodeURIComponent(job.id)}`);
  }

  const loc = (path: string) => (localErr?.path === path || localErr?.path.startsWith(`${path}.`) ? [{ code: "input.number", path: localErr.path, message: localErr.message }] : []);
  const at = (path: string) => [...issuesAt(errors, path), ...loc(path)];
  const warnAt = (path: string) => issuesAt(warnings, path);
  const bad = (path: string) => at(path).length > 0;
  const vis = (s: Section) => cn(section === s ? "flex" : "hidden", "tablet:flex");
  const total = outputTotal(draft.cuts);

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      className="flex flex-col gap-4 pb-28 tablet:pb-0"
      aria-busy={busy}
    >
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-border text-body">
        <span className="rounded-chip bg-primary-soft px-3 py-1 text-caption font-semibold text-primary-soft-fg">예능형</span>
        <div role="tablist" aria-label="언어" className="flex gap-4">
          <span role="tab" aria-selected="true" className="border-b-2 border-primary py-2 font-semibold">
            ko
          </span>
          <span role="tab" aria-selected="false" aria-disabled="true" title="일본어판은 번역 후 만들 수 있습니다" className="py-2 text-text-muted">
            ja
          </span>
        </div>
      </div>

      <div role="tablist" aria-label="편집 구역" className="flex gap-2 tablet:hidden">
        {SECTIONS.map((s) => (
          <button key={s.id} type="button" role="tab" aria-selected={section === s.id} onClick={() => setSection(s.id)} className={cn(BTN, "grow", FOCUS, section === s.id ? "bg-primary-soft text-primary-soft-fg" : "border border-border text-text")}>
            {s.label}
          </button>
        ))}
      </div>

      {!editable && (
        <p role="status" className="rounded-control bg-neutral-soft px-3 py-2 text-body text-neutral-soft-fg">
          현재 상태에서는 편집안을 고칠 수 없습니다.
        </p>
      )}
      {revNo === null && (
        <p role="status" className="rounded-control bg-neutral-soft px-3 py-2 text-body text-neutral-soft-fg">
          편집안이 아직 없습니다. 원본 준비가 끝나면 편집안이 만들어집니다 — 그 뒤 분석 시트를 보고 컷을 추가하세요.
        </p>
      )}
      {approvedAt && (
        <p role="status" className="rounded-control bg-success-soft px-3 py-2 text-body text-success-soft-fg">
          승인된 편집안입니다. 고쳐서 저장하면 새 리비전이 만들어집니다.
        </p>
      )}

      {(errors.length > 0 || rejected) && (
        <section id="edit-issues" aria-label="검증 결과" className="rounded-panel border border-danger bg-danger-soft p-4 text-body text-danger-soft-fg">
          <p className="font-semibold">
            {rejected ? "서버가 형식 오류로 저장을 거부했습니다" : `검증 오류 ${errors.length}건`}
            {stale && !rejected ? " (마지막 저장 기준)" : ""}
          </p>
          <ul className="mt-1 list-disc pl-5">
            {errors.map((i, n) => (
              <li key={`${i.code}-${i.path}-${n}`}>
                {varietyIssueLabel(i)}
                {i.path ? ` (${i.path})` : ""}: {i.message}
              </li>
            ))}
          </ul>
        </section>
      )}
      {warnings.length > 0 && (
        <section aria-label="검증 경고" className="rounded-panel border border-border bg-warning-soft p-4 text-body text-warning-soft-fg">
          <p className="font-semibold">경고 {warnings.length}건 (렌더를 막지 않습니다)</p>
          <ul className="mt-1 list-disc pl-5">
            {warnings.map((i, n) => (
              <li key={`${i.code}-${i.path}-${n}`}>
                {varietyIssueLabel(i)}
                {i.path ? ` (${i.path})` : ""}: {i.message}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-label="출력 타임라인" className={cn(CARD, "flex flex-col gap-2")}>
        <h2 className="text-h2 font-bold">출력 타임라인</h2>
        <VarietyTimeline draft={draft} />
      </section>

      <div className="grid gap-4 desktop:grid-cols-[1fr_2fr]">
        <section aria-label="분석 시트" className={cn(CARD, "flex-col gap-2", "hidden tablet:flex", section === "cuts" && "flex")}>
          <h2 className="text-h2 font-bold">분석 시트</h2>
          <SheetPanel info={sheet} />
          <p className="text-caption text-text-muted">시트에서 구간을 확인한 뒤 컷의 원본 시작·끝(초)에 입력하세요. 시각은 선택 구간 0초 기준입니다.</p>
        </section>

        <div className="flex min-w-0 flex-col gap-4">
          <section aria-label="컷 행" className={cn(CARD, "flex-col gap-3", vis("cuts"))}>
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-h2 font-bold">컷 ({draft.cuts.length}/{MAX_CUTS})</h2>
              <button
                type="button"
                disabled={lock || draft.cuts.length >= MAX_CUTS}
                className={SECONDARY}
                onClick={() => {
                  const last = draft.cuts[draft.cuts.length - 1];
                  set({ cuts: [...draft.cuts, { start: last ? last.end : "0", end: "", scale: "1", x: "0", y: "0" }] });
                }}
              >
                ＋ 컷
              </button>
            </div>
            <IssueList list={errors.filter((i) => i.path === "cuts")} />
            {draft.cuts.length === 0 ? (
              <p className="text-body text-text-muted">컷이 없습니다. “＋ 컷”으로 추가하세요(원본 시트에서 구간을 고릅니다).</p>
            ) : (
              <ul className="flex flex-col gap-3">
                {draft.cuts.map((c: CutDraft, i) => {
                  const empty = errors.some((e) => e.code === "cuts.empty_area" && (e.path === `cuts.${i}` || e.path.startsWith(`cuts.${i}.`)));
                  return (
                    <Row
                      key={i}
                      title={`컷 ${i + 1}`}
                      badges={
                        <>
                          {(isShortCut(c) || isTooShortCut(c)) && <Badge tone={isTooShortCut(c) ? "bad" : "warn"}>0.5초 미만</Badge>}
                          {empty && <Badge tone="bad">빈 화면</Badge>}
                        </>
                      }
                      issues={at(`cuts.${i}`)}
                      actions={
                        <>
                          <button type="button" aria-label={`컷 ${i + 1} 위로`} disabled={lock || i === 0} className={SECONDARY} onClick={() => set({ cuts: moveRow(draft.cuts, i, i - 1) })}>
                            ↑
                          </button>
                          <button type="button" aria-label={`컷 ${i + 1} 아래로`} disabled={lock || i === draft.cuts.length - 1} className={SECONDARY} onClick={() => set({ cuts: moveRow(draft.cuts, i, i + 1) })}>
                            ↓
                          </button>
                          <button type="button" disabled={lock} className={SECONDARY} onClick={() => del("cuts", i)}>
                            삭제
                          </button>
                        </>
                      }
                    >
                      <div className="flex items-center gap-3">
                        <span aria-hidden className="flex h-10 w-16 shrink-0 items-center justify-center rounded-control bg-neutral-soft text-caption text-neutral-soft-fg">
                          {c.start || "?"}~{c.end || "?"}
                        </span>
                        <span className="text-caption text-text-muted">시트의 해당 시각 장면을 보며 구간을 맞추세요.</span>
                      </div>
                      <div className="grid grid-cols-2 gap-3 tablet:grid-cols-5">
                        <Num id={`cut-${i}-s`} label="원본 시작(초)" value={c.start} disabled={lock} bad={bad(`cuts.${i}.src_start`)} onChange={(v) => upd("cuts", i, { start: v })} />
                        <Num id={`cut-${i}-e`} label="원본 끝(초)" value={c.end} disabled={lock} bad={bad(`cuts.${i}.src_end`)} onChange={(v) => upd("cuts", i, { end: v })} />
                        <Num id={`cut-${i}-c`} label="배율(1~3)" value={c.scale} disabled={lock} bad={bad(`cuts.${i}.scale`)} onChange={(v) => upd("cuts", i, { scale: v })} />
                        <Num id={`cut-${i}-x`} label="x" value={c.x} disabled={lock} bad={bad(`cuts.${i}.x`)} onChange={(v) => upd("cuts", i, { x: v })} />
                        <Num id={`cut-${i}-y`} label="y" value={c.y} disabled={lock} bad={bad(`cuts.${i}.y`)} onChange={(v) => upd("cuts", i, { y: v })} />
                      </div>
                      <IssueList list={warnAt(`cuts.${i}`)} tone="warn" />
                    </Row>
                  );
                })}
              </ul>
            )}
            <p className="text-caption text-text-muted">출력 총길이 {total}초</p>
          </section>

          <section aria-label="대사 자막 행" className={cn(CARD, "flex-col gap-3", vis("subs"))}>
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-h2 font-bold">대사 자막</h2>
              <button
                type="button"
                disabled={lock || draft.subtitles.length >= MAX_SUBTITLES}
                className={SECONDARY}
                onClick={() => {
                  const last = draft.subtitles[draft.subtitles.length - 1];
                  set({ subtitles: [...draft.subtitles, { start: last ? last.end : "0", end: "", style: "line", text: "" }] });
                }}
              >
                ＋ 행
              </button>
            </div>
            <IssueList list={errors.filter((i) => i.path === "subtitles")} />
            {draft.subtitles.length === 0 ? (
              <p className="text-body text-text-muted">대사 자막이 없습니다. 출력 시각 기준으로 구간을 입력하세요(공백은 허용).</p>
            ) : (
              <ul className="flex flex-col gap-3">
                {draft.subtitles.map((s: SubDraft, i) => (
                  <Row
                    key={i}
                    title={dubOrdinals(draft.subtitles)[i] !== null ? `대사 ${dubOrdinals(draft.subtitles)[i]}` : `강조 ${i + 1}`}
                    badges={isShortSub(s) ? <Badge tone="warn">1.4초 미만</Badge> : undefined}
                    issues={at(`subtitles.${i}`)}
                    actions={
                      <button type="button" disabled={lock} className={SECONDARY} onClick={() => del("subtitles", i)}>
                        삭제
                      </button>
                    }
                  >
                    <div className="grid gap-3 tablet:grid-cols-3">
                      <Num id={`sub-${i}-s`} label="시작(초)" value={s.start} disabled={lock} bad={bad(`subtitles.${i}.start`)} onChange={(v) => upd("subtitles", i, { start: v })} />
                      <Num id={`sub-${i}-e`} label="끝(초)" value={s.end} disabled={lock} bad={bad(`subtitles.${i}.end`)} onChange={(v) => upd("subtitles", i, { end: v })} />
                      <div className="flex flex-col gap-1">
                        <label htmlFor={`sub-${i}-st`} className="text-caption text-text-muted">
                          스타일
                        </label>
                        <select id={`sub-${i}-st`} className={INPUT} value={s.style} disabled={lock} onChange={(e) => upd("subtitles", i, { style: e.target.value as SubStyle })}>
                          {(Object.keys(STYLE_LABEL) as SubStyle[]).map((k) => (
                            <option key={k} value={k}>
                              {STYLE_LABEL[k]}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <Text id={`sub-${i}-t`} label="문구" value={s.text} max={MAX_TEXT_CHARS} disabled={lock} bad={bad(`subtitles.${i}.text`)} onChange={(v) => upd("subtitles", i, { text: v })} />
                    <IssueList list={warnAt(`subtitles.${i}`)} tone="warn" />
                  </Row>
                ))}
              </ul>
            )}
          </section>

          <section aria-label="반응 자막 행" className={cn(CARD, "flex-col gap-3", vis("subs"))}>
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-h2 font-bold">반응 자막</h2>
              <button
                type="button"
                disabled={lock || draft.reactions.length >= MAX_REACTIONS}
                className={SECONDARY}
                onClick={() => set({ reactions: [...draft.reactions, { start: "0", end: "", text: "", x: "540", y: "300" }] })}
              >
                ＋ 행
              </button>
            </div>
            <IssueList list={errors.filter((i) => i.path === "reactions")} />
            {draft.reactions.length === 0 ? (
              <p className="text-body text-text-muted">반응 자막이 없습니다. 필요하면 행을 추가하세요(대사 자막과 겹쳐도 됩니다).</p>
            ) : (
              <ul className="flex flex-col gap-3">
                {draft.reactions.map((r: ReactionDraft, i) => (
                  <Row
                    key={i}
                    title={`반응 ${i + 1}`}
                    issues={at(`reactions.${i}`)}
                    actions={
                      <button type="button" disabled={lock} className={SECONDARY} onClick={() => del("reactions", i)}>
                        삭제
                      </button>
                    }
                  >
                    <div className="grid grid-cols-2 gap-3 tablet:grid-cols-4">
                      <Num id={`re-${i}-s`} label="시작(초)" value={r.start} disabled={lock} bad={bad(`reactions.${i}.start`)} onChange={(v) => upd("reactions", i, { start: v })} />
                      <Num id={`re-${i}-e`} label="끝(초)" value={r.end} disabled={lock} bad={bad(`reactions.${i}.end`)} onChange={(v) => upd("reactions", i, { end: v })} />
                      <Num id={`re-${i}-x`} label="x" value={r.x} disabled={lock} bad={bad(`reactions.${i}.x`)} onChange={(v) => upd("reactions", i, { x: v })} />
                      <Num id={`re-${i}-y`} label="y" value={r.y} disabled={lock} bad={bad(`reactions.${i}.y`)} onChange={(v) => upd("reactions", i, { y: v })} />
                    </div>
                    <Text id={`re-${i}-t`} label="문구" value={r.text} max={MAX_TEXT_CHARS} disabled={lock} bad={bad(`reactions.${i}.text`)} onChange={(v) => upd("reactions", i, { text: v })} />
                    <IssueList list={warnAt(`reactions.${i}`)} tone="warn" />
                  </Row>
                ))}
              </ul>
            )}
          </section>

          <section aria-label="제목" className={cn(CARD, "flex-col gap-3", vis("title"))}>
            <h2 className="text-h2 font-bold">제목(1~2줄)</h2>
            {([0, 1] as const).map((n) => (
              <div key={n} className="flex flex-col gap-1">
                <label htmlFor={`v-h${n}`} className="text-body font-medium text-text">
                  제목 {n + 1}줄
                  {n === 0 && (
                    <span aria-hidden className="text-danger">
                      {" "}
                      *
                    </span>
                  )}
                </label>
                <input
                  id={`v-h${n}`}
                  className={INPUT}
                  value={draft.header[n]}
                  maxLength={MAX_HEADER_LINE_CHARS}
                  disabled={lock}
                  aria-invalid={bad("header")}
                  onChange={(e) => set({ header: n === 0 ? [e.target.value, draft.header[1]] : [draft.header[0], e.target.value] })}
                />
              </div>
            ))}
            <IssueList list={at("header")} />
            <p className="text-caption text-text-muted">줄바꿈은 줄을 나눠 입력하세요. 폭이 넘치면 렌더 후 작업 화면에서 안내합니다.</p>
          </section>
        </div>
      </div>

      {message && (
        <p role={message.tone === "error" ? "alert" : "status"} className={cn("rounded-control px-3 py-2 text-body", message.tone === "error" ? "bg-danger-soft text-danger-soft-fg" : "bg-success-soft text-success-soft-fg")}>
          {message.text}
        </p>
      )}
      {conflict && (
        <div role="alert" className="flex flex-col gap-2 rounded-panel border border-danger bg-danger-soft p-4 text-body text-danger-soft-fg">
          <p className="font-semibold">다른 곳에서 먼저 수정되었거나 현재 상태에서는 저장·승인할 수 없습니다.</p>
          <p>내 변경은 저장되지 않았습니다. 최신 편집안을 다시 불러온 뒤 필요한 부분을 다시 고쳐 주세요.</p>
          <div>
            <button type="button" className={PRIMARY} onClick={() => window.location.reload()}>
              최신 편집안 불러오기
            </button>
          </div>
        </div>
      )}

      {blockers.length > 0 && !conflict && revNo !== null && (
        <p id="approve-why" className="text-caption text-text-muted">
          승인할 수 없는 이유:{" "}
          {blockers.map((b, n) => (
            <span key={b.id}>
              {n > 0 ? " · " : ""}
              {b.id === "errors" && errors.length > 0 ? (
                <a href="#edit-issues" className="underline">
                  {b.text}
                </a>
              ) : (
                b.text
              )}
            </span>
          ))}
        </p>
      )}

      <div className="fixed inset-x-0 bottom-0 z-10 flex flex-col gap-2 border-t border-border bg-surface p-3 tablet:static tablet:flex-row tablet:flex-wrap tablet:border-0 tablet:bg-transparent tablet:p-0">
        <button type="submit" disabled={lock || revNo === null} className={PRIMARY}>
          {phase === "saving" ? "저장하는 중…" : "저장"}
        </button>
        <button type="button" disabled={blockers.length > 0 || conflict} aria-describedby={blockers.length > 0 ? "approve-why" : undefined} onClick={() => void approve()} className={SECONDARY}>
          {phase === "approving" ? "승인하는 중…" : "승인"}
        </button>
        <AiDraftButton jobId={job.id} disabled={busy || conflict || job.status !== "review"} dirty={dirty} onBusy={(b) => setPhase(b ? "drafting" : "idle")} onApplied={applyDraft} onFail={handleFail} />
        <button type="button" disabled={busy} onClick={cancel} className={SECONDARY}>
          취소
        </button>
        <p className="text-caption text-text-muted tablet:basis-full">{AI_DRAFT_SEND_NOTICE}</p>
      </div>
    </form>
  );
}
