import "server-only";

import { createServerClient, type CookieMethodsServer, type CookieOptionsWithName } from "@supabase/ssr";
import { cookies } from "next/headers";
import type { NextRequest, NextResponse } from "next/server";
import type { Database } from "@/types/db";
import { getSupabaseEnv } from "@/server/env";

// 세션은 서버 전용(httpOnly). 서버 컴포넌트·액션·Route Handler와 proxy가 같은 팩토리·옵션을 쓴다.
export const SESSION_COOKIE_OPTIONS: CookieOptionsWithName = {
  httpOnly: true,
  sameSite: "lax",
  secure: process.env.NODE_ENV === "production",
  path: "/",
};

function createSupabase(cookieMethods: CookieMethodsServer) {
  const { url, publishableKey } = getSupabaseEnv();
  return createServerClient<Database>(url, publishableKey, {
    cookies: cookieMethods,
    cookieOptions: SESSION_COOKIE_OPTIONS,
  });
}

/** 서버 컴포넌트·Server Action·Route Handler용 */
export async function createServerSupabase() {
  const store = await cookies();
  return createSupabase({
    getAll: () => store.getAll(),
    setAll: (toSet) => {
      try {
        for (const { name, value, options } of toSet) store.set(name, value, { ...options, ...SESSION_COOKIE_OPTIONS });
      } catch {
        // 서버 컴포넌트에서는 쿠키를 쓸 수 없다. 세션 갱신은 proxy가 맡는다.
      }
    },
  });
}

/** proxy용: 요청 쿠키를 읽고, 갱신된 쿠키를 응답에 쓴다. */
export function createProxySupabase(request: NextRequest, getResponse: () => NextResponse) {
  return createSupabase({
    getAll: () => request.cookies.getAll(),
    setAll: (toSet, headers) => {
      for (const { name, value } of toSet) request.cookies.set(name, value);
      const response = getResponse();
      for (const { name, value, options } of toSet) response.cookies.set(name, value, { ...options, ...SESSION_COOKIE_OPTIONS });
      for (const [key, value] of Object.entries(headers ?? {})) response.headers.set(key, value);
    },
  });
}
