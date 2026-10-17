import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { LOADING_STAGES, LoadingSteps } from "@/components/ask/LoadingSteps";

describe("LoadingSteps", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("cycles through stages then holds at the final label", () => {
    render(<LoadingSteps />);
    expect(screen.getByText(LOADING_STAGES[0])).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1200);
    });
    expect(screen.getByText(LOADING_STAGES[1])).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1200 * 2);
    });
    expect(screen.getByText(LOADING_STAGES[3])).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1200 * 5);
    });
    expect(screen.getByText(LOADING_STAGES[3])).toBeInTheDocument();
  });
});