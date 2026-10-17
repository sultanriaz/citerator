import { NavLink, useLocation } from "react-router-dom";
import {
  FileText,
  FlaskConical,
  MessageSquare,
  Settings as SettingsIcon,
  ShieldCheck,
} from "lucide-react";
import { motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/cn";
import { useHealthStatus } from "@/hooks/useHealthStatus";
import { StatusPill } from "@/components/shared/StatusPill";
import { ThemeToggle } from "./ThemeToggle";
import { UserMenu } from "./UserMenu";
import { getTenantContext } from "@/api/client";

const NAV_ITEMS = [
  { to: "/", label: "Ask", icon: MessageSquare, end: true },
  { to: "/documents", label: "Documents", icon: FileText, end: false },
  { to: "/evaluation", label: "Evaluation", icon: FlaskConical, end: false },
  { to: "/settings", label: "Settings", icon: SettingsIcon, end: false },
];

const spring = { type: "spring" as const, stiffness: 420, damping: 34, mass: 0.9 };

export function Sidebar() {
  const { status } = useHealthStatus();
  const location = useLocation();
  const reduce = useReducedMotion();

  const pillTone =
    status === "healthy" ? "healthy" : status === "checking" ? "neutral" : "danger";
  const pillLabel =
    status === "healthy"
      ? "Pipeline healthy"
      : status === "checking"
        ? "Checking pipeline..."
        : "Unable to reach API";

  return (
    <aside className="hidden md:flex md:w-60 md:shrink-0 md:flex-col border-r border-border bg-bg [perspective:1200px]">
      <BrandHeader reduce={!!reduce} />

      <WorkspaceCard reduce={!!reduce} />

      <nav aria-label="Primary" className="px-3">
        <div className="px-2 pb-2 text-2xs font-medium uppercase tracking-wider text-muted">
          Workspace
        </div>
        <ul className="space-y-0.5">
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => {
            const active = end
              ? location.pathname === to
              : location.pathname === to || location.pathname.startsWith(to + "/");
            return (
              <li key={to}>
                <NavLink
                  to={to}
                  end={end}
                  className="relative flex items-center gap-3 rounded-md px-2 py-1.5 text-sm"
                >
                  {active && (
                    <motion.span
                      layoutId="sidebar-active-bg"
                      transition={spring}
                      className="absolute inset-0 rounded-md bg-accent-soft"
                      aria-hidden
                    />
                  )}

                  <motion.span
                    className="relative z-10 flex h-4 w-4 shrink-0 items-center justify-center"
                    animate={
                      active
                        ? { rotateY: 0, scale: 1 }
                        : { rotateY: 0, scale: 1 }
                    }
                    whileHover={reduce ? undefined : { rotateY: -18, scale: 1.08 }}
                    transition={spring}
                    style={{ transformStyle: "preserve-3d" }}
                  >
                    <Icon
                      className={cn(
                        "h-4 w-4 transition-colors",
                        active ? "text-accent" : "text-secondary"
                      )}
                      aria-hidden
                    />
                  </motion.span>

                  <span
                    className={cn(
                      "relative z-10 truncate transition-colors",
                      active ? "text-accent font-medium" : "text-secondary"
                    )}
                  >
                    {label}
                  </span>

                  {active && (
                    <motion.span
                      layoutId="sidebar-active-edge"
                      transition={spring}
                      className="absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-r bg-accent"
                      aria-hidden
                    />
                  )}
                </NavLink>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="mt-auto px-3 pb-3">
        <motion.div
          initial={reduce ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...spring, delay: 0.05 }}
          whileHover={reduce ? undefined : { y: -2 }}
          className="mb-4 rounded-xl border border-border bg-surface px-3 py-3 shadow-sm"
        >
          <ShieldCheck className="h-4 w-4 text-accent" aria-hidden />
          <div className="mt-2 text-xs font-medium text-primary leading-snug">
            Built for evidence.
            <br />
            Not assumptions.
          </div>
          <div className="mt-1.5 text-2xs leading-relaxed text-secondary">
            Every answer, iterated back to its source.
          </div>
        </motion.div>

        <StatusPill
          tone={pillTone as "healthy" | "warning" | "danger" | "neutral"}
          label={pillLabel}
          ariaLabel={`Pipeline status: ${pillLabel}`}
        />

        <div className="mt-1">
          <ThemeToggle />
        </div>

        <UserMenu />
      </div>
    </aside>
  );
}

function BrandHeader({ reduce }: { reduce: boolean }) {
  return (
    <div className="flex items-center gap-2 px-5 pt-5 pb-6">
      <motion.span
        className="flex h-6 w-6 items-center justify-center text-accent"
        aria-hidden
        initial={reduce ? false : { rotateY: 0 }}
        whileHover={reduce ? undefined : { rotateY: 360 }}
        transition={{ duration: 0.9, ease: [0.4, 0, 0.2, 1] }}
        style={{ transformStyle: "preserve-3d" }}
      >
        <span className="text-sm font-mono">[ ]</span>
      </motion.span>
      <span className="text-lg font-semibold tracking-tight text-primary">
        Citerator
      </span>
      <span className="rounded border border-border px-1.5 py-0.5 text-2xs font-medium uppercase text-secondary">
        Beta
      </span>
    </div>
  );
}

function WorkspaceCard({ reduce }: { reduce: boolean }) {
  const tenant = getTenantContext();
  const initial = (tenant.tenantName || "T").slice(0, 1).toUpperCase();
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...spring, delay: 0.02 }}
      whileHover={reduce ? undefined : { y: -1, rotateX: 2 }}
      className="mx-3 mb-6 flex items-center gap-3 rounded-xl border border-border bg-surface px-3 py-3 shadow-sm"
      style={{ transformStyle: "preserve-3d" }}
    >
      <span
        className="flex h-8 w-8 items-center justify-center rounded-lg border border-border-strong text-xs font-semibold text-primary"
        aria-hidden
      >
        {initial}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-primary">
          {tenant.tenantName}
        </div>
        <div className="truncate font-mono text-2xs text-secondary">
          {tenant.tenantId}
        </div>
      </div>
    </motion.div>
  );
}