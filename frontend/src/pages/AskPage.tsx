import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { TopBar } from "@/components/layout/TopBar";
import { QueryInput } from "@/components/ask/QueryInput";
import { ExampleChips } from "@/components/ask/ExampleChips";
import { FilterRow, type FilterState } from "@/components/ask/FilterRow";
import { AnswerThread } from "@/components/ask/AnswerThread";
import { EvidencePanel } from "@/components/ask/EvidencePanel";
import { RetrievalDetailsDrawer } from "@/components/ask/RetrievalDetailsDrawer";
import { EscalationModal } from "@/components/ask/EscalationModal";
import { useQuery, type QueryTurn } from "@/hooks/useQuery";
import type { EscalationSource, RetrievedChunk } from "@/api/types";

export function AskPage() {
  const { turns, inFlight, submit, retry } = useQuery();
  const [filters, setFilters] = useState<FilterState>({
    docId: null,
    jurisdiction: null,
    showRetrievalDetails: false,
  });

  const [evidenceChunk, setEvidenceChunk] = useState<RetrievedChunk | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(false);

  const [retrievalDetails, setRetrievalDetails] = useState<QueryTurn | null>(null);

  const [escalation, setEscalation] = useState<{
    source: EscalationSource;
    turn: QueryTurn;
  } | null>(null);

  function handleSubmit(question: string) {
    void submit({
      question,
      document_scope: filters.docId ? [filters.docId] : null,
      jurisdiction: filters.jurisdiction,
      show_retrieval_details: filters.showRetrievalDetails,
    });
  }

  function handleOpenEvidence(chunk: RetrievedChunk | null) {
    setEvidenceChunk(chunk);
    setEvidenceOpen(true);
  }

  const emptyState = useMemo(() => turns.length === 0, [turns.length]);

  return (
    <div className="flex h-full flex-col">
      <TopBar breadcrumbs={["Workspace", "Ask"]} />
      <div className="grid flex-1 min-h-0 grid-cols-1 md:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-w-0 flex-col overflow-y-auto px-6 py-6">
          <header className="mb-5">
            <h1 className="text-2xl font-semibold tracking-tight text-primary">
              Ask
            </h1>
            <p className="mt-1 text-xs text-secondary">
              Grounded answers with citations, or an escalation when the evidence
              is thin.
            </p>
          </header>

          <div className="space-y-3">
            <QueryInput onSubmit={handleSubmit} disabled={inFlight} />
            <FilterRow value={filters} onChange={setFilters} />
          </div>

          <div className="mt-6">
            {emptyState ? (
              <div className="rounded-xl border border-dashed border-border bg-surface px-6 py-10 text-center">
                <Search className="mx-auto h-6 w-6 text-muted" aria-hidden />
                <p className="mt-3 text-sm text-primary">
                  Ask a question, or try one of these:
                </p>
                <div className="mt-4 flex justify-center">
                  <ExampleChips onSelect={handleSubmit} />
                </div>
              </div>
            ) : (
              <AnswerThread
                turns={turns}
                onRetry={retry}
                onOpenEvidence={handleOpenEvidence}
                onOpenRetrieval={(turn) => setRetrievalDetails(turn)}
                onEscalate={(turn) => setEscalation({ source: "escalated", turn })}
                onFlag={(turn) => setEscalation({ source: "flagged", turn })}
              />
            )}
          </div>

          <p className="mt-6 text-center text-2xs text-secondary">
            Answers use only your indexed documents. When evidence is weak, we escalate.
          </p>
        </div>

        <aside className="hidden md:block border-l border-border bg-bg px-5 py-6">
          <h2 className="text-xs uppercase tracking-wider text-muted">
            Session
          </h2>
          <dl className="mt-3 space-y-2 text-xs">
            <div className="flex justify-between">
              <dt className="text-secondary">Questions</dt>
              <dd className="text-primary">{turns.length}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-secondary">Confident</dt>
              <dd className="text-primary">
                {turns.filter((t) => t.response?.state === "confident").length}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-secondary">Escalated</dt>
              <dd className="text-primary">
                {turns.filter((t) => t.response?.state === "insufficient").length}
              </dd>
            </div>
          </dl>
        </aside>
      </div>

      <EvidencePanel
        open={evidenceOpen}
        onClose={() => setEvidenceOpen(false)}
        chunk={evidenceChunk}
      />

      <RetrievalDetailsDrawer
        open={retrievalDetails != null}
        onClose={() => setRetrievalDetails(null)}
        details={retrievalDetails?.response?.retrieval_details ?? null}
      />

      <EscalationModal
        open={escalation != null}
        onClose={() => setEscalation(null)}
        source={escalation?.source ?? "escalated"}
        question={escalation?.turn.question ?? ""}
        draft={escalation?.turn.response?.escalation_draft ?? null}
        traceId={escalation?.turn.traceId ?? null}
      />
    </div>
  );
}