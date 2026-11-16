import { beforeEach, describe, expect, it, vi } from "vitest";

const { redirect, listProfiles, updateProfile, setProfileSelection } = vi.hoisted(() => ({
  redirect: vi.fn((to: string) => {
    throw new Error(`REDIRECT:${to}`);
  }),
  listProfiles: vi.fn(),
  updateProfile: vi.fn(),
  setProfileSelection: vi.fn(),
}));
vi.mock("server-only", () => ({}));
vi.mock("next/navigation", () => ({ redirect, useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: vi.fn() }));
vi.mock("@/server/api/profiles", () => ({ listProfiles, updateProfile, setProfileSelection }));

const { ApiError, SESSION_EXPIRED_PATH } = await import("@/server/api/client");
const { default: ProfilesPage } = await import("./page");
const { saveConditions, saveSelection } = await import("./actions");

const ID = "00000000-0000-4000-8000-000000000001";
const TOKEN = "2026-11-17T01:02:03.123456+00:00";
const INPUT = {
  market: "KR",
  format: "all",
  category: "전체",
  min_views: "100",
  max_growth_pct: "5",
  keywords: "",
  cc_only: false,
  include_broadcast: true,
};
const unauth = () => new ApiError(401, "UNAUTHENTICATED", "로그인이 필요합니다.");

describe("MON-D1 401 → 세션 정리 경로", () => {
  beforeEach(() => {
    redirect.mockClear();
    listProfiles.mockReset();
    updateProfile.mockReset();
    setProfileSelection.mockReset();
  });

  it("목록 401 → SESSION_EXPIRED_PATH (/login 아님)", async () => {
    listProfiles.mockRejectedValue(unauth());
    await expect(ProfilesPage()).rejects.toThrow(`REDIRECT:${SESSION_EXPIRED_PATH}`);
    expect(redirect).toHaveBeenCalledWith(SESSION_EXPIRED_PATH);
    expect(redirect).not.toHaveBeenCalledWith("/login");
  });

  it("조건 저장 401 → SESSION_EXPIRED_PATH", async () => {
    updateProfile.mockRejectedValue(unauth());
    await expect(saveConditions(ID, TOKEN, INPUT)).rejects.toThrow(`REDIRECT:${SESSION_EXPIRED_PATH}`);
  });

  it("선택 저장 401 → SESSION_EXPIRED_PATH", async () => {
    setProfileSelection.mockRejectedValue(unauth());
    await expect(saveSelection([ID])).rejects.toThrow(`REDIRECT:${SESSION_EXPIRED_PATH}`);
  });

  it("조건 저장: 9필드 본문 전송, 409는 conflict", async () => {
    updateProfile.mockRejectedValue(new ApiError(409, "CONFLICT", "x", "updated_at"));
    const res = await saveConditions(ID, TOKEN, { ...INPUT, name: "해킹", selected: true });
    expect(res).toMatchObject({ ok: false, kind: "conflict" });
    const body = updateProfile.mock.calls[0][1];
    expect(Object.keys(body).sort()).toEqual(
      ["category", "cc_only", "format", "include_broadcast", "keywords", "market", "max_growth_pct", "min_views", "updated_at"],
    );
  });

  it("선택 4개는 서버 액션에서도 API 호출 없이 거부", async () => {
    const ids = [1, 2, 3, 4].map((n) => `00000000-0000-4000-8000-00000000000${n}`);
    const res = await saveSelection(ids);
    expect(res).toMatchObject({ ok: false, kind: "error" });
    expect(setProfileSelection).not.toHaveBeenCalled();
  });

  it("범위 초과는 API 호출 없이 필드 오류", async () => {
    const res = await saveConditions(ID, TOKEN, { ...INPUT, min_views: "-1" });
    expect(res).toMatchObject({ ok: false, kind: "field" });
    expect(updateProfile).not.toHaveBeenCalled();
  });
});
