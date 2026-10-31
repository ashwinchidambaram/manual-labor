"""SQL migrations of project.db. `MIGRATIONS[i]` brings `user_version` from i to i+1."""

from __future__ import annotations

_APPEND_ONLY = """
CREATE TRIGGER {t}_no_update BEFORE UPDATE ON {t}
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER {t}_no_delete BEFORE DELETE ON {t}
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
"""


def _append_only(*tables: str) -> str:
    return "".join(_APPEND_ONLY.format(t=t) for t in tables)


MIGRATION_1 = (
    """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE blobs (sha256 TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    screen TEXT NOT NULL,
    kind TEXT NOT NULL,
    target_id TEXT,
    doc_id TEXT,
    payload TEXT NOT NULL,
    example TEXT,
    before_ref TEXT REFERENCES blobs(sha256),
    after_ref TEXT REFERENCES blobs(sha256),
    learning_provenance TEXT,
    request_id TEXT UNIQUE
);
CREATE TABLE decisions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id INTEGER NOT NULL UNIQUE REFERENCES actions(id) DEFERRABLE INITIALLY DEFERRED,
    block_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    action TEXT NOT NULL,
    score REAL,
    threshold REAL NOT NULL,
    signals TEXT NOT NULL,
    edited_text TEXT,
    flag_id TEXT,
    ts TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL,
    shown_text_sha256 TEXT NOT NULL,
    faith_passed INTEGER,
    human_edit_diff TEXT,
    numbers_verified INTEGER NOT NULL DEFAULT 0,
    learning_provenance TEXT NOT NULL,
    source TEXT NOT NULL
);
CREATE INDEX decisions_block ON decisions(block_id, seq);
CREATE TABLE flags (
    n INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id TEXT NOT NULL,
    category TEXT NOT NULL,
    note TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution TEXT,
    created_action_id INTEGER NOT NULL REFERENCES actions(id) DEFERRABLE INITIALLY DEFERRED,
    resolved_action_id INTEGER REFERENCES actions(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TRIGGER flags_update BEFORE UPDATE ON flags
WHEN OLD.status <> 'open' OR NEW.status <> 'resolved' OR NEW.n <> OLD.n
  OR NEW.target_id <> OLD.target_id OR NEW.category <> OLD.category
  OR NEW.note IS NOT OLD.note OR NEW.created_at <> OLD.created_at
  OR NEW.created_action_id <> OLD.created_action_id
BEGIN SELECT RAISE(ABORT, 'flags: only open->resolved'); END;
CREATE TRIGGER flags_no_delete BEFORE DELETE ON flags
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TABLE proposals (
    n INTEGER PRIMARY KEY AUTOINCREMENT,
    flag_id INTEGER NOT NULL REFERENCES flags(n),
    target_id TEXT NOT NULL,
    round INTEGER NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_action_id INTEGER REFERENCES actions(id)
);
CREATE TABLE selection (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    body TEXT NOT NULL,
    action_id INTEGER NOT NULL REFERENCES actions(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE group_overrides (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    body TEXT NOT NULL,
    action_id INTEGER NOT NULL REFERENCES actions(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE attach_overrides (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    body TEXT NOT NULL,
    action_id INTEGER NOT NULL REFERENCES actions(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE figure_overrides (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    figure_id TEXT NOT NULL,
    bbox TEXT NOT NULL,
    action_id INTEGER NOT NULL REFERENCES actions(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE review_cursor (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    body TEXT NOT NULL,
    action_id INTEGER NOT NULL REFERENCES actions(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE threshold_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    old REAL,
    new REAL NOT NULL,
    reason TEXT NOT NULL,
    action_id INTEGER NOT NULL REFERENCES actions(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE jobs (
    n INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    plan TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    units_done INTEGER NOT NULL DEFAULT 0,
    units_total INTEGER NOT NULL DEFAULT 0,
    node TEXT,
    doc TEXT,
    message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    pid INTEGER,
    log_path TEXT,
    exit_code INTEGER,
    error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    resumed_from TEXT
);
CREATE TABLE learning_snapshots (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    parent TEXT,
    origin TEXT NOT NULL,
    source_first_action INTEGER,
    source_last_action INTEGER,
    counts TEXT NOT NULL,
    path TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX learning_one_active ON learning_snapshots(active) WHERE active = 1;
"""
    + _append_only(
        "actions", "decisions", "group_overrides", "attach_overrides", "figure_overrides"
    )
    + _append_only("threshold_history")
)

# module 10: at most one proposal per (flag, round); resume-safe ingestion of agent events
MIGRATION_2 = """
CREATE UNIQUE INDEX proposals_flag_round ON proposals(flag_id, round);
CREATE INDEX proposals_status ON proposals(status);
"""

# review F8: the job runner reads `jobs` by status every 0.5 s tick and looks a replayed request
# up by the request id its plan carries; both were full scans that parsed every plan
MIGRATION_3 = """
CREATE INDEX jobs_status ON jobs(status, n);
CREATE INDEX jobs_request ON jobs(json_extract(plan, '$.request_id'));
"""

# design 07 section 18: an enqueued pipeline run folds into an identical job at the queue's tail
# (`plan_key` is the hash it is compared on); the folded row keeps pointing at its survivor
MIGRATION_4 = """
ALTER TABLE jobs ADD COLUMN plan_key TEXT;
ALTER TABLE jobs ADD COLUMN merged_into TEXT;
CREATE INDEX jobs_merged ON jobs(merged_into) WHERE merged_into IS NOT NULL;
"""

MIGRATIONS: list[str] = [MIGRATION_1, MIGRATION_2, MIGRATION_3, MIGRATION_4]
