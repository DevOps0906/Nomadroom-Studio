import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

const { default: DashboardErrorBoundary } = await import("../error");

describe("(dashboard)/error.tsx", () => {
  it("role=alert와 다시 시도 버튼, 오류 내용은 노출하지 않는다", () => {
    const html = renderToStaticMarkup(<DashboardErrorBoundary error={new Error("secret stack")} reset={() => {}} />);
    expect(html).toContain('role="alert"');
    expect(html).toMatch(/<button[^>]*type="button"[^>]*>다시 시도<\/button>/);
    expect(html).not.toContain("secret stack");
  });
});
