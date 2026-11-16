import { ChevronDown } from "lucide-react";
import { NavLink } from "./nav-link";
import { FOOTER_LINKS, NAV } from "./nav-config";

type Props = { pathname: string; opsUrl?: string; onNavigate?: () => void };

export function SidebarNav({ pathname, opsUrl, onNavigate }: Props) {
  const common = { pathname, opsUrl, onNavigate };
  return (
    <div className="flex h-full flex-col gap-4 p-3">
      <div className="flex items-center gap-3 px-3 py-2 tablet:justify-center desktop:justify-start">
        <span aria-hidden className="grid size-8 shrink-0 grid-cols-2 gap-1 rounded-control bg-primary p-1.5">
          <span className="rounded-chip bg-primary-fg" />
          <span className="rounded-chip bg-primary-fg" />
          <span className="rounded-chip bg-primary-fg" />
          <span className="rounded-chip bg-primary-fg" />
        </span>
        <span className="flex flex-col leading-tight tablet:sr-only desktop:not-sr-only">
          <span className="text-h2 font-bold text-primary">Nomadroom</span>
          <span className="text-caption font-semibold uppercase tracking-widest text-text-muted">Studio</span>
        </span>
      </div>
      {opsUrl ? (
        <a
          href={opsUrl}
          target="_blank"
          rel="noopener noreferrer"
          onClick={onNavigate}
          className="rounded-control bg-primary px-3 py-2.5 text-center text-body font-semibold text-primary-fg hover:bg-primary-hover focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span aria-hidden>＋</span>
          <span className="tablet:sr-only desktop:not-sr-only"> 새 영상 만들기 ↗</span>
          <span className="sr-only">(새 탭에서 열림)</span>
        </a>
      ) : (
        <span aria-disabled="true" className="cursor-not-allowed rounded-control bg-neutral-soft px-3 py-2.5 text-center text-body text-text-muted">
          <span aria-hidden>＋</span>
          <span className="tablet:sr-only desktop:not-sr-only"> 새 영상 만들기 (연동 전)</span>
        </span>
      )}
      <nav aria-label="주 메뉴" className="flex flex-1 flex-col gap-1 overflow-y-auto">
        {NAV.map((entry) =>
          "children" in entry ? (
            <div key={entry.key} role="group" aria-label={entry.label} className="flex flex-col gap-1">
              <p className="flex items-center gap-3 px-3 py-2.5 text-body font-semibold text-text tablet:sr-only desktop:not-sr-only">
                <span className="flex-1">{entry.label}</span>
                <ChevronDown aria-hidden className="size-4 text-text-muted" />
              </p>
              <div className="ml-5 flex flex-col gap-1 border-l border-border pl-2 tablet:ml-0 tablet:border-l-0 tablet:pl-0 desktop:ml-5 desktop:border-l desktop:pl-2">
                {entry.children.map((c) => (
                  <NavLink key={c.key} item={c} {...common} />
                ))}
              </div>
            </div>
          ) : (
            <NavLink key={entry.key} item={entry} {...common} />
          ),
        )}
      </nav>
      <div className="flex flex-col gap-1 border-t border-border pt-3">
        {FOOTER_LINKS.map((l) => (
          <NavLink key={l.key} item={l} {...common} />
        ))}
      </div>
    </div>
  );
}
