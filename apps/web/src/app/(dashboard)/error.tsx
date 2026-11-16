"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";

/** (dashboard) 오류 경계: 예상하지 못한 렌더링 오류. 서버 데이터를 다시 불러온 뒤 경계를 초기화한다. */
export default function DashboardErrorBoundary({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return (
    <section role="alert" className="mx-auto max-w-7xl rounded-panel border border-danger bg-danger-soft p-5 text-danger-soft-fg">
      <h2 className="text-h2 font-bold">화면을 불러오지 못했습니다</h2>
      <p className="mt-1 mb-4 text-body">잠시 후 다시 시도하세요.</p>
      <button
        type="button"
        onClick={() =>
          startTransition(() => {
            router.refresh();
            reset();
          })
        }
        disabled={pending}
        className="inline-flex min-h-11 items-center justify-center rounded-control bg-primary px-4 text-body font-semibold text-primary-fg hover:bg-primary-hover disabled:opacity-55 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-3"
      >
        {pending ? "다시 불러오는 중…" : "다시 시도"}
      </button>
    </section>
  );
}
