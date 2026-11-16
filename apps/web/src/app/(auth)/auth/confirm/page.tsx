import type { Metadata } from "next";
import { AuthCard, AuthLink, SubmitButton } from "@/components/auth/auth-ui";
import { confirmRecovery } from "./actions";

export const metadata: Metadata = { title: "비밀번호 재설정 · Nomadroom Studio" };

type Search = Promise<{ token_hash?: string | string[]; type?: string | string[] }>;

// GET은 확인 화면만 보여 준다. 토큰 검증은 버튼(POST, Server Action)에서 한다.
export default async function ConfirmPage({ searchParams }: { searchParams: Search }) {
  const { token_hash: tokenHash, type } = await searchParams;
  if (typeof tokenHash !== "string" || type !== "recovery") {
    return (
      <AuthCard title="비밀번호 재설정" description="재설정 링크가 만료되었거나 올바르지 않습니다.">
        <AuthLink href="/forgot-password">비밀번호 찾기 다시 요청</AuthLink>
      </AuthCard>
    );
  }
  return (
    <AuthCard title="비밀번호 재설정" description="아래 버튼을 눌러 새 비밀번호 설정을 계속하세요.">
      <form action={confirmRecovery} className="grid gap-4">
        <input type="hidden" name="token_hash" value={tokenHash} />
        <input type="hidden" name="type" value="recovery" />
        <SubmitButton pending={false}>비밀번호 재설정 계속</SubmitButton>
      </form>
    </AuthCard>
  );
}
