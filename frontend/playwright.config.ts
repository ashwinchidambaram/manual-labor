import { defineConfig, devices } from "@playwright/test";

// One shared server and project: selection state is global, so tests run serially.
export default defineConfig({
  testDir: "e2e",
  workers: 1,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // Builds or reuses the cached mock project, copies it to a temp dir and serves the API.
      command: "bash ../scripts/e2e-serve.sh",
      url: "http://127.0.0.1:8765/api/project",
      reuseExistingServer: false,
      timeout: 300_000,
      stdout: "pipe",
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5173 --strictPort",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      // E0: the built dist served by `labor serve` (no --dev) on its own port.
      command: "npm run build && E2E_PORT=8766 E2E_DEV=0 bash ../scripts/e2e-serve.sh",
      url: "http://127.0.0.1:8766/api/project",
      reuseExistingServer: false,
      timeout: 300_000,
    },
  ],
});
