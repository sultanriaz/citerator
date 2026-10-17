import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { StatusPill } from "@/components/shared/StatusPill";

describe("StatusPill", () => {
  it("renders its label", () => {
    render(<StatusPill tone="healthy" label="Pipeline healthy" />);
    expect(screen.getByText("Pipeline healthy")).toBeInTheDocument();
  });

  it("is keyboard-activatable when given onClick", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<StatusPill tone="healthy" label="Pipeline healthy" onClick={onClick} />);
    const button = screen.getByRole("button");
    button.focus();
    await user.keyboard("{Enter}");
    expect(onClick).toHaveBeenCalled();
  });
});