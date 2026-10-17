import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AskPage } from "@/pages/AskPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <AskPage />
    </MemoryRouter>
  );
}

describe("AskPage", () => {
  it("renders the confident answer with a citation chip", async () => {
    const user = userEvent.setup();
    renderPage();

    const textarea = screen.getByLabelText(/compliance question/i);
    await user.type(textarea, "When is enhanced due diligence required?");
    await user.click(screen.getByRole("button", { name: /send question/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/Enhanced due diligence is required/i)
      ).toBeInTheDocument()
    );
    expect(
      screen.getByRole("button", { name: /open source 1/i })
    ).toBeInTheDocument();
  });

  it("renders the low_confidence warning banner and escalate button", async () => {
    const user = userEvent.setup();
    renderPage();

    const textarea = screen.getByLabelText(/compliance question/i);
    await user.type(textarea, "low signal question");
    await user.click(screen.getByRole("button", { name: /send question/i }));

    await waitFor(() =>
      expect(screen.getByText(/Limited evidence found/i)).toBeInTheDocument()
    );
    expect(
      screen.getByRole("button", { name: /escalate to compliance team/i })
    ).toBeInTheDocument();
  });

  it("renders the insufficient state with no answer text", async () => {
    const user = userEvent.setup();
    renderPage();

    const textarea = screen.getByLabelText(/compliance question/i);
    await user.type(textarea, "insufficient evidence question");
    await user.click(screen.getByRole("button", { name: /send question/i }));

    // The component renders "couldn&rsquo;t find enough evidence" (curly
    // apostrophe). Matching on the substring after the apostrophe avoids
    // the straight-vs-curly mismatch without needing an exact copy.
    await waitFor(() =>
      expect(
        screen.getByText(/find enough evidence/i)
      ).toBeInTheDocument()
    );
    expect(
      screen.getByRole("button", { name: /escalate to a human/i })
    ).toBeInTheDocument();
  });
});