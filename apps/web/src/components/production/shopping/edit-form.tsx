"use client";

import { useLangDirty } from "@/components/production/lang/dirty-guard";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { EVIDENCE_SESSION_EXPIRED_PATH as SESSION_EXPIRED_PATH } from "@/components/evidence/evidence";
import type { ProductionStatus, ShoppingBrief, ShoppingVertical, SpecIssue, Validation } from "@/server/api/production";
import { AUDIO_ACCEPT, MAX_AUDIO_BYTES, approveRevision, audioMime, saveRevision, type AiDraft, type EditResult } from "../edit/api";
import { AiScriptPanel, applyVariant } from "./ai-script";
import { approveBlockers, isEditableStatus, issuesAt, voicesFor } from "../edit/model";
import { SheetPanel, type SheetInfo } from "../edit/sheet-panel";
import { uploadAsset } from "./api";
import {
  ALL_BASES,
  CONFIRM_MARK,
  disclosureFor,
  SCRIPT_MAX,
  SCRIPT_MIN,
  SENTENCES,
  VERTICAL_LABEL,
  buildShoppingSpec,
  charCount,
  emptyShoppingDraft,
  scriptHints,
  sentenceSegments,
  shoppingIssueLabel,
  toShoppingDraft,
  type CutDraft,
  type MaskDraft,
  type ShoppingDraft,
} from "./model";
import type { RightsBasis } from "@/server/api/production";
import { BasisSelect, CARD, Field, FOCUS, INPUT, IssueList, PRIMARY, SECONDARY } from "./ui";

// PROD-02S 편집안(쇼핑). 서버 검증(validation)이 정본: 저장은 오류가 있어도 허용, 승인은 오류 0·저장 완료일 때만.
// 근거: docs/03_SCREENS_UX.md PROD-02S, tasks/task-046.md. AI 대본·AI 생성 컷(P1·task-054)은 이 화면에 없다.

export type ShoppingEditJob = { id: string; title: string; status: ProductionStatus; failed_stage: "prepare" | "audio" | "render" | null; vertical: ShoppingVertical | null };
export type ShoppingEditRevision = { rev_no: number; spec: Record<string, unknown>; validation: Validation; approved_at: string | null; updated_at: string };
export type EditAsset = { id: string; kind: string; status: "pending" | "ready"; duration_sec: number | null };

type Section = "script" | "cuts" | "voice" | "cta";
const SECTIONS: { id: Section; label: string }[] = [
  { id: "script", label: "대본" },
  { id: "cuts", label: "컷" },
  { id: "voice", label: "음성" },
  { id: "cta", label: "CTA" },
];

const NUM_KEYS = ["src_start", "src_end", "scale", "x", "y"] as const;
const NUM_LABEL: Record<(typeof NUM_KEYS)[number], string> = { src_start: "in(초)", src_end: "out(초)", scale: "배율(1~3)", x: "x", y: "y" };

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

/** 브리프 요약(대본 대조용): 제품명(여행은 목적지)·확인된 사실. */
export function BriefSummary({ vertical, brief }: { vertical: ShoppingVertical | null; brief: ShoppingBrief | null }) {
  const name = vertical === "travel" ? brief?.destination : brief?.product_name;
  return (
    <section aria-label="브리프 요약" className={cn(CARD, "flex flex-col gap-1")}>
      <h2 className="text-h2 font-bold">브리프 요약{vertical ? ` · ${VERTICAL_LABEL[vertical]}` : ""}</h2>
      <p className="text-body">
        <span className="text-text-muted">{vertical === "travel" ? "목적지" : "제품명"}: </span>
        {name || "미입력"}
      </p>
      {brief?.facts && brief.facts.length > 0 ? (
        <ul className="list-disc pl-5 text-body">
          {brief.facts.map((f, i) => (
            <li key={i}>{f}</li>
          ))}
        </ul>
      ) : (
        <p className="text-caption text-text-muted">확인된 사실이 없습니다. 근거 없는 효능·가격 표현은 쓰지 마세요.</p>
      )}
    </section>
  );
}

export function ShoppingEditForm({ job, revision, sheet, brief, assets: initialAssets }: { job: ShoppingEditJob; revision: ShoppingEditRevision | null; sheet: SheetInfo | null; brief: ShoppingBrief | null; assets: EditAsset[] }) {
  const router = useRouter();
  const editable = isEditableStatus(job.status, job.failed_stage);
  const initial = useMemo(() => (revision ? toShoppingDraft(revision.spec) : emptyShoppingDraft()), [revision]);

  const [draft, setDraft] = useState<ShoppingDraft>(initial);
  const [snapshot, setSnapshot] = useState(() => JSON.stringify(initial));
  const [revNo, setRevNo] = useState<number | null>(revision?.rev_no ?? null);
  // task-059: 읽은 리비전 updated_at(다음 저장의 base). 저장·AI 초안 성공 때 갱신, 가공하지 않는다
  const [updatedAt, setUpdatedAt] = useState<string | null>(revision?.updated_at ?? null);
  const [validation, setValidation] = useState<Validation>(revision?.validation ?? { errors: [], warnings: [] });
  const [approvedAt, setApprovedAt] = useState<string | null>(revision?.approved_at ?? null);
  const [localErr, setLocalErr] = useState<{ path: string; message: string } | null>(null);
  const [rejected, setRejected] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [phase, setPhase] = useState<"idle" | "saving" | "approving" | "uploading" | "drafting">("idle");
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [section, setSection] = useState<Section>("script");
  const [assets, setAssets] = useState<EditAsset[]>(initialAssets);
  const [basis, setBasis] = useState<"" | RightsBasis>("own");
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

  const set = (patch: Partial<ShoppingDraft>) => setDraft((d) => ({ ...d, ...patch }));
  const setCut = (i: number, p: Partial<CutDraft>) => set({ cuts: draft.cuts.map((c, n) => (n === i ? { ...c, ...p } : c)) });
  const setMask = (i: number, j: number, p: Partial<MaskDraft>) => setCut(i, { masks: draft.cuts[i]!.masks.map((m, n) => (n === j ? { ...m, ...p } : m)) });

  const ready = assets.filter((a) => a.status === "ready");
  const cutSources = ready.filter((a) => a.kind === "source_upload" || a.kind === "image");
  const imageIds = useMemo(() => new Set(assets.filter((a) => a.kind === "image").map((a) => a.id)), [assets]);
  const narrations = ready.filter((a) => a.kind === "narration");
  const bgms = ready.filter((a) => a.kind === "bgm");
  const sourceLabel = (id: string) => {
    const a = cutSources.find((x) => x.id === id);
    if (!a) return "알 수 없는 원본";
    const n = cutSources.filter((x) => x.kind === a.kind).findIndex((x) => x.id === id) + 1;
    return a.kind === "image" ? `사진 ${n}` : `영상 원본 ${n}`;
  };
  const durationOf = (id: string) => assets.find((a) => a.id === id)?.duration_sec ?? null;

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

  /** A-14가 만든 새 리비전(1안 적용·미승인)을 화면 기준으로 삼는다. */
  function applyAiDraft(rev: AiDraft["revision"]) {
    const next = toShoppingDraft(rev.spec);
    setDraft(next);
    setSnapshot(JSON.stringify(next));
    setRevNo(rev.rev_no);
    setUpdatedAt(rev.updated_at);
    setValidation(rev.validation);
    setApprovedAt(rev.approved_at);
    setRejected(false);
    setLocalErr(null);
    setMessage({ tone: "ok", text: `AI 대본 rev ${rev.rev_no}을 만들었습니다. 3안 중 하나를 골라 검토한 뒤 저장·승인하세요.` });
  }

  async function save(): Promise<boolean> {
    if (lock || revNo === null || updatedAt === null) return false;
    setMessage(null);
    const built = buildShoppingSpec(draft, imageIds);
    if (!built.ok) {
      setLocalErr({ path: built.path, message: built.message });
      setMessage({ tone: "error", text: "입력을 확인하세요. " + built.message });
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

  async function upload(kind: "narration" | "bgm", file: File, sentenceIdx?: number) {
    if (lock) return;
    setMessage(null);
    const mime = audioMime(file);
    if (!mime) return setMessage({ tone: "error", text: "wav·mp3·m4a 파일만 올릴 수 있습니다." });
    if (file.size === 0 || file.size > MAX_AUDIO_BYTES) return setMessage({ tone: "error", text: "음성 파일은 50MB 이하여야 합니다." });
    if (!basis) return setMessage({ tone: "error", text: "권리 근거를 먼저 선택하세요." });
    setPhase("uploading");
    const r = await uploadAsset(job.id, file, kind, mime, { basis });
    setPhase("idle");
    if (!r.ok) {
      if (r.status === 401) return window.location.assign(SESSION_EXPIRED_PATH);
      return setMessage({ tone: "error", text: r.message });
    }
    setAssets((a) => [...a, { id: r.data.assetId, kind, status: "ready", duration_sec: null }]);
    if (kind === "narration" && sentenceIdx !== undefined) set({ narrationIds: draft.narrationIds.map((x, n) => (n === sentenceIdx ? r.data.assetId : x)) });
    else set({ bgmId: r.data.assetId });
    setMessage({ tone: "ok", text: kind === "narration" ? `${(sentenceIdx ?? 0) + 1}번 문장 녹음을 올렸습니다. 저장하면 반영됩니다.` : "BGM을 올렸습니다. 저장하면 반영됩니다." });
  }

  function cancel() {
    if (dirty && !window.confirm("저장하지 않은 변경이 있습니다. 나가시겠습니까?")) return;
    router.push(`/production/${encodeURIComponent(job.id)}`);
  }

  const loc = (path: string): SpecIssue[] => (localErr?.path === path ? [{ code: "input.number", path, message: localErr.message }] : []);
  const at = (path: string) => [...issuesAt(errors, path), ...loc(path)];
  const warnAt = (path: string) => issuesAt(warnings, path);
  const hints = scriptHints(draft.script);
  const segs = sentenceSegments(draft, durationOf);
  const totalSec = segs.reduce((n, s) => n + s.seconds, 0);
  const vis = (s: Section) => cn(section === s ? "flex" : "hidden", "tablet:flex");
  const narrationCount = draft.narrationIds.filter(Boolean).length;

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
      <div role="tablist" aria-label="언어" className="flex gap-4 border-b border-border text-body">
        <span role="tab" aria-selected="true" className="border-b-2 border-primary py-2 font-semibold">
          ko
        </span>
        <span role="tab" aria-selected="false" aria-disabled="true" title="일본어판은 번역 후 만들 수 있습니다" className="py-2 text-text-muted">
          ja
        </span>
      </div>

      <div role="tablist" aria-label="편집 구역" className="flex gap-2 tablet:hidden">
        {SECTIONS.map((s) => (
          <button key={s.id} type="button" role="tab" aria-selected={section === s.id} onClick={() => setSection(s.id)} className={cn("inline-flex min-h-11 grow items-center justify-center rounded-control px-4 text-body font-semibold", FOCUS, section === s.id ? "bg-primary-soft text-primary-soft-fg" : "border border-border text-text")}>
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
          편집안 초안이 아직 없습니다. 초안이 만들어지면 이 양식으로 고칠 수 있습니다.
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
                {shoppingIssueLabel(i)}
                {i.path ? ` (${i.path})` : ""}: {i.message}
                {i.code === "gen.unreviewed" && (
                  <>
                    {" "}
                    <Link href={`/production/${encodeURIComponent(job.id)}/source`} className="underline">
                      원본 화면에서 검수하기
                    </Link>
                  </>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {warnings.length > 0 && (
        <section aria-label="검증 경고" className="rounded-panel border border-border bg-warning-soft p-4 text-body text-warning-soft-fg">
          <p className="font-semibold">경고 {warnings.length}건 (승인을 막지 않습니다)</p>
          <ul className="mt-1 list-disc pl-5">
            {warnings.map((i, n) => (
              <li key={`${i.code}-${i.path}-${n}`}>
                {shoppingIssueLabel(i)}
                {i.path ? ` (${i.path})` : ""}: {i.message}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-label="분석 시트" className={cn(CARD, "flex-col gap-2", vis("cuts"))}>
        <h2 className="text-h2 font-bold">분석 시트</h2>
        <SheetPanel info={sheet} />
      </section>

      <div className={cn("flex-col gap-4", vis("script"))}>
        <BriefSummary vertical={job.vertical} brief={brief} />
        <AiScriptPanel
          jobId={job.id}
          disabled={lock || revNo === null || job.status !== "review"}
          dirty={dirty}
          onBusy={(b) => setPhase(b ? "drafting" : "idle")}
          onApplied={applyAiDraft}
          onUse={(sentences) => setDraft((d) => applyVariant(d, sentences))}
          onFail={handleFail}
        />
        <section aria-label="대본 4문장" className={cn(CARD, "flex flex-col gap-3")}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-h2 font-bold">대본 {SENTENCES}문장</h2>
            <p aria-live="polite" className={cn("text-body font-semibold tabular-nums", hints.outOfRange ? "text-warning" : "text-text")}>
              합계 {hints.total}자 <span className="text-caption font-normal text-text-muted">(권장 {SCRIPT_MIN}~{SCRIPT_MAX})</span>
            </p>
          </div>
          {hints.outOfRange && <p className="text-caption text-warning">글자 수가 권장 범위를 벗어났습니다. 승인은 막지 않습니다.</p>}
          <IssueList list={errors.filter((i) => i.path === "script")} />
          <ol className="flex flex-col gap-3">
            {draft.script.map((t, i) => {
              const issues = at(`script.${i}`);
              return (
                <li key={i} className={cn("flex flex-col gap-1 rounded-card border bg-bg p-3", issues.length > 0 ? "border-danger" : "border-border")}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <label htmlFor={`sc-${i}`} className="flex items-center gap-2 text-body font-semibold">
                      {i + 1}번 문장
                      {hints.marked.includes(i) && <span className="rounded-chip bg-danger-soft px-2 py-0.5 text-caption font-semibold text-danger-soft-fg">{CONFIRM_MARK}</span>}
                    </label>
                    <span className="text-caption tabular-nums text-text-muted" aria-label={`${i + 1}번 문장 글자 수`}>
                      {charCount(t)}자
                    </span>
                  </div>
                  <textarea id={`sc-${i}`} rows={2} className={cn(INPUT, "py-2")} value={t} disabled={lock} aria-invalid={issues.length > 0} onChange={(e) => set({ script: draft.script.map((x, n) => (n === i ? e.target.value : x)) })} />
                  {hints.banned[i] && <p className="text-caption text-warning">금지 문구 &lsquo;{hints.banned[i]}&rsquo;가 있습니다.</p>}
                  <IssueList list={issues} />
                  <IssueList list={warnAt(`script.${i}`)} tone="warn" />
                </li>
              );
            })}
          </ol>
        </section>
      </div>

      <section aria-label="컷 행" className={cn(CARD, "flex-col gap-3", vis("cuts"))}>
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-h2 font-bold">컷 ({draft.cuts.length})</h2>
          <button
            type="button"
            disabled={lock || cutSources.length === 0}
            className={SECONDARY}
            onClick={() => set({ cuts: [...draft.cuts, { source_asset_id: cutSources[0]!.id, src_start: "0", src_end: "3", scale: "1", x: "0", y: "0", sentence: "1", masks: [], motion: "zoom" }] })}
          >
            ＋ 컷
          </button>
        </div>
        <p className="text-caption text-text-muted">문장마다 컷이 1개 이상 필요합니다. 컷 길이 합계는 렌더러가 음성 길이에 맞춰 조정하고 리포트에 기록합니다.</p>
        <IssueList list={errors.filter((i) => i.path === "cuts")} />
        {cutSources.length === 0 && <p className="text-body text-text-muted">준비된 원본이 없습니다. 원본·브리프 화면에서 원본을 올리고 준비를 마치세요.</p>}
        {draft.cuts.length === 0 ? (
          <p className="text-body text-text-muted">컷이 없습니다. ＋ 컷으로 추가하세요(문장마다 1개 이상).</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {draft.cuts.map((c, i) => {
              const isImage = imageIds.has(c.source_asset_id);
              const issues = at(`cuts.${i}`);
              return (
                <li key={i} className={cn("flex flex-col gap-3 rounded-card border bg-bg p-3", issues.length > 0 ? "border-danger" : "border-border")}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-body font-semibold">컷 {i + 1}</span>
                    <span className="flex flex-wrap gap-2">
                      <button type="button" className={SECONDARY} disabled={lock || i === 0} aria-label={`컷 ${i + 1} 위로`} onClick={() => set({ cuts: swap(draft.cuts, i, i - 1) })}>
                        위로
                      </button>
                      <button type="button" className={SECONDARY} disabled={lock || i === draft.cuts.length - 1} aria-label={`컷 ${i + 1} 아래로`} onClick={() => set({ cuts: swap(draft.cuts, i, i + 1) })}>
                        아래로
                      </button>
                      <button type="button" className={SECONDARY} disabled={lock} aria-label={`컷 ${i + 1} 삭제`} onClick={() => set({ cuts: draft.cuts.filter((_, n) => n !== i) })}>
                        삭제
                      </button>
                    </span>
                  </div>
                  <div className="grid gap-3 tablet:grid-cols-3">
                    <Field id={`cut-${i}-sentence`} label="문장 번호">
                      <select id={`cut-${i}-sentence`} className={INPUT} value={c.sentence} disabled={lock} onChange={(e) => setCut(i, { sentence: e.target.value })}>
                        {Array.from({ length: SENTENCES }, (_, n) => (
                          <option key={n} value={String(n + 1)}>
                            {n + 1}번 문장
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field id={`cut-${i}-source`} label="원본 선택">
                      <select id={`cut-${i}-source`} className={INPUT} value={c.source_asset_id} disabled={lock} onChange={(e) => setCut(i, { source_asset_id: e.target.value })}>
                        {!cutSources.some((a) => a.id === c.source_asset_id) && <option value={c.source_asset_id}>알 수 없는 원본</option>}
                        {cutSources.map((a) => (
                          <option key={a.id} value={a.id}>
                            {sourceLabel(a.id)}
                          </option>
                        ))}
                      </select>
                    </Field>
                    {isImage && (
                      <Field id={`cut-${i}-motion`} label="사진 모션">
                        <select id={`cut-${i}-motion`} className={INPUT} value={c.motion} disabled={lock} onChange={(e) => setCut(i, { motion: e.target.value as CutDraft["motion"] })}>
                          <option value="zoom">zoom(기본)</option>
                          <option value="pan">pan</option>
                          <option value="none">none</option>
                        </select>
                      </Field>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-3 tablet:grid-cols-5">
                    {NUM_KEYS.map((k) => (
                      <Num key={k} id={`cut-${i}-${k}`} label={isImage && k === "src_start" ? "시작(초)" : isImage && k === "src_end" ? "표시 끝(초)" : NUM_LABEL[k]} value={c[k]} disabled={lock} bad={at(`cuts.${i}.${k}`).length > 0} onChange={(v) => setCut(i, { [k]: v })} />
                    ))}
                  </div>
                  <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-body font-medium">마스크 ({c.masks.length})</span>
                      <button type="button" className={SECONDARY} disabled={lock} onClick={() => setCut(i, { masks: [...c.masks, { x: "0", y: "0", w: "100", h: "100" }] })}>
                        ＋ 마스크
                      </button>
                    </div>
                    {c.masks.map((m, j) => (
                      <div key={j} className="grid grid-cols-2 items-end gap-3 tablet:grid-cols-5">
                        {(["x", "y", "w", "h"] as const).map((k) => (
                          <Num key={k} id={`cut-${i}-m${j}-${k}`} label={`마스크 ${j + 1} ${k}`} value={m[k]} disabled={lock} bad={at(`cuts.${i}.masks.${j}`).length > 0} onChange={(v) => setMask(i, j, { [k]: v })} />
                        ))}
                        <button type="button" className={SECONDARY} disabled={lock} aria-label={`컷 ${i + 1} 마스크 ${j + 1} 삭제`} onClick={() => setCut(i, { masks: c.masks.filter((_, n) => n !== j) })}>
                          삭제
                        </button>
                      </div>
                    ))}
                  </div>
                  <IssueList list={issues} />
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section aria-label="문장·컷 타임라인" className={cn(CARD, "flex-col gap-2", vis("cuts"))}>
        <h2 className="text-h2 font-bold">문장·컷 타임라인</h2>
        <ol className="flex flex-col gap-2">
          {segs.map((s) => (
            <li key={s.sentence} className="flex items-center gap-2">
              <span className="w-14 shrink-0 text-caption text-text-muted">{s.sentence}번 문장</span>
              <span className="relative h-6 grow overflow-hidden rounded-control bg-neutral-soft" role="img" aria-label={s.empty ? `${s.sentence}번 문장: 컷 없음` : `${s.sentence}번 문장: 컷 ${s.cuts}개 ${Math.round(s.seconds * 10) / 10}초`}>
                <span style={{ width: `${s.empty || totalSec <= 0 ? 100 : Math.max((s.seconds / totalSec) * 100, 2)}%` }} className={cn("absolute inset-y-0 left-0", s.empty ? "bg-danger" : "bg-primary")} />
              </span>
              <span className={cn("w-28 shrink-0 text-caption tabular-nums", s.empty ? "text-danger" : "text-text-muted")}>
                {s.empty ? "컷 없음" : `${Math.round(s.seconds * 10) / 10}초`}
                {s.voiceSec !== null ? ` / 녹음 ${Math.round(s.voiceSec * 10) / 10}초` : ""}
              </span>
            </li>
          ))}
        </ol>
        <p className="text-caption text-text-muted">
          <span className="text-danger">빨강</span> 컷이 없는 문장(빈 화면) · 컷 길이는 음성 길이에 맞춰 렌더러가 조정합니다.
        </p>
      </section>

      <div className={cn("flex-col gap-4", vis("voice"))}>
        <section aria-label="음성" className={cn(CARD, "flex flex-col gap-3")}>
          <h2 className="text-h2 font-bold">
            음성 <span aria-hidden className="text-danger">*</span>
          </h2>
          <fieldset className="flex flex-col gap-2" disabled={lock}>
            <legend className="text-body font-medium text-text">방식(둘 중 하나)</legend>
            <div className="flex flex-wrap gap-4">
              <label className="inline-flex min-h-11 items-center gap-2 text-body">
                <input type="radio" name="sh-voice-mode" checked={draft.mode === "tts"} onChange={() => set({ mode: "tts" })} />
                TTS 음성 사용
              </label>
              <label className="inline-flex min-h-11 items-center gap-2 text-body">
                <input type="radio" name="sh-voice-mode" checked={draft.mode === "narration"} onChange={() => set({ mode: "narration" })} />
                문장별 녹음 4개
              </label>
            </div>
          </fieldset>
          <IssueList list={errors.filter((i) => i.path === "voice" || i.path.startsWith("voice."))} />
          {draft.mode === "tts" ? (
            <div className="grid gap-3 tablet:grid-cols-2">
              <Field id="sh-tts-voice" label="TTS 목소리" error={at("voice.tts.voice")[0]?.message}>
                <select id="sh-tts-voice" className={INPUT} value={draft.tts.voice} disabled={lock} onChange={(e) => set({ tts: { ...draft.tts, voice: e.target.value } })}>
                  {!voicesFor("ko").some((v) => v.id === draft.tts.voice) && <option value={draft.tts.voice}>{draft.tts.voice}</option>}
                  {voicesFor("ko").map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field id="sh-tts-rate" label="TTS 속도" hint="+10%·-10%처럼 부호와 숫자·% 형식. TTS가 꺼져 있으면 렌더가 실패하며 무음으로 대체하지 않습니다." error={at("voice.tts.rate")[0]?.message}>
                <input id="sh-tts-rate" className={INPUT} value={draft.tts.rate} disabled={lock} onChange={(e) => set({ tts: { ...draft.tts, rate: e.target.value } })} />
              </Field>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              <BasisSelect id="sh-narr-basis" value={basis} bases={ALL_BASES} disabled={lock} onChange={setBasis} />
              <p className="text-caption text-text-muted" aria-live="polite">
                녹음 {narrationCount}/{SENTENCES} · wav·mp3·m4a 50MB 이하. 문장 i의 자막 구간은 녹음 i의 실제 길이로 정해집니다.
              </p>
              <ol className="flex flex-col gap-3">
                {draft.narrationIds.map((nid, i) => (
                  <li key={i} className="grid gap-3 rounded-card border border-border bg-bg p-3 tablet:grid-cols-2">
                    <Field id={`nr-${i}-sel`} label={`${i + 1}번 문장 녹음`} required>
                      <select id={`nr-${i}-sel`} className={INPUT} value={nid ?? ""} disabled={lock} onChange={(e) => set({ narrationIds: draft.narrationIds.map((x, n) => (n === i ? e.target.value || null : x)) })}>
                        <option value="">선택 안 함</option>
                        {narrations.map((a, n) => (
                          <option key={a.id} value={a.id}>
                            녹음 파일 {n + 1}
                            {a.duration_sec ? ` (${Math.round(a.duration_sec * 10) / 10}초)` : ""}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field id={`nr-${i}-file`} label="새 녹음 올리기">
                      <input id={`nr-${i}-file`} type="file" accept={AUDIO_ACCEPT} disabled={lock} className={cn(INPUT, "py-2")} onChange={(e) => e.target.files?.[0] && void upload("narration", e.target.files[0], i)} />
                    </Field>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </section>

        <section aria-label="원본 소리·BGM" className={cn(CARD, "flex flex-col gap-3")}>
          <h2 className="text-h2 font-bold">원본 소리·BGM</h2>
          <Field id="sh-source-audio" label="원본 소리">
            <select id="sh-source-audio" className={INPUT} value={draft.sourceAudio} disabled={lock} onChange={(e) => set({ sourceAudio: e.target.value as "mute" | "duck" })}>
              <option value="mute">음소거(기본)</option>
              <option value="duck">낮추기</option>
            </select>
          </Field>
          <div className="grid gap-3 tablet:grid-cols-2">
            <Field id="sh-bgm" label="BGM(자산 선택)" error={at("bgm_asset_id")[0]?.message}>
              <select id="sh-bgm" className={INPUT} value={draft.bgmId ?? ""} disabled={lock} onChange={(e) => set({ bgmId: e.target.value || null })}>
                <option value="">사용 안 함</option>
                {bgms.map((a, n) => (
                  <option key={a.id} value={a.id}>
                    BGM {n + 1}
                  </option>
                ))}
              </select>
            </Field>
            <Field id="sh-bgm-file" label="BGM 올리기" hint="권리 근거(위 음성 방식의 선택값)를 함께 보냅니다. 올린 뒤 저장해야 반영됩니다.">
              <input id="sh-bgm-file" type="file" accept={AUDIO_ACCEPT} disabled={lock} className={cn(INPUT, "py-2")} onChange={(e) => e.target.files?.[0] && void upload("bgm", e.target.files[0])} />
            </Field>
          </div>
          {draft.bgmId && <BasisSelect id="sh-bgm-basis" value={basis} bases={ALL_BASES} disabled={lock} onChange={setBasis} />}
        </section>
      </div>

      <section aria-label="CTA·표기" className={cn(CARD, "flex-col gap-3", vis("cta"))}>
        <h2 className="text-h2 font-bold">CTA·표기</h2>
        <Field id="sh-cta" label="CTA 문구(4번 문장 화면)" required error={at("cta.text")[0]?.message}>
          <input id="sh-cta" className={INPUT} value={draft.cta} maxLength={100} disabled={lock} aria-invalid={at("cta.text").length > 0} onChange={(e) => set({ cta: e.target.value })} />
        </Field>
        <Field id="sh-disclosure" label="표기 문구" hint="언어별 고정 문구(ko 제휴 링크 포함 · ja PR)이며 화면 위치도 고정입니다. 다른 문구는 쓸 수 없습니다.">
          <input id="sh-disclosure" className={INPUT} value={disclosureFor(draft.rest.lang)} readOnly disabled />
        </Field>
      </section>

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
        <button type="button" disabled={busy} onClick={cancel} className={SECONDARY}>
          취소
        </button>
      </div>
    </form>
  );
}

function swap<T>(list: T[], a: number, b: number): T[] {
  const out = [...list];
  [out[a], out[b]] = [out[b]!, out[a]!];
  return out;
}
