import type { JobFormat, SpecIssue } from "@/server/api/production";
import type { SavedRevision } from "../edit/api";
import type { JaRevision } from "./api";

// 언어 탭(ko·ja) 화면 판단(순수). 서버가 정본이고 여기는 탭 상태·잠금 표시·안내 문구만 정한다.
// 근거: docs/03_SCREENS_UX.md 일본어판 공통 규칙(F-07), tasks/task-049.md J3(번역 경로)·J7(편집 가드)·J8(원본 변경).

export type Lang = "ko" | "ja";

/** `?lang=` 값 → 탭. 알 수 없는 값은 ko. */
export function parseLang(v: string | string[] | undefined): Lang {
  return (Array.isArray(v) ? v[0] : v) === "ja" ? "ja" : "ko";
}

/** 탭 링크 주소. ko는 기본이라 쿼리를 붙이지 않는다. */
export function langHref(base: string, lang: Lang): string {
  return lang === "ja" ? `${base}?lang=ja` : base;
}

export type Gate = { enabled: boolean; reason: string | null };

/** "일본어판 만들기" 활성 조건: 현재 ko 리비전이 승인돼 있어야 한다(J2). */
export function makeGate(ko: { approved_at: string | null } | null): Gate {
  if (!ko) return { enabled: false, reason: "ko 편집안이 아직 없습니다. ko 탭에서 편집안을 만들고 승인하세요." };
  if (!ko.approved_at) return { enabled: false, reason: "ko 편집안이 승인되기 전에는 일본어판을 만들 수 없습니다. ko 탭에서 승인하세요." };
  return { enabled: true, reason: null };
}

export const SOURCE_CHANGED = "ja.source_changed";
export const hasSourceChanged = (errors: Pick<SpecIssue, "code">[]) => errors.some((e) => e.code === SOURCE_CHANGED);

export const SOURCE_CHANGED_NOTE =
  "원본(ko) 편집안이 바뀌어 이 일본어판은 오래되었습니다. 승인할 수 없습니다. \"다시 만들기\"로 최신 ko 승인본에서 새 번역 초안을 만드세요(지금 편집안은 보관됩니다).";

export const TRANSLATE_DISCLOSURE = "ko 문구(대본·자막·제목·CTA)가 외부 AI(Claude)로 전송됩니다. 영상·이미지·음성은 보내지 않습니다.";
export const TRANSLATE_DIRTY_CONFIRM = "저장하지 않은 변경이 있습니다. 새 번역 초안을 만들면 화면의 변경은 사라집니다(저장된 편집안은 보관됩니다). 계속할까요?";

// ---- 번역 경로(J3). 서버가 같은 경로만 바꿀 수 있게 막는다(ja.locked_field) ----

type Seg = string | number;
export type TextField = { key: string; path: Seg[]; label: string; value: string };

const asObj = (v: unknown): Record<string, unknown> | null => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : null);

/** 배열 원소가 문자열이거나 {text}인 경우를 모두 받는다. */
function collectList(spec: Record<string, unknown>, name: string, label: string, field: string | null, out: TextField[]) {
  const list = spec[name];
  if (!Array.isArray(list)) return;
  list.forEach((el, i) => {
    if (field === null) {
      if (typeof el === "string") out.push(mk([name, i], `${label} ${i + 1}`, el));
      return;
    }
    const o = asObj(el);
    if (o && typeof o[field] === "string") out.push(mk([name, i, field], `${label} ${i + 1}`, o[field] as string));
  });
}

const mk = (path: Seg[], label: string, value: string): TextField => ({ key: path.join("."), path, label, value });

/** 형식별 번역 대상 문구(J3 경로). 그 밖의 값은 편집 불가. */
export function extractTexts(format: JobFormat, spec: Record<string, unknown>): TextField[] {
  const out: TextField[] = [];
  const header = asObj(spec.header);
  if (header && Array.isArray(header.lines) && format !== "shopping") {
    header.lines.forEach((l, i) => typeof l === "string" && out.push(mk(["header", "lines", i], `제목 ${i + 1}줄`, l)));
  }
  if (format === "category") {
    const hook = asObj(spec.hook);
    if (hook && typeof hook.text === "string") out.push(mk(["hook", "text"], "훅 문구", hook.text));
    collectList(spec, "items", "자막", "text", out);
    collectList(spec, "overlays", "오버레이", "text", out);
  } else if (format === "variety") {
    collectList(spec, "subtitles", "자막", "text", out);
    collectList(spec, "reactions", "반응", "text", out);
  } else {
    const list = spec.script;
    if (Array.isArray(list)) {
      list.forEach((el, i) => {
        if (typeof el === "string") out.push(mk(["script", i], `대본 ${i + 1}문장`, el));
        else {
          const o = asObj(el);
          if (o && typeof o.text === "string") out.push(mk(["script", i, "text"], `대본 ${i + 1}문장`, o.text));
        }
      });
    }
    const cta = asObj(spec.cta);
    if (cta && typeof cta.text === "string") out.push(mk(["cta", "text"], "CTA 문구", cta.text));
  }
  return out;
}

/** 화면 입력(키→문구)을 spec 사본에 반영한다. 번역 경로 밖 값은 건드리지 않는다. */
export function applyTexts(format: JobFormat, spec: Record<string, unknown>, edits: Record<string, string>): Record<string, unknown> {
  const next = JSON.parse(JSON.stringify(spec)) as Record<string, unknown>;
  for (const f of extractTexts(format, next)) {
    const v = edits[f.key];
    if (v === undefined || v === f.value) continue;
    let cur: unknown = next;
    f.path.slice(0, -1).forEach((s) => (cur = (cur as Record<Seg, unknown>)[s]));
    (cur as Record<Seg, unknown>)[f.path[f.path.length - 1]] = v;
  }
  return next;
}

/** 초기 입력값(키→문구). */
export const textsOf = (format: JobFormat, spec: Record<string, unknown>): Record<string, string> =>
  Object.fromEntries(extractTexts(format, spec).map((f) => [f.key, f.value]));

export function isDirty(format: JobFormat, spec: Record<string, unknown>, edits: Record<string, string>): boolean {
  return extractTexts(format, spec).some((f) => edits[f.key] !== undefined && edits[f.key] !== f.value);
}

/** 잠금 표시(ko 승인본 값 그대로, 수정 불가) 설명. */
export const LOCKED_NOTE: Record<JobFormat, string> = {
  category: "구도(shots)·자막 시간·종류·위치·오버레이 위치·원본 구간은 ko 승인본과 같아야 하며 바꿀 수 없습니다.",
  variety: "컷·자막 시간·스타일·반응 위치·원본 구간은 ko 승인본과 같아야 하며 바꿀 수 없습니다.",
  shopping: "컷·구도·마스크·모션·문장 번호·표기(PR)는 ko 승인본과 같아야 하며 바꿀 수 없습니다.",
};
export const VOICE_NOTE = "음성: ko 녹음은 쓰지 않고 일본어 TTS 기본 목소리로 만듭니다(번역판 음성 설정은 서버 기본값).";

/** 승인 막는 사유. 서버 재검증이 정본이고 여기는 버튼 비활성만 정한다. */
export function approveBlockers(s: { dirty: boolean; saving: boolean; approved: boolean; errors: Pick<SpecIssue, "code">[] }): string[] {
  const out: string[] = [];
  if (s.approved) out.push("이미 승인된 편집안입니다. 수정하면 새 리비전이 만들어집니다.");
  if (s.dirty) out.push("저장하지 않은 변경이 있습니다. 먼저 저장하세요.");
  if (hasSourceChanged(s.errors)) out.push("원본(ko)이 바뀌었습니다. \"다시 만들기\"가 필요합니다.");
  else if (s.errors.length > 0) out.push(`검증 오류 ${s.errors.length}건을 고쳐야 합니다.`);
  return out;
}

// ---- 리포트 warnings(task-051 D7) ----

export type ReportWarning = { code: string; line?: number; overflow_sec?: number; message?: string };

/** dub_overflow(대사 번호·초과 초)·dub_none(대사 없음) 문구. 그 밖은 코드를 그대로 보인다. */
export function warningText(w: ReportWarning): string {
  if (w.code === "dub_overflow") {
    const where = w.line !== undefined ? `대사 ${w.line}번(강조 제외 순번)` : "대사";
    const sec = w.overflow_sec !== undefined ? ` ${w.overflow_sec.toFixed(2)}초` : "";
    return `${where}: 일본어 음성이 자막 구간을${sec} 넘어 잘렸습니다. 검수에서 확인하세요.`;
  }
  if (w.code === "dub_none") return "대사 자막이 없어 더빙 없이 원본 소리 그대로 만들었습니다.";
  return w.message ? `${w.code}: ${w.message}` : w.code;
}

/** 리포트의 언어가 보는 탭과 다르면 숨긴다(언어를 모르면 보인다). */
export const warningsForLang = (report: { lang: Lang | null; warnings: ReportWarning[] }, tab: Lang) => (report.lang && report.lang !== tab ? [] : report.warnings);

/**
 * 대사 순번(워커 `line` 기준): style=line 자막만 start 오름차순(같으면 배열 순)으로 1부터. 강조(punch)는 null.
 * variety 편집 화면 번호와 dub_overflow 경고의 "대사 N번"을 같은 기준으로 맞춘다.
 */
export function dubOrdinals(subs: { style?: string; start: string | number }[]): (number | null)[] {
  const order = subs
    .map((s, i) => ({ i, start: Number(s.start), line: s.style === "line" }))
    .filter((s) => s.line)
    .sort((a, b) => (a.start === b.start || Number.isNaN(a.start) || Number.isNaN(b.start) ? a.i - b.i : a.start - b.start));
  const out: (number | null)[] = subs.map(() => null);
  order.forEach((s, n) => (out[s.i] = n + 1));
  return out;
}

/** task-059: A-12(ja) 저장 성공 응답으로 패널 리비전을 갱신한다(새로고침·재마운트 없이 다음 저장의 base가 된다). */
export function applySaved(rev: JaRevision, spec: Record<string, unknown>, saved: SavedRevision): JaRevision {
  return { ...rev, id: saved.id, rev_no: saved.rev_no, spec, origin: "user", validation: saved.validation, approved_at: saved.approved_at, updated_at: saved.updated_at };
}
