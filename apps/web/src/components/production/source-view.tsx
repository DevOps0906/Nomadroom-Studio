import Link from "next/link";
import type { ReactNode } from "react";
import type { CandidateInfo } from "./source-form";

// PROD-01 화면 조각(서버 렌더): 머리말·후보 정보 카드.

export function SourceHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="flex flex-col gap-1">
      <nav aria-label="경로" className="text-caption text-text-muted">
        <Link href="/production" className="underline-offset-4 hover:underline">
          제작 작업
        </Link>{" "}
        / 원본·구간·출처
      </nav>
      <h1 className="line-clamp-2 text-h1 font-bold">{title}</h1>
      {children}
    </header>
  );
}

const LICENSE_TEXT = { true: "CC(재사용 허용)", false: "그 외", null: "미확인" } as const;

/** MON-01에서 넘어온 후보 정보. 제목은 비신뢰 입력이라 텍스트로만 표시한다. */
export function CandidateCard({ candidate }: { candidate: CandidateInfo }) {
  return (
    <aside aria-label="후보 정보" className="rounded-card border border-border bg-surface-alt p-3 text-body">
      <p className="text-caption font-semibold text-text-muted">후보 정보</p>
      <p className="mt-1 line-clamp-2 font-semibold">{candidate.title}</p>
      <p className="text-caption text-text-muted">라이선스: {LICENSE_TEXT[String(candidate.license_cc) as keyof typeof LICENSE_TEXT]}</p>
    </aside>
  );
}
