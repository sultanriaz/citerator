import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Download,
  Flag,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { ConfidenceBadge } from "@/components/shared/ConfidenceBadge";
import { CitationChip } from "@/components/shared/CitationChip";
import { SourceCard } from "@/components/shared/SourceCard";
import { Toast } from "@/components/shared/Toast";
import { postFeedback } from "@/api/feedback";
import type { QueryResponse, RetrievedChunk } from "@/api/types";

export interface AnswerCardProps {
  question: string;
  response: QueryResponse;
  traceId: string | null;
  onOpenEvidence: (chunk: RetrievedChunk | null) => void;
  onOpenRetrieval: () => void;
  onEscalate: () => void;
  onFlag: () => void;
}

function buildCitationText(question: string, response: QueryResponse): string {
  const lines = [question, "", response.answer ?? ""];
  response.citations.forEach((c, i) => {
    lines.push(
      `[${i + 1}] ${c.doc_title} \u2014 ${c.section_path.join(" \u203A ")}`
    );
  });
  return lines.join("\n");
}

export function AnswerCard({
  question,
  response,
  traceId,
  onOpenEvidence,
  onOpenRetrieval,
  onEscalate,
  onFlag,
}: AnswerCardProps) {
  const [feedback, setFeedback] = useState<"up" | "down" | null>(null);
  const [highlighted, setHighlighted] = useState<number | null>(null);
  const [toast, setToast] = useState<{ tone: "success" | "error"; message: string } | null>(null);

  const isLow = response.state === "low_confidence";
  const isInsufficient = response.state === "insufficient";

  const sources: RetrievedChunk[] = useMemo(() => {
    const byId = new Map<string, RetrievedChunk>();
    response.related_passages.forEach((p) => byId.set(p.chunk_id, p));
    return Array.from(byId.values());
  }, [response]);

  function handleCitation(index: number) {
    setHighlighted(index);
    const chunkId = response.citations[index - 1]?.chunk_id;
    const chunk = sources.find((s) => s.chunk_id === chunkId) ?? null;
    onOpenEvidence(chunk);
  }

  async function copy(text: string, label: string) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setToast({ tone: "success", message: `${label} copied` });
    } catch (err) {
      setToast({
        tone: "error",
        message: `Copy failed: ${(err as Error).message ?? "unknown error"}`,
      });
    }
  }

  async function rate(rating: "up" | "down") {
    if (!traceId) {
      setToast({
        tone: "error",
        message:
          "No trace ID on this response. The X-Trace-Id header is not being exposed across origins.",
      });
      return;
    }
    setFeedback(rating);
    try {
      await postFeedback({ trace_id: traceId, rating });
      setToast({
        tone: "success",
        message: rating === "up" ? "Thanks \u2014 marked helpful" : "Thanks \u2014 noted",
      });
    } catch (err) {
      setFeedback(null);
      setToast({
        tone: "error",
        message: `Feedback failed: ${(err as Error).message ?? "unknown error"}`,
      });
    }
  }

  const answerWithChips =
    response.answer?.split(/(\[\d+\])/g).map((part, i) => {
      const m = /^\[(\d+)\]$/.exec(part);
      if (m) {
        const idx = Number(m[1]);
        return (
          <CitationChip
            key={i}
            index={idx}
            active={highlighted === idx}
            onClick={() => handleCitation(idx)}
          />
        );
      }
      return <span key={i}>{part}</span>;
    }) ?? null;

  return (
    <article className="rounded-xl border border-border bg-surface p-5">
      <header className="flex items-center gap-3">
        <span
          aria-hidden
          className="flex h-7 w-7 items-center justify-center rounded-full bg-accent-soft font-mono text-2xs text-accent"
        >
          [ ]
        </span>
        <span className="text-2xs font-medium uppercase tracking-wider text-muted">
          Citerator
        </span>
        <span className="text-2xs text-secondary">Evidence-based answer</span>
        <span className="ml-auto">
          <ConfidenceBadge state={response.state} confidence={response.confidence} />
        </span>
      </header>

      {isLow && (
        <div className="mt-4 flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" aria-hidden />
          <span>Limited evidence found. Verify before relying on this.</span>
        </div>
      )}

      {isInsufficient ? (
        <div className="mt-5">
          <h3 className="text-sm font-medium text-primary">
            Citerator couldn&rsquo;t find enough evidence in the indexed documents to
            answer this.
          </h3>
          <p className="mt-1.5 text-xs text-secondary">
            Below are the closest passages. They are not an answer.
          </p>

          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
            {response.related_passages.slice(0, 4).map((p) => (
              <SourceCard
                key={p.chunk_id}
                source={p}
                onOpen={() => onOpenEvidence(p)}
                onCopy={() =>
                  copy(
                    `${p.doc_title} \u00B7 ${p.section_path.join(" \u203A ")}`,
                    "Citation"
                  )
                }
              />
            ))}
          </div>

          <button
            type="button"
            onClick={onEscalate}
            className="mt-4 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-foreground"
          >
            Escalate to a human
          </button>
        </div>
      ) : (
        <>
          <div className="mt-4 text-sm leading-relaxed text-primary">
            {answerWithChips}
          </div>

          {response.citations.length > 0 && (
            <section className="mt-5">
              <header className="flex items-center gap-2 text-2xs uppercase tracking-wider text-muted">
                <span className="font-mono text-accent">[ ]</span>
                <span>Sources</span>
                <span className="ml-1 text-secondary">
                  {response.citations.length}
                </span>
                <span className="ml-auto">Verifiable by design</span>
              </header>
              <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-2">
                {response.citations.map((c, i) => {
                  const chunk =
                    sources.find((s) => s.chunk_id === c.chunk_id) ?? null;
                  const relevance =
                    (chunk?.rerank_score != null
                      ? 1 / (1 + Math.exp(-chunk.rerank_score))
                      : null) ?? null;
                  return (
                    <SourceCard
                      key={c.chunk_id}
                      index={i + 1}
                      source={chunk ?? c}
                      relevance={relevance}
                      highlighted={highlighted === i + 1}
                      onOpen={() => onOpenEvidence(chunk)}
                      onCopy={() =>
                        copy(
                          `[${i + 1}] ${c.doc_title} \u2014 ${c.section_path.join(" \u203A ")} (${c.source_file})`,
                          "Citation"
                        )
                      }
                    />
                  );
                })}
              </div>
            </section>
          )}
        </>
      )}

      {!isInsufficient && (
        <footer className="mt-4 flex flex-wrap items-center gap-3 border-t border-border pt-3 text-2xs text-secondary">
          {response.latency_ms.total != null && (
            <span>{(response.latency_ms.total / 1000).toFixed(1)}s</span>
          )}
          {response.tokens && (
            <span>
              {response.tokens.input ?? 0} in / {response.tokens.output ?? 0} out tokens
            </span>
          )}
          <span className="inline-flex items-center gap-1 text-success">
            <CheckCircle2 className="h-3 w-3" aria-hidden /> Citations verified
          </span>

          <span className="ml-auto flex items-center gap-1">
            <button
              type="button"
              onClick={() => rate("up")}
              aria-label="Helpful"
              aria-pressed={feedback === "up"}
              className={
                "rounded p-1 hover:bg-surface-elevated " +
                (feedback === "up" ? "text-success" : "text-secondary")
              }
            >
              <ThumbsUp className="h-3.5 w-3.5" aria-hidden />
            </button>
            <button
              type="button"
              onClick={() => rate("down")}
              aria-label="Not helpful"
              aria-pressed={feedback === "down"}
              className={
                "rounded p-1 hover:bg-surface-elevated " +
                (feedback === "down" ? "text-danger" : "text-secondary")
              }
            >
              <ThumbsDown className="h-3.5 w-3.5" aria-hidden />
            </button>
            <button
              type="button"
              onClick={() =>
                copy(buildCitationText(question, response), "Answer with citations")
              }
              aria-label="Copy answer with citations"
              className="rounded p-1 text-secondary hover:bg-surface-elevated hover:text-primary"
            >
              <Copy className="h-3.5 w-3.5" aria-hidden />
            </button>
            <button
              type="button"
              disabled
              title="Coming soon"
              aria-label="Export as PDF (coming soon)"
              className="rounded p-1 text-muted cursor-not-allowed"
            >
              <Download className="h-3.5 w-3.5" aria-hidden />
            </button>
            <button
              type="button"
              onClick={onFlag}
              className="ml-1 rounded border border-border px-2 py-1 text-2xs text-secondary hover:bg-surface-elevated hover:text-primary"
            >
              <Flag className="mr-1 inline h-3 w-3" aria-hidden />
              Flag for review
            </button>
          </span>
        </footer>
      )}

      {isLow && (
        <button
          type="button"
          onClick={onEscalate}
          className="mt-3 w-full rounded-md bg-accent px-3 py-2 text-xs font-medium text-accent-foreground"
        >
          Escalate to compliance team
        </button>
      )}

      {response.retrieval_details && response.retrieval_details.length > 0 && (
        <button
          type="button"
          onClick={onOpenRetrieval}
          className="mt-3 text-2xs text-accent hover:underline"
        >
          View retrieval details ({response.retrieval_details.length} chunks)
        </button>
      )}

      {toast && (
        <div className="mt-3">
          <Toast
            tone={toast.tone}
            message={toast.message}
            onDismiss={() => setToast(null)}
          />
        </div>
      )}
    </article>
  );
}