import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EscalationModal } from "@/components/ask/EscalationModal";

const draft = {
  question: "Is this a PEP?",
  passages: [],
  suggested_note: "Ambiguous -- needs human review",
};

describe("EscalationModal", () => {
  it("pre-fills the note from the draft and posts on submit", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <EscalationModal
        open
        onClose={onClose}
        source="escalated"
        question="Is this a PEP?"
        draft={draft}
        traceId="trace-1"
      />
    );

    const note = screen.getByLabelText(/note/i) as HTMLTextAreaElement;
    expect(note.value).toBe(draft.suggested_note);

    await user.clear(note);
    await user.type(note, "Reviewed and confirmed");
    await user.click(screen.getByRole("button", { name: /send escalation/i }));

    await waitFor(() =>
      expect(screen.getByText(/Escalation submitted/i)).toBeInTheDocument()
    );
  });
});