// PROD-03 브라우저 → Route Handler 호출. 서명 URL은 응답으로만 받고 저장·로그하지 않는다. 근거: tasks/task-027.md.

export type RunResult<T> = { ok: true; data: T } | { ok: false; status: number; message: string; keepKey: boolean };

const FALLBACK = "요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.";

async function call<T>(url: string, method: string, body?: unknown, headers: Record<string, string> = {}, f: typeof fetch = fetch): Promise<RunResult<T>> {
  try {
    const res = await f(url, {
      method,
      cache: "no-store",
      headers: { Accept: "application/json", ...(body !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = (await res.json().catch(() => null)) as Record<string, unknown> | null;
    if (res.ok) return { ok: true, data: data as T };
    const message = typeof data?.message === "string" && data.message ? data.message : FALLBACK;
    return { ok: false, status: res.status, message, keepKey: res.status >= 500 };
  } catch {
    return { ok: false, status: 0, message: FALLBACK, keepKey: true };
  }
}

const base = (id: string) => `/api/production-jobs/${encodeURIComponent(id)}`;

type RunBody = { run: { id: string; status: string; attempt: number } };

export const requestRender = (id: string, revisionId: string, key: string, f?: typeof fetch) =>
  call<RunBody>(`${base(id)}/render-runs`, "POST", { revision_id: revisionId, lang: "ko" }, { "Idempotency-Key": key }, f);

export const retryRender = (id: string, runId: string, f?: typeof fetch) =>
  call<RunBody>(`${base(id)}/render-runs/${encodeURIComponent(runId)}/retry`, "POST", undefined, {}, f);

export const approveReview = (id: string, f?: typeof fetch) =>
  call<{ job: { id: string; status: string } }>(`${base(id)}/review/approve`, "POST", undefined, {}, f);

export const assetUrl = (id: string, assetId: string, f?: typeof fetch) =>
  call<{ url: string }>(`${base(id)}/assets/${encodeURIComponent(assetId)}/download-url`, "GET", undefined, {}, f);
