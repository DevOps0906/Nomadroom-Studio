import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { DashboardForbidden } from "@/components/dashboard/dashboard-view";
import { isUuid } from "@/components/monitoring/query";
import { JobsError } from "@/components/production/job-list-view";
import { EditForm, type EditRevision } from "@/components/production/edit/edit-form";
import { ShoppingEditForm } from "@/components/production/shopping/edit-form";
import { ApiError, SESSION_EXPIRED_PATH, classifyApiError } from "@/server/api/client";
import { getProductionJob, getProductionRevision, type ProductionJobDetail } from "@/server/api/production";
import { JaPanel } from "@/components/production/lang/ja-panel";
import type { JaRevision } from "@/components/production/lang/api";
import { LangTabs } from "@/components/production/lang/lang-tabs";
import { parseLang } from "@/components/production/lang/model";

export const metadata = { title: "편집안 · Nomadroom Studio" };

/** PROD-02 편집안. 작업·리비전(A-09 GET·A-12 GET)은 서버에서 읽고 저장·승인·업로드는 Route Handler로 보낸다. */
export default async function ProductionEditPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { id } = await params;
  const lang = parseLang((await searchParams).lang);
  if (!isUuid(id)) notFound();

  let detail: ProductionJobDetail;
  let revision: EditRevision | null = null;
  let jaRevision: JaRevision | null = null;
  try {
    detail = await getProductionJob(id);
    if (detail.current_revision.ko) {
      const r = await getProductionRevision(id);
      revision = { rev_no: r.rev_no, spec: r.spec, validation: r.validation, approved_at: r.approved_at };
    }
    if (lang === "ja" && detail.current_revision.ja) {
      const r = await getProductionRevision(id, undefined, "ja");
      jaRevision = { id: r.id, rev_no: r.rev_no, spec: r.spec, origin: r.origin, validation: r.validation, approved_at: r.approved_at, derived_from: r.derived_from ?? null };
    }
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
  if (job.status === "draft" || job.status === "preparing" || (job.status === "failed" && job.failed_stage === "prepare")) {
    redirect(`/production/${encodeURIComponent(job.id)}/source`);
  }
  const source = assets.find((a) => a.kind === "source_upload" && a.status === "ready");

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 tablet:gap-5 desktop:max-w-5xl">
      <div className="flex flex-col gap-3 tablet:flex-row tablet:items-start tablet:justify-between">
      <header className="flex flex-col gap-1">
        <nav aria-label="경로" className="text-caption text-text-muted">
          <Link href="/production" className="underline-offset-4 hover:underline">
            제작 작업
          </Link>{" "}
          / 편집안
        </nav>
        <h1 className="line-clamp-2 text-h1 font-bold">
          {job.title}
        </h1>
        {job.kind === "shopping" && (
          <p className="text-caption font-semibold text-primary">쇼핑{job.vertical ? "·" + (job.vertical === "travel" ? "여행" : "상품") : ""} 형식</p>
        )}
        <p className="text-caption text-text-muted">{revision ? `리비전 ${revision.rev_no}${revision.approved_at ? " · 승인됨" : ""}` : "리비전 없음"}</p>
      </header>
      <LangTabs basePath={`/production/${encodeURIComponent(job.id)}/edit`} active={lang} jaExists={!!detail.current_revision.ja} />
      </div>
      {lang === "ja" ? (
        <JaPanel
          key={`${job.id}-ja-${jaRevision?.rev_no ?? 0}`}
          job={{ id: job.id, format: job.format }}
          ko={detail.current_revision.ko ? { id: detail.current_revision.ko.id, rev_no: detail.current_revision.ko.rev_no, approved_at: detail.current_revision.ko.approved_at } : null}
          ja={jaRevision}
        />
      ) : job.kind === "shopping" ? (
        <ShoppingEditForm
          key={`${job.id}-${revision?.rev_no ?? 0}`}
          job={{ id: job.id, title: job.title, status: job.status, failed_stage: job.failed_stage, vertical: job.vertical ?? null }}
          revision={revision}
          brief={job.brief ?? null}
          assets={assets.map((a) => ({ id: a.id, kind: a.kind, status: a.status, duration_sec: a.duration_sec }))}
          sheet={{
            jobId: job.id,
            sheetIds: assets.filter((a) => a.kind === "sheet" && a.status === "ready").map((a) => a.id),
            sourceStart: job.source_start_sec,
            segmentLen: job.segment_len_sec,
            sourceDuration: source?.duration_sec ?? null,
          }}
        />
      ) : (
        <EditForm
          key={`${job.id}-${revision?.rev_no ?? 0}`}
          job={{ id: job.id, title: job.title, status: job.status, failed_stage: job.failed_stage, format: job.format === "variety" ? "variety" : "category" }}
          revision={revision}
          sheet={{
            jobId: job.id,
            sheetIds: assets.filter((a) => a.kind === "sheet" && a.status === "ready").map((a) => a.id),
            sourceStart: job.source_start_sec,
            segmentLen: job.segment_len_sec,
            sourceDuration: source?.duration_sec ?? null,
          }}
        />
      )}
    </div>
  );
}
