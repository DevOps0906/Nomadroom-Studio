import type { ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  CATEGORIES,
  FIELD_LABELS,
  FORMATS,
  MARKETS,
  MAX_KEYWORDS,
  type ConditionsInput,
  type FieldErrors,
  type FieldName,
} from "./conditions";

// MON-D1 조건 폼(상태 없는 뷰). 상태 관리는 conditions-dialog.tsx.

export type FormStatus =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "conflict"; message: string }
  | { kind: "error"; message: string };

export const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
const BTN = cn(
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-control px-4 text-body font-semibold disabled:cursor-not-allowed disabled:opacity-60",
  FOCUS,
);
export const BTN_PRIMARY = cn(BTN, "bg-primary text-primary-fg hover:bg-primary-hover");
export const BTN_DEFAULT = cn(BTN, "border border-border bg-surface text-text hover:border-input");
const CONTROL =
  "min-h-11 w-full rounded-control border bg-bg px-3 text-(length:--text-input) text-text outline-none focus-visible:ring-2 focus-visible:ring-ring";

type Props = {
  formId: string;
  input: ConditionsInput;
  errors: FieldErrors;
  status: FormStatus;
  onChange: (patch: Partial<ConditionsInput>) => void;
  onSubmit: () => void;
  onCancel: () => void;
  onRefresh: () => void;
};

function Field({
  id,
  name,
  label,
  required,
  hint,
  errors,
  children,
}: {
  id: string;
  name: FieldName;
  label: string;
  required?: boolean;
  hint?: string;
  errors: FieldErrors;
  children: ReactNode;
}) {
  const error = errors[name];
  return (
    <div className="grid content-start gap-1">
      <label htmlFor={id} className="text-body font-medium text-text">
        {label}
        {required && <span aria-hidden className="text-danger">*</span>}
      </label>
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-caption text-text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-caption text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

function described(id: string, errors: FieldErrors, name: FieldName, hasHint: boolean) {
  const error = errors[name];
  return {
    "aria-invalid": error ? true : undefined,
    "aria-describedby": error ? `${id}-error` : hasHint ? `${id}-hint` : undefined,
    className: cn(CONTROL, error ? "border-danger" : "border-input"),
  } as const;
}

export function ConditionsFormView({ formId, input, errors, status, onChange, onSubmit, onCancel, onRefresh }: Props) {
  const saving = status.kind === "saving";
  const id = (n: string) => `${formId}-${n}`;
  const errorNames = (Object.keys(errors) as FieldName[]).filter((n) => errors[n]);
  const categories = CATEGORIES.includes(input.category) ? CATEGORIES : [...CATEGORIES, input.category];

  return (
    <form
      id={formId}
      noValidate
      aria-busy={saving}
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      {errorNames.length > 0 && (
        <p role="alert" className="mb-3 rounded-control bg-danger-soft px-3 py-2 text-body text-danger-soft-fg">
          입력값을 확인하세요: {errorNames.map((n) => FIELD_LABELS[n]).join(", ")}
        </p>
      )}
      <div className="grid grid-cols-1 gap-3 tablet:grid-cols-2">
        <Field id={id("market")} name="market" label="시장" required errors={errors}>
          <select
            id={id("market")}
            value={input.market}
            onChange={(e) => onChange({ market: e.target.value })}
            {...described(id("market"), errors, "market", false)}
          >
            {MARKETS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </Field>
        <Field id={id("format")} name="format" label="영상 형식" required errors={errors}>
          <select
            id={id("format")}
            value={input.format}
            onChange={(e) => onChange({ format: e.target.value })}
            {...described(id("format"), errors, "format", false)}
          >
            {FORMATS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </Field>
        <Field id={id("category")} name="category" label="카테고리" errors={errors}>
          <select
            id={id("category")}
            value={input.category}
            onChange={(e) => onChange({ category: e.target.value })}
            {...described(id("category"), errors, "category", false)}
          >
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </Field>
        <Field id={id("min_views")} name="min_views" label="최소 조회수" hint="0 이상 정수" errors={errors}>
          <input
            id={id("min_views")}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            value={input.min_views}
            onChange={(e) => onChange({ min_views: e.target.value })}
            {...described(id("min_views"), errors, "min_views", true)}
          />
        </Field>
        <Field
          id={id("max_growth_pct")}
          name="max_growth_pct"
          label="허용 증가율(%)"
          required
          hint="0~1000, 소수 둘째 자리까지"
          errors={errors}
        >
          <input
            id={id("max_growth_pct")}
            type="text"
            inputMode="decimal"
            autoComplete="off"
            value={input.max_growth_pct}
            onChange={(e) => onChange({ max_growth_pct: e.target.value })}
            {...described(id("max_growth_pct"), errors, "max_growth_pct", true)}
          />
        </Field>
        <Field
          id={id("keywords")}
          name="keywords"
          label="키워드"
          hint={`쉼표로 구분, 최대 ${MAX_KEYWORDS}개`}
          errors={errors}
        >
          <input
            id={id("keywords")}
            type="text"
            autoComplete="off"
            value={input.keywords}
            onChange={(e) => onChange({ keywords: e.target.value })}
            {...described(id("keywords"), errors, "keywords", true)}
          />
        </Field>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
        <label className="inline-flex min-h-11 items-center gap-2 text-body text-text">
          <input
            type="checkbox"
            checked={input.cc_only}
            onChange={(e) => onChange({ cc_only: e.target.checked })}
            className={cn("size-4 accent-primary", FOCUS)}
          />
          C.C만
        </label>
        <label className="inline-flex min-h-11 items-center gap-2 text-body text-text">
          <input
            type="checkbox"
            checked={input.include_broadcast}
            onChange={(e) => onChange({ include_broadcast: e.target.checked })}
            className={cn("size-4 accent-primary", FOCUS)}
          />
          방송사 포함
        </label>
      </div>

      {status.kind === "conflict" && (
        <div role="alert" className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-control bg-warning-soft px-3 py-2 text-body text-warning-soft-fg">
          <span>{status.message}</span>
          <button type="button" onClick={onRefresh} className={BTN_DEFAULT}>
            새로고침
          </button>
        </div>
      )}
      {status.kind === "error" && (
        <p role="alert" className="mt-4 rounded-control bg-danger-soft px-3 py-2 text-body text-danger-soft-fg">
          {status.message}
        </p>
      )}

      <div className="mt-5 flex flex-col-reverse gap-2 tablet:flex-row tablet:justify-end">
        <button type="button" onClick={onCancel} disabled={saving} className={BTN_DEFAULT}>
          취소
        </button>
        <button type="submit" disabled={saving || status.kind === "conflict"} aria-busy={saving} className={BTN_PRIMARY}>
          {saving && <Loader2 aria-hidden data-testid="spinner" className="size-4 animate-spin" />}
          {saving ? "저장 중…" : status.kind === "error" ? "다시 시도" : "저장"}
        </button>
      </div>
    </form>
  );
}
