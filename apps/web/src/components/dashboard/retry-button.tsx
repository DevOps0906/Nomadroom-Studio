"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";

/** 서버 컴포넌트 데이터를 다시 불러온다. */
export function RetryButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return (
    <button
      type="button"
      onClick={() => startTransition(() => router.refresh())}
      disabled={pending}
      className="inline-flex min-h-11 items-center justify-center rounded-control bg-primary px-4 text-body font-semibold text-primary-fg hover:bg-primary-hover disabled:opacity-55 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-3"
    >
      {pending ? "다시 불러오는 중…" : "다시 시도"}
    </button>
  );
}
