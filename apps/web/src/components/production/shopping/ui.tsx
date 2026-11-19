import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { RightsBasis, SpecIssue } from "@/server/api/production";
import { BASIS_LABEL } from "./model";

// 쇼핑 화면 공용 조각(스타일 상수·필드·권리 입력). 색·크기는 토큰만 쓴다.

export const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
export const INPUT =
  "min-h-11 w-full rounded-control border border-input bg-bg px-3 text-(length:--text-input) text-text outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";
export const BTN = "inline-flex min-h-11 items-center justify-center rounded-control px-4 text-body font-semibold disabled:cursor-not-allowed disabled:opacity-55";
export const PRIMARY = cn(BTN, "bg-primary text-primary-fg hover:bg-primary-hover", FOCUS);
export const SECONDARY = cn(BTN, "border border-border bg-surface text-text hover:bg-surface-alt", FOCUS);
export const CARD = "rounded-panel border border-border bg-surface p-4 tablet:p-5";

export function Field({ id, label, required, hint, error, children }: { id: string; label: string; required?: boolean; hint?: string; error?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-body font-medium text-text">
        {label}
        {required && (
          <span aria-hidden className="text-danger">
            {" "}
            *
          </span>
        )}
      </label>
      {children}
      {hint && !error && <p className="text-caption text-text-muted">{hint}</p>}
      {error && (
        <p role="alert" className="text-caption text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export function IssueList({ list, tone = "error" }: { list: SpecIssue[]; tone?: "error" | "warn" }) {
  if (list.length === 0) return null;
  return (
    <ul className={cn("flex flex-col gap-0.5 text-caption", tone === "error" ? "text-danger" : "text-warning")}>
      {list.map((i, n) => (
        <li key={`${i.code}-${i.path}-${n}`} role={tone === "error" ? "alert" : undefined}>
          {i.message}
        </li>
      ))}
    </ul>
  );
}

export function BasisSelect({ id, value, bases, disabled, onChange, error }: { id: string; value: "" | RightsBasis; bases: RightsBasis[]; disabled?: boolean; onChange: (v: "" | RightsBasis) => void; error?: string }) {
  return (
    <Field id={id} label="권리 근거" required error={error}>
      <select id={id} className={INPUT} value={value} disabled={disabled} aria-invalid={!!error} onChange={(e) => onChange(e.target.value as "" | RightsBasis)}>
        <option value="">선택</option>
        {bases.map((b) => (
          <option key={b} value={b}>
            {BASIS_LABEL[b]}
          </option>
        ))}
      </select>
    </Field>
  );
}
