import { redirect } from "next/navigation";
import { DashboardForbidden } from "@/components/dashboard/dashboard-view";
import { RetryButton } from "@/components/dashboard/retry-button";
import type { Profile } from "@/components/profiles/conditions";
import { ProfileList } from "@/components/profiles/profile-list";
import { ApiError, SESSION_EXPIRED_PATH, classifyApiError } from "@/server/api/client";
import { listProfiles } from "@/server/api/profiles";
import { saveConditions, saveSelection } from "./actions";

export const metadata = { title: "프로필 조건 설정 · Nomadroom Studio" };

/** MON-D1 프로필 조건 설정(A-03). 읽기는 서버 컴포넌트, 쓰기는 Server Action. */
export default async function ProfilesPage() {
  let profiles: Profile[] | null = null;
  let message = "";
  try {
    profiles = (await listProfiles()).items;
  } catch (e) {
    const kind = classifyApiError(e);
    // /login으로 바로 보내면 Supabase 세션이 살아 있어 루프가 생긴다. 쿠키를 지우는 경로를 거친다.
    if (kind === "login") redirect(SESSION_EXPIRED_PATH);
    if (kind === "forbidden") return <DashboardForbidden />;
    message = e instanceof ApiError ? e.message : "잠시 후 다시 시도하세요.";
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4 tablet:gap-5">
      <div>
        <h1 className="text-h1 font-bold">프로필 조건 설정</h1>
        <p className="mt-1 text-body text-text-muted">
          프로필별 수집 조건을 저장하고, 검증할 프로필을 최대 3개까지 고르세요.
        </p>
      </div>
      {profiles ? (
        <ProfileList profiles={profiles} saveConditions={saveConditions} saveSelection={saveSelection} />
      ) : (
        <div role="alert" className="flex flex-col items-start gap-3 rounded-panel border border-border bg-surface p-5">
          <p className="text-body text-danger">프로필을 불러오지 못했습니다. {message}</p>
          <RetryButton />
        </div>
      )}
    </div>
  );
}
