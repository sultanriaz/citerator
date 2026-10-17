import { useEffect, useState } from "react";
import { Drawer } from "@/components/shared/Drawer";
import { getDocumentChunks } from "@/api/documents";
import type { DocumentRow, ChunkRow } from "@/api/types";

export interface ChunkPreviewDrawerProps {
  open: boolean;
  onClose: () => void;
  doc: DocumentRow | null;
}

export function ChunkPreviewDrawer({ open, onClose, doc }: ChunkPreviewDrawerProps) {
  const [chunks, setChunks] = useState<ChunkRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !doc) return;
    setLoading(true);
    setError(null);
    getDocumentChunks(doc.doc_id)
      .then((res) => setChunks(res.chunks))
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Could not load chunks.")
      )
      .finally(() => setLoading(false));
  }, [open, doc]);

  if (!doc) return null;

  return (
    <Drawer open={open} onClose={onClose} title={doc.title ?? doc.source_file}>
      <div className="mb-4 text-2xs text-secondary">
        <div><span className="text-muted">Type:</span> {doc.doc_type ?? "\u2014"}</div>
        <div><span className="text-muted">Jurisdiction:</span> {doc.jurisdiction ?? "\u2014"}</div>
        <div><span className="text-muted">Effective:</span> {doc.effective_date ?? "\u2014"}</div>
        <div><span className="text-muted">Chunks:</span> {doc.chunk_count ?? 0}</div>
      </div>

      {loading && <p className="text-2xs text-secondary">Loading chunks...</p>}
      {error && <p className="text-2xs text-danger">{error}</p>}

      {chunks && (
        <ul className="space-y-3">
          {chunks.map((c) => (
            <li
              key={c.chunk_id ?? String(c.chunk_index)}
              className="rounded-md border border-border bg-surface p-3 text-2xs"
            >
              <div className="mb-1 flex items-center gap-2 text-muted">
                <span className="font-mono">#{c.chunk_index}</span>
                <span className="truncate">{c.section_path.join(" \u203A ") || "Section"}</span>
                {c.page_start != null && (
                  <span className="ml-auto font-mono">
                    p. {c.page_start}{c.page_end && c.page_end !== c.page_start ? `-${c.page_end}` : ""}
                  </span>
                )}
              </div>
              <p className="whitespace-pre-wrap leading-relaxed text-primary">
                {c.text}
              </p>
              <div className="mt-1 text-2xs text-muted">{c.token_count ?? 0} tokens</div>
            </li>
          ))}
        </ul>
      )}
    </Drawer>
  );
}