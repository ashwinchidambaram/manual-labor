// Runs after the web servers are up (Playwright starts webServer before globalSetup): mark the getting-started
// guide as seen on both API servers, so every existing spec runs with the panel hidden (design 12 section 3).
// onboarding.spec.ts clears the flag for its own tests and sets it again afterwards.
import { request } from "@playwright/test";

export default async function globalSetup(): Promise<void> {
  for (const port of [8765, 8766]) {
    const ctx = await request.newContext({ baseURL: `http://127.0.0.1:${port}` });
    const r = await ctx.put("/api/ui/guide", { data: { seen: true } });
    if (!r.ok()) throw new Error(`global setup: PUT /api/ui/guide on ${port} answered ${r.status()}: ${await r.text()}`);
    await ctx.dispose();
  }
}
