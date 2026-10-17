import { useCallback, useEffect, useState } from "react";
import { FileText, Layers, ListChecks, Plus } from "lucide-react";
import { TopBar } from "@/components/layout/TopBar";
import { Toast } from "@/components/shared/Toast";
import { ConfirmModal } from "@/components/shared/ConfirmModal";
import { UploadModal } from "@/components/documents/UploadModal";
import { DocumentsTable } from "@/components/documents/DocumentsTable";
import { JobsTable } from "@/components/documents/JobsTable";
import { ChunkingStrategiesTable } from "@/components/documents/ChunkingStrategiesTable";
import { ChunkPreviewDrawer } from "@/components/documents/ChunkPreviewDrawer";
import {
  deleteDocument,
  getChunkingStrategies,
  listDocuments,
  listJobs,
  reindexDocument,
  retryJob,
} from "@/api/documents";
import type {
  ChunkingStrategyRow,
  DocumentRow,
  JobRow,
  UploadResponse,
} from "@/api/types";
import { cn } from "@/lib/cn";

type Tab = "documents" | "jobs" | "strategies";

export function DocumentsPage() {
  const [tab, setTab] = useState<Tab>("documents");
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [strategies, setStrategies] = useState<ChunkingStrategyRow[]>([]);
  const [activeStrategy, setActiveStrategy] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [toast, setToast] = useState<{ tone: "success" | "error"; message: string } | null>(null);

  const [confirmDelete, setConfirmDelete] = useState<DocumentRow | null>(null);
  const [chunkDoc, setChunkDoc] = useState<DocumentRow | null>(null);
  const [chunkOpen, setChunkOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [d, j, s] = await Promise.all([
        listDocuments({ limit: 500 }),
        listJobs({ limit: 50 }).catch(() => [] as JobRow[]),
        getChunkingStrategies().catch(() => ({
          strategies: [] as ChunkingStrategyRow[],
          active: "",
        })),
      ]);
      setDocs(d.documents);
      setJobs(j);
      setStrategies(s.strategies);
      setActiveStrategy(s.active);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load documents.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const anyPending = jobs.some(
      (j) => !["indexed", "failed", "empty"].includes(j.status)
    );
    if (!anyPending) return;
    const t = window.setInterval(refresh, 2000);
    return () => window.clearInterval(t);
  }, [jobs, refresh]);

  function onUploadAccepted(response: UploadResponse) {
    setToast({
      tone: "success",
      message: `Uploaded ${response.count} file${response.count === 1 ? "" : "s"}. Ingestion started.`,
    });
    setTab("jobs");
    void refresh();
  }

  async function onConfirmDelete() {
    if (!confirmDelete) return;
    const target = confirmDelete;
    setConfirmDelete(null);
    try {
      await deleteDocument(target.doc_id);
      setToast({ tone: "success", message: `Deleted ${target.title ?? target.source_file}.` });
      void refresh();
    } catch (err) {
      setToast({
        tone: "error",
        message: err instanceof Error ? err.message : "Delete failed.",
      });
    }
  }

  async function onReindex(doc: DocumentRow) {
    try {
      const res = await reindexDocument(doc.doc_id);
      setToast({ tone: "success", message: `Reindex scheduled (job ${res.job_id.slice(0, 8)}).` });
      setTab("jobs");
      void refresh();
    } catch (err) {
      setToast({
        tone: "error",
        message: err instanceof Error ? err.message : "Reindex failed.",
      });
    }
  }

  async function onRetryJob(jobId: string) {
    try {
      await retryJob(jobId);
      setToast({ tone: "success", message: "Job requeued." });
      void refresh();
    } catch (err) {
      setToast({
        tone: "error",
        message: err instanceof Error ? err.message : "Retry failed.",
      });
    }
  }

  const totalChunks = docs.reduce((acc, d) => acc + (d.chunk_count ?? 0), 0);
  const jurisdictions = new Set(
    docs.map((d) => d.jurisdiction).filter((j): j is string => !!j)
  ).size;

  return (
    <div className="flex h-full flex-col">
      <TopBar
        breadcrumbs={["Workspace", "Documents"]}
        rightSlot={
          <button
            type="button"
            onClick={() => setUploadOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-foreground"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden />
            Upload documents
          </button>
        }
      />

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <header className="mb-5">
          <h1 className="text-2xl font-semibold tracking-tight text-primary">
            Documents
          </h1>
          <p className="mt-1 text-xs text-secondary">
            Your regulatory corpus. Indexed, traceable, and ready to query.
          </p>
        </header>

        <div className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="flex h-[68px] items-center gap-3 rounded-xl border border-border bg-surface px-4">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-elevated">
              <FileText className="h-4 w-4 text-accent" aria-hidden />
            </span>
            <div className="min-w-0">
              <div className="text-xl font-semibold leading-none text-primary">{docs.length}</div>
              <div className="mt-1 truncate text-2xs text-secondary">indexed documents</div>
            </div>
          </div>
          <div className="flex h-[68px] items-center gap-3 rounded-xl border border-border bg-surface px-4">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-elevated">
              <Layers className="h-4 w-4 text-accent" aria-hidden />
            </span>
            <div className="min-w-0">
              <div className="text-xl font-semibold leading-none text-primary">{totalChunks}</div>
              <div className="mt-1 truncate text-2xs text-secondary">searchable chunks</div>
            </div>
          </div>
          <div className="flex h-[68px] items-center gap-3 rounded-xl border border-border bg-surface px-4">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-elevated">
              <ListChecks className="h-4 w-4 text-accent" aria-hidden />
            </span>
            <div className="min-w-0">
              <div className="text-xl font-semibold leading-none text-primary">{jurisdictions}</div>
              <div className="mt-1 truncate text-2xs text-secondary">jurisdictions</div>
            </div>
          </div>
        </div>

        <nav className="mb-4 flex gap-4 border-b border-border text-xs">
          {(["documents", "jobs", "strategies"] as Tab[]).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={cn(
                "-mb-px border-b-2 px-1 pb-2 font-medium transition-colors",
                tab === t
                  ? "border-accent text-accent"
                  : "border-transparent text-secondary hover:text-primary"
              )}
            >
              {t === "documents"
                ? "Documents"
                : t === "jobs"
                  ? `Ingestion jobs${jobs.length ? ` (${jobs.length})` : ""}`
                  : "Chunking strategies"}
            </button>
          ))}
        </nav>

        {loading && (
          <p className="text-xs text-secondary">Loading...</p>
        )}

        {error && (
          <p className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
            {error}
          </p>
        )}

        {!loading && !error && tab === "documents" && (
          <DocumentsTable
            documents={docs}
            onDelete={(d) => setConfirmDelete(d)}
            onReindex={onReindex}
            onViewChunks={(d) => {
              setChunkDoc(d);
              setChunkOpen(true);
            }}
          />
        )}

        {!loading && !error && tab === "jobs" && (
          <JobsTable jobs={jobs} onRetry={onRetryJob} />
        )}

        {!loading && !error && tab === "strategies" && (
          <ChunkingStrategiesTable strategies={strategies} activeStrategy={activeStrategy} />
        )}
      </div>

      <UploadModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onAccepted={onUploadAccepted}
      />

      <ConfirmModal
        open={confirmDelete != null}
        title={`Delete ${confirmDelete?.title ?? confirmDelete?.source_file ?? ""}?`}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        onConfirm={onConfirmDelete}
        onCancel={() => setConfirmDelete(null)}
      >
        This removes the document from Qdrant, the registry, the manifest, and the
        source file on disk. This action cannot be undone.
      </ConfirmModal>

      <ChunkPreviewDrawer
        open={chunkOpen}
        onClose={() => setChunkOpen(false)}
        doc={chunkDoc}
      />

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 w-80">
          <Toast
            tone={toast.tone}
            message={toast.message}
            onDismiss={() => setToast(null)}
          />
        </div>
      )}
    </div>
  );
}