"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { EVIDENCE_SESSION_EXPIRED_PATH as SESSION_EXPIRED_PATH } from "@/components/evidence/evidence";
import type { ProductionStatus, SpecIssue, Validation } from "@/server/api/production";
import { AUDIO_ACCEPT, MAX_AUDIO_BYTES, approveRevision, audioMime, completeHookAudio, putAudio, requestHookAudio, saveRevision, type EditResult } from "./api";
import {
  KIND_LABEL,
  approveBlockers,
  buildSpec,
  durationOf,
  emptyDraft,
  isEditableStatus,
  isShort,
  issueLabel,
  issuesAt,
  issuesOf,
  toDraft,
  type Draft,
  type ItemDraft,
  type ItemKind,
  type ShotDraft,
} from "./model";
import { OverlaysTab } from "./OverlaysTab";
import { SheetPanel, type SheetInfo } from "./sheet-panel";
import { Timeline } from "./timeline";

// PROD-02 편집안 폼. 서버 검증(validation)이 정본이다: 저장은 오류가 있어도 허용, 승인은 오류 0·저장 완료일 때만.
// 근거: docs/03_SCREENS_UX.md PROD-02, tasks/task-026.md.

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
const INPUT =
  "min-h-11 w-full rounded-control border border-input bg-bg px-3 text-(length:--text-input) text-text outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";
const BTN = "inline-flex min-h-11 items-center justify-center rounded-control px-4 text-body font-semibold disabled:cursor-not-allowed disabled:opacity-55";
const PRIMARY = cn(BTN, "bg-primary text-primary-fg hover:bg-primary-hover", FOCUS);
const SECONDARY = cn(BTN, "border border-border bg-surface text-text hover:bg-surface-alt", FOCUS);
const CARD = "rounded-panel border border-border bg-surface p-4 tablet:p-5";

export type EditJob = { id: string; title: string; status: ProductionStatus; failed_stage: "prepare" | "audio" | "render" | null };
export type EditRevision = { rev_no: number; spec: Record<string, unknown>; validation: Validation; approved_at: string | null };

type Section = "hook" | "items" | "shots" | "sheet";
const SECTIONS: { id: Section; label: string }[] = [
  { id: "hook", label: "훅" },
  { id: "items", label: "자막" },
  { id: "shots", label: "구도" },
  { id: "sheet", label: "시트" },
];

const ISSUE_TONE = "text-caption text-danger";

function IssueList({ list, tone = "error" }: { list: SpecIssue[]; tone?: "error" | "warn" }) {
  if (list.length === 0) return null;
  return (
    <ul className={cn("flex flex-col gap-0.5", tone === "error" ? ISSUE_TONE : "text-caption text-warning")}>
      {list.map((i, n) => (
        <li key={`${i.code}-${i.path}-${n}`} role={tone === "error" ? "alert" : undefined}>
          {issueLabel(i)}: {i.message}
        </li>
      ))}
    </ul>
  );
}

function Field({ id, label, required, hint, children, issues }: { id: string; label: string; required?: boolean; hint?: string; children: ReactNode; issues?: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-body font-medium text-text">
        {label}
        {required && (
          <span aria-hidden className="text-danger">
            {" "}
            *
          </span>
        )}
      </label>
      {children}
      {hint && <p className="text-caption text-text-muted">{hint}</p>}
      {issues}
    </div>
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

function RowShell({ title, badges, onRemove, disabled, issues, children }: { title: string; badges?: ReactNode; onRemove: () => void; disabled: boolean; issues: SpecIssue[]; children: ReactNode }) {
  return (
    <li className={cn("flex flex-col gap-2 rounded-card border bg-bg p-3", issues.length > 0 ? "border-danger" : "border-border")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-body font-semibold">
          {title}
          {badges}
        </span>
        <button type="button" disabled={disabled} onClick={onRemove} className={cn(SECONDARY, "min-h-11")}>
          삭제
        </button>
      </div>
      {children}
      <IssueList list={issues} />
    </li>
  );
}

const SHORT_BADGE = <span className="rounded-chip bg-warning-soft px-2 py-0.5 text-caption font-semibold text-warning-soft-fg">1.4초 미만</span>;

export function EditForm({
  job,
  revision,
  sheet,
}: {
  job: EditJob;
  revision: EditRevision | null;
  sheet: SheetInfo | null;
}) {
  const router = useRouter();
  const editable = isEditableStatus(job.status, job.failed_stage);
  const initial = useMemo(() => (revision ? toDraft(revision.spec) : emptyDraft()), [revision]);

  const [draft, setDraft] = useState<Draft>(initial);
  const [snapshot, setSnapshot] = useState(() => JSON.stringify(initial));
  const [revNo, setRevNo] = useState<number | null>(revision?.rev_no ?? null);
  const [validation, setValidation] = useState<Validation>(revision?.validation ?? { errors: [], warnings: [] });
  const [approvedAt, setApprovedAt] = useState<string | null>(revision?.approved_at ?? null);
  const [localErr, setLocalErr] = useState<{ path: string; message: string } | null>(null);
  const [rejected, setRejected] = useState(false); // 마지막 저장이 400으로 거부돼 validation이 저장본이 아님
  const [conflict, setConflict] = useState(false);
  const [phase, setPhase] = useState<"idle" | "saving" | "approving" | "uploading">("idle");
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [section, setSection] = useState<Section>("hook");
  const [tab, setTab] = useState<"edit" | "comment" | "source">("edit");
  const [audioSec, setAudioSec] = useState<number | null>(null);
  const busy = phase !== "idle";
  const lock = !editable || busy || conflict;
  const fileRef = useRef<HTMLInputElement>(null);

  const dirty = JSON.stringify(draft) !== snapshot;
  const { errors, warnings } = validation;
  const stale = dirty || rejected;

  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const setShot = (i: number, p: Partial<ShotDraft>) => set({ shots: draft.shots.map((s, n) => (n === i ? { ...s, ...p } : s)) });
  const setItem = (i: number, p: Partial<ItemDraft>) => set({ items: draft.items.map((s, n) => (n === i ? { ...s, ...p } : s)) });

  function handleFail<T>(r: Extract<EditResult<T>, { ok: false }>): void {
    if (r.status === 401) {
      window.location.assign(SESSION_EXPIRED_PATH);
      return;
    }
    if (r.status === 409) {
      setConflict(true);
      setMessage({ tone: "error", text: r.message });
    } else {
      setMessage({ tone: "error", text: r.message });
    }
    if (r.status === 400 && r.errors) {
      setValidation({ errors: r.errors, warnings: r.warnings ?? [] });
      setRejected(true);
    }
  }

  async function save(): Promise<boolean> {
    if (lock || revNo === null) return false;
    setMessage(null);
    const built = buildSpec(draft);
    if (!built.ok) {
      setLocalErr({ path: built.path, message: built.message });
      setMessage({ tone: "error", text: "숫자가 아닌 칸이 있어 저장하지 못했습니다." });
      return false;
    }
    setLocalErr(null);
    setPhase("saving");
    const r = await saveRevision(job.id, built.spec, revNo);
    setPhase("idle");
    if (!r.ok) {
      handleFail(r);
      return false;
    }
    const rev = r.data.revision;
    setRevNo(rev.rev_no);
    setValidation(rev.validation);
    setApprovedAt(rev.approved_at);
    setRejected(false);
    setSnapshot(JSON.stringify(draft));
    setMessage({ tone: "ok", text: rev.validation.errors.length > 0 ? `저장했습니다. 검증 오류 ${rev.validation.errors.length}건이 있습니다.` : "저장했습니다." });
    return true;
  }

  const blockers = approveBlockers({ status: job.status, hasRevision: revNo !== null, dirty, approved: approvedAt !== null, errorCount: rejected ? Math.max(errors.length, 1) : errors.length, overlayErrorCount: errors.filter((i) => i.path.startsWith("overlays")).length, busy });

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

  async function upload(file: File) {
    if (lock) return;
    setMessage(null);
    const mime = audioMime(file);
    if (!mime) return setMessage({ tone: "error", text: "wav·mp3·m4a 파일만 올릴 수 있습니다." });
    if (file.size === 0 || file.size > MAX_AUDIO_BYTES) return setMessage({ tone: "error", text: "음성 파일은 50MB 이하여야 합니다." });
    setPhase("uploading");
    const t = await requestHookAudio(job.id, file.size, mime);
    if (!t.ok) {
      setPhase("idle");
      return handleFail(t);
    }
    if (!(await putAudio(t.data.upload_url, file, mime))) {
      setPhase("idle");
      return setMessage({ tone: "error", text: "음성 업로드에 실패했습니다. 다시 시도하세요." });
    }
    const c = await completeHookAudio(job.id, t.data.asset.id);
    setPhase("idle");
    if (!c.ok) return handleFail(c);
    set({ audioAssetId: t.data.asset.id, tts: null });
    setMessage({ tone: "ok", text: "훅 음성을 올렸습니다. 저장하면 편집안에 반영됩니다." });
    const url = URL.createObjectURL(file);
    const a = new Audio(url);
    a.onloadedmetadata = () => {
      setAudioSec(Number.isFinite(a.duration) ? a.duration : null);
      URL.revokeObjectURL(url);
    };
    a.onerror = () => URL.revokeObjectURL(url);
    if (fileRef.current) fileRef.current.value = "";
  }

  function cancel() {
    if (dirty && !window.confirm("저장하지 않은 변경이 있습니다. 나가시겠습니까?")) return;
    router.push(`/production/${encodeURIComponent(job.id)}`);
  }

  const loc = (path: string) => (localErr?.path === path ? [{ code: "input.number", path, message: localErr.message }] : []);
  const at = (path: string) => [...issuesAt(errors, path), ...loc(path)];
  const firstItemLen = draft.items[0] ? Number(draft.items[0].end) - Number(draft.items[0].start) : NaN;
  const hookWarn = audioSec !== null && Number.isFinite(firstItemLen) && audioSec > firstItemLen + 0.001;
  const vis = (s: Section) => (tab !== "edit" ? "hidden" : cn(section === s ? "flex" : "hidden", "tablet:flex"));

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
      {/* 탭: 언어·편집안·댓글·출처. ja·댓글·출처는 후속 작업(댓글·출처는 task-032) */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-border text-body">
        <div role="tablist" aria-label="언어" className="flex gap-4">
          <span role="tab" aria-selected="true" className="border-b-2 border-primary py-2 font-semibold">
            ko
          </span>
          <span role="tab" aria-selected="false" aria-disabled="true" title="일본어판은 번역 후 만들 수 있습니다" className="py-2 text-text-muted">
            ja
          </span>
        </div>
        <div role="tablist" aria-label="편집안 탭" className="flex gap-4">
          {(
            [
              { id: "edit", label: "편집안" },
              { id: "comment", label: "댓글" },
              { id: "source", label: "출처" },
            ] as const
          ).map((t) => (
            <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)} className={cn("min-h-11 py-2", FOCUS, tab === t.id ? "border-b-2 border-primary font-semibold" : "text-text-muted")}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* ~767 섹션 탭 4개 */}
      <div role="tablist" aria-label="편집 구역" className={cn("gap-2 tablet:hidden", tab === "edit" ? "flex" : "hidden")}>
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
          편집안 초안이 아직 없습니다. 초안이 만들어지면 이 양식으로 고칠 수 있습니다(AI 초안 채우기는 후속 작업).
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
                {issueLabel(i)}
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
                {issueLabel(i)}
                {i.path ? ` (${i.path})` : ""}: {i.message}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-label="분석 시트" className={cn(CARD, "flex-col gap-2", vis("sheet"))}>
        <h2 className="text-h2 font-bold">분석 시트</h2>
        <SheetPanel info={sheet} />
      </section>

      <section aria-label="제목·훅" className={cn(CARD, "flex-col gap-4", vis("hook"))}>
        <h2 className="text-h2 font-bold">제목·훅</h2>
        {([0, 1] as const).map((n) => (
          <Field key={n} id={`ed-h${n}`} label={`제목 ${n + 1}줄`} required issues={<IssueList list={at(`header.lines.${n}`)} />}>
            <input
              id={`ed-h${n}`}
              className={INPUT}
              value={draft.header[n]}
              maxLength={100}
              disabled={lock}
              aria-invalid={at(`header.lines.${n}`).length > 0}
              onChange={(e) => set({ header: n === 0 ? [e.target.value, draft.header[1]] : [draft.header[0], e.target.value] })}
            />
          </Field>
        ))}
        <Field id="ed-hook" label="첫 훅 문구" required issues={<IssueList list={[...issuesOf(errors, "hook.text"), ...issuesOf(errors, "hook")]} />}>
          <input id="ed-hook" className={INPUT} value={draft.hookText} disabled={lock} aria-invalid={issuesOf(errors, "hook.text").length > 0} onChange={(e) => set({ hookText: e.target.value })} />
        </Field>
        <Field
          id="ed-audio"
          label="훅 음성 (첨부 업로드)"
          hint={draft.audioAssetId ? "첨부 음성이 지정되어 있습니다." : draft.tts ? "현재 TTS 음성을 쓰고 있습니다. 워커 설정에서 TTS가 꺼져 있으면 실패합니다. 파일을 올리면 첨부 음성으로 바뀝니다." : "wav·mp3·m4a, 50MB 이하"}
          issues={<IssueList list={issuesAt(errors, "hook.audio_asset_id")} />}
        >
          <input ref={fileRef} id="ed-audio" type="file" accept={AUDIO_ACCEPT} disabled={lock} className={cn(INPUT, "py-2")} onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />
        </Field>
        <div className="flex flex-col gap-1" aria-live="polite">
          <p className="text-body font-medium">훅 카운터</p>
          <p className="text-caption text-text-muted">
            첫 자막 {Number.isFinite(firstItemLen) ? `${Math.round(firstItemLen * 100) / 100}초` : "-"}
            {audioSec !== null ? ` · 올린 음성 ${Math.round(audioSec * 100) / 100}초` : " · 음성 길이는 올린 직후에만 알 수 있습니다"}
          </p>
          {hookWarn && <p className="text-caption text-warning">훅 음성이 첫 자막보다 깁니다. 승인은 막지 않으며 최종 판정은 렌더 후 작업 화면에서 안내합니다.</p>}
        </div>
        <Field id="ed-duration" label="전체 길이(초)" required issues={<IssueList list={[...issuesOf(errors, "duration"), ...loc("duration")]} />}>
          <input id="ed-duration" inputMode="decimal" className={INPUT} value={draft.duration} disabled={lock} aria-invalid={issuesOf(errors, "duration").length > 0} onChange={(e) => set({ duration: e.target.value })} />
        </Field>
      </section>

      <section aria-label="자막 행" className={cn(CARD, "flex-col gap-3", vis("items"))}>
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-h2 font-bold">자막</h2>
          <button
            type="button"
            disabled={lock}
            className={SECONDARY}
            onClick={() => {
              const last = draft.items[draft.items.length - 1];
              const start = last ? last.end : "0";
              set({ items: [...draft.items, { start, end: "", kind: "white", text: "", y: "" }] });
            }}
          >
            ＋ 행
          </button>
        </div>
        <IssueList list={errors.filter((i) => i.path === "items")} />
        {draft.items.length === 0 ? (
          <p className="text-body text-text-muted">자막이 없습니다. 행을 추가하세요(최소 1개).</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {draft.items.map((it, i) => (
              <RowShell key={i} title={`자막 ${i + 1}`} badges={isShort(it) ? SHORT_BADGE : undefined} disabled={lock} onRemove={() => set({ items: draft.items.filter((_, n) => n !== i) })} issues={at(`items.${i}`)}>
                <div className="grid gap-3 tablet:grid-cols-4">
                  <Num id={`it-${i}-s`} label="시작(초)" value={it.start} disabled={lock} bad={at(`items.${i}.start`).length > 0} onChange={(v) => setItem(i, { start: v })} />
                  <Num id={`it-${i}-e`} label="끝(초)" value={it.end} disabled={lock} bad={at(`items.${i}.end`).length > 0} onChange={(v) => setItem(i, { end: v })} />
                  <div className="flex flex-col gap-1">
                    <label htmlFor={`it-${i}-k`} className="text-caption text-text-muted">
                      유형
                    </label>
                    <select id={`it-${i}-k`} className={INPUT} value={it.kind} disabled={lock} onChange={(e) => setItem(i, { kind: e.target.value as ItemKind })}>
                      {(Object.keys(KIND_LABEL) as ItemKind[]).map((k) => (
                        <option key={k} value={k}>
                          {KIND_LABEL[k]}
                        </option>
                      ))}
                    </select>
                  </div>
                  <Num id={`it-${i}-y`} label="Y(선택)" value={it.y} disabled={lock} bad={at(`items.${i}.y`).length > 0} onChange={(v) => setItem(i, { y: v })} />
                </div>
                <div className="flex flex-col gap-1">
                  <label htmlFor={`it-${i}-t`} className="text-caption text-text-muted">
                    문구
                  </label>
                  <input id={`it-${i}-t`} className={INPUT} value={it.text} disabled={lock} aria-invalid={at(`items.${i}.text`).length > 0} onChange={(e) => setItem(i, { text: e.target.value })} />
                </div>
              </RowShell>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="구도 행" className={cn(CARD, "flex-col gap-3", vis("shots"))}>
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-h2 font-bold">구도(컷)</h2>
          <button
            type="button"
            disabled={lock}
            className={SECONDARY}
            onClick={() => {
              const last = draft.shots[draft.shots.length - 1];
              set({ shots: [...draft.shots, { start: last ? last.end : "0", end: "", scale: "1", y: "0" }] });
            }}
          >
            ＋ 행
          </button>
        </div>
        <IssueList list={errors.filter((i) => i.path === "shots")} />
        {draft.shots.length === 0 ? (
          <p className="text-body text-text-muted">구도가 없습니다. 행을 추가하세요(전체 길이를 덮어야 합니다).</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {draft.shots.map((s, i) => (
              <RowShell key={i} title={`구도 ${i + 1}`} disabled={lock} onRemove={() => set({ shots: draft.shots.filter((_, n) => n !== i) })} issues={at(`shots.${i}`)}>
                <div className="grid gap-3 tablet:grid-cols-4">
                  <Num id={`sh-${i}-s`} label="시작(초)" value={s.start} disabled={lock} bad={at(`shots.${i}.start`).length > 0} onChange={(v) => setShot(i, { start: v })} />
                  <Num id={`sh-${i}-e`} label="끝(초)" value={s.end} disabled={lock} bad={at(`shots.${i}.end`).length > 0} onChange={(v) => setShot(i, { end: v })} />
                  <Num id={`sh-${i}-c`} label="배율(1~3)" value={s.scale} disabled={lock} bad={at(`shots.${i}.scale`).length > 0} onChange={(v) => setShot(i, { scale: v })} />
                  <Num id={`sh-${i}-y`} label="세로 오프셋(Y)" value={s.y} disabled={lock} bad={at(`shots.${i}.y`).length > 0} onChange={(v) => setShot(i, { y: v })} />
                </div>
              </RowShell>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="구간 타임라인" className={cn(CARD, "flex-col gap-2", vis("shots"))}>
        <h2 className="text-h2 font-bold">구간 타임라인</h2>
        <Timeline draft={draft} duration={durationOf(draft)} />
      </section>

      {tab !== "edit" && (
        <OverlaysTab
          kind={tab}
          overlays={draft.overlays}
          errors={[...errors, ...(localErr?.path.startsWith("overlays.") ? [{ code: "input.number", path: localErr.path, message: localErr.message }] : [])]}
          warnings={warnings}
          lock={lock}
          onChange={(overlays) => set({ overlays })}
        />
      )}

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
              {(b.id === "errors" || b.id === "overlays") && errors.length > 0 ? (
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
        <button type="button" disabled={busy} onClick={cancel} className={SECONDARY}>
          취소
        </button>
      </div>
    </form>
  );
}
