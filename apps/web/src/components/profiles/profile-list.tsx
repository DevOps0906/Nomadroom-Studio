"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  CATEGORY_ALL,
  MAX_SELECTED,
  canSelectMore,
  formatLabel,
  marketLabel,
  settleSelection,
  toggleSelection,
  type Profile,
  type SaveResult,
} from "./conditions";
import { ConditionsDialog, type SaveConditionsAction } from "./conditions-dialog";
import { FOCUS } from "./conditions-form-view";

export type SaveSelectionAction = (ids: string[]) => Promise<SaveResult>;

type Props = {
  profiles: Profile[];
  saveConditions: SaveConditionsAction;
  saveSelection: SaveSelectionAction;
};

function summary(p: Profile): string {
  const parts = [
    marketLabel(p.market),
    `형식 ${formatLabel(p.format)}`,
    `카테고리 ${p.category ?? CATEGORY_ALL}`,
    `${p.min_views.toLocaleString("ko-KR")}회 이상`,
    `증가율 ${p.max_growth_pct}% 이하`,
  ];
  if (p.cc_only) parts.push("C.C만");
  if (p.include_broadcast) parts.push("방송사 포함");
  return parts.join(" · ");
}

/** 프로필 카드 목록: 검증 대상 선택(최대 3) + 조건 설정 모달 열기. */
export function ProfileList({ profiles, saveConditions, saveSelection }: Props) {
  const router = useRouter();
  const [selected, setSelected] = useState<string[]>(() => profiles.filter((p) => p.selected).map((p) => p.id));
  const [prevProfiles, setPrevProfiles] = useState(profiles);
  if (prevProfiles !== profiles) {
    // router.refresh 뒤 서버 값으로 선택 상태를 다시 맞춘다.
    setPrevProfiles(profiles);
    setSelected(profiles.filter((p) => p.selected).map((p) => p.id));
  }
  const [selError, setSelError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [selPending, startSel] = useTransition();
  const openers = useRef(new Map<string, HTMLButtonElement>());
  const lastEditing = useRef<string | null>(null);
  useEffect(() => {
    // 다이얼로그가 닫히면(저장·새로고침·닫기) 열기 버튼으로 포커스를 돌려준다.
    if (editingId) lastEditing.current = editingId;
    else if (lastEditing.current) {
      openers.current.get(lastEditing.current)?.focus();
      lastEditing.current = null;
    }
  }, [editingId]);
  const editing = profiles.find((p) => p.id === editingId) ?? null;
  const full = !canSelectMore(selected);

  function toggle(id: string) {
    const next = toggleSelection(selected, id);
    if (next === selected) return; // 4개째는 막는다
    const prev = selected;
    setSelected(next);
    setSelError(null);
    setNotice(null);
    startSel(async () => {
      const res = await saveSelection(next);
      if (res.ok) {
        router.refresh();
        return;
      }
      const settled = settleSelection(res, prev, next);
      setSelected(settled.selected);
      setSelError(settled.error);
    });
  }

  if (profiles.length === 0) {
    return (
      <p className="rounded-panel border border-border bg-surface p-5 text-body text-text-muted">
        등록된 프로필이 없습니다. 관리자에게 프로필 추가를 요청하세요.
      </p>
    );
  }

  return (
    <section aria-labelledby="profiles-title" className="rounded-panel border border-border bg-surface p-4 tablet:p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id="profiles-title" className="text-h2 font-bold">
          검증 대상 프로필
        </h2>
        <span aria-live="polite" className="text-body text-text-muted">
          {selected.length}/{MAX_SELECTED}개 선택{selPending ? " · 저장 중…" : ""}
        </span>
      </div>
      {full && <p id="profiles-limit-hint" className="mb-3 text-caption text-text-muted">최대 {MAX_SELECTED}개까지 선택할 수 있습니다. 다른 프로필을 고르려면 하나를 해제하세요.</p>}
      {selError && (
        <p role="alert" className="mb-3 rounded-control bg-danger-soft px-3 py-2 text-body text-danger-soft-fg">
          {selError}
        </p>
      )}
      {notice && (
        <p role="status" className="mb-3 rounded-control bg-success-soft px-3 py-2 text-body text-success-soft-fg">
          {notice}
        </p>
      )}
      <ul className="grid grid-cols-1 gap-3 tablet:grid-cols-2 desktop:grid-cols-3">
        {profiles.map((p) => {
          const on = selected.includes(p.id);
          const blocked = !on && full;
          return (
            <li
              key={p.id}
              className={cn(
                "min-w-0 rounded-card border p-3",
                on ? "border-primary bg-primary-soft" : "border-border bg-surface",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <label className={cn("inline-flex min-h-11 min-w-0 items-center gap-2 text-body font-semibold", blocked && "text-text-muted")}>
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={blocked || selPending}
                    aria-describedby={blocked ? "profiles-limit-hint" : undefined}
                    onChange={() => toggle(p.id)}
                    className={cn("size-4 shrink-0 accent-primary", FOCUS)}
                  />
                  <span className="truncate">{p.name}</span>
                </label>
                <span
                  className={cn(
                    "shrink-0 rounded-chip px-2 py-0.5 text-caption font-semibold",
                    on ? "bg-primary text-primary-fg" : "bg-neutral-soft text-neutral-soft-fg",
                  )}
                >
                  {on ? "검증 선택" : blocked ? "선택 불가(최대 3개)" : "선택 가능"}
                </span>
              </div>
              <p className="mt-1 text-caption text-text-muted">{summary(p)}</p>
              {p.keywords.length > 0 && <p className="mt-1 truncate text-caption text-text-muted">키워드: {p.keywords.join(", ")}</p>}
              <button
                type="button"
                ref={(el) => {
                  if (el) openers.current.set(p.id, el);
                  else openers.current.delete(p.id);
                }}
                onClick={() => {
                  setNotice(null);
                  setEditingId(p.id);
                }}
                className={cn("mt-2 inline-flex min-h-11 items-center rounded-control px-2 text-body font-semibold text-primary hover:bg-surface-alt", FOCUS)}
              >
                조건 설정
              </button>
            </li>
          );
        })}
      </ul>
      {editing && (
        <ConditionsDialog
          key={`${editing.id}-${editing.updated_at}`}
          profile={editing}
          save={saveConditions}
          onClose={() => setEditingId(null)}
          onSaved={() => {
            setEditingId(null);
            setNotice(`'${editing.name}' 조건을 저장했습니다.`);
            router.refresh();
          }}
          onRefresh={() => {
            setEditingId(null);
            router.refresh();
          }}
        />
      )}
    </section>
  );
}
