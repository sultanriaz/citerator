import { Drawer } from "@/components/shared/Drawer";
import type { RetrievalDetail } from "@/api/types";

export interface RetrievalDetailsDrawerProps {
  open: boolean;
  onClose: () => void;
  details: RetrievalDetail[] | null;
}

export function RetrievalDetailsDrawer({
  open,
  onClose,
  details,
}: RetrievalDetailsDrawerProps) {
  return (
    <Drawer open={open} onClose={onClose} title="Retrieval details">
      {!details || details.length === 0 ? (
        <p className="text-xs text-secondary">
          No retrieval details were captured for this query. Enable
          &ldquo;Show retrieval details&rdquo; before asking to record them.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-2xs">
            <thead className="text-left text-muted">
              <tr>
                <th className="py-1.5 pr-2">Chunk</th>
                <th className="py-1.5 pr-2">Dense</th>
                <th className="py-1.5 pr-2">Sparse</th>
                <th className="py-1.5 pr-2">Fused</th>
                <th className="py-1.5 pr-2">Rerank</th>
                <th className="py-1.5">Used</th>
              </tr>
            </thead>
            <tbody>
              {details.map((d) => (
                <tr key={d.chunk_id} className="border-t border-border">
                  <td className="py-1.5 pr-2 font-mono text-primary truncate max-w-[12rem]">
                    {d.chunk_id}
                  </td>
                  <td className="py-1.5 pr-2 text-secondary">
                    {d.dense_score?.toFixed(3) ?? "—"}
                  </td>
                  <td className="py-1.5 pr-2 text-secondary">
                    {d.sparse_score?.toFixed(3) ?? "—"}
                  </td>
                  <td className="py-1.5 pr-2 text-secondary">
                    {d.fused_score?.toFixed(3) ?? "—"}
                  </td>
                  <td className="py-1.5 pr-2 text-secondary">
                    {d.rerank_score?.toFixed(3) ?? "—"}
                  </td>
                  <td className="py-1.5 text-secondary">
                    {d.used_in_answer ? "yes" : "no"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Drawer>
  );
}