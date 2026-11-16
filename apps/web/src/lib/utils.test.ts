import { describe, expect, it } from "vitest";
import { cn } from "./utils";

describe("cn", () => {
  it("클래스를 병합하고 충돌을 해소한다", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
  });
});
