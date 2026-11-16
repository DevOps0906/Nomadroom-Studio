// 썸네일 허용 목록(순수). vidIQ·YouTube 유래 URL은 비신뢰: https + host i.ytimg.com + 포트·userinfo 없음만 쓴다.
export const THUMBNAIL_HOST = "i.ytimg.com";

export function safeThumbnailUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" || url.hostname !== THUMBNAIL_HOST) return null;
  if (url.port !== "" || url.username !== "" || url.password !== "") return null;
  return url.href;
}
