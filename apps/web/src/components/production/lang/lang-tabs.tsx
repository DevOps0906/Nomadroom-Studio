"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import { confirmLangLeave } from "./dirty-guard";
import { langHref, type Lang } from "./model";

// 편집 화면 3종(PROD-02·02V·02S)과 PROD-03 공통 언어 탭(ko·ja). 탭 상태는 `?lang=`이라 새로고침·공유에도 유지된다.
// 미저장 편집이 있으면 전환 전에 확인한다(취소하면 이동하지 않음). ~767: 헤더 아래 가로 전폭 칩, 768~: 헤더 오른쪽(부모가 flex로 배치).

const TABS: { lang: Lang; label: string }[] = [
  { lang: "ko", label: "ko 한국어" },
  { lang: "ja", label: "ja 일본어" },
];

export function LangTabs({ basePath, active, jaExists }: { basePath: string; active: Lang; jaExists: boolean }) {
  return (
    <nav aria-label="언어" className="flex w-full gap-2 tablet:w-auto">
      {TABS.map((t) => (
        <Link
          key={t.lang}
          href={langHref(basePath, t.lang)}
          aria-current={t.lang === active ? "page" : undefined}
          onClick={(e) => {
            if (t.lang !== active && !confirmLangLeave()) e.preventDefault();
          }}
          className={cn(
            "inline-flex min-h-11 flex-1 items-center justify-center gap-1 rounded-chip border px-4 text-body font-semibold tablet:flex-none",
            "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
            t.lang === active ? "border-primary bg-primary-soft text-primary-soft-fg" : "border-border bg-surface text-text hover:bg-surface-alt",
          )}
        >
          {t.label}
          {t.lang === "ja" && !jaExists && <span className="text-caption font-normal text-text-muted">(없음)</span>}
        </Link>
      ))}
    </nav>
  );
}
