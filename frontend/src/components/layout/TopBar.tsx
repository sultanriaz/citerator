import { Bell } from "lucide-react";

export interface TopBarProps {
  breadcrumbs: string[];
  rightSlot?: React.ReactNode;
}

export function TopBar({ breadcrumbs, rightSlot }: TopBarProps) {
  return (
    <header className="flex items-center gap-4 border-b border-border bg-bg px-6 py-3">
      <nav aria-label="Breadcrumbs" className="flex items-center gap-2 text-xs">
        {breadcrumbs.map((crumb, i) => (
          <span key={crumb} className="flex items-center gap-2">
            {i > 0 && <span className="text-muted">&rsaquo;</span>}
            <span
              className={i === breadcrumbs.length - 1 ? "text-primary" : "text-secondary"}
            >
              {crumb}
            </span>
          </span>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-3">
        {rightSlot}
        <span className="hidden md:inline text-2xs font-medium uppercase tracking-wider text-muted">
          Demo workspace
        </span>
        <button
          type="button"
          aria-label="Notifications"
          className="rounded-md p-1.5 text-secondary hover:bg-surface hover:text-primary transition-colors"
        >
          <Bell className="h-4 w-4" aria-hidden />
        </button>
        <span
          aria-hidden
          className="hidden md:flex h-7 w-7 items-center justify-center rounded-full border border-border-strong text-2xs font-medium text-primary"
        >
          JL
        </span>
      </div>
    </header>
  );
}