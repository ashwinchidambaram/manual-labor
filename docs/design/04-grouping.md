# Module 4 design: grouping (structure view + topic view)

Inputs: SPEC §3, §4.5, §6.1, §7.1, §8, §9 · CLAUDE.md (gate 4, "silently dropping blocks", deterministic core) · `00-contracts.md` §4.4, §4.5, §4.11, §6, §10.3/§10.4/§10.16/§10.19 · `01-parse.md` §4.4 (heading level / section number), §6, §8.2 · `03-scoring.md` §1, §7 · findings.md "self-improvement from HIL feedback" · the code as it is now.
Gate: every block assigned exactly once (both views, all 6 fixtures); coverage mapping between views correct on all fixtures; cohesion computed.
Implementer: one Sonnet agent. Report anything you cannot satisfy instead of changing this design.

## 0. Measured on this machine (2026-10-29, real parse+score of clean, twocol, manual.docx; mock and Ollama `nomic-embed-text`)

| Probe | Result | Consequence |
|---|---|---|
| Heading tree in `blocks.json` | clean: 18 headings, title "Acme X200 Service Manual" is level 1 with no number, then `1.`/`1.1`… exactly as GT. twocol: 18 headings, order = GT. manual.docx: `1.`, `1.1`, `2.` (2 virtual pages). No body block starts with a section number. | §2 tree rules are sufficient. GT has no `sections` key; tests derive sections from GT heading blocks. |
| Header/footer blocks | interleaved in reading order (clean p1: title, paragraph, *header*) | excluded by type, never by position |
| Raw cosine similarity, nomic | same-section median 0.91, cross-section median 0.83, p90 0.89. Average-linkage cut at any distance 0.3–0.6 gives **1 cluster** | raw similarities from an anisotropic model carry no signal at fixed thresholds |
| Same after **centering** (subtract the doc mean, re-normalize) | nomic: same-section 0.27, cross 0.06; mock: 0.19 / −0.04. Cut at cosine distance 0.80: nomic clean 128 blocks → 9–13 clusters, max 18, top-section purity 0.94; twocol 85 → 14; mock similar sizes | §3.3: center, average linkage, cut 0.80 |
| Member → own centroid similarity (centered) | p5 0.44–0.47, median 0.64–0.66 (both models) | `T_ASSIGN = 0.30` for stragglers |
| Straggler best-centroid similarity (mock twocol) | 0.16 … 0.41 | 4 of 7 assigned at 0.30, rest `low_similarity` |
| Tiny doc (manual, 13 blocks, nomic) | all clusters < 3 blocks at 0.80 | §3.3 small-doc rule |

## 1. Package layout (`manuallabor/grouping/`)

| File | Contents (all pure unless noted) |
|---|---|
| `__init__.py` | **empty** (no re-exports), so `providers/mock.py` can import `mock_replies` without loading scipy |
| `types.py` | `GROUPING_ALGO_VERSION = "1"`, every constant in §9, `GroupingError`, internal dataclasses `SectionNode`, `Cluster`, `StragglerDecision` |
| `structure.py` | `build_structure(doc, blocks) -> StructureResult(groups, unassigned, section_of: dict[BlockId, GroupId], path_of: dict[BlockId, list[str]])` (§2) |
| `summary.py` | `block_summaries(blocks, structure) -> dict[BlockId, str]` (§3.1) |
| `embed.py` | `embed_blocks(provider, ids, texts, *, prefix, batch) -> np.ndarray` (I/O through `Provider.embed`, §3.2) |
| `cluster.py` | `center(V)`, `cluster(C, ids, params, cannot_link) -> list[list[int]]`, `cohesion(C, idx) -> float` (§3.3) |
| `label.py` | `name_topic(...)`, `review_stragglers(...)`, validators, `fallback_name(...)` (§3.4–3.5; LLM I/O) |
| `topics.py` | `build_topics(...) -> TopicResult` — orchestrates §3.1–3.6 for one doc |
| `coverage.py` | `overlap(structure, topics)`, `coverage(selected, gf) -> CoverageReport` (§4) |
| `selection.py` | selection ops, `load_selection`/`save_selection`, `scope_summary` (§5) |
| `overrides.py` | `apply_overrides(gf, overrides) -> (gf, stale)` (§7.1) |
| `learning.py` | `load_learned_grouping(paths, config) -> LearnedGrouping \| None` (§7.2) |
| `mock_replies.py` | `mock_grouping_reply(messages) -> str`; imports only stdlib + `manuallabor.ids` + `parse.text.SECTION_RE` |
| `pipeline.py` | `group_document(...)` (pure given providers), `check_partition`, `run_group(paths, only, force, providers, emit)` (I/O), fingerprint |

- CLI: `labor group <project> [--force] [--doc SLUG]`, one JSON progress line per doc, exit 1 if any doc failed.
- Paths (`project.py`): `DocPaths.groups = root/"groups.json"`, `DocPaths.group_overrides = root/"group_overrides.json"`, `ProjectPaths.selection = root/"selection.json"`.
- Mock registration: `providers/mock.py` adds `Task.grouping: mock_grouping_reply` **literally in `DEFAULT_MOCK_RESPONSES`** (import at the top of mock.py). Registering at grouping import time would change `MockProvider._replies_digest` depending on import order, so cleanup/verifier cache keys would differ between processes. `Task.embeddings` needs no reply: `MockProvider.embed` already serves every task with `hashed_embedding`.
- Dependency: add `scipy>=1.11` explicitly (already installed transitively via scikit-learn 1.9 / scipy 1.18).
- Reuse: `ids.slugify`, `ids.make_unique_slug`, `ids.UNASSIGNED`, `ids.group_id`, `ids.block_sort_key`, `parse.text.{SECTION_RE, CAPTION_RE, collapse_ws}`, `contracts.io.write_json/read_json`, `scoring.pipeline.load_scored_blocks`, `scoring.types.SCORING_ALGO_VERSION`, `parse.pipeline.stdout_emit`.

### 1.1 Contract additions (schemas + TS types regenerated; `00-contracts.md` §3/§4.4/§4.5/§4.11 updated)
| Where | Addition |
|---|---|
| `enums.py` | `UnassignedReason` = header_footer, low_similarity, no_text, topic_failed, do_not_merge · `TitleSource` = heading, llm, fallback, human |
| `group.py` | `UnassignedEntry{block_id, view: GroupView, reason: UnassignedReason}` · `GroupOverlap{topic_id, section_id, blocks: int ≥1}` · `StragglerRecord{block_id, topic_id: GroupId\|None, similarity: float (round6, −1..1), by: Literal["centroid","llm"]}` · `GroupingParams` (every constant of §9, frozen into the file) · `GroupOverride` (§7.1) · `GroupsFile` (below) |
| `selection.py` | `GroupCoverage`, `CoverageReport`, `ReviewLoad`, `ScopeSummary` (§4, §5) |
| `config.py` | `LearningConfig{enabled: bool = False}`; `ProjectConfig.learning: LearningConfig = LearningConfig()`. Module 7 extends `LearningConfig` (snapshots); this is the minimal toggle module 4 must read. |

`GroupsFile` (written to `docs/<slug>/groups.json`, `write_json`, no timestamps, no absolute paths):

| Field | Type | Notes |
|---|---|---|
| doc_id | DocSlug | |
| algo_version | str | `GROUPING_ALGO_VERSION` |
| fingerprint | Sha256Hex | §6 |
| embedding_model | str | `"<provider>:<model>"` of `config.model_for(embeddings)` |
| embedding_dim | int ≥0 | 0 when topic_status == failed |
| grouping_model | str | `"<provider>:<model>"` of `config.model_for(grouping)` |
| learning_snapshot | str | `"baseline"` or the snapshot id (§7.2) |
| params | GroupingParams | |
| structure | list[Group] | view structure, ids `s001…` in preorder |
| topics | list[Group] | `t000` (Unassigned, always present, may be empty) first, then `t001…` |
| unassigned | list[UnassignedEntry] | both views; sorted by (view, block_sort_key) |
| stragglers | list[StragglerRecord] | sorted by block id |
| overlap | list[GroupOverlap] | sorted by (topic_id, section_id); t000 included |
| title_sources | dict[GroupId, TitleSource] | every group id |
| topic_status | Literal["ok","failed"] | |
| topic_error | str \| None | non-None iff failed |
| overrides_applied | int ≥0 | |
| overrides_stale | list[int] | indexes into `group_overrides.json` that no longer apply |

`GroupsFile` validator (internal consistency only; the full partition against `blocks.json` is `check_partition`, §6): no block id twice within a view; `t000.block_ids == [u.block_id for u in unassigned if u.view == topic and u.reason != header_footer]`; structure-view entries have reason `header_footer` only; every `overlap` count equals the intersection it names.

## 2. Structure view (`structure.py`)

Input: the doc's blocks sorted by `reading_order`. "Body" = every block whose type is not header/footer.

**Header/footer:** never in a structure group; one `UnassignedEntry(view=structure, reason=header_footer)` each (00 §10.4). The same blocks get an identical entry with `view=topic` (§3.6).

**Tree nodes.** A block is a node iff `type == heading` and none of these demotion rules fires (a demoted heading is an ordinary body block of the enclosing section):

| # | Demote when | Why |
|---|---|---|
| D1 | `collapse_ws(raw_text) == ""` | Group.title needs min 1 |
| D2 | bbox is inside a figure or table block's bbox on the same page (≥ 0.8 of the heading's area) | labels inside drawings / table header cells that Docling calls `section_header` |
| D3 | `CAPTION_RE` matches raw_text | captions mislabelled as headings |

**Level of a node** (first rule that applies): (1) `section_number` set → number of components, cap 6 (the number wins over a conflicting `heading_level`); (2) `heading_level` set → it; (3) the level of the previous node, or 1 if none (siblings by default).

**Parenting:** stack-based in reading order. Pop while `stack[-1].level >= node.level`; parent = `stack[-1]` or None; push. Level jumps (1 → 3) attach to the nearest shallower node; no synthetic nodes are created. `Group.level` = depth in the tree (top-level = 1), not the raw heading level.

**Membership:** a node's group owns its heading block plus every following body block up to (not including) the next node, in reading order. Every node is a group, not only leaves: a parent's heading and its intro text before the first child need a home, and coverage for a parent is reported over its subtree (§4). Body blocks before the first node form an implicit **front matter** group (title "Front matter", slug `front-matter`, level 1, no parent) only if there is at least one such block.

**No headings at all** (after demotion): page-window groups of `PAGE_WINDOW = 10` pages: "Pages 1–10", slug `pages-001-010`, level 1, so a long scanned manual stays selectable in structure view. Window = page of the block (DOCX: virtual page).

**Group fields:** id `g-<slug>-sNNN` in preorder (= reading order of nodes; front matter first); `title = collapse_ws(heading raw_text)[:200]` including its number ("1.1 General Precautions"); `slug = make_unique_slug(slugify(title), used)` (e.g. `1-1-general-precautions`); `section_number` from the heading block; `parent_id`; `page_ranges` = the sorted distinct pages of own blocks merged into runs ([1,2,3,5] → [1–3],[5–5]); `figure_count` = own blocks of type figure; `section_ids = []`; `cohesion = None`; `title_sources[id] = heading`. DOCX: pages are virtual pages, and nothing else differs.

## 3. Topic view (`summary.py`, `embed.py`, `cluster.py`, `label.py`, `topics.py`)

### 3.1 Units and summaries
- **Topic candidates** = body blocks, minus `no_text` blocks: `collapse_ws(raw_text) == ""` and type is not figure. Those go to t000 with reason `no_text`.
- **Summary** (raw text only: grouping runs before cleanup, and topics must not move after Scope when cleanup rewrites `clean_text`):
  `"{path}\n{type}: {first SUMMARY_TOKENS=64 whitespace tokens of collapse_ws(text)}"`, where `path` = the titles of the block's structure group and its ancestors, root first, joined `" > "` (front matter / page windows: their title). For a figure, `text` = raw_text of its **bound caption** (the caption block immediately before or after it in reading order on the same page; after wins), else `""`.

### 3.2 Embeddings
- `prefix` from `EMBED_PREFIX = {"nomic-embed-text": "clustering: "}`, matched by model name with any `:tag` removed. The default is `""`. It is recorded in `params.embed_prefix`.
- Batches of `EMBED_BATCH = 32` in `block_sort_key` order → `providers.get(Task.embeddings).embed(Task.embeddings, batch)`. Caching is the provider's (LLMCache key per batch, vectors rounded to 6). No second cache.
- Validate: one vector per text, equal dims, finite, norm > 0. Failure (or `ProviderError`) → `topic_status = failed` (§3.6), with no silent fallback to another model.
- `V` = float64 matrix in `block_sort_key` order, each row L2-normalized.

### 3.3 Clustering (deterministic, no random seeds)
1. **Center**: `C = V − mean(V, axis 0)`, then L2-normalize rows. A row with norm < 1e-12 becomes `e_0`. Reason (§0): anisotropic models put every pair at 0.8–0.9 raw cosine; centering is the only thing that made one threshold work for both mock and nomic.
2. **Small doc**: `n < SMALL_DOC = 12` candidates → one cluster with everything; go to step 6. (`manual.docx` has 13 candidates, one above the threshold, so it is clustered normally and gets 3 topics; the rule is not tuned to it. Test 13 uses synthetic docs of 3, 8 and 11 blocks.)
3. `y = round(pdist(C, "cosine"), 9)`; `Z = scipy.cluster.hierarchy.linkage(y, method="average")`. The input order is `block_sort_key`, so ties resolve identically on every run on one machine (the average linkage dendrogram is unique except for ties). Exact ties are broken inside scipy's linkage and come out differently on macOS and Linux (13 orthogonal rows: one cluster on macOS, two on Linux, seen in CI 2026-10-30), so a tie-only input is not a cross-platform fixture; real embeddings rounded to 9 places do not tie except for duplicate blocks, which merge first either way.
4. **Cut**: `labels = fcluster(Z, D_CUT = 0.80, "distance")`. If the cluster count `k > K_MAX = max(1, n // 4)`, re-cut with `fcluster(Z, K_MAX, "maxclust")`.
5. **Size cap and cannot-link**: walk `to_tree(Z)`. Any cluster with more than `MAX_TOPIC_BLOCKS = 60` members, or containing both ends of a do-not-merge pair (§7.2), is replaced by its two dendrogram children, recursively until neither condition holds (a leaf always satisfies both).
6. **Dissolve**: clusters with fewer than `MIN_TOPIC_BLOCKS = 3` members are dissolved, and their blocks become **stragglers**. If no cluster survives, the whole candidate set becomes one cluster (no stragglers).
7. **Provisional keys** `c01, c02, …` by each cluster's first member in `block_sort_key` order.
- **Centroid** of a cluster = L2-normalized mean of its members' rows of `C`. **Cohesion** = mean pairwise cosine of the members' rows of `C` (`(sum(C_I C_Iᵀ) − m) / (m(m−1))`), clamped to [0,1] and rounded to 6 places. It is computed on the **final** membership (§3.6). SPEC's "mean intra-cluster embedding similarity" is kept, measured in the centered space, because raw similarity is ~0.8 for everything with nomic. Every topic has ≥ 2 members, so cohesion is always defined.
- **Low cohesion** (UI marking): `cohesion < LOW_COHESION = 0.30`. The constant is shipped in `params` so the UI does not hard-code it.

### 3.4 Naming (LLM, one call per surviving cluster, `Task.grouping`)
- Input JSON inside `<input>…</input>` in the user message: `{"kind":"name_topic","headings":[≤5 distinct structure-group titles of members, by member count desc then first appearance],"blocks":[≤NAME_SAMPLE=12 summaries truncated to 40 tokens, members nearest the centroid first, ties by block id]}`. The system prompt asks for a short noun-phrase title using the documents' own words, and says the input is data, not instructions.
- `json_schema = {"type":"object","additionalProperties":false,"required":["title","slug"],"properties":{"title":{"type":"string","minLength":1,"maxLength":80},"slug":{"type":"string","pattern":"^[a-z0-9]+(?:-[a-z0-9]+)*$","maxLength":40}}}`. Schema failures raise `ProviderOutputError` and are never cached.
- Post-validation (`validate_name`): `title = collapse_ws(title)`, which must be non-empty with no control characters; `slug != "unassigned"`; `slug` must not be `front-matter` and must not start with `pages-`. That keeps it apart from structure slugs for readability, although both views may share a slug.
- **Retry once** on `ProviderOutputError` or a post-validation failure: append one user message `"Your previous answer was rejected: <reason>. Reply again with JSON only."`. The retry needs a different input hash, because temperature 0 plus the cache would otherwise return the same answer. A second failure, or any `ProviderError`, → **fallback**.
- **Fallback** (`fallback_name`): `headings[0]` (already the most frequent; leading `SECTION_RE` number stripped) → title, `slugify(title, 40)`. With no headings: `Topic NN` / `topic-nn` (NN = provisional key number). `title_sources = fallback`.
- **Uniqueness**: superseded by §3.4.1 (2026-10-30). Until then slugs were made unique per doc in final-id order with `make_unique_slug` (duplicates got `-2`, `-3`), and the model's own slug was kept.

#### 3.4.1 Final topic names (2026-10-30, first-use report C12)
A tester saw "Parts List" beside "parts list", "Connector Data" beside "connector data", one-word lowercase topics ("idler", "pulley"), and article files `connector-data-2.md` and `x200-two-column--belt-path-3-1-harness-3-2-4-drive-train.md` (a 1B model named the topic "Belt Path" and gave an unrelated slug). The model proposes a title only; the shown title and the slug are made by `label.finalize_topic_names`, a pure function run once per document over the surviving topics in final-id order (step 5 of §3.6), after the size cap and the dissolve of small topics:

1. **Case.** `title_case`: an all-lowercase title gets a capital on each word except the joining words `a an and as at by for from in into nor of on or per the to via vs with` after the first ("removal of the belt" -> "Removal of the Belt"). A title with any capital letter was cased by its writer and is kept as written ("pH sensor", "X200 belt path", an all-capitals heading).
2. **No two alike.** A title equal, ignoring case, to an earlier topic's title in the same document gets a disambiguator that tells it apart from every earlier topic of that name, the first that applies: `section N` (the number of the structure section holding most of its blocks, ties by reading order) when theirs differ; else its page range (`page 5`, `pages 3–4`, `pages 2, 6`) when theirs differ; else `part N`, N counting the topics of that name (the first is part 1). The first topic of a name keeps it plain. Topics are not merged: merging would move blocks, and the partition is the clustering's (§3.3), not the namer's. Two topics of one name in one section and one page are told apart by `part N` and stay two rows; the reviewer can move blocks between them or rename one (§7.1).
3. **Slug from the shown title.** The slug is `slugify(base title)` cut to leave room for `-<slug of the disambiguator>` (so `connector-data-section-5`, `electrical-data-pages-2-6`, `parts-list-part-2`), never the model's slug. A slug a topic may not use (`unassigned`, `front-matter`, `pages-*`) is prefixed `topic-`; a title with nothing to slug becomes `topic-NN` (its position). `make_unique_slug` remains only as the last guard (two titles differing only in punctuation).

Deterministic: the inputs are the model's titles (temperature 0, cached), the members and the structure, all fixed for the same document and config. The rule changes slugs, and a slug is the topic's article id (design 11 §16) and the target of a move override: a project grouped before this rule keeps its `groups.json` until grouping re-runs. Amended 2026-10-30: the scoring algo bump to `"6"` (design 03 §2.10a) is in the grouping fingerprint, so the first `labor run` after upgrading re-groups every existing project and applies this rule once: topic names, slugs and article file names may change that one time (README "Upgrading"). When it re-runs, an override naming an old `-2` slug is reported in `overrides_stale`, as any renamed topic is. Tests: `tests/grouping/test_label_names.py` (case rule, each disambiguator, slug from title, banned and empty slugs, uniqueness and determinism, and `group_document` with a model that names every cluster "parts list" with an unrelated slug).

### 3.5 Stragglers
- For each straggler, the cosine of its `C` row to every surviving centroid gives the **candidates**: the top `N_CANDIDATES = 3` with similarity ≥ `T_CANDIDATE = 0.15`, ordered by similarity desc then key.
- **Deterministic default**: the best candidate if its similarity is ≥ `T_ASSIGN = 0.30`, else unassigned (`low_similarity`).
- **LLM review** (`params.llm_stragglers = True`): one call per batch of ≤ 10 stragglers that have ≥ 1 candidate, in block order. Input: `{"kind":"assign_stragglers","topics":[{"key","title"}…],"blocks":[{"block_id","text": summary,"candidates":[keys…,"unassigned"]}]}`. Schema: `{"assignments":[{"block_id": str, "topic": str}]}`, additionalProperties false.
- Validation: every batch block_id appears exactly once, no unknown ids, and each `topic` ∈ that block's candidates (`"unassigned"` included). On any failure, retry once with a rejection note; if that fails too, the defaults apply to the whole batch.
- The LLM may only choose from the fixed candidate list, never a block outside the batch and never a new topic. Each outcome is recorded in a `StragglerRecord(by = "llm" | "centroid")`.

### 3.6 Final assembly (order is part of the contract)
1. Members = cluster members + stragglers assigned to them.
2. **Caption follows figure**: a bound caption (§3.1) moves to its figure's topic (or to t000 if the figure is unassigned).
3. **Heading follows its section**: a heading block whose structure group has ≥ 1 other own body block moves to the topic holding the plurality of those blocks. Ties go to the topic of the first such block, and a t000 plurality is ignored.
4. **Do-not-merge on the final assignment** (§7.2): clustering keeps a pair apart, but a straggler or a bound heading/caption may land beside its partner. For each pair that now shares a topic, the later movable block (straggler, heading, caption) moves to its next-best topic (centroid similarity ≥ `T_CANDIDATE`) holding none of its partners; if none exists it goes to t000 with reason `do_not_merge`. Repeated until no pair shares a topic.
4a. **Size cap**: any topic with > `MAX_TOPIC_BLOCKS` members after steps 1-4 is re-split along the dendrogram of its own members (cannot-link pairs respected), or, when the tree is lopsided (a chunk < `MIN_TOPIC_BLOCKS`) or a chunk is still too big, into even consecutive chunks in reading order. Chunks are re-named like clusters. The partition invariant is unaffected.
4b. Drop topics left with < 2 members; their blocks become `low_similarity` stragglers in t000. Each such block that came from a cluster gets a `StragglerRecord(topic_id=None)` with its similarity to the cluster it left. A straggler whose final topic differs from its first decision (moved by binding, enforcement or the cap) records its similarity to the final topic. An override whose target topic is dissolved afterwards is counted in `overrides_stale`, not `overrides_applied`.
5. **Final ids** `t001…` by each topic's first block in `block_sort_key` order. Final titles and slugs (§3.4.1) are made in this order.
6. Topic `Group` fields: `level = 0`, `parent_id = None`, `section_ids` = sorted structure ids of members, `page_ranges`, `figure_count`, `cohesion` (§3.3).
7. **t000** "Unassigned blocks", slug `unassigned`, `is_unassigned = True`, `cohesion = None`; it holds `no_text` and `low_similarity` blocks. Header/footer blocks are **not** in t000; they appear only as `UnassignedEntry(view=topic, reason=header_footer)`, exactly mirroring the structure view, so t000 contains only selectable blocks.
8. **Topic failure** (embeddings failed): `topics = [t000 with every body block]`, each with reason `topic_failed`. The structure view is still written, and the doc's exit status is 1. The UI keeps working in structure view.

## 4. Coverage mapping (`coverage.py`)

Partition per view (§6): **structure** groups ⊎ header_footer = all blocks; **topic** groups (t000 included) ⊎ header_footer = all blocks. "Selectable" = body blocks. Both views therefore partition the same selectable set, which is what makes coverage exact.

- `overlap(structure, topics) -> list[GroupOverlap]`: for every (topic, structure group) pair with a non-empty own-block intersection, the count. It is computed once and stored in `groups.json`. Invariants: Σ over sections of `overlap(t, ·)` = `t.block_count`; Σ over topics of `overlap(·, s)` = `s.block_count`.
- `coverage(selected: frozenset[BlockId], gf) -> CoverageReport` for one doc:

| Model | Fields |
|---|---|
| `GroupCoverage` | `group_id`, `view`, `selected: int`, `total: int`, `fraction: Unit \| None` (`round6(selected/total)`, None iff total 0), `subtree_selected: int \| None`, `subtree_total: int \| None`, `subtree_fraction: Unit \| None` (structure only: own + all descendants; equal to own for leaves; None for topics) |
| `CoverageReport` | `doc_id`, `selected: int` (= \|S ∩ selectable(doc)\|), `selectable: int`, `structure: list[GroupCoverage]` (gf order), `topics: list[GroupCoverage]` (gf order, t000 first) |

- **Exactness / symmetry** (tested): Σ `structure[*].selected` = Σ `topics[*].selected` = `selected`; for every group `selected ≤ total`; `coverage(S)` for S = a whole topic t gives, for each section s, `selected = overlap(t, s)`, and vice versa. Ids in S that belong to another doc are ignored for this doc; header/footer ids in S are ignored and counted in the API's `dropped` (§5).
- The UI shows `fraction` (`subtree_fraction` on structure rows) in the opposite view. Numbers come from the API (module 7), which calls `coverage()`; the frontend does not recompute.

## 5. Selection and review load (`selection.py`)

- Storage: `<project>/selection.json` (`Selection`, `write_json`, atomic). Module 7 may move it into SQLite; the model stays the same. If the file is missing, `default_selection(paths)` = every selectable block of every grouped doc, `article_split = config.article_split`, `active_view = topic`. It is not written until the first user action; `labor group` never writes selection.
- Pure ops (return a new `Selection`, never mutate): `select_blocks(sel, ids)`, `deselect_blocks(sel, ids)`, `select_group(sel, group_or_id, *, subtree=False, gf=None)` / `deselect_group` (`subtree=False`: literally the group's own `block_ids`; `subtree=True`: for a structure group, its own blocks plus every descendant's, which needs `gf`). **The Scope UI uses `subtree=True` for structure rows** (selecting "1. Safety" selects the section and all its subsections) and `subtree=False` for topic rows (topics have no subtree), `set_view(sel, view)`, which changes only `active_view` and so **leaves `block_ids` byte-identical** (SPEC §7.1, §11.6), and `set_split(sel, split)`.
- `normalize(sel, blocks_by_id) -> (Selection, dropped: list[BlockId])` removes unknown ids (a removed doc) and header/footer ids. It runs on load and before every save.
- `scope_summary(sel, groups: Mapping[slug, GroupsFile], blocks: Mapping[slug, list[Block]]) -> ScopeSummary`, with blocks from `load_scored_blocks`:

| Field | Definition |
|---|---|
| `docs` | docs with ≥ 1 selected block |
| `articles_per_topic` | Σ over docs of the topic groups (t000 included → article `<doc>--unassigned`) with ≥ 1 selected block |
| `articles_per_document` | = `docs` |
| `articles` | the one matching `sel.article_split` |
| `blocks` | \|S\| after normalize |
| `figures` | selected blocks with `type == figure` |
| `pages` | distinct (doc, page) pairs of selected blocks (DOCX: virtual pages) |
| `review_load: ReviewLoad` | `queued` = \|{b ∈ S : b.status == queued}\|; `numeric_queued` = those with `has_numeric_spec`; `threshold` = `config.threshold` |

`status` is the one `load_scored_blocks` returns: machine status now, the human overlay once module 7 exists. Because a threshold change restates `scores.json` (03 §6), the estimate follows the slider. It is a pre-cleanup estimate; module 5 re-scores selected blocks, and the label says "estimated".
- **Articles in `per_topic` mode come from the topic view**, whatever `active_view` is. The structure view is a selection lens. Module 11 builds one article per topic (and `<doc>--unassigned` for selected t000 blocks), with ids `<docslug>--<topic-slug>` (SPEC §6.1).

## 6. Pipeline, determinism, persistence (`pipeline.py`)

Per doc, in slug order:
1. `blocks = load_scored_blocks(paths, slug)` (fails clearly if not scored); `doc = paths.load_document(slug)`; overrides; learned state (§7).
2. Fingerprint `sha256(canonical_json({algo: GROUPING_ALGO_VERSION, scoring_algo: SCORING_ALGO_VERSION, document_sha, blocks_sha, params, embeddings_ref, grouping_ref, overrides_sha|None, learning_snapshot}))`. `scores.json` *content* is deliberately excluded: grouping reads raw text only, so post-cleanup re-scores must not invalidate it. The scoring algo version is included so that a scoring algorithm change forces a re-run.
3. Skip (`status: skip`) if `groups.json` exists, parses, and has the same algo_version and fingerprint, unless `--force`.
4. `group_document(doc, blocks, providers, params, overrides, learned) -> GroupsFile`. It is pure apart from provider calls, which are sequential so the call-log order is deterministic.
5. `check_partition(blocks, gf)` → list of problems: per view, every block id from `blocks.json` exactly once across groups ∪ header_footer entries; no unknown ids; t000 consistent; header/footer types ↔ header_footer entries; every non-t000 topic has ≥ 2 blocks and cohesion in [0,1]. Any problem → `GroupingError`; **nothing is written** and the doc fails.
6. `write_json(dp.groups, gf)`. Progress line: `{"doc","stage":"group","status","structure_groups","topics","unassigned","low_cohesion","stragglers","llm_fallbacks","elapsed_ms","detail"}`.
- Providers: same construction as `run_score` (cache `paths.root/".llm_cache"`, `JsonlSink(paths.root/"llm_calls.jsonl")`, or injected `ProviderSet`).
- Stage order: `parse → figures → score → group`. Module 7's stage graph treats `groups.json` as stale when the fingerprint changes.

**Determinism**

| Scope | Guarantee |
|---|---|
| MockProvider (any process, any machine) | `groups.json` byte-identical: hashed embeddings, canned replies, numpy float64 + rounding of distances to 9 places, `block_sort_key` input order, no sets iterated, no timestamps |
| Real models, same project (cache present) | byte-identical: embeddings and chat replies come from the LLM cache keyed by input hash |
| Real models, cold cache / other machine | **not** guaranteed: GPU/CPU kernels and model updates (`:latest`) change low-order bits, and a near-tie in the dendrogram can flip. `embedding_model`, `embedding_dim`, `grouping_model`, `params` are recorded so a difference can be explained. Module 6 should add the model digest to `cache_namespace`. |
| Across embedding models | different topics by design; partition and coverage invariants still hold |

Budget (LLM/embedding time excluded): 3,000 blocks < 5 s (pdist 4.5 M distances + average linkage ≈ 1 s; 36 MB).

## 7. Human overrides and learning hooks

### 7.1 Overrides (decisions, always applied)
`docs/<slug>/group_overrides.json` = `list[GroupOverride]`, appended by module 7 (Scope edits, accepted agent-pass regroup proposals). `GroupOverride{seq: int, kind: Literal["move","rename"], block_id: BlockId|None, to_topic_slug: TopicSlug|None, title: str|None, topic_slug: TopicSlug|None}`. `move` puts a block into the topic with that slug, or t000 for `unassigned`. `rename` sets a topic's title (its slug never changes, so article ids stay stable). They are applied in `seq` order after §3.6 and before final ids. A target slug that no longer exists makes the override **stale**: it is listed in `overrides_stale`, never applied silently, and the block keeps its machine topic. A rename sets `title_sources[topic] = human`; a moved block that was a straggler drops its `StragglerRecord`. Overrides are part of the fingerprint. They are not "learning", so they apply even when `learning.enabled` is false.

### 7.2 Learning (`learning.py`, read only when `config.learning.enabled`)
- `LearnedGrouping{snapshot: str, examples: list[RegroupExample], do_not_merge: list[tuple[BlockId, BlockId]]}`; `RegroupExample{doc_id, summary: str, from_title: str, to_title: str, kind: "move"|"rename"}`. Module 7 derives it from captured decisions into its versioned `learning/` snapshot layer and owns the writer and the layout. Module 4 reads only through `load_learned_grouping(paths, config)`, which returns `None` when learning is off, when no snapshot exists, or before module 7 lands.
- **Use**: up to 3 examples (same doc first, then most recent `seq`) appended as `"examples"` to the naming and straggler `<input>` JSON. `do_not_merge` pairs act as cannot-link constraints in §3.3 step 5. Neither use can bypass validation: the LLM still picks from the fixed candidate list, and the partition check still runs.
- **Provenance**: `GroupsFile.learning_snapshot` = the snapshot id, or `"baseline"` when learning is off (even if learned state exists on disk). It is in the fingerprint, so toggling learning re-runs grouping, and resetting to baseline reproduces the baseline output byte-for-byte (with MockProvider). The baseline (constants, prompts, empty example set) is never edited by learning.

## 8. Test list (`tests/grouping/`)

Fixtures: lift `figproj_scoring`/`scoredproj`/`scored_copy` from `tests/scoring/conftest.py` into `tests/conftest.py` (one Docling parse per session, shared). Synthetic unit tests use the `make_block` helper (also lifted). `gt_blocks(name)` builds contract Blocks from `tests/fixtures/ground_truth/<name>.json` (ids from page/per-page order) for tests that need no parser. Every pipeline test uses `mock_providers`.

| # | Test | Fixture | Assertion |
|---|---|---|---|
| 1 | partition, structure | all 6 (`scoredproj`) | every block id exactly once across structure groups ∪ header_footer entries; header/footer types ⇔ entries |
| 2 | partition, topic | all 6 | same over topics (t000 included) ∪ header_footer; t000 has no header/footer |
| 3 | `check_partition` catches defects | synthetic GroupsFile with a dropped / duplicated / foreign id | each returns a problem; `run_group` writes nothing and exits 1 |
| 4 | structure vs GT | clean, twocol, tables, figures | node section_numbers (and the clean title) in GT heading order; parent of `n.m` = `n`; each group's `page_ranges` = pages of the GT blocks from its heading to the next GT heading (header/footer excluded) |
| 5 | structure, scanned | scanned | same section_number sequence as clean (OCR headings) |
| 6 | DOCX virtual pages | manual | s001 `1. Overview` [1–1], s002 `1.1 Required Items` parent s001, s003 `2. Maintenance` [2–2]; level 1/2/1 |
| 7 | front matter | synthetic: 2 paragraphs then heading | s001 "Front matter" holds both; no front matter when the doc starts with a heading |
| 8 | repair: number beats level, jumps, no-level | synthetic: `2.1` with heading_level 1; levels 1→3; heading without level | level 2; 3 attaches to 1 with depth 2; no-level heading is sibling of previous |
| 9 | repair: demotion D1–D3 | synthetic heading inside a table bbox, empty heading, "Figure 3. …" heading | not nodes; counted in enclosing group |
| 10 | no headings → page windows | synthetic 25 pages, no headings | 3 groups `pages-001-010`, `pages-011-020`, `pages-021-025` |
| 11 | topics, mock | all 6 | every non-t000 topic has ≥ 2 blocks, cohesion ∈ [0,1]; no empty topics; `section_ids`/`page_ranges`/`figure_count` match members |
| 12 | clustering core | synthetic vectors: 3 tight groups + 2 outliers | 3 clusters; outliers become stragglers; result unchanged when input rows are permuted then re-sorted by id |
| 13 | small doc / separated groups / ties | synthetic docs of 3, 8, 11 blocks (< `SMALL_DOC`); 5 orthogonal blocks; 13 blocks in groups of 5, 4, 4 with distinct distances; 13 orthogonal blocks (all distances equal) | one topic with all candidates; no crash on n ∈ {0,1,2}; the three groups; the tie case is a deterministic partition, not a fixed shape (see §3.3 step 3) |
| 14 | size cap + cannot-link | synthetic 130 near-identical vectors; a do-not-merge pair inside one cluster | every topic ≤ 60; the pair ends in different topics |
| 15 | straggler rule | synthetic straggler with best sim 0.31 / 0.29 / 0.10 | assigned / `low_similarity` (candidate shown) / no candidates, LLM not called |
| 16 | straggler LLM validation | canned replies: unknown topic, block missing, extra block, valid non-default candidate | invalid → retry once (different input hash) → defaults; valid → applied with `by=llm` |
| 17 | naming validation | canned replies: not JSON, title 81 chars, slug `../x`, slug `Unassigned`, slug `unassigned`, empty title after collapse | each → one retry then fallback name from headings; `title_sources = fallback`; 2 calls logged |
| 18 | duplicate slugs | canned reply always `{"title":"Belts","slug":"belts"}` | slugs `belts`, `belts-2`, … unique; no retries |
| 19 | caption / heading binding | synthetic figure+caption split by clustering; heading clustered away from its section | caption joins the figure's topic; heading joins its section's plurality |
| 20 | coverage sum property | each fixture, S = random seeded subsets (Hypothesis, 50 examples) | Σ structure selected = Σ topic selected = \|S ∩ selectable\|; selected ≤ total |
| 21 | coverage symmetry | each fixture, S = each topic in turn, then each section | coverage per opposite group = `overlap` entry; overlap row/column sums = block counts |
| 22 | subtree coverage | clean, S = all of section 2.x | `2. Drive Assembly` subtree_fraction 1.0, own fraction 1.0, `1.` 0.0 |
| 23 | selection persists across toggle | model level | `set_view` twice → `block_ids` and JSON bytes unchanged; save → load round-trip equal |
| 24 | normalize | selection with a header id, an unknown-doc id | both dropped and reported |
| 25 | review load | clean (`scoredproj`), S = all; S = one topic | `queued` = count of selected blocks with status queued, recomputed directly from `load_scored_blocks` (85 for all of clean today); `numeric_queued` ≤ queued; changes when threshold restated |
| 26 | scope summary | clean+figures, mixed selection | articles per_topic / per_document, figures, pages counted as defined in §5 |
| 27 | `labor group` idempotent + `--force` | `scored_copy` | second run `status: skip`, file untouched (mtime and bytes); `--force` rewrites identical bytes |
| 28 | byte-identical across processes | `scored_copy` ×2 | two `subprocess` runs of `uv run labor group` → identical `groups.json` |
| 29 | fingerprint invalidation | `scored_copy` | changing blocks.json, the embeddings ModelRef, an override, or `learning.enabled` → re-run; re-scoring with a new threshold → skip |
| 30 | fully mocked run | `build_provider_set` with all-mock config and **no** canned responses | completes all 6 docs, no `ProviderError`; `llm_calls.jsonl` has `grouping` and `embeddings` entries |
| 31 | mock digest stable | fresh interpreter with/without importing `manuallabor.grouping.pipeline` | `MockProvider.cache_namespace` equal |
| 32 | topic failure | embeddings provider raising `ProviderError` | groups.json written with structure view, t000 = all body blocks `topic_failed`, partition holds, exit 1 |
| 33 | overrides | move to existing slug; move to vanished slug; rename | applied / listed stale and not applied / title changed, slug unchanged |
| 34 | learning off = baseline | learned state present, `learning.enabled = False` | `learning_snapshot == "baseline"`, bytes equal to a run with no learned state |
| 35 | performance | synthetic 3,000 blocks, mock | `group_document` < 5 s |
| 36 | live (skips unless `MANUALLABOR_LIVE=1` and Ollama answers with `nomic-embed-text`) | `gt_blocks("clean")`, `gt_blocks("twocol")`; test-local `OllamaEmbedTestProvider(BaseProvider)` (urllib `/api/embed`) until module 6 provides the real one; grouping chat = mock | partition invariant holds; every cohesion ∈ [0,1]; 3 ≤ topics ≤ n/4 |

## 9. Constants (`types.py`, single source, copied into `GroupingParams`)
`SUMMARY_TOKENS=64`, `NAME_SAMPLE=12`, `NAME_TOKENS=40`, `EMBED_BATCH=32`, `EMBED_PREFIX={"nomic-embed-text":"clustering: "}`, `SMALL_DOC=12`, `D_CUT=0.80`, `K_MAX=n//4`, `MIN_TOPIC_BLOCKS=3`, `MAX_TOPIC_BLOCKS=60`, `T_ASSIGN=0.30`, `T_CANDIDATE=0.15`, `N_CANDIDATES=3`, `STRAGGLER_BATCH=10`, `LOW_COHESION=0.30`, `PAGE_WINDOW=10`, `TITLE_MAX=80`, `TOPIC_SLUG_MAX=40`, `llm_stragglers=True`.

## 10. Open issues (each resolved with a choice)
1. **Topics across documents** conflict with article ids `<docslug>--<topic-slug>` → per-document topics in v1 (00 §10.3). Cross-doc topics are deferred, and the overlap/coverage models are already per doc.
2. **"One group per leaf section"** vs. parent headings with intro text → one group per heading node (own blocks); parents report subtree coverage. A leaf-only view loses blocks or misattributes them.
3. **Unassigned in structure view**: the contract allows `is_unassigned` only for t000 → header/footer accounting lives in `GroupsFile.unassigned` for both views, and t000 holds only selectable blocks. This needs the §1.1 contract additions.
4. **Fixed similarity thresholds don't transfer between models** (§0) → centered embeddings plus thresholds on centered cosine. Cohesion is reported in the centered space, and the definition is stated in the UI tooltip.
5. **How big a topic can be** → ≤ 60 blocks (dendrogram split), k ≤ n/4, ≥ 2 blocks after assembly.
6. **Doc with no headings** → structure page windows of 10 pages; the topic view is unchanged.
7. **Which view drives articles** → per_topic split uses topics; a `per_section` split would be a later `ArticleSplit` addition (contract change, not v1).
8. **Summaries from raw, not clean** → topics never move after Scope because of cleanup.
9. **LLM retry under temperature 0 + cache** → the retry message carries the rejection note, so it has a new input hash.
10. **No Ollama provider until module 6** → the live test uses a test-local embed provider; it is replaced, not kept, once module 6 registers `ollama`.
11. **LLM call volume** → about n/10 naming calls + ⌈stragglers/10⌉ review calls per doc, sequential, as one background job (module 7). The UI shows the structure view as soon as `groups.json` exists. The topic view is never partial, because the file is written once.
