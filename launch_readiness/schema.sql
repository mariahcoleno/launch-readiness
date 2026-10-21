-- Launch readiness tracker schema (SQLite).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS launches (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    model_version TEXT NOT NULL,
    target_date   TEXT,                       -- ISO date, YYYY-MM-DD
    stage         TEXT NOT NULL
                  CHECK (stage IN ('internal', 'trusted_testers', 'limited_ga', 'ga')),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per surface or capability that is ON for a launch.
CREATE TABLE IF NOT EXISTS launch_features (
    launch_id INTEGER NOT NULL REFERENCES launches(id) ON DELETE CASCADE,
    kind      TEXT NOT NULL CHECK (kind IN ('surface', 'capability')),
    name      TEXT NOT NULL,
    PRIMARY KEY (launch_id, kind, name),
    CHECK (
        (kind = 'surface' AND name IN ('api', 'consumer_app', 'enterprise'))
        OR (kind = 'capability' AND name IN
            ('tool_use', 'code_execution', 'web_browsing', 'file_uploads', 'memory'))
    )
);

-- Gates for a launch. Gates that are no longer required are marked with
-- removed_at instead of being deleted, so their history stays visible.
-- A waived gate must say why and who approved it; other gates carry neither.
CREATE TABLE IF NOT EXISTS gates (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    launch_id        INTEGER NOT NULL REFERENCES launches(id) ON DELETE CASCADE,
    gate_key         TEXT NOT NULL,           -- id from gate_rules.yaml
    name             TEXT NOT NULL,
    team             TEXT NOT NULL,
    owner            TEXT,
    status           TEXT NOT NULL DEFAULT 'not_started'
                     CHECK (status IN ('not_started', 'in_progress', 'passed', 'failed', 'waived')),
    due_date         TEXT,                    -- ISO date, YYYY-MM-DD
    notes            TEXT,
    waiver_rationale TEXT,
    waived_by        TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    removed_at       TEXT,                    -- set when the gate stops being required
    UNIQUE (launch_id, gate_key),
    CHECK (
        (status = 'waived'
            AND length(trim(coalesce(waiver_rationale, ''))) > 0
            AND length(trim(coalesce(waived_by, ''))) > 0)
        OR (status <> 'waived' AND waiver_rationale IS NULL AND waived_by IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS decisions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    launch_id   INTEGER NOT NULL REFERENCES launches(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('go', 'no_go', 'scope_change')),
    decided_by  TEXT NOT NULL,
    decided_on  TEXT NOT NULL,                -- ISO date, YYYY-MM-DD
    rationale   TEXT NOT NULL CHECK (length(trim(rationale)) > 0),
    follow_up   TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_gates_launch ON gates(launch_id);
CREATE INDEX IF NOT EXISTS idx_decisions_launch ON decisions(launch_id);
