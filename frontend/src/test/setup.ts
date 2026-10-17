import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./mocks/handlers";

// jsdom does not implement Element.scrollIntoView. AnswerThread calls it
// after every render; without this stub every AskPage test throws.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {
    /* no-op in jsdom */
  };
}

// jsdom's default matchMedia returns matches: false for every query, which
// would make useTheme start in "light" mode even though the design is
// dark-first. Report dark as preferred so the initial theme matches
// production.
if (typeof window !== "undefined") {
  window.matchMedia = ((query: string) => ({
    matches: /dark/.test(query),
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());