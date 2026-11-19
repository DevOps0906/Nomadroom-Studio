"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";

// PROD-00 "제작 시작": 유형(일반·쇼핑) → 일반이면 형식(카테고리형·예능형), 쇼핑이면 분야(상품·여행) → 계속.
// 고르기 전에는 "계속"이 꺼져 있다. 근거: docs/03_SCREENS_UX.md PROD-00.

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
const BTN = "inline-flex min-h-11 items-center justify-center rounded-control px-4 text-body font-semibold disabled:cursor-not-allowed disabled:opacity-55";

type Kind = "general" | "shopping";

/** 선택이 끝났을 때만 이동 주소를 돌려준다(일반 → PROD-01 형식 미리 선택, 쇼핑 → PROD-01S 분야 미리 선택). */
export function chooserHref(kind: Kind | null, sub: string | null): string | null {
  if (kind === "general" && (sub === "category" || sub === "variety")) return `/production/new?kind=general&format=${sub}`;
  if (kind === "shopping" && (sub === "product" || sub === "travel")) return `/production/new?kind=shopping&vertical=${sub}`;
  return null;
}

function Radio({ name, value, checked, label, hint, onChange }: { name: string; value: string; checked: boolean; label: string; hint?: string; onChange: () => void }) {
  return (
    <label className={cn("flex min-h-11 cursor-pointer items-start gap-3 rounded-card border p-3", checked ? "border-primary bg-primary-soft" : "border-border bg-surface")}>
      <input type="radio" name={name} value={value} checked={checked} onChange={onChange} className="mt-1 size-5 accent-primary" />
      <span className="flex flex-col">
        <span className="text-body font-semibold">{label}</span>
        {hint && <span className="text-caption text-text-muted">{hint}</span>}
      </span>
    </label>
  );
}

export function TypeChooser() {
  const router = useRouter();
  const [kind, setKind] = useState<Kind | null>(null);
  const [sub, setSub] = useState<string | null>(null);
  const href = chooserHref(kind, sub);
  const pick = (k: Kind) => {
    setKind(k);
    setSub(null);
  };

  return (
    <form
      aria-label="제작 시작"
      onSubmit={(e) => {
        e.preventDefault();
        if (href) router.push(href);
      }}
      className="flex flex-col gap-4 rounded-panel border border-border bg-surface p-4 tablet:p-5"
    >
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-h2 font-bold">유형</legend>
        <div className="grid gap-2 tablet:grid-cols-2">
          <Radio name="pc-kind" value="general" label="일반" hint="카테고리형·예능형 쇼츠" checked={kind === "general"} onChange={() => pick("general")} />
          <Radio name="pc-kind" value="shopping" label="쇼핑" hint="상품·여행 쇼핑 쇼츠(원본 여러 개·권리 입력)" checked={kind === "shopping"} onChange={() => pick("shopping")} />
        </div>
      </fieldset>
      {kind === "general" && (
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-h2 font-bold">형식</legend>
          <div className="grid gap-2 tablet:grid-cols-2">
            <Radio name="pc-sub" value="category" label="카테고리형" checked={sub === "category"} onChange={() => setSub("category")} />
            <Radio name="pc-sub" value="variety" label="예능형" checked={sub === "variety"} onChange={() => setSub("variety")} />
          </div>
        </fieldset>
      )}
      {kind === "shopping" && (
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-h2 font-bold">분야</legend>
          <div className="grid gap-2 tablet:grid-cols-2">
            <Radio name="pc-sub" value="product" label="상품" checked={sub === "product"} onChange={() => setSub("product")} />
            <Radio name="pc-sub" value="travel" label="여행" checked={sub === "travel"} onChange={() => setSub("travel")} />
          </div>
        </fieldset>
      )}
      <div>
        <button type="submit" disabled={!href} className={cn(BTN, "bg-primary text-primary-fg hover:bg-primary-hover", FOCUS)}>
          계속
        </button>
      </div>
    </form>
  );
}
