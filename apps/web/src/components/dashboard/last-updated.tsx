"use client";

import { useEffect, useSyncExternalStore } from "react";
import { formatDateTime } from "./format";

const KEY = "dashboard:last-updated";

function subscribe(onChange: () => void) {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

/** 마지막 갱신 시각. 성공 시 at을 저장하고, 오류 상태(at 없음)에서는 마지막 성공 시각을 보여 준다. */
export function LastUpdated({ at }: { at?: string }) {
  const stored = useSyncExternalStore(subscribe, () => sessionStorage.getItem(KEY), () => null);
  useEffect(() => {
    if (at) sessionStorage.setItem(KEY, at);
  }, [at]);
  const value = at ?? stored;
  return (
    <p className="text-caption text-text-muted">
      마지막 갱신: {value ? <time dateTime={value}>{formatDateTime(value)}</time> : "기록 없음"}
    </p>
  );
}
