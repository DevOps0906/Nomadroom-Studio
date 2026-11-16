import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

const { summary, redirect } = vi.hoisted(() => ({
  summary: vi.fn(),
  redirect: vi.fn((to: string) => {
    throw new Error(`REDIRECT:${to}`);
  }),
}));
vi.mock("server-only", () => ({}));
vi.mock("next/navigation", () => ({ redirect, useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: vi.fn() }));
vi.mock("@/server/api/dashboard", () => ({ getDashboardSummary: summary }));

const { ApiError, SESSION_EXPIRED_PATH } = await import("@/server/api/client");
const { DashboardContent } = await import("./dashboard-content");

const render = async () => renderToStaticMarkup(await DashboardContent({ period: "7d" }));

describe("DashboardContent", () => {
  beforeEach(() => {
    summary.mockReset();
    redirect.mockClear();
  });

  it("401이면 /login이 아니라 세션 쿠키를 지우는 경로로 보낸다(루프 방지)", async () => {
    summary.mockRejectedValue(new ApiError(401, "UNAUTHENTICATED", "m"));
    await expect(render()).rejects.toThrow(`REDIRECT:${SESSION_EXPIRED_PATH}`);
    expect(redirect).toHaveBeenCalledWith(SESSION_EXPIRED_PATH);
    expect(redirect).not.toHaveBeenCalledWith("/login");
  });

  it("403 FORBIDDEN이면 접근 권한 없음 안내", async () => {
    summary.mockRejectedValue(new ApiError(403, "FORBIDDEN", "m"));
    const html = await render();
    expect(html).toContain("접근 권한 없음");
    expect(redirect).not.toHaveBeenCalled();
  });

  it("403이지만 FORBIDDEN이 아니면 오류 상태(메시지 표시)", async () => {
    summary.mockRejectedValue(new ApiError(403, "OTHER", "다른 거부"));
    const html = await render();
    expect(html).toContain("대시보드를 불러오지 못했습니다");
    expect(html).toContain("다른 거부");
  });
});
