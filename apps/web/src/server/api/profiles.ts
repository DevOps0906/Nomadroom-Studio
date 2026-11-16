import "server-only";

import type { ConditionsPayload, Profile } from "@/components/profiles/conditions";
import { apiFetch } from "./client";

// A-03 프로필. 계약: docs/04_API.md#A-03, tasks/task-010.md#구현 결정.

export function listProfiles(): Promise<{ items: Profile[] }> {
  return apiFetch<{ items: Profile[] }>("/v1/profiles");
}

/** 조건 8필드 + updated_at 전체 교체(낙관적 잠금). name·selected는 보내지 않는다. */
export function updateProfile(id: string, body: ConditionsPayload): Promise<Profile> {
  return apiFetch<Profile>(`/v1/profiles/${encodeURIComponent(id)}`, { method: "PUT", body });
}

/** 검증 대상 선택(최대 3, 빈 배열 = 전부 해제). 원자적 갱신. */
export function setProfileSelection(ids: string[]): Promise<{ selected_ids: string[] }> {
  return apiFetch<{ selected_ids: string[] }>("/v1/profiles/selection", { method: "PUT", body: { selected_ids: ids } });
}
