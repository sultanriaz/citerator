import { useEffect, useState } from "react";
import { Drawer } from "@/components/shared/Drawer";
import { getEvalRun } from "@/api/eval";
import type { EvalQuestionResult, EvalRun } from "@/api/types";
import { CheckCircle2, XCircle } from "lucide-react";
import { cn } from "@/lib/cn";

const CATEGORIES = ["all", "lookup", "multi_document", "out_of_corpus", "underspecified"] as const;

export interface RunDetailDrawerProps {
  open: boolean;
  onClose: () => void;
  run: EvalRun | null;
}

export function RunDetailDrawer({ open, onClose, run }: RunDetailDrawerProps) {
  const [category, setCategory] = useState<string>("all");
  const [results, setResults] = useState<EvalQuestionResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !run) return;
    setLoading(true);
    setError(null);
    getEvalRun(run.run_id, category === "all" ? undefined : category)
      .then((d) => setResults(d.results))
      .catch((err) => setError(err.message ?? "Failed to load run"))
      .finally(() => setLoading(false));
  }, [open, run, category]);

  if (!run) return null;

  return (
    <Drawer open={open} onClose={onClose} title={`Run detail · ${run.label ?? run.run_id.slice(0, 8)}`} width="w-full md:w-[720px]">
      <p className="mb-4 text-xs text-secondary">
        {run.question_count} questions · {run.chunking_strategy} · {run.embedder?.split("/").pop() ?? "\u2014"} · Hybrid + reranker
      </p>

      <div className="mb-4 flex flex-wrap gap-1.5">
        {CATEGORIES.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setCategory(c)}
            className={cn(
              "rounded-full border px-3 py-1 text-2xs",
              category === c
                ? "border-accent bg-accent-soft text-accent"
                : "border-border bg-surface text-secondary hover:text-primary"
            )}
          >
            {c === "all" ? "All questions" : c}
          </button>
        ))}
      </div>

      {loading && <p className="text-xs text-secondary">Loading...</p>}
      {error && <p className="text-xs text-danger">{error}</p>}

      {!loading && !error && (
        <table className="w-full text-2xs">
          <thead className="text-left text-muted">
            <tr>
              <th className="py-1.5">Question</th>
              <th className="py-1.5">Behavior</th>
              <th className="py-1.5">Result</th>
              <th className="py-1.5">Faithfulness</th>
              <th className="py-1.5">Latency / cost</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <tr key={r.id} className="border-t border-border">
                <td className="py-2 pr-3">
                  <div className="text-primary">{r.question}</div>
                  {r.category && (
                    <div className="mt-0.5 text-muted">{r.category}</div>
                  )}
                </td>
                <td className="py-2 pr-3 text-secondary capitalize">
                  {r.expected_behavior ?? "\u2014"}
                </td>
                <td className="py-2 pr-3">
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-2xs",
                      r.passed
                        ? "border-success/30 bg-success/10 text-success"
                        : "border-danger/30 bg-danger/10 text-danger"
                    )}
                  >
                    {r.passed ? (
                      <CheckCircle2 className="h-3 w-3" aria-hidden />
                    ) : (
                      <XCircle className="h-3 w-3" aria-hidden />
                    )}
                    {r.passed ? "Pass" : "Fail"}
                  </span>
                </td>
                <td className="py-2 pr-3 text-secondary">
                  {r.faithfulness != null ? r.faithfulness.toFixed(2) : "\u2014"}
                </td>
                <td className="py-2 text-secondary">
                  {r.latency_ms != null ? `${(r.latency_ms / 1000).toFixed(1)}s` : "\u2014"}
                  {r.cost_usd != null ? ` / $${r.cost_usd.toFixed(4)}` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Drawer>
  );
}