import { ArrowRight, CheckCircle2, Loader2, XCircle } from "lucide-react";
import { cn } from "@/lib/cn";
import type { EvalRun } from "@/api/types";

export interface RunsTableProps {
  runs: EvalRun[];
  selectedIds: string[];
  onToggleSelect: (id: string) => void;
  onOpen: (run: EvalRun) => void;
  onCompare: () => void;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return (
    d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) +
    " \u00B7 " +
    d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
  );
}

function statusMeta(status: string) {
  if (status === "completed") {
    return {
      Icon: CheckCircle2,
      label: "Completed",
      cls: "border-success/30 bg-success/10 text-success",
    };
  }
  if (status === "failed") {
    return {
      Icon: XCircle,
      label: "Failed",
      cls: "border-danger/30 bg-danger/10 text-danger",
    };
  }
  return {
    Icon: Loader2,
    label: status,
    cls: "border-border bg-surface-elevated text-secondary",
  };
}

export function RunsTable({
  runs,
  selectedIds,
  onToggleSelect,
  onOpen,
  onCompare,
}: RunsTableProps) {
  return (
    <div>
      <header className="mb-3 flex items-center">
        <h2 className="text-sm font-medium text-primary">
          Evaluation runs
          <span className="ml-2 rounded border border-border px-1.5 py-0.5 text-2xs text-secondary">
            {runs.length}
          </span>
        </h2>
        <button
          type="button"
          onClick={onCompare}
          disabled={selectedIds.length !== 2}
          className="ml-auto rounded-md border border-border px-3 py-1.5 text-2xs text-secondary hover:bg-surface-elevated hover:text-primary disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Compare runs
        </button>
      </header>

      <div className="overflow-hidden rounded-lg border border-border bg-surface">
        <table className="w-full table-fixed text-xs">
          <colgroup>
            <col className="w-[36px]" />
            <col className="w-[170px]" />
            <col />
            <col className="w-[76px]" />
            <col className="w-[110px]" />
            <col className="w-[80px]" />
            <col className="w-[110px]" />
            <col className="w-[40px]" />
          </colgroup>
          <thead className="bg-surface-elevated text-left text-2xs uppercase tracking-wider text-muted">
            <tr>
              <th className="px-3 py-2" />
              <th className="px-3 py-2 font-medium">Run / timestamp</th>
              <th className="px-3 py-2 font-medium">Pipeline configuration</th>
              <th className="px-3 py-2 font-medium text-right">Questions</th>
              <th className="px-3 py-2 font-medium">Faithfulness</th>
              <th className="px-3 py-2 font-medium text-right">Relevancy</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => {
              const { Icon, label, cls } = statusMeta(r.status);
              const spinning = r.status === "running";
              const faithfulness = r.faithfulness_mean;
              const relevance = r.answer_relevancy_mean;

              return (
                <tr
                  key={r.run_id}
                  className="border-t border-border hover:bg-surface-elevated/50"
                >
                  <td className="px-3 py-2.5 align-middle">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(r.run_id)}
                      onChange={() => onToggleSelect(r.run_id)}
                      aria-label={`Select ${r.label ?? r.run_id}`}
                      className="h-3.5 w-3.5 rounded border-border-strong bg-surface accent-accent"
                    />
                  </td>

                  <td className="px-3 py-2.5 align-middle">
                    <div className="flex items-center gap-2 min-w-0">
                      <span
                        className="truncate font-mono text-2xs font-medium text-primary"
                        title={r.run_id}
                      >
                        {r.label ?? r.run_id.slice(0, 8)}
                      </span>
                      {r.label === "Latest" && (
                        <span className="shrink-0 rounded border border-accent/40 bg-accent-soft px-1.5 py-0.5 text-2xs text-accent">
                          LATEST
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 truncate text-2xs text-muted">
                      {fmtDate(r.created_at)}
                    </div>
                  </td>

                  <td className="px-3 py-2.5 align-middle">
                    <div className="flex flex-wrap items-center gap-1">
                      {r.chunking_strategy && (
                        <span className="rounded border border-border px-1.5 py-0.5 text-2xs text-secondary whitespace-nowrap">
                          {r.chunking_strategy}
                        </span>
                      )}
                      {r.embedder && (
                        <span
                          className="rounded border border-border px-1.5 py-0.5 text-2xs text-secondary whitespace-nowrap truncate max-w-[120px]"
                          title={r.embedder}
                        >
                          {r.embedder.split("/").pop()}
                        </span>
                      )}
                    </div>
                    <div className="mt-1 truncate text-2xs text-muted">
                      Hybrid search \u00B7 cross-encoder reranker
                    </div>
                  </td>

                  <td className="px-3 py-2.5 align-middle text-right text-2xs font-mono text-primary">
                    {r.question_count}
                  </td>

                  <td className="px-3 py-2.5 align-middle">
                    {faithfulness != null ? (
                      <div className="flex items-center gap-2">
                        <span className="w-7 shrink-0 text-2xs font-mono text-primary">
                          {faithfulness.toFixed(2)}
                        </span>
                        <span className="h-1 flex-1 min-w-[24px] overflow-hidden rounded-full bg-border">
                          <span
                            className="block h-full bg-accent"
                            style={{ width: `${Math.min(100, faithfulness * 100)}%` }}
                          />
                        </span>
                      </div>
                    ) : (
                      <span className="text-2xs text-muted">\u2014</span>
                    )}
                  </td>

                  <td className="px-3 py-2.5 align-middle text-right text-2xs font-mono text-primary">
                    {relevance != null ? relevance.toFixed(2) : <span className="text-muted">\u2014</span>}
                  </td>

                  <td className="px-3 py-2.5 align-middle">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-2xs whitespace-nowrap",
                        cls
                      )}
                    >
                      <Icon
                        className={cn("h-3 w-3", spinning && "animate-spin")}
                        aria-hidden
                      />
                      <span className="truncate">{label}</span>
                    </span>
                  </td>

                  <td className="px-2 py-2.5 align-middle text-right">
                    <button
                      type="button"
                      onClick={() => onOpen(r)}
                      aria-label={`Open ${r.label ?? r.run_id}`}
                      className="rounded p-1 text-secondary hover:bg-surface hover:text-primary"
                    >
                      <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}