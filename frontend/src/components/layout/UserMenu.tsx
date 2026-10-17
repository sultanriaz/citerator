import { useEffect, useState } from "react";
import { Check, ChevronDown, Building2, User } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/cn";
import { getTenantContext, setTenantContext, PRESET_TENANTS } from "@/api/client";
import type { TenantContext } from "@/api/types";

const spring = { type: "spring" as const, stiffness: 480, damping: 32 };

export function UserMenu() {
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState<TenantContext>(getTenantContext);
  const reduce = useReducedMotion();

  useEffect(() => {
    function onTenantChanged(e: Event) {
      const customEvent = e as CustomEvent<TenantContext>;
      if (customEvent.detail) {
        setCurrent(customEvent.detail);
      }
    }
    window.addEventListener("citerator_tenant_changed", onTenantChanged);
    return () => window.removeEventListener("citerator_tenant_changed", onTenantChanged);
  }, []);

  function handleSelect(ctx: TenantContext) {
    setTenantContext(ctx);
    setCurrent(ctx);
    setOpen(false);
    // Reload documents / answers cleanly across pages
    window.location.reload();
  }

  const initials = current.userName
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <div className="relative border-t border-border pt-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Open tenant and user switcher"
        className="flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left hover:bg-surface-elevated transition-colors"
      >
        <motion.span
          aria-hidden
          whileHover={reduce ? undefined : { scale: 1.06 }}
          transition={spring}
          className="flex h-8 w-8 items-center justify-center rounded-full border border-border-strong text-xs font-medium text-primary bg-surface-elevated"
        >
          {initials}
        </motion.span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-primary">
            {current.userName}
          </span>
          <span className="block truncate text-2xs text-secondary">
            {current.tenantName} &middot; {current.userRole}
          </span>
        </span>
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={spring}
          className="text-muted"
        >
          <ChevronDown className="h-4 w-4" aria-hidden />
        </motion.span>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: 6, scale: 0.98 }}
            transition={spring}
            className="absolute bottom-full left-0 mb-2 w-64 origin-bottom rounded-lg border border-border bg-surface-elevated p-1 shadow-xl z-50"
          >
            <div className="px-2 py-1 text-2xs font-semibold text-muted uppercase tracking-wider">
              Switch Tenant Identity
            </div>
            <div className="my-1 border-t border-border" />
            {PRESET_TENANTS.map((t) => {
              const active = t.tenantId === current.tenantId && t.userId === current.userId;
              return (
                <button
                  key={`${t.tenantId}-${t.userId}`}
                  role="menuitem"
                  type="button"
                  onClick={() => handleSelect(t)}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-xs transition-colors",
                    active
                      ? "bg-accent-soft text-accent font-medium"
                      : "text-primary hover:bg-surface"
                  )}
                >
                  <Building2 className="h-4 w-4 shrink-0 text-muted" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">{t.tenantName}</div>
                    <div className="truncate text-2xs text-secondary flex items-center gap-1">
                      <User className="h-2.5 w-2.5 inline" /> {t.userName} ({t.userRole})
                    </div>
                  </div>
                  {active && <Check className="h-4 w-4 shrink-0 text-accent" />}
                </button>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}