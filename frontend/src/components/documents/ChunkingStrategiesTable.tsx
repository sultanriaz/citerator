import type { ChunkingStrategyRow } from "@/api/types";
import { CheckCircle2 } from "lucide-react";

export interface ChunkingStrategiesTableProps {
  strategies: ChunkingStrategyRow[];
  activeStrategy: string;
}

export function ChunkingStrategiesTable({
  strategies,
  activeStrategy,
}: ChunkingStrategiesTableProps) {
  if (strategies.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border bg-surface px-6 py-8 text-center text-xs text-secondary">
        No strategies indexed yet.
      </p>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <table className="w-full text-xs">
        <thead className="bg-surface-elevated text-left text-2xs uppercase tracking-wider text-muted">
          <tr>
            <th className="px-4 py-2 font-medium">Strategy</th>
            <th className="px-4 py-2 font-medium">Documents</th>
            <th className="px-4 py-2 font-medium">Total chunks</th>
            <th className="px-4 py-2 font-medium">Avg</th>
            <th className="px-4 py-2 font-medium">Median</th>
            <th className="px-4 py-2 font-medium">Active</th>
          </tr>
        </thead>
        <tbody>
          {strategies.map((s) => (
            <tr key={s.chunker} className="border-t border-border">
              <td className="px-4 py-2.5 font-mono text-2xs text-primary">{s.chunker}</td>
              <td className="px-4 py-2.5 text-2xs text-secondary">{s.document_count}</td>
              <td className="px-4 py-2.5 text-2xs text-secondary">{s.total_chunk_count}</td>
              <td className="px-4 py-2.5 text-2xs text-secondary">{s.avg_chunk_count}</td>
              <td className="px-4 py-2.5 text-2xs text-secondary">{s.median_chunk_count}</td>
              <td className="px-4 py-2.5">
                {s.chunker === activeStrategy ? (
                  <span className="inline-flex items-center gap-1 text-2xs text-success">
                    <CheckCircle2 className="h-3 w-3" aria-hidden />
                    Active
                  </span>
                ) : (
                  <span className="text-2xs text-muted">\u2014</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="border-t border-border bg-surface-elevated px-4 py-2 text-2xs text-muted">
        Corpus-shape statistics only. Retrieval-quality metrics (hit@5, MRR) require
        labelled questions and belong to Phase 5&rsquo;s evaluation harness.
      </div>
    </div>
  );
}