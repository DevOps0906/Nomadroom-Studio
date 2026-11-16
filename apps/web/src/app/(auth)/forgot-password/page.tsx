import type { Metadata } from "next";
import { AuthCard } from "@/components/auth/auth-ui";
import { ForgotForm } from "./forgot-form";

export const metadata: Metadata = { title: "비밀번호 찾기 · Nomadroom Studio" };

export default async function ForgotPasswordPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return (
    <AuthCard title="비밀번호 찾기" description="등록된 이메일로 비밀번호 재설정 링크를 보냅니다.">
      <ForgotForm linkError={error === "link"} />
    </AuthCard>
  );
}
