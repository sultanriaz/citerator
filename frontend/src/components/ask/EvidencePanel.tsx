import { useEffect, useState } from "react";
import { Drawer } from "@/components/shared/Drawer";
import { getDocumentChunks } from "@/api/documents";
import type { ChunkRow, RetrievedChunk } from "@/api/types";

export interface EvidencePanelProps {
  open: boolean;
  onClose: () => void;
  chunk: RetrievedChunk | null;
}

export function EvidencePanel({ open, onClose, chunk }: EvidencePanelProps) {
  const [siblings, setSiblings] = useState<ChunkRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !chunk) return;
    setLoading(true);
    setError(null);
    getDocumentChunks(chunk.doc_id)
      .then((res) => setSiblings(res.chunks))
      .catch((err) => setError(err.message ?? "Could not load surrounding context."))
      .finally(() => setLoading(false));
  }, [open, chunk]);

  if (!chunk) return null;

  const targetIndex = chunk.chunk_index;
  const window = siblings
    ? siblings.filter(
        (c) =>
          c.chunk_index != null &&
          c.chunk_index >= targetIndex - 1 &&
          c.chunk_index <= targetIndex + 1
      )
    : [];

  return (
    <Drawer open={open} onClose={onClose} title={chunk.doc_title}>
      <dl className="mb-4 grid grid-cols-2 gap-3 text-2xs">
        <div>
          <dt className="text-muted">Type</dt>
          <dd className="text-primary">{chunk.doc_type}</dd>
        </div>
        <div>
          <dt className="text-muted">Jurisdiction</dt>
          <dd className="text-primary">{chunk.jurisdiction ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted">Effective date</dt>
          <dd className="text-primary">{chunk.effective_date ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted">Section</dt>
          <dd className="text-primary">{chunk.section_path.join(" \u203A ") || "—"}</dd>
        </div>
        <div className="col-span-2">
          <dt className="text-muted">Chunk ID</dt>
          <dd className="truncate font-mono text-primary">{chunk.chunk_id}</dd>
        </div>
      </dl>

      {loading && <p className="text-2xs text-secondary">Loading surrounding context...</p>}
      {error && <p className="text-2xs text-danger">{error}</p>}

      {window.length > 0 && (
        <div className="space-y-3">
          {window.map((c) => {
            const isTarget = c.chunk_index === targetIndex;
            return (
              <div
                key={c.chunk_id ?? String(c.chunk_index)}
                className={
                  "rounded-md border p-3 text-2xs leading-relaxed " +
                  (isTarget
                    ? "border-accent bg-accent-soft text-primary"
                    : "border-border bg-surface text-secondary")
                }
              >
                <div className="mb-1 text-2xs uppercase tracking-wider text-muted">
                  {c.section_path.join(" \u203A ") || "Section"}
                  {isTarget && " \u00B7 matched chunk"}
                </div>
                <p className="whitespace-pre-wrap">{c.text}</p>
              </div>
            );
          })}
        </div>
      )}
    </Drawer>
  );
}