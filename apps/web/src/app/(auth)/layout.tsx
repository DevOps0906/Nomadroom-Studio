import type { ReactNode } from "react";

// 인증 화면 레이아웃(셸 없음). 3구간 모두 가운데 카드.
export default function AuthLayout({ children }: { children: ReactNode }) {
  return <main className="flex min-h-screen items-center justify-center bg-bg px-4 py-10 text-text tablet:px-6">{children}</main>;
}
