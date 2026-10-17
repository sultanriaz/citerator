import { useEffect, useState } from "react";
import { Skeleton } from "@/components/shared/SkeletonLoader";
import { cn } from "@/lib/cn";

export const LOADING_STAGES = [
  "Retrieving",
  "Re-ranking",
  "Verifying citations",
  "Writing answer",
] as const;

const STAGE_INTERVAL_MS = 1200;

export function LoadingSteps() {
  const [stage, setStage] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setStage((s) => (s < LOADING_STAGES.length - 1 ? s + 1 : s));
    }, STAGE_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="rounded-lg border border-border bg-surface p-4" role="status" aria-live="polite">
      <ol className="flex flex-wrap items-center gap-2 text-2xs">
        {LOADING_STAGES.map((label, i) => (
          <li
            key={label}
            className={cn(
              "flex items-center gap-1.5 rounded-full border px-2.5 py-1 transition-colors",
              i < stage && "border-border text-muted line-through",
              i === stage && "border-accent bg-accent-soft text-accent",
              i > stage && "border-border text-muted"
            )}
          >
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                i < stage ? "bg-muted" : i === stage ? "bg-accent" : "bg-border-strong"
              )}
              aria-hidden
            />
            <span>{label}</span>
          </li>
        ))}
      </ol>
      <div className="mt-4 space-y-2">
        <Skeleton className="h-3 w-4/5" />
        <Skeleton className="h-3 w-3/5" />
        <Skeleton className="h-3 w-2/5" />
      </div>
    </div>
  );
}