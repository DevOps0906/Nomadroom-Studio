// PROD-01S AI 영상 생성의 순수 규칙(DOM 없이 테스트). 근거: tasks/task-057.md.

export const REVIEW_ITEMS = [
  { key: "physics", label: "물리 오류가 없음" },
  { key: "angle", label: "불가능한 앵글이 없음" },
  { key: "compare", label: "실제 사진과 대조함" },
] as const;
export type ReviewKey = (typeof REVIEW_ITEMS)[number]["key"];
export type ReviewState = Record<ReviewKey, boolean>;
export const NO_CHECKS: ReviewState = { physics: false, angle: false, compare: false };
export const allChecked = (c: ReviewState) => REVIEW_ITEMS.every((i) => c[i.key]);

/** 검수 저장 가드: 3항목이 모두 체크됐고 다른 요청이 없을 때만. */
export const canSubmitReview = (c: ReviewState, busy: boolean) => !busy && allChecked(c);

/** 견적 요청의 의도 지문. 같은 입력이면 같은 키(재시도), 입력이 바뀌면 새 키. */
export const quoteFingerprint = (b: { source_asset_id: string; prompt: string; duration_sec: number }) => JSON.stringify([b.source_asset_id, b.prompt, b.duration_sec]);

/** 실패 뒤 목록을 다시 읽어 실제 상태(unknown 포함)를 반영할지. 확인은 항상, 견적은 응답이 불명확한(5xx·네트워크) 때만. */
export function shouldReloadRuns(kind: "quote" | "confirm", r: { ok: boolean; keepKey?: boolean }): boolean {
  return !r.ok && (kind === "confirm" || r.keepKey === true);
}

/** 동시에 하나만 실행한다. 실행 중 호출은 null(무시) — 이중 클릭이 과금·제출을 두 번 부르지 않게 한다. */
export function createSingleFlight() {
  let busy = false;
  return {
    get busy() {
      return busy;
    },
    async run<T>(fn: () => Promise<T>): Promise<T | null> {
      if (busy) return null;
      busy = true;
      try {
        return await fn();
      } finally {
        busy = false;
      }
    },
  };
}
