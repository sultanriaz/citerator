import { motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/cn";

export type PillTone = "healthy" | "warning" | "danger" | "neutral";

const TONE_DOT: Record<PillTone, string> = {
  healthy: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  neutral: "bg-muted",
};

export interface StatusPillProps {
  tone: PillTone;
  label: string;
  onClick?: () => void;
  ariaLabel?: string;
}

export function StatusPill({ tone, label, onClick, ariaLabel }: StatusPillProps) {
  const dot = TONE_DOT[tone];
  const reduce = useReducedMotion();
  const pulse = !reduce && (tone === "healthy" || tone === "neutral");

  const inner = (
    <>
      <span className="relative flex h-1.5 w-1.5 shrink-0" aria-hidden>
        {pulse && (
          <motion.span
            className={cn("absolute inset-0 rounded-full", dot)}
            animate={{ scale: [1, 2.2, 2.2], opacity: [0.55, 0, 0] }}
            transition={{ duration: 2, repeat: Infinity, ease: "easeOut" }}
          />
        )}
        <span className={cn("relative h-1.5 w-1.5 rounded-full", dot)} />
      </span>
      <span className="truncate">{label}</span>
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        aria-label={ariaLabel ?? label}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-primary hover:bg-surface-elevated transition-colors"
      >
        {inner}
      </button>
    );
  }

  return (
    <div className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-primary">
      {inner}
    </div>
  );
}