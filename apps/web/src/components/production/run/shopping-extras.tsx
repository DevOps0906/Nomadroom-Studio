"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { EVIDENCE_SESSION_EXPIRED_PATH as SESSION_EXPIRED_PATH } from "@/components/evidence/evidence";
import type { ProductionAsset, PublishText } from "@/server/api/production";
import { formatBytes } from "../format";
import { fetchPublishText } from "../shopping/api";
import { BASIS_LABEL } from "../shopping/model";

// PROD-03 쇼핑 전용 카드: 게시 문구(A-21)·출처·권리 목록. 근거: docs/03_SCREENS_UX.md PROD-03, tasks/task-046.md.

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
const BTN = "inline-flex min-h-11 items-center justify-center rounded-control px-4 text-body font-semibold disabled:cursor-not-allowed disabled:opacity-55";
const SECONDARY = cn(BTN, "border border-border bg-surface text-text hover:bg-surface-alt", FOCUS);
const CARD = "rounded-panel border border-border bg-surface p-4 tablet:p-5";

const FIELDS: { key: keyof PublishText; label: string }[] = [
  { key: "caption", label: "설명란(첫 줄 대가성 표기·댓글 키워드 안내)" },
  { key: "pinned_comment", label: "고정 댓글" },
  { key: "recommended_time", label: "업로드 권장 시각 메모" },
];

/** 클립보드에 복사한다. 실패하면 false(권한·비보안 컨텍스트). 내용은 저장·로그하지 않는다. */
export async function copyText(text: string, clip: Pick<Clipboard, "writeText"> | undefined = typeof navigator === "undefined" ? undefined : navigator.clipboard): Promise<boolean> {
  try {
    if (!clip) return false;
    await clip.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function PublishTextView({ text, onCopy }: { text: PublishText; onCopy?: (key: keyof PublishText) => void }) {
  return (
    <dl className="flex flex-col gap-3">
      {FIELDS.map((f) => (
        <div key={f.key} className="flex flex-col gap-1">
          <dt className="flex flex-wrap items-center justify-between gap-2 text-body font-medium">
            {f.label}
            {onCopy && (
              <button type="button" className={SECONDARY} onClick={() => onCopy(f.key)} aria-label={`${f.label} 복사`}>
                복사
              </button>
            )}
          </dt>
          <dd className="whitespace-pre-wrap break-words rounded-card bg-bg p-3 text-body">{text[f.key] || "(없음)"}</dd>
        </div>
      ))}
    </dl>
  );
}

/** 게시 문구(쇼핑만, 완료된 렌더가 있을 때). 제휴 링크가 들어 있어 화면 메모리에만 두고 저장하지 않는다. */
export function PublishTextCard({ jobId, lang = "ko" }: { jobId: string; lang?: "ko" | "ja" }) {
  const [state, setState] = useState<{ kind: "loading" } | { kind: "error"; message: string } | { kind: "ok"; text: PublishText }>({ kind: "loading" });
  const [note, setNote] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    void fetchPublishText(jobId, lang).then((r) => {
      if (!alive) return;
      if (r.ok) return setState({ kind: "ok", text: r.data.text });
      if (r.status === 401) return window.location.assign(SESSION_EXPIRED_PATH);
      setState({ kind: "error", message: r.message });
    });
    return () => {
      alive = false;
    };
  }, [jobId, lang, tick]);

  async function onCopy(key: keyof PublishText) {
    if (state.kind !== "ok") return;
    const label = FIELDS.find((f) => f.key === key)!.label;
    setNote((await copyText(state.text[key])) ? `${label}을(를) 복사했습니다.` : "복사하지 못했습니다. 글을 직접 선택해 복사하세요.");
  }

  return (
    <section aria-label="게시 문구" className={cn(CARD, "flex flex-col gap-3")}>
      <h2 className="text-h2 font-bold">게시 문구</h2>
      <p className="text-caption text-text-muted">자동 게시는 하지 않습니다. 복사해서 직접 올리세요.</p>
      {state.kind === "loading" && (
        <p role="status" className="text-text-muted">
          게시 문구를 불러오는 중…
        </p>
      )}
      {state.kind === "error" && (
        <div className="flex flex-col items-start gap-2">
          <p role="alert" className="text-body text-danger">
            {state.message}
          </p>
          <button
            type="button"
            className={SECONDARY}
            onClick={() => {
              setState({ kind: "loading" });
              setTick((n) => n + 1);
            }}
          >
            다시 시도
          </button>
        </div>
      )}
      {state.kind === "ok" && <PublishTextView text={state.text} onCopy={(k) => void onCopy(k)} />}
      {note && (
        <p role="status" className="text-caption text-text-muted">
          {note}
        </p>
      )}
    </section>
  );
}

const RIGHTS_KINDS: Record<string, string> = { source_upload: "영상 원본", image: "사진", bgm: "BGM", narration: "녹음" };

/** 출처·권리 목록. 권리 값은 A-09 상세가 주는 경우에만 채우고, 없으면 조회 불가 안내를 보인다. */
export function RightsList({ assets }: { assets: ProductionAsset[] }) {
  const rows = assets.filter((a) => a.kind in RIGHTS_KINDS);
  const known = rows.some((a) => a.rights);
  return (
    <section aria-label="출처·권리 목록" className={cn(CARD, "flex flex-col gap-3")}>
      <h2 className="text-h2 font-bold">출처·권리 목록</h2>
      {rows.length === 0 ? (
        <p className="text-body text-text-muted">사용자가 올린 자산이 없습니다.</p>
      ) : (
        <>
          {!known && <p className="text-caption text-text-muted">권리 정보가 아직 입력되지 않았습니다. 쇼핑 자산은 올릴 때 권리 근거를 입력해야 합니다.</p>}
          <ul className="flex flex-col gap-2">
            {rows.map((a, i) => (
              <li key={a.id} className="rounded-card border border-border bg-bg p-3 text-body">
                <p className="font-semibold">
                  {RIGHTS_KINDS[a.kind]} {i + 1}
                  {a.size_bytes ? <span className="ml-2 text-caption font-normal text-text-muted">{formatBytes(a.size_bytes)}</span> : null}
                </p>
                {a.rights ? (
                  <dl className="mt-1 grid gap-x-4 gap-y-1 text-caption tablet:grid-cols-2">
                    <div>
                      <dt className="inline text-text-muted">권리 근거: </dt>
                      <dd className="inline">{BASIS_LABEL[a.rights.basis] ?? a.rights.basis}</dd>
                    </div>
                    <div>
                      <dt className="inline text-text-muted">출처 URL: </dt>
                      <dd className="inline break-all">{a.rights.source_url || "-"}</dd>
                    </div>
                    <div>
                      <dt className="inline text-text-muted">저작자: </dt>
                      <dd className="inline">{a.rights.author || "-"}</dd>
                    </div>
                    <div>
                      <dt className="inline text-text-muted">사람 등장: </dt>
                      <dd className="inline">{a.rights.has_person ? "예" : "아니오"}</dd>
                    </div>
                    <div>
                      <dt className="inline text-text-muted">초상권 동의: </dt>
                      <dd className="inline">{a.rights.has_person ? (a.rights.portrait_consent ? "동의" : "미동의") : "-"}</dd>
                    </div>
                  </dl>
                ) : (
                  <p className="mt-1 text-caption text-warning">권리 정보가 입력되지 않았습니다.</p>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
