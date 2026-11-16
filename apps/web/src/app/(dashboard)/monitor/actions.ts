"use server";

import { redirect } from "next/navigation";
import { ApiError, SESSION_EXPIRED_PATH, classifyApiError } from "@/server/api/client";
import {
  createCollectJob,
  getCollectJob,
  retryCollectJob,
  runVerify,
  stopCollectJob,
  type CollectJob,
} from "@/server/api/monitor";
import { pickJob, type JobView } from "@/components/monitoring/job";
import { FAILED_MESSAGE, toActionFailure, type ActionFailure } from "@/components/monitoring/messages";
import { isUuid } from "@/components/monitoring/query";
import { MAX_SELECTED } from "@/components/profiles/conditions";

// MON-01 실행류(A-05 생성·재시도·중지, A-07 기록 검증). Server Action이라 Next의 Origin 검사를 거친다.
// 클라이언트 값은 신뢰하지 않는다: 키·id 형식을 다시 검증한다. 근거: tasks/task-013.md#구현 결정.

export type JobActionResult = { ok: true; job: JobView } | ActionFailure;
export type VerifyActionResult =
  | { ok: true; checked: number; skipped: number; failed: number }
  | ActionFailure;

const INVALID: ActionFailure = { ok: false, message: FAILED_MESSAGE, keepKey: false };

function profileIds(raw: unknown): string[] | null {
  if (!Array.isArray(raw) || raw.length === 0 || !raw.every(isUuid)) return null;
  const unique = [...new Set(raw as string[])];
  return unique.length <= MAX_SELECTED ? unique : null;
}

function fail(e: unknown, verify = false): ActionFailure {
  // API만 401이면 /login 대신 세션 정리 경로로(루프 방지).
  if (classifyApiError(e) === "login") redirect(SESSION_EXPIRED_PATH);
  if (e instanceof ApiError) return toActionFailure(e, { verify });
  return { ok: false, message: FAILED_MESSAGE, keepKey: true };
}

/** 실행 응답(job) 뒤 상세(GET)로 워커 상태까지 채운다. 상세를 못 받으면 실행 응답으로 대신한다(모양이 틀리면 null). */
async function withDetail(job: CollectJob): Promise<JobView | null> {
  try {
    const detail = pickJob(await getCollectJob(job.id));
    if (detail) return detail;
  } catch (e) {
    if (classifyApiError(e) === "login") redirect(SESSION_EXPIRED_PATH);
  }
  // 워커 상태를 모르면 오프라인 안내를 띄우지 않는다(다음 폴링이 바로잡는다).
  const base = pickJob(job);
  return base ? { ...base, result: null, worker_online: true } : null;
}

async function jobResult(job: CollectJob): Promise<JobActionResult> {
  const view = await withDetail(job);
  return view ? { ok: true, job: view } : INVALID;
}

export async function startCollect(key: unknown, ids: unknown): Promise<JobActionResult> {
  const targets = profileIds(ids);
  if (!isUuid(key) || !targets) return INVALID;
  let job: CollectJob;
  try {
    job = await createCollectJob(key, targets);
  } catch (e) {
    return fail(e);
  }
  return jobResult(job);
}

export async function retryCollect(jobId: unknown): Promise<JobActionResult> {
  if (!isUuid(jobId)) return INVALID;
  let job: CollectJob;
  try {
    job = await retryCollectJob(jobId);
  } catch (e) {
    return fail(e);
  }
  return jobResult(job);
}

export async function stopCollect(jobId: unknown): Promise<JobActionResult> {
  if (!isUuid(jobId)) return INVALID;
  let job: CollectJob;
  try {
    job = await stopCollectJob(jobId);
  } catch (e) {
    return fail(e);
  }
  return jobResult(job);
}

export async function verifyRecords(key: unknown, ids: unknown): Promise<VerifyActionResult> {
  const targets = profileIds(ids);
  if (!isUuid(key) || !targets) return INVALID;
  try {
    const res = await runVerify(key, targets);
    return { ok: true, checked: res.checked ?? 0, skipped: res.skipped_recent ?? 0, failed: res.failed ?? 0 };
  } catch (e) {
    return fail(e, true);
  }
}
