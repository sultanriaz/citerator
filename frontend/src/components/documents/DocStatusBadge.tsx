import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

export function DocStatusBadge({ status }: { status: string }) {
  const inProgress = !["indexed", "failed", "empty"].includes(status);

  const { Icon, cls, label } = status === "indexed"
    ? { Icon: CheckCircle2, cls: "text-success border-success/30 bg-success/10", label: "Indexed" }
    : status === "failed"
      ? { Icon: AlertCircle, cls: "text-danger border-danger/30 bg-danger/10", label: "Failed" }
      : status === "empty"
        ? { Icon: AlertCircle, cls: "text-warning border-warning/30 bg-warning/10", label: "Empty" }
        : { Icon: Loader2, cls: "text-secondary border-border bg-surface-elevated", label: status };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-2xs font-medium",
        cls
      )}
    >
      <Icon className={cn("h-3 w-3", inProgress && "animate-spin")} aria-hidden />
      {label}
    </span>
  );
}