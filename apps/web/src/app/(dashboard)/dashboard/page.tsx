import { Suspense } from "react";
import { DEFAULT_OPS_SITE_URL } from "@/components/shell/nav-config";
import { DashboardContent } from "@/components/dashboard/dashboard-content";
import { DashboardHeader, DashboardSkeleton } from "@/components/dashboard/dashboard-view";
import { parsePeriod } from "@/server/api/dashboard";

export const metadata = { title: "대시보드 · Nomadroom Studio" };

export default async function DashboardPage({ searchParams }: { searchParams: Promise<{ period?: string | string[] }> }) {
  const period = parsePeriod((await searchParams).period);
  const opsUrl = process.env.NEXT_PUBLIC_OPS_SITE_URL ?? DEFAULT_OPS_SITE_URL;
  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4 tablet:gap-5">
      <DashboardHeader period={period} opsUrl={opsUrl} />
      <Suspense key={period} fallback={<DashboardSkeleton />}>
        <DashboardContent period={period} />
      </Suspense>
    </div>
  );
}
