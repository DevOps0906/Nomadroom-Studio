"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { EVIDENCE_SESSION_EXPIRED_PATH, fetchEvidence } from "./evidence";
import { EvidenceView, type EvidenceState } from "./evidence-view";

// MON-D2 관측 근거 다이얼로그(fetch 컨테이너) + 후보 카드의 트리거 버튼.
// 401 → 세션 정리 경로, 404 → "목록으로 돌아가기"로 닫으면 router.refresh(). 닫기·id 변경 시 이전 요청 abort.

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

type DialogProps = { candidateId: string; title: string; opsUrl: string; onClose: () => void };

export function EvidenceDialog({ candidateId, title, opsUrl, onClose }: DialogProps) {
  const router = useRouter();
  const ref = useRef<HTMLDialogElement>(null);
  const [state, setState] = useState<EvidenceState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [prevId, setPrevId] = useState(candidateId);
  if (prevId !== candidateId) {
    setPrevId(candidateId);
    setState({ kind: "loading" });
  }
  const titleId = `evidence-title-${candidateId}`;

  useEffect(() => {
    const el = ref.current;
    if (el && !el.open) el.showModal();
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    fetchEvidence(candidateId, ctrl.signal)
      .then((res) => {
        if (ctrl.signal.aborted) return;
        if (res.kind === "unauthorized") window.location.assign(EVIDENCE_SESSION_EXPIRED_PATH);
        else if (res.kind === "ok") setState({ kind: "ok", data: res.data, now: Date.now() });
        else if (res.kind === "not_found") setState({ kind: "not_found" });
        else setState({ kind: "error", retrying: false });
      })
      .catch(() => {
        if (!ctrl.signal.aborted) setState({ kind: "error", retrying: false });
      });
    return () => ctrl.abort();
  }, [candidateId, attempt]);

  function retry() {
    if (state.kind === "error" && state.retrying) return;
    setState({ kind: "error", retrying: true });
    setAttempt((n) => n + 1);
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={() => {
        if (state.kind === "not_found") router.refresh();
        onClose();
      }}
      className="m-auto max-h-[calc(100dvh-2rem)] w-full max-w-lg overflow-y-auto rounded-dialog border border-border bg-surface p-0 text-text shadow-card backdrop:bg-text/40"
    >
      <div className="relative p-5 tablet:p-6">
        <button
          type="button"
          aria-label="닫기"
          onClick={() => ref.current?.close()}
          className={cn("absolute top-2 right-2 inline-flex size-11 items-center justify-center rounded-control text-text-muted hover:bg-surface-alt", FOCUS)}
        >
          <X aria-hidden className="size-5" />
        </button>
        <EvidenceView
          state={state}
          fallbackTitle={title}
          titleId={titleId}
          opsUrl={opsUrl}
          onRetry={retry}
          onClose={() => ref.current?.close()}
        />
      </div>
    </dialog>
  );
}

/** 후보 카드의 "관측 근거" 버튼. 서버 렌더 카드 안에 두는 클라이언트 말단. */
export function EvidenceButton({ candidateId, title, opsUrl }: { candidateId: string; title: string; opsUrl: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
        className={cn("inline-flex min-h-11 items-center rounded-control px-2 text-body font-semibold text-primary hover:bg-surface-alt", FOCUS)}
      >
        관측 근거
      </button>
      {open && <EvidenceDialog candidateId={candidateId} title={title} opsUrl={opsUrl} onClose={() => setOpen(false)} />}
    </>
  );
}
