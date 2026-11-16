"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";
import { SidebarNav } from "./sidebar-nav";
import { NavLink } from "./nav-link";
import { CRUMBS, TABS } from "./nav-config";
import { SignOutButton } from "@/components/auth/sign-out-button";

export function AppShell({ children, opsUrl }: { children: ReactNode; opsUrl?: string }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const crumbs = CRUMBS[pathname] ?? [];
  const menuRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);

  useEffect(() => {
    if (open) {
      closeRef.current?.focus();
      const onKey = (e: KeyboardEvent) => {
        if (e.key === "Escape") setOpen(false);
      };
      document.addEventListener("keydown", onKey);
      wasOpen.current = true;
      return () => document.removeEventListener("keydown", onKey);
    }
    if (wasOpen.current) {
      wasOpen.current = false;
      menuRef.current?.focus();
    }
  }, [open]);

  return (
    <div className="min-h-screen overflow-x-clip bg-bg text-text">
      {open && (
        <button
          type="button"
          aria-label="메뉴 닫기"
          onClick={() => setOpen(false)}
          className="fixed inset-0 z-30 bg-text/40 tablet:hidden outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      )}
      <aside
        id="app-sidebar"
        className={`fixed inset-y-0 left-0 z-40 w-64 border-r border-border bg-surface transition-transform tablet:w-16 tablet:translate-x-0 desktop:w-60 ${open ? "translate-x-0" : "invisible -translate-x-full tablet:visible"}`}
      >
        <button
          ref={closeRef}
          type="button"
          aria-label="메뉴 닫기"
          onClick={() => setOpen(false)}
          className="absolute right-2 top-2 rounded-control p-2 tablet:hidden outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <X aria-hidden className="size-5" />
        </button>
        <SidebarNav pathname={pathname} opsUrl={opsUrl} onNavigate={() => setOpen(false)} />
      </aside>

      <div inert={open} className="min-w-0 tablet:pl-16 desktop:pl-60">
        <header className="sticky top-0 z-20 border-b border-border bg-surface">
          <div className="flex items-center gap-3 px-4 py-3 tablet:px-6">
            <button
              ref={menuRef}
              type="button"
              aria-label="메뉴 열기"
              aria-expanded={open}
              aria-controls="app-sidebar"
              onClick={() => setOpen(true)}
              className="rounded-control p-2 tablet:hidden outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Menu aria-hidden className="size-5" />
            </button>
            <nav aria-label="현재 위치" className="text-body text-text-muted">
              <ol className="flex items-center gap-2">
                {crumbs.map((c, i) => (
                  <li key={c} className="flex items-center gap-2">
                    {i > 0 && <span aria-hidden>/</span>}
                    <span
                      aria-current={i === crumbs.length - 1 ? "page" : undefined}
                      className={i === crumbs.length - 1 ? "font-semibold text-text" : undefined}
                    >
                      {c}
                    </span>
                  </li>
                ))}
              </ol>
            </nav>
            <div className="ml-auto">
              <SignOutButton />
            </div>
          </div>
          <nav aria-label="작업 탭" className="flex min-w-0 gap-2 overflow-x-auto px-4 pb-3 tablet:gap-4 tablet:px-6 tablet:pb-0">
            {TABS.map((t) => (
              <NavLink key={t.key} item={t} pathname={pathname} opsUrl={opsUrl} variant="tab" />
            ))}
          </nav>
        </header>
        <main className="p-4 tablet:p-6">{children}</main>
      </div>
    </div>
  );
}
