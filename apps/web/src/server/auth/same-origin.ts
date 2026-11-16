import { getAppOrigin } from "@/server/env";

/**
 * 상태를 바꾸는 Route Handler(POST·PUT·PATCH·DELETE) 첫 줄에서 부른다.
 * Origin 헤더가 APP_ORIGIN과 정확히 같지 않으면(없음 포함) 403 응답을 돌려준다. 통과하면 null.
 * Server Action은 Next 자체 Origin 검사에 맡긴다.
 */
export function assertSameOrigin(request: Request, appOrigin: string = getAppOrigin()): Response | null {
  const origin = request.headers.get("origin");
  if (origin !== null && origin === appOrigin) return null;
  return new Response("허용되지 않은 요청 출처입니다.", { status: 403 });
}
