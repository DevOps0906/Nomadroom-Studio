import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { AuthCard } from "@/components/auth/auth-ui";
import { getRecoverySession } from "@/server/auth/recovery-session";
import { ResetForm } from "./reset-form";

export const metadata: Metadata = { title: "비밀번호 재설정 · Nomadroom Studio" };

// recovery 링크 직후 세션만 허용. 일반 로그인 세션이면 "/"로.
export default async function ResetPasswordPage() {
  if (!(await getRecoverySession())) redirect("/");
  return (
    <AuthCard title="비밀번호 재설정" description="새 비밀번호를 입력하세요.">
      <ResetForm />
    </AuthCard>
  );
}
