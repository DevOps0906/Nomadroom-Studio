import type { ComponentProps, ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

// 인증 화면 공용 조각. 색·크기는 토큰만 쓴다.
export function AuthCard({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <div className="w-full max-w-sm rounded-panel border border-border bg-surface p-6 shadow-card tablet:max-w-md tablet:p-8">
      <p className="text-caption font-semibold text-text-muted">Nomadroom Studio</p>
      <h1 className="mt-1 text-h1 font-bold text-text">{title}</h1>
      {description && <p className="mt-2 text-body text-text-muted">{description}</p>}
      <div className="mt-6">{children}</div>
    </div>
  );
}

export function AuthField({ label, id, ...input }: { label: string; id: string } & ComponentProps<"input">) {
  return (
    <div className="grid gap-1">
      <label htmlFor={id} className="text-body font-medium text-text">
        {label}
        {input.required && <span aria-hidden className="text-danger">*</span>}
      </label>
      <input
        id={id}
        {...input}
        className="min-h-11 w-full rounded-control border border-input bg-bg px-3 text-(length:--text-input) text-text outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
      />
    </div>
  );
}

export function SubmitButton({ pending, children }: { pending: boolean; children: ReactNode }) {
  return (
    <button
      type="submit"
      disabled={pending}
      aria-busy={pending}
      className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-control bg-primary px-4 text-body font-semibold text-primary-fg hover:bg-primary-hover outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-70"
    >
      {pending && <Loader2 aria-hidden data-testid="spinner" className="size-4 animate-spin" />}
      {children}
    </button>
  );
}

export function AuthAlert({ tone, id, children }: { tone: "danger" | "success"; id?: string; children: ReactNode }) {
  return (
    <p
      id={id}
      role={tone === "danger" ? "alert" : "status"}
      className={cn(
        "rounded-control px-3 py-2 text-body",
        tone === "danger" ? "bg-danger-soft text-danger-soft-fg" : "bg-success-soft text-success-soft-fg",
      )}
    >
      {children}
    </p>
  );
}

export function AuthLink(props: ComponentProps<"a">) {
  return <a {...props} className="text-body text-primary underline-offset-4 hover:underline outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-control" />;
}
