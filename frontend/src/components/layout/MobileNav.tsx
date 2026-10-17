import { useState } from "react";
import { NavLink } from "react-router-dom";
import { FileText, FlaskConical, Menu, MessageSquare, Settings as SettingsIcon, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { ThemeToggle } from "./ThemeToggle";

const ITEMS = [
  { to: "/", label: "Ask", icon: MessageSquare, end: true },
  { to: "/documents", label: "Documents", icon: FileText, end: false },
  { to: "/evaluation", label: "Evaluation", icon: FlaskConical, end: false },
  { to: "/settings", label: "Settings", icon: SettingsIcon, end: false },
];

export function MobileNav() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Close navigation menu" : "Open navigation menu"}
        aria-expanded={open}
        className="md:hidden fixed top-3 right-3 z-40 rounded-md border border-border bg-surface p-2 text-primary"
      >
        {open ? <X className="h-4 w-4" aria-hidden /> : <Menu className="h-4 w-4" aria-hidden />}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Navigation"
          className="md:hidden fixed inset-0 z-30 bg-bg/95 backdrop-blur pt-16"
        >
          <nav aria-label="Primary mobile" className="mx-auto w-64">
            <ul className="space-y-1">
              {ITEMS.map(({ to, label, icon: Icon, end }) => (
                <li key={to}>
                  <NavLink
                    to={to}
                    end={end}
                    onClick={() => setOpen(false)}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-3 rounded-md px-3 py-2 text-sm",
                        isActive
                          ? "bg-accent-soft text-accent font-medium"
                          : "text-secondary hover:bg-surface hover:text-primary"
                      )
                    }
                  >
                    <Icon className="h-4 w-4" aria-hidden />
                    {label}
                  </NavLink>
                </li>
              ))}
            </ul>
            <div className="mt-4">
              <ThemeToggle />
            </div>
          </nav>
        </div>
      )}
    </>
  );
}