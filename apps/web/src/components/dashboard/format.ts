const DATE_TIME = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** ISO 시각 → "11. 17. 09:30" (한국 시간). 해석 불가면 "—". */
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : DATE_TIME.format(d);
}

/** 증가율(%) → "+12.3%". null이면 "—". */
export function formatGrowth(pct: number | null): string {
  if (pct === null || !Number.isFinite(pct)) return "—";
  return `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
}
