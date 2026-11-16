import "server-only";

import { apiFetch } from "./client";

// A-02 GET /v1/dashboard/summary. 계약: docs/04_API.md#A-02.

export type DashboardPeriod = "24h" | "7d";

export type DashboardSummary = {
  stats: {
    collected: number;
    /** MVP: 항상 null(운영 사이트 연동 전) */
    in_progress: number | null;
    reviewed: number | null;
    upload_pending: number | null;
  };
  stealth: { producible: number; pending: number };
  recent_ready: {
    id: string;
    title: string;
    profile_name: string | null;
    growth_pct: number | null;
    status_changed_at: string;
  }[];
  updated_at: string;
};

export function parsePeriod(value: unknown): DashboardPeriod {
  return value === "24h" ? "24h" : "7d";
}

export function getDashboardSummary(period: DashboardPeriod): Promise<DashboardSummary> {
  return apiFetch<DashboardSummary>("/v1/dashboard/summary", { query: { period } });
}
