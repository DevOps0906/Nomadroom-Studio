// MON-01 문구(순수). 근거: tasks/task-013.md#구현 결정(오류 문구), docs/04_API.md W-02(detail 코드).
import type { ChromeState } from "./job";

export const QUOTA_MESSAGE = "오늘 YouTube 조회 한도에 도달했습니다. 내일 다시 시도하세요";
export const RATE_LIMITED_MESSAGE = "잠시 후 다시 시도하세요";
export const VERIFY_TIMEOUT_MESSAGE = "검증이 계속 진행 중일 수 있습니다. 잠시 뒤 새로고침하세요";
export const WORKER_OFFLINE_MESSAGE =
  "워커 오프라인 — 로컬 워커가 연결되지 않아 수집이 대기 중입니다. 워커를 켜거나 수집을 중지하세요.";
export const UNKNOWN_CAUSE = "알 수 없는 원인";
/** 검색 수집일 때 vidIQ 자리 안내(task-009 준비 중). */
export const VIDIQ_PENDING_MESSAGE = "vidIQ 수집: 준비 중";
export const FAILED_MESSAGE = "요청을 처리하지 못했습니다. 다시 시도하세요.";

export const CHROME_STATE_LABEL: Record<ChromeState, string> = {
  ready: "준비 완료",
  resize_needed: "창 확대 필요",
  login_needed: "로그인 만료",
  error: "준비 실패",
};

const CHROME_DETAIL_LABEL: Record<string, string> = {
  window_small: "Chrome 창이 작습니다. 창을 확대하세요",
  login_required: "vidIQ·YouTube 로그인이 만료되었습니다. 다시 로그인하세요",
  profile_locked: "Chrome 프로필이 다른 창에서 사용 중입니다",
  network: "네트워크 오류",
  unknown: UNKNOWN_CAUSE,
};

const JOB_ERROR_LABEL: Record<string, string> = {
  chrome_failed: "Chrome 준비 실패",
  vidiq_changed: "vidIQ 화면이 바뀌어 읽지 못했습니다",
  network: "네트워크 오류",
  stopped_by_user: "사용자가 수집을 중지했습니다",
  worker_offline: "워커 오프라인 — 하트비트가 3분 넘게 없어 실패 처리되었습니다",
  timeout: "시간 초과",
  upstream_error: "YouTube 검색 응답을 받지 못했습니다",
  quota_exceeded: "오늘 YouTube 조회 한도에 도달해 일부 프로필을 수집하지 못했습니다",
  unknown: UNKNOWN_CAUSE,
};

/** Chrome detail 코드 → 한국어. 모르는 값(비신뢰)은 그대로 보여 주지 않는다. */
export function chromeDetailLabel(detail: string | null): string | null {
  if (detail === null) return null;
  return CHROME_DETAIL_LABEL[detail] ?? UNKNOWN_CAUSE;
}

export function jobErrorLabel(error: string | null): string | null {
  if (error === null) return null;
  return JOB_ERROR_LABEL[error] ?? UNKNOWN_CAUSE;
}

/** 실행류 Server Action 실패 결과. keepKey면 같은 Idempotency-Key로 다시 시도한다. */
export type ActionFailure = { ok: false; message: string; keepKey: boolean; unauthenticated?: boolean };

/**
 * API 오류 → 화면 문구. 429는 code별 고정 문구, API message는 400·409만 쓰고 나머지는 고정 문구.
 * 응답을 못 받은 경우(status 0)·5xx는 키를 유지한다(같은 키 재요청은 기존 job 반환).
 */
export function toActionFailure(
  err: { status: number; code: string; message: string },
  opts: { verify?: boolean } = {},
): ActionFailure {
  if (err.status === 0 && err.code === "TIMEOUT" && opts.verify) {
    return { ok: false, message: VERIFY_TIMEOUT_MESSAGE, keepKey: true };
  }
  if (err.status === 429) {
    return { ok: false, message: err.code === "QUOTA_EXCEEDED" ? QUOTA_MESSAGE : RATE_LIMITED_MESSAGE, keepKey: false };
  }
  if (err.status === 400 || err.status === 409) return { ok: false, message: err.message || FAILED_MESSAGE, keepKey: false };
  return { ok: false, message: FAILED_MESSAGE, keepKey: err.status === 0 || err.status >= 500 };
}
