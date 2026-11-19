import type { SpecIssue } from "@/server/api/production";

// PROD-02V 예능형 편집안 입력 모델(순수). 서버 검증이 정본이고 여기는 입력 변환·표시 계산만 한다(상한은 화면 1차 안내).
// 근거: docs/05_DATA_MODEL.md#예능형-spec-필드, apps/api/app/production/validation_variety.py.

export const WARN_CUT_SEC = 0.5;
export const MIN_CUT_SEC = 0.2;
export const MAX_CUTS = 60;
export const MAX_TOTAL_SEC = 180;
export const MIN_SHOW_SEC = 1.4;
export const MAX_SUBTITLES = 200;
export const MAX_REACTIONS = 200;
export const MAX_HEADER_LINE_CHARS = 60;
export const MAX_TEXT_CHARS = 200;

export type SubStyle = "line" | "punch";
export const STYLE_LABEL: Record<SubStyle, string> = { line: "line(검정)", punch: "punch(빨강)" };
const STYLES = Object.keys(STYLE_LABEL) as SubStyle[];

export type CutDraft = { start: string; end: string; scale: string; x: string; y: string };
export type SubDraft = { start: string; end: string; style: SubStyle; text: string };
export type ReactionDraft = { start: string; end: string; text: string; x: string; y: string };
export type VarietyDraft = { header: [string, string]; cuts: CutDraft[]; subtitles: SubDraft[]; reactions: ReactionDraft[]; rest: Record<string, unknown> };

const str = (v: unknown) => (typeof v === "string" ? v : "");
const numStr = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? String(v) : "");
const obj = (v: unknown): Record<string, unknown> => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

export const emptyVarietyDraft = (): VarietyDraft => ({ header: ["", ""], cuts: [], subtitles: [], reactions: [], rest: {} });

export function toVarietyDraft(spec: Record<string, unknown>): VarietyDraft {
  const { header, cuts, subtitles, reactions, ...rest } = spec;
  const lines = arr(obj(header).lines);
  return {
    header: [str(lines[0]), str(lines[1])],
    cuts: arr(cuts).map((c) => {
      const o = obj(c);
      return { start: numStr(o.src_start), end: numStr(o.src_end), scale: numStr(o.scale), x: numStr(o.x), y: numStr(o.y) };
    }),
    subtitles: arr(subtitles).map((s) => {
      const o = obj(s);
      return { start: numStr(o.start), end: numStr(o.end), style: STYLES.includes(o.style as SubStyle) ? (o.style as SubStyle) : "line", text: str(o.text) };
    }),
    reactions: arr(reactions).map((r) => {
      const o = obj(r);
      return { start: numStr(o.start), end: numStr(o.end), text: str(o.text), x: numStr(o.x), y: numStr(o.y) };
    }),
    rest,
  };
}

export const parse = (s: string): number | null => {
  const t = s.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
};

export type VarietyBuild = { ok: true; spec: Record<string, unknown> } | { ok: false; path: string; message: string };

/** 입력을 서버로 보낼 spec으로 바꾼다. 숫자가 아닌 칸은 위치를 돌려준다. 제목 둘째 줄이 비면 1줄로 보낸다. */
export function buildVarietySpec(d: VarietyDraft): VarietyBuild {
  const bad = (path: string): VarietyBuild => ({ ok: false, path, message: "숫자를 입력하세요." });
  const cuts = [];
  for (const [i, c] of d.cuts.entries()) {
    const v = { src_start: parse(c.start), src_end: parse(c.end), scale: parse(c.scale), x: parse(c.x), y: parse(c.y) };
    for (const k of ["src_start", "src_end", "scale", "x", "y"] as const) if (v[k] === null) return bad(`cuts.${i}.${k}`);
    cuts.push(v);
  }
  const subtitles = [];
  for (const [i, s] of d.subtitles.entries()) {
    const start = parse(s.start);
    const end = parse(s.end);
    if (start === null) return bad(`subtitles.${i}.start`);
    if (end === null) return bad(`subtitles.${i}.end`);
    subtitles.push({ start, end, style: s.style, text: s.text });
  }
  const reactions = [];
  for (const [i, r] of d.reactions.entries()) {
    const v = { start: parse(r.start), end: parse(r.end), text: r.text, x: parse(r.x), y: parse(r.y) };
    for (const k of ["start", "end", "x", "y"] as const) if (v[k] === null) return bad(`reactions.${i}.${k}`);
    reactions.push(v);
  }
  const lines = d.header[1] === "" ? [d.header[0]] : [...d.header];
  return { ok: true, spec: { ...d.rest, header: { lines }, cuts, subtitles, reactions } };
}

export function moveRow<T>(list: T[], from: number, to: number): T[] {
  if (to < 0 || to >= list.length || from === to) return list;
  const out = [...list];
  const [item] = out.splice(from, 1);
  out.splice(to, 0, item);
  return out;
}

// ---- 표시 계산 ----

export function cutLength(c: Pick<CutDraft, "start" | "end">): number | null {
  const a = parse(c.start);
  const b = parse(c.end);
  return a !== null && b !== null && b > a ? b - a : null;
}

export const isShortCut = (c: Pick<CutDraft, "start" | "end">) => {
  const n = cutLength(c);
  return n !== null && n < WARN_CUT_SEC && n >= MIN_CUT_SEC;
};
export const isTooShortCut = (c: Pick<CutDraft, "start" | "end">) => {
  const n = cutLength(c);
  return n !== null && n < MIN_CUT_SEC;
};

/** 출력 총길이(초): 컷 길이 누적. 계산 못 하는 컷은 0. */
export const outputTotal = (cuts: CutDraft[]) => Math.round(cuts.reduce((t, c) => t + (cutLength(c) ?? 0), 0) * 1000) / 1000;

export const isShortSub = (s: Pick<SubDraft, "start" | "end">) => {
  const a = parse(s.start);
  const b = parse(s.end);
  return a !== null && b !== null && b > a && b - a < MIN_SHOW_SEC;
};

export type Seg = { left: number; width: number; bad: boolean; warn: boolean };
const pct = (v: number) => Math.min(100, Math.max(0, v));

/** 출력 타임라인 컷 막대: 누적 위치. 0.2초 미만·계산 불가는 bad, 0.5초 미만은 warn. */
export function cutSegments(cuts: CutDraft[], total: number): Seg[] {
  if (!(total > 0)) return [];
  let at = 0;
  return cuts.map((c) => {
    const n = cutLength(c);
    if (n === null) return { left: pct((at / total) * 100), width: 0, bad: true, warn: false };
    const seg = { left: pct((at / total) * 100), width: pct((n / total) * 100), bad: n < MIN_CUT_SEC, warn: n < WARN_CUT_SEC };
    at += n;
    return seg;
  });
}

/** 자막 막대(대사 또는 반응): 앞 막대와 시간이 겹치면 bad(대사)/warn(반응 — 겹침 허용). 범위 초과도 bad. */
export function timedSegments(rows: { start: string; end: string }[], total: number, overlapIsBad: boolean): Seg[] {
  if (!(total > 0)) return [];
  const spans = rows.map((r) => ({ a: parse(r.start), b: parse(r.end) }));
  return spans.map((s, i) => {
    if (s.a === null || s.b === null) return { left: 0, width: 0, bad: true, warn: false };
    const overlaps = spans.some((o, j) => j !== i && o.a !== null && o.b !== null && o.a < s.b! - 0.001 && s.a! < o.b - 0.001);
    const outside = s.b <= s.a || s.b > total + 0.001 || s.a < 0;
    return { left: pct((s.a / total) * 100), width: pct(((s.b - s.a) / total) * 100), bad: outside || (overlapIsBad && overlaps), warn: !overlapIsBad && overlaps };
  });
}

// ---- 검증 항목 표시 ----

const LABELS: Record<string, string> = {
  "header.invalid": "제목 줄 위반",
  "cuts.count": "컷 개수",
  "cuts.out_of_range": "컷이 원본 범위 밖",
  "cuts.too_short": "컷 0.2초 미만",
  "cuts.short": "컷 0.5초 미만",
  "cuts.empty_area": "빈 화면",
  "cuts.total_too_long": "총길이 초과",
  "subtitles.overlap": "자막 겹침",
  "subtitles.out_of_range": "자막 범위 초과",
  "subtitles.empty_text": "빈 자막 문구",
  "subtitles.style": "자막 스타일",
  "subtitles.short": "자막 1.4초 미만",
  "reactions.out_of_range": "반응 범위 초과",
  "reactions.empty_text": "빈 반응 문구",
  "reactions.overlap": "반응 시간 겹침",
  "path.forbidden": "경로·URL 불가",
};
export const varietyIssueLabel = (i: SpecIssue) => LABELS[i.code] ?? i.code;
