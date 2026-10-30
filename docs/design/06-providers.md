# Module 6 design: provider layer + hardware probe

Status: draft for implementation · Inputs: SPEC §8, §9, §10 · CLAUDE.md (module 6 gate) · `docs/design/00-contracts.md` §4.11, §4.12, §6 · `findings.md` (environment, resource constraint) · code read: `providers/{base,cache,sinks,mock,__init__}.py`, `contracts/{config,llm}.py`, `cli.py`, `ingest.py`, `grouping/pipeline.py`, `cleanup/pipeline.py`, `scoring/verifier.py`.

**Gate (CLAUDE.md):** Ollama + Anthropic + OpenAI-compatible each pass the same contract test; `labor probe` returns a suggestion table on Linux/macOS.

## 0. Facts established (measured 2026-10-29 on this machine)

| Fact | Value | Consequence |
|---|---|---|
| LiteLLM installed | 1.106.5 (`litellm.__version__` does not exist; use `importlib.metadata.version("litellm")`) | Record the version in `probe.json`/logs. |
| `import litellm` cost | ~1.0 s, ~194 MB RSS | Lazy import only; never at package import. |
| LiteLLM Ollama | `ollama_chat/<model>` hits `/api/chat`: images (`message.images`), `response_format` json_schema mapped to Ollama `format`; embeddings via `ollama/<model>` (`/api/embed` or `/api/embeddings`) | One implementation suffices (decision D1). |
| LiteLLM Anthropic | `anthropic/<model>`: chat + image content blocks; **no embeddings API exists** | `embed` on anthropic raises `ProviderError` (not a bug; contract test expects it). |
| LiteLLM OpenAI-compatible | `openai/<model>` + `api_base` (vLLM, llama.cpp-server, OpenAI) | `vllm`, `llamacpp`, `openai_compatible`, `openai` are aliases of one spec. |
| LiteLLM network side effects | fetches its model-cost map from GitHub on import unless `LITELLM_LOCAL_MODEL_COST_MAP=True`; telemetry on by default | Set the env var **before** import and `litellm.telemetry=False` (offline guarantee). |
| Ollama here | 0.40.2 at `localhost:11434`; models present: `nomic-embed-text:latest` (274 MB) only | Chat + vision models must be pulled for live tests (§8). |
| Hardware | Apple M3, 16 GB unified, ~11 GB free disk | Small models only; concurrency 1; no model > ~2 GB in live gate. |
| Existing wiring | `BaseProvider` already does cache, one-log-per-call, schema validation, vector checks. Callers use `build_provider_set(config, cache_dir=, sink=)` (default `factories=DEFAULT_FACTORIES`) and `ingest.py` calls `DEFAULT_FACTORIES.get(ref.provider)` directly | The new providers are **only** a `BaseProvider` subclass plus entries in `DEFAULT_FACTORIES`. **No caller changes** (one defensive edit in `ingest.py`, §2). |

## 1. Package layout (`manuallabor/providers/`)

| File | Content |
|---|---|
| `registry.py` | `BackendSpec` table, `normalize_ollama_host`, `resolve_endpoint(ref, env) -> Endpoint`, `register_defaults(factories)`, `make_factory(name) -> Factory`. Imports **nothing heavy** (no litellm, no httpx at top level). |
| `litellm_provider.py` | `LiteLLMProvider(BaseProvider)`: the only real implementation. Imports litellm lazily through `_litellm()`. |
| `probe.py` | Hardware detectors, parsers, `suggest()`, `render_table()`, `run_probe()`. Imports `subprocess`, `shutil`, `platform`; `httpx` only inside `probe_ollama`. |
| `probe_catalog.py` | Pure data: model candidates per task and tier (name, approx GB, notes), the all-API row. Edit-in-place data, no logic. |
| `contracts/probe.py` | **New contract (forced):** `ProbeResult`, `SuggestionTable`, `TaskSuggestion`, `TierOption`, `OllamaStatus`, `GpuInfo`, `CpuInfo`. Added to `EXPORTED_MODELS`; run `labor schemas export` so `schemas/` and generated TS types move together (CLAUDE.md principle 6). |
| `ollama_provider.py` | **Not created.** Fallback only if the live Ollama contract run (T1) fails for a reason LiteLLM cannot be configured around (see D1). |

`providers/__init__.py` calls `registry.register_defaults(DEFAULT_FACTORIES)` after its existing imports. `base.py` changes only the annotation: `DEFAULT_FACTORIES: dict[str, Factory] = {"mock": _mock_factory}` (mutable; `build_provider_set`'s default argument holds the same object, so in-place registration reaches every caller). Importing `manuallabor.providers` must not import litellm or httpx (T3).

Registered names: `mock`, `ollama`, `anthropic`, `openai`, `openai_compatible`, `vllm`, `llamacpp` (the contract's `KNOWN_PROVIDERS` already lists all but `openai`; add `"openai"` to `KNOWN_PROVIDERS`, a tuple used only for docs/UI hints, not validation).

### 1.1 `BackendSpec` (data, in `registry.py`)

| name | chat id | embed id | default base | base env | key env (default) | key required | schema mode | max concurrency | read timeout |
|---|---|---|---|---|---|---|---|---|---|
| `ollama` | `ollama_chat/{m}` | `ollama/{m}` | `http://localhost:11434` | `OLLAMA_HOST` | none | no | native | 1 | 600 s (first call loads model) |
| `anthropic` | `anthropic/{m}` | unsupported | LiteLLM default | none | `ANTHROPIC_API_KEY` | yes | prompt | 4 | 120 s |
| `openai` / `openai_compatible` | `openai/{m}` | `openai/{m}` | LiteLLM default | `OPENAI_BASE_URL` | `OPENAI_API_KEY` | yes if no `api_base` | native | 4 | 120 s |
| `vllm`, `llamacpp` | `openai/{m}` | `openai/{m}` | **required** (`ref.api_base`) | none | none (sends `"not-needed"`) | no | native | 1 | 600 s |

Resolution order for base URL: `ref.api_base` > base env > spec default. Key: `os.environ[ref.api_key_env or spec.key_env]` read **at call time**, never stored on the instance in logs/repr, never written to `project.json`, cache, sink, or exception text. All error strings pass through `_redact(text, secrets)` which replaces the key (and any `sk-…`/`Bearer …` token pattern) with `***`. Missing key: `ProviderError("environment variable ANTHROPIC_API_KEY is not set (required for provider 'anthropic')", retriable=False)` raised **at factory time** (so a bad project fails before any block is processed); the message names the variable, never a value. `ingest.py` line ~131 wraps `factory(...)` in `try/except ProviderError` → `warn(...)`, return `None` (the one defensive caller edit).

`normalize_ollama_host(value)`: pure; `None`/empty → default; `host` → `http://host:11434`; `host:port` → `http://host:port`; `0.0.0.0` → `127.0.0.1`; keeps an explicit `http(s)://`; strips trailing `/`.

## 2. `LiteLLMProvider` behaviour (precise)

Constructor `(ref, *, sink, cache, clock, spec, endpoint, sleep=time.sleep)`. Concurrency: a process-wide `threading.BoundedSemaphore(spec.max_concurrency)` keyed by `(provider, api_base)`, acquired around each raw call; `MANUALLABOR_MAX_CONCURRENCY` overrides (integer ≥1). On this machine the local default of 1 is the cap (D4).

**`_litellm()`** (`functools.cache`): always sets `LITELLM_LOCAL_MODEL_COST_MAP=True` and `LITELLM_TELEMETRY=False` (offline wins over a user value), imports litellm, sets `telemetry=False`, `drop_params=False` (a silently dropped `temperature` would break determinism), `suppress_debug_info=True`, `success_callback=[]`, `failure_callback=[]`, logger `LiteLLM`/`httpx` to WARNING. Every call passes `num_retries=0` (we own retries) and `timeout=(connect 10, read spec)` semantics via `timeout=`.

**Request construction (common):** `temperature=TEMPERATURE` (taken from the `temperature` argument base passes; assert `== 0`), `max_tokens=max_tokens_for(task, messages)`: fixed per task (grouping 2048, verifier 256, vision 1024, metadata 1024, agent 2048) except **cleanup = min(4096, 2 × estimated prompt tokens + 256)**, so a 1,500-token block is not cut (estimate = chars / 3.5; module constants, not config). A reply with `finish_reason == "length"` (Ollama `done_reason`, Anthropic `max_tokens`) raises a non-retriable `ProviderError("response truncated at max_tokens=…")`, is never cached and is logged with `truncated=true` (`LLMCallLog.truncated`), `api_key`, `api_base`, `seed=0` where supported (ollama `options.seed`, openai `seed`). Ollama extras: `num_ctx=8192` (Ollama's default 4096 silently truncates long prompts, a faithfulness hazard) and `keep_alive="10m"`. `num_ctx` does reach Ollama as `options.num_ctx` (verified on the wire); the earlier silent truncation came from prompts *larger* than `num_ctx`, where Ollama reports `prompt_eval_count` far below the real size (an ~8.4k-token prompt gave 4098). The guard is therefore: raise `ProviderError("prompt truncated …")` before any request when the estimate exceeds `num_ctx`, and after a reply when `prompt_eval_count >= num_ctx` or `< 0.8 ×` the estimate (non-retriable, never cached; the caller falls back per module 5's rejection rule). **Revision 2026-10-30:** the `< 0.8 ×` estimate test applies only when `prompt_cannot_exceed_ctx(messages)` is false (see "Truncation guard revision" below).

**Chat:** messages → `[{"role","content"}]`. `json_schema` handling by `spec.schema_mode`:
- `native`: `response_format={"type":"json_schema","json_schema":{"name":"out","schema":schema,"strict":False}}` (strict False: module schemas are not guaranteed OpenAI-strict-compliant).
- `prompt`: append to the system message (or add one) `"Reply with ONLY a JSON value valid against this JSON Schema, no prose, no code fence:\n<canonical schema>"`. The same suffix is **also** added in native mode for Ollama models that ignore `format` (cheap, deterministic); so both modes end with identical validation.
- Output pass: `_unfence(text)` strips one leading/trailing ```` ```json ```` fence only (deterministic, applied before validation; the cached text is the unfenced text). Empty text → `ProviderError`.
- **Invalid-output policy (decided):** `_chat_raw` validates with `self._validate`; on `ProviderOutputError` it makes **one** corrective re-ask (history + the bad reply as `assistant` + a `user` message: `"That reply was invalid: <error>. Reply with only valid JSON matching the schema."`), summing tokens into one `RawChat`. The second reply is returned and `BaseProvider` validates again and raises `ProviderOutputError` (never cached, one log line `ok=False`). Never more than 2 model calls. Transport retries (below) are a separate loop and never apply to validation failures.

**Vision:** `messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":"data:image/png;base64,<b64>"}}]}]`, MIME sniffed from magic bytes (PNG/JPEG/GIF/WEBP; else `ProviderError`). LiteLLM translates this per backend (Ollama `images[]`, Anthropic `image` block, OpenAI `image_url`) (D2). `json_schema` follows the chat rules including the one corrective re-ask (the re-ask re-sends the image).

**Embed:** texts split into batches of 64 → `litellm.embedding(model=embed_id, input=batch, ...)`; results re-ordered by `index`; concatenated; `RawEmbed(vectors, prompt_tokens=sum(usage.prompt_tokens))`. Count, finiteness, equal dimension are enforced by the existing `BaseProvider._check_vectors`. `anthropic` → `ProviderError("provider 'anthropic' has no embeddings API; configure models.embeddings with ollama/openai/…")`. Ollama embed of an empty string is rejected before sending.

**Transport retries:** wrapper `_with_retries(fn)`: up to 2 retries (3 attempts) with sleeps 1 s, 4 s (`sleep` injectable) only for LiteLLM `Timeout`, `APIConnectionError`, `ServiceUnavailableError`, `InternalServerError`, `RateLimitError`, `APIError` with status ≥ 500 or 429. Exhaustion → `ProviderError(retriable=True)`. Never retried (`retriable=False`): `AuthenticationError`, `BadRequestError`, `NotFoundError` (for Ollama the message appends `run: ollama pull <model>`), `ContextWindowExceededError`, validation failures. A non-ProviderError escaping is wrapped by `BaseProvider._err`.

**Tokens:** `usage.prompt_tokens/completion_tokens` from the response; Ollama: `prompt_eval_count`/`eval_count` (LiteLLM maps them to usage). If missing: estimate `ceil(len(utf8 text)/4)` for both sides, and cache entry `usage` gets `"estimated": true` (the `LLMCallLog` schema is frozen, so the flag lives only in the cache entry; the log stores the integers) (D3).

**Cache identity (`cache_namespace` override):**

| provider | namespace |
|---|---|
| `ollama` | `ollama:<model>@<digest12>` where digest comes from one `GET <host>/api/tags` per provider instance, lazily on first key computation, matching `<model>` or `<model>:latest`; on failure falls back to `ollama:<model>` and logs a warning once. A re-pulled model has a new digest, so old entries miss. |
| `vllm`/`llamacpp`/`openai_compatible` with explicit `api_base` | `<provider>:<model>@<host[:port]>` (two servers exposing the same model id do not collide) |
| `anthropic`, `openai` default base | `<provider>:<model>` (base-class default) |

The `/api/tags` GET is the only non-inference request and happens at most once per instance; "cache hit means zero network calls" is asserted on **inference** requests (everything but `/api/tags`), and the offline guard (§4) permits it because it targets `OLLAMA_HOST`.

## 3. Contract test suite (the gate)

Location `tests/providers/contract/`: `conftest.py` (backends, transport scripting), `recordings/` (JSON), `test_contract.py` (one suite). Existing `tests/providers/test_providers.py` stays untouched.

**`Backend` descriptor (conftest):** `name`, `ref`, `kind in {mock, replay, live}`, `supports_vision`, `supports_embed`, `make(tmp_path, sink) -> Provider`, `script(kind, outcome)`, `requests -> list[CapturedRequest]` (method, path, host, decoded JSON body, headers with auth redacted), `temperature_seen() -> list[float]`, `inference_count()`.

| Backend id | Transport | Enabled when |
|---|---|---|
| `mock` | spy wrapping `_chat_raw/_vision_raw/_embed_raw` (records the `temperature` argument) | always |
| `ollama-replay` | `respx` router on `http://localhost:11434` replaying `ollama_*.json` | always |
| `anthropic-replay` | `respx` on `https://api.anthropic.com`, `ANTHROPIC_API_KEY=sk-test-SECRET` via `monkeypatch` | always |
| `openai-replay` | `respx` on `https://api.openai.com` and a second param on `http://127.0.0.1:8000/v1` (vLLM-style alias) | always |
| `ollama-live` | real host | `MANUALLABOR_LIVE=1` **and** host answers **and** required models exist; else `pytest.skip("missing: run `ollama pull llama3.2:1b` ...")` listing exactly the absent models' pull commands |
| `anthropic-live`, `openai-live` | real API | env key set **and** `MANUALLABOR_LIVE_API=1` |

Live backends skip every test marked `needs_script` (failure injection). Replay scripting outcomes: `ok`, `invalid_json`, `schema_mismatch`, `ok_after_invalid` (first reply invalid, second valid), `http_500`, `http_401`, `timeout` (`httpx.ReadTimeout`), `empty`. The `sleep` hook is patched to a no-op.

**Assertions (identical for every backend; `T1` below):**

| # | Test | Assertion |
|---|---|---|
| a | chat | `ChatResult.text` non-empty string; `log.kind=="chat"` |
| b | json chat | schema `{"type":"object","required":["n"],"properties":{"n":{"type":"integer"}}}` → `parsed == {"n": 7}` (replay: scripted; live: prompt asks for it) |
| c | json invalid then valid | `ok_after_invalid` → success, exactly **2** inference requests, one log line |
| d | json invalid twice | `invalid_json` → `ProviderOutputError` (a `ProviderError`), exactly 2 requests, 1 log line with `ok=False`, nothing cached (third call re-requests) |
| e | vision | PNG fixture (`tests/fixtures/…` smallest figure, or a 64×64 generated PNG) → non-empty text; request body carries the image (Ollama `images[0]`, Anthropic `image` block `source.type=="base64"`, OpenAI `image_url` data URL), and decoding it equals the input bytes |
| f | embed | 3 texts → 3 vectors, equal dim > 0, all finite; anthropic backends instead assert `ProviderError` mentioning "no embeddings" |
| g | temperature | every captured inference request has temperature 0 (`options.temperature` for Ollama, `temperature` for Anthropic/OpenAI; mock spy for mock) |
| h | log line | exactly one `LLMCallLog` per public call; fields `task, kind, provider, model, input_hash (64 hex), latency_ms ≥ 0, cached, ok, timestamp` present; tokens int (usage or estimate) on success; `JsonlSink` line round-trips through `LLMCallLog.model_validate_json` |
| i | cache hit | same call twice with a cache: second has `cached=True`, `inference_count` unchanged, text equal; `input_hash` equal across both |
| j | failures not cached | `http_500` (3 attempts, then `ProviderError(retriable=True)`), `timeout` (same), `empty` (non-retriable): next identical call after recovery makes a request |
| k | non-retriable | `http_401` → one attempt only, `retriable=False`, message free of the key |
| l | key hygiene | replay key `sk-test-SECRET` appears in no sink line, cache file, exception string, or `caplog` text |
| m | namespace | `cache_namespace` stable across instances; changing model changes `input_hash`; Ollama replay: changing the scripted `/api/tags` digest changes `input_hash` |

**Recordings (`tests/providers/contract/recordings/`)**, hand-authored from vendor API reference shapes (small; one `*.json` each, `{"match": {"method","path"}, "status", "json"}`); live runs are the check that the shapes match reality:
`ollama_tags.json`, `ollama_chat_text.json`, `ollama_chat_json.json` (message.content `{"n": 7}`), `ollama_chat_invalid.json`, `ollama_embed.json` (`embeddings` ×3, dim 8), `anthropic_messages_text.json` (`content:[{type:text}]`, `usage.input_tokens/output_tokens`), `anthropic_messages_json.json`, `openai_chat_text.json`, `openai_chat_json.json`, `openai_embeddings.json` (`data[].index/embedding`, `usage.prompt_tokens`), `error_500.json`, `error_401_anthropic.json`, `error_401_openai.json`. The Ollama embed router matches both `/api/embed` and `/api/embeddings` (LiteLLM chooses by version) and returns the matching shape.

## 4. Offline guarantee

Rule: with every task on `ollama` or `mock`, the only outbound connections are to `OLLAMA_HOST`.

**Test T4 (subprocess, cold litellm so import-time egress is covered).** Parent starts a loopback `http.server` stub (thread, random port) serving canned `/api/tags`, `/api/chat`, `/api/embed`. It spawns `python -I -m tests.providers.offline_child` with env `OLLAMA_HOST=127.0.0.1:<port>`, `MANUALLABOR_STUB_PORT`. The child's first act is `install_guard(allowed={("127.0.0.1", port)})`, which monkeypatches `socket.getaddrinfo`, `socket.socket.connect`, `socket.socket.connect_ex`, `socket.create_connection` to append `(host, port)` to a `violations` list and raise `OSError("offline guard")` for any destination other than the allowed one (DNS lookups of non-allowed names count as violations). Then it imports `manuallabor.providers`, builds a `ProviderSet` from a config with all five tasks on `ollama` (plus `mock` for one), runs chat, json chat, vision, embed, and a repeated chat (cache hit), and prints `{"violations": [...], "calls": n}`. Parent asserts `violations == []` and that the stub saw only expected paths. **Negative control (same child, flag):** an `anthropic` provider under the same guard records a violation, proving the guard bites (assert on the list, not the exception, because LiteLLM rewraps connect errors).

**Static guard T5:** an AST scan asserts that only `manuallabor/providers/**`, `manuallabor/server*` (module 7) import `httpx`, `requests`, `urllib.request`, `aiohttp`, or `socket`; any other package doing so fails the test (names the file).

**Third-party telemetry (2026-10-30).** A library can phone home without going through a provider. onnxruntime 1.31 (RapidOCR's runtime) starts Microsoft 1DS telemetry on macOS and Linux at import: it writes a device id and an event database under `~/Library/Application Support/Microsoft/DeveloperTools/.onnxruntime/` and uploads from a background thread; its exit-time teardown also hung spawned render workers (design 01 section 11.1). Its Python call `onnxruntime.disable_telemetry_events()` only mutes events after the provider has started (checked: the store is still created); the environment variable `ORT_DISABLE_TELEMETRY` (truthy: `1`, `true`, `yes`, `on`, `y`) stops the provider from starting at all (onnxruntime `core/platform/telemetry_environment.h`, `IsTelemetryDisabledByEnvironment`). So `manuallabor/__init__.py` calls `telemetry.disable_library_telemetry()`, which sets `ORT_DISABLE_TELEMETRY=1` unconditionally (a user value of `0` cannot turn it back on) and, when onnxruntime is already imported, also calls `disable_telemetry_events()`. It runs before any submodule can import onnxruntime; the OCR pool initializer and `_rapid_engine` call it again. LiteLLM's telemetry and cost-map fetch are off in `litellm_provider.py`; Hugging Face is offline under `MANUALLABOR_OFFLINE=1`. Tests: `tests/providers/test_library_telemetry.py` (with `HOME` pointed at a temporary folder and the CI variables removed, a bare `import onnxruntime` creates the store, the control, and `import manuallabor, onnxruntime` creates nothing; a user `0` is overridden; a spawned pool worker has it set without inheriting it).

## 5. Hardware probe

`labor probe [PROJECT] [--json] [--apply small|medium|large|api] [--force]` (the `--write` flag in the brief is replaced by `--apply`: nothing is written to `models` without an explicit tier). Without `PROJECT`: print only, write nothing. With `PROJECT`: always writes `<project>/probe.json` (`ProbeResult`, `dump_json` rules) for the UI model panel (SPEC §7.1); `--apply` additionally rewrites `<project>/project.json` `models` (read → set the five TaskModels (+ metadata/agent left to fall back) → `ProjectConfig.model_validate` → atomic write; all other keys untouched). `--apply` refuses a tier whose required models do not fit in `effective_model_memory_gb` unless `--force`, and prints (never runs) every missing `ollama pull`. `labor` never installs anything.

### 5.1 `ProbeResult` (contracts/probe.py)

`schema_version "1.0"`, `probed_at` (UTC, injected clock), `platform {system, machine}`, `cpu {model, cores_physical, cores_logical}`, `ram_gb` (1 dp), `gpu: GpuInfo | None {vendor: nvidia|amd|apple|none, name, vram_gb: float|None, unified: bool}`, `effective_model_memory_gb` (the number all rules use), `disk_free_gb` + `disk_path` (project dir or CWD), `ollama {installed, version, host, reachable, models: [{name, size_gb, digest}]}`, `litellm_version | None` (via `importlib.metadata`, no import), `notes: list[str]` (why a detector was skipped).

`effective_model_memory_gb`: NVIDIA/AMD = max single-GPU VRAM; Apple = `ram_gb × 0.66` if RAM ≤ 36 else `× 0.75` (Metal working-set cap); CPU-only = `ram_gb × 0.5`.

### 5.2 Detectors (each `run(cmd, timeout=3.0) -> str | None`; `Runner` is an injectable callable so tests pass canned output; `subprocess.run(..., capture_output, text, timeout)`, never `shell=True`, `FileNotFoundError`/timeout/non-zero → `None` + a note)

| Platform | Commands / sources |
|---|---|
| macOS | `sysctl -n machdep.cpu.brand_string`, `sysctl -n hw.memsize`, `sysctl -n hw.physicalcpu`, `sysctl -n hw.logicalcpu`; optional `system_profiler SPDisplaysDataType -json` (GPU core count, chip name; timeout 8 s; failure is a note, not an error). Apple Silicon is `gpu.vendor="apple", unified=True, vram_gb=None`. |
| Linux | `/proc/cpuinfo` (`model name`), `/proc/meminfo` (`MemTotal`), `os.cpu_count`; `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits` (MiB; multiple lines = multiple GPUs); `rocm-smi --showproductname --showmeminfo vram --json` (keys containing `Total Memory`, bytes); neither present → CPU-only |
| Both | `shutil.disk_usage(path).free`; Ollama: `shutil.which("ollama")` + `ollama --version`, `GET <OLLAMA_HOST>/api/tags` (httpx, timeout 2 s) → models |
| Windows | unsupported: `platform.system()` other than Darwin/Linux yields CPU/RAM via `os`/`psutil` if importable plus a note; not gate-tested |

Pure parsers (unit-tested with canned strings): `parse_sysctl_macos`, `parse_system_profiler`, `parse_nvidia_smi_csv`, `parse_rocm_smi_json`, `parse_meminfo`, `parse_cpuinfo`, `parse_ollama_tags`.

### 5.3 Suggestion table

`suggest(probe, catalog) -> SuggestionTable`: rows = tasks `cleanup, grouping, vision, verifier, embeddings`; columns = `small, medium, large, api`. Each cell `TierOption {provider, model, approx_gb, fits: bool, speed_class, est_tokens_per_s, pull_command | None, present: bool}`.

| Rule | Definition |
|---|---|
| `fits` | `approx_gb + 1.5 × (tasks sharing that model counted once) ≤ effective_model_memory_gb − headroom`, headroom = 3 GB for Apple/CPU (OS + Docling process), 1 GB for discrete GPU |
| default tier | `api` when not even the small tier fits (e.g. an 8 GB machine), with `SuggestionTable.default_reason` saying why; otherwise the highest tier where **all** five tasks fit, capped by disk (`sum(missing model sizes) ≤ disk_free_gb − 5`); never above `small` when `effective_model_memory_gb < 14` |
| `est_tokens_per_s` | `0.5 × bandwidth_gbps / approx_gb`, bandwidth by class: CPU-only 40; Apple base 100 (brand contains Pro 150, Max 300, Ultra 600; unknown Apple 100); discrete GPU 300; labelled `~`, an estimate, not measured |
| `speed_class` | ≥ 30 fast · 10–30 ok · < 10 slow · does not fit `n/a` |
| `api` column | catalog rows: cleanup/grouping/vision → `anthropic` `claude-haiku-4-5`, **verifier → `claude-sonnet-4-5`** (never the cleanup model); embeddings → `openai` `text-embedding-3-small` (Anthropic has none); always `fits=true`, notes the env var needed and "data leaves the machine" |

Catalog (`probe_catalog.py`, sizes approximate; names verified at pull time, and the catalog is data so a wrong tag is a one-line fix):

| task | small | medium | large |
|---|---|---|---|
| cleanup, grouping | `llama3.2:1b` (1.3 GB) | `qwen2.5:7b` (4.7 GB) | `qwen2.5:14b` (9 GB) |
| verifier | `qwen2.5:1.5b` (1.0 GB) | `llama3.2:3b` (2.0 GB) | `qwen2.5:7b` |
| vision | `moondream` (1.7 GB) | `gemma3:4b` (3.3 GB) | `llama3.2-vision:11b` (7.8 GB) |
| embeddings | `nomic-embed-text` (0.27 GB) | `mxbai-embed-large` (0.67 GB) | `bge-m3` (1.2 GB) |
| agent | `qwen2.5:3b` (1.9 GB) | `qwen2.5:7b` | `qwen2.5:14b` |

The agent row was added 2026-10-30: `llama3.2:1b` and `qwen2.5:1.5b` cannot follow the proposal schema and `qwen2.5:3b` is the smallest that does (measured with `tests/agent/test_live.py` test 31b). Memory accounting treats the agent as a second resident group (`agent`, `vision`, `embeddings`) because it runs in its own job after the pipeline; `tier_memory_need_gb` is the larger of the pipeline group and the agent group, so the small tier still fits a 16 GB machine (pipeline 5.8 GB, agent group 5.4 GB against a 7.6 GB budget). The api column maps the agent to `claude-haiku-4-5`.

Expected on this machine (effective ≈ 10.6 GB): small default; medium shows `fits` for chat (4.7 + headroom) but `slow` class and the 3.3 GB vision is acceptable; large `fits=false`. Output: `render_table(table)` text (columns aligned, ASCII only) followed by a "Commands to run yourself" block of `ollama pull …` lines for missing models, and `--json` prints `{"probe":…, "suggestions":…}`. The `ModelRef`s written by `--apply <tier>` are `ollama` refs (or the `api` row's). **Verifier independence (review fix):** a verifier that is the cleanup model only re-reads its own output (the pipeline skipped it as `skip_same_model`). The catalog therefore never pairs them, the default `TaskModels.verifier` is `ollama:qwen2.5:1.5b`, and `TaskModels` rejects `verifier == cleanup` (provider, model, api_base) with a validation error; `--apply` output satisfies it. **`--apply` guards:** besides per-model `fits`, it refuses (without `--force`) when the tier's models together need more than the memory budget (`sum(approx_gb) + 1.5 GB`) or the missing pulls exceed free disk; the `metadata` override is reset to `null` unless `--keep-overrides`, and `agent` is written from the tier like the other tasks (kept under `--keep-overrides`). `--project` must be an existing directory. The `TaskModels` **defaults in `contracts/config.py` are not changed** by this module (the current default `gemma4:e4b-it-q4_K_M` is 9.6 GB and unsuitable here; open issue 4 asks the owner whether to flip defaults; the live gate uses `--apply small`).

## 6. Determinism and caching

Reuses `LLMCache` and `BaseProvider` as is: key = `sha256(namespace, task, kind, inputs)` with the namespace from §2; `input_hash` in the log is the key. Temperature is the module constant 0 plus `seed=0`; no config field changes it. Same request twice yields one inference request (T1i). Cached chat text is exactly what the first call returned (post-unfence), so a cached run is byte-identical. Probe output is not cached; `probe.json` is the only persisted artifact and is not an input hash of any other stage.

## 7. Learning hooks

None in this module beyond logging (`llm_calls.jsonl` already records task, model, tokens, latency, input hash for later analysis).

## 8. Models to pull for the live gate (orchestrator runs these; `ollama list` currently shows only `nomic-embed-text`)

| Model | Size | Used for |
|---|---|---|
| `llama3.2:1b` | ~1.3 GB | cleanup, grouping, verifier, metadata, json-schema live tests |
| `moondream` | ~1.7 GB | vision |
| `nomic-embed-text` | 274 MB (present) | embeddings |
| `qwen2.5:3b` | ~1.9 GB | agent (added 2026-10-30; the only small model that follows the proposal schema) |

Total new ≈ 3.0 GB of ~11 GB free; a model beyond these should not be pulled. Alternative chat model if JSON adherence of `llama3.2:1b` is poor: `qwen2.5:1.5b` (~1.0 GB). moondream does not follow `json_schema` reliably: live vision runs without a schema (T1e), and the schema path is covered on the replay backends.

## 9. Test list

| # | Test | Where / gating |
|---|---|---|
| T1 | Contract suite a-m × backends `mock, ollama-replay, anthropic-replay, openai-replay (×2 bases), [ollama-live, anthropic-live, openai-live]` | `tests/providers/contract/` |
| T2 | Registry: unknown provider → `ProviderError` naming it; missing `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` → error naming the variable, containing no key value; `vllm`/`llamacpp` without `api_base` → error; `openai_compatible` and `openai` build the same class; `normalize_ollama_host` table (`None`, `host`, `host:port`, `0.0.0.0`, `https://x/`) | `tests/providers/test_registry.py` |
| T3 | Lazy import: subprocess `python -I -c "import manuallabor.providers, manuallabor.cli, sys; assert 'litellm' not in sys.modules and 'httpx' not in sys.modules"`; `labor --help` runs without litellm; mock-only `build_provider_set` and one mock chat leave `litellm` out of `sys.modules` | `test_lazy_import.py` |
| T4 | Offline guard (subprocess + loopback stub + negative control), §4 | `test_offline.py` |
| T5 | Static network-import scan, §4 | `test_offline.py` |
| T6 | Probe parsers with canned outputs: macOS sysctl (M3 16 GB: `17179869184`), `system_profiler` JSON, `nvidia-smi` (one and two GPUs, MiB), `rocm-smi` JSON (bytes), `/proc/meminfo`, `/proc/cpuinfo`, Ollama `/api/tags`; garbage / empty / timeout → `None` plus a note, never an exception | `test_probe_parsers.py` |
| T7 | Suggestion rules: 16 GB Apple M3 → default `small`, medium chat `slow`, large `fits=false`; 64 GB Apple Max → `medium` default; 64 GB + 24 GB NVIDIA → `large` fits, headroom 1 GB; CPU-only 8 GB → small only, `n/a` speeds above; disk cap forces smaller tier; `api` column always present; deterministic output (same input, same text) | `test_probe_suggest.py` |
| T8 | `labor probe` CLI on this macOS machine (real detectors, `tmp_path` project): exit 0, table contains the five task names and "Commands to run yourself", `probe.json` validates as `ProbeResult`, `project.json` unchanged (byte compare); `--json` parses | `test_cli_probe.py` |
| T9 | `labor probe --apply small`: `project.json` models equal the small tier, other keys preserved, still a valid `ProjectConfig`; `--apply large` on the 16 GB probe fixture exits non-zero without writing unless `--force`; no subprocess ever runs `ollama pull` (assert the `Runner` log) | `test_cli_probe.py` |
| T10 | Live Ollama (`MANUALLABOR_LIVE=1`): chat with `llama3.2:1b`, vision with `moondream`, embed with `nomic-embed-text`, i.e. T1 on `ollama-live`; skip message lists the exact `ollama pull` commands for absent models | marker `live` |
| T11 | Live cleanup smoke (`MANUALLABOR_LIVE=1`): build a tmp project from the pre-parsed `clean` fixture ground truth (no parser/Docling run), cap at 10 eligible blocks (use the narrowest public entry in `cleanup/pipeline.py` or a truncated `blocks.json`), `models` from `--apply small`, `cleanup.llm="always"`, run through the real Ollama provider; assert module 5's faithfulness verify chain reports **0 violations among accepted `clean_text`**, `llm_calls.jsonl` has ≥ 1 `ollama` row, a second run is 100% `cached=True` with no inference requests | marker `live` |
| T12 | Cache namespace: Ollama digest change invalidates; two `openai_compatible` bases do not collide; digest lookup failure falls back to `ollama:<model>` with one warning | `test_registry.py` |
| T13 | Token usage: response with `usage` logs those numbers; response without usage logs `ceil(len/4)` and the cache entry has `usage.estimated == true` | contract extras |
| T14 | Concurrency: 8 threads on an Ollama provider never exceed 1 in-flight request (counter in the respx side effect); `MANUALLABOR_MAX_CONCURRENCY=2` allows 2 | `test_registry.py` |
| T15 | Truncation guard: Ollama reply with `prompt_eval_count >= num_ctx` → non-retriable `ProviderError`, not cached | contract extras |

Pytest additions: register the `live` marker in `pyproject.toml`; `-m "not live"` is the default for CI. **Do not run the full suite while implementing;** run only `tests/providers` (T3/T4 spawn one extra process of ~200 MB each; run sequentially). Gate commands for `docs/PROGRESS.md`: `uv run pytest tests/providers -q`, `uv run labor probe tests/fixtures/project-a --json` (on a copy), and `MANUALLABOR_LIVE=1 uv run pytest tests/providers -m live` after the orchestrator pulls the models.

## 10. Open issues resolved

| # | Question | Decision |
|---|---|---|
| D1 | LiteLLM vs direct HTTP for Ollama | LiteLLM (`ollama_chat/` for chat+vision, `ollama/` for embeddings). One implementation, one retry/log/redaction path. Escape hatch: if T10/T1 shows LiteLLM mangling a request we cannot fix with parameters (wrong embed endpoint, vision dropped), add `ollama_provider.py` as a ~100-line `BaseProvider` over `httpx` (`/api/chat`, `/api/embed`) and register it under `ollama`; the contract suite is unchanged, which is what makes the swap safe. |
| D2 | Vision for Ollama models | OpenAI-style `image_url` data-URL message; LiteLLM converts to Ollama `images[]`. Only vision-capable tags (moondream, gemma3, llama3.2-vision, llava, qwen2.5vl) are in the catalog; a non-vision model returns text that ignores the image (cannot be detected reliably), so `labor probe` only ever suggests vision tags. |
| D3 | Tokens without usage | `ceil(len(utf8)/4)` both sides, flagged only in the cache entry. |
| D4 | Max concurrency on 16 GB | 1 for `ollama`/`vllm`/`llamacpp` (one process-wide semaphore per endpoint); 4 for hosted APIs; env override. |
| D5 | `--write` vs `--apply` | Single `--apply <tier>` flag; no flag, no write to `models`. |
| D6 | Validation retry vs "never retry validation failures" | One corrective re-ask inside a single logged call (never transport-style retries, never more than 2 model calls). |
| D7 | Digest lookup vs "zero network on cache hit" | One `GET /api/tags` per instance (to `OLLAMA_HOST`); inference requests are zero on a hit. |
| D8 | `ProbeResult` placement | `contracts/probe.py` + schema export (forced contract addition, UI needs the type). |
| 4 | Flip `TaskModels` defaults to the small tier? | Out of scope; recommend the owner decide (touching defaults changes `schemas/` and any test asserting them). |

## 11. Changes outside `providers/` (all forced, all small)

`contracts/probe.py` (new) + `schemas_export.EXPORTED_MODELS` + regenerated `schemas/`; `contracts/config.py` `KNOWN_PROVIDERS` gains `"openai"`; `providers/base.py` `DEFAULT_FACTORIES` annotation; `providers/__init__.py` registration; `cli.py` `probe` command (replaces the stub); `ingest.py` wraps the factory call; `pyproject.toml` `live` marker (litellm and respx are already dependencies). No change to `grouping/`, `cleanup/`, `scoring/` callers.

## Truncation guard revision (2026-10-30)

**Failure mode.** In build/human-test 71 of 124 verifier calls (qwen2.5:1.5b) failed as `prompt truncated: Ollama evaluated N prompt tokens of about M`, for example 257 of 328. The prompts were 210 to 390 estimated tokens, far below `num_ctx = 8192`. The estimate is `chars / 3.5`, deliberately high so that budgets are safe; for English prose the real count is about 4 to 4.5 chars per token, so measured / estimate sat at 0.72 to 0.80 on the failures and 0.80 to 1.43 on the calls that passed. The cut-off of 0.8 sat inside the normal spread. An absolute floor such as "more than 64 tokens short" does not separate them either: the recorded shortfalls were 45 to 92 tokens, and 257 of 328 is 71 short.

**Rule.** Ollama only truncates a prompt that does not fit `num_ctx`. No tokenizer Ollama runs emits more tokens than the text has UTF-8 bytes (byte-level BPE merges bytes; SentencePiece with byte fallback falls back to one token per byte), and the chat template adds a bounded number (`OLLAMA_TEMPLATE_ALLOWANCE = 256`: role tags, BOS/EOS, a default system line). So when `utf8_bytes(all message text) + 256 < num_ctx` (`prompt_cannot_exceed_ctx`) the prompt cannot have been truncated, and the ratio test is not consulted. Above that bound the guard is unchanged: `prompt_eval_count >= num_ctx` or `< 0.8 × estimate` raises. `prompt_eval_count >= num_ctx` raises for every prompt. A message with a non-text part (an image) is never bounded this way, since its tokens are not in the text, so vision calls keep the ratio test. The model's own tokenizer is not used: Ollama has no stable tokenize endpoint, and fetching a tokenizer would be a network call (invariant 6).

**What it does not do.** It does not relax the guard where truncation is possible: the pre-request `estimate > num_ctx` refusal and the 0.8 ratio above the byte bound are unchanged, and a truncated reply is still never cached. Prompts between the byte bound (about 7.9k bytes) and the pre-request refusal still use the ratio; a false positive there remains possible for prose that tokenizes unusually well, and fails safe (the caller's fallback, nothing is cached).

Tests (`tests/providers/test_hardening.py`): `test_short_prompt_with_a_low_count_is_not_truncation` (the recorded 257-of-328 verifier prompt, rebuilt from the block's text, now succeeds and is cached), `test_short_prompt_reported_at_num_ctx_still_raises`, `test_image_prompt_keeps_the_ratio_check` (also: text at or above the bound, and multi-byte text counted in bytes), and the existing `test_prompt_eval_count_far_below_estimate_raises` (an ~8.4k-token prompt reported at 4098 still raises).
