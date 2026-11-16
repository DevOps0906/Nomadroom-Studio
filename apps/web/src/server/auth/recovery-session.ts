import "server-only";

import { cookies } from "next/headers";
import { createServerSupabase } from "@/server/supabase/client";
import { getVerifiedClaims } from "@/server/auth/session";
import { RECOVERY_COOKIE } from "@/server/auth/recovery";

/** recovery 링크로 막 만든 세션이면 supabase 클라이언트를, 아니면 null. */
export async function getRecoverySession() {
  const supabase = await createServerSupabase();
  const claims = await getVerifiedClaims(supabase);
  const marker = (await cookies()).get(RECOVERY_COOKIE)?.value;
  if (!claims || !marker || typeof claims.session_id !== "string" || marker !== claims.session_id) return null;
  return supabase;
}
