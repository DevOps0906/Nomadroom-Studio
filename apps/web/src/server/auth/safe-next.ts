// 로그인 후 이동 경로(next) 검증. 같은 Origin의 경로만 허용하고, 실패하면 "/".
// 입력은 이미 디코드된 값(searchParams·formData)이다. 다시 디코드하지 않는다.
const CONTROL_OR_SPACE = /[\s\u0000-\u001f\u007f]/;

function isUnsafePath(path: string): boolean {
  return !path.startsWith("/") || path[1] === "/" || path[1] === "\\" || CONTROL_OR_SPACE.test(path);
}

export function safeNext(raw: string | null | undefined, appOrigin: string): string {
  if (!raw || isUnsafePath(raw)) return "/";
  try {
    const origin = new URL(appOrigin).origin;
    const url = new URL(raw, origin);
    if (url.origin !== origin) return "/";
    // 정규화 결과(예: "/.//evil.com" → "//evil.com")를 다시 검사한다.
    if (isUnsafePath(url.pathname)) return "/";
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return "/";
  }
}
