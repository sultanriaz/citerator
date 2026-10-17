import { Copy, ExternalLink, FileText } from "lucide-react";
import { cn } from "@/lib/cn";
import type { Citation, RetrievedChunk } from "@/api/types";

export interface SourceCardProps {
  index?: number;
  source: Citation | RetrievedChunk;
  relevance?: number | null;
  highlighted?: boolean;
  onOpen: () => void;
  onCopy: () => void;
}

function excerptOf(source: Citation | RetrievedChunk): string {
  if ("excerpt" in source && typeof source.excerpt === "string") return source.excerpt;
  if ("text" in source && typeof source.text === "string") return source.text.slice(0, 220);
  return "";
}

function pageRange(source: Citation | RetrievedChunk): string | null {
  const start = source.page_start;
  const end = source.page_end;
  if (start == null && end == null) return null;
  if (start != null && end != null && start !== end) return `pp. ${start}-${end}`;
  return `p. ${start ?? end}`;
}

export function SourceCard({
  index,
  source,
  relevance,
  highlighted,
  onOpen,
  onCopy,
}: SourceCardProps) {
  const excerpt = excerptOf(source);
  const pages = pageRange(source);
  const section = source.section_path?.join(" \u203A ");

  return (
    <article
      className={cn(
        "rounded-lg border bg-surface p-3 transition-colors",
        highlighted ? "border-accent" : "border-border"
      )}
    >
      <header className="flex items-start gap-2">
        {index != null && (
          <span className="font-mono text-2xs text-accent">[{index}]</span>
        )}
        <FileText className="h-3.5 w-3.5 shrink-0 text-muted mt-0.5" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-medium text-primary">
            {source.doc_title}
          </div>
          {(section || pages) && (
            <div className="mt-0.5 truncate text-2xs text-secondary">
              {section}
              {section && pages && " \u00B7 "}
              {pages}
            </div>
          )}
        </div>
      </header>

      {excerpt && (
        <p className="mt-2 line-clamp-3 text-2xs leading-relaxed text-secondary">
          &ldquo;{excerpt}&rdquo;
        </p>
      )}

      <footer className="mt-2 flex items-center gap-2">
        <span className="truncate font-mono text-2xs text-muted">
          {source.chunk_id}
        </span>

        {relevance != null && (
          <>
            <span
              className="ml-1 h-1 w-16 overflow-hidden rounded-full bg-border"
              aria-hidden
            >
              <span
                className="block h-full bg-accent"
                style={{ width: `${Math.round(relevance * 100)}%` }}
              />
            </span>
            <span className="text-2xs text-secondary">
              {Math.round(relevance * 100)}% relevance
            </span>
          </>
        )}

        <span className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={onOpen}
            aria-label={`Open ${source.doc_title} in document view`}
            className="rounded p-1 text-secondary hover:bg-surface-elevated hover:text-primary transition-colors"
          >
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          </button>
          <button
            type="button"
            onClick={onCopy}
            aria-label={`Copy citation for ${source.doc_title}`}
            className="rounded p-1 text-secondary hover:bg-surface-elevated hover:text-primary transition-colors"
          >
            <Copy className="h-3.5 w-3.5" aria-hidden />
          </button>
        </span>
      </footer>
    </article>
  );
}