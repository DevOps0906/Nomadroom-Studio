// 인증 경계 경로. proxy가 쓴다.
export const GUEST_ONLY_PATHS = ["/login", "/forgot-password"];
export const PUBLIC_PATHS = [...GUEST_ONLY_PATHS, "/auth/confirm", "/auth/signout", "/terms"];

export function matchesPath(pathname: string, paths: string[]): boolean {
  return paths.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}
