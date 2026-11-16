import { NextResponse, type NextRequest } from "next/server";
import { cookies } from "next/headers";
import { createServerSupabase } from "@/server/supabase/client";
import { clearSupabaseCookies } from "@/server/auth/session";
import { getDashboardSummary } from "@/server/api/dashboard";

// API가 401을 줄 때의 탈출구. Supabase 세션은 유효한데 API만 거부하면 /login → proxy가 다시 대시보드로 보내 루프가 생긴다.
// Server Component는 쿠키를 쓸 수 없으므로 여기서 세션 쿠키를 지운 뒤 /login으로 보낸다.
// GET이라 외부 링크·프리페치로도 열릴 수 있어, API가 이 세션을 실제로 거부할 때만 로그아웃한다.
export async function GET(request: NextRequest) {
  try {
    await getDashboardSummary("24h");
    return NextResponse.redirect(new URL("/dashboard", request.url), 303);
  } catch {
    // 401·오류 모두 로그아웃: 대시보드로 되돌리면 API 상태에 따라 다시 이 경로로 올 수 있다.
  }
  const supabase = await createServerSupabase();
  await supabase.auth.signOut({ scope: "local" }).catch(() => undefined);
  clearSupabaseCookies(await cookies());
  return NextResponse.redirect(new URL("/login", request.url), 303);
}
