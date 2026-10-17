import { HelpCircle } from "lucide-react";
import { cn } from "@/lib/cn";

export interface MetricCardProps {
  label: string;
  value: string;
  delta: number | null;
  sparkline?: number[];
  direction?: "higher_is_better" | "lower_is_better";
  helpText?: string;
}

export function MetricCard({
  label,
  value,
  delta,
  sparkline,
  direction = "higher_is_better",
  helpText,
}: MetricCardProps) {
  const isGood =
    delta == null
      ? null
      : direction === "higher_is_better"
        ? delta >= 0
        : delta <= 0;

  const max = sparkline && sparkline.length ? Math.max(...sparkline) : 1;
  const min = sparkline && sparkline.length ? Math.min(...sparkline) : 0;
  const range = max - min || 1;

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-center gap-1.5 text-2xs text-secondary">
        <span>{label}</span>
        {helpText && (
          <span title={helpText} className="cursor-help">
            <HelpCircle className="h-3 w-3 text-muted" aria-hidden />
          </span>
        )}
      </div>
      <div className="mt-3 flex items-baseline gap-3">
        <div className="text-3xl font-semibold tracking-tight text-primary">
          {value}
        </div>
        {delta != null && (
          <div
            className={cn(
              "text-xs font-medium",
              isGood ? "text-success" : "text-danger"
            )}
          >
            {delta >= 0 ? "+" : ""}
            {delta.toFixed(direction === "higher_is_better" ? 2 : 3)}
          </div>
        )}
      </div>
      {sparkline && sparkline.length > 0 && (
        <>
          <div className="mt-2 text-2xs text-muted">vs. previous run</div>
          <div className="mt-1 flex h-3 items-end gap-0.5">
            {sparkline.map((v, i) => (
              <div
                key={i}
                className={cn(
                  "flex-1 rounded-sm",
                  i === sparkline.length - 1 ? "bg-accent" : "bg-border-strong"
                )}
                style={{ height: `${20 + ((v - min) / range) * 80}%` }}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}