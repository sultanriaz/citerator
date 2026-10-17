import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { ThemeToggle } from "@/components/layout/ThemeToggle";

describe("ThemeToggle", () => {
  beforeEach(() => {
    window.localStorage.clear();
    // Pin the initial theme so the test doesn't depend on jsdom's
    // matchMedia behavior. useTheme reads localStorage first.
    window.localStorage.setItem("citerator.theme", "dark");
  });

  it("toggles data-theme and persists to localStorage", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);
    const button = screen.getByRole("button");

    await user.click(button);
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("citerator.theme")).toBe("light");
  });

  it("has an aria-label", () => {
    render(<ThemeToggle />);
    expect(screen.getByRole("button")).toHaveAccessibleName(/theme/i);
  });
});