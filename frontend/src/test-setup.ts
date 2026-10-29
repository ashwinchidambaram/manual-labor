import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./test/server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  server.events.removeAllListeners();
});
afterAll(() => server.close());

// jsdom lacks these
Element.prototype.scrollIntoView = () => {};
if (!("CSS" in globalThis)) (globalThis as unknown as { CSS: { escape: (s: string) => string } }).CSS = { escape: (s) => s };
