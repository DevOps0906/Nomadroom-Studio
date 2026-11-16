"use server";

import { headers } from "next/headers";
import type { AuthErrorKind } from "@/components/auth/auth-messages";
import { createServerSupabase } from "@/server/supabase/client";
import { clientIp, loginLimiter } from "@/server/auth/rate-limit";

export type ForgotState = { sent: boolean; error: AuthErrorKind | null; email: string };

// 가입 여부를 드러내지 않도록 존재하지 않는 이메일도 같은 "보냄" 안내를 준다.
export async function requestPasswordReset(_prev: ForgotState, formData: FormData): Promise<ForgotState> {
  const email = String(formData.get("email") ?? "").trim();
  if (!loginLimiter.hit(`reset:${clientIp(await headers())}`)) return { sent: false, error: "rate_limited", email };
  if (!email) return { sent: false, error: null, email };

  const supabase = await createServerSupabase();
  const { error } = await supabase.auth.resetPasswordForEmail(email);
  if (error?.status === 429) return { sent: false, error: "rate_limited", email };
  if (error && (error.status ?? 500) >= 500) return { sent: false, error: "unavailable", email };
  return { sent: true, error: null, email };
}
