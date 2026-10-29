import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./test/server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(async () => {
  cleanup();
  // Unmounting flushes pending selection edits; let that PUT land on this test's handlers, not the next test's.
  await new Promise((r) => setTimeout(r, 30));
  server.resetHandlers();
  server.events.removeAllListeners();
});
afterAll(() => server.close());

// jsdom lacks these
Element.prototype.scrollIntoView = () => {};
Element.prototype.scrollTo = () => {};
if (!("CSS" in globalThis)) (globalThis as unknown as { CSS: { escape: (s: string) => string } }).CSS = { escape: (s) => s };
if (typeof ResizeObserver === "undefined")
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
// jsdom has no layout: give virtualised scroll containers a viewport (the Verify queue is role=listbox).
for (const [prop, size] of [["offsetHeight", 640], ["offsetWidth", 320]] as const)
  Object.defineProperty(HTMLElement.prototype, prop, {
    configurable: true,
    get(this: HTMLElement) {
      return this.getAttribute("role") === "listbox" ? size : 0;
    },
  });
