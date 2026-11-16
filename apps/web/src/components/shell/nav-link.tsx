import Link from "next/link";
import {
  Archive, BookOpen, Bot, Clapperboard, Download, ExternalLink, FolderOpen, LayoutDashboard,
  Radar, Search, Settings, Stethoscope, Tv, type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { isActive, type NavItem } from "./nav-config";

const ICONS: Record<string, LucideIcon> = {
  layout: LayoutDashboard, bot: Bot, folder: FolderOpen, archive: Archive, download: Download,
  radar: Radar, search: Search, clapper: Clapperboard, stethoscope: Stethoscope, tv: Tv,
  book: BookOpen, external: ExternalLink, settings: Settings,
};

type Props = {
  item: NavItem;
  pathname: string;
  opsUrl?: string;
  variant?: "side" | "tab";
  onNavigate?: () => void;
};

export function NavLink({ item, pathname, opsUrl, variant = "side", onNavigate }: Props) {
  const Icon = ICONS[item.icon] ?? LayoutDashboard;
  const isTab = variant === "tab";
  const hideOnRail = !isTab && "tablet:sr-only desktop:not-sr-only";
  const base = cn(
    "flex items-center gap-3 rounded-control text-body font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring",
    isTab
      ? "shrink-0 whitespace-nowrap rounded-chip border border-border px-3 py-2 tablet:rounded-none tablet:border-0 tablet:border-b-2 tablet:border-transparent"
      : "px-3 py-2.5 tablet:justify-center desktop:justify-start",
  );
  const label = <span className={cn(hideOnRail)}>{item.label}</span>;
  const icon = isTab ? null : <Icon aria-hidden className="size-5 shrink-0" />;

  if (item.href) {
    const active = isActive(pathname, item.href);
    return (
      <Link
        href={item.href}
        aria-current={active ? "page" : undefined}
        title={item.label}
        onClick={onNavigate}
        className={cn(
          base,
          active
            ? isTab
              ? "bg-primary-soft text-primary-soft-fg tablet:border-primary tablet:bg-transparent tablet:text-primary"
              : "bg-primary-soft text-primary-soft-fg"
            : "text-text hover:bg-neutral-soft",
        )}
      >
        {icon}
        {label}
      </Link>
    );
  }

  if (!opsUrl) {
    return (
      <span aria-disabled="true" title="운영 사이트 연동 전" className={cn(base, "cursor-not-allowed text-text-muted")}>
        {icon}
        {label}
        <span className={cn("text-caption", hideOnRail)}>(연동 전)</span>
      </span>
    );
  }

  return (
    <a
      href={opsUrl}
      target="_blank"
      rel="noopener noreferrer"
      onClick={onNavigate}
      title={`${item.label} (새 탭)`}
      className={cn(base, "text-text hover:bg-neutral-soft")}
    >
      {icon}
      {label}
      <span aria-hidden className={cn("text-text-muted", hideOnRail)}>↗</span>
      <span className="sr-only">(새 탭에서 열림)</span>
    </a>
  );
}
