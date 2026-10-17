import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { DocumentsPage } from "@/pages/DocumentsPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <DocumentsPage />
    </MemoryRouter>
  );
}

describe("DocumentsPage", () => {
  it("renders documents from GET /documents", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("FATF Recommendations")).toBeInTheDocument()
    );
    expect(screen.getAllByText("1").length).toBeGreaterThanOrEqual(1); // doc count
  });

  it("opens the upload modal and submits a file", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("FATF Recommendations")).toBeInTheDocument()
    );

    await user.click(screen.getByRole("button", { name: /upload documents/i }));
    expect(
      screen.getByRole("dialog", { name: /upload documents/i })
    ).toBeInTheDocument();

    const file = new File(["# Hello"], "hello.md", { type: "text/markdown" });
    const input = document.querySelector(
      'input[type="file"]'
    ) as HTMLInputElement;
    await user.upload(input, file);

    await waitFor(() =>
      expect(screen.getByText("hello.md")).toBeInTheDocument()
    );

    await user.click(screen.getByRole("button", { name: /upload 1 file/i }));

    await waitFor(() =>
      expect(screen.getByText(/Uploaded 1 file/i)).toBeInTheDocument()
    );
  });

  it("switches to the jobs tab", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("FATF Recommendations")).toBeInTheDocument()
    );

    await user.click(screen.getByRole("button", { name: /ingestion jobs/i }));
    await waitFor(() =>
      expect(screen.getByText("policy.md")).toBeInTheDocument()
    );
  });
});