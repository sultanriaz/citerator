import { ShieldCheck } from "lucide-react";

export interface SafetyCardProps {
  refusePct: number | null;
  escalatePct: number | null;
}

export function SafetyCard({ refusePct, escalatePct }: SafetyCardProps) {
  return (
    <div className="rounded-xl border border-accent/20 bg-accent-soft/40 p-5">
      <div className="flex items-center gap-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-accent/30 bg-accent-soft">
          <ShieldCheck className="h-5 w-5 text-accent" aria-hidden />
        </div>
        <div>
          <h2 className="text-sm font-medium text-primary">
            Knowing when not to answer.
          </h2>
          <p className="mt-0.5 text-2xs text-secondary">
            Safety is a behavior, not a disclaimer.
          </p>
        </div>

        <div className="ml-auto flex items-center gap-8">
          <div className="text-right">
            <div className="text-3xl font-semibold tracking-tight text-accent">
              {refusePct != null ? `${refusePct.toFixed(1)}%` : "\u2014"}
            </div>
            <div className="mt-0.5 text-2xs text-secondary">
              Out-of-corpus correctly refused
            </div>
          </div>
          <div className="text-right">
            <div className="text-3xl font-semibold tracking-tight text-accent">
              {escalatePct != null ? `${escalatePct.toFixed(1)}%` : "\u2014"}
            </div>
            <div className="mt-0.5 text-2xs text-secondary">
              Underspecified correctly escalated
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}