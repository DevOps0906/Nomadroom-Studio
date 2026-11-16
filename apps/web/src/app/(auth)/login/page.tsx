import type { Metadata } from "next";
import { AuthCard } from "@/components/auth/auth-ui";
import { safeNext } from "@/server/auth/safe-next";
import { getAppOrigin } from "@/server/env";
import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "로그인 · Nomadroom Studio" };

type Search = Promise<{ next?: string | string[]; reset?: string }>;

export default async function LoginPage({ searchParams }: { searchParams: Search }) {
  const { next, reset } = await searchParams;
  const target = safeNext(typeof next === "string" ? next : null, getAppOrigin());
  return (
    <AuthCard title="로그인" description="등록된 이메일과 비밀번호로 로그인하세요.">
      <LoginForm next={target} notice={reset === "done" ? "비밀번호를 변경했습니다. 새 비밀번호로 로그인하세요." : undefined} />
    </AuthCard>
  );
}
