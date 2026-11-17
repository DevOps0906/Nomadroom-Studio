"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { EVIDENCE_SESSION_EXPIRED_PATH } from "@/components/evidence/evidence";

// MON-01 후보 카드의 "사용한 소재" 표시/해제(A-08 중계 /api/candidates/{id}/used).
// 요청 중 잠금, 성공 시 router.refresh(), 401 → 세션 정리 경로. 필터 목록에서 표시하면 카드가 빠지는 것은 의도.

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

export type UsedResultKind = "ok" | "unauthorized" | "not_found" | "error";

export async function setCandidateUsed(id: string, used: boolean, fetchImpl: typeof fetch = fetch): Promise<UsedResultKind> {
  try {
    const res = await fetchImpl(`/api/candidates/${encodeURIComponent(id)}/used`, {
      method: "PATCH",
      cache: "no-store",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ used }),
    });
    if (res.status === 401) return "unauthorized";
    if (res.status === 404) return "not_found";
    return res.ok ? "ok" : "error";
  } catch {
    return "error";
  }
}

export const USED_ERROR_MESSAGES: Record<"not_found" | "error", string> = {
  not_found: "후보를 찾을 수 없습니다. 목록을 새로고침해 주세요.",
  error: "사용 표시를 바꾸지 못했습니다. 다시 시도해 주세요.",
};

export function UsedToggle({ candidateId, used }: { candidateId: string; used: boolean }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    if (pending) return;
    setPending(true);
    setError(null);
    const kind = await setCandidateUsed(candidateId, !used);
    if (kind === "unauthorized") {
      window.location.assign(EVIDENCE_SESSION_EXPIRED_PATH);
      return;
    }
    setPending(false);
    if (kind === "ok") router.refresh();
    else setError(USED_ERROR_MESSAGES[kind]);
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={toggle}
        disabled={pending}
        aria-busy={pending}
        className={cn(
          "inline-flex min-h-11 items-center rounded-control px-2 text-body font-semibold text-text-muted hover:bg-surface-alt disabled:opacity-60",
          FOCUS,
        )}
      >
        {used ? "표시 해제" : "사용함 표시"}
      </button>
      <p aria-live="polite" className="text-caption text-danger">
        {error}
      </p>
    </div>
  );
}
