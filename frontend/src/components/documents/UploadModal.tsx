import { useCallback, useRef, useState } from "react";
import { FileText, Upload, X } from "lucide-react";
import { uploadDocuments } from "@/api/documents";
import type { UploadMeta, UploadResponse } from "@/api/types";
import { cn } from "@/lib/cn";

export interface UploadModalProps {
  open: boolean;
  onClose: () => void;
  onAccepted: (response: UploadResponse) => void;
}

const ACCEPTED = ".pdf,.md,.markdown,.html,.htm";

export function UploadModal({ open, onClose, onAccepted }: UploadModalProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [meta, setMeta] = useState<UploadMeta>({});
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const reset = useCallback(() => {
    setFiles([]);
    setMeta({});
    setDragging(false);
    setSubmitting(false);
    setError(null);
  }, []);

  function handleClose() {
    if (submitting) return;
    reset();
    onClose();
  }

  function addFiles(list: FileList | File[]) {
    const arr = Array.from(list);
    const accepted = arr.filter((f) => {
      const ext = "." + (f.name.split(".").pop() ?? "").toLowerCase();
      return ACCEPTED.split(",").includes(ext);
    });
    setFiles((prev) => [...prev, ...accepted]);
  }

  async function submit() {
    if (files.length === 0) return;
    setSubmitting(true);
    setError(null);
    try {
      const response = await uploadDocuments(files, meta);
      onAccepted(response);
      reset();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={handleClose} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Upload documents"
        className="relative w-full max-w-2xl rounded-lg border border-border bg-surface p-5 shadow-xl"
      >
        <header className="flex items-start">
          <div>
            <h2 className="text-sm font-medium text-primary">Upload documents</h2>
            <p className="mt-1 text-xs text-secondary">
              PDF, Markdown, or HTML. Each file becomes a background ingestion job.
            </p>
          </div>
          <button
            type="button"
            onClick={handleClose}
            aria-label="Close"
            className="ml-auto rounded p-1 text-secondary hover:bg-surface-elevated hover:text-primary"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </header>

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            if (e.dataTransfer?.files) addFiles(e.dataTransfer.files);
          }}
          className={cn(
            "mt-4 flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-8 text-center transition-colors",
            dragging ? "border-accent bg-accent-soft" : "border-border bg-surface-elevated"
          )}
        >
          <Upload className="h-6 w-6 text-muted" aria-hidden />
          <p className="mt-2 text-xs text-primary">
            Drag files here, or
          </p>
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="mt-1 text-xs font-medium text-accent hover:underline"
          >
            browse
          </button>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={ACCEPTED}
            className="hidden"
            onChange={(e) => {
              if (e.target.files) addFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>

        {files.length > 0 && (
          <ul className="mt-4 space-y-1.5">
            {files.map((f, i) => (
              <li
                key={`${f.name}-${i}`}
                className="flex items-center gap-2 rounded-md border border-border bg-surface-elevated px-3 py-2 text-xs"
              >
                <FileText className="h-3.5 w-3.5 shrink-0 text-muted" aria-hidden />
                <span className="truncate text-primary">{f.name}</span>
                <span className="text-2xs text-muted">
                  {(f.size / 1024).toFixed(1)} KB
                </span>
                <button
                  type="button"
                  onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
                  aria-label={`Remove ${f.name}`}
                  className="ml-auto rounded p-0.5 text-secondary hover:bg-surface hover:text-primary"
                >
                  <X className="h-3 w-3" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-4">
          <label className="text-2xs text-secondary">
            Document type
            <input
              type="text"
              placeholder="policy"
              value={meta.doc_type ?? ""}
              onChange={(e) => setMeta((m) => ({ ...m, doc_type: e.target.value }))}
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-primary focus:border-accent focus:outline-none"
            />
          </label>
          <label className="text-2xs text-secondary">
            Jurisdiction
            <input
              type="text"
              placeholder="US"
              value={meta.jurisdiction ?? ""}
              onChange={(e) => setMeta((m) => ({ ...m, jurisdiction: e.target.value }))}
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-primary focus:border-accent focus:outline-none"
            />
          </label>
          <label className="text-2xs text-secondary">
            Effective date
            <input
              type="text"
              placeholder="2025-01-01"
              value={meta.effective_date ?? ""}
              onChange={(e) => setMeta((m) => ({ ...m, effective_date: e.target.value }))}
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-primary focus:border-accent focus:outline-none"
            />
          </label>
          <label className="text-2xs text-secondary">
            Visibility
            <select
              value={meta.visibility ?? "tenant"}
              onChange={(e) => setMeta((m) => ({ ...m, visibility: e.target.value as "tenant" | "public" | "private" }))}
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-primary focus:border-accent focus:outline-none"
            >
              <option value="tenant">Tenant Shared</option>
              <option value="private">Private (Only me)</option>
              <option value="public">Public / Global</option>
            </select>
          </label>
        </div>

        {error && (
          <p role="alert" className="mt-3 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
            {error}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={handleClose}
            disabled={submitting}
            className="rounded-md border border-border px-3 py-1.5 text-xs text-secondary hover:bg-surface-elevated hover:text-primary disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={submitting || files.length === 0}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-foreground disabled:opacity-40"
          >
            {submitting
              ? "Uploading..."
              : files.length > 0
                ? `Upload ${files.length} file${files.length === 1 ? "" : "s"}`
                : "Upload"}
          </button>
        </div>
      </div>
    </div>
  );
}