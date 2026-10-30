// A spec that changes the project in a way no other spec may see (a new manual, every document unscored) runs its own
// `labor serve` over a fresh copy of the cached e2e project. The copy is made in beforeAll, so a retry (CI `retries: 1`
// starts a new worker) begins from the cache again instead of from what the failed attempt left behind. The page is the
// built dist (made by the 8766 web server's `npm run build`). Specs run one at a time (workers: 1), so they can share a
// port: `stop` waits until the server has exited and the port is free.
import { type ChildProcess, spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, request as pwRequest, type APIRequestContext } from "@playwright/test";
import type { JobInfo } from "../src/api/schema";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "../..");
const CACHE = path.join(HERE, ".cache");
const LOCK = path.join(HERE, ".cache.lock");

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Copy the cached project under the same mkdir mutex scripts/e2e-serve.sh uses. */
async function copyCache(dst: string): Promise<void> {
  for (let i = 0; ; i++) {
    try {
      fs.mkdirSync(LOCK);
      break;
    } catch {
      if (i > 900) throw new Error("the e2e cache lock was held for 15 minutes");
      await sleep(1000);
    }
  }
  try {
    fs.cpSync(path.join(CACHE, "project"), dst, { recursive: true });
  } finally {
    fs.rmdirSync(LOCK);
  }
}

const portOpen = (port: number): Promise<boolean> =>
  new Promise((resolve) => {
    const s = net.connect({ host: "127.0.0.1", port }, () => {
      s.destroy();
      resolve(true);
    });
    s.on("error", () => resolve(false));
  });

export interface OwnServer {
  base: string;
  api: APIRequestContext;
  /** the copied project's directory */
  project: string;
  /** cancel its jobs, stop the server, wait for the port to be free, delete the copy */
  stop: () => Promise<void>;
}

export async function startOwnServer(opts: { port: number; prepare?: (project: string) => void; env?: Record<string, string> }): Promise<OwnServer> {
  const { port } = opts;
  if (await portOpen(port)) throw new Error(`port ${port} is in use: another server is still running there`);
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), `ml-e2e-${port}-`));
  const project = path.join(tmp, "project");
  await copyCache(project);
  opts.prepare?.(project);
  const server: ChildProcess = spawn("uv", ["run", "labor", "serve", project, "--mock", "--port", String(port)], {
    cwd: ROOT,
    env: { ...process.env, ...(opts.env ?? {}) },
    stdio: "ignore",
    detached: true,
  });
  const exited = new Promise<void>((r) => server.once("exit", () => r()));
  const base = `http://127.0.0.1:${port}`;
  const api = await pwRequest.newContext({ baseURL: base });
  await expect.poll(async () => (await api.get("/api/project").catch(() => null))?.ok() ?? false, { timeout: 120_000, intervals: [500] }).toBe(true);
  expect((await api.put("/api/ui/guide", { data: { seen: true } })).ok()).toBe(true);

  const stop = async (): Promise<void> => {
    try {
      const active = (await (await api.get("/api/jobs?status=queued&status=running")).json()) as JobInfo[];
      for (const j of active) await api.post(`/api/jobs/${j.id}/cancel`);
      await expect.poll(async () => ((await (await api.get("/api/jobs?status=queued&status=running")).json()) as unknown[]).length, { timeout: 30_000 }).toBe(0);
    } catch {
      /* the server is already gone */
    }
    await api.dispose();
    if (server.pid && server.exitCode === null && server.signalCode === null) {
      try {
        process.kill(-server.pid, "SIGTERM");
      } catch {
        /* already gone */
      }
      await Promise.race([exited, sleep(20_000)]);
    }
    await expect.poll(() => portOpen(port), { timeout: 20_000, intervals: [250] }).toBe(false);
    fs.rmSync(tmp, { recursive: true, force: true });
  };
  return { base, api, project, stop };
}
