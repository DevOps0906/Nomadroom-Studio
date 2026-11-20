"use client";

import { useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { requestAiDraft, type AiDraft, type EditResult } from "../edit/api";
import { CONFIRM_MARK, SENTENCES, charCount } from "./model";
import { CARD, PRIMARY, SECONDARY } from "./ui";

// PROD-02S "AI 대본 3안 만들기"(A-14 shopping). brief 텍스트가 외부 AI(Claude)로 나가므로 실행 전 고지한다.
// 결과는 새 리비전(1안 적용·미승인)으로 서버에 만들어지고, "이 안 사용"은 화면의 대본 4문장만 바꾼다(저장 전).
// AI 텍스트는 비신뢰: React 텍스트 노드로만 그린다. 근거: tasks/task-056.md, docs/04_API.md A-14.

export const AI_SCRIPT_DISCLOSURE = "브리프 텍스트가 외부 AI(Claude)로 전송됩니다.";
export const AI_SCRIPT_DIRTY_CONFIRM = "저장하지 않은 변경이 있습니다. AI 대본을 만들면 화면의 변경은 사라집니다(저장된 편집안은 보관됩니다). 계속할까요?";
export const NARRATION_STALE_NOTE = "대본이 바뀌어 기존 문장별 녹음이 맞지 않을 수 있습니다. 녹음을 다시 올리거나 TTS를 쓰세요.";

export type ScriptVariant = { hook_type: string; sentences: string[]; char_count: number };

const newKey = () => `ai-${crypto.randomUUID()}`;

type KeyResult = { ok: boolean; status?: number; code?: string };
/**
 * 결과가 불명확한 실패면 같은 키로 재시도하고(상태 0·504 NETWORK·500·503·그 밖 5xx, 코드 없는 502),
 * 확정 응답(성공·4xx·서버가 확정한 502 UPSTREAM_ERROR)이면 다음 요청에 새 키. AI 대본·번역 공통.
 */
export const isAmbiguousFailure = (r: KeyResult) => {
  if (r.ok) return false;
  const s = r.status ?? 0;
  if (s === 502) return r.code !== "UPSTREAM_ERROR";
  return s === 0 || s >= 500;
};
/** 요청 뒤 보관할 키: 불명확한 실패면 같은 키 유지, 아니면 null(다음 요청이 새 키를 만든다). */
export const retainKey = (key: string, r: KeyResult): string | null => (isAmbiguousFailure(r) ? key : null);

/** "이 안 사용": 대본 4문장만 바꾸고 나머지(컷·음성·CTA 등)는 그대로 둔다. */
export const applyVariant = <T extends { script: string[] }>(draft: T, sentences: string[]): T => ({ ...draft, script: sentences.slice(0, SENTENCES) });

export const hasNarrationStale = (warnings: { code: string }[]) => warnings.some((w) => w.code === "voice.narration_stale");

/** 3안 카드·확인할 사실 목록(표시만). 선택은 onUse로 위임한다. */
export function AiScriptResult({ variants, facts, staleNarration, disabled, usedIndex, onUse }: { variants: ScriptVariant[]; facts: string[]; staleNarration: boolean; disabled: boolean; usedIndex: number | null; onUse: (i: number) => void }) {
  return (
    <div className="flex flex-col gap-3">
      {staleNarration && (
        <p role="status" className="rounded-control bg-warning-soft px-3 py-2 text-body text-warning-soft-fg">
          {NARRATION_STALE_NOTE}
        </p>
      )}
      <ul aria-label="AI 대본 3안" className="grid gap-3 tablet:grid-cols-3">
        {variants.map((v, i) => {
          const marked = v.sentences.some((s) => s.includes(CONFIRM_MARK));
          return (
            <li key={i} className="flex flex-col gap-2 rounded-card border border-border bg-bg p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-body font-semibold">
                  {i + 1}안 · {v.hook_type}
                </span>
                <span className="text-caption tabular-nums text-text-muted">{v.char_count}자</span>
              </div>
              {marked && <span className="w-fit rounded-chip bg-danger-soft px-2 py-0.5 text-caption font-semibold text-danger-soft-fg">{CONFIRM_MARK}</span>}
              <ol className="flex list-decimal flex-col gap-1 pl-5 text-body">
                {v.sentences.slice(0, SENTENCES).map((s, n) => (
                  <li key={n}>
                    {s}
                    <span className="sr-only"> ({charCount(s)}자)</span>
                  </li>
                ))}
              </ol>
              <button type="button" disabled={disabled} aria-label={`${i + 1}안 사용`} onClick={() => onUse(i)} className={cn(SECONDARY, "mt-auto")}>
                {usedIndex === i ? "사용 중" : "이 안 사용"}
              </button>
            </li>
          );
        })}
      </ul>
      {facts.length > 0 && (
        <section aria-label="확인할 사실" className="rounded-card border border-border bg-bg p-3">
          <h3 className="text-body font-semibold">업로드 전 확인할 사실</h3>
          <ul className="mt-1 list-disc pl-5 text-body">
            {facts.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

export function AiScriptPanel({
  jobId,
  disabled,
  dirty,
  onBusy,
  onApplied,
  onUse,
  onFail,
  request = requestAiDraft,
}: {
  jobId: string;
  disabled: boolean;
  dirty: boolean;
  onBusy: (busy: boolean) => void;
  /** 서버가 만든 새 리비전(1안 적용)을 화면 기준으로 삼는다. */
  onApplied: (revision: AiDraft["revision"]) => void;
  /** 선택한 안의 4문장으로 대본만 교체한다(저장 전). */
  onUse: (sentences: string[]) => void;
  onFail: (r: Extract<EditResult<AiDraft>, { ok: false }>) => void;
  request?: typeof requestAiDraft;
}) {
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const [result, setResult] = useState<{ variants: ScriptVariant[]; facts: string[]; stale: boolean } | null>(null);
  const [used, setUsed] = useState<number | null>(0);
  const keyRef = useRef<string | null>(null);

  async function run() {
    if (disabled || pending) return;
    if (dirty && !window.confirm(AI_SCRIPT_DIRTY_CONFIRM)) return;
    setPending(true);
    onBusy(true);
    const key = keyRef.current ?? newKey();
    const r = await request(jobId, key);
    keyRef.current = retainKey(key, r);
    setPending(false);
    onBusy(false);
    if (!r.ok) {
      setFailed(true);
      return onFail(r);
    }
    const variants = r.data.variants ?? [];
    if (variants.length === 0) {
      setFailed(true);
      return onFail({ ok: false, status: 502, message: "AI 대본 3안을 받지 못했습니다. 다시 시도하세요." });
    }
    setFailed(false);
    setUsed(0);
    setResult({ variants, facts: r.data.facts_to_check ?? [], stale: hasNarrationStale(r.data.revision.validation.warnings) });
    onApplied(r.data.revision);
  }

  return (
    <section aria-label="AI 대본 3안" className={cn(CARD, "flex flex-col gap-3")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-h2 font-bold">AI 대본 3안</h2>
        <button type="button" disabled={disabled || pending} aria-busy={pending} onClick={() => void run()} className={PRIMARY}>
          {pending ? "AI 대본 만드는 중…" : failed ? "다시 시도" : "AI 대본 3안 만들기"}
        </button>
      </div>
      <p className="text-caption text-text-muted">{AI_SCRIPT_DISCLOSURE} 이미지·원본·음성은 보내지 않습니다. 생성하면 새 편집안(미승인)이 만들어지고 기존 편집안은 보관됩니다.</p>
      {failed && (
        <p role="alert" className="rounded-control bg-danger-soft px-3 py-2 text-body text-danger-soft-fg">
          AI 대본을 만들지 못했습니다. 직접 입력한 대본은 그대로 있습니다. 다시 시도할 수 있습니다.
        </p>
      )}
      {result && (
        <AiScriptResult
          variants={result.variants}
          facts={result.facts}
          staleNarration={result.stale}
          disabled={disabled || pending}
          usedIndex={used}
          onUse={(i) => {
            const v = result.variants[i];
            if (!v) return;
            setUsed(i);
            onUse(v.sentences.slice(0, SENTENCES));
          }}
        />
      )}
    </section>
  );
}
