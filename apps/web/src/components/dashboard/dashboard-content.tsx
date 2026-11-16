import { redirect } from "next/navigation";
import { ApiError, SESSION_EXPIRED_PATH, classifyApiError } from "@/server/api/client";
import { getDashboardSummary, type DashboardPeriod, type DashboardSummary } from "@/server/api/dashboard";
import { DashboardError, DashboardForbidden, DashboardSummaryView } from "./dashboard-view";

const FALLBACK_MESSAGE = "잠시 후 다시 시도하세요.";

/** A-02를 서버에서 불러와 상태(성공·빈·오류·권한 없음)를 고른다. */
export async function DashboardContent({ period }: { period: DashboardPeriod }) {
  let summary: DashboardSummary;
  try {
    summary = await getDashboardSummary(period);
  } catch (e) {
    const kind = classifyApiError(e);
    // /login으로 바로 보내면 Supabase 세션이 살아 있어 proxy가 되돌려 보낸다(루프). 쿠키를 지우는 경로를 거친다.
    if (kind === "login") redirect(SESSION_EXPIRED_PATH);
    if (kind === "forbidden") return <DashboardForbidden />;
    return <DashboardError message={e instanceof ApiError ? e.message : FALLBACK_MESSAGE} />;
  }
  return <DashboardSummaryView summary={summary} />;
}
