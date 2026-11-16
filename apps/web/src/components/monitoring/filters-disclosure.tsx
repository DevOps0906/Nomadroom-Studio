"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

// 검색·필터 패널: 모바일(~767)은 접을 수 있고, 태블릿 이상(768~)은 항상 펼친다.
// CSS(::details-content)로 먼저 펼치고, 지원하지 않는 브라우저는 마운트 뒤 open으로 맞춘다.
const TABLET_UP = "(min-width: 768px)";
const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

export function FiltersDisclosure({ activeCount, children }: { activeCount: number; children: ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const mq = window.matchMedia(TABLET_UP);
    const sync = () => {
      if (mq.matches && ref.current) ref.current.open = true;
    };
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  return (
    <section aria-label="검색·필터" className="rounded-panel border border-border bg-surface p-4 tablet:p-5">
      <details ref={ref} open={activeCount > 0 || undefined} className="group tablet:details-content:[content-visibility:visible]">
        <summary
          className={`flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 rounded-control text-body font-semibold tablet:hidden [&::-webkit-details-marker]:hidden ${FOCUS}`}
        >
          <span>
            검색·필터
            {activeCount > 0 && <span className="ml-1 text-caption text-text-muted">({activeCount}개 적용)</span>}
          </span>
          <ChevronDown aria-hidden className="size-5 text-text-muted transition-transform group-open:rotate-180" />
        </summary>
        <div className="mt-3 flex flex-col gap-3 tablet:mt-0">{children}</div>
      </details>
    </section>
  );
}
