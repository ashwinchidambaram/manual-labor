# Module 7 design: project state, stage graph, background jobs, API, `labor check`, `labor serve`

Status: draft for approval · Inputs: SPEC §3, §4, §5.4, §5.5, §7, §8, §9, §10 · CLAUDE.md (gate: "Resumable: kill mid-run, restart, continue; every action persisted") · findings.md "self-improvement" + "Learning must be reversible" · designs 00 §4.6–4.11/§10.12, 01 §10/§14, 02 §9/§14, 03 §6/§7, 04 §5/§7, 05 §4/§5.3/§7/§8, 06 §1/§4/§5.
Implementers: **A** (state store, stage graph, jobs, learning layer, `labor check/run/status`) and **B** (FastAPI app, OpenAPI → TS, `labor serve`, static assets), in parallel (§11). Neither may change this design; report what you cannot satisfy.

## 0. Facts this design rests on (read from the code, 2026-10-29)

| Fact | Consequence |
|---|---|
| Stage entry points: `parse_project(paths, force, only, emit, workers) -> int`, `run_figures(paths, only, force, emit) -> list[str]`, `run_score / run_group / run_clean(paths, only, force, providers: ProviderSet \| Callable[[], ProviderSet] \| None, emit, …) -> list[str]` | The executor calls these as plain functions; it injects `providers` and `emit`. `run_clean` is called with `rescore=False`; score(2) is its own node. |
| Every stage skips by its own fingerprint, but the fingerprint is computed inside private helpers (`_skip_if_current`, figures `_fingerprint`, scoring inline in `_score_doc`, cleanup `fp_clean/fp_attach/fp_desc`) | Forced change F1: expose them as pure public functions (§10.1). |
| Parse metadata builds its own provider from `DEFAULT_FACTORIES` (`ingest.metadata_provider`), not injectable | Mock forcing must also rewrite the copied config (§6). |
| `project-a/project.json` is already all-`mock`; it holds `sources/clean.pdf`, `sources/figures.pdf` and no `docs/` | `labor check` must ingest first. `--live` cannot mean "use the configured providers" for project-a (§6). |
| Modules 4/5 read the learned layer only from `learning/grouping.json` / `learning/cleanup.json` and take provenance from the file's `snapshot` field | The versioned layer is *materialized* into those two paths. Modules 4/5 need no code change (§9). |
| LLM log is `<project>/llm_calls.jsonl` (00 §6.2 says `logs/`) | Keep the code path; fix 00 §6.2 text. |
| Scoring appends `score_history.jsonl` *after* writing `scores.json` | A kill between them breaks byte-identical resume. Forced change F3. |
| Spawn pool (01 §14.13) | Stages run only inside `labor …` CLI processes or `python -m manuallabor.jobs.worker` (both `__main__`-guarded), never from an inline script. |
| 06 T5 allows network imports only in `providers/**` and `server*` | `api/` and `serve.py` must not import `httpx/requests/urllib.request/aiohttp/socket` (tests may). |

## 1. Package layout

| Path | Owner | Contents |
|---|---|---|
| `manuallabor/state/__init__.py` | A | empty |
| `state/models.py` | A, **day 0, verbatim from §5.2** | every DTO crossing the A/B boundary |
| `state/interfaces.py` | A, day 0 | `Protocol`s of §11.2 plus `NotImplementedError` stubs so B can code before A lands |
| `state/db.py` | A | `connect(path, readonly)`, pragmas, `migrate(conn)`, `StateError` |
| `state/migrations.py` | A | `MIGRATIONS: list[str]` (SQL scripts; index+1 = `user_version`) |
| `state/store.py` | A | `Store`: the only code that touches `project.db` |
| `state/review.py` | A | status derivation, overlay, `load_review_blocks`, queue, cursor, why-list, human-edit check, `ReviewService` |
| `state/scope.py` | A | `ScopeService` (selection ops, coverage, summary, regroup, model panel data) |
| `state/figures.py` | A | `FigureService` (rail, attach/detach, bbox overrides) |
| `state/projections.py` | A | DB → file projections and `reconcile(store, paths)` |
| `state/learning.py` | A | snapshots, derive, activate/reset/rollback/publish, global store, `LearningService` |
| `state/lock.py` | A | `ProjectLock` (fcntl flock) |
| `manuallabor/faults.py` | A | `fault(point)` test hook (§8) |
| `manuallabor/jobs/graph.py` | A | `Node`, `NODES`, `node_state`, `project_status` (§3) |
| `jobs/executor.py` | A | `make_plan`, `execute`, `stages.json` bookkeeping |
| `jobs/providers.py` | A | `ProviderMode`, `MOCK_ONLY_FACTORIES`, `mockify(cfg)`, `provider_set_factory(...)` |
| `jobs/worker.py` | A | `python -m manuallabor.jobs.worker <root> <job_id>` (has `if __name__ == "__main__":`) |
| `jobs/runner.py` | A | `JobRunner` supervisor thread (lives in the serve process) |
| `manuallabor/check.py` | A | `run_check(...)` for `labor check` |
| `manuallabor/api/app.py` | B | `create_app(ctx: AppContext) -> FastAPI`, static mount |
| `api/models.py` | B | request bodies + re-exports of `state.models` used in responses |
| `api/deps.py` | B | `AppContext{paths, store, review, scope, figures, learning, runner, mock}` dependency |
| `api/routes/{project,sources,scope,verify,figures,learning,jobs,agent,export}.py` | B | one router per area (§5) |
| `api/openapi.py` | B | `export_openapi(out, check) -> bool` |
| `manuallabor/serve.py` | B | `serve(paths, host, port, dev, mock, resume)` |
| `manuallabor/cli_serve.py` | B | `register(app: typer.Typer)` adds `serve` and `openapi export` |
| `manuallabor/cli.py` | A | `status`, `run`, `check`, `learning …`, `decisions export`; stage commands routed through the executor (F6); one line `cli_serve.register(app)` (A adds it day 0 against B's stub) |
| `frontend/src/api/{openapi.json,schema.d.ts,client.ts}` | B | generated spec, generated types, typed fetch wrapper |

New project paths (F4, `project.py`, A): `ProjectPaths.db = root/"project.db"`, `.lock = root/".labor.lock"`, `.worker_lock = root/".labor.worker.lock"`, `.logs = root/"logs"`, `.job_log(id) = logs/"jobs"/f"{id}.jsonl"`, `.job_plan(id)`, `.uploads = root/".uploads"`, `.learning = root/"learning"`, `.learning_active = learning/"active.json"`, `.snapshot_dir(id) = learning/"snapshots"/id`, `.learned_calibration = learning/"calibration.json"`; `DocPaths.stages = root/"stages.json"`, `DocPaths.figure_overrides = root/"figure_overrides.json"`, `DocPaths.page_view(page, dpi) = root/"pages_view"/f"p{page:03d}-{dpi}.png"`. `learned_cleanup` / `learned_grouping` keep their paths; their docstrings say "materialized active snapshot (module 7)".

## 2. SQLite state (`<project>/project.db`)

### 2.1 Connection rules
`PRAGMA journal_mode=WAL; synchronous=NORMAL; foreign_keys=ON; busy_timeout=5000`. **One writer process per project**, enforced by `ProjectLock` (§4.4). In that process `Store` holds one connection (`check_same_thread=False`) behind a `threading.Lock`; every write is `BEGIN IMMEDIATE … COMMIT` and covers exactly one user action. Readers that do not hold the lock (`labor status`) open with `mode=ro`. Timestamps come from an injected `Clock` and use the 00 §2 `UTCDateTime` format. JSON columns hold `canonical_json`. `Store.close()` runs `PRAGMA wal_checkpoint(TRUNCATE)`, so a stopped project is a single file you can zip.

**What goes where:** anything derivable from stage files (blocks, scores, groups, clean, attach, figures) stays in files. The DB holds human actions, the current human state (selection, cursor, flags), overrides and job bookkeeping. Files that stages *read* (`selection.json`, `group_overrides.json`, `attach_overrides.json`, `figure_overrides.json`, `learning/*.json`) are **projections** of DB rows (§2.4).

### 2.2 Tables (migration 1)

| Table | Columns (type) | Rules |
|---|---|---|
| `meta` | `key TEXT PK`, `value TEXT` | `project_uuid`, `created_at` |
| `blobs` | `sha256 TEXT PK`, `body TEXT` | content-addressed before/after snapshots; `INSERT OR IGNORE` |
| `actions` | `id INTEGER PK AUTOINCREMENT`, `ts`, `screen` (scope, verify, agent, export, settings, cli), `kind` (§5.2 `ActionKind`), `target_id NULL`, `doc_id NULL`, `payload` JSON, `example` JSON NULL, `before_ref` NULL → blobs, `after_ref` NULL → blobs, `learning_provenance TEXT NULL`, `request_id TEXT UNIQUE NULL` | **append-only**: triggers `BEFORE UPDATE` / `BEFORE DELETE` → `RAISE(ABORT,'append-only')`. `example` is the full learning example (§2.5). |
| `decisions` | `seq INTEGER PK AUTOINCREMENT` (= `Decision.seq`), `action_id UNIQUE → actions`, `block_id`, `doc_id`, `action` (approve, edit, flag, skip), `score REAL NULL`, `threshold REAL`, `signals` JSON, `edited_text NULL`, `flag_id NULL`, `ts`, `raw_sha256`, `shown_text_sha256`, `faith_passed INT NULL`, `human_edit_diff` JSON NULL, `numbers_verified INT`, `learning_provenance`, `source` (human, agent) | append-only (same triggers). Written in the same transaction as its action. Index `(block_id, seq)`. |
| `flags` | `n INTEGER PK AUTOINCREMENT` (id = `flag-{n:06d}`), `target_id`, `category`, `note NULL`, `status`, `created_at`, `resolved_at NULL`, `resolution NULL`, `created_action_id`, `resolved_action_id NULL` | the only mutable columns are `status, resolved_at, resolution, resolved_action_id`, and only open→resolved (trigger). Rows map 1:1 to `Flag`. |
| `proposals` | `n PK` (id `prop-{n:06d}`), `flag_id → flags`, `target_id`, `round`, `body` JSON (`Proposal`), `status`, `created_at`, `decided_action_id NULL` | created now, written by module 10 |
| `selection` | `id INTEGER PK CHECK(id=1)`, `body` JSON (`Selection`), `action_id` | current state; history = actions with before/after refs |
| `group_overrides` | `seq INTEGER PK AUTOINCREMENT` (= `GroupOverride.seq`), `doc_id`, `body` JSON, `action_id` | append-only |
| `attach_overrides` | `seq PK AUTOINCREMENT` (= `AttachOverride.seq`), `doc_id`, `body` JSON, `action_id` | append-only |
| `figure_overrides` | `seq PK AUTOINCREMENT`, `doc_id`, `figure_id`, `bbox` JSON, `action_id` | append-only; the latest per figure wins |
| `review_cursor` | `id PK CHECK(id=1)`, `body` JSON (`Cursor`), `action_id` | updated in the transaction of the action that moves it |
| `threshold_history` | `id PK`, `ts`, `kind` (view, project), `old REAL NULL`, `new REAL`, `reason` (slider, calibration, cli), `action_id` | append-only |
| `jobs` | `n PK` (id `job-{n:06d}`), `kind` (run, ingest_run; later agent, export), `plan` JSON, `status` (queued, running, done, failed, cancelled, interrupted), `progress REAL`, `units_done`, `units_total`, `node NULL`, `doc NULL`, `message NULL`, `created_at`, `started_at NULL`, `finished_at NULL`, `pid NULL`, `log_path`, `exit_code NULL`, `error NULL`, `cancel_requested INT`, `resumed_from NULL` | bookkeeping, mutable |
| `learning_snapshots` | `id TEXT PK` (`001`…), `created_at`, `parent NULL`, `origin` (project, global), `source_first_action`, `source_last_action`, `counts` JSON, `path`, `active INT` | partial unique index `ON (active) WHERE active=1` |

`PRAGMA user_version` = applied migrations. Opening a DB whose `user_version` is greater than `len(MIGRATIONS)` raises `StateError("project.db was written by a newer Manual Labor")`. Each migration runs in one transaction.

### 2.3 Invariants and status derivation
1. `actions.id` and `decisions.seq` are strictly increasing and never reused; no row is updated or deleted (triggers).
2. **Block status is derived, never stored.** `derive_status(block, decisions_for_block, open_flags) -> (BlockStatus, stale_reason | None)`:

| Latest decision for the block (by seq; `skip` ignored; rows whose `raw_sha256` ≠ the current `sha256(raw_text)` are *stale* and ignored) | Derived status | `clean_text` in overlay | `numbers_verified` |
|---|---|---|---|
| none | machine status from `scores.json` | machine | False |
| approve, `shown_text_sha256` == sha of the current display text (`clean_text or raw_text`) | approved | machine | `has_numeric_spec` |
| approve, display text changed since (cleanup/learning re-run) | machine status, why-chip `changed since approval` | machine | False |
| edit | edited | `edited_text` | `has_numeric_spec` |
| flag, flag open | flagged | machine | False |
| flag, flag resolved | machine status (module 10 writes an approve/edit decision when it accepts a proposal) | machine | False |

An approve or edit on a block with an open flag resolves that flag (`resolution="superseded by <action>"`) in the same transaction. Stale decisions (re-parsed raw text) stay in the log and are listed by `labor status` as `orphaned_decisions`.
3. **Human edits go through the faithfulness check** (`review.check_human_edit`): it builds `BlockContext` with `scoring.pipeline.block_contexts` and calls `check_faithfulness_ex(**faith_kwargs(block_with_clean=text, ctx, variants))`. If it passes, the edit is stored with `faith_passed=1`. If it fails and the request lacks `confirm_content_change=true`, the API answers 409 `EditConflict` (violations, numeric changes such as `35 → 36`, diff) and nothing is written. With the confirmation the edit is stored with `faith_passed=0`, `human_edit_diff` = the diff ops, and action kind `edit` with `example.human_edit=true`. Humans may override content (SPEC §7.4), but never silently. Empty text → 422. Figure blocks cannot be edited → 422.
4. `load_review_blocks(paths, store, slug) -> list[Block]` = `scoring.pipeline.load_scored_blocks` plus the overlay of this table, validated via `Block.model_validate`. **The API and module 11 read blocks only through it.** It never feeds back into scoring.
5. Review scope = selected blocks + figure blocks attached to any article (05 §10). Actions on out-of-scope blocks → 422.

### 2.4 Projections (DB is truth; files are what stages read)

| Projection | Written from | Shape |
|---|---|---|
| `selection.json` | `selection` row | `Selection` (`write_json`) |
| `docs/<slug>/group_overrides.json` | `group_overrides` rows of the doc, by seq | `list[GroupOverride]` |
| `docs/<slug>/attach_overrides.json` | `attach_overrides` rows | `list[AttachOverride]` |
| `docs/<slug>/figure_overrides.json` | latest `figure_overrides` row per figure | `list[{seq, figure_id, bbox}]` (F2) |
| `learning/{cleanup,grouping,calibration}.json` + `learning/active.json` | active snapshot (§9) | snapshot files copied verbatim; `active.json` written last |

A projection is written after COMMIT. `reconcile(store, paths)` runs at every `Store.open` in a writer process and rewrites any projection whose bytes differ, so a crash between commit and file write heals on the next open. **First-open import:** if the DB has no rows for a projection and the file exists (a project built before module 7), its contents are imported as `screen=cli, kind=import` actions.

### 2.5 The learning example (`actions.example`, findings "capture everything")
Each review, scope, figure and agent action stores a self-contained example: `{block_id, doc_id, block_type, raw_text, raw_text_by_parser, clean_before, clean_after, signals, score, threshold, has_numeric_spec, action, flag_category, flag_note, faith_passed, diff, learning_provenance, cleanup_entry: {passes, residual, learned_rules, few_shot} | None, figure: {figure_id, from_articles, to_article, rule_before} | None, regroup: {from_topic, from_title, to_topic, to_title, summary} | None, proposal: Proposal | None}`. Unused keys are null. `labor decisions export <project> [--out f]` and `GET /api/decisions/export` stream `ActionRecord` NDJSON sorted by id (canonical JSON, one line each).

## 3. Stage graph and invalidation (`jobs/graph.py`, `jobs/executor.py`)

### 3.1 Nodes (per document; `assemble`/`export` are project-level and only declared until module 11)

| Node | Runs | Output (existence ⇒ not missing) | Fingerprint (F1) | Upstream |
|---|---|---|---|---|
| ingest | `ingest_files` | `document.json` | sha256 of source = `Document.sha256` | — |
| parse | `parse_project(only=…)` | `parse/state.json` complete + `blocks.json` | `parse.pipeline.parse_is_current(paths, slug, cfg) -> bool` | ingest |
| figures | `run_figures` | `figures_report.json` | `figures.pipeline.figures_fingerprint(paths, slug) -> str` | parse |
| score | `run_score` | `scores.json` | `scoring.pipeline.score_fingerprint(paths, slug, cfg) -> str` | figures |
| group | `run_group` | `groups.json` | `grouping.pipeline.group_fingerprint(paths, slug, cfg) -> str` | score |
| clean | `run_clean(rescore=False)` | `clean.json`, `attach.json`, `describe.json` | `cleanup.pipeline.clean_fingerprints(paths, slug, cfg) -> tuple[str,str,str]` | group (+ selection, overrides, learning via fingerprint) |
| score2 | `run_score` | `scores.json` whose fingerprint includes `clean_sha` | same as score | clean |
| assemble | module 11 | module 11 | module 11 | score2 + decisions |
| export | module 11 | zip | module 11 | assemble |

`score` and `score2` share the file. The node is `score2` once `clean.json` exists for the doc; before that `score2` is `missing`.

### 3.2 State rules (`node_state(paths, slug, node, cfg, stages) -> NodeState`), first match wins
1. Output missing → `missing`.
2. `stages.json[node].status == failed` with a seq newer than the last done → `failed` (reason = error).
3. Fingerprint function ≠ the output's recorded fingerprint → `stale` ("inputs changed").
4. Any upstream node's `seq` > this node's `seq` → `stale` ("upstream re-run: <node>"). A missing seq counts as 0, so files made before module 7 are judged by rule 3 only.
5. Any upstream not `fresh` → `stale` ("upstream <node> is <state>").
6. Otherwise `fresh`.

Rule 4 is the literal "a re-run of N marks N+1.. stale". It covers `labor figures --force` (02 §14): the re-run bumps figures' seq, so score/group/clean/score2 go stale even when outputs are byte-identical, and the next run restores the sidecar confidences through scoring's skip path.

`docs/<slug>/stages.json` = `{counter: int, nodes: {node: {seq, status: done|failed, fingerprint: str|None, error: str|None}}}`. It is written atomically by the executor after each (node, doc) finishes, with no timestamps. The counter is per doc, because upstream comparison is per doc.

### 3.3 Executor
- `make_plan(paths, cfg, to: Node = score2, docs: list[str] | None, force: set[Node], allow_reparse: bool) -> Plan`. For each doc (slug order), include every node up to `to` that is not fresh or is forced. Once a node is planned for a doc, plan every downstream node of that doc. `Plan{units: list[(node, slug)], to, force, allow_reparse, provider_mode}`. Execution is **node-major** (parse all planned docs, then figures, …), with docs in slug order within a node: one Docling/OCR runtime per parse call, and score2 finishes doc by doc so the queue fills incrementally.
- **Re-parse guard (01 §14.12):** a planned `parse` for a doc that has ≥1 decision is dropped with an error line unless `allow_reparse` (CLI `--allow-reparse`). It fails closed: when `project.db` cannot be read the parse is refused too (section 14.4).
- `execute(paths, plan, *, emit, providers: Callable[[], ProviderSet], cancelled: Callable[[], bool]) -> ExecResult{failed: dict[node, list[slug]]}`. For each node it calls the stage function with `only=slug` when one doc is planned, else `only=None` (fresh docs skip cheaply). `force=True` only for forced nodes. It wraps `emit` to add `"node"` and to tee to the job log, then updates `stages.json` for each doc from the stage's return value (failed slugs → `failed`). A failed doc's downstream units are skipped with `status: blocked`.
- Before the first node it deletes stray `*.json.tmp` under `docs/`, `figures/`, `learning/` (left by a SIGKILL during `write_text_atomic`). It must hold the worker lock to do this. Writers outside the worker lock never use `.tmp`; see section 14.1.
- Every stage gets `providers=provider_set_factory(paths, cfg, mode, sink=TeeSink(JsonlSink(root/"llm_calls.jsonl"), heartbeat))`. The heartbeat counts LLM calls for progress and is where fault point `llm.after_calls:<n>` fires.
- **"Never loses more than the current block"**, per node: parse resumes at page granularity (`parse/.partial`, module 1). Figures, score, group and clean write one atomic file per doc. Everything inside a doc is deterministic and fast (<10 s per 3,000 blocks) except LLM calls, and **every LLM call is cached as it completes** (`.llm_cache`), so a kill loses at most the in-flight call; re-running the doc replays the cache. A killed run resumes at the first (node, doc) whose state is not fresh.
- **F3 (scoring):** `_write_outputs` appends `score_history.jsonl` *before* `scores.json`. The appender first truncates a trailing partial line, and the reader ignores one. The history only appends a line when the value differs from the block's last line, so a replay after a kill appends nothing, and resume is byte-identical.

### 3.4 CLI (A)
- `labor status <project> [--json]`: a table of docs × nodes (`fresh`/`stale`/`missing`/`failed`, reason on `-v`), plus per doc `learning: group=<prov> clean=<prov>`, `orphaned_decisions`, running jobs. Read-only; no lock.
- `labor run <project> [--to NODE] [--doc SLUG] [--force NODE …] [--allow-reparse] [--mock]`: takes the project lock and the worker lock, records a `jobs` row (kind run), executes, prints the progress lines. Exit codes: 0 ok, 1 any doc failed, 3 lock held (prints the owner pid and command).
- Existing `labor parse|figures|score|group|clean` (F6): same flags and output, but they call `executor.run_node(paths, node, only, force, …)` so `stages.json` stays true. `labor clean` keeps `--no-score` (without it, it runs clean then score2).

## 4. Background jobs (`jobs/runner.py`, `jobs/worker.py`)

### 4.1 Choice: one subprocess per job, supervised by a thread in the serve process
A thread in the API process would share the event loop's GIL with Docling/torch, would die with the API, and cannot host the spawn pool cleanly. A subprocess (`[sys.executable, "-m", "manuallabor.jobs.worker", root, job_id]`, `start_new_session=True`, stdout/stderr → `logs/jobs/<id>.stderr`) survives an API SIGKILL, has a `__main__` guard for the spawn pool, and can be cancelled as a process group. Default **concurrency 1** (`MANUALLABOR_JOB_CONCURRENCY`, max 2; a second job starts only if its doc set is disjoint from the running one and neither plans `parse`).

### 4.2 Protocol
- **Worker** (no DB access): takes the worker lock, reads `logs/jobs/<id>.plan.json`, runs `execute`, and writes NDJSON to `logs/jobs/<id>.jsonl`: `{"event":"job_start","units":N}`, every stage progress line with `node` added, `{"event":"unit_done","node","doc","status"}`, `{"event":"heartbeat","llm_calls"}` (every 5 s and every LLM call, at most 2/s), `{"event":"job_end","status":"done|failed|cancelled","failed":{…}}`. It flushes per line. SIGTERM sets `cancelled()` and raises `Cancelled` at the next unit or LLM call. `finally` closes the OCR pool and writes `job_end cancelled`.
- **Supervisor** (`JobRunner`, daemon thread, 0.5 s tick, the single DB writer): starts the oldest queued job (status running, pid, started_at) and tails the log by byte offset. From `unit_done` it sets `units_done`, `progress = units_done/units_total` (monotonic, ≤ 1), `node`, `doc`, and `message` (last stage line, e.g. `clean clean-pdf: 37 LLM calls`). On process exit it finalizes from `job_end` (done/failed/cancelled); with no `job_end` the job is `interrupted`.
- **Cancel:** `cancel(id)` sets `cancel_requested`, sends `killpg(SIGTERM)`, and after 5 s `killpg(SIGKILL)`; status becomes cancelled. A queued job is cancelled immediately.
- **Startup reconcile** (`JobRunner.start()`): a `running` row whose pid is alive and whose log mtime is < 30 s old is *adopted* (tailed until `job_end`). Otherwise it is marked `interrupted`, and when `resume=True` (default) a new job with the same plan and `resumed_from=<id>` is enqueued. Because the stage graph is idempotent, resuming means re-planning.
- **Per-doc readiness for Verify:** a doc is `ready` when its score2 output exists and loads (fresh or stale; `ProjectData.scored`: clean.json plus a scores.json of the current `SCORING_ALGO_VERSION` that matches blocks.json), `pending` otherwise (`waiting_for` = its first non-fresh node). A score file from an older algo version is `pending`, never an error (design 03 section 2.10a). The queue lists ready docs only; stale ready docs are still listed with `stale=true`. Review is never blocked by a running job.
- `JobRunner` API (used by B): `enqueue(plan_in: RunPlanIn, kind="run", files: list[Path] = []) -> JobInfo`, `get(id) -> JobInfo`, `list(status: set[str] | None) -> list[JobInfo]`, `cancel(id) -> JobInfo`, `log(id, after_line: int, limit=500) -> list[dict]`, `start()`, `stop()`. `ingest_run` jobs ingest `files` (saved under `.uploads/<sha>/`) and then plan `to=group`.

### 4.3 Provider modes (`jobs/providers.py`)
`ProviderMode = Literal["config","mock"]`. `provider_set_factory(paths, cfg, mode, sink)` returns a memoized `Callable[[], ProviderSet]` that calls `build_provider_set(eff_cfg, cache_dir=root/".llm_cache", sink=sink, factories=F)`, where `F = DEFAULT_FACTORIES` for config and `MOCK_ONLY_FACTORIES = {"mock": _mock_factory}` for mock. In mock mode `eff_cfg = mockify(cfg)`, and `mockify` is also written into the project's `project.json` by `labor check` (§6). `mockify` maps every non-None ref to `ModelRef(provider="mock", model=ref.model if ref.provider == "mock" else f"mock-{task}")` and the verifier to `mock-verifier`, so it never equals cleanup. With only the mock factory registered, a non-mock ref anywhere is a `ProviderError`, never a network call. `labor serve --mock` and `labor run --mock` run every job in mock mode (used by module 9's Playwright tests).

### 4.4 Locks (`state/lock.py`)
`ProjectLock(path).acquire(nonblocking=True)` uses `fcntl.flock(LOCK_EX|LOCK_NB)` and writes `{pid, cmd, started_at}` into the file. Holders: `serve` holds the project lock; `run`, `check` (on its temp copy) and `learning` take the project lock; `run` and the worker also take the worker lock. An orphaned worker therefore still blocks a concurrent `labor run`. The kernel releases locks when a process dies. macOS and Linux only (Windows is out of scope for v1).

## 5. API (FastAPI, prefix `/api`, B)

### 5.1 Conventions
All endpoints are plain `def` (threadpool). **No endpoint makes an LLM call or imports litellm/docling.** Model work is only ever enqueued as a job. Page renders use PyMuPDF (light). Mutations take `request_id` (UUID, idempotent via `actions.request_id`: a replay returns the stored outcome). Errors are `{"detail": str, "code": str}`; 409 for edit conflicts and locks, 422 for validation/scope, 501 for stubs. `create_app(..., generate_unique_id_function=lambda r: r.name, separate_input_output_schemas=False)` keeps operationIds and component names stable. Responses use `response_model` everywhere.

### 5.2 Shared models (`state/models.py`, A writes on day 0; contract models imported from `manuallabor.contracts`)

| Model | Fields |
|---|---|
| `ActionKind` (StrEnum) | select, deselect, select_group, deselect_group, set_view, set_split, regroup_move, regroup_rename, approve, edit, flag, skip, back, resolve_flag, attach, detach, crop_bbox, cursor, threshold_view, threshold_project, config_models, learning_toggle, learning_snapshot, learning_activate, learning_reset, learning_disable_item, learning_publish, proposal_accept, proposal_edit, proposal_reject, export_override, import |
| `ActionRecord` | id, ts, screen, kind, target_id, doc_id, payload: dict, example: dict \| None, before_ref, after_ref, learning_provenance, request_id |
| `DecisionRecord` | decision: `Decision`, action_id, doc_id, raw_sha256, shown_text_sha256, faith_passed: bool \| None, human_edit_diff: list[`DiffOp`] \| None, numbers_verified: bool, learning_provenance: str, source: human \| agent |
| `WhyItem` | kind: signal \| rule \| stale \| learning, name, value: float \| None, critical: bool, detail: str \| None. Order: critical first, then value ascending, then name. |
| `QueueSort` | worst_first, by_page, figures_only |
| `Cursor` | sort: QueueSort = worst_first, view_threshold: Unit \| None = None, doc_filter: DocSlug \| None, current_block_id: BlockId \| None, trail: list[BlockId] (≤ 50, newest last) |
| `QueueItem` | block_id, doc_id, page, type, confidence, status, has_numeric_spec, reasons: list[str] (≤ 3, from the why-list), stale_doc: bool |
| `ReviewCounts` | pending, auto_approved, approved, edited, flagged_open, skipped, in_scope |
| `DocReadiness` | doc_id, state: ready \| pending, stale: bool, waiting_for: str \| None |
| `QueuePage` | items: list[QueueItem], total, counts, docs: list[DocReadiness], cursor |
| `PageRef` | doc_id, page, width, height, render_url: str \| None (None for DOCX), source_url |
| `LearningUse` | provenance, learned_rules: list[str], few_shot: list[str] |
| `FigureRailItem` | figure_id, block_id, record: `FigureRecord`, image_url, attachment: {article_id, rule, confidence, anchor_block_id} \| None, status: BlockStatus |
| `BlockDetail` | block: `Block` (overlaid), article_ids, page: PageRef, why: list[WhyItem], parser_texts: dict[str,str], learning: LearningUse, history: list[DecisionRecord], figures: list[FigureRailItem], flags: list[`Flag`] |
| `ReviewActionIn` | kind: approve \| edit \| flag \| skip \| back, block_id: BlockId \| None (None only for back), text: str \| None, confirm_content_change: bool = False, flag: {category: FlagCategory, note: str \| None, target_id: TargetId \| None} \| None, request_id |
| `ReviewActionOut` | action_id, decision: DecisionRecord \| None, flag: Flag \| None, block_status, next: QueueItem \| None, cursor, counts |
| `EditConflict` | violations: list[`FaithfulnessViolation`], numeric_changes: list[str], diff: list[DiffOp] |
| `SelectionOp` | op: select \| deselect \| select_group \| deselect_group \| set_view \| set_split, block_ids, group_id, doc_id, subtree: bool, view, split, request_id |
| `SelectionOut` | selection: Selection, dropped: list[BlockId], coverage: list[`CoverageReport`], summary: `ScopeSummary` |
| `RegroupIn` | doc_id, kind: move \| rename, block_id, to_topic_slug, topic_slug, title, request_id |
| `NodeState` / `DocStatus` / `ProjectStatus` | {node, state, reason} / {doc_id, kind, pages, nodes, learning: {group, clean}, orphaned_decisions} / {project, docs, unregistered_sources, jobs_running: list[JobInfo]} |
| `RunPlanIn` | to: str = "score2", docs: list[DocSlug] \| None, force: list[str] = [], allow_reparse: bool = False |
| `JobInfo` | id, kind, plan: dict, status, progress: Unit, units_done, units_total, node, doc, step_done, step_total, step_unit, files (§17), message, created_at, started_at, finished_at, pid, error, resumed_from |
| `SnapshotInfo` / `LearningState` | {id, created_at, parent, origin, source_first_action, source_last_action, counts, active} / {enabled, use_global, contribute_global, active: str \| None, provenance: str, snapshots} |
| `CalibrationReport` (module 10 fills) | buckets: list[{lo, hi, n, edited, edit_rate: Unit \| None}], target_edit_rate, suggested_threshold: Unit \| None, ab: {baseline_n, baseline_edit_rate, learned_n, learned_edit_rate, verdict: learned_better \| learned_worse \| insufficient} \| None |
| `ExportStatus` | unlocked: bool, open_flags: int, overrides: list[`Override`] |

### 5.3 Routes

| Method + path | Body → response | Calls (A) |
|---|---|---|
| GET `/api/project` | → `{name, root, config: ProjectConfig, learning: LearningState, mock: bool, tool_version}` | `paths.load_config`, `learning.state()` |
| GET `/api/status` | → `ProjectStatus` | `graph.project_status(paths, runner)` |
| GET / POST `/api/probe` | → `{probe: ProbeResult, suggestions: SuggestionTable}` (GET 404 if no `probe.json`; POST runs `run_probe` in the threadpool and writes `probe.json`) | `providers.probe` |
| POST `/api/config/apply-tier` | `{tier, force, request_id}` → `{models: TaskModels, stale: list[NodeState]}` | `probe.apply_tier` + action `config_models` |
| PUT `/api/config/threshold` | `{value, reason, request_id}` → `{threshold, job: JobInfo}` (project threshold; enqueues `run to=score2`, which restates statuses) | `scope.set_project_threshold` |
| GET `/api/sources` | → `list[{slug, filename, kind, pages, ocr_warning: str \| None, nodes}]` | `graph.project_status` |
| POST `/api/sources` | multipart files → 202 `JobInfo` (`ingest_run`) | `runner.enqueue(kind="ingest_run", files=…)` |
| GET `/api/docs/{slug}/source` | → original file (pdf.js) | — |
| GET `/api/docs/{slug}/pages/{page}.png?dpi=150` | → PNG (cached in `pages_view/`; 404 for DOCX) | `review.render_page` |
| GET `/api/docs/{slug}/pages/{page}/blocks` | → `list[{block_id, bbox, type, status}]` (click-to-jump) | `review.page_blocks` |
| GET `/api/scope/groups?doc=` | → `list[{doc_id, groups: GroupsFile, coverage: CoverageReport}]` | `scope.groups` |
| GET / PUT `/api/scope/selection` | `SelectionOp` → `SelectionOut` | `scope.get` / `scope.apply` |
| GET `/api/scope/summary` | → `ScopeSummary` | `scope.summary` |
| POST `/api/scope/regroup` | `RegroupIn` → 202 `{override: GroupOverride, job: JobInfo}` (run `to=group`, that doc) | `scope.regroup` |
| GET `/api/scope/models` | → `{models: TaskModels, probe: ProbeResult \| None, suggestions: SuggestionTable \| None}` | `scope.models` |
| POST `/api/scope/confirm` | `{request_id}` → 202 `JobInfo` (run `to=score2`) | `runner.enqueue` |
| GET `/api/verify/queue?sort&view_threshold&doc&limit=200&offset=0` | → `QueuePage` (query params override the cursor for this read only) | `review.queue` |
| GET / PUT `/api/verify/cursor` | `{sort, view_threshold, doc_filter, current_block_id, request_id}` → `Cursor` (a changed `view_threshold` also writes `threshold_history kind=view`) | `review.cursor` / `review.set_cursor` |
| GET `/api/verify/blocks/{block_id}` | → `BlockDetail` | `review.detail` |
| POST `/api/verify/actions` | `ReviewActionIn` → `ReviewActionOut` (409 `EditConflict`) | `review.act` |
| GET `/api/flags?status=open` · POST `/api/flags/{id}/resolve` | `{resolution, request_id}` → `Flag` | `review.flags` / `review.resolve_flag` |
| GET `/api/articles/{article_id}/figures` | → `list[FigureRailItem]` | `figures.rail` |
| GET `/api/figures/{fid}/image` | → PNG/SVG file | `figures.image_path` |
| POST `/api/figures/{fid}/attach` · `/detach` | `{article_id, anchor_block_id?, request_id}` → 202 `{override: AttachOverride, job}` (run `to=score2` for the doc) | `figures.attach` / `figures.detach` |
| PUT `/api/figures/{fid}/bbox` | `{bbox, request_id}` → 202 `{job}` (re-extract via F2, run `to=score2`) | `figures.set_bbox` |
| GET `/api/decisions/export` | → NDJSON stream of `ActionRecord` | `store.iter_actions()` |
| GET / PUT `/api/learning` | `{enabled?, use_global?, contribute_global?, request_id}` → `LearningState` (+ `stale` nodes; never auto-runs) | `learning.state` / `learning.set_flags` |
| POST `/api/learning/snapshots` · `/activate/{id}` · `/reset` · `/items/{item_id}/disable` · `/publish/{id}` | → `SnapshotInfo` / `LearningState` | §9 |
| POST `/api/jobs` | `RunPlanIn` → 202 `JobInfo` · GET `/api/jobs?status` → list · GET `/api/jobs/{id}` · GET `/api/jobs/{id}/log?after=` → `list[dict]` · POST `/api/jobs/{id}/cancel` | `runner.*` |
| POST `/api/agent/run` · GET `/api/agent/proposals` · POST `/api/agent/proposals/{id}/{accept\|edit\|reject}` · POST `/api/agent/accept-all-passing` · GET `/api/calibration` · POST `/api/calibration/apply` | **501**, `response_model` = `JobInfo` / `list[Proposal]` / `Proposal` / `list[Proposal]` / `CalibrationReport` / `{threshold}` | module 10 |
| GET `/api/export/status` | → `ExportStatus` (**real**: open flags from DB) | `store.open_flag_count` |
| POST `/api/export` · POST `/api/export/override` | **501** (`JobInfo` / `ExportStatus`) | module 11 |

**Queue and `next` algorithm (`review.queue`, `review.act`).** `pending` = in-scope blocks of ready docs whose derived status is `queued`, or `auto_approved` with `confidence < view_threshold` (when set). An auto-approved block shown this way can be approved or edited; nothing is ever re-approved by the slider. `figures_only` restricts to `type == figure`. Sort keys: worst_first = `(conf if not None else -1.0, block_sort_key)`; by_page and figures_only = `block_sort_key` / worst_first. After an action on X: `next` = the first pending item whose key > key(X), otherwise `pending[0]` (wrap, which is how skipped blocks come back), otherwise None. The cursor sets `current = next` and pushes X to `trail`. `back` pops `trail` into `current` and records no decision (empty trail → current unchanged). `skip` writes a `skip` decision and does not change status. Every action, `back` and cursor changes included, is an `actions` row (SPEC "autosave on every action"). Reopening returns the stored cursor verbatim.

### 5.4 OpenAPI → TypeScript (B)
`labor openapi export [--out frontend/src/api/openapi.json] [--check]` dumps `json.dumps(app.openapi(), sort_keys=True, indent=2, ensure_ascii=False)+"\n"`, built from `create_app` with a dummy context (no project needed), so it is byte-stable. `--check` exits 1 on drift. Frontend devDeps add `openapi-typescript@7` and dep `openapi-fetch@0.13` (pinned); scripts `"gen-api": "openapi-typescript src/api/openapi.json -o src/api/schema.d.ts"` and `"check-api-fresh": "npm run gen-api && git diff --exit-code -- src/api/schema.d.ts"`. `src/api/client.ts` = `createClient<paths>({baseUrl: ""})` (Vite proxies `/api` to 127.0.0.1:8765). CI: the python job adds `uv run labor openapi export --check`; the frontend job adds `npm run check-api-fresh`. Module 8+ take API types from `components["schemas"]`; `src/types/generated.ts` stays for contract-only types.

## 6. `labor check <project> [--live] [--keep]` (`check.py`, A)

1. Copy `<project>` to `mkdtemp(prefix="labor-check-")`, excluding `project.db*`, `logs/`, `.labor*.lock`, `.uploads/` (00 §10.12). The source tree must be untouched (tested).
2. **Mock (default):** write `mockify(cfg)` into the copy's `project.json`, so parse metadata through `ingest.metadata_provider` is mock too, and run every node with `provider_mode="mock"` (`MOCK_ONLY_FACTORIES`). **Live:** if the config has any `mock` ref, apply the probe's `small` tier to the copy (`probe.apply_tier`). Preflight: `run_probe`; if Ollama is unreachable or a required model is absent, print `SKIP live: <reason>` plus the `ollama pull …` commands and **exit 0** without running anything (exit 4 instead when `MANUALLABOR_LIVE_REQUIRED=1`).
3. Ingest every `sources/*` not yet registered, then `execute(make_plan(to="group"))`. Auto-select all: write `default_selection` through `ScopeService.apply(replace)` as a `cli` action, which also exercises the store. Then `execute(make_plan(to="score2"))`.
4. Run the checks below, print a table `check | status | detail | ms`, exit 1 if any FAIL, delete the temp dir on success (kept with its path printed on failure or with `--keep`).

| # | Check (now, module 7) |
|---|---|
| K1 | every node `fresh` to score2 for every doc (`project_status`) |
| K2 | artifacts validate: `Document`, `list[Block]`, `FigureReport`, every sidecar as `FigureRecord` and against `schemas/FigureRecord.json` (jsonschema), file targets exist, `ScoreFile` covers every block once, `GroupsFile` + `check_partition` ok, `CleanFile` entries = the selected cleanable blocks, `AttachFile`, `DescribeFile` |
| K3 | **zero faithfulness violations on auto-approved blocks** (SPEC §11.1): every `auto_approved` block with `clean_text` has `faithfulness.passed` |
| K4 | block accounting: every block id from `blocks.json` is in exactly one topic or in `unassigned` (both views) |
| K5 | every figure in `attach.json` has a sidecar and an image; caption refs resolved (`unresolved_refs` reported, not failed) |
| K6 | idempotent: a second `execute(to=score2)` emits only `skip` lines, and the sha256 of every file under `docs/` and `figures/` is unchanged |
| K7 | mock mode only: every `llm_calls.jsonl` row has `provider == "mock"` |
| K8 | state: `project.db` integrity_check ok, `actions` ids monotonic, `selection.json` == DB selection |
| K9 | learning provenance = `baseline` in `groups.json` and `clean.json` |

Added in module 11 (as K10–K13): assemble + export run; the zip validates against `schemas/Manifest.json` and the `Manifest` validators; every `FIG-` reference in every article resolves to a file and a sidecar; README present; manifest accounting equals K4. Live mode runs the same checks except K7.

## 7. `labor serve <project> [--host 127.0.0.1] [--port 8765] [--dev] [--mock] [--no-resume]` (`serve.py`, B)
Startup order: acquire the project lock (held → exit 3 with the owner) → `Store.open` (migrate + `reconcile`) → print the `labor status` table → `JobRunner(paths, store, mode, resume).start()` → `uvicorn.run(create_app(ctx), host, port, workers=1, reload=False, log_level="warning")`. It never waits on a job or an LLM call. Static: unless `--dev`, mount the first existing of `$MANUALLABOR_FRONTEND_DIST`, `manuallabor/_frontend/` (packaged wheel, later), `<repo>/frontend/dist`; serve `assets/` and fall back to `index.html` for any non-`/api` GET. If none exists, `/` returns a short HTML page saying "frontend not built: cd frontend && npm run build". `--dev` serves `/api` only (Vite on 5173 proxies). Unknown `/api/*` → JSON 404. SIGINT/SIGTERM: `runner.stop()` (it does not kill a running worker; that job is adopted next start), `store.close()`, release the lock.

## 8. Resumability tests (the gate) — `tests/jobs/test_resume.py`, marker `slow`
Fixture: a tmp project with `clean.pdf` + `scanned.pdf` (copied from `tests/fixtures/`) and project-a's mock `project.json`. A session fixture builds one **uninterrupted reference** (`labor run --to score2`) and snapshots `{relpath: sha256}` of `docs/**`, `figures/**`, `selection.json`, `learning/**`. The comparison excludes `logs/`, `llm_calls.jsonl`, `.llm_cache/` (content-addressed: assert reference keys ⊆ resumed keys), `docs/*/stages.json`, `project.db*`, `parse/.partial/`. Runs are sequential (16 GB; one Docling process at a time).

| Case | Kill | Then | Assert |
|---|---|---|---|
| R1 random | `labor run` subprocess (`start_new_session=True`); poll its stdout until the first `"node":"score"` (seed A) or `"node":"clean"` (seed B) line, sleep `random.Random(seed).uniform(0, 0.3)` s, `killpg(SIGKILL)` | `labor run` again | exit 0; `labor status --json` all fresh; hash map == reference; no `*.tmp`; no orphan OCR pool processes (`pgrep -g`) |
| R2 deterministic | `MANUALLABOR_FAULT=node.after:score:clean` (SIGKILL after the unit, before `stages.json`) · `llm.after_calls:3` during clean (`cleanup.llm="always"` so mock calls happen) · `node.after:clean:scanned` | rerun | same as R1, plus `score_history.jsonl` byte-equal (F3) |
| R3 decision write | subprocess applies 5 actions, then `MANUALLABOR_FAULT=action.after_insert` on the 6th (SIGKILL inside the open transaction) | `Store.open` | `max(actions.id)` = 5th, no 6th decision, `integrity_check == ok`, cursor == the 5th action's `ReviewActionOut.cursor` |
| R4 projection | `action.after_commit` on a selection op | `Store.open` | row present; `selection.json` rewritten == DB |
| R5 serve, API only | `labor serve --mock` on a free port; POST `/api/jobs`; when the job reaches clean, SIGKILL only the serve pid | start serve again | the job is adopted and ends `done`; outputs == reference |
| R6 serve + worker | as R5, but `killpg` both serve and the worker group | start serve | old job `interrupted`; a new job with `resumed_from` ends `done`; outputs == reference |

`faults.fault(point)`: if `os.environ.get("MANUALLABOR_FAULT") == point`, `os.kill(os.getpid(), SIGKILL)`. Points: `action.after_insert`, `action.after_commit`, `node.after:<node>:<slug>`, `llm.after_calls:<n>`. They are compiled in permanently and are no-ops without the env var.

## 9. Learning layer (mandatory parts; A)
- **Config (F5):** `LearningConfig{enabled: bool = False, use_global: bool = False, contribute_global: bool = False}`. Regenerate schemas and TS types.
- **Layout:** `<project>/learning/snapshots/NNN/{cleanup.json, grouping.json, calibration.json?, manifest.json}`, immutable once written (built in `snapshots/.tmp-NNN/`, then `os.rename`). `manifest.json` = `{id, created_at, parent, origin, source_action_range: [first, last], derivers: {cleanup: "v1", grouping: "v1"}, counts}`. The `snapshot` field inside `cleanup.json`/`grouping.json` is the provenance string `snapshot:NNN` (or `global:NNN`).
- **Active pointer:** the DB row `active=1` is the truth. The projection copies the active snapshot's files to `learning/cleanup.json`, `learning/grouping.json`, `learning/calibration.json`, then writes `learning/active.json` `{id, provenance}` last. With no active snapshot these files are absent. If `use_global` is set and there is no project snapshot, the global active snapshot is materialized instead (provenance `global:NNN`). Project beats global; they are never merged.
- **Provenance:** `GroupsFile.learning_snapshot` and `CleanFile.learning_snapshot` already record `baseline | snapshot:NNN | global:NNN`, and both are in their fingerprints, so a toggle or activation makes group/clean `stale`. Every decision row stores the provenance of the output the human saw (from `clean.json`, or `groups.json` for regroups), and `labor status` shows it per doc. Module 11's manifest states the set.
- **Derivers v1 (deterministic, pure over action rows, registry `DERIVERS` so module 10 adds rules/calibration):** cleanup `examples` = for each block, the latest human decision that is an edit with `faith_passed` and text ≠ raw, or an approve whose shown clean text ≠ raw, as `FewShotExample{id: f"ex-{seq}", block_type, ocr, residual (from the clean entry), raw, clean}`, newest 200; `rules = []` (module 10 mines `hyphen_*`/`bullet_glyph`). grouping `examples` = `RegroupExample` from `regroup_move/rename` actions; `do_not_merge = []`. Same rows → byte-identical files (no timestamps outside `manifest.json`).
- **Operations** (`LearningService`; CLI `labor learning list|snapshot|activate <id>|rollback <id>|reset|disable <item_id>|publish <id>`): `snapshot()` derives from all actions and does not activate. `activate(id)` / `rollback(id)` (same op) sets active and re-projects. `reset()` clears active and deletes the materialized files, **keeping snapshots and all decisions** so learning can be re-derived. `disable_item(item_id)` creates a child snapshot of the active one with that rule/example removed and activates it (snapshots stay immutable; this is the UI chip's per-rule disable). `publish(id)` (requires `contribute_global`) copies the snapshot to `$MANUALLABOR_HOME/learning/snapshots/NNN` (default `~/.manuallabor`) with `origin=project:<name>`. Every operation is an action row. **None writes `models`, `threshold`, any other config key, or code**; only `PUT /api/learning` changes `learning.*`.
- **Guardrail hook (module 10):** `Store.decisions_by_provenance() -> dict[str, list[DecisionRecord]]` and `CalibrationReport.ab`. Module 10 computes learned-vs-baseline edit rates on the same project and, when worse, the UI offers `reset`.

## 10. Determinism, forced changes, tests

### 10.1 Changes forced in modules 1–6 (made in this module; regenerate schemas/TS where noted)

| # | Where | Change | Why |
|---|---|---|---|
| F1 | `parse/pipeline`, `figures/pipeline`, `scoring/pipeline`, `grouping/pipeline`, `cleanup/pipeline` | expose `parse_is_current`, `figures_fingerprint`, `score_fingerprint`, `group_fingerprint`, `clean_fingerprints` as pure functions. The stages call them, with no behaviour change. | stage graph freshness (§3.2) without running stages |
| F2 | `figures/pipeline._process_doc` | read `figure_overrides.json`: an override bbox replaces the region before the method decision (`reason="human_bbox"`, ID unchanged); the overrides' sha goes into the figures fingerprint | SPEC §7.2 crop adjust → re-extract |
| F3 | `scoring/pipeline._write_outputs`, `_append_history` | history before `scores.json`; repair/ignore a trailing partial line | byte-identical resume |
| F4 | `project.py` | paths of §1 | — |
| F5 | `contracts/config.LearningConfig` | `use_global`, `contribute_global` (schemas + TS regenerated) | global opt-in |
| F6 | `cli.py` | stage commands go through `executor.run_node`; new commands; `cli_serve.register` hook | `stages.json` truth |
| D | `00-contracts.md` §6.2 | LLM log path is `<project>/llm_calls.jsonl` | doc drift |

### 10.2 Determinism
DB writes use the injected clock and canonical JSON; snapshot derivation is pure; the queue order is a total order (ties by `block_sort_key`); projections use `write_json`; `stages.json` has no timestamps; the OpenAPI dump uses sorted keys. Nothing in `docs/` or `figures/` depends on wall time or job ids.

### 10.3 Test list (`tests/state/`, `tests/jobs/`, `tests/api/`, `tests/check/`; a session fixture builds the mock-scored project-a copy once and caches it under the pytest tmp dir)

| # | Test | Assertion |
|---|---|---|
| S1 | migrations | fresh → `user_version == len(MIGRATIONS)`, all tables; a DB built with `MIGRATIONS[:1]` plus rows migrates and keeps the rows; `user_version` too high → `StateError`; double open idempotent |
| S2 | append-only + monotonic | UPDATE/DELETE on `actions`/`decisions` raise; 200 mixed actions → ids strictly increasing; flags only open→resolved |
| S3 | idempotency | same `request_id` twice → one row, equal responses |
| S4 | status derivation | every row of the §2.3 table (incl. stale raw sha, changed-since-approval, approve resolves open flag) |
| S5 | human edit | lossless edit → `faith_passed`; `35→36` without confirm → `EditConflict` (numeric_changes `["35 → 36"]`), no row; with confirm → stored, diff has the replace op, overlay `clean_text` = text, status edited, `Block` validates; figure edit → 422 |
| S6 | numeric approve | approve on a `has_numeric_spec` block → `numbers_verified` in the overlay and `numbers_verified_blocks()`; non-numeric / skip → False |
| S7 | queue | worst_first == `build_queue` ∩ scope; by_page; figures_only; `view_threshold=1.0` adds undecided auto-approved; `0.0` still lists every machine-queued block; threshold changes create no decisions and change no derived status |
| S8 | 20-action sequence | fixed key script (A A E F J K A E(lossless) A J …) via `ReviewService.act` → each `next` equals the precomputed expectation; back pops; skip wraps; reopen → identical cursor |
| S9 | projections | each projection equals its DB rows; deleting a file then `Store.open` recreates it byte-identical; legacy `selection.json`/overrides imported once as `import` actions |
| S10 | lock | second writer → exit 3 naming the pid; lock free after SIGKILL of the holder; orphan worker lock blocks `labor run` |
| G1 | node states | after a full run all fresh; `labor figures --force` → score, group, clean, score2 stale; selection change → clean, score2 only; group override → group..score2; project threshold → score; learning toggle → group, clean; delete `groups.json` → missing |
| G2 | F1 equivalence | each `*_fingerprint` equals the fingerprint in its output after a run; parse `parse_is_current` True after a run, False after a config `ocr_dpi` change |
| G3 | idempotent run | second `labor run` → only `skip` lines, all bytes unchanged |
| G4 | planning | node-major, slug order; a stale parse schedules all downstream for that doc only; `--to group`, `--doc`; re-parse with decisions refused without `--allow-reparse` |
| G5 | **gate** R1–R4 (§8) | as specified |
| G6 | job runner | tiny mock project: queued→running→done, progress monotonic to 1.0, log has `job_start/unit_done/job_end`; cancel during clean → cancelled, no process left in the group; rerun → outputs == reference |
| G7 | **gate** R5–R6 (§8) | adopt and auto-resume |
| G8 | readiness | doc A run to score2, doc B to group → queue lists only A's items, `docs` = [A ready, B pending waiting_for clean] |
| G9 | mock forcing | `provider_set_factory(mode="mock")` on an all-ollama config → every provider is a `MockProvider`; `llm_calls.jsonl` all mock; under the 06 T4 offline guard (subprocess) zero connection attempts |
| L1 | toggle off | with an active snapshot and `enabled=false` → provenance `baseline`, bytes equal a project with no `learning/` |
| L2 | snapshot derive | deterministic bytes; only faith-passing edits with clean ≠ raw; range correct; second snapshot `002`, parent `001`; dirs immutable |
| L3 | activate/rollback/reset | materialized files == snapshot files; after rerun `clean.json.learning_snapshot == "snapshot:002"`; reset → files gone, rerun == L1 baseline bytes; rollback 001 → `snapshot:001` |
| L4 | config untouched | `project.json` bytes unchanged by snapshot/activate/rollback/reset/disable/publish |
| L5 | global | `MANUALLABOR_HOME=tmp`; publish refused without `contribute_global`; `use_global` with no project snapshot → `global:001`; project active beats global |
| L6 | disable item | child snapshot without the item, active; parent unchanged |
| L7 | A/B hook | `decisions_by_provenance` groups by the recorded provenance |
| A1 | route coverage | parametrized table of every `app.routes` `/api` route (asserted complete): status code + body validates against the `response_model` (`httpx.AsyncClient` + `ASGITransport`) |
| A2 | project/status/probe | `/api/status` == `project_status`; `/api/probe` 404, then 200 after writing a canned `ProbeResult` |
| A3 | scope | `select_group subtree`; `set_view` leaves `block_ids` byte-identical; coverage sums equal; summary review_load; persists across a new app instance |
| A4 | keyboard flow | S8's 20-action script over HTTP; a new app instance → GET cursor identical |
| A5 | edit 409 | over HTTP, then confirm → 200 |
| A6 | threshold | PUT cursor `view_threshold` 1.0 → queue grows; 0.0 → machine-queued still present; no decisions; `threshold_history` rows |
| A7 | figures rail | rail items for an article; attach/detach → 202, override row, projection file; bbox → 202 + `figure_overrides.json` |
| A8 | jobs | with a `FakeRunner` (Protocol §11.2): POST 202, GET, log, cancel |
| A9 | learning routes | round trip of toggle/snapshot/activate/reset |
| A10 | stubs | every module 10/11 mutation → 501 `{detail, code:"not_implemented"}`; `/api/export/status` real counts |
| A11 | decisions export | NDJSON line count == actions, sorted ids, canonical JSON |
| A12 | OpenAPI | two exports byte-identical; `--check` clean on the committed file; operationIds unique == route names; no `-Input`/`-Output` schema names |
| A13 | static | fake dist: `/` and `/verify` → index.html, `/assets/x.js` served, `/api/nope` → JSON 404; `--dev` → `/` 404; no dist → "frontend not built" page |
| A14 | non-blocking | while a `FakeRunner` job "runs" (sleeps), `/api/verify/queue` answers < 200 ms; after the API suite `litellm`, `docling`, `torch` ∉ `sys.modules` |
| A15 | frontend | `npm run check-api-fresh`; `npm run typecheck` with a test file that calls `client.GET("/api/verify/queue")` |
| C1 | **gate** `labor check tests/fixtures/project-a` | exit 0, K1–K9 PASS, source tree hash unchanged, temp dir removed |
| C2 | check fails loudly | `run_check(extra_checks=[failing])` → exit 1, row FAIL, temp dir kept and printed; an unparseable source → exit 1 |
| C3 | `--live` skip | `OLLAMA_HOST=127.0.0.1:<closed port>` → exit 0, `SKIP live:` with the reason, no stage ran; `MANUALLABOR_LIVE_REQUIRED=1` → exit 4 |
| C4 | `--live` (marker `live`) | passes on this machine with the small tier |
| C5 | mock forcing via check | a copy of project-a with ollama refs → passes fully mocked (K7) |
| V1 | serve | subprocess: `/api/status` 200 within 10 s; a second serve → exit 3; SIGTERM → lock released, WAL checkpointed (`project.db-wal` empty or absent) |

Gate commands for `docs/PROGRESS.md`: `uv run pytest tests/state tests/jobs tests/api tests/check` · `uv run pytest -m slow tests/jobs/test_resume.py` · `uv run labor check ./tests/fixtures/project-a` · `uv run labor check --live ./tests/fixtures/project-a` · `uv run labor openapi export --check` · `cd frontend && npm run check-api-fresh && npm run typecheck && npm test -- --run`.

## 11. A/B split

### 11.1 Ownership
| A (state + jobs + check) | B (API + serve + frontend wiring) |
|---|---|
| `state/**`, `jobs/**`, `faults.py`, `check.py`, `cli.py`, F1–F6, `tests/state`, `tests/jobs`, `tests/check`, `docs/design` sync | `api/**`, `serve.py`, `cli_serve.py`, `frontend/src/api/**`, `frontend/package.json` scripts/deps, `.github/workflows/ci.yml` additions, `tests/api`, V1 |

**Day 0 (A, first commit, before anything else):** `state/models.py` verbatim from §5.2, `state/interfaces.py` (below, with stubs raising `NotImplementedError`), `project.py` paths (F4), the `cli_serve.register` line in `cli.py`. B starts from that commit and tests against fakes implementing the Protocols, then switches `deps.py` to the real classes when A lands. The final integration run (A1–A15 against real services) belongs to the reviewer.

### 11.2 Interface (`state/interfaces.py`)
```python
class ReviewServiceP(Protocol):
    def queue(self, sort: QueueSort | None, view_threshold: float | None, doc: str | None, limit: int, offset: int) -> QueuePage: ...
    def cursor(self) -> Cursor: ...
    def set_cursor(self, c: Cursor, request_id: str) -> Cursor: ...
    def detail(self, block_id: str) -> BlockDetail: ...                       # KeyError → 404, OutOfScope → 422
    def act(self, a: ReviewActionIn) -> ReviewActionOut: ...                  # raises EditConflictError(EditConflict) → 409
    def flags(self, status: FlagStatus | None) -> list[Flag]: ...
    def resolve_flag(self, flag_id: str, resolution: str, request_id: str) -> Flag: ...
    def render_page(self, slug: str, page: int, dpi: int) -> Path: ...        # NoPageRender → 404
    def page_blocks(self, slug: str, page: int) -> list[dict[str, Any]]: ...
class ScopeServiceP(Protocol):
    def groups(self, doc: str | None) -> list[dict[str, Any]]: ...
    def get(self) -> SelectionOut: ...
    def apply(self, op: SelectionOp) -> SelectionOut: ...
    def summary(self) -> ScopeSummary: ...
    def regroup(self, r: RegroupIn) -> GroupOverride: ...
    def models(self) -> dict[str, Any]: ...
    def set_project_threshold(self, value: float, reason: str, request_id: str) -> float: ...
class FigureServiceP(Protocol):
    def rail(self, article_id: str) -> list[FigureRailItem]: ...
    def image_path(self, figure_id: str) -> Path: ...
    def attach(self, figure_id: str, article_id: str, anchor: str | None, request_id: str) -> AttachOverride: ...
    def detach(self, figure_id: str, article_id: str, request_id: str) -> AttachOverride: ...
    def set_bbox(self, figure_id: str, bbox: list[float], request_id: str) -> None: ...
class LearningServiceP(Protocol):
    def state(self) -> LearningState: ...
    def set_flags(self, enabled: bool | None, use_global: bool | None, contribute_global: bool | None, request_id: str) -> LearningState: ...
    def snapshot(self, request_id: str) -> SnapshotInfo: ...
    def activate(self, snapshot_id: str, request_id: str) -> LearningState: ...
    def reset(self, request_id: str) -> LearningState: ...
    def disable_item(self, item_id: str, request_id: str) -> SnapshotInfo: ...
    def publish(self, snapshot_id: str, request_id: str) -> SnapshotInfo: ...
class JobRunnerP(Protocol):
    def enqueue(self, plan: RunPlanIn, kind: str = "run", files: Sequence[Path] = ()) -> JobInfo: ...
    def get(self, job_id: str) -> JobInfo: ...
    def list(self, status: set[str] | None = None) -> list[JobInfo]: ...
    def cancel(self, job_id: str) -> JobInfo: ...
    def log(self, job_id: str, after_line: int, limit: int = 500) -> list[dict[str, Any]]: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
class StoreP(Protocol):
    def iter_actions(self) -> Iterator[ActionRecord]: ...
    def open_flag_count(self) -> int: ...
    def close(self) -> None: ...
def project_status(paths: ProjectPaths, runner: JobRunnerP | None) -> ProjectStatus: ...   # jobs/graph.py
def open_project(paths: ProjectPaths, *, mode: ProviderMode, resume: bool, clock: Clock = utc_now) -> AppServices: ...
# AppServices{paths, store, review, scope, figures, learning, runner, mock}; A implements, serve.py calls it after taking the lock
```
Exceptions (`state/errors.py`, day 0): `NotFound`, `OutOfScope`, `EditConflictError(conflict: EditConflict)`, `LockHeld(owner: dict)`, `InvalidOp`. B maps them to 404/422/409/409/422.

## 12. Open issues (each resolved with a choice)
1. **Job runner: subprocess or thread?** Subprocess per job, supervised by a thread (§4.1). It survives an API kill, hosts the spawn pool, and cancels cleanly by process group. Cost: ~1 s interpreter start per job.
2. **Who writes the DB during a job?** Only the serve process. Workers write files and their log; the supervisor turns log lines into job rows. A `labor run` without serve writes its own row. One writer, always.
3. **How `check` forces mocks.** Two layers: `mockify` rewrites the temp copy's config (this covers parse/ingest metadata, which builds providers itself), and `build_provider_set(factories=MOCK_ONLY_FACTORIES)` for every stage, so any non-mock ref fails loudly instead of reaching the network. No change to `parse_project`'s signature.
4. **`--live` on an all-mock project (project-a).** Apply the probe's `small` tier to the temp copy. Skip (exit 0, `SKIP live:`) when Ollama or a model is missing.
5. **Threshold slider vs SPEC "drag to 0".** The API's `view_threshold` is a view filter that only ever *adds* auto-approved blocks to the queue (findings, 03 §12.11). The project threshold changes only through calibration/apply (`PUT /api/config/threshold`), which restates machine statuses through scoring and never touches decisions. Module 9 may draw the slider inverted to match the SPEC wording.
6. **Progress granularity.** Stages emit per doc, not per block. Progress = (node, doc) units, plus an LLM-call heartbeat for liveness. Per-block emit would mean editing every stage for no correctness gain.
7. **Approval of text that later changes** (cleanup/learning re-run). The approval does not transfer: the block reverts to machine status with a `changed since approval` chip (§2.3). Edits keep their own text, so they survive.
8. **Selection storage.** Moved into SQLite as the truth; `selection.json` stays as a projection, because modules 4/5 read it.
9. **Learned layer location vs modules 4/5.** Materialize the active snapshot into the paths they already read, rather than teaching them about snapshots. Reset deletes the materialized copies only.
10. **Rejected status** (`BlockStatus.rejected`) is not produced by module 7. Module 10/11 define it (agent pass / export exclusion).
11. **NumericVariants** stay in `scores.json` (03 §7). Module 7 does not take them over; a human resolves a numeric conflict by editing, which goes through §2.3.3.
12. **Parser-disagreement highlights on the page render** need word bboxes per parser, which blocks do not carry. v1 highlights disagreement spans in the *text* pane (`parser_texts` + diff); page-level highlighting is deferred.
13. **Two generated TS type sets** (`generated.ts` from contracts, `schema.d.ts` from OpenAPI) overlap. Accepted: API code uses `schema.d.ts`; contract-only consumers keep `generated.ts`.
14. **Windows.** `fcntl` locks and `killpg` make v1 macOS/Linux only; recorded, not addressed.

## 13. Implementation notes (implementer A, 2026-10-29): where the code differs from or extends this design

| Item | What the code does | Why |
|---|---|---|
| `ActionKind.import` | the enum member is `ActionKind.import_` with value `"import"` | `import` is a Python keyword |
| `ReviewActionIn.request_id` | required, non-empty | idempotency is the point of the field |
| `ReviewActionOut.block_status` | `None` after `back` | `back` records no decision |
| Executor granularity | one stage call per (node, doc) unit, including `parse` | per-unit `stages.json` and fault points; `parse` builds its OCR runtime per call (cost: one pool start per document that needs OCR) |
| `score` node when `clean.json` exists | the fingerprint check is left to `score2` (the file carries score2's fingerprint); the threshold check still applies to both | otherwise `score` would look stale after every clean |
| Node `failed` vs `missing` | a recorded failure is reported as `failed` even when the output is absent | the reason is more useful than "missing" |
| Fault points | `llm.after_calls:<node>:<n>` (calls inside one node) and `score.after_history` / `score.after_scores` were added; `faults.delay(point)` (`MANUALLABOR_DELAY=<point>=<s>`) holds a unit open for the cancel test | the R2 "during clean" case needs a per-node counter; cancel needs a unit that is still running |
| `node.after:<node>:<slug>` | fires after the stage returned and before `stages.json` is written (as specified) | |
| Projections | `selection.json`, overrides and `learning/*` are rewritten by `reconcile` on every writer `Store.open`; the project threshold and `learning.*` config writes happen after commit and are not reconciled | a crash between commit and the config write leaves the old config; the action row shows the intent |
| `figure_overrides.json` | `[{seq, figure_id, bbox}]`, latest per figure; absent when there are no rows; its sha enters the figures fingerprint only when the file exists | pre-module-7 fingerprints stay valid |
| `jobs` concurrency | 1; the worker lock is project-wide, so a second worker would be refused anyway (`MANUALLABOR_JOB_CONCURRENCY` is not read) | |
| Learning example | `actions.example` also carries `raw_source` (needed to mark OCR examples) and `human_edit` | |
| `labor run` / `labor check` | one `jobs` row per call (kind `run`) written by `jobs/inline.py`; progress lines are the stage lines plus `{"event":"unit_done",...}` | |
| `labor check` K6 | re-runs every node through its skip path (`make_plan(include_fresh=True)`) and asserts only `skip`/`sidecars` statuses and unchanged hashes under `docs/` and `figures/` (stages.json excluded) | an empty plan would prove nothing |
| Approve after edit (review fix) | an `approve` whose block has a current `edit` approves the edited text: the decision stores `sha256(edited_text)` as `shown_text_sha256`; the derived status stays `edited` (the edit is the text source), `numbers_verified = has_numeric_spec`. `numbers_verified` is set by an approve (or an accepted agent proposal), never by an edit; an approval recorded against other text never discards an edit | K then A must not throw the human edit away |
| Re-parse guard on every CLI path (review fix) | `run_node` applies the `make_plan` guard: `labor parse [--force]` on a doc with decisions is refused (exit 1) with a message naming the decision count; `--discard-decisions` (`labor parse`, and an alias of `--allow-reparse` on `labor run`) overrides it | `--force` bypassed the guard |
| Selection writes (review fix) | `ScopeService.apply` reads the current selection inside its `BEGIN IMMEDIATE` transaction | concurrent PUTs lost updates |
| Request ids (review fix) | `Store.action_by_request(rid, kinds)`: a request id already used by an action of another kind → `RequestIdReused` → 409 `request_id_reused`. `JobRunner.enqueue(..., request_id=)` is idempotent (the plan JSON carries `request_id`), so replaying attach/detach/bbox/threshold/regroup returns the original job | a replay must not enqueue a second job |
| Job errors, `labor check`, `labor learning list` (review fix) | a failed unit records `"<node> <slug>: <message>"` (first 500 chars) in `jobs.error`; an invalid `project.json` is a `project.json FAIL` row (exit 1); `MANUALLABOR_TMP` sets where the check copy goes; `labor learning list` opens the DB read-only without the lock | |

## 14. Concurrency and durability fixes (code review F1, F2, F7, F14, F16, F17; 2026-10-30)

### 14.1 Temp files: two suffixes, two owners (F1, F16)
**Failure mode.** The job's start-up cleaner (`clean_stray_tmp`) deleted every `*.tmp` under `docs/`, `figures/` and `learning/`. The serve process writes there too, outside the worker lock: the DB-to-file projections after every regroup, attach, detach, crop and learning change (`write_if_differs` through `write_text_atomic`, which wrote `<name>.tmp`), and learning snapshots staged in `learning/snapshots/.tmp-<sid>/`. Each of those API mutations enqueues a job right after it, so the cleaner ran within one runner tick of the write: the API returned 500 from the after-commit callback, the projection on disk stayed stale and the job just enqueued read the stale file. The cleaner itself crashed when a writer renamed its temp file between `rglob` and `unlink`, failing the whole job. Two concurrent writes of one file also shared `<name>.tmp`, so the second `os.replace` failed. Same-named concurrent uploads shared `.uploads/.incoming-<sha(name)>` and interleaved their bytes.

**Rule.**
- Every `write_text_atomic` call writes its own temp file, `<name>.<uuid4 hex><suffix>`, then fsyncs it, renames it and fsyncs the directory (14.3). A failed write removes its temp file.
- `*.tmp` (`TMP_SUFFIX`, the default) is written only while holding the worker lock (pipeline stages, `stages.json`). `clean_stray_tmp` removes leftovers at every job start, with `unlink(missing_ok=True)`.
- `*.part` (`PART_SUFFIX`) is written by everything outside the worker lock that lands under `docs/`, `figures/` or `learning/`: `write_if_differs` (every projection, `agent/outcomes.json`, the materialised learning files), the snapshot staging dir (`learning/snapshots/.part-<sid>-<hex>/`), page renders (`render_tmp_path`) and upload temp files (`.uploads/.incoming-<random>.part`). The job cleaner never matches them.
- `.part` leftovers are removed by `clean_stray_parts`, called only from `clean_leftovers_at_start` at `labor serve` start-up: after the project lock is taken (no API request or CLI writer can be running) and before the runner starts, and only if the worker lock can be taken too (a worker left running by the previous serve renders OCR pages with `.part`; when it is alive, the clean is skipped until the next start). It also removes legacy `.tmp-*` snapshot staging dirs and `.uploads/<sha>/` dirs that no queued or running job lists in its plan file (ingest has copied them to `sources/`).
- Writes outside the project (`~/.manuallabor/learning/snapshots/.part-<gid>-<uuid>/`, `calibration/<uuid>.jsonl`) and root files (`project.json`, `probe.json`) are not matched by any cleaner; their unique temp names are enough. Global publish (`learning.publish_global`, amended 2026-10-30, review 2 finding 5): the id was read from `latest_global()` outside any lock and staged in a shared `.tmp-<gid>` that each publish `rmtree`d first, so two publishes (two projects, or a double submit) took the same id and one deleted the other's files mid-write. Now the id is chosen while holding an exclusive `flock` on `<global>/snapshots/.publish.lock` (blocking; it also serialises threads of one process), the files are staged in this call's own `.part-<gid>-<uuid>/` and renamed into place before the lock is released, and only that folder is removed on failure. Test: `tests/state/test_publish_race.py` (eight concurrent publishes get ids 001 to 008, each complete, and a foreign staging folder is left alone).

**Tests.** `tests/jobs/test_temp_files.py` runs the job cleaner between the temp write and the rename of a projection and of a snapshot, removes a temp file between the cleaner's `is_file` and `unlink`, checks unique `.part` names per call, runs six concurrent writers of one file, and checks what the start-up cleaner removes, that it does nothing while a worker holds its lock, and that it keeps uploads a queued job still needs. `tests/api/test_upload_temp.py` interleaves two same-named uploads.

### 14.2 Sequence numbers are allocated inside the transaction (F2)
**Failure mode.** `regroup`, `FigureService._override` (attach, detach) and `set_bbox` read `next_override_seq` / `next_figure_override_seq` before `with store.tx()`. API routes are sync and run in a threadpool, so two requests read the same value and the second insert failed `UNIQUE constraint failed: <table>.seq`, an unmapped 500 that also lost the request id. `LearningService.snapshot` and `disable_item` had the same shape with `next_snapshot_id` (the second request got "snapshot already exists").

**Choice.** Read the sequence inside the same `store.tx()` as the insert. `tx()` holds the store's `RLock` and `BEGIN IMMEDIATE`, so allocation and insert are serialised within the process and across processes. Rejected: dropping the explicit seq for the AUTOINCREMENT rowid (`cur.lastrowid`). The seq is also inside the override's JSON `body` (`GroupOverride.seq`, `AttachOverride.seq`, which grouping and cleanup apply in order), so the body would have to be written after the insert, and the override tables are append-only (an `UPDATE` trigger aborts). That needs a migration for no gain.

**Tests.** `tests/state/test_override_seq_race.py`: two threads per write path meet at a barrier inside `next_*` (0.5 s timeout). With the read outside the transaction both read the same value and one insert fails; inside it the barrier times out and both writes get distinct seqs.

### 14.3 `write_text_atomic` is durable (F14)
`f.flush(); os.fsync(f.fileno())` before `os.replace`, then fsync of the directory (POSIX; skipped where a directory cannot be opened). Without it a crash can make the rename durable while the data is not, leaving a zero-length `document.json` (which drops the document from `list_slugs` without a message) or `blocks.json`. Test: `tests/contracts/test_atomic_write.py` records the order fsync(file), replace, fsync(dir).

### 14.4 The re-parse guard fails closed (F7)
**Failure mode.** `_decision_count` returned 0 when `project.db` failed to open or to be read (a corrupt file, a newer schema, a permissions error), so `make_plan` and `run_node` let a re-parse through and orphaned every decision. **Rule.** A missing `project.db` means no decisions. Any other error while counting refuses the parse with `reparse_unknown(exc)`, which names `project.db` and the error. Amended 2026-10-30 (review 2 finding 2): it does not suggest `--discard-decisions` (which still overrides when given), because the decisions are probably intact and the fault is the database or its path; it says to check that `project.db` is readable or restore it. The read-only open uses a quoted file URI (`path.resolve().as_uri() + "?mode=ro"`): the unquoted `file:{path}?mode=ro` read `#` as a fragment, `?` as the query and decoded `%xx`, so a project under `~/Manuals #2/` failed to open and every re-parse was refused. Tests: `tests/state/test_db_uri.py` (`#`, `%`, `?` and spaces in the folder name, through `Store.open(readonly=True)` and the guard). Tests: `tests/jobs/test_reparse_guard_db.py` (corrupt bytes and `user_version = 999`, through `make_plan` and `labor parse`). `labor status`'s `orphaned_decisions` (`graph._orphans`) still reports 0 on an unreadable DB; it is informational and does not gate anything.

### 14.5 Project paths (F17)
`ProjectPaths.llm_cache` (`.llm_cache/`) and `ProjectPaths.probe` (`probe.json`) join `llm_log`; no module builds them by hand (`tests/test_project_paths.py` greps the package).

## 15. Request guard, upload cap, bind warning, explicit not-found (code review F3, F13; 2026-10-30)

**Failure modes.** (F3) Uvicorn and FastAPI accepted any `Host` header, so a web page could DNS-rebind its own name to `127.0.0.1` and read every GET (the manuals via `/api/docs/{slug}/source`, the export zip, `/api/decisions/export`). JSON writes are protected by the browser's CORS preflight (the API sends no CORS headers), but `POST /api/sources` is `multipart/form-data`, a "simple" request: any page could submit a form to `127.0.0.1:8765`, store a file and start an ingest job that runs the configured (possibly API-key) models. Uploads had no size cap, and `--host 0.0.0.0` warned nothing. (F13) A global `KeyError -> 404` handler reported every programming error that happened to be a `KeyError` as "not found"; Tesseract subprocesses had no timeout, so a wedged one hung an OCR pool worker forever while the job kept heart-beating.

**Rule: one ASGI middleware, `RequestGuard` (`manuallabor/api/guard.py`), installed by `create_app` around every route.** It runs before routing, so a rejected request reaches no handler, no service and no file.
1. **Host.** When `create_app(allowed_hosts=...)` is given (`labor serve` always gives it), the request's `Host` name (lower-cased, port and IPv6 brackets stripped) must be in the allow-list, else **421 `bad_host`**. A missing `Host` is rejected the same way. The allow-list is `allowed_hosts_for(bind_host, extra)`: `127.0.0.1`, `localhost`, `::1`, the exact `--host` given (unless it is a wildcard) and every `--allow-host NAME`. When the bind host is a wildcard (`0.0.0.0`, `::`), any IP-literal `Host` is also accepted: clients reach a wildcard bind by whichever address they route to, and a rebinding attack always arrives with the attacker's DNS name in `Host`, never an IP literal. A DNS name for a LAN bind (`mybox.local`) must be listed with `--allow-host`. The port is not compared: the Vite dev proxy forwards the browser's `Host` (`127.0.0.1:5173`) unchanged. That needs `changeOrigin: false` written out in `frontend/vite.config.ts`: Vite's string shorthand (`"/api": "http://127.0.0.1:8765"`) turns `changeOrigin` on, rewrites `Host` to `127.0.0.1:8765` while the browser's `Origin` stays `http://127.0.0.1:5173`, and every UI write through the dev server would be refused by rule 2 (checked with curl through both proxy shapes; `tests/api/test_guard.py` pins the config). `create_app` without `allowed_hosts` (unit tests, OpenAPI export) skips this check only.
2. **Same-origin writes.** For `POST`, `PUT`, `PATCH`, `DELETE` (and websocket handshakes): each of these headers, when present, must say same-origin, else **403 `cross_origin`**: `Origin` (its `host[:port]` must equal the request's `Host` header exactly, scheme `http` or `https`; `Origin: null` fails), `Sec-Fetch-Site` (`same-origin` or `none`; `same-site` fails, since `localhost:3000` is same-site with `localhost:8765`), and `Referer` (same `host[:port]` as `Host`). A request with none of them (curl, Playwright's `request` fixture, the Python tests) passes. The bundled UI passes: its `fetch` is same-origin (`Origin` = `Host`), directly on 8765/8766 or through the Vite proxy on 5173 (browser `Origin: http://127.0.0.1:5173`, forwarded `Host: 127.0.0.1:5173`). The multipart upload is the one write a foreign page can send without a preflight; every browser that can send it adds `Origin` to a cross-origin POST (and `Sec-Fetch-Site` since 2020, `Referer` as the older fallback), so it is covered by this rule and tested with each header alone. GETs are not origin-checked: a cross-origin read is blocked by the browser because the API sends no `Access-Control-Allow-Origin`, and rule 1 stops rebinding.
3. **Body cap.** Every request body is capped at `max_body_bytes` (`labor serve --max-upload-mb`, default 200 MB). A `Content-Length` above the cap is answered **413 `too_large`** before the app reads anything. Without `Content-Length` (chunked), the guard counts bytes as the app reads them and stops at the first chunk past the cap with the same 413 (the app's own response, e.g. FastAPI's 400 for a body that failed to parse, is replaced). The check has to sit in front of the app: Starlette spools the whole multipart body into anonymous temp files before the handler runs. `_save_upload` repeats the check per file (same limit, read from `app.state.max_body_bytes`) and removes its `.incoming-*.part` temp file on the way out, so a 413 leaves nothing under `.uploads/`.

Rejections are JSON `{detail, code}` like every other error and log one warning line (`manuallabor.api` logger) with the method, path and offending header.

**Bind warning.** `labor serve` keeps `--host 127.0.0.1` as the default; a non-loopback address is only ever bound because the user typed it. For a non-loopback `--host`, `serve` prints to stderr before binding: the server has no authentication, and anyone who can reach that address on the network can read the manuals in the project, download exports and decision logs, and start jobs (including ones that spend API-key models); then the host names it accepts (rule 1).

**Explicit not-found (F13).** The global `KeyError` handler is gone. `NotFound` (`state/errors.py`, already raised by every service lookup a route reaches: review, figures, learning, scope, agent proposals, the job runner) maps to 404 `not_found`; routes raise `ApiError(404, ...)` themselves. Any other exception, a plain `KeyError` included, is a JSON **500 `internal_error`** and is re-raised so uvicorn logs it with its traceback. (`agent/inputs.py` raises a plain `KeyError` for a missing block, but only inside the agent job, whose `pipeline.py` catches it; no route reaches it.)

**Tesseract timeouts (F13).** `TesseractAdapter.ocr_page` runs `tesseract` with a per-page timeout, `MANUALLABOR_TESSERACT_TIMEOUT` seconds (default 600; a 300 dpi page takes 2 to 15 s on the reference machine, so this only fires on a wedged process). `subprocess.run` kills the child on expiry and the page fails with `RuntimeError("tesseract timed out after N s on page P (...)")`, which fails the parse job with that message instead of hanging the pool worker. `--version` and `--list-langs` get 30 s each with the same kind of error.

**Other swallows (F13).** `ingest.metadata_provider` no longer turns an unreadable or invalid `project.json` into a silent "no metadata model": it warns with the error and skips metadata inference. `ingest._docx_info` imports `python-docx` outside its `try`, so a broken install fails loudly instead of reading as "no title"; a document whose core properties cannot be read still has no title. `state/review.py` `_page_ref` (a failed page open becomes a zero-size page with no log) belongs to the state owner and is left to them.

**Tests.** `tests/api/test_guard.py`: foreign, missing and bracketed-IPv6 `Host`; non-loopback and wildcard binds with IP literals and `--allow-host`; write with a foreign, `null`, other-port and matching `Origin`, the Vite-proxy shape, `Sec-Fetch-Site` cross-site and same-site, foreign `Referer` alone; the multipart upload with each of those (403, no job, nothing under `.uploads/`) and with none (202); GET with a foreign `Origin` passes and carries no CORS header; body cap with and without `Content-Length` (413, no job, no temp file), `_save_upload`'s own cap; `KeyError` -> 500 re-raised, `NotFound` -> 404; the bind warning text; the CLI default host and option plumbing; `serve` printing the warning and guarding its app; a real uvicorn socket rejecting a foreign `Host`, a cross-origin multipart form and an oversized body; `vite.config.ts` keeping `changeOrigin: false`. `tests/parse/test_ingest.py`: an unreadable `project.json` warns, a missing `python-docx` raises. `tests/parse/test_b_ocr.py`: a fake `tesseract` that sleeps past a short timeout fails the page with the timeout message.

## 16. Read caches, selection deltas and job rows (code review F4, F5, F6, F8, F12; 2026-10-30)

### 16.1 One cache for every read the screens poll (F4, F5)
**Failure mode.** `/api/export/status` built a cold `ProjectData` and re-read and re-validated every block per call (215 ms at 424 blocks, about 0.5 ms per block); `/api/scope/blocks` called `load_scored_blocks` per document per call; `/api/docs/{slug}/figures` re-derived the whole document once per figure page; `/api/status` (also behind `/api/sources`, mounted by five components) opened a new read-only `Store` and hashed every block per document per call. All of them are refetched after every approve and every job.

**Rule.** The serving `ProjectData` (`state/data.py`) is the one cache. `memo(kind, key, signature, make)` recomputes a value when its signature changes. A value that reads decisions, flags, the selection or overrides puts `store.max_action_id()` in its signature through `db_signature(*files)`: every write of those tables appends an action in the same transaction, so the last action id moves with them, and a read that starts after the commit sees the new id. `db_signature` returns None (do not read or fill the cache) while a transaction is open: the thread that owns it sees rows before their action row (a decision is written first, its action last), and other threads block on the store lock until the commit. A value computed from data newer than its key only causes one extra miss; it is never served under a newer key.
- `ReviewService._derive_doc(slug)` (machine block, overlay, derivation per block) is cached on `(blocks, scores, clean stats, last action id)`. Projections of it share that signature: `review_blocks` (the overlays, `load_review_blocks` equivalent), `block_statuses`, the per-page index behind `page_blocks`, and the title rows behind `titles` (16.3). The Verify queue, block detail and actions read the same cache outside a transaction; an action's own outcome (`_outcome`, inside its transaction) derives uncached, as before.
- `export_status(paths, store, review)` caches the gate and the active overrides on `(document slugs, each document's blocks/scores/clean/groups/attach stats, last action id)`; `export/state.json` and the zip are read per call (one small file and a stat). The CLI passes no service and gets a throwaway one; `run_assemble` keeps its own uncached gate. Semantics are unchanged: the cached answer equals the uncached one after every write kind (test below).
- `/api/scope/blocks` serves rows from `ProjectData.machine_blocks` and memoises them per document on the machine files' stats. `/api/docs/{slug}/figures` memoises the file part (attachments, figure records) on the stats of `attach.json`, `blocks.json` and every `FIG-*.json` (and their names), and reads statuses from `block_statuses`.
- `jobs/graph.project_status` memoises, beside the node states, each document's `document.json`, its learning provenance (`groups.json`/`clean.json` stats) and its orphan count (`blocks.json` stats plus the last action id). It reads the DB through the runner's store when serving; `labor status` opens one read-only store per call instead of one per document.

**Tests.** `tests/api/test_cached_reads.py` on the real services: three unchanged export polls derive nothing; an approve, a flag, a blanket override and a selection op are each seen by the next poll and the cached status equals the CLI's uncached one after each; a stage file rewritten with the same bytes is a miss; scope rows load only the touched document; figures and every page's blocks follow an approve with one derivation; `/api/status` re-reads nothing when nothing changed, re-counts orphans after an action, and reports an orphan as soon as a decided block's raw text changes; `db_signature` is None inside a transaction.

### 16.2 A selection action stores its delta (F6)
**Failure mode.** Every selection op stored the selection before and after as blobs and the whole `SelectionOut` (selection, coverage, summary) in its payload: 24.6 KiB per click at 364 selected ids, about 0.7 MB per click at 10 000 blocks, streamed again by `labor decisions export` and the learning snapshot builder.

**Rule** (`state/selection_log.py`). The payload keeps the op (`op`, `block_ids`, `group_id`, `subtree`, and now `view` and `split`), adds `delta` = the change from the stored selection before to the one written (`base`: `stored` or `none`; `added` and `removed` ids; `set`: every other field that changed, as `[old, new]`), and keeps in `_outcome` only what cannot be recomputed: `dropped` and `summary`. No blobs. The log stays replayable because only `ScopeService.apply` (and `import_legacy`, once, with an `after` snapshot) write the stored selection:
- forward, `replay_selection(actions)` rebuilds the stored selection from nothing (a delta, or an `after` snapshot for older rows and `import`);
- backward, a replayed request (S3) gets its first response back: `selection_at` reverts the deltas of every later selection action from the stored selection, coverage is recomputed on the current groups (equal unless a regroup ran in between), `dropped` and `summary` come from the row.

**Old rows are not migrated.** A row with the full `_outcome` (it has a `selection` key) is returned verbatim on replay; its `after` snapshot serves the forward replay. A newer row can never precede an older one, so the backward walk never crosses one (it raises if it would).

**Tests.** `tests/state/test_selection_log.py`: a single-block op on a 364-id selection stores no blobs and a payload under 2 KiB; a replay after five later ops (ids, view, split) equals the first response and writes nothing; the very first op (no stored selection) replays; the forward replay equals the stored selection; a hand-written old-format row replays verbatim and anchors the forward replay. The existing request-id tests (`tests/api/test_real_services.py`) stay green.

### 16.3 Titles for blocks named outside the queue (F12)
`GET /api/verify/titles?ids=...` (1 to 200 ids) returns `BlockTitle {block_id, doc_id, page, type, section_title}` per known id, in the order asked, once each; unknown ids and documents not scored yet are left out. `section_title` is the card's (the nearest heading above, on the overlay text). The Export screen asks for exactly its blockers (at most 20) instead of reading every document's whole queue with `limit=2000&view_threshold=1`. Tests: `tests/api/test_cached_reads.py` (equal to the queue card fields, order, unknown id, 422 on none and on 201), `frontend/src/shell/blockTitles.test.tsx`, `ExportScreen.test.tsx` (grouping by the looked-up sections, one request with the listed ids).

### 16.4 Job rows: indexed reads, quiet ticks, pruning, a lower-priority worker (F8, T13)
**Failure mode.** `JobRunner.poll` read the whole `jobs` table three times per 0.5 s tick and filtered in Python; `enqueue(request_id=)` read every row and parsed every plan; `_update_progress` wrote the row every tick whether or not anything changed; nothing ever deleted a row. Every approve, attach, regroup and threshold change enqueues a job, so the tick grew for the life of the project, in the serve process and under the store lock the API needs.

**Rule.** Migration 3 adds `jobs_status ON jobs(status, n)` and `jobs_request ON jobs(json_extract(plan, '$.request_id'))`. `Store.job_rows(statuses)` filters in SQL; `Store.job_by_request` finds a replayed request through the index and parses only the plan it returns. A tick reads the running rows once and the queued rows only when nothing runs; it writes progress only when the log tail moved (`_Tail.written`).
**Pruning.** At start and then hourly, finished rows (`done`, `failed`, `cancelled`, `interrupted`) whose `finished_at` is more than **7 days** old are deleted, except the newest **200** finished rows, which are always kept. A finished row is read for three things: the idempotency of a replayed request (a client retry: seconds to minutes), the Jobs bar and `/api/jobs` (recent work), and its log (the files under `logs/jobs/` stay on disk). A week covers every retry and a weekend away; the newest 200 keep a project reopened after a long break showing what last ran. Queued and running rows are never pruned. Job ids keep increasing (`AUTOINCREMENT`), so a pruned id is never reused.
**Worker priority.** The runner lowers each worker's priority to nice 10 right after spawning it (`os.setpriority`, before the worker has imported anything, so every thread it starts inherits it). Parse and model work is background by design; at equal priority a Docling parse on a 2-core machine delayed every API request (T13 measured a ~1 s approve ack on a 2-vCPU CI runner). This is the only protection: Docling keeps a fixed 4 torch threads on every machine (design 01 section 4.2, block IDs must not depend on the core count), and the kernel scheduler gives the API the core it needs.

**Tests.** `tests/jobs/test_runner_rows.py`: status filters through `jobs_status` (query plan); a replayed request found through `jobs_request` parses one plan among 51 rows; an unchanged tick writes nothing and a moved one writes once; pruning keeps queued, recent and the newest 200, deletes the rest, is idempotent and leaves a kept row's request replayable; a started worker is reniced to 10. `tests/state/test_store.py` S1 covers the migration.

### 16.5 Lock order: the runner's, then the store's (review 2, 2026-10-30)
**Failure mode.** `AgentService.enqueue` and `CalibrationService.apply` enqueue a job inside their own `store.tx()` (the store's RLock, held for the whole transaction), and `JobRunner._enqueue` then took the runner's lock; the supervisor tick (`poll`) takes the runner's lock and then the store's for every query. A tick that landed while an agent pass was being enqueued deadlocked both threads, and every later API request queued behind the store lock.
**Rule.** The runner's lock is never acquired while the store's is held. `_enqueue` and the request-id check in `enqueue` rely on `store.tx()` alone (it makes the row and its plan file appear together, and a tick reads rows only after the commit); `_live` reads the in-memory step without a lock (a dict lookup and a whole-tuple read). `poll`, `cancel`, `prune` and `_reconcile` keep runner, then store.
**Test.** `tests/jobs/test_lock_order.py`: a transaction is held while a tick is parked on the store lock inside `poll`, then the transaction enqueues (`enqueue_raw`, `enqueue`, `enqueue` with a request id); both threads must finish and the tick starts the new job.

## 17. Inner progress for the jobs bar (first-use report D; 2026-10-30)
**What failed.** A tester watched "3 of 4 steps · now on pump-service-tables" for 45 s to 3 min: `node`/`doc` were set from `unit_done` (the unit that had *finished*, not the one running), progress moved only per unit, and the slow unit (grouping with a 1B model) said nothing.

**Events.** The worker's `StepLog` (`jobs/worker.py`) is the executor's `emit`. It writes `{"event":"unit_start","node","doc","index"}` before each planned unit runs (after `job_start`, after each `unit_done`, and after a document unit skipped as `blocked`, which writes no `unit_done`; a blocked project-level unit, `assemble` or `export` with `doc` "", writes its own `unit_done` after the blocked line, so the next unit is named only then; amended 2026-10-30, review 2 finding 7), and `{"event":"step","node","doc","done","total","unit"}` from the stages' own counts. Stages report through `jobs/progress.report(doc, done, total, unit)`, a no-op unless a reporter is installed (CLI output and every direct call are unchanged); only counts a stage already keeps are reported: OCR pages collected (`parse`, unit `page`), the page of the figure being extracted (`figures`, `page`), blocks scored (`score`/`score2`, `block`), topics named (`group`, `topic`, the naming loop only), blocks cleaned (`clean`, `block`). Docling's own parse, embedding, straggler review, attach and describe report nothing: those steps say "working, no estimate". `StepLog` drops a step for another unit, never goes backwards, and writes at most one step per 0.25 s (the first and the last count always). Fault point `step:<node>` (`MANUALLABOR_DELAY`) sleeps after each written step; the Playwright spec uses it to keep a step visible.

**Job row.** The supervisor sets `node`/`doc` from `unit_start` (the unit running; after the last unit they stay on the last one finished, as before) and keeps the current unit's step in memory: `JobInfo.step_done`, `step_total`, `step_unit` (None when the unit reported no count) are added by `JobRunner.get`/`list` for a running job, not stored (no migration; an adopted job re-reads its log from the start, so a serve restart rebuilds them). `progress = (units_done + step_done/step_total) / units_total`, still monotonic. `JobInfo.files` lists the file names of a queued or running `ingest_run` job (from its plan file), so a waiting upload is named before it has a document slug. Contract change: `JobInfo` (OpenAPI and TS types regenerated).

**Tests.** `tests/jobs/test_worker_progress.py`: `report` without a reporter; `unit_start` order including a blocked unit; step throttling, monotonicity and other-unit drops; a blocked project-level unit named done only by its `unit_done`; the job row's current unit, step and progress through `poll`, ignoring another unit's step, clearing on `unit_done`; `files` of a queued ingest job; topic naming, scoring and cleanup report real counts on synthetic documents.
