import { base, call, type EditResult, type SavedRevision } from "../edit/api";
import type { Validation } from "@/server/api/production";

// 언어 탭(ja) 브라우저 → Route Handler 호출. 근거: tasks/task-052.md, docs/04_API.md A-12·A-13·A-20.

export type JaRevision = {
  id: string;
  rev_no: number;
  spec: Record<string, unknown>;
  origin: "user" | "ai_draft";
  validation: Validation;
  approved_at: string | null;
  derived_from?: string | null;
};
export type Translated = { revision: JaRevision; translate_count: number; replay: boolean };

/** A-20 번역 초안. key는 의도(클릭) 단위, 결과가 불명확한 실패면 같은 키로 재시도한다. */
export function requestTranslate(id: string, revisionId: string, key: string, f: typeof fetch = fetch): Promise<EditResult<Translated>> {
  const withKey: typeof fetch = (url, init) => f(url, { ...init, headers: { ...(init?.headers as Record<string, string>), "Idempotency-Key": key } });
  return call<Translated>(`${base(id)}/translate`, "POST", { revision_id: revisionId }, withKey);
}

export const saveJaRevision = (id: string, spec: Record<string, unknown>, baseRevNo: number, f?: typeof fetch) =>
  call<{ revision: SavedRevision }>(`${base(id)}/revision`, "PUT", { spec, base_rev_no: baseRevNo, lang: "ja" }, f);

export const approveJaRevision = (id: string, revNo: number, f?: typeof fetch) =>
  call<{ revision: { rev_no: number; approved_at: string } }>(`${base(id)}/revision/approve`, "POST", { rev_no: revNo, lang: "ja" }, f);
