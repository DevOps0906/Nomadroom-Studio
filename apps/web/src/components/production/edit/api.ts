import type { SpecIssue, Validation } from "@/server/api/production";

// PROD-02 브라우저 → Route Handler 호출. 서명 URL PUT만 Storage로 직접 간다. 근거: tasks/task-026.md.

export type EditResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; message: string; code?: string; errors?: SpecIssue[]; warnings?: SpecIssue[] };

const FALLBACK = "요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.";

const isIssue = (i: unknown): i is SpecIssue => {
  const o = i as Record<string, unknown> | null;
  return typeof o?.code === "string" && typeof o?.path === "string" && typeof o?.message === "string";
};
const issues = (v: unknown): SpecIssue[] | undefined => (Array.isArray(v) ? v.filter(isIssue) : undefined);

export async function call<T>(url: string, method: string, body?: unknown, f: typeof fetch = fetch): Promise<EditResult<T>> {
  try {
    const res = await f(url, {
      method,
      cache: "no-store",
      headers: { Accept: "application/json", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = (await res.json().catch(() => null)) as Record<string, unknown> | null;
    if (res.ok) return { ok: true, data: data as T };
    const message = typeof data?.message === "string" && data.message ? data.message : FALLBACK;
    return { ok: false, status: res.status, message, code: typeof data?.code === "string" ? data.code : undefined, errors: issues(data?.errors), warnings: issues(data?.warnings) };
  } catch {
    return { ok: false, status: 0, message: FALLBACK };
  }
}

export const base = (id: string) => `/api/production-jobs/${encodeURIComponent(id)}`;

export type SavedRevision = { id: string; rev_no: number; validation: Validation; approved_at: string | null };

export type AiDraft = {
  revision: { id: string; rev_no: number; spec: Record<string, unknown>; origin: "user" | "ai_draft"; validation: Validation; approved_at: string | null };
  ai_draft_count: number;
  previous_rev_no: number | null;
  /** 쇼핑만(그 밖은 null·없음). */
  variants?: { hook_type: string; sentences: string[]; char_count: number }[] | null;
  facts_to_check?: string[] | null;
};

/** A-14 AI 초안. key는 클릭(의도) 단위로 만든다. */
export function requestAiDraft(id: string, key: string, f: typeof fetch = fetch): Promise<EditResult<AiDraft>> {
  const withKey: typeof fetch = (url, init) => f(url, { ...init, headers: { ...(init?.headers as Record<string, string>), "Idempotency-Key": key } });
  return call<AiDraft>(`${base(id)}/ai-draft`, "POST", undefined, withKey);
}

export const saveRevision =(id: string, spec: Record<string, unknown>, baseRevNo: number, f?: typeof fetch) =>
  call<{ revision: SavedRevision }>(`${base(id)}/revision`, "PUT", { spec, base_rev_no: baseRevNo }, f);

export const approveRevision = (id: string, revNo: number, f?: typeof fetch) =>
  call<{ revision: { rev_no: number; approved_at: string } }>(`${base(id)}/revision/approve`, "POST", { rev_no: revNo }, f);

export const requestHookAudio = (id: string, size: number, mime: string, f?: typeof fetch) =>
  call<{ asset: { id: string }; upload_url: string; expires_at: string }>(`${base(id)}/revision/hook-audio`, "POST", { size_bytes: size, mime }, f);

export const completeHookAudio = (id: string, assetId: string, f?: typeof fetch) =>
  call<{ asset: { id: string; status: string } }>(`${base(id)}/uploads/${encodeURIComponent(assetId)}/complete`, "POST", undefined, f);

export const sheetUrl = (id: string, assetId: string, f?: typeof fetch) =>
  call<{ url: string }>(`${base(id)}/revision/sheet/${encodeURIComponent(assetId)}`, "GET", undefined, f);

/** 서명 URL에 음성 파일을 PUT 한다. URL은 저장·로그하지 않는다. */
export async function putAudio(url: string, file: Blob, mime: string, f: typeof fetch = fetch): Promise<boolean> {
  try {
    return (await f(url, { method: "PUT", headers: { "Content-Type": mime }, body: file })).ok;
  } catch {
    return false;
  }
}

const AUDIO_MIMES: Record<string, string> = { wav: "audio/wav", mp3: "audio/mpeg", m4a: "audio/mp4" };
export const AUDIO_ACCEPT = ".wav,.mp3,.m4a";
export const MAX_AUDIO_BYTES = 50 * 1024 * 1024;
export function audioMime(file: Pick<File, "name">): string | null {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  return AUDIO_MIMES[ext] ?? null;
}
