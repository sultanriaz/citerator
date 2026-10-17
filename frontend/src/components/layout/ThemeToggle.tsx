import { Moon, Sun } from "lucide-react";
import { motion, useReducedMotion } from "framer-motion";
import { useTheme } from "@/hooks/useTheme";

const spring = { type: "spring" as const, stiffness: 500, damping: 32, mass: 0.7 };

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const isDark = theme === "dark";
  const reduce = useReducedMotion();

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      aria-pressed={isDark}
      className="group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-secondary hover:bg-surface-elevated hover:text-primary transition-colors"
    >
      <motion.span
        className="inline-flex h-3.5 w-3.5 items-center justify-center"
        animate={reduce ? undefined : { rotate: isDark ? 0 : 180 }}
        transition={spring}
      >
        {isDark ? (
          <Moon className="h-3.5 w-3.5" aria-hidden />
        ) : (
          <Sun className="h-3.5 w-3.5" aria-hidden />
        )}
      </motion.span>

      <span>{isDark ? "Dark appearance" : "Light appearance"}</span>

      <span
        className={
          "ml-auto relative inline-flex h-4 w-7 items-center rounded-full transition-colors " +
          (isDark ? "bg-accent" : "bg-border-strong")
        }
        aria-hidden
      >
        <motion.span
          layout
          transition={spring}
          className="absolute h-3 w-3 rounded-full bg-surface"
          style={{ left: isDark ? "14px" : "2px" }}
        />
      </span>
    </button>
  );
}