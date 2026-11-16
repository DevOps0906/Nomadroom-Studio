import "server-only";

import { createServerSupabase } from "@/server/supabase/client";

type ServerSupabase = Awaited<ReturnType<typeof createServerSupabase>>;

/** 로컬 JWT 검증(getClaims)으로 확인한 사용자. 세션이 없거나 무효면 null. */
export async function getVerifiedClaims(supabase: Pick<ServerSupabase, "auth">) {
  const { data, error } = await supabase.auth.getClaims();
  if (error || !data?.claims?.sub) return null;
  return data.claims;
}

type CookieStore = { getAll(): { name: string }[]; delete(name: string): unknown };

/** signOut이 실패해도 브라우저 세션이 남지 않도록 Supabase 세션 쿠키(sb-*)를 직접 지운다. */
export function clearSupabaseCookies(store: CookieStore) {
  for (const { name } of store.getAll()) if (name.startsWith("sb-")) store.delete(name);
}
