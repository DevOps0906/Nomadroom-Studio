import { NextResponse, type NextRequest } from "next/server";
import { createProxySupabase } from "@/server/supabase/client";
import { getVerifiedClaims } from "@/server/auth/session";
import { safeNext } from "@/server/auth/safe-next";
import { GUEST_ONLY_PATHS, PUBLIC_PATHS, matchesPath } from "@/server/auth/paths";
import { getAppOrigin } from "@/server/env";

// 인증 경계: 세션 갱신 + 미로그인 리다이렉트. (dashboard)/layout.tsx가 한 번 더 확인한다(이중 방어).
export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });
  const supabase = createProxySupabase(request, () => {
    response = NextResponse.next({ request });
    return response;
  });
  const claims = await getVerifiedClaims(supabase);
  const { pathname, search } = request.nextUrl;

  const redirectTo = (target: string) => {
    const redirect = NextResponse.redirect(new URL(target, request.url));
    for (const cookie of response.cookies.getAll()) redirect.cookies.set(cookie);
    // setAll이 넣은 헤더(Cache-Control 등)도 옮긴다. Next 내부 헤더(x-middleware-*)와 쿠키는 제외.
    for (const [key, value] of response.headers) {
      if (!key.startsWith("x-middleware-") && key !== "set-cookie") redirect.headers.set(key, value);
    }
    return redirect;
  };

  if (!claims && !matchesPath(pathname, PUBLIC_PATHS)) {
    // /api/*(폴링 중계)는 리다이렉트 대신 JSON 401. 클라이언트가 세션 정리 경로로 이동한다.
    if (matchesPath(pathname, ["/api"])) {
      const res = NextResponse.json(
        { code: "UNAUTHENTICATED", message: "로그인이 필요합니다." },
        { status: 401, headers: { "Cache-Control": "no-store" } },
      );
      for (const cookie of response.cookies.getAll()) res.cookies.set(cookie);
      return res;
    }
    const next = safeNext(`${pathname}${search}`, getAppOrigin());
    return redirectTo(next === "/" ? "/login" : `/login?next=${encodeURIComponent(next)}`);
  }
  if (claims && matchesPath(pathname, GUEST_ONLY_PATHS)) return redirectTo("/");
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|avif)$).*)"],
};
