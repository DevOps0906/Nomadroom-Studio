import { AuthCard } from "./auth-ui";
import { SignOutButton } from "./sign-out-button";

/** 로그인했지만 워크스페이스 소속이 없는 사용자 안내. */
export function NoWorkspace() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-bg px-4 py-10 text-text tablet:px-6">
      <AuthCard title="접근 권한 없음" description="워크스페이스 접근 권한이 없습니다. 관리자에게 문의하세요.">
        <SignOutButton className="w-full" />
      </AuthCard>
    </main>
  );
}
