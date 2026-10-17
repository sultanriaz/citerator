import { useEffect } from "react";
import { AlertTriangle, CheckCircle2, X } from "lucide-react";
import { cn } from "@/lib/cn";

export type ToastTone = "success" | "error";

export interface ToastProps {
  tone: ToastTone;
  message: string;
  onDismiss: () => void;
  durationMs?: number;
}

export function Toast({ tone, message, onDismiss, durationMs = 5000 }: ToastProps) {
  useEffect(() => {
    const t = window.setTimeout(onDismiss, durationMs);
    return () => window.clearTimeout(t);
  }, [onDismiss, durationMs]);

  const Icon = tone === "success" ? CheckCircle2 : AlertTriangle;
  const cls =
    tone === "success"
      ? "border-success/30 bg-success/10 text-success"
      : "border-danger/30 bg-danger/10 text-danger";

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex items-start gap-2 rounded-lg border px-3 py-2.5 text-xs shadow-lg",
        cls
      )}
    >
      <Icon className="h-4 w-4 mt-0.5 shrink-0" aria-hidden />
      <span className="flex-1 text-primary">{message}</span>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss notification"
        className="rounded p-0.5 text-secondary hover:bg-surface hover:text-primary"
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}