import { NextResponse, type NextRequest } from "next/server";
import { cookies } from "next/headers";
import { createServerSupabase } from "@/server/supabase/client";
import { assertSameOrigin } from "@/server/auth/same-origin";
import { clearSupabaseCookies } from "@/server/auth/session";
import { RECOVERY_COOKIE } from "@/server/auth/recovery";

export async function POST(request: NextRequest) {
  const denied = assertSameOrigin(request);
  if (denied) return denied;
  const supabase = await createServerSupabase();
  const { error } = await supabase.auth.signOut({ scope: "local" });
  const store = await cookies();
  if (error) clearSupabaseCookies(store);
  store.delete(RECOVERY_COOKIE);
  return NextResponse.redirect(new URL("/login", request.url), 303);
}
