import type { ProductionJobDetail } from "@/server/api/production";

// PROD-03 화면 판단(순수). 서버가 정본이고 여기는 버튼 노출·문구만 정한다. 근거: docs/03_SCREENS_UX.md PROD-03.

/** 편집안으로 돌아가 고쳐야 하는 사유(재시도 불가, A-16 409). */
export const EDIT_FIRST_CODES = ["hook_too_long", "text_too_long", "tts_failed"] as const;

export const REASON_TEXT: Record<string, string> = {
  hook_too_long: "훅 음성이 허용 길이보다 깁니다. 훅 문구를 줄이거나 더 짧은 음성으로 바꾼 뒤 다시 승인하세요.",
  text_too_long: "자막이 한 줄에 들어가기에 너무 깁니다. 자막 문구를 줄인 뒤 다시 승인하세요.",
  tts_failed: "TTS 훅 음성을 만들지 못했습니다(워커 TTS 꺼짐·음성 설정 오류·연결 실패). 편집안에서 첨부 음성으로 바꾼 뒤 다시 승인하세요.",
  worker_offline: "제작 워커가 응답하지 않아 중단되었습니다. 워커를 켠 뒤 재시도하세요.",
};

export const RUN_STAGE_LABEL: Record<string, string> = {
  queued: "대기",
  audio: "음성",
  render: "렌더",
  inspect: "검수 준비",
};

export function stageLabel(stage: string | null): string {
  return stage ? (RUN_STAGE_LABEL[stage] ?? stage) : "";
}

export const STEPS = [
  { key: "audio", label: "음성" },
  { key: "render", label: "렌더" },
  { key: "inspect", label: "검수" },
] as const;

export type StepState = "done" | "active" | "todo" | "failed";
type StepKey = (typeof STEPS)[number]["key"];

export function stepStates(detail: Pick<ProductionJobDetail, "job" | "latest_run">): Record<StepKey, StepState> {
  const { job, latest_run: run } = detail;
  if (job.status === "inspect") return { audio: "done", render: "done", inspect: "active" };
  if (job.status === "done") return { audio: "done", render: "done", inspect: "done" };
  const out: Record<StepKey, StepState> = { audio: "todo", render: "todo", inspect: "todo" };
  const failed = job.status === "failed";
  if (job.status !== "rendering" && !failed) return out;
  const stage = failed ? (run?.error_stage ?? job.failed_stage) : run?.progress_stage;
  const cur = stage === "render" ? 1 : 0;
  STEPS.forEach((s, i) => {
    out[s.key] = i < cur ? "done" : i === cur ? (failed ? "failed" : "active") : "todo";
  });
  return out;
}

export type RunView = {
  /** 승인된 리비전이 있고 job이 review일 때 렌더 요청 가능 */
  canRequest: boolean;
  rendering: boolean;
  failed: boolean;
  /** 실패 run이 있고 편집 사유가 아닐 때만 재시도 */
  canRetry: boolean;
  editFirst: boolean;
  inspect: boolean;
  done: boolean;
  /** 렌더 대기·진행 중 워커 오프라인 */
  workerOffline: boolean;
};

export function viewOf(d: ProductionJobDetail): RunView {
  const { job, latest_run: run, current_revision: rev } = d;
  const code = job.status === "failed" ? (run?.error_code ?? job.error_code) : null;
  const failed = job.status === "failed" && job.failed_stage !== "prepare";
  const editFirst = failed && !!code && (EDIT_FIRST_CODES as readonly string[]).includes(code);
  const rendering = job.status === "rendering";
  return {
    canRequest: job.status === "review" && !!rev.ko?.approved_at,
    rendering,
    failed,
    canRetry: failed && !editFirst && run?.status === "failed",
    editFirst,
    inspect: job.status === "inspect",
    done: job.status === "done",
    workerOffline: rendering && !d.worker_online,
  };
}

/** 가장 최근 ready 산출물(자산은 생성 순). */
export function latestAsset(assets: ProductionJobDetail["assets"], kind: "output_mp4" | "report"): string | null {
  const ready = assets.filter((a) => a.kind === kind && a.status === "ready");
  return ready.length ? ready[ready.length - 1].id : null;
}
