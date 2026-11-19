import type { ProductionStatus, SpecIssue } from "@/server/api/production";

// PROD-02 편집안 입력 모델(순수). 서버 검증이 정본이고, 여기는 입력 변환·표시 계산만 한다.
// 근거: docs/05_DATA_MODEL.md#편집안-spec-필드, tasks/task-026.md.

export const MIN_SHOW_SEC = 1.4;
export type ItemKind = "white" | "paren" | "emph";
export const KIND_LABEL: Record<ItemKind, string> = { white: "흰색", paren: "괄호", emph: "강조" };
const KINDS = Object.keys(KIND_LABEL) as ItemKind[];

export type ShotDraft = { start: string; end: string; scale: string; y: string };
export type ItemDraft = { start: string; end: string; kind: ItemKind; text: string; y: string };
export type OverlayKind = "comment" | "source";
/** 댓글·출처 오버레이 입력. 위치 x·y는 608×1080 화면의 카드 중심. 이미지·URL 첨부 없음. */
export type OverlayDraft = { kind: OverlayKind; text: string; start: string; end: string; x: string; y: string; ref?: string };
export type Tts = { voice: string; rate?: string };

// 서버 spec.py의 Tts 패턴과 같다(edge-tts가 SSML에 그대로 넣어 형식 고정).
export const TTS_VOICE_RE = /^[a-z]{2,3}-[A-Z]{2,4}-[A-Za-z0-9]+Neural$/;
export const TTS_RATE_RE = /^[+-]\d{1,3}%$/;
export const TTS_VOICES: { id: string; label: string }[] = [
  { id: "ko-KR-SunHiNeural", label: "한국어 여성 (SunHi)" },
  { id: "ko-KR-InJoonNeural", label: "한국어 남성 (InJoon)" },
  { id: "ja-JP-NanamiNeural", label: "일본어 여성 (Nanami)" },
  { id: "ja-JP-KeitaNeural", label: "일본어 남성 (Keita)" },
];
/** 편집안 lang과 같은 접두사 음성만(서버 hook.tts.voice_lang 검사와 같다). */
export const voicesFor = (lang: string) => TTS_VOICES.filter((v) => v.id.split("-", 1)[0] === lang);
export const defaultTts = (lang: string): Tts => ({ voice: (voicesFor(lang)[0] ?? TTS_VOICES[0]!).id, rate: "+50%" });

/** 입력 중인 편집안. 숫자는 입력 문자열 그대로 두고, overlays 등 이 화면이 다루지 않는 필드는 rest로 통과시킨다. */
export type Draft = {
  lang: string;
  header: [string, string];
  hookText: string;
  audioAssetId: string | null;
  tts: Tts | null;
  duration: string;
  shots: ShotDraft[];
  items: ItemDraft[];
  overlays: OverlayDraft[];
  rest: Record<string, unknown>;
};

const str = (v: unknown) => (typeof v === "string" ? v : "");
const numStr = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? String(v) : "");
const obj = (v: unknown): Record<string, unknown> => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

export function emptyDraft(): Draft {
  return { lang: "ko", header: ["", ""], hookText: "", audioAssetId: null, tts: null, duration: "", shots: [], items: [], overlays: [], rest: {} };
}

export function toDraft(spec: Record<string, unknown>): Draft {
  const { lang, header, hook, duration, shots, items, overlays, ...rest } = spec;
  const lines = arr(obj(header).lines);
  const h = obj(hook);
  const tts = obj(h.tts);
  return {
    lang: str(lang) || "ko",
    header: [str(lines[0]), str(lines[1])],
    hookText: str(h.text),
    audioAssetId: typeof h.audio_asset_id === "string" ? h.audio_asset_id : null,
    tts: typeof tts.voice === "string" ? { voice: tts.voice, ...(typeof tts.rate === "string" ? { rate: tts.rate } : {}) } : null,
    duration: numStr(duration),
    shots: arr(shots).map((s) => {
      const o = obj(s);
      return { start: numStr(o.start), end: numStr(o.end), scale: numStr(o.scale), y: numStr(o.y) };
    }),
    items: arr(items).map((i) => {
      const o = obj(i);
      return { start: numStr(o.start), end: numStr(o.end), kind: KINDS.includes(o.kind as ItemKind) ? (o.kind as ItemKind) : "white", text: str(o.text), y: numStr(o.y) };
    }),
    overlays: arr(overlays).map((x) => {
      const o = obj(x);
      const row: OverlayDraft = { kind: o.kind === "source" ? "source" : "comment", text: str(o.text), start: numStr(o.start), end: numStr(o.end), x: numStr(o.x), y: numStr(o.y) };
      if (typeof o.ref === "string") row.ref = o.ref;
      return row;
    }),
    rest,
  };
}

const parse = (s: string): number | null => {
  const t = s.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
};

export type BuildResult = { ok: true; spec: Record<string, unknown> } | { ok: false; path: string; message: string };

/** 입력을 서버로 보낼 spec으로 바꾼다. 숫자가 아닌 칸이 있으면 보내지 않고 위치를 돌려준다(NaN은 JSON으로 못 간다). */
export function buildSpec(d: Draft): BuildResult {
  const bad = (path: string): BuildResult => ({ ok: false, path, message: "숫자를 입력하세요." });
  const duration = parse(d.duration);
  if (duration === null) return bad("duration");
  const shots = [];
  for (const [i, s] of d.shots.entries()) {
    const start = parse(s.start);
    const end = parse(s.end);
    const scale = parse(s.scale);
    const y = parse(s.y);
    if (start === null) return bad(`shots.${i}.start`);
    if (end === null) return bad(`shots.${i}.end`);
    if (scale === null) return bad(`shots.${i}.scale`);
    if (y === null) return bad(`shots.${i}.y`);
    shots.push({ start, end, scale, y });
  }
  const items = [];
  for (const [i, it] of d.items.entries()) {
    const start = parse(it.start);
    const end = parse(it.end);
    if (start === null) return bad(`items.${i}.start`);
    if (end === null) return bad(`items.${i}.end`);
    const row: Record<string, unknown> = { start, end, kind: it.kind, text: it.text };
    if (it.y.trim()) {
      const y = parse(it.y);
      if (y === null) return bad(`items.${i}.y`);
      row.y = y;
    }
    items.push(row);
  }
  const overlays = [];
  for (const [i, o] of d.overlays.entries()) {
    const start = parse(o.start);
    const end = parse(o.end);
    const x = parse(o.x);
    const y = parse(o.y);
    if (start === null) return bad(`overlays.${i}.start`);
    if (end === null) return bad(`overlays.${i}.end`);
    if (x === null) return bad(`overlays.${i}.x`);
    if (y === null) return bad(`overlays.${i}.y`);
    const row: Record<string, unknown> = { kind: o.kind, text: o.text, start, end, x, y };
    if (o.ref !== undefined) row.ref = o.ref;
    overlays.push(row);
  }
  if (d.tts) {
    if (!TTS_VOICE_RE.test(d.tts.voice)) return { ok: false, path: "hook.tts.voice", message: "허용된 음성을 고르세요." };
    if (d.tts.rate !== undefined && !TTS_RATE_RE.test(d.tts.rate)) return { ok: false, path: "hook.tts.rate", message: "속도는 +50%, -10% 형식(부호·숫자 1~3자리·%)으로 입력하세요." };
  }
  const hook: Record<string, unknown> = { text: d.hookText };
  if (d.audioAssetId) hook.audio_asset_id = d.audioAssetId;
  if (d.tts) hook.tts = d.tts;
  return { ok: true, spec: { ...d.rest, lang: d.lang, header: { lines: [...d.header] }, hook, duration, shots, items, ...(overlays.length > 0 ? { overlays } : {}) } };
}

// ---- 검증 항목 표시 ----

const LABELS: Record<string, string> = {
  "shots.gap": "구도 공백",
  "shots.overlap": "구도 겹침",
  "shots.blank": "빈 화면",
  "shots.scale": "배율 범위",
  "shots.y": "세로 오프셋 범위",
  "shots.range": "구도가 길이 초과",
  "items.first_not_zero": "첫 자막이 0초가 아님",
  "items.too_short": "표시 1.4초 미만",
  "items.text.empty": "빈 자막 문구",
  "hook.text.empty": "빈 훅 문구",
  "header.lines.invalid": "제목 2줄 위반",
  "hook.audio_xor": "훅 음성·TTS 중 하나만",
  "path.forbidden": "경로·URL 불가",
  "duration.range": "길이 범위",
  "overlays.range": "오버레이 구간 범위",
  "overlays.overlap": "오버레이 구간 겹침",
  "overlays.header_overlap": "오버레이가 제목과 겹침",
  "overlays.pos": "오버레이 위치 범위",
  "overlays.text.empty": "빈 오버레이 문구",
  "overlays.text.newline": "오버레이 줄바꿈 불가",
  "overlays.text.long": "오버레이 문구 길이",
  "overlays.caption_overlap": "자막과 겹침",
};
export const issueLabel = (i: SpecIssue) => LABELS[i.code] ?? i.code;

/** 경로 p(예: "items.2")의 항목 자체 또는 하위 필드(items.2.text)에 걸린 항목. */
export function issuesAt(list: SpecIssue[], p: string): SpecIssue[] {
  return list.filter((i) => i.path === p || i.path.startsWith(`${p}.`));
}

/** 필드 하나(정확히 같은 경로) 항목만. */
export const issuesOf = (list: SpecIssue[], p: string) => list.filter((i) => i.path === p);

/** 행(shots.N·items.N)에 걸리지 않은 항목: 훅·길이·헤더·목록 전체. */
export function globalIssues(list: SpecIssue[]): SpecIssue[] {
  return list.filter((i) => !/^(shots|items|overlays)\.\d+/.test(i.path));
}

// ---- 타임라인 ----

export type Seg = { left: number; width: number; bad: boolean; short: boolean };
const pct = (v: number) => Math.min(100, Math.max(0, v));

/** 구도 막대: 앞 구간 끝과 이어지지 않으면(공백·겹침) bad. 화면 표시용이며 승인 판단은 서버 검증. */
export function shotSegments(shots: ShotDraft[], duration: number): Seg[] {
  if (!(duration > 0)) return [];
  let prev = 0;
  return shots.map((s) => {
    const start = parse(s.start);
    const end = parse(s.end);
    if (start === null || end === null) return { left: 0, width: 0, bad: true, short: false };
    const bad = Math.abs(start - prev) > 0.001 || end <= start;
    prev = end;
    return { left: pct((start / duration) * 100), width: pct(((end - start) / duration) * 100), bad, short: false };
  });
}

export function itemSegments(items: ItemDraft[], duration: number): Seg[] {
  if (!(duration > 0)) return [];
  let prev = 0;
  return items.map((s) => {
    const start = parse(s.start);
    const end = parse(s.end);
    if (start === null || end === null) return { left: 0, width: 0, bad: true, short: false };
    const bad = start < prev - 0.001 || end <= start;
    prev = end;
    return { left: pct((start / duration) * 100), width: pct(((end - start) / duration) * 100), bad, short: end > start && end - start < MIN_SHOW_SEC };
  });
}

export const isShort = (it: Pick<ItemDraft, "start" | "end">) => {
  const a = parse(it.start);
  const b = parse(it.end);
  return a !== null && b !== null && b > a && b - a < MIN_SHOW_SEC;
};

/** duration 입력값(초). 숫자가 아니면 0. */
export const durationOf = (d: Draft) => parse(d.duration) ?? 0;

// ---- 승인 가능 여부 ----

export type Blocker = { id: string; text: string };

/** 승인을 막는 사유(없으면 빈 배열). 서버가 최종 재검증하므로 여기는 안내용. */
export function approveBlockers(a: { status: ProductionStatus; hasRevision: boolean; dirty: boolean; approved: boolean; errorCount: number; overlayErrorCount?: number; busy: boolean }): Blocker[] {
  const out: Blocker[] = [];
  if (!a.hasRevision) out.push({ id: "none", text: "편집안 초안이 아직 없습니다." });
  if (a.status !== "review") out.push({ id: "status", text: "편집안 검토 상태에서만 승인할 수 있습니다." });
  if (a.approved) out.push({ id: "approved", text: "이미 승인된 편집안입니다. 고치면 새 리비전으로 저장됩니다." });
  if (a.dirty) out.push({ id: "dirty", text: "저장하지 않은 변경이 있습니다. 먼저 저장하세요." });
  const ov = a.overlayErrorCount ?? 0;
  if (a.errorCount - ov > 0) out.push({ id: "errors", text: `검증 오류 ${a.errorCount - ov}건을 고쳐야 합니다.` });
  if (ov > 0) out.push({ id: "overlays", text: `댓글·출처 탭 오류 ${ov}건을 고쳐야 합니다.` });
  if (a.busy) out.push({ id: "busy", text: "처리 중입니다." });
  return out;
}

/** 저장(편집)을 허용하는 상태: review·inspect·failed(audio·render). */
export function isEditableStatus(status: ProductionStatus, failedStage: string | null): boolean {
  return status === "review" || status === "inspect" || (status === "failed" && (failedStage === "audio" || failedStage === "render"));
}
