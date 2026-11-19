import { notFound, redirect } from "next/navigation";
import { DashboardForbidden } from "@/components/dashboard/dashboard-view";
import { isUuid } from "@/components/monitoring/query";
import { formatBytes } from "@/components/production/format";
import { SourceForm } from "@/components/production/source-form";
import { SourceHeader } from "@/components/production/source-view";
import { JobsError } from "@/components/production/job-list-view";
import { ApiError, SESSION_EXPIRED_PATH, classifyApiError } from "@/server/api/client";
import { getProductionJob, type ProductionJobDetail } from "@/server/api/production";

export const metadata = { title: "원본·구간·출처 · Nomadroom Studio" };

/** PROD-01 원본·구간·출처. 상세(A-09 GET)는 서버에서 읽고 저장·업로드·준비는 Route Handler로 보낸다. */
export default async function ProductionSourcePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();

  let detail: ProductionJobDetail;
  try {
    detail = await getProductionJob(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    const kind = classifyApiError(error);
    if (kind === "login") redirect(SESSION_EXPIRED_PATH);
    if (kind === "forbidden") return <DashboardForbidden />;
    return (
      <div className="mx-auto max-w-3xl">
        <JobsError message={error instanceof ApiError ? error.message : "잠시 후 다시 시도하세요."} />
      </div>
    );
  }

  const { job, assets } = detail;
  const source = assets.find((a) => a.kind === "source_upload" && a.status === "ready");
  const info = source ? [source.size_bytes ? formatBytes(source.size_bytes) : null, source.duration_sec ? `${Math.round(source.duration_sec)}초` : null].filter(Boolean).join(" · ") : undefined;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 tablet:gap-5">
      <SourceHeader title={job.title} />
      <SourceForm
        key={`${job.id}-${job.status}`}
        job={{
          id: job.id,
          title: job.title,
          status: job.status,
          failed_stage: job.failed_stage,
          error_code: job.error_code,
          rights_confirmed: job.rights_confirmed,
          license_cc: job.license_cc,
          credit: job.credit,
          source_start_sec: job.source_start_sec,
          segment_len_sec: job.segment_len_sec,
          source_kind: job.source_kind,
          source_url: job.source_url,
          format: job.format,
        }}
        candidate={null}
        hasReadySource={!!source}
        readySourceInfo={info || undefined}
      />
    </div>
  );
}
