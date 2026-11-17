// MON-D2 관측 근거: 응답 해석·reason 문구·다음 관측 문구(순수 로직, 서버·클라이언트 공용).
// 근거: docs/04_API.md A-06, docs/01_PRD.md#9(reason 코드 정본), tasks/task-015.md#착수 결정.

export type EvidenceStatus = "producible" | "pending" | "excluded" | "used";
export type EvidenceObservation = { observed_at: string; view_count: number };

/** PRD#9 reason 코드 10종. 새 코드를 추가하지 않는다. */
export const REASON_LABELS = {
  market: "시장 불일치",
  category: "카테고리 불일치",
  format: "형식 불일치",
  views_min: "최소 조회수 미달",
  not_cc: "C.C 라이선스 아님",
  broadcaster: "방송사 채널",
  keyword: "키워드 미포함",
  no_prev: "이전 관측 없음",
  license_unknown: "라이선스 미확인",
  growth_out_of_range: "허용 증가율 범위 밖",
} as const;

export type ReasonCode = keyof typeof REASON_LABELS;

export type Evidence = {
  candidate: { id: string; title: string; status: EvidenceStatus };
  prev: EvidenceObservation | null;
  curr: EvidenceObservation | null;
  growth_pct: number | null;
  /** 10종 밖 값은 null로 낮춘다. */
  reason: ReasonCode | null;
  needs_prev: boolean;
  next_observation_at: string | null;
};

/** 401일 때 보낼 곳. server/api/client.ts의 SESSION_EXPIRED_PATH와 같아야 한다(테스트가 확인). */
export const EVIDENCE_SESSION_EXPIRED_PATH = "/dashboard/session-expired";

const STATUSES: readonly EvidenceStatus[] = ["producible", "pending", "excluded", "used"];

export function isReasonCode(v: unknown): v is ReasonCode {
  return typeof v === "string" && Object.hasOwn(REASON_LABELS, v);
}

export function reasonLabel(v: unknown): string | null {
  return isReasonCode(v) ? REASON_LABELS[v] : null;
}

function pickObservation(v: unknown): EvidenceObservation | null {
  if (!v || typeof v !== "object") return null;
  const o = v as Record<string, unknown>;
  if (typeof o.observed_at !== "string" || typeof o.view_count !== "number" || !Number.isFinite(o.view_count)) return null;
  return { observed_at: o.observed_at, view_count: o.view_count };
}

/** API 응답 → 화면 필드만. 형식이 맞지 않으면 null. */
export function pickEvidence(v: unknown): Evidence | null {
  if (!v || typeof v !== "object") return null;
  const o = v as Record<string, unknown>;
  const c = o.candidate as Record<string, unknown> | null | undefined;
  if (!c || typeof c !== "object") return null;
  if (typeof c.id !== "string" || typeof c.title !== "string" || !STATUSES.includes(c.status as EvidenceStatus)) return null;
  const growth = typeof o.growth_pct === "number" && Number.isFinite(o.growth_pct) ? o.growth_pct : null;
  return {
    candidate: { id: c.id, title: c.title, status: c.status as EvidenceStatus },
    prev: pickObservation(o.prev),
    curr: pickObservation(o.curr),
    growth_pct: growth,
    reason: isReasonCode(o.reason) ? o.reason : null,
    needs_prev: o.needs_prev === true,
    next_observation_at: typeof o.next_observation_at === "string" ? o.next_observation_at : null,
  };
}

export type EvidenceFetchResult =
  | { kind: "ok"; data: Evidence }
  | { kind: "unauthorized" }
  | { kind: "not_found" }
  | { kind: "error" };

/** 브라우저 → /api/evidence/{id}. abort는 호출자가 구분한다(AbortError를 그대로 던진다). */
export async function fetchEvidence(id: string, signal: AbortSignal, fetchImpl: typeof fetch = fetch): Promise<EvidenceFetchResult> {
  const res = await fetchImpl(`/api/evidence/${encodeURIComponent(id)}`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal,
  });
  if (res.status === 401) return { kind: "unauthorized" };
  if (res.status === 404) return { kind: "not_found" };
  if (!res.ok) return { kind: "error" };
  const data = pickEvidence(((await res.json()) as { evidence?: unknown }).evidence);
  return data ? { kind: "ok", data } : { kind: "error" };
}

/** 다음 관측 시각이 지났는지. 해석 불가면 false. */
export function isObservationDue(nextAt: string, now: number): boolean {
  const t = new Date(nextAt).getTime();
  return !Number.isNaN(t) && t <= now;
}
