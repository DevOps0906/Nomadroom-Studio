import { redirect } from "next/navigation";
import { formatDateTime } from "@/components/dashboard/format";
import { DashboardForbidden } from "@/components/dashboard/dashboard-view";
import { DEFAULT_OPS_SITE_URL } from "@/components/shell/nav-config";
import type { Profile } from "@/components/profiles/conditions";
import { pickJob, type JobView } from "@/components/monitoring/job";
import { CandidateFilters, CandidateResults, MonitorError, StatusStats } from "@/components/monitoring/monitor-view";
import { MonitorWorkbench } from "@/components/monitoring/monitor-workbench";
import { parseCandidateQuery } from "@/components/monitoring/query";
import { ApiError, SESSION_EXPIRED_PATH, classifyApiError } from "@/server/api/client";
import { getActiveCollectJob, listCandidates, type CandidateList } from "@/server/api/monitor";
import { listProfiles } from "@/server/api/profiles";
import { saveConditions, saveSelection } from "../monitoring/profiles/actions";
import { retryCollect, startCollect, stopCollect, verifyRecords } from "./actions";

export const metadata = { title: "소재수집(정체) · Nomadroom Studio" };

const FALLBACK = "잠시 후 다시 시도하세요.";
const ACTIONS = { startCollect, retryCollect, stopCollect, verifyRecords, saveConditions, saveSelection };

type Settled<T> = { ok: true; value: T } | { ok: false; error: unknown };

async function settle<T>(p: Promise<T>): Promise<Settled<T>> {
  try {
    return { ok: true, value: await p };
  } catch (error) {
    return { ok: false, error };
  }
}

/** MON-01 소재수집(정체) 목록. 읽기(A-03·A-04·A-05 active)는 서버, 실행류는 Server Action. */
export default async function MonitorPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const query = parseCandidateQuery(await searchParams);
  const [profilesRes, candidatesRes, activeRes] = await Promise.all([
    settle(listProfiles()),
    settle(listCandidates(query)),
    settle(getActiveCollectJob()),
  ]);

  for (const r of [profilesRes, candidatesRes, activeRes]) {
    if (r.ok) continue;
    const kind = classifyApiError(r.error);
    // /login으로 바로 보내면 Supabase 세션이 살아 있어 루프가 생긴다. 쿠키를 지우는 경로를 거친다.
    if (kind === "login") redirect(SESSION_EXPIRED_PATH);
    if (kind === "forbidden") return <DashboardForbidden />;
  }

  const message = (r: Settled<unknown>) => (!r.ok && r.error instanceof ApiError ? r.error.message : FALLBACK);
  const profiles: Profile[] | null = profilesRes.ok ? profilesRes.value.items : null;
  // 활성 job 조회 실패는 화면을 막지 않는다(다음 새로고침에서 복구).
  const activeJob: JobView | null = activeRes.ok && activeRes.value ? pickJob(activeRes.value) : null;
  const data: CandidateList | null = candidatesRes.ok ? candidatesRes.value : null;
  const opsUrl = process.env.NEXT_PUBLIC_OPS_SITE_URL ?? DEFAULT_OPS_SITE_URL;

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4 tablet:gap-5">
      <MonitorWorkbench
        profiles={profiles}
        profilesError={profilesRes.ok ? null : message(profilesRes)}
        activeJob={activeJob}
        actions={ACTIONS}
        sessionExpiredPath={SESSION_EXPIRED_PATH}
        updated={
          <p className="text-caption text-text-muted">
            마지막 갱신: {data ? <time dateTime={data.updated_at}>{formatDateTime(data.updated_at)}</time> : "기록 없음"}
          </p>
        }
      >
        {data ? (
          <>
            <StatusStats counts={data.counts} query={query} />
            <CandidateFilters
              query={query}
              categories={data.categories}
              profiles={(profiles ?? []).map((p) => ({ id: p.id, name: p.name }))}
            />
            <CandidateResults data={data} query={query} opsUrl={opsUrl} />
          </>
        ) : (
          <MonitorError title="후보를 불러오지 못했습니다" message={message(candidatesRes)} />
        )}
      </MonitorWorkbench>
    </div>
  );
}
