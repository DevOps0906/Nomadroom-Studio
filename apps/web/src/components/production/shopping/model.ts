import type { Affiliate, AssetRights, RightsBasis, ShoppingBrief, ShoppingVertical, SpecIssue } from "@/server/api/production";
import { issueLabel } from "../edit/model";

// 쇼핑(PROD-01S·02S) 입력 모델(순수). 서버 검증이 정본이고, 여기는 입력 변환·1차 안내만 한다.
// 근거: docs/05_DATA_MODEL.md#쇼핑-spec-필드, apps/api/app/production/validation_shopping.py(1차 안내 규칙), tasks/task-044·045.md.

export const VERTICAL_LABEL: Record<ShoppingVertical, string> = { product: "상품", travel: "여행" };
export const PRODUCT_TYPE_LABEL = { stay: "숙소", tour: "투어", package: "패키지" } as const;
export const BASIS_LABEL: Record<RightsBasis, string> = { own: "직접 제작", licensed: "라이선스", permission: "허락", quote: "인용", platform_audio: "플랫폼 음원" };
/** 영상 원본·BGM·녹음은 다섯 가지, 사진은 직접 촬영·라이선스 구매만(제휴처·숙소 제공 사진 불가, task-045 팀장 결정). */
export const IMAGE_BASES: RightsBasis[] = ["own", "licensed"];
export const ALL_BASES = Object.keys(BASIS_LABEL) as RightsBasis[];

export const MIN_SCENES = 3;
export const MAX_SCENES = 5;
export const MIN_SOURCES = 3;
export const MAX_SOURCES = 10;
export const SENTENCES = 4;
export const SCRIPT_MIN = 110;
export const SCRIPT_MAX = 140;
/** 표기 문구 고정값(서버 DISCLOSURE_TEXT와 같다): ko "제휴 링크 포함", ja "PR". */
export const DISCLOSURE_TEXT = { ko: "제휴 링크 포함", ja: "PR" } as const;
export const DISCLOSURE_KO = DISCLOSURE_TEXT.ko;
export const disclosureFor = (lang: unknown): string => (lang === "ja" ? DISCLOSURE_TEXT.ja : DISCLOSURE_TEXT.ko);
export const CONFIRM_MARK = "[확인 필요]";
/** 서버 금지어 기본값(가정, validation_shopping.DEFAULT_BANNED_PHRASES와 같게). 서버 경고가 정본이다. */
export const BANNED_PHRASES = ["강력 추천", "인생템", "지금 바로"];

// ---- 금지 품목(1차 안내) ----

/** 서버 shopping.BANNED_KEYWORDS와 같은 목록(가정). 안내용이며 서버가 다시 검사한다. */
export const BANNED_KEYWORDS = [
  "의약품", "일반의약품", "전문의약품", "건강기능식품", "건기식", "건강보조식품", "영양제", "영양보충제", "식이보충제", "처방약", "다이어트약",
  "医薬品", "医薬部外品", "健康食品", "機能性表示食品", "特定保健用食品", "サプリメント", "サプリ", "supplement", "pharmaceutical", "medicine",
];

/** NFKC → 소문자 → 문자·숫자만(서버 normalize와 같은 순서). */
export function normalizeText(text: string): string {
  return [...text.normalize("NFKC").toLowerCase()].filter((ch) => /[\p{L}\p{N}]/u.test(ch)).join("");
}
const BANNED_NORM = BANNED_KEYWORDS.map(normalizeText);

/** 첫 번째로 일치한 금지 키워드(없으면 null). */
export function findBanned(texts: (string | undefined)[]): string | null {
  for (const t of texts) {
    if (!t) continue;
    const n = normalizeText(t);
    const i = BANNED_NORM.findIndex((k) => k && n.includes(k));
    if (i >= 0) return BANNED_KEYWORDS[i]!;
  }
  return null;
}

// ---- 브리프 ----

export type BriefDraft = {
  product_name: string;
  pain: string;
  destination: string;
  product_type: "" | "stay" | "tour" | "package";
  appeal: string;
  scenes: string[];
  avoid: string;
  facts: string[];
  gender: "" | "female" | "male" | "all";
  age: string;
};

export const emptyBrief = (): BriefDraft => ({
  product_name: "",
  pain: "",
  destination: "",
  product_type: "",
  appeal: "",
  scenes: ["", "", ""],
  avoid: "",
  facts: [""],
  gender: "",
  age: "",
});

export function toBriefDraft(b: ShoppingBrief | null | undefined): BriefDraft {
  const d = emptyBrief();
  if (!b) return d;
  return {
    product_name: b.product_name ?? "",
    pain: b.pain ?? "",
    destination: b.destination ?? "",
    product_type: b.product_type ?? "",
    appeal: b.appeal ?? "",
    scenes: b.scenes && b.scenes.length > 0 ? [...b.scenes] : d.scenes,
    avoid: b.avoid ?? "",
    facts: b.facts && b.facts.length > 0 ? [...b.facts] : d.facts,
    gender: b.target?.gender ?? "",
    age: b.target?.age ?? "",
  };
}

export type BriefErrors = Partial<Record<"product_name" | "pain" | "destination" | "product_type" | "appeal" | "scenes", string>>;

/** 필수 항목(상품: 제품명·불편·장면 3~5 / 여행: 목적지·상품 종류·소구점·장면 3~5). 서버는 초안 저장을 허용하고 화면이 막는다. */
export function validateBrief(vertical: ShoppingVertical, d: BriefDraft): BriefErrors {
  const e: BriefErrors = {};
  if (vertical === "product") {
    if (!d.product_name.trim()) e.product_name = "제품명을 입력하세요.";
    if (!d.pain.trim()) e.pain = "해결하는 불편 1개를 입력하세요.";
  } else {
    if (!d.destination.trim()) e.destination = "목적지를 입력하세요.";
    if (!d.product_type) e.product_type = "상품 종류를 선택하세요.";
    if (!d.appeal.trim()) e.appeal = "소구점 1개를 입력하세요.";
  }
  const scenes = d.scenes.filter((s) => s.trim()).length;
  if (scenes < MIN_SCENES || scenes > MAX_SCENES) e.scenes = `실제 장면을 ${MIN_SCENES}~${MAX_SCENES}개 입력하세요(현재 ${scenes}개).`;
  return e;
}

/** 서버로 보낼 brief. 분야에 맞는 항목만 담는다(분야 외 항목은 서버가 400). */
export function briefPayload(vertical: ShoppingVertical, d: BriefDraft): ShoppingBrief {
  const out: ShoppingBrief = {};
  const put = (k: "product_name" | "pain" | "destination" | "appeal" | "avoid", v: string) => {
    if (v.trim()) out[k] = v.trim();
  };
  if (vertical === "product") {
    put("product_name", d.product_name);
    put("pain", d.pain);
  } else {
    put("destination", d.destination);
    if (d.product_type) out.product_type = d.product_type;
    put("appeal", d.appeal);
  }
  put("avoid", d.avoid);
  out.scenes = d.scenes.map((s) => s.trim()).filter(Boolean);
  out.facts = d.facts.map((s) => s.trim()).filter(Boolean);
  const target: NonNullable<ShoppingBrief["target"]> = {};
  if (d.gender) target.gender = d.gender;
  if (d.age.trim()) target.age = d.age.trim();
  if (Object.keys(target).length > 0) out.target = target;
  return out;
}

// ---- 제휴 링크 ----

export type AffiliateDraft = { lang: "ko" | "ja"; partner: string; url: string };

export function isHttpsUrl(v: string): boolean {
  const t = v.trim();
  if (!t || t.length > 2048 || /\s/.test(t)) return false;
  try {
    const u = new URL(t);
    return u.protocol === "https:" && !!u.hostname && !u.username && !u.password;
  } catch {
    return false;
  }
}

/** 행별 오류(빈 행은 건너뜀). 키는 행 번호. */
export function validateAffiliates(rows: AffiliateDraft[]): Record<number, string> {
  const e: Record<number, string> = {};
  rows.forEach((r, i) => {
    if (!r.partner.trim() && !r.url.trim()) return;
    if (!r.partner.trim() || r.partner.trim().length > 50) e[i] = "제휴처를 1~50자로 입력하세요.";
    else if (!isHttpsUrl(r.url)) e[i] = "https 주소만 입력할 수 있습니다(공백·사용자 정보 불가).";
  });
  return e;
}

export const affiliatesPayload = (rows: AffiliateDraft[]): Affiliate[] =>
  rows.filter((r) => r.partner.trim() || r.url.trim()).map((r) => ({ lang: r.lang, partner: r.partner.trim(), url: r.url.trim() }));

// ---- 원본 행 ----

export type SourceRowDraft = {
  key: string;
  file: File | null;
  basis: "" | RightsBasis;
  source_url: string;
  author: string;
  has_person: boolean;
  portrait_consent: boolean;
  note: string;
  status: "idle" | "uploading" | "failed";
  error: string | null;
};

let seq = 0;
export const newRow = (): SourceRowDraft => ({ key: `row-${++seq}`, file: null, basis: "", source_url: "", author: "", has_person: false, portrait_consent: false, note: "", status: "idle", error: null });

const VIDEO_MIME: Record<string, string> = { mp4: "video/mp4", mov: "video/quicktime", webm: "video/webm", mkv: "video/x-matroska" };
const IMAGE_MIME: Record<string, string> = { jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp" };
export const SOURCE_ACCEPT = ".mp4,.mov,.webm,.mkv,.jpg,.jpeg,.png,.webp";
const ext = (name: string) => name.split(".").pop()?.toLowerCase() ?? "";

/** 파일 → 업로드 종류·mime. 영상은 source_upload, 사진은 image. 허용 밖이면 null. */
export function classifyFile(file: { name: string }): { kind: "source_upload" | "image"; mime: string } | null {
  const e = ext(file.name);
  if (VIDEO_MIME[e]) return { kind: "source_upload", mime: VIDEO_MIME[e] };
  if (IMAGE_MIME[e]) return { kind: "image", mime: IMAGE_MIME[e] };
  return null;
}

export const basesFor = (kind: "source_upload" | "image"): RightsBasis[] => (kind === "image" ? IMAGE_BASES : ALL_BASES);

export type RowErrors = Partial<Record<"file" | "basis" | "source_url" | "consent", string>>;

export function validateRow(r: SourceRowDraft): RowErrors {
  const e: RowErrors = {};
  const c = r.file ? classifyFile(r.file) : null;
  if (!r.file) e.file = "파일을 선택하세요.";
  else if (!c) e.file = "mp4·mov·webm·mkv 영상 또는 jpg·png·webp 사진만 올릴 수 있습니다.";
  else if (r.file.size === 0) e.file = "빈 파일입니다.";
  if (!r.basis) e.basis = "권리 근거를 선택하세요.";
  else if (c && !basesFor(c.kind).includes(r.basis)) e.basis = "사진은 직접 제작·라이선스만 쓸 수 있습니다.";
  if (r.source_url.trim() && !/^https?:\/\/\S+$/i.test(r.source_url.trim())) e.source_url = "http(s) 주소로 입력하세요.";
  if (r.has_person && !r.portrait_consent) e.consent = "사람이 나오면 초상권 동의가 필요합니다.";
  return e;
}

export function rightsOf(r: Pick<SourceRowDraft, "basis" | "source_url" | "author" | "has_person" | "portrait_consent" | "note">): AssetRights {
  const out: AssetRights = { basis: r.basis as RightsBasis, has_person: r.has_person, portrait_consent: r.has_person ? r.portrait_consent : false };
  if (r.source_url.trim()) out.source_url = r.source_url.trim();
  if (r.author.trim()) out.author = r.author.trim();
  if (r.note.trim()) out.note = r.note.trim();
  return out;
}

export type SourceWarning = { id: string; text: string };

/** 막지 않는 경고(원본 3개 미만) + 막는 안내(금지 품목·초상권). */
export function sourceWarnings(a: { sources: number; banned: string | null; consentMissing: boolean; hasVideo: boolean }): SourceWarning[] {
  const out: SourceWarning[] = [];
  if (a.banned) out.push({ id: "banned", text: `금지 품목 키워드가 있습니다(${a.banned}). 의약품·건강기능식품은 제작할 수 없습니다.` });
  if (a.consentMissing) out.push({ id: "consent", text: "사람이 나오는데 초상권 동의가 체크되지 않은 원본이 있습니다." });
  if (a.sources < MIN_SOURCES) out.push({ id: "few", text: `원본이 ${MIN_SOURCES}개 미만입니다(현재 ${a.sources}개). 계속할 수는 있지만 장면이 부족할 수 있습니다.` });
  if (a.sources > 0 && !a.hasVideo) out.push({ id: "video", text: "영상 원본이 1개 이상 있어야 원본 준비를 시작할 수 있습니다(사진만으로는 준비되지 않을 수 있습니다)." });
  return out;
}

/** 원본 개수·영상 여부. 이번 화면에서 이미 올린 자산(uploaded, 새 작업이라 서버 목록에 아직 없는 것)도 센다. */
export function countSources(kept: { kind: string }[], rows: SourceRowDraft[], uploaded: string[]): { count: number; hasVideo: boolean } {
  const rowKinds = rows.filter((r) => r.file).map((r) => (r.file ? classifyFile(r.file)?.kind : undefined));
  const kinds = [...kept.map((a) => a.kind), ...rowKinds, ...uploaded];
  return { count: kinds.length, hasVideo: kinds.includes("source_upload") };
}

/** 원본 준비 시작 후에는 분야·원본 편집을 잠근다(draft·준비 실패만 편집). */
export const isSourceEditable = (status: string, failedStage: string | null) => status === "draft" || (status === "failed" && failedStage === "prepare");

// ---- 편집안 spec(PROD-02S) ----

export type MaskDraft = { x: string; y: string; w: string; h: string };
export type CutDraft = { source_asset_id: string; src_start: string; src_end: string; scale: string; x: string; y: string; sentence: string; masks: MaskDraft[]; motion: "pan" | "zoom" | "none" };
export type VoiceMode = "tts" | "narration";
export type ShoppingDraft = {
  script: string[];
  cuts: CutDraft[];
  mode: VoiceMode;
  tts: { voice: string; rate: string };
  narrationIds: (string | null)[];
  sourceAudio: "mute" | "duck";
  bgmId: string | null;
  cta: string;
  rest: Record<string, unknown>;
};

const str = (v: unknown) => (typeof v === "string" ? v : "");
const numStr = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? String(v) : "");
const obj = (v: unknown): Record<string, unknown> => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
export const DEFAULT_VOICE = "ko-KR-SunHiNeural";
export const DEFAULT_RATE = "+0%";

export function emptyShoppingDraft(): ShoppingDraft {
  return {
    script: ["", "", "", ""],
    cuts: [],
    mode: "tts",
    tts: { voice: DEFAULT_VOICE, rate: DEFAULT_RATE },
    narrationIds: [null, null, null, null],
    sourceAudio: "mute",
    bgmId: null,
    cta: "",
    rest: {},
  };
}

export function toShoppingDraft(spec: Record<string, unknown>): ShoppingDraft {
  const { script, cuts, voice, source_audio, bgm_asset_id, cta, disclosure: _disclosure, ...rest } = spec;
  const v = obj(voice);
  const tts = obj(v.tts);
  const ids = arr(v.narration_asset_ids);
  const d = emptyShoppingDraft();
  const lines = arr(script).map((s) => str(obj(s).text));
  return {
    script: Array.from({ length: Math.max(SENTENCES, lines.length) }, (_, i) => lines[i] ?? ""),
    cuts: arr(cuts).map((c) => {
      const o = obj(c);
      const motion = obj(o.motion).type;
      return {
        source_asset_id: str(o.source_asset_id),
        src_start: numStr(o.src_start),
        src_end: numStr(o.src_end),
        scale: numStr(o.scale),
        x: numStr(o.x),
        y: numStr(o.y),
        sentence: numStr(o.sentence),
        masks: arr(o.masks).map((m) => ({ x: numStr(obj(m).x), y: numStr(obj(m).y), w: numStr(obj(m).w), h: numStr(obj(m).h) })),
        motion: motion === "pan" || motion === "none" ? motion : "zoom",
      };
    }),
    mode: ids.length > 0 && !tts.voice ? "narration" : "tts",
    tts: { voice: str(tts.voice) || d.tts.voice, rate: str(tts.rate) || d.tts.rate },
    narrationIds: [0, 1, 2, 3].map((i) => (typeof ids[i] === "string" ? (ids[i] as string) : null)),
    sourceAudio: source_audio === "duck" ? "duck" : "mute",
    bgmId: typeof bgm_asset_id === "string" ? bgm_asset_id : null,
    cta: str(obj(cta).text),
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
export const TTS_VOICE_RE = /^[a-z]{2,3}-[A-Z]{2,4}-[A-Za-z0-9]+Neural$/;
export const TTS_RATE_RE = /^[+-]\d{1,3}%$/;

/** 입력 → 서버 spec. 숫자 아닌 칸은 보내지 않고 위치를 돌려준다. 표기 문구는 고정값, motion은 사진 컷에만 둔다. */
export function buildShoppingSpec(d: ShoppingDraft, imageIds: ReadonlySet<string>): BuildResult {
  const bad = (path: string, message = "숫자를 입력하세요."): BuildResult => ({ ok: false, path, message });
  const cuts: Record<string, unknown>[] = [];
  for (const [i, c] of d.cuts.entries()) {
    const src_start = parse(c.src_start);
    const src_end = parse(c.src_end);
    const scale = parse(c.scale);
    const x = parse(c.x);
    const y = parse(c.y);
    const sentence = parse(c.sentence);
    if (src_start === null) return bad(`cuts.${i}.src_start`);
    if (src_end === null) return bad(`cuts.${i}.src_end`);
    if (scale === null) return bad(`cuts.${i}.scale`);
    if (x === null) return bad(`cuts.${i}.x`);
    if (y === null) return bad(`cuts.${i}.y`);
    if (sentence === null || !Number.isInteger(sentence)) return bad(`cuts.${i}.sentence`, "문장 번호를 고르세요.");
    const masks = [];
    for (const [j, m] of c.masks.entries()) {
      const [mx, my, mw, mh] = [parse(m.x), parse(m.y), parse(m.w), parse(m.h)];
      if (mx === null || my === null || mw === null || mh === null) return bad(`cuts.${i}.masks.${j}`);
      masks.push({ x: mx, y: my, w: mw, h: mh });
    }
    const row: Record<string, unknown> = { source_asset_id: c.source_asset_id, src_start, src_end, scale, x, y, sentence, masks };
    if (imageIds.has(c.source_asset_id)) row.motion = { type: c.motion };
    cuts.push(row);
  }
  let voice: Record<string, unknown>;
  if (d.mode === "tts") {
    if (!TTS_VOICE_RE.test(d.tts.voice)) return bad("voice.tts.voice", "허용된 음성을 고르세요.");
    if (!TTS_RATE_RE.test(d.tts.rate)) return bad("voice.tts.rate", "속도는 +10%, -10% 형식으로 입력하세요.");
    voice = { tts: { voice: d.tts.voice, rate: d.tts.rate } };
  } else {
    voice = { narration_asset_ids: d.narrationIds.filter((x): x is string => x !== null) };
  }
  const spec: Record<string, unknown> = {
    ...d.rest,
    script: d.script.map((text) => ({ text })),
    cuts,
    voice,
    source_audio: d.sourceAudio,
    cta: { text: d.cta },
    disclosure: { text: disclosureFor(d.rest.lang) },
  };
  if (d.bgmId) spec.bgm_asset_id = d.bgmId;
  return { ok: true, spec };
}

// ---- 대본 카운터·경고(1차 안내) ----

/** 공백 포함 글자 수(서버 len과 같게 코드 포인트 기준). */
export const charCount = (t: string) => [...t].length;
export const scriptTotal = (script: string[]) => script.reduce((n, t) => n + charCount(t), 0);

export function scriptHints(script: string[]): { total: number; outOfRange: boolean; banned: Record<number, string>; marked: number[] } {
  const total = scriptTotal(script);
  const flat = (v: string) => v.replace(/\s+/g, "").toLowerCase();
  const banned: Record<number, string> = {};
  script.forEach((t, i) => {
    const hit = BANNED_PHRASES.find((p) => flat(t).includes(flat(p)));
    if (hit) banned[i] = hit;
  });
  const marked = script.map((t, i) => (t.includes(CONFIRM_MARK) ? i : -1)).filter((i) => i >= 0);
  return { total, outOfRange: total < SCRIPT_MIN || total > SCRIPT_MAX, banned, marked };
}

// ---- 문장 타임라인 ----

export type SentenceSeg = { sentence: number; seconds: number; cuts: number; voiceSec: number | null; empty: boolean };

/** 문장별 컷 길이 합(초)과 문장별 녹음 길이(알 때). 렌더러가 음성에 맞춰 컷 길이를 조정하므로 안내용이다. */
export function sentenceSegments(d: ShoppingDraft, durationOf: (assetId: string) => number | null): SentenceSeg[] {
  return Array.from({ length: SENTENCES }, (_, i) => {
    const n = i + 1;
    const mine = d.cuts.filter((c) => parse(c.sentence) === n);
    const seconds = mine.reduce((sum, c) => {
      const a = parse(c.src_start);
      const b = parse(c.src_end);
      return a !== null && b !== null && b > a ? sum + (b - a) : sum;
    }, 0);
    const nid = d.mode === "narration" ? d.narrationIds[i] : null;
    return { sentence: n, seconds, cuts: mine.length, voiceSec: nid ? durationOf(nid) : null, empty: mine.length === 0 };
  });
}

// ---- 승인 사유·표시 ----

const LABELS: Record<string, string> = {
  "script.count": "대본 문장 수",
  "script.empty_text": "빈 문장",
  "script.multi_sentence": "한 줄에 여러 문장",
  "script.unverified": "[확인 필요] 표시 남음",
  "script.length": "글자 수 범위",
  "script.banned_phrase": "금지 문구",
  "script.product_in_first": "1번 문장에 제품명",
  "cuts.count": "컷 개수",
  "cuts.sentence_empty": "문장에 컷 없음",
  "cuts.sentence_invalid": "문장 번호",
  "cuts.source_invalid": "컷 원본 오류",
  "cuts.out_of_range": "컷 시각 범위",
  "cuts.scale": "배율 범위",
  "cuts.empty_area": "빈 화면",
  "cuts.motion_invalid": "사진 모션 오류",
  "masks.out_of_range": "마스크 범위",
  "sources.few": "원본 3개 미만",
  "voice.missing": "음성 미선택",
  "voice.both": "음성 중복",
  "voice.asset_invalid": "녹음 자산 오류",
  "voice.tts_lang": "음성 언어",
  "bgm.rights_missing": "BGM 권리 없음",
  "bgm.asset_invalid": "BGM 자산 오류",
  "cta.empty": "CTA 문구 비어 있음",
  "disclosure.empty": "표기 문구 비어 있음",
  "rights.missing": "권리 근거 없음",
  "rights.portrait_consent": "초상권 동의 없음",
  "gen.unreviewed": "AI 생성 컷 검수 전",
};
export const shoppingIssueLabel = (i: SpecIssue) => LABELS[i.code] ?? issueLabel(i);
