// MON-D1 조건 폼 규칙(순수 함수). 범위 정본: docs/04_API.md#A-03, tasks/task-010.md#구현 결정. 최종 검증은 API.

export type Market = "KR" | "JP";
export type Format = "all" | "short" | "long";

export type Profile = {
  id: string;
  name: string;
  market: Market;
  format: Format;
  category: string | null;
  min_views: number;
  max_growth_pct: number;
  keywords: string[];
  cc_only: boolean;
  include_broadcast: boolean;
  selected: boolean;
  updated_at: string;
};

/** PUT /v1/profiles/{id} 본문(정확히 이 9필드). */
export type ConditionsPayload = Pick<
  Profile,
  "market" | "format" | "category" | "min_views" | "max_growth_pct" | "keywords" | "cc_only" | "include_broadcast" | "updated_at"
>;

/** 폼 입력 원본(문자열). 오류가 나도 이 값을 그대로 유지한다. */
export type ConditionsInput = {
  market: string;
  format: string;
  category: string;
  min_views: string;
  max_growth_pct: string;
  keywords: string;
  cc_only: boolean;
  include_broadcast: boolean;
};

export type FieldName = "market" | "format" | "category" | "min_views" | "max_growth_pct" | "keywords";
export type FieldErrors = Partial<Record<FieldName, string>>;

export const MAX_SELECTED = 3;
export const MAX_MIN_VIEWS = 2_000_000_000;
export const MAX_GROWTH_PCT = 1000;
export const MAX_KEYWORDS = 5;
export const MAX_KEYWORD_LEN = 30;
export const MAX_CATEGORY_LEN = 40;
export const CATEGORY_ALL = "전체";

export const MARKETS: { value: Market; label: string }[] = [
  { value: "KR", label: "한국 (KR)" },
  { value: "JP", label: "일본 (JP)" },
];
export const FORMATS: { value: Format; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "short", label: "쇼츠" },
  { value: "long", label: "롱폼" },
];
/** 시안(Nomadroom_Dashboard_Design.html) 카테고리 선택지. */
export const CATEGORIES = [CATEGORY_ALL, "예능", "영화·드라마", "스포츠", "일상", "쇼핑·리뷰", "음식", "재즈·피아노"];

export const FIELD_MESSAGES: Record<FieldName, string> = {
  market: "시장을 선택하세요.",
  format: "영상 형식을 선택하세요.",
  category: `카테고리는 ${MAX_CATEGORY_LEN}자 이하여야 합니다.`,
  min_views: `최소 조회수는 0~${MAX_MIN_VIEWS.toLocaleString("ko-KR")} 사이의 정수여야 합니다.`,
  max_growth_pct: `허용 증가율은 0~${MAX_GROWTH_PCT} 사이, 소수 둘째 자리까지 입력하세요.`,
  keywords: `키워드는 최대 ${MAX_KEYWORDS}개, 각 1~${MAX_KEYWORD_LEN}자로 입력하세요.`,
};

export const FIELD_LABELS: Record<FieldName, string> = {
  market: "시장",
  format: "영상 형식",
  category: "카테고리",
  min_views: "최소 조회수",
  max_growth_pct: "허용 증가율",
  keywords: "키워드",
};

export function marketLabel(value: string): string {
  return MARKETS.find((m) => m.value === value)?.label ?? value;
}

export function formatLabel(value: string): string {
  return FORMATS.find((f) => f.value === value)?.label ?? value;
}

export function toInput(p: Profile): ConditionsInput {
  return {
    market: p.market,
    format: p.format,
    category: p.category ?? CATEGORY_ALL,
    min_views: String(p.min_views),
    max_growth_pct: String(p.max_growth_pct),
    keywords: p.keywords.join(", "),
    cc_only: p.cc_only,
    include_broadcast: p.include_broadcast,
  };
}

const INT_RE = /^\d+$/;
const DECIMAL_RE = /^\d+(\.\d{1,2})?$/;
const CONTROL_RE = /[\x00-\x1f\x7f]/;

/** 쉼표로 나눠 공백 제거·대소문자 무시 중복 제거. 빈 항목은 건너뛴다. */
export function splitKeywords(raw: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of raw.split(",")) {
    const kw = part.trim();
    if (!kw) continue;
    const key = kw.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(kw);
  }
  return out;
}

/** 입력을 검사해 API 본문을 만든다. 오류가 있으면 payload는 null. */
export function validateConditions(
  input: ConditionsInput,
  updatedAt: string,
): { payload: ConditionsPayload | null; errors: FieldErrors } {
  const errors: FieldErrors = {};

  const market = MARKETS.find((m) => m.value === input.market)?.value;
  if (!market) errors.market = FIELD_MESSAGES.market;
  const format = FORMATS.find((f) => f.value === input.format)?.value;
  if (!format) errors.format = FIELD_MESSAGES.format;

  const cat = input.category.trim();
  if ([...cat].length > MAX_CATEGORY_LEN || CONTROL_RE.test(cat)) errors.category = FIELD_MESSAGES.category;
  const category = cat === "" || cat === CATEGORY_ALL ? null : cat;

  const mv = input.min_views.trim();
  const minViews = INT_RE.test(mv) ? Number(mv) : NaN;
  if (!(minViews >= 0 && minViews <= MAX_MIN_VIEWS)) errors.min_views = FIELD_MESSAGES.min_views;

  const gp = input.max_growth_pct.trim();
  const growth = DECIMAL_RE.test(gp) ? Number(gp) : NaN;
  if (!(growth >= 0 && growth <= MAX_GROWTH_PCT)) errors.max_growth_pct = FIELD_MESSAGES.max_growth_pct;

  const keywords = splitKeywords(input.keywords);
  if (keywords.length > MAX_KEYWORDS || keywords.some((k) => [...k].length > MAX_KEYWORD_LEN || CONTROL_RE.test(k))) {
    errors.keywords = FIELD_MESSAGES.keywords;
  }

  if (Object.keys(errors).length > 0 || !market || !format) return { payload: null, errors };
  return {
    payload: {
      market,
      format,
      category,
      min_views: minViews,
      max_growth_pct: growth,
      keywords,
      cc_only: input.cc_only,
      include_broadcast: input.include_broadcast,
      updated_at: updatedAt,
    },
    errors,
  };
}

/** 서버 액션 결과. 401은 액션에서 세션 정리 경로로 보낸다. */
export type SaveResult =
  | { ok: true }
  | { ok: false; kind: "field"; errors: FieldErrors }
  | { ok: false; kind: "conflict"; message: string }
  | { ok: false; kind: "error"; message: string };

export const CONFLICT_MESSAGE = "다른 곳에서 수정됨. 새로고침한 뒤 다시 저장하세요.";
export const SAVE_FAILED_MESSAGE = "저장하지 못했습니다. 다시 시도하세요.";

/** API 오류(상태·코드·필드)를 폼 결과로 바꾼다. 필드 경로 `keywords.2` → `keywords`. */
export function toSaveResult(err: { status: number; code: string; message: string; field?: string }): SaveResult {
  if (err.status === 409) return { ok: false, kind: "conflict", message: CONFLICT_MESSAGE };
  if (err.status === 400) {
    const name = err.field?.split(".")[0] as FieldName | undefined;
    if (name && name in FIELD_MESSAGES) return { ok: false, kind: "field", errors: { [name]: FIELD_MESSAGES[name] } };
    return { ok: false, kind: "error", message: err.message || SAVE_FAILED_MESSAGE };
  }
  if (err.status === 404) return { ok: false, kind: "error", message: "프로필을 찾을 수 없습니다. 새로고침하세요." };
  return { ok: false, kind: "error", message: err.message || SAVE_FAILED_MESSAGE };
}

/** 선택 토글. 이미 3개면 새로 추가하지 않는다(해제는 항상 가능). */
export function toggleSelection(selected: string[], id: string): string[] {
  if (selected.includes(id)) return selected.filter((x) => x !== id);
  if (selected.length >= MAX_SELECTED) return selected;
  return [...selected, id];
}

/** 선택 저장 결과 반영: 실패(400 포함)면 이전 선택으로 되돌리고 오류 문구를 돌려준다. */
export function settleSelection(
  res: SaveResult,
  prev: string[],
  next: string[],
): { selected: string[]; error: string | null } {
  if (res.ok) return { selected: next, error: null };
  return { selected: prev, error: res.kind === "field" ? "선택을 저장하지 못했습니다. 다시 시도하세요." : res.message };
}

export function canSelectMore(selected: string[]): boolean {
  return selected.length < MAX_SELECTED;
}
