import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { DashboardPeriod, DashboardSummary } from "@/server/api/dashboard";
import { formatDateTime, formatGrowth } from "./format";
import { LastUpdated } from "./last-updated";
import { RetryButton } from "./retry-button";

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-3";
const BTN = cn("inline-flex min-h-11 items-center justify-center rounded-control px-4 text-body font-semibold", FOCUS);
const BTN_PRIMARY = cn(BTN, "bg-primary text-primary-fg hover:bg-primary-hover");
const BTN_DEFAULT = cn(BTN, "border border-border bg-surface text-text hover:border-input");
const PANEL = "rounded-panel border border-border bg-surface p-4 tablet:p-5";
const NOT_LINKED = "운영 사이트 연동 전";
const MONITOR_HREF = "/monitor";

const PERIODS: { value: DashboardPeriod; label: string }[] = [
  { value: "24h", label: "최근 24시간" },
  { value: "7d", label: "최근 7일" },
];

/** 인사·새 영상 만들기·기간 선택. 데이터와 무관해 로딩·오류 중에도 보인다. */
export function DashboardHeader({ period, opsUrl }: { period: DashboardPeriod; opsUrl: string }) {
  return (
    <>
      <div>
        <h1 className="text-h1 font-bold">대시보드</h1>
        <p className="mt-1 text-body text-text-muted">소재 수집과 제작 가능 후보를 한눈에 확인하세요.</p>
      </div>
      <section aria-labelledby="dash-hero" className="rounded-panel bg-primary-soft p-5 text-primary-soft-fg tablet:p-6">
        <h2 id="dash-hero" className="text-h2 font-bold">오늘은 어떤 쇼츠를 만들까요?</h2>
        <p className="mt-1 mb-4 text-body">소재 탐색부터 제작 요청까지 한곳에서 이어서 작업하세요.</p>
        {opsUrl ? (
          <a href={opsUrl} target="_blank" rel="noopener noreferrer" className={BTN_PRIMARY}>
            새 영상 만들기<span aria-hidden className="ml-1">↗</span>
            <span className="sr-only">(새 탭에서 열림)</span>
          </a>
        ) : (
          <span aria-disabled="true" className={cn(BTN_PRIMARY, "cursor-not-allowed opacity-55")}>
            새 영상 만들기 ({NOT_LINKED})
          </span>
        )}
      </section>
      <nav aria-label="기간 선택" className="flex flex-wrap items-center gap-2">
        {PERIODS.map((p) => {
          const active = p.value === period;
          return (
            <Link
              key={p.value}
              href={`?period=${p.value}`}
              aria-current={active ? "true" : undefined}
              className={cn(
                "inline-flex min-h-11 items-center rounded-chip border px-4 text-body font-medium",
                FOCUS,
                active ? "border-primary bg-primary text-primary-fg" : "border-border bg-surface text-text-muted hover:border-input",
              )}
            >
              {p.label}
            </Link>
          );
        })}
        <span className="text-caption text-text-muted">수집 소재·최근 제작 가능 후보 기준</span>
      </nav>
    </>
  );
}

function StatCard({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-card border border-border bg-surface p-4">
      <dt className="text-body text-text-muted">{label}</dt>
      <dd className="mt-1">
        {value === null ? (
          <>
            <span className="block text-h1 font-bold text-text-muted" aria-hidden>—</span>
            <span className="text-caption text-text-muted">{NOT_LINKED}</span>
          </>
        ) : (
          <span className="block text-h1 font-bold tabular-nums">{value.toLocaleString("ko-KR")}</span>
        )}
      </dd>
    </div>
  );
}

function StatGrid({ children }: { children: ReactNode }) {
  return <dl className="grid grid-cols-2 gap-3 desktop:grid-cols-4">{children}</dl>;
}

/**
 * 첫 사용(기간과 무관한 총 건수 0). A-02에는 전체 건수가 없어 기간 무관 값인 stealth(제작 가능+근거 대기)와
 * 기간 내 collected의 합으로 근사한다. 제외·사용됨만 남은 오래된 후보는 이 근사에서 빠진다.
 */
function isFirstUse(s: DashboardSummary): boolean {
  return s.stats.collected + s.stealth.producible + s.stealth.pending === 0 && s.recent_ready.length === 0;
}

/** 성공·빈 상태. */
export function DashboardSummaryView({ summary }: { summary: DashboardSummary }) {
  if (isFirstUse(summary)) {
    return (
      <>
        <section className="rounded-panel border border-dashed border-input p-6 text-center">
          <h2 className="text-h2 font-bold">아직 수집된 소재가 없습니다</h2>
          <p className="mt-1 mb-4 text-body text-text-muted">
            소재수집(정체)에서 후보를 가져오면 제작 가능 소재가 여기에 표시됩니다.
          </p>
          <Link href={MONITOR_HREF} className={BTN_PRIMARY}>
            소재수집(정체) 열기
          </Link>
        </section>
        <LastUpdated at={summary.updated_at} />
      </>
    );
  }

  const { stats, stealth, recent_ready } = summary;
  return (
    <>
      <StatGrid>
        <StatCard label="수집 소재" value={stats.collected} />
        <StatCard label="작업 중" value={stats.in_progress} />
        <StatCard label="검수 완료" value={stats.reviewed} />
        <StatCard label="업로드 대기" value={stats.upload_pending} />
      </StatGrid>

      <section aria-labelledby="dash-stealth" className={cn(PANEL, "flex flex-col gap-3 tablet:flex-row tablet:items-center tablet:justify-between")}>
        <div>
          <h2 id="dash-stealth" className="text-h2 font-bold">소재수집(정체)</h2>
          <p className="mt-1 text-body text-text-muted">
            제작 가능 <strong className="font-semibold text-success tabular-nums">{stealth.producible}건</strong>과 근거 대기{" "}
            <strong className="font-semibold text-warning tabular-nums">{stealth.pending}건</strong>을 확인하세요.
          </p>
        </div>
        <Link href={MONITOR_HREF} className={BTN_DEFAULT}>
          정체 후보 보기<span aria-hidden className="ml-1">→</span>
        </Link>
      </section>

      <section aria-labelledby="dash-recent" className={PANEL}>
        <h2 id="dash-recent" className="mb-3 text-h2 font-bold">최근 제작 가능 후보</h2>
        {recent_ready.length === 0 ? (
          <p className="text-body text-text-muted">
            {stats.collected === 0 ? "이 기간에 새로 수집된 소재가 없습니다." : "선택한 기간에 제작 가능 판정이 없습니다."}
          </p>
        ) : (
          <>
            {/* 모바일: 카드(제목 + 보조 줄). 태블릿 이상: 표 */}
            <ul aria-labelledby="dash-recent" className="flex flex-col gap-2 tablet:hidden">
              {recent_ready.map((r) => (
                <li key={r.id} className="rounded-card border border-border p-3">
                  <p className="truncate text-body font-semibold" title={r.title}>{r.title}</p>
                  <p className="mt-1 flex flex-wrap gap-x-2 text-caption text-text-muted">
                    <span>{r.profile_name ?? "—"}</span>
                    <span aria-hidden>·</span>
                    <span className="tabular-nums">
                      <span className="sr-only">증가율 </span>
                      {formatGrowth(r.growth_pct)}
                    </span>
                    <span aria-hidden>·</span>
                    <time dateTime={r.status_changed_at} className="tabular-nums">{formatDateTime(r.status_changed_at)}</time>
                  </p>
                </li>
              ))}
            </ul>
            <div className="hidden overflow-x-auto tablet:block">
              <table aria-labelledby="dash-recent" className="w-full min-w-120 border-collapse text-left text-body">
                <thead className="text-caption text-text-muted">
                  <tr className="border-b border-border">
                    <th scope="col" className="py-2 pr-3 font-semibold">제목</th>
                    <th scope="col" className="py-2 pr-3 font-semibold">프로필</th>
                    <th scope="col" className="py-2 pr-3 text-right font-semibold">증가율</th>
                    <th scope="col" className="py-2 font-semibold">판정 시각</th>
                  </tr>
                </thead>
                <tbody>
                  {recent_ready.map((r) => (
                    <tr key={r.id} className="border-b border-border last:border-b-0">
                      <td className="max-w-80 truncate py-2 pr-3" title={r.title}>{r.title}</td>
                      <td className="py-2 pr-3 text-text-muted">{r.profile_name ?? "—"}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{formatGrowth(r.growth_pct)}</td>
                      <td className="py-2 tabular-nums text-text-muted">
                        <time dateTime={r.status_changed_at}>{formatDateTime(r.status_changed_at)}</time>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
      <LastUpdated at={summary.updated_at} />
    </>
  );
}

function Bar({ className }: { className?: string }) {
  return <span className={cn("block animate-pulse rounded-control bg-neutral-soft", className)} />;
}

/** 로딩: 지표 스켈레톤. */
export function DashboardSkeleton() {
  return (
    <div role="status" aria-label="대시보드 불러오는 중" className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 desktop:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="rounded-card border border-border bg-surface p-4">
            <Bar className="h-4 w-20" />
            <Bar className="mt-3 h-8 w-16" />
          </div>
        ))}
      </div>
      <div className={PANEL}>
        <Bar className="h-5 w-40" />
        <Bar className="mt-3 h-4 w-64 max-w-full" />
      </div>
      <div className={PANEL}>
        <Bar className="h-5 w-40" />
        {[0, 1, 2].map((i) => (
          <Bar key={i} className="mt-3 h-4 w-full" />
        ))}
      </div>
      <span className="sr-only">불러오는 중…</span>
    </div>
  );
}

/** 오류: 다시 시도 + 마지막 갱신 시각 유지. */
export function DashboardError({ message }: { message: string }) {
  return (
    <>
      <section role="alert" className="rounded-panel border border-danger bg-danger-soft p-5 text-danger-soft-fg">
        <h2 className="text-h2 font-bold">대시보드를 불러오지 못했습니다</h2>
        <p className="mt-1 mb-4 text-body">{message}</p>
        <RetryButton />
      </section>
      <LastUpdated />
    </>
  );
}

/** 403 FORBIDDEN: 워크스페이스 소속 없음. */
export function DashboardForbidden() {
  return (
    <section role="alert" className={PANEL}>
      <h2 className="text-h2 font-bold">접근 권한 없음</h2>
      <p className="mt-1 text-body text-text-muted">워크스페이스 접근 권한이 없습니다. 관리자에게 문의하세요.</p>
    </section>
  );
}
