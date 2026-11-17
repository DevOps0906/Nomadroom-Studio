import { cn } from "@/lib/utils";
import { formatDateTime, formatGrowth } from "@/components/dashboard/format";
import { isObservationDue, reasonLabel, type Evidence, type EvidenceObservation, type EvidenceStatus } from "./evidence";

// MON-D2 관측 근거 본문(상태 prop만 받는 순수 뷰). 판정은 재계산하지 않고 서버 값만 표시한다.
// 비신뢰 값(제목)은 JSX 텍스트로만 넣는다.

export type EvidenceState =
  | { kind: "loading" }
  | { kind: "ok"; data: Evidence; now: number }
  | { kind: "error"; retrying: boolean }
  | { kind: "not_found" };

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
const BTN = cn("inline-flex min-h-11 items-center justify-center rounded-control px-4 text-body font-semibold disabled:cursor-not-allowed disabled:opacity-55", FOCUS);
const BTN_PRIMARY = cn(BTN, "bg-primary text-primary-fg hover:bg-primary-hover");
const BTN_SECONDARY = cn(BTN, "border border-input bg-surface text-text hover:bg-surface-alt");

const STATUS_TAG: Record<EvidenceStatus, { label: string; className: string }> = {
  producible: { label: "제작 가능", className: "bg-success-soft text-success-soft-fg" },
  pending: { label: "근거 대기", className: "bg-warning-soft text-warning-soft-fg" },
  excluded: { label: "조건 제외", className: "bg-neutral-soft text-neutral-soft-fg" },
  used: { label: "사용한 소재", className: "bg-primary-soft text-primary-soft-fg" },
};

const nf = (n: number) => n.toLocaleString("ko-KR");

function Bar({ className }: { className?: string }) {
  return <span className={cn("block h-4 animate-pulse rounded-control bg-neutral-soft", className)} />;
}

function ObservationTable({ rows }: { rows: { label: string; obs: EvidenceObservation }[] }) {
  return (
    <div className="overflow-x-auto rounded-card border border-border">
      <table className="w-full border-collapse text-left text-body">
        <thead className="text-caption text-text-muted">
          <tr>
            <th scope="col" className="border-b border-border px-3 py-2 font-semibold">시점</th>
            <th scope="col" className="border-b border-border px-3 py-2 font-semibold">날짜(KST)</th>
            <th scope="col" className="border-b border-border px-3 py-2 text-right font-semibold">조회수</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} data-row={r.label}>
              <th scope="row" className="border-b border-border px-3 py-2 font-semibold">{r.label}</th>
              <td className="border-b border-border px-3 py-2 tabular-nums">
                <time dateTime={r.obs.observed_at}>{formatDateTime(r.obs.observed_at)}</time>
              </td>
              <td className="border-b border-border px-3 py-2 text-right tabular-nums">{nf(r.obs.view_count)}회</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function NextObservation({ at, now }: { at: string | null; now: number }) {
  if (!at) return null;
  return (
    <p className="text-caption text-text-muted" data-next-observation>
      다음 관측:{" "}
      {isObservationDue(at, now) ? (
        "관측 가능(기록 검증 실행 시 반영)"
      ) : (
        <time dateTime={at}>{formatDateTime(at)} (KST)</time>
      )}
    </p>
  );
}

function ReasonLine({ text }: { text: string }) {
  return (
    <p className="text-body" data-reason>
      <span className="text-text-muted">판정 사유</span> <strong className="font-semibold">{text}</strong>
    </p>
  );
}

function Verdict({ data }: { data: Evidence }) {
  const status = data.candidate.status;
  const reason = reasonLabel(data.reason) ?? (status === "producible" ? "허용 증가율 안" : null);
  const growth = (
    <p key="growth" className="text-body">
      <span className="text-text-muted">증가율</span> <strong className="font-semibold tabular-nums">{formatGrowth(data.growth_pct)}</strong>
    </p>
  );
  const why = reason && <ReasonLine key="reason" text={reason} />;
  // 제외 후보는 왜 빠졌는지를 증가율보다 먼저 보여준다.
  return <div className="flex flex-col gap-1">{status === "excluded" ? [why, growth] : [growth, why]}</div>;
}

function Body({ data, now }: { data: Evidence; now: number }) {
  // 관측이 모자란 분기에서도 서버 사유가 있으면 보인다. 제외 사유는 맨 위에 먼저.
  const label = reasonLabel(data.reason);
  const excluded = data.candidate.status === "excluded";
  const top = label && excluded ? <ReasonLine text={label} /> : null;
  const bottom = label && !excluded ? <ReasonLine text={label} /> : null;
  if (!data.curr) {
    return (
      <div className="flex flex-col gap-2 rounded-card border border-dashed border-input p-4">
        {top}
        <p className="text-body font-semibold">아직 관측 기록이 없습니다</p>
        {bottom}
        <NextObservation at={data.next_observation_at} now={now} />
      </div>
    );
  }
  if (data.needs_prev || !data.prev) {
    return (
      <div className="flex flex-col gap-2">
        {top}
        <p className="rounded-control bg-warning-soft px-3 py-2 text-body font-semibold text-warning-soft-fg">이전 관측값 필요</p>
        <ObservationTable rows={[{ label: "현재", obs: data.curr }]} />
        {bottom}
        <NextObservation at={data.next_observation_at} now={now} />
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <ObservationTable
        rows={[
          { label: "이전", obs: data.prev },
          { label: "현재", obs: data.curr },
        ]}
      />
      <Verdict data={data} />
      <NextObservation at={data.next_observation_at} now={now} />
    </div>
  );
}

type Props = {
  state: EvidenceState;
  /** 목록에서 넘겨받은 제목(로딩·오류 중 표시). */
  fallbackTitle: string;
  titleId: string;
  opsUrl: string;
  onRetry: () => void;
  onClose: () => void;
};

export function EvidenceView({ state, fallbackTitle, titleId, opsUrl, onRetry, onClose }: Props) {
  const data = state.kind === "ok" ? state.data : null;
  const tag = data ? STATUS_TAG[data.candidate.status] : null;
  return (
    <div className="flex flex-col gap-4">
      <nav aria-label="위치" className="pr-10 text-caption text-text-muted">
        소재수집 <span aria-hidden>›</span> 관측 근거
      </nav>
      <header className="flex flex-col gap-1 pr-10">
        <h2 id={titleId} className="line-clamp-2 text-h2 font-bold">
          {data ? data.candidate.title : fallbackTitle}
        </h2>
        {tag && <span className={cn("self-start rounded-chip px-2 py-0.5 text-caption font-semibold", tag.className)}>{tag.label}</span>}
      </header>

      {state.kind === "loading" && (
        <div role="status" data-state="loading" className="flex flex-col gap-2 rounded-card border border-border p-3">
          {[0, 1].map((i) => (
            <div key={i} className="flex gap-3">
              <Bar className="w-12" />
              <Bar className="flex-1" />
              <Bar className="w-20" />
            </div>
          ))}
          <span className="sr-only">관측 근거 불러오는 중…</span>
        </div>
      )}

      {state.kind === "error" && (
        <div role="alert" data-state="error" className="rounded-card border border-danger bg-danger-soft p-4 text-danger-soft-fg">
          <p className="text-body font-semibold">관측 근거를 불러오지 못했습니다.</p>
          <button type="button" onClick={onRetry} disabled={state.retrying} aria-busy={state.retrying || undefined} className={cn(BTN_PRIMARY, "mt-3")}>
            {state.retrying ? "다시 불러오는 중…" : "다시 시도"}
          </button>
        </div>
      )}

      {state.kind === "not_found" && (
        <div role="alert" data-state="not_found" className="rounded-card border border-dashed border-input p-4">
          <p className="text-body font-semibold">후보를 찾을 수 없습니다.</p>
          <p className="text-caption text-text-muted">삭제되었거나 볼 수 없는 후보입니다.</p>
          <button type="button" onClick={onClose} className={cn(BTN_SECONDARY, "mt-3")}>
            목록으로 돌아가기
          </button>
        </div>
      )}

      {data && state.kind === "ok" && <Body data={data} now={state.now} />}

      <div className="flex flex-wrap justify-end gap-2">
        {data?.candidate.status === "producible" && opsUrl && (
          <a href={opsUrl} target="_blank" rel="noopener noreferrer" className={BTN_PRIMARY}>
            영상 만들기<span aria-hidden className="ml-1">→</span>
            <span className="sr-only">(새 탭에서 열림)</span>
          </a>
        )}
        {state.kind !== "not_found" && (
          <button type="button" onClick={onClose} className={BTN_SECONDARY}>
            닫기
          </button>
        )}
      </div>
    </div>
  );
}
