import Link from "next/link";
import { cn } from "@/lib/utils";
import { formatDateTime, formatGrowth } from "@/components/dashboard/format";
import { RetryButton } from "@/components/dashboard/retry-button";
import { EvidenceButton } from "@/components/evidence/evidence-dialog";
import type { CandidateItem, CandidateList, Counts } from "@/server/api/monitor";
import {
  FORMAT_FILTERS,
  LICENSE_FILTERS,
  MAX_PAGE,
  MAX_Q,
  PAGE_SIZE,
  SORTS,
  STATUSES,
  toHref,
  type CandidateQuery,
} from "./query";
import { candidateHref } from "@/components/production/format";
import { FiltersDisclosure } from "./filters-disclosure";
import { safeThumbnailUrl } from "./thumbnail";
import { UsedToggle } from "./UsedToggle";

// MON-01 후보 영역(상태 없는 서버 렌더 뷰). 비신뢰 값(제목·장르·프로필명)은 JSX 텍스트로만 넣는다.

export const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
export const PANEL = "rounded-panel border border-border bg-surface p-4 tablet:p-5";
const CHIP = cn("inline-flex min-h-11 items-center rounded-chip border px-3 text-body font-medium", FOCUS);
const CHIP_ON = "border-primary bg-primary text-primary-fg";
const CHIP_OFF = "border-border bg-surface text-text-muted hover:border-input";

const STATUS_TAG: Record<CandidateItem["status"], { label: string; className: string }> = {
  producible: { label: "제작 가능", className: "bg-success-soft text-success-soft-fg" },
  pending: { label: "근거 대기", className: "bg-warning-soft text-warning-soft-fg" },
  excluded: { label: "조건 제외", className: "bg-neutral-soft text-neutral-soft-fg" },
  used: { label: "사용한 소재", className: "bg-primary-soft text-primary-soft-fg" },
};

const nf = (n: number) => n.toLocaleString("ko-KR");

function countOf(counts: Counts, status: CandidateQuery["status"]): number {
  return status === "all" ? counts.total : counts[status];
}

/** 상태별 지표(누르면 필터). */
export function StatusStats({ counts, query }: { counts: Counts; query: CandidateQuery }) {
  return (
    <nav aria-label="상태 필터">
      <ul className="grid grid-cols-2 gap-2 tablet:grid-cols-3 desktop:grid-cols-5">
        {STATUSES.map((s, i) => {
          const active = s.value === query.status;
          return (
            // 모바일 2열에서 5번째 칸이 혼자 남지 않게 두 칸을 차지한다.
            <li key={s.value} className={i === STATUSES.length - 1 ? "col-span-2 tablet:col-span-1" : undefined}>
              <Link
                href={toHref(query, { status: s.value })}
                aria-current={active ? "true" : undefined}
                className={cn(
                  "flex min-h-11 flex-col rounded-card border p-3",
                  FOCUS,
                  active ? "border-primary bg-primary-soft text-primary-soft-fg" : "border-border bg-surface hover:border-input",
                )}
              >
                <span className="text-body text-text-muted">{s.label}</span>
                <span className="text-h1 font-bold tabular-nums">{nf(countOf(counts, s.value))}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function ChipGroup<T extends string | null>({
  label,
  options,
  value,
  href,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T;
  href: (v: T) => string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap items-center gap-2">
      <span className="text-caption font-semibold text-text-muted">{label}</span>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <Link
            key={o.value ?? "__all"}
            href={href(o.value)}
            aria-current={active ? "true" : undefined}
            className={cn(CHIP, active ? CHIP_ON : CHIP_OFF)}
          >
            {o.label}
          </Link>
        );
      })}
    </div>
  );
}

/** 상태 외에 적용된 검색·필터 수(모바일 접힘 요약에 표시). */
export function activeFilters(q: CandidateQuery): number {
  return [q.q !== "", q.category !== null, q.format !== "all", q.profile_id !== null, q.license !== "any"].filter(Boolean).length;
}

/** 검색(제목·채널) + 카테고리·형식·프로필·라이선스 필터 + 정렬. JS 없이 동작하는 링크·GET 폼. */
export function CandidateFilters({
  query,
  categories,
  profiles,
}: {
  query: CandidateQuery;
  categories: string[];
  profiles: { id: string; name: string }[];
}) {
  const keep = Object.entries(Object.fromEntries(new URLSearchParams(toHref(query, { q: "" }).slice(1)))).filter(
    ([k]) => k !== "page",
  );
  return (
    <FiltersDisclosure activeCount={activeFilters(query)}>
      <form method="get" role="search" className="flex flex-col gap-2 tablet:flex-row">
        {keep.map(([k, v]) => (
          <input key={k} type="hidden" name={k} value={v} />
        ))}
        <label htmlFor="candidate-q" className="sr-only">
          제목·채널 검색
        </label>
        <input
          id="candidate-q"
          name="q"
          type="search"
          defaultValue={query.q}
          maxLength={MAX_Q}
          placeholder="제목·채널 검색"
          className={cn("min-h-11 w-full rounded-control border border-input bg-surface px-3 text-input", FOCUS)}
        />
        <button
          type="submit"
          className={cn("inline-flex min-h-11 shrink-0 items-center justify-center rounded-control border border-border bg-surface px-4 text-body font-semibold hover:border-input", FOCUS)}
        >
          검색
        </button>
      </form>
      <ChipGroup
        label="카테고리"
        options={[{ value: null, label: "전체" }, ...categories.map((c) => ({ value: c as string | null, label: c }))]}
        value={query.category}
        href={(v) => toHref(query, { category: v })}
      />
      <ChipGroup label="형식" options={FORMAT_FILTERS} value={query.format} href={(v) => toHref(query, { format: v })} />
      {profiles.length > 0 && (
        <ChipGroup
          label="프로필"
          options={[{ value: null, label: "전체 프로필" }, ...profiles.map((p) => ({ value: p.id as string | null, label: p.name }))]}
          value={query.profile_id}
          href={(v) => toHref(query, { profile_id: v })}
        />
      )}
      <ChipGroup label="라이선스" options={LICENSE_FILTERS} value={query.license} href={(v) => toHref(query, { license: v })} />
      <ChipGroup label="정렬" options={SORTS} value={query.sort} href={(v) => toHref(query, { sort: v })} />
    </FiltersDisclosure>
  );
}

function formatLabel(f: CandidateItem["format"]): string {
  return f === "short" ? "쇼츠" : f === "long" ? "롱폼" : "형식 미확인";
}

function licenseLabel(cc: boolean | null): string {
  return cc === true ? "C.C 확인" : cc === null ? "라이선스 확인 대기" : "표준 라이선스";
}

/** 두 시점 미니 차트(장식). 수치는 옆 텍스트가 전달한다. */
function MiniChart({ prev, curr }: { prev: number; curr: number }) {
  const max = Math.max(prev, curr, 1);
  const y = (v: number) => 26 - (v / max) * 22;
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden className="h-8 w-full">
      <line x1="0" y1="27" x2="100" y2="27" className="stroke-border" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      <polyline points={`4,${y(prev)} 96,${y(curr)}`} className="fill-none stroke-primary" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Thumbnail({ url }: { url: string | null }) {
  const safe = safeThumbnailUrl(url);
  if (!safe) return <div aria-hidden data-thumb="placeholder" className="aspect-video w-full rounded-control bg-neutral-soft" />;
  // eslint-disable-next-line @next/next/no-img-element -- 허용 host만, next/image 미사용(결정 문서)
  return <img src={safe} alt="" loading="lazy" referrerPolicy="no-referrer" className="aspect-video w-full rounded-control bg-neutral-soft object-cover" />;
}

export function CandidateCard({ item, opsUrl }: { item: CandidateItem; opsUrl: string }) {
  const tag = STATUS_TAG[item.status] ?? STATUS_TAG.pending;
  return (
    <article className="flex w-full min-w-0 flex-col gap-2 rounded-card border border-border bg-surface p-3">
      <Thumbnail url={item.thumbnail_url} />
      <div className="flex flex-wrap gap-1">
        <span className={cn("rounded-chip px-2 py-0.5 text-caption font-semibold", tag.className)}>{tag.label}</span>
        {item.genre && <span className="rounded-chip bg-neutral-soft px-2 py-0.5 text-caption text-neutral-soft-fg">{item.genre}</span>}
      </div>
      <h3 className="line-clamp-2 text-body font-semibold" title={item.title}>
        {item.title}
      </h3>
      <p className="text-caption text-text-muted">
        {formatLabel(item.format)} · {item.profile_names.length > 0 ? item.profile_names.join(", ") : "프로필 —"} ·{" "}
        {licenseLabel(item.license_cc)}
      </p>
      {item.prev && item.curr ? (
        <div>
          <MiniChart prev={item.prev.view_count} curr={item.curr.view_count} />
          <p className="text-caption text-text-muted tabular-nums">
            <time dateTime={item.prev.observed_at}>{formatDateTime(item.prev.observed_at)}</time> ~{" "}
            <time dateTime={item.curr.observed_at}>{formatDateTime(item.curr.observed_at)}</time>
            {item.period_days !== null && ` (${item.period_days.toFixed(1)}일)`} · {nf(item.prev.view_count)} → {nf(item.curr.view_count)}회{" "}
            <strong className="font-semibold text-text">
              <span className="sr-only">증가율 </span>
              {formatGrowth(item.growth_pct)}
            </strong>
          </p>
        </div>
      ) : (
        <p className="rounded-control bg-warning-soft px-2 py-1 text-caption text-warning-soft-fg">
          이전 관측값 필요
          {item.curr && ` · 현재 ${nf(item.curr.view_count)}회`}
          {item.next_observation_at && (
            <>
              {" "}
              · 다음 관측 예정 <time dateTime={item.next_observation_at}>{formatDateTime(item.next_observation_at)}</time>
            </>
          )}
        </p>
      )}
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-1">
        <EvidenceButton candidateId={item.id} title={item.title} opsUrl={opsUrl} />
        <UsedToggle candidateId={item.id} used={item.used} />
        <Link
          href={candidateHref(item)}
          className={cn("inline-flex min-h-11 items-center rounded-control border border-border bg-surface px-3 text-body font-semibold text-text hover:bg-surface-alt", FOCUS)}
        >
          내부 제작
        </Link>
        {item.status === "producible" && opsUrl && (
          <a
            href={opsUrl}
            target="_blank"
            rel="noopener noreferrer"
            className={cn("inline-flex min-h-11 items-center rounded-control bg-primary px-3 text-body font-semibold text-primary-fg hover:bg-primary-hover", FOCUS)}
          >
            영상 만들기<span aria-hidden className="ml-1">→</span>
            <span className="sr-only">(새 탭에서 열림)</span>
          </a>
        )}
      </div>
    </article>
  );
}

function Pagination({ query, total }: { query: CandidateQuery; total: number }) {
  const pages = Math.min(Math.ceil(total / PAGE_SIZE), MAX_PAGE);
  if (pages <= 1) return null;
  const cur = Math.min(query.page, pages);
  const nums = [...new Set([1, cur - 1, cur, cur + 1, pages])].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  const link = (n: number, label: string, aria?: string) => (
    <Link
      key={label}
      href={toHref(query, { page: n })}
      aria-label={aria}
      aria-current={n === cur && !aria ? "page" : undefined}
      className={cn(CHIP, "justify-center px-0 min-w-11", n === cur && !aria ? CHIP_ON : CHIP_OFF)}
    >
      {label}
    </Link>
  );
  return (
    <nav aria-label="페이지" className="flex flex-wrap items-center justify-center gap-1">
      {cur > 1 && link(cur - 1, "‹", "이전 페이지")}
      {nums.map((n) => link(n, String(n)))}
      {cur < pages && link(cur + 1, "›", "다음 페이지")}
    </nav>
  );
}

function isFiltered(q: CandidateQuery): boolean {
  return q.status !== "all" || q.category !== null || q.format !== "all" || q.profile_id !== null || q.license !== "any" || q.q !== "";
}

/** 후보 목록(성공·빈 상태) + 페이지. */
export function CandidateResults({ data, query, opsUrl }: { data: CandidateList; query: CandidateQuery; opsUrl: string }) {
  const total = countOf(data.counts, query.status);
  return (
    <section aria-labelledby="candidates-title" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="candidates-title" className="text-h2 font-bold">
          {STATUSES.find((s) => s.value === query.status)?.label ?? "전체"} 후보
        </h2>
        <span className="text-caption text-text-muted tabular-nums">{nf(total)}건</span>
      </div>
      {data.items.length === 0 ? (
        data.counts.total === 0 && !isFiltered(query) ? (
          <div className="rounded-panel border border-dashed border-input p-6 text-center">
            <p className="text-h2 font-bold">아직 가져온 후보가 없습니다</p>
            <p className="mt-1 text-body text-text-muted">위의 &apos;후보 가져오기&apos;를 눌러 선택한 프로필의 후보를 가져오세요.</p>
          </div>
        ) : (
          <div className="rounded-panel border border-dashed border-input p-6 text-center">
            <p className="text-body text-text-muted">선택한 조건에 맞는 후보가 없습니다.</p>
            <Link href="?" className={cn("mt-3 inline-flex min-h-11 items-center rounded-control px-3 text-body font-semibold text-primary", FOCUS)}>
              필터 초기화
            </Link>
          </div>
        )
      ) : (
        <ul className="grid grid-cols-1 gap-3 tablet:grid-cols-2 desktop:grid-cols-3">
          {data.items.map((item) => (
            <li key={item.id} className="flex">
              <CandidateCard item={item} opsUrl={opsUrl} />
            </li>
          ))}
        </ul>
      )}
      <Pagination query={query} total={total} />
    </section>
  );
}

function Bar({ className }: { className?: string }) {
  return <span className={cn("block animate-pulse rounded-control bg-neutral-soft", className)} />;
}

/** 로딩: 카드 스켈레톤. */
export function CandidateSkeleton({ label = "후보 가져오는 중" }: { label?: string }) {
  return (
    <div role="status" aria-label={label} className="grid grid-cols-1 gap-3 tablet:grid-cols-2 desktop:grid-cols-3">
      {[0, 1, 2].map((i) => (
        <div key={i} className="rounded-card border border-border bg-surface p-3">
          <Bar className="aspect-video w-full" />
          <Bar className="mt-3 h-4 w-24" />
          <Bar className="mt-2 h-5 w-full" />
          <Bar className="mt-2 h-4 w-40 max-w-full" />
        </div>
      ))}
      <span className="sr-only">{label}…</span>
    </div>
  );
}

/** 로딩: 프로필별 진행 자리(스켈레톤 줄). */
export function ProgressSkeleton({ rows = 2 }: { rows?: number }) {
  return (
    <div aria-hidden data-skeleton="progress" className={PANEL}>
      <Bar className="h-5 w-32" />
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="mt-3 flex items-center justify-between gap-3 rounded-card border border-border p-3">
          <Bar className="h-4 w-28" />
          <Bar className="h-4 w-20" />
        </div>
      ))}
    </div>
  );
}

/** 오류: 다시 시도. message는 API 고정 문구 또는 공용 기본 문구. */
export function MonitorError({ title, message }: { title: string; message: string }) {
  return (
    <section role="alert" className="rounded-panel border border-danger bg-danger-soft p-5 text-danger-soft-fg">
      <h2 className="text-h2 font-bold">{title}</h2>
      <p className="mt-1 mb-4 text-body">{message}</p>
      <RetryButton />
    </section>
  );
}
