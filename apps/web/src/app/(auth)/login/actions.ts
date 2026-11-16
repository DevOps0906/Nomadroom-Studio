"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";
import type { AuthErrorKind, LoginState } from "@/components/auth/auth-messages";
import { createServerSupabase } from "@/server/supabase/client";
import { clientIp, loginLimiter } from "@/server/auth/rate-limit";
import { safeNext } from "@/server/auth/safe-next";
import { getAppOrigin } from "@/server/env";

/** 실패 기록: 사유만 남긴다(이메일·IP·비밀번호 금지). */
function logLoginFailed(reason: AuthErrorKind) {
  console.warn(JSON.stringify({ event: "login_failed", reason }));
}

export async function login(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const next = safeNext(String(formData.get("next") ?? ""), getAppOrigin());

  const fail = (reason: AuthErrorKind): LoginState => {
    logLoginFailed(reason);
    return { error: reason, email };
  };

  if (!loginLimiter.hit(clientIp(await headers()))) return fail("rate_limited");
  if (!email || !password) return fail("credentials");

  const supabase = await createServerSupabase();
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) {
    if (error.status === 429) return fail("rate_limited");
    if (error.status === 400) return fail("credentials");
    return fail("unavailable");
  }
  redirect(next);
}
