import { useCallback, useEffect, useState } from "react";
import { FlaskConical, Download, Play } from "lucide-react";
import { TopBar } from "@/components/layout/TopBar";
import { MetricCard } from "@/components/evaluation/MetricCard";
import { MetricsChart } from "@/components/evaluation/MetricsChart";
import { SafetyCard } from "@/components/evaluation/SafetyCard";
import { RunsTable } from "@/components/evaluation/RunsTable";
import { RunDetailDrawer } from "@/components/evaluation/RunDetailDrawer";
import { Toast } from "@/components/shared/Toast";
import { getEvalLatest, listEvalRuns, startEvalRun } from "@/api/eval";
import type { EvalLatest, EvalRun } from "@/api/types";

export function EvaluationPage() {
  const [latest, setLatest] = useState<EvalLatest | null>(null);
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [starting, setStarting] = useState(false);
  const [openRun, setOpenRun] = useState<EvalRun | null>(null);
  const [toast, setToast] = useState<{ tone: "success" | "error"; message: string } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [runsResp, latestResp] = await Promise.all([
        listEvalRuns(50, 0),
        getEvalLatest().catch(() => null),
      ]);
      setRuns(runsResp.runs);
      setLatest(latestResp);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load evaluation data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  function toggleSelect(id: string) {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : prev.length >= 2 ? [prev[1], id] : [...prev, id]
    );
  }

  const hasActiveRun = runs.some((r) => r.status === "running");

  async function onStartRun() {
    if (hasActiveRun || starting) return;
    setStarting(true);
    try {
      const { run_id } = await startEvalRun("New run");
      setToast({ tone: "success", message: `Started run ${run_id.slice(0, 8)}` });
      void refresh();
    } catch (err) {
      setToast({ tone: "error", message: err instanceof Error ? err.message : "Failed to start run" });
    } finally {
      setStarting(false);
      void refresh();
    }
  }

  return (
    <div className="flex h-full flex-col">
      <TopBar
        breadcrumbs={["Workspace", "Evaluation"]}
        rightSlot={
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled
              title="Coming soon"
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted cursor-not-allowed"
            >
              <Download className="h-3.5 w-3.5" aria-hidden />
              Export report
            </button>
            <button
              type="button"
              onClick={onStartRun}
              disabled={starting || hasActiveRun}
              className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-foreground disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <FlaskConical className="h-3.5 w-3.5" aria-hidden />
              Run evaluation
            </button>
          </div>
        }
      />

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <header className="mb-5">
          <h1 className="text-2xl font-semibold tracking-tight text-primary">Evaluation</h1>
          <p className="mt-1 text-xs text-secondary">
            Trust is earned. Here's the evidence behind every answer.
          </p>
        </header>

        {loading && <p className="text-xs text-secondary">Loading...</p>}
        {error && (
          <p className="mb-4 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
            {error}
          </p>
        )}

        {latest && (
          <>
            <div className="mb-4 flex items-center gap-3">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-success/30 bg-success/10 px-2.5 py-1 text-2xs text-success">
                <Play className="h-3 w-3" aria-hidden />
                Latest run {latest.label ?? "completed"}
              </span>
              <span className="font-mono text-2xs text-secondary">
                {latest.run_id.slice(0, 8)} · {new Date(latest.timestamp).toLocaleString("en-GB")}
              </span>
              <span className="ml-auto inline-flex items-center gap-1 text-2xs text-secondary">
                <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
                {latest.question_count} questions evaluated
              </span>
            </div>

            <div className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
              {[
                { key: "faithfulness_mean", label: "Faithfulness", fmt: (v: number) => v.toFixed(2) },
                { key: "answer_relevancy_mean", label: "Answer relevancy", fmt: (v: number) => v.toFixed(2) },
                { key: "context_precision_mean", label: "Context precision", fmt: (v: number) => v.toFixed(2) },
                { key: "context_recall_mean", label: "Context recall", fmt: (v: number) => v.toFixed(2) },
                { key: "latency_p50_ms", label: "Latency p50 / p95", fmt: (v: number, m: any) => `${(v / 1000).toFixed(1)} / ${(((m.latency_p95_ms?.value ?? 0) / 1000)).toFixed(1)}s`, dir: "lower_is_better" as const },
                { key: "cost_per_query_usd_mean", label: "Cost per query", fmt: (v: number) => `$${v.toFixed(4)}`, dir: "lower_is_better" as const },
              ].map((m) => {
                const point = latest.metrics[m.key];
                if (!point) return null;
                return (
                  <MetricCard
                    key={m.key}
                    label={m.label}
                    value={point.value != null ? m.fmt(point.value, latest.metrics) : "\u2014"}
                    delta={point.delta_vs_previous}
                    sparkline={point.sparkline}
                    direction={m.dir ?? "higher_is_better"}
                  />
                );
              })}
            </div>

            <div className="mb-6">
              <SafetyCard refusePct={latest.safety.refuse_pct} escalatePct={latest.safety.escalate_pct} />
            </div>
          </>
        )}

        {runs.length > 0 && (
          <>
            <div className="mb-6">
              <MetricsChart runs={runs} />
            </div>
            <RunsTable
              runs={runs}
              selectedIds={selectedIds}
              onToggleSelect={toggleSelect}
              onOpen={setOpenRun}
              onCompare={() => {
                if (selectedIds.length === 2) {
                  window.open(`/eval/runs/compare?a=${selectedIds[0]}&b=${selectedIds[1]}`, "_blank");
                }
              }}
            />
          </>
        )}

        {!loading && runs.length === 0 && !error && (
          <div className="rounded-lg border border-dashed border-border bg-surface px-6 py-10 text-center">
            <FlaskConical className="mx-auto h-6 w-6 text-muted" aria-hidden />
            <p className="mt-3 text-sm text-primary">No evaluation runs yet.</p>
            <p className="mt-1 text-xs text-secondary">
              Click "Run evaluation" to score the pipeline against your question set.
            </p>
          </div>
        )}
      </div>

      <RunDetailDrawer open={openRun != null} onClose={() => setOpenRun(null)} run={openRun} />

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 w-80">
          <Toast tone={toast.tone} message={toast.message} onDismiss={() => setToast(null)} />
        </div>
      )}
    </div>
  );
}