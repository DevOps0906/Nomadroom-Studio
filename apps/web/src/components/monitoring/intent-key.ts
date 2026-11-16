// "실행 의도" 단위 Idempotency-Key(순수). 근거: tasks/task-013.md#구현 결정.
// 요청 중·타임아웃 뒤 재시도는 같은 키, 성공·확정 오류(4xx) 뒤에는 새 키.
// 키는 요청 본문 지문과 함께 저장한다: 지문이 바뀌면(다른 프로필 조합) 새 키.

export type IntentKey = {
  /** 이 지문의 의도 키. 저장된 지문과 다르면 새로 만든다. */
  current(fingerprint: string): string;
  /** 요청 결과 반영: keepKey가 아니면 다음 요청은 새 키. */
  settle(keepKey: boolean): void;
};

/** profile_ids 지문: 중복 제거 + 정렬. */
export function idsFingerprint(ids: string[]): string {
  return [...new Set(ids.map((x) => x.toLowerCase()))].sort().join(",");
}

export function createIntentKey(newKey: () => string = () => crypto.randomUUID()): IntentKey {
  let saved: { key: string; fingerprint: string } | null = null;
  return {
    current(fingerprint) {
      if (!saved || saved.fingerprint !== fingerprint) saved = { key: newKey(), fingerprint };
      return saved.key;
    },
    settle(keepKey) {
      if (!keepKey) saved = null;
    },
  };
}

/** 의도 단위 실행기: 요청 중 중복 클릭은 무시(null), 결과에 따라 키를 유지·교체한다. 예외(전송 실패)면 키 유지. */
export function createIntentRunner(newKey?: () => string) {
  const key = createIntentKey(newKey);
  let busy = false;
  return {
    get busy() {
      return busy;
    },
    async run<R extends { ok: boolean; keepKey?: boolean }>(
      fingerprint: string,
      send: (key: string) => Promise<R>,
    ): Promise<R | null> {
      if (busy) return null;
      busy = true;
      try {
        const res = await send(key.current(fingerprint));
        key.settle(!res.ok && res.keepKey === true);
        return res;
      } finally {
        busy = false;
      }
    },
  };
}
