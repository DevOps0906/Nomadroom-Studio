import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { DashboardForbidden } from "@/components/dashboard/dashboard-view";
import { isUuid } from "@/components/monitoring/query";
import { JobsError } from "@/components/production/job-list-view";
import { RunView } from "@/components/production/run/run-view";
import { JaRunView } from "@/components/production/lang/ja-run";
import { LangTabs } from "@/components/production/lang/lang-tabs";
import { parseLang } from "@/components/production/lang/model";
import { latestAsset } from "@/components/production/run/model";
import { ApiError, SESSION_EXPIRED_PATH, classifyApiError } from "@/server/api/client";
import { getProductionJob, type ProductionJobDetail } from "@/server/api/production";

export const metadata = { title: "작업·검수 · Nomadroom Studio" };

/** PROD-03 작업·검수. 상세(A-09 GET)는 서버에서 읽고 렌더 요청·재시도·검수 승인은 Route Handler로 보낸다. */
export default async function ProductionJobPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { id } = await params;
  const lang = parseLang((await searchParams).lang);
  if (!isUuid(id)) notFound();

  let detail: ProductionJobDetail;
  try {
    detail = await getProductionJob(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return (
        <div className="mx-auto flex max-w-3xl flex-col items-start gap-3">
          <h1 className="text-h1 font-bold">작업을 찾을 수 없습니다</h1>
          <Link href="/production" className="text-primary underline underline-offset-4">
            목록으로 돌아가기
          </Link>
        </div>
      );
    }
    const kind = classifyApiError(error);
    if (kind === "login") redirect(SESSION_EXPIRED_PATH);
    if (kind === "forbidden") return <DashboardForbidden />;
    return (
      <div className="mx-auto max-w-3xl">
        <JobsError message={error instanceof ApiError ? error.message : "잠시 후 다시 시도하세요."} />
      </div>
    );
  }

  const { job } = detail;
  if (job.status === "draft" || job.status === "preparing" || (job.status === "failed" && job.failed_stage === "prepare")) {
    redirect(`/production/${encodeURIComponent(job.id)}/source`);
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 tablet:gap-5 desktop:max-w-5xl">
      <div className="flex flex-col gap-3 tablet:flex-row tablet:items-start tablet:justify-between">
      <header className="flex flex-col gap-1">
        <nav aria-label="경로" className="text-caption text-text-muted">
          <Link href="/production" className="underline-offset-4 hover:underline">
            제작 작업
          </Link>{" "}
          / 작업·검수
        </nav>
        <h1 className="line-clamp-2 text-h1 font-bold">{job.title}</h1>
      </header>
      <LangTabs basePath={`/production/${encodeURIComponent(job.id)}`} active={lang} jaExists={!!detail.current_revision.ja} />
      </div>
      {lang === "ja" ? (
        <JaRunView
          job={{ id: job.id, shopping: job.kind === "shopping" }}
          ja={detail.current_revision.ja ? { id: detail.current_revision.ja.id, rev_no: detail.current_revision.ja.rev_no, approved_at: detail.current_revision.ja.approved_at } : null}
          reportId={latestAsset(detail.assets, "report")}
        />
      ) : (
        <RunView detail={detail} />
      )}
    </div>
  );
}
