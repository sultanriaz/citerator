import { useEffect, useState } from "react";
import { listDocuments } from "@/api/documents";
import type { DocumentRow } from "@/api/types";

export interface FilterState {
  docId: string | null;
  jurisdiction: string | null;
  showRetrievalDetails: boolean;
}

export interface FilterRowProps {
  value: FilterState;
  onChange: (next: FilterState) => void;
}

export function FilterRow({ value, onChange }: FilterRowProps) {
  const [docs, setDocs] = useState<DocumentRow[]>([]);

  useEffect(() => {
    let active = true;
    listDocuments({ limit: 500 })
      .then((res) => {
        if (active) setDocs(res.documents);
      })
      .catch(() => {
        /* filters are optional; failure to load doesn't block the screen */
      });
    return () => {
      active = false;
    };
  }, []);

  const jurisdictions = Array.from(
    new Set(docs.map((d) => d.jurisdiction).filter((j): j is string => !!j))
  ).sort();

  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="flex items-center gap-1.5 text-2xs text-secondary">
        <span className="sr-only">Filter by document</span>
        <select
          aria-label="Filter by document"
          value={value.docId ?? ""}
          onChange={(e) => onChange({ ...value, docId: e.target.value || null })}
          className="rounded-md border border-border bg-surface px-2 py-1 text-2xs text-primary focus:outline-none focus:border-accent"
        >
          <option value="">All documents</option>
          {docs.map((d) => (
            <option key={d.doc_id} value={d.doc_id}>
              {d.title ?? d.source_file}
            </option>
          ))}
        </select>
      </label>

      <label className="flex items-center gap-1.5 text-2xs text-secondary">
        <span className="sr-only">Filter by jurisdiction</span>
        <select
          aria-label="Filter by jurisdiction"
          value={value.jurisdiction ?? ""}
          onChange={(e) =>
            onChange({ ...value, jurisdiction: e.target.value || null })
          }
          className="rounded-md border border-border bg-surface px-2 py-1 text-2xs text-primary focus:outline-none focus:border-accent"
        >
          <option value="">All jurisdictions</option>
          {jurisdictions.map((j) => (
            <option key={j} value={j}>
              {j}
            </option>
          ))}
        </select>
      </label>

      <label className="ml-auto flex items-center gap-2 text-2xs text-secondary">
        <input
          type="checkbox"
          checked={value.showRetrievalDetails}
          onChange={(e) =>
            onChange({ ...value, showRetrievalDetails: e.target.checked })
          }
          className="h-3 w-3 rounded border-border-strong bg-surface accent-accent"
        />
        Show retrieval details
      </label>
    </div>
  );
}