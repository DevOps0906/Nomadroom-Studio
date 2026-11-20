// 리포트 JSON에서 화면에 필요한 값만 고른다(비신뢰 입력: 문자열·숫자만, 개수·길이 제한).

export type ReportWarning = { code: string; line?: number; overflow_sec?: number; message?: string };
export type ReportWarnings = { lang: "ko" | "ja" | null; warnings: ReportWarning[] };

const MAX = 100;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
const first = (o: Record<string, unknown>, keys: string[]) => {
  for (const k of keys) {
    const n = num(o[k]);
    if (n !== undefined) return n;
  }
  return undefined;
};

export function pickReportWarnings(report: unknown): ReportWarnings {
  const r = typeof report === "object" && report !== null ? (report as Record<string, unknown>) : {};
  const lang = r.lang === "ja" || r.lang === "ko" ? r.lang : null;
  const raw = Array.isArray(r.warnings) ? r.warnings : [];
  const warnings: ReportWarning[] = [];
  for (const w of raw.slice(0, MAX)) {
    if (typeof w === "string") {
      warnings.push({ code: w.slice(0, 60) });
      continue;
    }
    if (typeof w !== "object" || w === null) continue;
    const o = w as Record<string, unknown>;
    if (typeof o.code !== "string") continue;
    warnings.push({
      code: o.code.slice(0, 60),
      line: first(o, ["line", "index", "cue", "n"]),
      overflow_sec: first(o, ["overflow_sec", "over_sec", "excess_sec"]),
      message: typeof o.message === "string" ? o.message.slice(0, 200) : undefined,
    });
  }
  return { lang, warnings };
}
