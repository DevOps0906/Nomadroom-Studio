import type { Affiliate, AssetRights, RightsBasis, ShoppingBrief, ShoppingVertical } from "@/server/api/production";

// 쇼핑 입력 1차 검사(타입·길이·허용값). 정본 검사는 API(task-044 BriefIn·AffiliateIn·RightsIn)다. 여기서는 허용된 필드만 골라 새 객체로 만든다.
// 오류는 { message, field }로 돌려주고, 입력 값은 문구에 넣지 않는다(제휴 링크 로그 금지).

export type Checked<T> = { ok: true; value: T } | { ok: false; message: string; field: string };
const bad = (field: string, message: string): { ok: false; message: string; field: string } => ({ ok: false, message, field });

const CONTROL = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u;
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const text = (v: unknown, max: number): string | null => (typeof v === "string" && v.trim().length <= max && !CONTROL.test(v) ? v.trim() : null);

export const VERTICALS: readonly ShoppingVertical[] = ["product", "travel"];
export const isVertical = (v: unknown): v is ShoppingVertical => v === "product" || v === "travel";
const BASES: readonly RightsBasis[] = ["own", "licensed", "permission", "quote", "platform_audio"];
const PRODUCT_TYPES = ["stay", "tour", "package"] as const;
const GENDERS = ["female", "male", "all"] as const;
const SHORT = 100;
const LONG = 300;
const MAX_URL = 2048;
export const MAX_AFFILIATES = 20;

export function parseBrief(v: unknown): Checked<ShoppingBrief> {
  if (!isObj(v)) return bad("brief", "브리프 형식이 올바르지 않습니다.");
  const out: ShoppingBrief = {};
  for (const [key, max] of [["product_name", SHORT], ["destination", SHORT], ["pain", LONG], ["appeal", LONG], ["avoid", LONG]] as const) {
    if (v[key] === undefined) continue;
    const t = text(v[key], max);
    if (t === null) return bad(`brief.${key}`, `${max}자 이하 텍스트로 입력하세요.`);
    if (t) out[key] = t;
  }
  if (v.product_type !== undefined) {
    if (!(PRODUCT_TYPES as readonly unknown[]).includes(v.product_type)) return bad("brief.product_type", "상품 종류가 올바르지 않습니다.");
    out.product_type = v.product_type as (typeof PRODUCT_TYPES)[number];
  }
  for (const [key, cap] of [["scenes", 5], ["facts", 10]] as const) {
    if (v[key] === undefined) continue;
    const list = v[key];
    if (!Array.isArray(list) || list.length > cap) return bad(`brief.${key}`, `최대 ${cap}개까지 입력할 수 있습니다.`);
    const items: string[] = [];
    for (const it of list) {
      const t = text(it, LONG);
      if (t === null) return bad(`brief.${key}`, `${LONG}자 이하 텍스트로 입력하세요.`);
      if (t) items.push(t);
    }
    out[key] = items;
  }
  if (v.target !== undefined) {
    if (!isObj(v.target)) return bad("brief.target", "대상 형식이 올바르지 않습니다.");
    const target: NonNullable<ShoppingBrief["target"]> = {};
    if (v.target.gender !== undefined) {
      if (!(GENDERS as readonly unknown[]).includes(v.target.gender)) return bad("brief.target", "성별 값이 올바르지 않습니다.");
      target.gender = v.target.gender as (typeof GENDERS)[number];
    }
    if (v.target.age !== undefined) {
      const age = text(v.target.age, SHORT);
      if (age === null) return bad("brief.target", "연령대는 100자 이하로 입력하세요.");
      if (age) target.age = age;
    }
    out.target = target;
  }
  return { ok: true, value: out };
}

/** 제휴 링크: https만·공백·사용자 정보 없음·2048자 이하. */
export function isAffiliateUrl(v: unknown): v is string {
  if (typeof v !== "string" || v.length === 0 || v.length > MAX_URL || /\s/.test(v) || CONTROL.test(v)) return false;
  try {
    const u = new URL(v);
    return u.protocol === "https:" && !!u.hostname && !u.username && !u.password;
  } catch {
    return false;
  }
}

export function parseAffiliates(v: unknown): Checked<Affiliate[]> {
  if (!Array.isArray(v) || v.length > MAX_AFFILIATES) return bad("affiliates", `제휴 링크는 최대 ${MAX_AFFILIATES}개입니다.`);
  const out: Affiliate[] = [];
  for (const a of v) {
    if (!isObj(a) || (a.lang !== "ko" && a.lang !== "ja")) return bad("affiliates", "제휴 링크 언어가 올바르지 않습니다.");
    const partner = text(a.partner, 50);
    if (!partner) return bad("affiliates", "제휴처는 1~50자로 입력하세요.");
    if (!isAffiliateUrl(a.url)) return bad("affiliates", "제휴 링크는 https 주소만 입력할 수 있습니다.");
    out.push({ lang: a.lang, partner, url: a.url });
  }
  return { ok: true, value: out };
}

export function parseCommentKeyword(v: unknown): Checked<string | null> {
  if (v === null) return { ok: true, value: null };
  const t = text(v, 50);
  return t === null ? bad("comment_keyword", "댓글 유도 단어는 50자 이하로 입력하세요.") : { ok: true, value: t || null };
}

export type ShoppingFields = { vertical?: ShoppingVertical; brief?: ShoppingBrief; affiliates?: Affiliate[]; comment_keyword?: string | null };

/** 보낸 쇼핑 필드만 검사해 모은다(PATCH·POST 공용). */
export function parseShoppingFields(b: Record<string, unknown>): Checked<ShoppingFields> {
  const out: ShoppingFields = {};
  if ("vertical" in b) {
    if (!isVertical(b.vertical)) return bad("vertical", "분야가 올바르지 않습니다.");
    out.vertical = b.vertical;
  }
  if ("brief" in b) {
    const r = parseBrief(b.brief);
    if (!r.ok) return r;
    out.brief = r.value;
  }
  if ("affiliates" in b) {
    const r = parseAffiliates(b.affiliates);
    if (!r.ok) return r;
    out.affiliates = r.value;
  }
  if ("comment_keyword" in b) {
    const r = parseCommentKeyword(b.comment_keyword);
    if (!r.ok) return r;
    out.comment_keyword = r.value;
  }
  return { ok: true, value: out };
}

export const hasShoppingFields = (b: Record<string, unknown>) => ["vertical", "brief", "affiliates", "comment_keyword"].some((k) => k in b);

/** 업로드 권리(자산마다). 허용된 필드만 새 객체로 옮긴다(gen·reviewed 등 추가 필드는 버리지 않고 거부). */
export function parseRights(v: unknown): Checked<AssetRights> {
  if (!isObj(v)) return bad("rights", "권리 근거를 입력하세요.");
  const allowed = new Set(["basis", "source_url", "author", "has_person", "portrait_consent", "note"]);
  if (Object.keys(v).some((k) => !allowed.has(k))) return bad("rights", "권리 항목이 올바르지 않습니다.");
  if (!(BASES as readonly unknown[]).includes(v.basis)) return bad("rights.basis", "권리 근거를 선택하세요.");
  const out: AssetRights = { basis: v.basis as RightsBasis };
  if (v.source_url !== undefined && v.source_url !== "") {
    if (typeof v.source_url !== "string" || v.source_url.length > MAX_URL || /\s/.test(v.source_url) || !/^https?:\/\//i.test(v.source_url))
      return bad("rights.source_url", "출처 URL은 http(s) 주소로 입력하세요.");
    out.source_url = v.source_url;
  }
  if (v.author !== undefined && v.author !== "") {
    const a = text(v.author, SHORT);
    if (!a) return bad("rights.author", "저작자는 100자 이하로 입력하세요.");
    out.author = a;
  }
  if (v.note !== undefined && v.note !== "") {
    const n = text(v.note, 500);
    if (!n) return bad("rights.note", "메모는 500자 이하로 입력하세요.");
    out.note = n;
  }
  for (const k of ["has_person", "portrait_consent"] as const) {
    if (v[k] === undefined) continue;
    if (typeof v[k] !== "boolean") return bad(`rights.${k}`, "예·아니오 값이어야 합니다.");
    out[k] = v[k];
  }
  if (out.has_person && !out.portrait_consent) return bad("rights.portrait_consent", "인물이 나오면 초상권 동의가 필요합니다.");
  return { ok: true, value: out };
}
