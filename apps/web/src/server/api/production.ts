import "server-only";

import { apiFetch } from "./client";

// 제작 작업 API 호출(A-09~A-13·A-17·A-18). 계약: docs/04_API.md#제작-api, tasks/task-022.md.
// 웹·API는 작업 ID·자산 ID만 주고받는다(경로·파일명 없음). 화면 타입은 task-025에서 정한다.

export type ProductionStatus = "draft" | "preparing" | "review" | "rendering" | "inspect" | "done" | "failed";

export type ShoppingVertical = "product" | "travel";
export type ShoppingBrief = {
  product_name?: string;
  pain?: string;
  destination?: string;
  product_type?: "stay" | "tour" | "package";
  appeal?: string;
  scenes?: string[];
  avoid?: string;
  facts?: string[];
  target?: { gender?: "female" | "male" | "all"; age?: string };
};
export type Affiliate = { lang: "ko" | "ja"; partner: string; url: string };
export type JobFormat = "category" | "variety" | "shopping";

export type ProductionJob = {
  id: string;
  title: string;
  format: JobFormat;
  // 쇼핑 확장(A-09, task-044). 일반 작업은 kind=general·나머지 비어 있음.
  kind?: "general" | "shopping";
  vertical?: ShoppingVertical | null;
  brief?: ShoppingBrief | null;
  affiliates?: Affiliate[];
  comment_keyword?: string | null;
  status: ProductionStatus;
  failed_stage: "prepare" | "audio" | "render" | null;
  error_code: string | null;
  candidate_id: string | null;
  source_kind: "upload" | "url";
  source_url: string | null;
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
> & { kind?: "general" | "shopping"; vertical?: ShoppingVertical | null; langs?: ("ko" | "ja")[] };

export type RightsBasis = "own" | "licensed" | "permission" | "quote" | "platform_audio";
export type AssetRights = {
  basis: RightsBasis;
  source_url?: string;
  author?: string;
  has_person?: boolean;
  portrait_consent?: boolean;
  note?: string;
};

export type ProductionAsset = {
  id: string;
  kind: string;
  status: "pending" | "ready";
  size_bytes: number | null;
  duration_sec: number | null;
  // A-09 GET은 아직 권리를 돌려주지 않는다(ASSET_COLUMNS). 주면 PROD-03 권리 목록이 채운다.
  rights?: AssetRights | null;
  /** 산출물이 연결된 render run의 언어(task-060). 연결이 없으면 null, 구 API면 없음. */
  render_lang?: "ko" | "ja" | null;
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
  /** 다음 A-12 PUT의 base_updated_at(task-059). 가공 없이 문자열 그대로 돌려보낸다. */
  updated_at: string;
  /** ja 리비전의 원본 ko 리비전(A-12, task-049). */
  derived_from?: string | null;
};

export type RevisionLang = "ko" | "ja";

export type RunSummary = {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  progress_pct: number;
  progress_stage: string | null;
  error_stage: string | null;
  error_code: string | null;
  attempt: number;
};

export type ProductionJobDetail = {
  job: ProductionJob;
  assets: ProductionAsset[];
  current_revision: {
    ko: Pick<Revision, "id" | "rev_no" | "approved_at" | "validation"> | null;
    ja?: Pick<Revision, "id" | "rev_no" | "approved_at" | "validation"> | null;
  };
  latest_run: RunSummary | null;
  /** 언어별 최신 run(task-060). 구 API면 없음. */
  latest_runs?: { ko: RunSummary | null; ja: RunSummary | null };
  worker_online: boolean;
};

export type CreateProductionJob = {
  title: string;
  kind?: "general" | "shopping";
  format?: JobFormat;
  vertical?: ShoppingVertical;
  brief?: ShoppingBrief;
  affiliates?: Affiliate[];
  comment_keyword?: string | null;
  not_banned_confirmed?: boolean;
  candidate_id?: string;
  source_kind: "upload" | "url";
  source_url?: string | null;
  rights_confirmed: boolean;
  license_cc?: boolean | null;
  credit?: string | null;
  source_start_sec: number;
  segment_len_sec: number;
};

export type PatchProductionJob = Partial<
  Pick<
    CreateProductionJob,
    "source_kind" | "source_url" | "rights_confirmed" | "license_cc" | "credit" | "source_start_sec" | "segment_len_sec" | "vertical" | "brief" | "affiliates" | "comment_keyword"
  >
>;

export type UploadKind = "source_upload" | "hook_audio" | "image" | "bgm" | "narration";
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
export function requestProductionUpload(id: string, body: { kind: UploadKind; size_bytes: number; mime: string; rights?: AssetRights }) {
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
export async function getProductionRevision(id: string, revNo?: number, lang: RevisionLang = "ko"): Promise<Revision> {
  const res = await apiFetch<{ revision: Revision }>(`${jobPath(id)}/revision`, {
    query: { rev_no: revNo?.toString(), lang: lang === "ja" ? "ja" : undefined },
  });
  return res.revision;
}

/** A-12 저장(낙관적 잠금 base_rev_no·base_updated_at). 의미 오류가 있어도 저장되고 validation에 담긴다. */
export async function saveProductionRevision(
  id: string,
  spec: Record<string, unknown>,
  baseRevNo: number,
  baseUpdatedAt: string,
  lang: RevisionLang = "ko",
): Promise<Revision> {
  const res = await apiFetch<{ revision: Revision }>(`${jobPath(id)}/revision`, {
    method: "PUT",
    query: { lang: lang === "ja" ? "ja" : undefined },
    body: { spec, base_rev_no: baseRevNo, base_updated_at: baseUpdatedAt },
  });
  return res.revision;
}

/** A-13 편집안 승인(서버 재검증). */
export async function approveProductionRevision(id: string, revNo: number, lang: RevisionLang = "ko") {
  const res = await apiFetch<{ revision: { id: string; rev_no: number; approved_at: string; approved_by: string | null } }>(
    `${jobPath(id)}/revision/approve`,
    { method: "POST", body: lang === "ja" ? { rev_no: revNo, lang } : { rev_no: revNo } },
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

export type RenderRun = { id: string; status: "queued" | "running" | "done" | "failed"; attempt: number };

/** A-15 렌더 요청(승인본·언어). 같은 키 재요청은 200 + 기존 run. */
export async function requestProductionRender(id: string, revisionId: string, lang: RevisionLang, idempotencyKey: string): Promise<RenderRun> {
  const res = await apiFetch<{ render_run: RenderRun }>(`${jobPath(id)}/render-runs`, {
    method: "POST",
    body: { revision_id: revisionId, lang },
    idempotencyKey,
  });
  return res.render_run;
}

/** A-16 실패 run 재시도(새 run, attempt+1). */
export async function retryProductionRender(id: string, runId: string): Promise<RenderRun> {
  const res = await apiFetch<{ render_run: RenderRun }>(`${jobPath(id)}/render-runs/${encodeURIComponent(runId)}/retry`, { method: "POST" });
  return res.render_run;
}

/** 쇼핑 AI 대본 1안(A-14). 문장 맨 앞 `[확인 필요] `는 서버가 붙인다. */
export type AiScriptVariant = { hook_type: string; sentences: string[]; char_count: number };

export type AiDraftResult = {
  revision: Revision;
  ai_draft_count: number;
  previous_rev_no: number | null;
  replay: boolean;
  variants?: AiScriptVariant[] | null;
  facts_to_check?: string[] | null;
};

/** A-14는 Claude 호출(재시도 1회 포함)을 기다리므로 기본 10초보다 길게 둔다(API 설정 타임아웃 90초 × 2 + 여유). */
export const AI_DRAFT_TIMEOUT_MS = 200_000;

/** A-14 AI 초안(새 리비전, origin=ai_draft, 기존 편집 보존). 같은 키 재요청은 기존 결과. 자동 승인 없음. */
export async function requestProductionAiDraft(id: string, idempotencyKey: string): Promise<AiDraftResult> {
  return apiFetch<AiDraftResult>(`${jobPath(id)}/ai-draft`, { method: "POST", idempotencyKey, timeoutMs: AI_DRAFT_TIMEOUT_MS });
}

export type TranslateResult = { revision: Revision; translate_count: number; replay: boolean };

/** A-20 일본어판 번역 초안(Claude 호출 포함). 같은 키 재요청은 기존 결과(replay). ko 텍스트만 외부로 나간다. */
export async function requestProductionTranslate(id: string, revisionId: string, idempotencyKey: string): Promise<TranslateResult> {
  return apiFetch<TranslateResult>(`${jobPath(id)}/translate`, {
    method: "POST",
    body: { revision_id: revisionId, target_lang: "ja" },
    idempotencyKey,
    timeoutMs: AI_DRAFT_TIMEOUT_MS,
  });
}

/** A-10 자산 삭제(task-044 P9). 204. 현재 리비전이 참조하는 사진·BGM·녹음과 준비 시작 뒤 원본은 409. */
export async function deleteProductionAsset(id: string, assetId: string): Promise<void> {
  await apiFetch<undefined>(`${jobPath(id)}/assets/${encodeURIComponent(assetId)}`, { method: "DELETE" });
}

export type PublishText = { caption: string; pinned_comment: string; recommended_time: string };
export type PublishTextResult = { text: PublishText; render_run_id: string; lang: "ko" | "ja" };

/** A-21 게시 문구(쇼핑만). 제휴 링크가 들어 있으므로 저장·로그하지 않는다(task-044 P8). */
export function getProductionPublishText(id: string, lang: "ko" | "ja", renderRunId?: string): Promise<PublishTextResult> {
  return apiFetch<PublishTextResult>(`${jobPath(id)}/publish-text`, { query: { lang, render_run_id: renderRunId } });
}

/** A-22 AI 영상 생성 run(견적→확인→진행→결과). 프롬프트는 화면 표시용이며 로그에 남기지 않는다. */
export type GenerationStatus = "quoted" | "confirmed" | "running" | "finalizing" | "done" | "failed" | "unknown";
export type GenerationRun = {
  id: string;
  job_id: string;
  source_asset_id: string | null;
  result_asset_id: string | null;
  cut_ref: string | null;
  prompt: string;
  duration_sec: number;
  est_cost_krw: number;
  actual_cost_krw: number | null;
  status: GenerationStatus;
  error_code: string | null;
  created_at: string;
  confirmed_at: string | null;
  finished_at: string | null;
};
export type GenerationBudget = { monthly_left_krw: number; job_left_krw: number };
export type GenerationEnvelope = { run: GenerationRun; budget: GenerationBudget | null; replay: boolean };
export type GenerationReview = { physics: boolean; angle: boolean; compare: boolean };
export type GenerationReviewResult = { run: GenerationRun; reviewed: boolean; review_checks: Record<string, unknown> };

const genPath = (id: string) => `${jobPath(id)}/generation-runs`;
/** 제출·진행 확인은 플랫폼·저장소 왕복이 있어 기본 10초보다 길게 둔다. */
const GEN_TIMEOUT_MS = 60_000;

/** A-22 목록(부작용 없음). */
export async function listGenerationRuns(id: string): Promise<{ items: GenerationRun[] }> {
  return apiFetch<{ items: GenerationRun[] }>(genPath(id));
}

/** A-22 견적(구성원). 과금 없음. 같은 키 재요청은 기존 run(replay). */
export async function quoteGenerationRun(id: string, body: { source_asset_id: string; prompt: string; duration_sec: number }, idempotencyKey: string): Promise<GenerationEnvelope> {
  return apiFetch<GenerationEnvelope>(genPath(id), { method: "POST", body, idempotencyKey });
}

/** A-22 확인(owner만, 여기서 과금 계상 후 플랫폼 제출). */
export async function confirmGenerationRun(id: string, runId: string): Promise<GenerationEnvelope> {
  return apiFetch<GenerationEnvelope>(`${genPath(id)}/${encodeURIComponent(runId)}/confirm`, { method: "POST", timeoutMs: GEN_TIMEOUT_MS });
}

/** A-22 진행 확인(수동 버튼에서만 호출한다). */
export async function refreshGenerationRun(id: string, runId: string): Promise<GenerationEnvelope> {
  return apiFetch<GenerationEnvelope>(`${genPath(id)}/${encodeURIComponent(runId)}/refresh`, { method: "POST", timeoutMs: GEN_TIMEOUT_MS });
}

/** A-22 검수(3항목 모두 true여야 reviewed). */
export async function reviewGenerationRun(id: string, runId: string, checks: GenerationReview): Promise<GenerationReviewResult> {
  return apiFetch<GenerationReviewResult>(`${genPath(id)}/${encodeURIComponent(runId)}/review`, { method: "POST", body: checks });
}
