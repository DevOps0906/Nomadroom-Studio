import { describe, expect, it } from "vitest";
import { safeNext } from "./safe-next";

const ORIGIN = "https://studio.example.com";

describe("safeNext", () => {
  it("같은 Origin 경로는 그대로 돌려준다", () => {
    expect(safeNext("/monitor", ORIGIN)).toBe("/monitor");
    expect(safeNext("/monitor?tab=a#x", ORIGIN)).toBe("/monitor?tab=a#x");
  });

  it("다시 디코드하지 않는다: 인코딩된 문자는 같은 Origin 경로의 일부로 남는다", () => {
    expect(safeNext("/%2Fevil.com", ORIGIN)).toBe("/%2Fevil.com");
    expect(safeNext("/%5Cevil.com", ORIGIN)).toBe("/%5Cevil.com");
    expect(safeNext("/%25252E//evil.com", ORIGIN)).toBe("/%25252E//evil.com");
    expect(safeNext("%2Fdashboard", ORIGIN)).toBe("/");
  });

  it.each([
    ["빈 값", ""],
    ["null", null],
    ["절대 URL", "https://evil.com"],
    ["상대 경로", "evil.com"],
    ["프로토콜 상대", "//x"],
    ["역슬래시", "/\\evil.com"],
    ["점 세그먼트 뒤 //", "/.//evil.com"],
    ["인코딩 점 세그먼트 뒤 //", "/%2E//evil.com"],
    ["소문자 인코딩 점", "/%2e//evil.com"],
    ["점점 세그먼트 뒤 //", "/a/..//evil.com"],
    ["점 세그먼트 뒤 역슬래시", "/./\\evil.com"],
    ["탭 문자", "/\t/x"],
    ["역슬래시 t", "/\\t/x"],
    ["줄바꿈", "/a\nb"],
    ["공백", "/a b"],
    ["javascript", "javascript:alert(1)"],
  ])("%s → /", (_name, raw) => {
    expect(safeNext(raw, ORIGIN)).toBe("/");
  });

  it.each([
    "/monitor?tab=a#x",
    "/.//evil.com",
    "/%2E//evil.com",
    "/%25252E//evil.com",
    "/%2525252E//evil.com",
    "/%2Fevil.com",
    "/a/../b?x=%20y#z",
    "/a?b=//evil.com",
    "//evil.com",
  ])("멱등: safeNext(safeNext(%s)) === safeNext(%s)", (raw) => {
    const once = safeNext(raw, ORIGIN);
    expect(safeNext(once, ORIGIN)).toBe(once);
    expect(new URL(once, ORIGIN).origin).toBe(ORIGIN);
  });
});
