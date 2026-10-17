import { useEffect, useState } from "react";
import { postEscalation } from "@/api/escalations";
import { Toast } from "@/components/shared/Toast";
import type {
  EscalationDraft,
  EscalationRequest,
  EscalationSource,
} from "@/api/types";

export interface EscalationModalProps {
  open: boolean;
  onClose: () => void;
  source: EscalationSource;
  question: string;
  draft: EscalationDraft | null;
  traceId: string | null;
}

export function EscalationModal({
  open,
  onClose,
  source,
  question,
  draft,
  traceId,
}: EscalationModalProps) {
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState<{ tone: "success" | "error"; message: string } | null>(
    null
  );

  useEffect(() => {
    if (!open) return;
    setNote(draft?.suggested_note ?? "");
    setToast(null);
  }, [open, draft]);

  if (!open) return null;

  const passages = (draft?.passages ?? []).map((p) => ({
    chunk_id: p.chunk_id,
    doc_title: p.doc_title,
    section_path: p.section_path,
    page_start: p.page_start,
    page_end: p.page_end,
    excerpt: p.text?.slice(0, 240) ?? null,
  }));

  async function submit() {
    setSubmitting(true);
    const body: EscalationRequest = {
      trace_id: traceId,
      source,
      question: draft?.question ?? question,
      passages,
      note,
    };
    try {
      await postEscalation(body);
      setToast({ tone: "success", message: "Escalation submitted." });
      window.setTimeout(onClose, 900);
    } catch (err) {
      setToast({
        tone: "error",
        message:
          err instanceof Error ? err.message : "Could not submit escalation.",
      });
    } finally {
      setSubmitting(false);
    }
  }

  function copyDraft() {
    const text = [
      `Question: ${draft?.question ?? question}`,
      "",
      `Note: ${note || draft?.suggested_note || ""}`,
      "",
      ...passages.map(
        (p, i) =>
          `[${i + 1}] ${p.doc_title ?? ""}${
            p.section_path?.length ? " \u00B7 " + p.section_path.join(" \u203A ") : ""
          }`
      ),
    ].join("\n");
    void navigator.clipboard.writeText(text);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Escalate to compliance team"
        className="relative w-full max-w-2xl rounded-lg border border-border bg-surface p-5 shadow-xl"
      >
        <h2 className="text-sm font-medium text-primary">
          {source === "flagged" ? "Flag for review" : "Escalate to compliance team"}
        </h2>

        <p className="mt-3 text-xs text-secondary">Question</p>
        <p className="mt-1 text-sm text-primary">{draft?.question ?? question}</p>

        {passages.length > 0 && (
          <>
            <p className="mt-4 text-xs text-secondary">Passages</p>
            <ul className="mt-1 space-y-1 text-2xs">
              {passages.map((p, i) => (
                <li key={p.chunk_id ?? i} className="rounded border border-border bg-surface-elevated px-2 py-1.5">
                  <div className="font-medium text-primary">
                    [{i + 1}] {p.doc_title}
                  </div>
                  {p.excerpt && <p className="mt-0.5 text-secondary">{p.excerpt}</p>}
                </li>
              ))}
            </ul>
          </>
        )}

        <label className="mt-4 block text-xs text-secondary">
          Note
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={4}
            className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-xs text-primary focus:outline-none focus:border-accent"
          />
        </label>

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={copyDraft}
            className="rounded-md border border-border px-3 py-1.5 text-xs text-secondary hover:bg-surface-elevated hover:text-primary"
          >
            Copy as text
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border px-3 py-1.5 text-xs text-secondary hover:bg-surface-elevated hover:text-primary"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={submitting}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-foreground disabled:opacity-40"
          >
            {submitting ? "Sending..." : "Send escalation"}
          </button>
        </div>

        {toast && (
          <div className="mt-4">
            <Toast
              tone={toast.tone}
              message={toast.message}
              onDismiss={() => setToast(null)}
            />
          </div>
        )}
      </div>
    </div>
  );
}