import { useEffect, useRef } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { AnswerCard } from "./AnswerCard";
import { LoadingSteps } from "./LoadingSteps";
import type { QueryTurn } from "@/hooks/useQuery";
import type { RetrievedChunk } from "@/api/types";

export interface AnswerThreadProps {
  turns: QueryTurn[];
  onRetry: (turnId: string) => void;
  onOpenEvidence: (chunk: RetrievedChunk | null) => void;
  onOpenRetrieval: (turn: QueryTurn) => void;
  onEscalate: (turn: QueryTurn) => void;
  onFlag: (turn: QueryTurn) => void;
}

export function AnswerThread({
  turns,
  onRetry,
  onOpenEvidence,
  onOpenRetrieval,
  onEscalate,
  onFlag,
}: AnswerThreadProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length]);

  return (
    <div className="space-y-5">
      {turns.map((turn) => (
        <div key={turn.id} className="space-y-3">
          <div className="flex items-start gap-3">
            <span
              aria-hidden
              className="flex h-7 w-7 items-center justify-center rounded-full border border-border-strong text-2xs font-medium text-primary"
            >
              JL
            </span>
            <div>
              <p className="text-sm font-medium text-primary">{turn.question}</p>
              <p className="text-2xs text-secondary">
                {turn.status === "pending" ? "Thinking..." : "Just now"}
              </p>
            </div>
          </div>

          {turn.status === "pending" && <LoadingSteps />}

          {turn.status === "error" && (
            <div className="rounded-lg border border-danger/30 bg-danger/5 p-4">
              <div className="flex items-start gap-2 text-xs text-danger">
                <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" aria-hidden />
                <div>
                  <p className="font-medium text-primary">
                    Couldn&rsquo;t reach the pipeline.
                  </p>
                  <p className="mt-1 text-secondary">{turn.error}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => onRetry(turn.id)}
                className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-2xs text-secondary hover:bg-surface-elevated hover:text-primary"
              >
                <RotateCcw className="h-3 w-3" aria-hidden />
                Retry
              </button>
            </div>
          )}

          {turn.status === "success" && turn.response && (
            <AnswerCard
              question={turn.question}
              response={turn.response}
              traceId={turn.traceId ?? null}
              onOpenEvidence={onOpenEvidence}
              onOpenRetrieval={() => onOpenRetrieval(turn)}
              onEscalate={() => onEscalate(turn)}
              onFlag={() => onFlag(turn)}
            />
          )}
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}