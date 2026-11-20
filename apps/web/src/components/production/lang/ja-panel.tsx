"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { EVIDENCE_SESSION_EXPIRED_PATH as SESSION_EXPIRED_PATH } from "@/components/evidence/evidence";
import type { JobFormat, SpecIssue, Validation } from "@/server/api/production";
import type { EditResult } from "../edit/api";
import { retainKey } from "../shopping/ai-script";
import { useLangDirty } from "./dirty-guard";
import { approveJaRevision, requestTranslate, saveJaRevision, type JaRevision } from "./api";
import {
  LOCKED_NOTE,
  SOURCE_CHANGED_NOTE,
  TRANSLATE_DIRTY_CONFIRM,
  TRANSLATE_DISCLOSURE,
  VOICE_NOTE,
  applyTexts,
  approveBlockers,
  extractTexts,
  hasSourceChanged,
  isDirty,
  makeGate,
  textsOf,
} from "./model";

// ja 탭 본문(PROD-02·02V·02S 공통): 일본어판 만들기(A-20) → 번역 초안 수정(A-12 lang=ja) → 승인(A-13 lang=ja).
// 번역 경로 밖 필드는 잠금 표시. 서버 검증이 정본이다. 일본어는 번역된 콘텐츠 값에만 쓰고 UI 문구는 한국어.

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
const BTN = "inline-flex min-h-11 items-center justify-center rounded-control px-4 text-body font-semibold disabled:cursor-not-allowed disabled:opacity-55";
const PRIMARY = cn(BTN, "bg-primary text-primary-fg hover:bg-primary-hover", FOCUS);
const SECONDARY = cn(BTN, "border border-border bg-surface text-text hover:bg-surface-alt", FOCUS);
const CARD = "rounded-panel border border-border bg-surface p-4 tablet:p-5";
const INPUT = "min-h-11 w-full rounded-control border border-input bg-bg px-3 text-(length:--text-input) text-text outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";

export type JaKo = { id: string; rev_no: number; approved_at: string | null } | null;

function Issues({ list, tone }: { list: SpecIssue[]; tone: "error" | "warn" }) {
  if (list.length === 0) return null;
  return (
    <ul className={cn("flex flex-col gap-0.5 text-caption", tone === "error" ? "text-danger" : "text-warning")}>
      {list.map((i, n) => (
        <li key={`${i.code}-${i.path}-${n}`} role={tone === "error" ? "alert" : undefined}>
          {i.code}
          {i.path ? ` (${i.path})` : ""}: {i.message}
        </li>
      ))}
    </ul>
  );
}

export function JaPanel({ job, ko, ja }: { job: { id: string; format: JobFormat }; ko: JaKo; ja: JaRevision | null }) {
  const router = useRouter();
  const [rev, setRev] = useState<JaRevision | null>(ja);
  const [edits, setEdits] = useState<Record<string, string>>(() => (ja ? textsOf(job.format, ja.spec) : {}));
  const [busy, setBusy] = useState<null | "translate" | "save" | "approve">(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [failed, setFailed] = useState(false);
  const keyRef = useRef<string | null>(null);

  const gate = makeGate(ko);
  const validation: Validation = rev?.validation ?? { errors: [], warnings: [] };
  const sourceChanged = hasSourceChanged(validation.errors);
  const dirty = rev ? isDirty(job.format, rev.spec, edits) : false;
  const locked = busy !== null;
  useLangDirty(dirty);
  const blockers = rev ? approveBlockers({ dirty, saving: busy === "save", approved: !!rev.approved_at, errors: validation.errors }) : [];

  function fail(r: Extract<EditResult<unknown>, { ok: false }>) {
    if (r.status === 401) return window.location.assign(SESSION_EXPIRED_PATH);
    setMsg({ tone: "error", text: r.message });
  }

  async function onTranslate() {
    if (locked || !gate.enabled || !ko) return;
    if (dirty && !window.confirm(TRANSLATE_DIRTY_CONFIRM)) return;
    setBusy("translate");
    setMsg(null);
    const key = keyRef.current ?? `tr-${crypto.randomUUID()}`;
    const r = await requestTranslate(job.id, ko.id, key);
    keyRef.current = retainKey(key, r);
    setBusy(null);
    if (!r.ok) {
      setFailed(true);
      return fail(r);
    }
    setFailed(false);
    setRev(r.data.revision);
    setEdits(textsOf(job.format, r.data.revision.spec));
    setMsg({ tone: "ok", text: `번역 초안 rev ${r.data.revision.rev_no}을 만들었습니다. 검토·수정 후 저장하고 승인하세요. (사용 ${r.data.translate_count}회)` });
    router.refresh();
  }

  async function onSave() {
    if (locked || !rev) return;
    setBusy("save");
    setMsg(null);
    const spec = applyTexts(job.format, rev.spec, edits);
    const r = await saveJaRevision(job.id, spec, rev.rev_no);
    setBusy(null);
    if (!r.ok) {
      if (r.errors) setRev({ ...rev, validation: { errors: r.errors, warnings: r.warnings ?? [] } });
      return fail(r);
    }
    const saved = r.data.revision;
    setRev({ ...rev, id: saved.id, rev_no: saved.rev_no, spec, origin: "user", validation: saved.validation, approved_at: saved.approved_at });
    setMsg({ tone: "ok", text: `저장했습니다. (rev ${saved.rev_no})` });
    router.refresh();
  }

  async function onApprove() {
    if (locked || !rev || blockers.length > 0) return;
    setBusy("approve");
    setMsg(null);
    const r = await approveJaRevision(job.id, rev.rev_no);
    setBusy(null);
    if (!r.ok) {
      if (r.errors) setRev({ ...rev, validation: { errors: r.errors, warnings: r.warnings ?? [] } });
      return fail(r);
    }
    setRev({ ...rev, approved_at: r.data.revision.approved_at });
    setMsg({ tone: "ok", text: "일본어판을 승인했습니다. 렌더는 작업·검수 화면의 ja 탭에서 요청하세요." });
    router.refresh();
  }

  const translateBtn = (label: string) => (
    <button type="button" disabled={locked || !gate.enabled} aria-busy={busy === "translate"} onClick={() => void onTranslate()} className={rev ? SECONDARY : PRIMARY}>
      {busy === "translate" ? "번역 중…" : failed ? "다시 시도" : label}
    </button>
  );

  const disclosure = <p className="text-caption text-text-muted">{TRANSLATE_DISCLOSURE}</p>;
  const gateReason =
    !gate.enabled && gate.reason ? (
      <p role="status" className="text-caption text-warning">
        {gate.reason}
      </p>
    ) : null;
  const message = msg && (
    <p role={msg.tone === "error" ? "alert" : "status"} className={cn("text-body", msg.tone === "error" ? "text-danger" : "text-success")}>
      {msg.text}
    </p>
  );

  if (!rev) {
    return (
      <section aria-label="일본어판 만들기" className={cn(CARD, "flex flex-col items-start gap-3")}>
        <h2 className="text-h2 font-bold">일본어판 만들기</h2>
        <p className="text-body text-text-muted">승인된 ko 편집안에서 일본어판을 만듭니다. 컷·구도·마스크는 ko 값을 그대로 복사하고 문구는 구어체 번역 초안으로 채웁니다.</p>
        {disclosure}
        {translateBtn("일본어판 만들기")}
        {gateReason}
        {failed && (
          <p role="alert" className="text-body text-danger">
            번역에 실패했습니다. 다시 시도할 수 있습니다.
          </p>
        )}
        {message}
      </section>
    );
  }

  const fields = extractTexts(job.format, rev.spec);
  return (
    <div className="flex flex-col gap-4">
      <section aria-label="일본어판 상태" className={cn(CARD, "flex flex-col gap-3")}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-h2 font-bold">
            일본어판 rev {rev.rev_no}
            <span className="ml-2 text-caption font-normal text-text-muted">
              {rev.approved_at ? "승인됨" : "미승인"} · {rev.origin === "ai_draft" ? "번역 초안" : "수정본"}
            </span>
          </h2>
          {sourceChanged && translateBtn("다시 만들기")}
        </div>
        {sourceChanged && (
          <p role="alert" className="rounded-control bg-warning-soft px-3 py-2 text-body text-warning-soft-fg">
            {SOURCE_CHANGED_NOTE}
          </p>
        )}
        {sourceChanged && gateReason}
        {sourceChanged && disclosure}
      </section>

      <section aria-label="번역 문구" className={cn(CARD, "flex flex-col gap-3")}>
        <h2 className="text-h2 font-bold">번역 문구</h2>
        {fields.length === 0 && <p className="text-body text-text-muted">수정할 문구가 없습니다.</p>}
        {fields.map((f) => (
          <div key={f.key} className="flex flex-col gap-1">
            <label htmlFor={`ja-${f.key}`} className="text-body font-medium">
              {f.label}
            </label>
            <input id={`ja-${f.key}`} lang="ja" className={INPUT} disabled={locked} value={edits[f.key] ?? f.value} onChange={(e) => setEdits((p) => ({ ...p, [f.key]: e.target.value }))} />
          </div>
        ))}
      </section>

      <section aria-label="잠금 필드" className={cn(CARD, "flex flex-col gap-1")}>
        <h2 className="text-h2 font-bold">
          <span aria-hidden>🔒 </span>잠금 필드
        </h2>
        <p className="text-body text-text-muted">{LOCKED_NOTE[job.format]}</p>
        <p className="text-body text-text-muted">{VOICE_NOTE}</p>
      </section>

      {(validation.errors.length > 0 || validation.warnings.length > 0) && (
        <section aria-label="검증 결과" className={cn(CARD, "flex flex-col gap-2")}>
          <h2 className="text-h2 font-bold">검증 결과</h2>
          <Issues list={validation.errors} tone="error" />
          <Issues list={validation.warnings} tone="warn" />
        </section>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={locked || !dirty} onClick={() => void onSave()} className={SECONDARY}>
          {busy === "save" ? "저장 중…" : "저장"}
        </button>
        <button type="button" disabled={locked || blockers.length > 0} onClick={() => void onApprove()} className={PRIMARY}>
          {busy === "approve" ? "승인 중…" : "승인"}
        </button>
      </div>
      {blockers.length > 0 && (
        <ul aria-label="승인 불가 사유" className="list-disc pl-5 text-caption text-text-muted">
          {blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      )}
      {message}
    </div>
  );
}
