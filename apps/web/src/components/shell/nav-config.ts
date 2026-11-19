export type NavItem = {
  key: string;
  label: string;
  /** 내부 경로. 없으면 운영 사이트(외부) 링크 */
  href?: string;
  icon: string;
};

export type NavEntry = NavItem | { key: string; label: string; icon: string; children: NavItem[] };

export const NAV: NavEntry[] = [
  { key: "dashboard", label: "대시보드", href: "/dashboard", icon: "layout" },
  { key: "room", label: "AI 작업방", icon: "bot" },
  {
    key: "material",
    label: "소재",
    icon: "folder",
    children: [
      { key: "vault", label: "소재보관함", icon: "archive" },
      { key: "collect", label: "소재수집(일반)", icon: "download" },
      { key: "monitor", label: "소재수집(정체)", href: "/monitor", icon: "radar" },
    ],
  },
  { key: "topic", label: "주제 발굴", icon: "search" },
  { key: "make", label: "제작·업로드", icon: "clapper" },
  { key: "production", label: "제작", href: "/production", icon: "clapper" },
  { key: "diag", label: "진단 · 채널 관리", icon: "stethoscope" },
  { key: "learn", label: "배우기", icon: "book" },
];

export const FOOTER_LINKS: NavItem[] = [
  { key: "ops", label: "운영 화면 열기", icon: "external" },
  { key: "settings", label: "설정", icon: "settings" },
];

export const TABS: NavItem[] = [
  { key: "dashboard", label: "대시보드", href: "/dashboard", icon: "layout" },
  { key: "topic", label: "주제 발굴", icon: "search" },
  { key: "monitor", label: "소재수집(정체)", href: "/monitor", icon: "radar" },
];

export const CRUMBS: Record<string, string[]> = {
  "/dashboard": ["워크스페이스", "대시보드"],
  "/monitor": ["워크스페이스", "소재수집(정체)"],
};

export function isActive(pathname: string, href?: string): boolean {
  return !!href && (pathname === href || pathname.startsWith(`${href}/`));
}

/** 운영 사이트 기본 주소. NEXT_PUBLIC_OPS_SITE_URL이 빈 문자열이면 연동 전(비활성) 표시. */
export const DEFAULT_OPS_SITE_URL = "https://greenroom-studio-kr.ovalsorrel16.chatgpt.site/";
