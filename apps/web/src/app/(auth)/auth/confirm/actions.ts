"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { createServerSupabase, SESSION_COOKIE_OPTIONS } from "@/server/supabase/client";
import { getVerifiedClaims } from "@/server/auth/session";
import { RECOVERY_COOKIE, RECOVERY_MAX_AGE } from "@/server/auth/recovery";

// 재설정 링크 확인(POST): token_hash 검증(type=recovery만) → 표식 쿠키 → /reset-password.
// 메일 스캐너가 GET으로 링크를 열어도 토큰이 소모되지 않도록 검증은 여기서만 한다.
export async function confirmRecovery(formData: FormData): Promise<void> {
  const tokenHash = String(formData.get("token_hash") ?? "");
  const type = String(formData.get("type") ?? "");
  if (!tokenHash || type !== "recovery") redirect("/forgot-password?error=link");

  const supabase = await createServerSupabase();
  const { error } = await supabase.auth.verifyOtp({ type: "recovery", token_hash: tokenHash });
  const claims = error ? null : await getVerifiedClaims(supabase);
  if (!claims || typeof claims.session_id !== "string") redirect("/forgot-password?error=link");

  (await cookies()).set(RECOVERY_COOKIE, claims.session_id, { ...SESSION_COOKIE_OPTIONS, maxAge: RECOVERY_MAX_AGE });
  redirect("/reset-password");
}
