// PROD-01 브라우저 → Route Handler(/api/production-jobs/*) 호출. 서명 URL PUT만 Storage로 직접 간다.

export type Result<T> = { ok: true; data: T } | { ok: false; status: number; message: string; field?: string; keepKey: boolean };

const FALLBACK = "요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.";

async function call<T>(url: string, method: string, body?: unknown, headers: Record<string, string> = {}, fetchImpl: typeof fetch = fetch): Promise<Result<T>> {
  try {
    const res = await fetchImpl(url, {
      method,
      cache: "no-store",
      headers: { Accept: "application/json", ...(body !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = (await res.json().catch(() => null)) as Record<string, unknown> | null;
    if (res.ok) return { ok: true, data: data as T };
    const message = typeof data?.message === "string" && data.message ? data.message : FALLBACK;
    return { ok: false, status: res.status, message, field: typeof data?.field === "string" ? data.field : undefined, keepKey: res.status >= 500 };
  } catch {
    return { ok: false, status: 0, message: FALLBACK, keepKey: true };
  }
}

// task-031: URL 원본은 YouTube(https)만. 웹(화면·Route Handler) 검사는 1차이고 정본 검사는 API(url_guard)·워커가 한다.
const YT_HOSTS = new Set(["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"]);
export const URL_ONLY = "YouTube 주소(https)만 입력할 수 있습니다. 업로드 작업에는 URL을 쓰지 않습니다.";
export function isYoutubeUrl(value: string): boolean {
  let u: URL;
  try {
    u = new URL(value.trim());
  } catch {
    return false;
  }
  return u.protocol === "https:" && YT_HOSTS.has(u.hostname.toLowerCase()) && !u.username && !u.password && (u.port === "" || u.port === "443");
}

const base = (id: string) => `/api/production-jobs/${encodeURIComponent(id)}`;

export type SaveBody = {
  title?: string;
  candidate_id?: string;
  source_kind?: "upload" | "url"; // 없으면 upload
  source_url?: string | null;
  rights_confirmed: boolean;
  license_cc: boolean | null;
  credit: string | null;
  source_start_sec: number;
  segment_len_sec: number;
};

export type JobFormat = "category" | "variety";

export const createJob = (body: SaveBody & { title: string }, key: string, f?: typeof fetch, format: JobFormat = "category") =>
  call<{ job: { id: string; status: string } }>("/api/production-jobs", "POST", { source_kind: "upload", ...body, format }, { "Idempotency-Key": key }, f);

export const patchJob = (id: string, body: Omit<SaveBody, "title" | "candidate_id">, f?: typeof fetch) =>
  call<{ job: { id: string; status: string } }>(base(id), "PATCH", body, {}, f);

export const requestUpload = (id: string, size: number, mime: string, f?: typeof fetch) =>
  call<{ asset: { id: string }; upload_url: string; expires_at: string }>(`${base(id)}/uploads`, "POST", { kind: "source_upload", size_bytes: size, mime }, {}, f);

export const completeUpload = (id: string, assetId: string, f?: typeof fetch) =>
  call<{ asset: { id: string; status: string } }>(`${base(id)}/uploads/${encodeURIComponent(assetId)}/complete`, "POST", undefined, {}, f);

export const prepareJob = (id: string, f?: typeof fetch) => call<{ job: { id: string; status: string } }>(`${base(id)}/prepare`, "POST", undefined, {}, f);

/** 서명 URL에 파일을 PUT 한다. URL은 저장·로그하지 않는다. */
export async function putFile(url: string, file: Blob, mime: string, f: typeof fetch = fetch): Promise<boolean> {
  try {
    const res = await f(url, { method: "PUT", headers: { "Content-Type": mime }, body: file });
    return res.ok;
  } catch {
    return false;
  }
}
