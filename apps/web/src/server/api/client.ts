import "server-only";

import { createServerSupabase } from "@/server/supabase/client";
import { getVerifiedClaims } from "@/server/auth/session";

// 웹 → FastAPI 공용 클라이언트(서버 전용). 근거: tasks/task-016.md#구현 결정, docs/04_API.md#공통 규칙.

export const API_TIMEOUT_MS = 10_000;

/** 편집안 검증 항목(A-12·A-13 400 응답의 errors[]·warnings[]). */
export type ApiIssue = { code: string; path: string; message: string };

/** API 오류. status 0은 응답을 받지 못한 경우(타임아웃·연결 실패). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly field?: string,
    /** 400 VALIDATION 응답에 errors[]·warnings[]가 있으면 보존한다(없으면 undefined). */
    readonly errors?: ApiIssue[],
    readonly warnings?: ApiIssue[],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const DEFAULT_MESSAGES: Record<string, string> = {
  UNAUTHENTICATED: "로그인이 필요합니다.",
  FORBIDDEN: "워크스페이스 접근 권한이 없습니다. 관리자에게 문의하세요.",
  TIMEOUT: "서버 응답이 늦어 요청을 중단했습니다. 잠시 후 다시 시도하세요.",
  NETWORK: "서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.",
  INTERNAL: "서버에서 오류가 발생했습니다. 잠시 후 다시 시도하세요.",
  UNKNOWN: "요청을 처리하지 못했습니다.",
};

function defaultCode(status: number): string {
  if (status === 401) return "UNAUTHENTICATED";
  if (status === 403) return "FORBIDDEN";
  if (status >= 500) return "INTERNAL";
  return "UNKNOWN";
}

function toIssues(v: unknown): ApiIssue[] | undefined {
  if (!Array.isArray(v)) return undefined;
  return v.flatMap((i): ApiIssue[] => {
    const o = typeof i === "object" && i !== null ? (i as Record<string, unknown>) : null;
    return o && typeof o.code === "string" && typeof o.path === "string" && typeof o.message === "string"
      ? [{ code: o.code, path: o.path, message: o.message }]
      : [];
  });
}

/** 오류 응답(status, 본문)을 ApiError로 바꾼다. 본문이 {code,message,field?}가 아니면 상태 코드 기본값. */
export function toApiError(status: number, body: unknown): ApiError {
  const b = typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};
  const code = typeof b.code === "string" && b.code ? b.code : defaultCode(status);
  const message =
    typeof b.message === "string" && b.message ? b.message : (DEFAULT_MESSAGES[code] ?? DEFAULT_MESSAGES.UNKNOWN);
  const field = typeof b.field === "string" ? b.field : undefined;
  return new ApiError(status, code, message, field, toIssues(b.errors), toIssues(b.warnings));
}

/** 화면 처리 분류: 401 → 로그인 이동, 403 FORBIDDEN → 소속 없음 안내, 나머지 → 오류 상태. */
export function classifyApiError(error: unknown): "login" | "forbidden" | "error" {
  if (error instanceof ApiError) {
    if (error.status === 401) return "login";
    if (error.status === 403 && error.code === "FORBIDDEN") return "forbidden";
  }
  return "error";
}

export type ApiRequest = {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  query?: Record<string, string | undefined>;
  body?: unknown;
  /** 실행류 요청의 Idempotency-Key 헤더(task-013). */
  idempotencyKey?: string;
  /** 기본 API_TIMEOUT_MS 대신 쓸 제한 시간(task-013: 기록 검증 60초). */
  timeoutMs?: number;
};

type Transport = { baseUrl: string; token: string; fetchImpl?: typeof fetch; timeoutMs?: number };

/** 401일 때 보낼 곳. Server Component는 쿠키를 쓸 수 없어 Route Handler가 세션 쿠키를 지운 뒤 /login으로 보낸다. */
export const SESSION_EXPIRED_PATH = "/dashboard/session-expired";

function isTimeout(e: unknown): boolean {
  const name = e instanceof Error || e instanceof DOMException ? e.name : "";
  return name === "TimeoutError" || name === "AbortError";
}

/** path("/v1/"로 시작)를 base 아래에 붙인다. 조립 결과가 base의 origin·경로 밖이면 throw. */
export function buildApiUrl(baseUrl: string, path: string): URL {
  if (!path.startsWith("/v1/")) throw new Error(`API 경로는 /v1/로 시작해야 합니다: ${path}`);
  const base = new URL(baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
  const url = new URL(path.slice(1), base);
  if (url.origin !== base.origin || !url.pathname.startsWith(base.pathname)) {
    throw new Error("API 경로가 API_BASE_URL 밖을 가리킵니다");
  }
  return url;
}

/** 토큰·주소가 정해진 뒤의 요청. 테스트에서 fetch를 바꿔 끼운다. */
export async function sendApiRequest<T>(path: string, req: ApiRequest, t: Transport): Promise<T> {
  const url = buildApiUrl(t.baseUrl, path);
  for (const [k, v] of Object.entries(req.query ?? {})) if (v !== undefined) url.searchParams.set(k, v);

  const headers: Record<string, string> = { Authorization: `Bearer ${t.token}`, Accept: "application/json" };
  if (req.body !== undefined) headers["Content-Type"] = "application/json";
  if (req.idempotencyKey !== undefined) headers["Idempotency-Key"] = req.idempotencyKey;

  let res: Response;
  try {
    res = await (t.fetchImpl ?? fetch)(url, {
      method: req.method ?? "GET",
      headers,
      body: req.body === undefined ? undefined : JSON.stringify(req.body),
      cache: "no-store",
      signal: AbortSignal.timeout(req.timeoutMs ?? t.timeoutMs ?? API_TIMEOUT_MS),
    });
  } catch (e) {
    if (isTimeout(e)) throw new ApiError(0, "TIMEOUT", DEFAULT_MESSAGES.TIMEOUT);
    throw new ApiError(0, "NETWORK", DEFAULT_MESSAGES.NETWORK);
  }

  if (res.ok && res.status === 204) return undefined as T;
  let body: unknown;
  try {
    body = await res.json();
  } catch (e) {
    // 본문을 읽다가 시간이 다 되면 타임아웃, 성공 응답인데 해석할 수 없으면 서버 오류.
    if (isTimeout(e)) throw new ApiError(0, "TIMEOUT", DEFAULT_MESSAGES.TIMEOUT);
    if (res.ok) throw new ApiError(res.status, "INTERNAL", DEFAULT_MESSAGES.INTERNAL);
    body = null;
  }
  if (!res.ok) throw toApiError(res.status, body);
  return body as T;
}

/** API_BASE_URL 검증: http(s)만, 운영(NODE_ENV=production)은 https만, userinfo 금지. */
export function parseApiBaseUrl(value: string | undefined, nodeEnv = process.env.NODE_ENV): string {
  if (!value) throw new Error("환경변수 API_BASE_URL이(가) 없습니다");
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error("API_BASE_URL이 올바른 URL이 아닙니다");
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") throw new Error("API_BASE_URL은 http(s)만 허용합니다");
  const isLocal = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (nodeEnv === "production" && url.protocol !== "https:" && !isLocal) throw new Error("운영 환경의 API_BASE_URL은 https여야 합니다");
  if (url.username || url.password) throw new Error("API_BASE_URL에 사용자 정보를 넣을 수 없습니다");
  return value;
}

/** 현재 세션 사용자로 FastAPI를 호출한다. getClaims로 검증한 뒤 getSession의 access token을 전달한다. */
export async function apiFetch<T>(path: string, req: ApiRequest = {}): Promise<T> {
  const supabase = await createServerSupabase();
  const claims = await getVerifiedClaims(supabase);
  if (!claims) throw toApiError(401, null);
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw toApiError(401, null);
  return sendApiRequest<T>(path, req, { baseUrl: parseApiBaseUrl(process.env.API_BASE_URL), token });
}
