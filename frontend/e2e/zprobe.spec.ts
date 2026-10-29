import { test } from "@playwright/test";
import { api, resetSelection, waitJobsIdle } from "./helpers";
test("probe", async ({ page, request }) => {
  await resetSelection(request);
  await request.post("/api/scope/confirm", { data: {} });
  await waitJobsIdle(request);
  page.on("console", (m) => { if (m.text().startsWith("PR")) console.log(m.text()); });
  await page.addInitScript(() => {
    const d = (e: Element | null) => (e ? `${e.tagName}${e.getAttribute("data-testid") ? "#" + e.getAttribute("data-testid") : ""}${e.getAttribute("aria-label") ? "[" + e.getAttribute("aria-label") + "]" : ""}` : "null");
    const t0 = performance.now();
    document.addEventListener("focusin", (e) => console.log(`PR ${(performance.now() - t0).toFixed(0)} focusin ${d(e.target as Element)}`), true);
  });
  await page.goto("/verify");
  await page.waitForTimeout(800);
  for (const k of ["a", "a", "e"]) { console.log("PR key " + k); await page.keyboard.press(k); await page.waitForTimeout(100); }
  await page.keyboard.type("x");
  console.log("PR key ctrl+enter");
  await page.keyboard.press("ControlOrMeta+Enter");
  await page.waitForTimeout(1000);
  console.log("PR key a"); await page.keyboard.press("a");
  console.log("PR key f"); await page.keyboard.press("f");
  await page.waitForTimeout(1000);
});
