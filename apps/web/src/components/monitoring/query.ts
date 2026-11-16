// MON-01 URL searchParams ↔ A-04 조회 조건(순수). 잘못된 값은 기본값, 배열은 첫 값(400이 나지 않게).
// 근거: tasks/task-013.md#구현 결정, docs/04_API.md#A-04.

export type CandidateStatus = "all" | "producible" | "pending" | "excluded" | "used";
export type CandidateSort = "growth" | "views" | "recent";
export type FormatFilter = "all" | "short" | "long";
export type LicenseFilter = "any" | "cc";

export type CandidateQuery = {
  status: CandidateStatus;
  category: string | null;
  format: FormatFilter;
  profile_id: string | null;
  license: LicenseFilter;
  q: string;
  sort: CandidateSort;
  page: number;
};

export const PAGE_SIZE = 24;
export const MAX_PAGE = 1000;
export const MAX_Q = 100;
const MAX_CATEGORY = 40;

export const STATUSES: { value: CandidateStatus; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "producible", label: "제작 가능" },
  { value: "pending", label: "근거 대기" },
  { value: "excluded", label: "조건 제외" },
  { value: "used", label: "사용한 소재" },
];
export const SORTS: { value: CandidateSort; label: string }[] = [
  { value: "growth", label: "증가율" },
  { value: "views", label: "조회수" },
  { value: "recent", label: "최신" },
];
export const FORMAT_FILTERS: { value: FormatFilter; label: string }[] = [
  { value: "all", label: "전체 형식" },
  { value: "short", label: "쇼츠" },
  { value: "long", label: "롱폼" },
];
export const LICENSE_FILTERS: { value: LicenseFilter; label: string }[] = [
  { value: "any", label: "모든 라이선스" },
  { value: "cc", label: "C.C만" },
];

export const DEFAULT_QUERY: CandidateQuery = {
  status: "all",
  category: null,
  format: "all",
  profile_id: null,
  license: "any",
  q: "",
  sort: "recent",
  page: 1,
};

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CONTROL_RE = /[\u0000-\u001f\u007f-\u009f]/g;

export function isUuid(v: unknown): v is string {
  return typeof v === "string" && UUID_RE.test(v);
}

type Raw = Record<string, string | string[] | undefined>;

function first(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v;
}

function pick<T extends string>(v: string | undefined, list: { value: T }[], fallback: T): T {
  return list.find((x) => x.value === v)?.value ?? fallback;
}

/** 제어 문자 제거 + 앞뒤 공백 제거 + 100자(코드 포인트)에서 자른다. */
export function cleanQ(v: string | undefined): string {
  if (!v) return "";
  return [...v.replace(CONTROL_RE, "").trim()].slice(0, MAX_Q).join("").trim();
}

export function parseCandidateQuery(raw: Raw): CandidateQuery {
  const page = Number(first(raw.page));
  const category = cleanQ(first(raw.category));
  const profile = first(raw.profile_id);
  return {
    status: pick(first(raw.status), STATUSES, "all"),
    category: category && [...category].length <= MAX_CATEGORY ? category : null,
    format: pick(first(raw.format), FORMAT_FILTERS, "all"),
    profile_id: isUuid(profile) ? profile.toLowerCase() : null,
    license: pick(first(raw.license), LICENSE_FILTERS, "any"),
    q: cleanQ(first(raw.q)),
    sort: pick(first(raw.sort), SORTS, "recent"),
    page: Number.isInteger(page) && page >= 1 && page <= MAX_PAGE ? page : 1,
  };
}

/** 기본값이 아닌 조건만 URL 쿼리 문자열로("?..." 또는 "?"). 필터를 바꾸면 page는 1로. */
export function toHref(query: CandidateQuery, patch: Partial<CandidateQuery> = {}): string {
  const next = { ...query, ...patch };
  if (!("page" in patch)) next.page = 1;
  const sp = new URLSearchParams();
  for (const key of Object.keys(DEFAULT_QUERY) as (keyof CandidateQuery)[]) {
    const v = next[key];
    if (v === null || v === "" || v === DEFAULT_QUERY[key]) continue;
    sp.set(key, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "?";
}

/** A-04 쿼리 파라미터. */
export function toApiQuery(query: CandidateQuery): Record<string, string | undefined> {
  return {
    status: query.status,
    category: query.category ?? undefined,
    format: query.format,
    profile_id: query.profile_id ?? undefined,
    license: query.license,
    q: query.q || undefined,
    sort: query.sort,
    page: String(query.page),
    size: String(PAGE_SIZE),
  };
}
