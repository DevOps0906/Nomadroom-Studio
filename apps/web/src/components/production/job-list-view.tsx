import Link from "next/link";
import { cn } from "@/lib/utils";
import { formatDateTime } from "@/components/dashboard/format";
import { RetryButton } from "@/components/dashboard/retry-button";
import type { ProductionJobListItem, ProductionStatus } from "@/server/api/production";
import { LIST_PAGE_SIZE, STAGE_LABEL, STATUS_FILTERS, STATUS_LABEL, STATUS_TONE } from "./format";

// PROD-00 작업 목록 화면 조각(서버 렌더). 근거: docs/03_SCREENS_UX.md PROD-00, tasks/task-025.md.

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
const LINK_BTN = cn("inline-flex min-h-11 items-center justify-center rounded-control px-4 text-body font-semibold", FOCUS);
const PRIMARY = cn(LINK_BTN, "bg-primary text-primary-fg hover:bg-primary-hover");
const CHIP = cn("inline-flex min-h-11 items-center rounded-chip border px-3 text-body font-medium", FOCUS);

const FORMAT_LABEL = { category: "카테고리형", variety: "예능형", shopping: "쇼핑" } as const;
const VERTICAL_TEXT = { product: "상품", travel: "여행" } as const;

/** 형식 칸 문구: 쇼핑은 분야까지(쇼핑·상품), 그 밖은 형식. */
export function formatText(j: Pick<ProductionJobListItem, "format" | "kind" | "vertical">): string {
  return j.kind === "shopping" && j.vertical ? FORMAT_LABEL.shopping + "·" + VERTICAL_TEXT[j.vertical] : FORMAT_LABEL[j.format];
}

function LangBadges({ langs }: { langs?: ("ko" | "ja")[] }) {
  if (!langs || langs.length === 0) return null;
  return (
    <span className="inline-flex gap-1" aria-label="언어">
      {langs.map((l) => (
        <span key={l} className="rounded-chip bg-neutral-soft px-2 py-0.5 text-caption font-semibold text-neutral-soft-fg">
          {l}
        </span>
      ))}
    </span>
  );
}

function listHref(status: ProductionStatus | null, page = 1) {
  const q = new URLSearchParams();
  if (status) q.set("status", status);
  if (page > 1) q.set("page", String(page));
  const s = q.toString();
  return s ? `/production?${s}` : "/production";
}

/** 작업 상태에 맞는 이동 위치: 초안·준비 실패는 PROD-01, 그 외는 작업 화면(PROD-03, 후속 작업). */
export function jobHref(j: Pick<ProductionJobListItem, "id" | "status" | "failed_stage">): string {
  const id = encodeURIComponent(j.id);
  if (j.status === "draft" || j.status === "preparing" || (j.status === "failed" && j.failed_stage === "prepare")) return `/production/${id}/source`;
  return `/production/${id}`;
}

export function ProductionHeader() {
  return (
    <div className="flex flex-col gap-3 tablet:flex-row tablet:items-start tablet:justify-between">
      <div>
        <h1 className="text-h1 font-bold">제작 작업</h1>
        <p className="mt-1 text-body text-text-muted">소재수집 후보나 업로드한 원본으로 편집안을 만들고 MP4를 검수합니다.</p>
      </div>
      <Link href="/production/new" className={PRIMARY}>
        내부 제작
      </Link>
    </div>
  );
}

export function StatusFilter({ status }: { status: ProductionStatus | null }) {
  return (
    <nav aria-label="상태 필터" className="flex flex-wrap gap-2">
      {STATUS_FILTERS.map((f) => (
        <Link
          key={f.value ?? "all"}
          href={listHref(f.value)}
          aria-current={f.value === status ? "page" : undefined}
          className={cn(CHIP, f.value === status ? "border-primary bg-primary text-primary-fg" : "border-border bg-surface text-text-muted hover:border-input")}
        >
          {f.label}
        </Link>
      ))}
    </nav>
  );
}

function StatusTag({ job }: { job: ProductionJobListItem }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <span className={cn("rounded-chip px-2 py-0.5 text-caption font-semibold", STATUS_TONE[job.status])}>{STATUS_LABEL[job.status]}</span>
      {job.status === "failed" && (
        <span className="text-caption text-danger">
          {job.failed_stage ? STAGE_LABEL[job.failed_stage] : ""}
          {job.error_code ? ` ${job.error_code}` : ""}
        </span>
      )}
    </span>
  );
}

export function JobTable({ items, status, page }: { items: ProductionJobListItem[]; status: ProductionStatus | null; page: number }) {
  return (
    <section aria-labelledby="jobs-title" className="flex flex-col gap-3">
      <h2 id="jobs-title" className="sr-only">
        작업 목록
      </h2>
      <ul className="flex flex-col gap-2 tablet:hidden">
        {items.map((j) => (
          <li key={j.id} className="rounded-card border border-border bg-surface p-3">
            <Link href={jobHref(j)} className={cn("line-clamp-2 text-body font-semibold text-primary", FOCUS)}>
              {j.title}
            </Link>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-caption text-text-muted">
              <StatusTag job={j} />
              <span>{j.kind === "shopping" ? "쇼핑" : "일반"} · {formatText(j)}</span>
              <LangBadges langs={j.langs} />
              <time dateTime={j.updated_at}>{formatDateTime(j.updated_at)}</time>
            </div>
          </li>
        ))}
      </ul>
      <div className="hidden overflow-x-auto rounded-panel border border-border bg-surface tablet:block">
        <table className="w-full text-left text-body">
          <caption className="sr-only">제작 작업 목록</caption>
          <thead className="bg-surface-alt text-caption text-text-muted">
            <tr>
              <th scope="col" className="px-4 py-3 font-semibold">제목</th>
              <th scope="col" className="px-4 py-3 font-semibold">유형</th>
              <th scope="col" className="px-4 py-3 font-semibold">형식(분야)</th>
              <th scope="col" className="px-4 py-3 font-semibold">언어</th>
              <th scope="col" className="px-4 py-3 font-semibold">상태</th>
              <th scope="col" className="px-4 py-3 font-semibold">수정 시각</th>
            </tr>
          </thead>
          <tbody>
            {items.map((j) => (
              <tr key={j.id} className="border-t border-border">
                <td className="max-w-0 px-4 py-3">
                  <Link href={jobHref(j)} className={cn("line-clamp-1 font-semibold text-primary", FOCUS)} title={j.title}>
                    {j.title}
                  </Link>
                </td>
                <td className="px-4 py-3">{j.kind === "shopping" ? "쇼핑" : "일반"}</td>
                <td className="px-4 py-3">{formatText(j)}</td>
                <td className="px-4 py-3">
                  <LangBadges langs={j.langs} />
                </td>
                <td className="px-4 py-3">
                  <StatusTag job={j} />
                </td>
                <td className="px-4 py-3 tabular-nums">
                  <time dateTime={j.updated_at}>{formatDateTime(j.updated_at)}</time>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <nav aria-label="페이지" className="flex items-center justify-between">
        {page > 1 ? (
          <Link href={listHref(status, page - 1)} className={cn(LINK_BTN, "border border-border bg-surface")}>
            이전
          </Link>
        ) : (
          <span />
        )}
        {items.length >= LIST_PAGE_SIZE && (
          <Link href={listHref(status, page + 1)} className={cn(LINK_BTN, "border border-border bg-surface")}>
            다음
          </Link>
        )}
      </nav>
    </section>
  );
}

export function EmptyJobs() {
  return (
    <section className="rounded-panel border border-border bg-surface p-6 text-center">
      <h2 className="text-h2 font-bold">제작 작업이 없습니다</h2>
      <p className="mt-1 mb-4 text-body text-text-muted">내부 제작은 소재수집(정체)의 후보나 &lsquo;내부 제작&rsquo; 버튼에서 시작합니다.</p>
      <Link href="/monitor" className={PRIMARY}>
        소재수집 열기
      </Link>
    </section>
  );
}

export function NoFilterResult() {
  return (
    <section className="rounded-panel border border-border bg-surface p-6 text-center">
      <h2 className="text-h2 font-bold">조건에 맞는 작업이 없습니다</h2>
      <Link href="/production" className={cn(LINK_BTN, "mt-3 text-primary")}>
        필터 지우기
      </Link>
    </section>
  );
}

export function JobsError({ message }: { message: string }) {
  return (
    <section role="alert" className="rounded-panel border border-danger bg-danger-soft p-5 text-danger-soft-fg">
      <h2 className="text-h2 font-bold">작업 목록을 불러오지 못했습니다</h2>
      <p className="mt-1 mb-4 text-body">{message}</p>
      <RetryButton />
    </section>
  );
}

export function JobsSkeleton() {
  return (
    <div role="status" aria-label="작업 목록 불러오는 중" className="flex flex-col gap-2">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="h-14 animate-pulse rounded-card bg-neutral-soft" />
      ))}
    </div>
  );
}
