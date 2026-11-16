import type { ReactNode } from "react";
import { redirect } from "next/navigation";
import { AppShell } from "@/components/shell/app-shell";
import { DEFAULT_OPS_SITE_URL } from "@/components/shell/nav-config";
import { NoWorkspace } from "@/components/auth/no-workspace";
import { createServerSupabase } from "@/server/supabase/client";
import { getVerifiedClaims } from "@/server/auth/session";

export default async function DashboardLayout({ children }: { children: ReactNode }) {
  // 이중 방어: proxy와 별개로 서버에서 세션·소속을 확인한다.
  const supabase = await createServerSupabase();
  const claims = await getVerifiedClaims(supabase);
  if (!claims) redirect("/login");
  const { count, error } = await supabase
    .from("workspace_members")
    .select("workspace_id", { count: "exact", head: true })
    .eq("user_id", claims.sub);
  if (error) throw new Error("워크스페이스 소속을 확인하지 못했습니다");
  if (!count) return <NoWorkspace />;

  return <AppShell opsUrl={process.env.NEXT_PUBLIC_OPS_SITE_URL ?? DEFAULT_OPS_SITE_URL}>{children}</AppShell>;
}
