import "server-only";

import { apiFetch } from "./client";

// 제작 작업 API 호출(A-09~A-13·A-17·A-18). 계약: docs/04_API.md#제작-api, tasks/task-022.md.
// 웹·API는 작업 ID·자산 ID만 주고받는다(경로·파일명 없음). 화면 타입은 task-025에서 정한다.

export type ProductionStatus = "draft" | "preparing" | "review" | "rendering" | "inspect" | "done" | "failed";

export type ProductionJob = {
  id: string;
  title: string;
  format: "category" | "variety";
  status: ProductionStatus;
  failed_stage: "prepare" | "audio" | "render" | null;
  error_code: string | null;
  candidate_id: string | null;
  source_kind: "upload" | "url";
  rights_confirmed: boolean;
  rights_confirmed_by: string | null;
  rights_confirmed_at: string | null;
  license_cc: boolean | null;
  credit: string | null;
  source_start_sec: number;
  segment_len_sec: number;
  lang: "ko";
  preset_version: string;
  current_revision_id: string | null;
  retry_count: number;
  updated_at: string;
  created_at: string;
  completed_at: string | null;
};

export type ProductionJobListItem = Pick<
  ProductionJob,
  "id" | "title" | "format" | "status" | "failed_stage" | "error_code" | "candidate_id" | "updated_at" | "completed_at"
>;

export type ProductionAsset = {
  id: string;
  kind: string;
  status: "pending" | "ready";
  size_bytes: number | null;
  duration_sec: number | null;
};

export type SpecIssue = { code: string; path: string; message: string };
export type Validation = { errors: SpecIssue[]; warnings: SpecIssue[] };

export type Revision = {
  id: string;
  rev_no: number;
  spec: Record<string, unknown>;
  origin: "user" | "ai_draft";
  validation: Validation;
  approved_at: string | null;
};

export type ProductionJobDetail = {
  job: ProductionJob;
  assets: ProductionAsset[];
  current_revision: { ko: Pick<Revision, "id" | "rev_no" | "approved_at" | "validation"> | null; ja: null };
  latest_run: {
    id: string;
    status: "queued" | "running" | "done" | "failed";
    progress_pct: number;
    progress_stage: string | null;
    error_stage: string | null;
    error_code: string | null;
    attempt: number;
  } | null;
  worker_online: boolean;
};

export type CreateProductionJob = {
  title: string;
  format?: "category";
  candidate_id?: string;
  source_kind: "upload";
  rights_confirmed: boolean;
  license_cc?: boolean | null;
  credit?: string | null;
  source_start_sec: number;
  segment_len_sec: number;
};

export type PatchProductionJob = Partial<
  Pick<CreateProductionJob, "source_kind" | "rights_confirmed" | "license_cc" | "credit" | "source_start_sec" | "segment_len_sec">
>;

export type UploadKind = "source_upload" | "hook_audio";
export type UploadTicket = {
  asset: { id: string; kind: UploadKind; status: "pending" };
  upload_url: string;
  expires_at: string;
};

const BASE = "/v1/production-jobs";
const jobPath = (id: string) => `${BASE}/${encodeURIComponent(id)}`;

export function listProductionJobs(query: { status?: ProductionStatus; format?: "category" | "variety"; page?: number; size?: number } = {}) {
  return apiFetch<{ items: ProductionJobListItem[] }>(BASE, {
    query: {
      status: query.status,
      format: query.format,
      page: query.page?.toString(),
      size: query.size?.toString(),
    },
  });
}

export function getProductionJob(id: string): Promise<ProductionJobDetail> {
  return apiFetch<ProductionJobDetail>(jobPath(id));
}

/** A-09 생성. 같은 Idempotency-Key 재요청은 기존 작업을 돌려준다. */
export async function createProductionJob(body: CreateProductionJob, idempotencyKey: string): Promise<ProductionJob> {
  return (await apiFetch<{ job: ProductionJob }>(BASE, { method: "POST", body, idempotencyKey })).job;
}

export async function patchProductionJob(id: string, body: PatchProductionJob): Promise<ProductionJob> {
  return (await apiFetch<{ job: ProductionJob }>(jobPath(id), { method: "PATCH", body })).job;
}

/** A-10 업로드 서명 발급. upload_url은 브라우저가 PUT 한 번에만 쓰고 저장·로그하지 않는다. */
export function requestProductionUpload(id: string, body: { kind: UploadKind; size_bytes: number; mime: string }) {
  return apiFetch<UploadTicket>(`${jobPath(id)}/uploads`, { method: "POST", body });
}

export async function completeProductionUpload(id: string, assetId: string): Promise<ProductionAsset> {
  const path = `${jobPath(id)}/uploads/${encodeURIComponent(assetId)}/complete`;
  return (await apiFetch<{ asset: ProductionAsset }>(path, { method: "POST" })).asset;
}

/** A-11 준비 시작·원본 단계 재시도. */
export async function prepareProductionJob(id: string): Promise<ProductionJob> {
  return (await apiFetch<{ job: ProductionJob }>(`${jobPath(id)}/prepare`, { method: "POST" })).job;
}

/** A-12 리비전 조회(rev_no 생략 = 현재). */
export async function getProductionRevision(id: string, revNo?: number): Promise<Revision> {
  const res = await apiFetch<{ revision: Revision }>(`${jobPath(id)}/revision`, { query: { rev_no: revNo?.toString() } });
  return res.revision;
}

/** A-12 저장(낙관적 잠금 base_rev_no). 의미 오류가 있어도 저장되고 validation에 담긴다. */
export async function saveProductionRevision(id: string, spec: Record<string, unknown>, baseRevNo: number): Promise<Revision> {
  const res = await apiFetch<{ revision: Revision }>(`${jobPath(id)}/revision`, {
    method: "PUT",
    body: { spec, base_rev_no: baseRevNo },
  });
  return res.revision;
}

/** A-13 편집안 승인(서버 재검증). */
export async function approveProductionRevision(id: string, revNo: number) {
  const res = await apiFetch<{ revision: { id: string; rev_no: number; approved_at: string; approved_by: string | null } }>(
    `${jobPath(id)}/revision/approve`,
    { method: "POST", body: { rev_no: revNo } },
  );
  return res.revision;
}

/** A-17 검수 승인(inspect → done). */
export async function approveProductionReview(id: string): Promise<ProductionJob> {
  return (await apiFetch<{ job: ProductionJob }>(`${jobPath(id)}/review/approve`, { method: "POST" })).job;
}

/** A-18 다운로드 서명 URL(10분). */
export function getProductionDownloadUrl(id: string, assetId: string) {
  return apiFetch<{ url: string; expires_at: string; kind: string }>(
    `${jobPath(id)}/assets/${encodeURIComponent(assetId)}/download-url`,
  );
}
