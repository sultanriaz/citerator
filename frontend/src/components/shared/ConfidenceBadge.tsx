import { CheckCircle2, AlertTriangle, HelpCircle } from "lucide-react";
import { cn } from "@/lib/cn";
import type { AnswerState } from "@/api/types";

const CONFIDENCE_TOOLTIP =
  "Confidence is the sigmoid of the top cross-encoder score for this question. " +
  "Above the threshold: confident. Between floor and threshold: low confidence. " +
  "Below the floor: insufficient, and no answer is written.";

export interface ConfidenceBadgeProps {
  state: AnswerState;
  confidence: number;
}

export function ConfidenceBadge({ state, confidence }: ConfidenceBadgeProps) {
  const { Icon, label, cls } =
    state === "confident"
      ? {
          Icon: CheckCircle2,
          label: `High confidence \u00B7 ${(confidence).toFixed(2)}`,
          cls: "text-success border-success/30 bg-success/10",
        }
      : state === "low_confidence"
        ? {
            Icon: AlertTriangle,
            label: `Low confidence \u00B7 ${(confidence).toFixed(2)}`,
            cls: "text-warning border-warning/30 bg-warning/10",
          }
        : {
            Icon: HelpCircle,
            label: `Insufficient \u00B7 ${(confidence).toFixed(2)}`,
            cls: "text-danger border-danger/30 bg-danger/10",
          };

  return (
    <span
      role="status"
      aria-label={`${label}. ${CONFIDENCE_TOOLTIP}`}
      title={CONFIDENCE_TOOLTIP}
      tabIndex={0}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
        cls
      )}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden />
      <span>{label}</span>
    </span>
  );
}