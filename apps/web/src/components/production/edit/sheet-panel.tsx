"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { sheetUrl } from "./api";

// 분석 시트 패널. 시트(0.5초 간격 이미지)는 서명 URL을 눌렀을 때만 받아 새 창에서 연다(URL 저장·로그 없음).

export type SheetInfo = { jobId: string; sheetIds: string[]; sourceStart: number; segmentLen: number; sourceDuration: number | null };

/** 클릭 직후 동기로 빈 창을 열고(팝업 차단 회피·opener 차단) URL을 받아 이동한다. 실패하면 창을 닫고 문구를 돌려준다. */
export async function openSheetWindow(
  jobId: string,
  assetId: string,
  fetchUrl: typeof sheetUrl = sheetUrl,
  open: typeof window.open = (...a) => window.open(...a),
): Promise<string | null> {
  const w = open("", "_blank");
  if (w) w.opener = null;
  const r = await fetchUrl(jobId, assetId);
  if (!r.ok) {
    w?.close();
    return r.message;
  }
  if (!w) return "팝업이 차단되었습니다. 팝업을 허용한 뒤 다시 시도하세요.";
  w.location.href = r.data.url;
  return null;
}

export function SheetPanel({ info }: { info: SheetInfo | null }) {
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function open(assetId: string) {
    setBusy(assetId);
    setMsg(null);
    const err = await openSheetWindow(info!.jobId, assetId);
    setBusy(null);
    if (err) setMsg(err);
  }

  if (!info) {
    return (
      <div aria-busy="true" className="flex flex-col gap-2" role="status">
        <span className="sr-only">분석 시트를 불러오는 중</span>
        <span className="h-3 w-2/3 rounded-control bg-border" />
        <span className="h-3 w-1/2 rounded-control bg-border" />
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2 text-body">
      <p className="text-text-muted">
        원본 {info.sourceStart}초부터 {info.segmentLen}초 구간
        {info.sourceDuration ? ` · 원본 길이 ${Math.round(info.sourceDuration)}초` : ""}
      </p>
      {info.sheetIds.length === 0 ? (
        <p className="text-text-muted">준비된 분석 시트가 없습니다.</p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {info.sheetIds.map((id, i) => (
            <li key={id}>
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => void open(id)}
                className={cn("min-h-11 rounded-control border border-border bg-surface px-3 text-body font-semibold hover:bg-surface-alt disabled:opacity-55", "outline-none focus-visible:ring-2 focus-visible:ring-ring")}
              >
                {busy === id ? "여는 중…" : `시트 ${i + 1} 보기`}
              </button>
            </li>
          ))}
        </ul>
      )}
      {msg && (
        <p role="alert" className="text-caption text-danger">
          {msg}
        </p>
      )}
    </div>
  );
}
