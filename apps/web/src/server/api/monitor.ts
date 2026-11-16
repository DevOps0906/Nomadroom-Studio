import "server-only";

import type { JobProfileRun, JobStatus } from "@/components/monitoring/job";
import { toApiQuery, type CandidateQuery, type CandidateStatus } from "@/components/monitoring/query";
import { apiFetch } from "./client";

// MON-01 API 호출(A-04 후보 · A-05 수집 작업 · A-07 기록 검증). 계약: docs/04_API.md#A-04·A-05·A-07.

export const VERIFY_TIMEOUT_MS = 60_000;

export type Counts = { total: number; producible: number; pending: number; excluded: number; used: number };
export type Observation = { observed_at: string; view_count: number };

export type CandidateItem = {
  id: string;
  thumbnail_url: string | null;
  status: Exclude<CandidateStatus, "all">;
  genre: string | null;
  title: string;
  format: "short" | "long" | null;
  profile_names: string[];
  license_cc: boolean | null;
  prev: Observation | null;
  curr: Observation | null;
  growth_pct: number | null;
  period_days: number | null;
  next_observation_at: string | null;
  used: boolean;
};

export type CandidateList = { counts: Counts; categories: string[]; items: CandidateItem[]; updated_at: string };

/** A-05 POST·retry·stop 응답의 job. */
export type CollectJob = {
  id: string;
  status: JobStatus;
  error: string | null;
  stop_requested: boolean;
  retry_count: number;
  profiles: JobProfileRun[];
};

/** A-05 GET /{id}·/active 응답의 job. */
export type CollectJobDetail = CollectJob & {
  /** 종료 상태일 때만 집계, 진행 중이면 null. */
  result: { candidates: number; producible: number; pending: number } | null;
  worker_last_seen_at: string | null;
  worker_online: boolean;
};

export type VerifyRun = {
  job: { id: string; kind: "verify"; status: JobStatus };
  checked: number | null;
  skipped_recent: number | null;
  failed: number | null;
  counts: Counts | null;
};

const jobPath = (id: string) => `/v1/collect-jobs/${encodeURIComponent(id)}`;

export function listCandidates(query: CandidateQuery): Promise<CandidateList> {
  return apiFetch<CandidateList>("/v1/candidates", { query: toApiQuery(query) });
}

/** 이 워크스페이스의 활성 collect job. 없으면(204) null. */
export async function getActiveCollectJob(): Promise<CollectJobDetail | null> {
  const res = await apiFetch<{ job: CollectJobDetail } | undefined>("/v1/collect-jobs/active");
  return res?.job ?? null;
}

export async function getCollectJob(id: string): Promise<CollectJobDetail> {
  return (await apiFetch<{ job: CollectJobDetail }>(jobPath(id))).job;
}

export async function createCollectJob(key: string, profileIds: string[]): Promise<CollectJob> {
  const res = await apiFetch<{ job: CollectJob }>("/v1/collect-jobs", {
    method: "POST",
    idempotencyKey: key,
    body: { profile_ids: profileIds },
  });
  return res.job;
}

export async function retryCollectJob(id: string): Promise<CollectJob> {
  return (await apiFetch<{ job: CollectJob }>(`${jobPath(id)}/retry`, { method: "POST" })).job;
}

export async function stopCollectJob(id: string): Promise<CollectJob> {
  return (await apiFetch<{ job: CollectJob }>(`${jobPath(id)}/stop`, { method: "POST" })).job;
}

export function runVerify(key: string, profileIds: string[]): Promise<VerifyRun> {
  return apiFetch<VerifyRun>("/v1/verify-runs", {
    method: "POST",
    idempotencyKey: key,
    body: { profile_ids: profileIds },
    timeoutMs: VERIFY_TIMEOUT_MS,
  });
}
