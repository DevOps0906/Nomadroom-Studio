"use client";

import { useState } from "react";
import { requestAiDraft, type AiDraft, type EditResult } from "./api";

// PROD-02 "AI 초안 채우기"(A-14, P1). 초안은 새 리비전으로만 만들어지고(기존 편집은 보관) 승인하지 않는다.
// 미저장 변경이 있으면 먼저 확인한다(H8). 실패 시 직접 입력은 그대로 두고 "다시 시도"(새 요청 키).
// 근거: tasks/task-029.md#착수-결정 H8, docs/03_SCREENS_UX.md PROD-02.

const BTN =
  "inline-flex min-h-11 items-center justify-center rounded-control px-4 text-body font-semibold disabled:cursor-not-allowed disabled:opacity-55 border border-border bg-surface text-text hover:bg-surface-alt outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

export const AI_DRAFT_DIRTY_CONFIRM = "저장하지 않은 변경이 있습니다. AI 초안을 만들면 화면의 변경은 사라집니다(저장된 편집안은 보관됩니다). 계속할까요?";

/** 성공 안내 문구. 직전 리비전 번호가 있으면 보관 사실을 알린다. */
export function aiDraftNotice(d: Pick<AiDraft, "previous_rev_no" | "ai_draft_count"> & { revision: { rev_no: number } }): string {
  const kept = d.previous_rev_no !== null ? ` 이전 편집안 rev ${d.previous_rev_no}은 보관됨.` : "";
  return `AI 초안 rev ${d.revision.rev_no}을 만들었습니다.${kept} 검토 후 저장·승인하세요. (사용 ${d.ai_draft_count}회)`;
}

const newKey = () => `ai-${crypto.randomUUID()}`;

export function AiDraftButton({
  jobId,
  disabled,
  dirty,
  onBusy,
  onApplied,
  onFail,
  request = requestAiDraft,
}: {
  jobId: string;
  disabled: boolean;
  dirty: boolean;
  onBusy: (busy: boolean) => void;
  onApplied: (revision: AiDraft["revision"]) => void;
  onFail: (r: Extract<EditResult<AiDraft>, { ok: false }>) => void;
  request?: typeof requestAiDraft;
}) {
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function run() {
    if (disabled || pending) return;
    if (dirty && !window.confirm(AI_DRAFT_DIRTY_CONFIRM)) return;
    setNotice(null);
    setPending(true);
    onBusy(true);
    const r = await request(jobId, newKey());
    setPending(false);
    onBusy(false);
    if (!r.ok) {
      setFailed(true);
      return onFail(r);
    }
    setFailed(false);
    onApplied(r.data.revision);
    setNotice(aiDraftNotice(r.data));
  }

  return (
    <>
      <button type="button" disabled={disabled || pending} aria-busy={pending} onClick={() => void run()} className={BTN}>
        {pending ? "AI 초안 만드는 중…" : failed ? "AI 초안 다시 시도" : "AI 초안 채우기"}
      </button>
      {notice && (
        <p role="status" className="rounded-control bg-success-soft px-3 py-2 text-body text-success-soft-fg tablet:basis-full">
          {notice}
        </p>
      )}
    </>
  );
}
