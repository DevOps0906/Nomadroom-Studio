"use client";

import { useEffect, useState } from "react";
import { fetchReportWarnings } from "../run/api";
import { warningText, warningsForLang, type Lang, type ReportWarning } from "./model";

// PROD-03 검수 리포트 카드의 report warnings(dub_overflow·dub_none 등)를 언어별로 보인다(task-051 D7).
// 리포트 본문은 서버 중계가 warnings만 골라 준다. 값은 비신뢰 데이터라 텍스트 노드로만 그린다.

export function ReportWarnings({ jobId, assetId, lang }: { jobId: string; assetId: string; lang: Lang }) {
  const [state, setState] = useState<{ kind: "loading" } | { kind: "error" } | { kind: "ok"; list: ReportWarning[] }>({ kind: "loading" });

  useEffect(() => {
    let alive = true;
    void fetchReportWarnings(jobId, assetId).then((r) => {
      if (!alive) return;
      setState(r.ok ? { kind: "ok", list: warningsForLang(r.data, lang) } : { kind: "error" });
    });
    return () => {
      alive = false;
    };
  }, [jobId, assetId, lang]);

  if (state.kind === "loading") return <p className="text-caption text-text-muted">리포트 경고를 확인하는 중…</p>;
  if (state.kind === "error") return <p className="text-caption text-text-muted">리포트 경고를 읽지 못했습니다. 리포트를 열어 확인하세요.</p>;
  if (state.list.length === 0) return <p className="text-caption text-text-muted">리포트 경고가 없습니다.</p>;
  return (
    <ul aria-label="리포트 경고" className="flex flex-col gap-1 text-body text-warning">
      {state.list.map((w, i) => (
        <li key={`${w.code}-${i}`}>{warningText(w)}</li>
      ))}
    </ul>
  );
}
