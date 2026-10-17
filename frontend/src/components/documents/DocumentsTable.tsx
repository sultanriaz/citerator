import { FileText, MoreVertical, RefreshCw, Trash2, Lock, Globe } from "lucide-react";
import { useState } from "react";
import type { DocumentRow } from "@/api/types";
import { DocStatusBadge } from "./DocStatusBadge";
import { cn } from "@/lib/cn";

export interface DocumentsTableProps {
  documents: DocumentRow[];
  onDelete: (doc: DocumentRow) => void;
  onReindex: (doc: DocumentRow) => void;
  onViewChunks: (doc: DocumentRow) => void;
}

function chunksLabel(doc: DocumentRow): string {
  const chunks = doc.chunk_count ?? 0;
  if (doc.page_count && doc.page_count > 0) {
    return `${doc.page_count} / ${chunks}`;
  }
  return `${chunks}`;
}

export function DocumentsTable({
  documents,
  onDelete,
  onReindex,
  onViewChunks,
}: DocumentsTableProps) {
  const [menuFor, setMenuFor] = useState<string | null>(null);

  if (documents.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border bg-surface px-6 py-8 text-center text-xs text-secondary">
        No documents indexed yet. Upload one to get started.
      </p>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <table className="w-full table-fixed text-xs">
        <colgroup>
          <col />
          <col className="w-[80px]" />
          <col className="w-[110px]" />
          <col className="w-[100px]" />
          <col className="w-[80px]" />
          <col className="w-[96px]" />
          <col className="w-[44px]" />
        </colgroup>
        <thead className="bg-surface-elevated text-left text-2xs uppercase tracking-wider text-muted">
          <tr>
            <th className="px-4 py-2 font-medium">Document</th>
            <th className="px-3 py-2 font-medium">Type</th>
            <th className="px-3 py-2 font-medium">Jurisdiction</th>
            <th className="px-3 py-2 font-medium">Effective</th>
            <th className="px-3 py-2 font-medium whitespace-nowrap">
              Pg / chunks
            </th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-2 py-2" />
          </tr>
        </thead>
        <tbody>
          {documents.map((doc) => (
            <tr
              key={doc.doc_id}
              className="h-[58px] border-t border-border hover:bg-surface-elevated/50"
            >
              <td className="px-4 py-2 align-middle">
                <div className="flex items-center gap-3 min-w-0">
                  <FileText
                    className="h-4 w-4 shrink-0 text-muted"
                    aria-hidden
                  />
                  <div className="min-w-0">
                    <div
                      className="truncate font-medium text-primary"
                      title={doc.title ?? doc.source_file}
                    >
                      {doc.title ?? doc.source_file}
                    </div>
                    <div className="mt-0.5 flex items-center gap-1.5 flex-wrap">
                      <span
                        className="truncate font-mono text-2xs text-secondary max-w-[140px]"
                        title={doc.source_file}
                      >
                        {doc.source_file}
                      </span>
                      {doc.tenant_id && (
                        <span
                          className={cn(
                            "inline-flex items-center gap-0.5 rounded px-1.5 py-0.2 text-[10px] font-medium border",
                            doc.tenant_id === "global"
                              ? "border-purple-500/30 bg-purple-500/10 text-purple-400"
                              : "border-blue-500/30 bg-blue-500/10 text-blue-400"
                          )}
                          title={`Tenant: ${doc.tenant_id}`}
                        >
                          {doc.tenant_id === "global" ? "Global" : doc.tenant_id}
                        </span>
                      )}
                      {doc.visibility && (
                        <span
                          className={cn(
                            "inline-flex items-center gap-0.5 rounded px-1.5 py-0.2 text-[10px] font-medium border",
                            doc.visibility === "private"
                              ? "border-amber-500/30 bg-amber-500/10 text-amber-400"
                              : doc.visibility === "public"
                              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                              : "border-border bg-surface-elevated text-secondary"
                          )}
                          title={`Visibility: ${doc.visibility}`}
                        >
                          {doc.visibility === "private" && <Lock className="h-2.5 w-2.5" />}
                          {doc.visibility === "public" && <Globe className="h-2.5 w-2.5" />}
                          {doc.visibility}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </td>
              <td className="px-3 py-2 align-middle text-2xs text-secondary whitespace-nowrap">
                {doc.doc_type ?? "\u2014"}
              </td>
              <td
                className="px-3 py-2 align-middle text-2xs text-secondary whitespace-nowrap truncate"
                title={doc.jurisdiction ?? ""}
              >
                {doc.jurisdiction ?? "\u2014"}
              </td>
              <td className="px-3 py-2 align-middle text-2xs text-secondary whitespace-nowrap">
                {doc.effective_date ?? "\u2014"}
              </td>
              <td className="px-3 py-2 align-middle text-2xs text-secondary whitespace-nowrap font-mono">
                {chunksLabel(doc)}
              </td>
              <td className="px-3 py-2 align-middle">
                <DocStatusBadge status={doc.status} />
              </td>
              <td className="px-2 py-2 align-middle text-right">
                <div className="relative inline-block">
                  <button
                    type="button"
                    onClick={() =>
                      setMenuFor(menuFor === doc.doc_id ? null : doc.doc_id)
                    }
                    aria-label={`Actions for ${doc.title ?? doc.source_file}`}
                    aria-haspopup="menu"
                    aria-expanded={menuFor === doc.doc_id}
                    className="rounded p-1 text-secondary hover:bg-surface hover:text-primary"
                  >
                    <MoreVertical className="h-4 w-4" aria-hidden />
                  </button>
                  {menuFor === doc.doc_id && (
                    <div
                      role="menu"
                      className="absolute right-0 top-full z-20 mt-1 w-44 rounded-md border border-border bg-surface-elevated py-1 shadow-lg"
                    >
                      <button
                        role="menuitem"
                        type="button"
                        onClick={() => {
                          setMenuFor(null);
                          onViewChunks(doc);
                        }}
                        className="block w-full px-3 py-1.5 text-left text-xs text-primary hover:bg-surface"
                      >
                        View chunks
                      </button>
                      <button
                        role="menuitem"
                        type="button"
                        onClick={() => {
                          setMenuFor(null);
                          onReindex(doc);
                        }}
                        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-primary hover:bg-surface"
                      >
                        <RefreshCw className="h-3 w-3" aria-hidden />
                        Reindex
                      </button>
                      <button
                        role="menuitem"
                        type="button"
                        onClick={() => {
                          setMenuFor(null);
                          onDelete(doc);
                        }}
                        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-danger hover:bg-surface"
                      >
                        <Trash2 className="h-3 w-3" aria-hidden />
                        Delete
                      </button>
                    </div>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}