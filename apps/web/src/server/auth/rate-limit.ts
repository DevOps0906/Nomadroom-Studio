// 로그인 시도 제한: IP별 5분 10회, 메모리 고정 창(단일 인스턴스 가정).
export const RATE_LIMIT = { max: 10, windowMs: 5 * 60 * 1000 } as const;
const MAX_BUCKETS = 10_000;

type Bucket = { start: number; count: number };

type Options = { max: number; windowMs: number; maxBuckets?: number };

export function createRateLimiter({ max, windowMs, maxBuckets = MAX_BUCKETS }: Options = RATE_LIMIT) {
  // Map은 삽입 순서를 지키므로 첫 키가 가장 오래 전에 창을 시작한 버킷이다.
  const buckets = new Map<string, Bucket>();
  return {
    /** 시도 1회를 기록하고, 허용되면 true. */
    hit(key: string, now: number = Date.now()): boolean {
      const bucket = buckets.get(key);
      if (!bucket || now - bucket.start >= windowMs) {
        buckets.delete(key);
        // 상한을 넘으면 가장 오래된 버킷부터 제거(O(1)).
        if (buckets.size >= maxBuckets) buckets.delete(buckets.keys().next().value as string);
        buckets.set(key, { start: now, count: 1 });
        return true;
      }
      bucket.count += 1;
      return bucket.count <= max;
    },
    get size() {
      return buckets.size;
    },
  };
}

/** x-forwarded-for 첫 값(신뢰 프록시 뒤 가정). 없으면 'unknown' 한 버킷. */
export function clientIp(headers: Headers): string {
  const first = headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return first || "unknown";
}

export const loginLimiter = createRateLimiter();
