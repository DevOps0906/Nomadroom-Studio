import { describe, expect, it } from "vitest";
import { clientIp, createRateLimiter } from "./rate-limit";

describe("createRateLimiter", () => {
  it("5분에 10회까지 허용하고 11회째 막는다, 창이 지나면 다시 허용", () => {
    const limiter = createRateLimiter();
    const t0 = 1_000_000;
    for (let i = 0; i < 10; i++) expect(limiter.hit("1.1.1.1", t0)).toBe(true);
    expect(limiter.hit("1.1.1.1", t0 + 1000)).toBe(false);
    expect(limiter.hit("2.2.2.2", t0 + 1000)).toBe(true);
    expect(limiter.hit("1.1.1.1", t0 + 5 * 60 * 1000)).toBe(true);
  });
});

describe("버킷 상한", () => {
  it("상한을 넘으면 가장 오래된 버킷부터 제거한다", () => {
    const limiter = createRateLimiter({ max: 1, windowMs: 60_000, maxBuckets: 3 });
    const t0 = 1_000_000;
    for (const ip of ["a", "b", "c"]) expect(limiter.hit(ip, t0)).toBe(true);
    expect(limiter.hit("b", t0)).toBe(false);
    expect(limiter.hit("d", t0 + 1)).toBe(true);
    expect(limiter.size).toBe(3);
    // a는 제거되어 새 버킷으로 다시 허용, b·c·d는 남아 있어 차단
    expect(limiter.hit("a", t0 + 2)).toBe(true);
    expect(limiter.size).toBe(3);
    expect(limiter.hit("c", t0 + 3)).toBe(false);
    expect(limiter.hit("d", t0 + 3)).toBe(false);
  });

  it("많은 키가 들어와도 상한을 넘지 않는다", () => {
    const limiter = createRateLimiter({ max: 10, windowMs: 60_000, maxBuckets: 100 });
    for (let i = 0; i < 1000; i++) limiter.hit(`ip-${i}`, 1000 + i);
    expect(limiter.size).toBe(100);
  });
});

describe("clientIp", () => {
  it("x-forwarded-for 첫 값, 없으면 unknown", () => {
    expect(clientIp(new Headers({ "x-forwarded-for": "9.9.9.9, 10.0.0.1" }))).toBe("9.9.9.9");
    expect(clientIp(new Headers())).toBe("unknown");
  });
});
