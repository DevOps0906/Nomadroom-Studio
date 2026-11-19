"use client";

import { cn } from "@/lib/utils";
import type { SpecIssue } from "@/server/api/production";
import { issueLabel, issuesAt, type OverlayDraft, type OverlayKind } from "./model";

// PROD-02 댓글·출처 탭(D-C6). 운영자가 문구·표시 구간·위치를 직접 입력한다. 이미지·URL 첨부는 없다.
// 검증은 서버가 정본이고 여기는 입력과 결과 표시만 한다. 근거: tasks/task-032.md.

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
const INPUT =
  "min-h-11 w-full rounded-control border border-input bg-bg px-3 text-(length:--text-input) text-text outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";
const BTN = "inline-flex min-h-11 items-center justify-center rounded-control border border-border bg-surface px-4 text-body font-semibold text-text hover:bg-surface-alt disabled:cursor-not-allowed disabled:opacity-55";

const COPY: Record<OverlayKind, { title: string; empty: string; rowTitle: string; textLabel: string; add: string }> = {
  comment: { title: "댓글 카드", empty: "댓글 카드가 없습니다. 행을 추가하면 영상 위에 카드로 표시됩니다.", rowTitle: "댓글", textLabel: "댓글 문구", add: "＋ 댓글" },
  source: { title: "출처 표기", empty: "출처 표기가 없습니다. 행을 추가하면 영상 위에 표기됩니다.", rowTitle: "출처", textLabel: "출처 내용", add: "＋ 출처" },
};
const DEFAULT_Y: Record<OverlayKind, string> = { comment: "200", source: "1000" };

function Issues({ list, tone }: { list: SpecIssue[]; tone: "error" | "warn" }) {
  if (list.length === 0) return null;
  return (
    <ul className={cn("flex flex-col gap-0.5 text-caption", tone === "error" ? "text-danger" : "text-warning")}>
      {list.map((i, n) => (
        <li key={`${i.code}-${i.path}-${n}`} role={tone === "error" ? "alert" : undefined}>
          {issueLabel(i)}: {i.message}
        </li>
      ))}
    </ul>
  );
}

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

export function OverlaysTab({
  kind,
  overlays,
  errors,
  warnings,
  lock,
  onChange,
}: {
  kind: OverlayKind;
  overlays: OverlayDraft[];
  errors: SpecIssue[];
  warnings: SpecIssue[];
  lock: boolean;
  onChange: (next: OverlayDraft[]) => void;
}) {
  const c = COPY[kind];
  const rows = overlays.map((o, index) => ({ o, index })).filter((r) => r.o.kind === kind);
  const patch = (index: number, p: Partial<OverlayDraft>) => onChange(overlays.map((o, n) => (n === index ? { ...o, ...p } : o)));
  const at = (list: SpecIssue[], p: string) => issuesAt(list, p);

  return (
    <section aria-label={c.title} className="flex flex-col gap-3 rounded-panel border border-border bg-surface p-4 tablet:p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-h2 font-bold">{c.title}</h2>
        <button
          type="button"
          disabled={lock}
          className={cn(BTN, FOCUS)}
          onClick={() => onChange([...overlays, { kind, text: "", start: "0", end: "", x: "304", y: DEFAULT_Y[kind] }])}
        >
          {c.add}
        </button>
      </div>
      <p className="text-caption text-text-muted">위치는 608×1080 화면에서 카드 중심(x 0~608, y 0~1080)입니다. 같은 종류의 구간은 겹칠 수 없고, 자막과 겹치면 경고만 표시됩니다.</p>
      {rows.length === 0 ? (
        <p className="text-body text-text-muted">{c.empty}</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {rows.map(({ o, index }, n) => {
            const path = `overlays.${index}`;
            const errs = at(errors, path);
            const warns = at(warnings, path);
            return (
              <li key={index} className={cn("flex flex-col gap-2 rounded-card border bg-bg p-3", errs.length > 0 ? "border-danger" : "border-border")}>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-body font-semibold">
                    {c.rowTitle} {n + 1}
                  </span>
                  <button type="button" disabled={lock} className={cn(BTN, FOCUS)} onClick={() => onChange(overlays.filter((_, i) => i !== index))}>
                    삭제
                  </button>
                </div>
                <div className="grid gap-3 tablet:grid-cols-4">
                  <Num id={`ov-${index}-s`} label="시작(초)" value={o.start} disabled={lock} bad={at(errors, `${path}.start`).length > 0} onChange={(v) => patch(index, { start: v })} />
                  <Num id={`ov-${index}-e`} label="끝(초)" value={o.end} disabled={lock} bad={at(errors, `${path}.end`).length > 0} onChange={(v) => patch(index, { end: v })} />
                  <Num id={`ov-${index}-x`} label="위치 X" value={o.x} disabled={lock} bad={at(errors, `${path}.x`).length > 0} onChange={(v) => patch(index, { x: v })} />
                  <Num id={`ov-${index}-y`} label="위치 Y" value={o.y} disabled={lock} bad={at(errors, `${path}.y`).length > 0} onChange={(v) => patch(index, { y: v })} />
                </div>
                <div className="flex flex-col gap-1">
                  <label htmlFor={`ov-${index}-t`} className="text-caption text-text-muted">
                    {c.textLabel}
                  </label>
                  <input id={`ov-${index}-t`} className={INPUT} value={o.text} disabled={lock} aria-invalid={at(errors, `${path}.text`).length > 0} onChange={(e) => patch(index, { text: e.target.value })} />
                </div>
                <Issues list={errs} tone="error" />
                <Issues list={warns} tone="warn" />
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
