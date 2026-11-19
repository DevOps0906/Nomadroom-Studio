import { Suspense } from "react";
import { redirect } from "next/navigation";
import { DashboardForbidden } from "@/components/dashboard/dashboard-view";
import { EmptyJobs, JobTable, JobsError, JobsSkeleton, NoFilterResult, ProductionHeader, StatusFilter } from "@/components/production/job-list-view";
import { LIST_PAGE_SIZE, parsePage, parseStatus } from "@/components/production/format";
import { ApiError, SESSION_EXPIRED_PATH, classifyApiError } from "@/server/api/client";
import { listProductionJobs, type ProductionJobListItem, type ProductionStatus } from "@/server/api/production";

export const metadata = { title: "제작 작업 · Nomadroom Studio" };

async function JobsSection({ status, page }: { status: ProductionStatus | null; page: number }) {
  let items: ProductionJobListItem[];
  try {
    ({ items } = await listProductionJobs({ status: status ?? undefined, page, size: LIST_PAGE_SIZE }));
  } catch (error) {
    const kind = classifyApiError(error);
    if (kind === "login") redirect(SESSION_EXPIRED_PATH);
    if (kind === "forbidden") return <DashboardForbidden />;
    return <JobsError message={error instanceof ApiError ? error.message : "잠시 후 다시 시도하세요."} />;
  }
  if (items.length === 0) return status || page > 1 ? <NoFilterResult /> : <EmptyJobs />;
  return <JobTable items={items} status={status} page={page} />;
}

/** PROD-00 제작 작업 목록. 읽기(A-09 GET)는 서버에서, 시작은 PROD-01로 이동. */
export default async function ProductionPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const status = parseStatus(sp.status);
  const page = parsePage(sp.page);
  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4 tablet:gap-5">
      <ProductionHeader />
      <StatusFilter status={status} />
      <Suspense key={`${status}-${page}`} fallback={<JobsSkeleton />}>
        <JobsSection status={status} page={page} />
      </Suspense>
    </div>
  );
}
