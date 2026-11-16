import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/app-shell";
import { DEFAULT_OPS_SITE_URL } from "@/components/shell/nav-config";

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return <AppShell opsUrl={process.env.NEXT_PUBLIC_OPS_SITE_URL ?? DEFAULT_OPS_SITE_URL}>{children}</AppShell>;
}
