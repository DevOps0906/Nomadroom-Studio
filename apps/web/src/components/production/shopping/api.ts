import type { AssetRights, PublishTextResult, ShoppingBrief, ShoppingVertical, Affiliate } from "@/server/api/production";
import { completeUpload, prepareJob, putFile, type Result } from "../api";

// PROD-01S·02S·03 브라우저 → Route Handler 호출(쇼핑). 서명 URL PUT만 Storage로 직접 간다. 근거: tasks/task-046.md.

export { completeUpload, prepareJob, putFile };
export type { Result };

const FALLBACK = "요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.";

async function call<T>(url: string, method: string, body?: unknown, headers: Record<string, string> = {}, f: typeof fetch = fetch): Promise<Result<T>> {
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
    return { ok: false, status: res.status, message, field: typeof data?.field === "string" ? data.field : undefined, keepKey: res.status >= 500 };
  } catch {
    return { ok: false, status: 0, message: FALLBACK, keepKey: true };
  }
}

const base = (id: string) => `/api/production-jobs/${encodeURIComponent(id)}`;

export type ShoppingFields = { vertical?: ShoppingVertical; brief?: ShoppingBrief; affiliates?: Affiliate[]; comment_keyword?: string | null };

/** 쇼핑 작업 생성(A-09 POST). 원본은 업로드만, 권리는 자산마다라 작업 단위 rights_confirmed는 false로 보낸다. */
export const createShoppingJob = (title: string, fields: Required<Pick<ShoppingFields, "vertical">> & ShoppingFields, key: string, f?: typeof fetch) =>
  call<{ job: { id: string; status: string } }>(
    "/api/production-jobs",
    "POST",
    { title, kind: "shopping", format: "shopping", source_kind: "upload", rights_confirmed: false, not_banned_confirmed: true, source_start_sec: 0, segment_len_sec: 30, ...fields },
    { "Idempotency-Key": key },
    f,
  );

export const patchShoppingJob = (id: string, fields: ShoppingFields, f?: typeof fetch) => call<{ job: { id: string; status: string } }>(base(id), "PATCH", fields, {}, f);

export const requestShoppingUpload = (id: string, body: { kind: "source_upload" | "image" | "bgm" | "narration"; size_bytes: number; mime: string; rights: AssetRights }, f?: typeof fetch) =>
  call<{ asset: { id: string }; upload_url: string; expires_at: string }>(`${base(id)}/uploads`, "POST", body, {}, f);

export const deleteAsset = (id: string, assetId: string, f?: typeof fetch) => call<{ ok: true }>(`${base(id)}/assets/${encodeURIComponent(assetId)}`, "DELETE", undefined, {}, f);

export const fetchPublishText = (id: string, lang: "ko" | "ja" = "ko", f?: typeof fetch) =>
  call<Pick<PublishTextResult, "text" | "render_run_id" | "lang">>(`${base(id)}/publish-text`, "POST", { lang }, {}, f);

/** 파일 하나를 서명 PUT → 완료 확인까지 올린다. 실패하면 사유 문구와 상태를 돌려준다. */
export async function uploadAsset(
  id: string,
  file: File,
  kind: "source_upload" | "image" | "bgm" | "narration",
  mime: string,
  rights: AssetRights,
  f?: typeof fetch,
): Promise<Result<{ assetId: string }>> {
  const t = await requestShoppingUpload(id, { kind, size_bytes: file.size, mime, rights }, f);
  if (!t.ok) return t;
  if (!(await putFile(t.data.upload_url, file, mime, f))) return { ok: false, status: 0, message: "업로드에 실패했습니다. 다시 시도하세요.", keepKey: true };
  const c = await completeUpload(id, t.data.asset.id, f);
  if (!c.ok) return c;
  return { ok: true, data: { assetId: t.data.asset.id } };
}

// PROD-01S AI 영상 생성(A-22) 브라우저 호출. 확인(과금)·진행 확인은 사용자가 누른 때에만 부른다.
export type GenerationRunView = import("@/server/api/production").GenerationRun;
export type GenerationEnvelopeView = import("@/server/api/production").GenerationEnvelope;
const gen = (id: string) => `${base(id)}/generation-runs`;
const genRun = (id: string, runId: string) => `${gen(id)}/${encodeURIComponent(runId)}`;

export const listGeneration = (id: string, f?: typeof fetch) => call<{ items: GenerationRunView[] }>(gen(id), "GET", undefined, {}, f);
export const quoteGeneration = (id: string, body: { source_asset_id: string; prompt: string; duration_sec: number }, key: string, f?: typeof fetch) =>
  call<GenerationEnvelopeView>(gen(id), "POST", body, { "Idempotency-Key": key }, f);
export const confirmGeneration = (id: string, runId: string, f?: typeof fetch) => call<GenerationEnvelopeView>(`${genRun(id, runId)}/confirm`, "POST", undefined, {}, f);
export const refreshGeneration = (id: string, runId: string, f?: typeof fetch) => call<GenerationEnvelopeView>(`${genRun(id, runId)}/refresh`, "POST", undefined, {}, f);
export const reviewGeneration = (id: string, runId: string, checks: { physics: boolean; angle: boolean; compare: boolean }, f?: typeof fetch) =>
  call<{ run_id: string; reviewed: boolean }>(`${genRun(id, runId)}/review`, "POST", checks, {}, f);

/** 생성 결과 영상(result)·입력 사진(source)의 서명 GET 주소. 사용자가 누른 때에만 부른다. */
export const generationAssetUrl = (id: string, runId: string, which: "result" | "source", f?: typeof fetch) =>
  call<{ url: string }>(`${genRun(id, runId)}/asset-url?which=${which}`, "GET", undefined, {}, f);
