import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EvalRun } from "@/api/types";

export interface MetricsChartProps {
  runs: EvalRun[];
}

const SERIES = [
  { key: "faithfulness_mean", label: "Faithfulness", color: "#6ee7b7" },
  { key: "answer_relevancy_mean", label: "Answer relevancy", color: "#a78bfa" },
  { key: "context_precision_mean", label: "Context precision", color: "#60a5fa" },
  { key: "context_recall_mean", label: "Context recall", color: "#fbbf24" },
] as const;

function hasAnyMetric(run: EvalRun): boolean {
  return SERIES.some((s) => {
    const v = run[s.key as keyof EvalRun];
    return typeof v === "number";
  });
}

export function MetricsChart({ runs }: MetricsChartProps) {
  // Only plot runs that actually produced metrics. Running/failed runs with
  // null values would otherwise stretch the x-axis and prevent line drawing.
  const plottable = runs
    .filter((r) => r.status === "completed" && hasAnyMetric(r))
    .reverse();

  const data = plottable.map((r, i) => ({
    index: i,
    name: r.label ?? r.run_id.slice(0, 8),
    ...Object.fromEntries(
      SERIES.map((s) => [s.key, r[s.key as keyof EvalRun] as number | null])
    ),
  }));

  const enoughToDraw = plottable.length >= 2;

  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <header className="flex items-center">
        <div>
          <h2 className="text-sm font-medium text-primary">
            Better with every iteration
          </h2>
          <p className="mt-0.5 text-2xs text-secondary">
            {enoughToDraw
              ? "Quality metrics across your evaluation runs"
              : "One run so far. Run the evaluation again to see trends."}
          </p>
        </div>
        <span className="ml-auto rounded-md border border-border px-2.5 py-1 text-2xs text-secondary">
          Last 30 days
        </span>
      </header>

      {!enoughToDraw ? (
        <div className="mt-6 flex h-48 items-center justify-center rounded-md border border-dashed border-border bg-bg text-center">
          <div>
            <p className="text-xs text-secondary">
              Not enough completed runs to plot a trend.
            </p>
            <p className="mt-1 text-2xs text-muted">
              Complete at least 2 evaluation runs.
            </p>
          </div>
        </div>
      ) : (
        <div className="mt-4 h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={data}
              margin={{ top: 10, right: 20, bottom: 0, left: -10 }}
            >
              <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
              <XAxis
                dataKey="name"
                tick={{ fontSize: 10, fill: "#93a39b" }}
                axisLine={false}
                tickLine={false}
                interval="preserveStartEnd"
              />
              <YAxis
                domain={[0.5, 1]}
                tick={{ fontSize: 10, fill: "#93a39b" }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v) => `${Math.round(v * 100)}%`}
              />
              <Tooltip
                contentStyle={{
                  background: "#121614",
                  border: "1px solid #1f2724",
                  fontSize: 12,
                  borderRadius: 8,
                }}
                labelStyle={{ color: "#e7eeea" }}
                formatter={(value) =>
                  typeof value === "number" ? value.toFixed(2) : String(value)
                }
              />
              <Legend
                wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                iconType="circle"
              />
              {SERIES.map((s, i) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  name={s.label}
                  stroke={s.color}
                  strokeWidth={2}
                  dot={{ r: 3, fill: s.color }}
                  connectNulls
                  animationDuration={900}
                  animationBegin={i * 120}
                  animationEasing="ease-out"
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}