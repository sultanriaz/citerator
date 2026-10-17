import { RotateCcw } from "lucide-react";
import type { JobRow } from "@/api/types";
import { DocStatusBadge } from "./DocStatusBadge";

export interface JobsTableProps {
  jobs: JobRow[];
  onRetry: (jobId: string) => void;
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}

export function JobsTable({ jobs, onRetry }: JobsTableProps) {
  if (jobs.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border bg-surface px-6 py-8 text-center text-xs text-secondary">
        No ingestion jobs yet. Upload a document to get started.
      </p>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <table className="w-full text-xs">
        <thead className="bg-surface-elevated text-left text-2xs uppercase tracking-wider text-muted">
          <tr>
            <th className="px-4 py-2 font-medium">File</th>
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-4 py-2 font-medium">Started</th>
            <th className="px-4 py-2 font-medium">Doc</th>
            <th className="px-4 py-2 font-medium">Error</th>
            <th className="px-4 py-2" />
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.job_id} className="border-t border-border">
              <td className="px-4 py-2.5 font-mono text-2xs text-primary">
                {j.file_name}
              </td>
              <td className="px-4 py-2.5">
                <DocStatusBadge status={j.status} />
              </td>
              <td className="px-4 py-2.5 text-2xs text-secondary">
                {timeAgo(j.created_at)}
              </td>
              <td className="px-4 py-2.5 font-mono text-2xs text-secondary">
                {j.doc_id ? j.doc_id.slice(0, 8) : "\u2014"}
              </td>
              <td className="px-4 py-2.5 text-2xs text-danger max-w-xs truncate" title={j.error ?? ""}>
                {j.error ?? ""}
              </td>
              <td className="px-4 py-2.5 text-right">
                {j.status === "failed" && (
                  <button
                    type="button"
                    onClick={() => onRetry(j.job_id)}
                    aria-label={`Retry ${j.file_name}`}
                    className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-2xs text-secondary hover:bg-surface-elevated hover:text-primary"
                  >
                    <RotateCcw className="h-3 w-3" aria-hidden />
                    Retry
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}