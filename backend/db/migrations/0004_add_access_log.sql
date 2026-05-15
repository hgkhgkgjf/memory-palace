-- Round 2 migration 0004 — Add access_log table (L0 layer).
--
-- Purpose: persist per-memory operation events (read, write, search_hit,
-- compact) used by the forgetting engine, reflection workflow, and
-- observability dashboards. L0 is internal-only — it is never surfaced
-- through MCP tools. Retention is FIFO and driven by an explicit
-- maintenance job (never inline).
--
-- Constraints honoured (see docs/superpowers/rfcs/memory-layering-schema.md):
--   * Pure additive: a new table plus two indexes. No existing rows are
--     touched, no columns dropped, no destructive SQL.
--   * Idempotent: every object uses IF NOT EXISTS so re-running this file
--     yields zero net schema change.
--   * Rollback: see paired 0004_add_access_log.rollback.sql.
--
-- Safety gate (C7):
--   1. Backup the database before applying (e.g.
--      `cp <db>.sqlite3 <db>.sqlite3.bak` or `sqlite3 .backup`).
--   2. The migration_gate tool performs a dry-run check before applying.
--   3. Forward SQL is idempotent (CREATE TABLE/INDEX IF NOT EXISTS).
--   4. Rollback file drops the table and indexes only; access_log is a
--      pure observability surface, so no data export is required when
--      reverting in an environment that has not yet started writing to it.

CREATE TABLE IF NOT EXISTS access_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER NOT NULL,
    operation TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    context TEXT,
    metadata_json TEXT,
    FOREIGN KEY (memory_id) REFERENCES memories(id)
);

CREATE INDEX IF NOT EXISTS idx_access_log_memory_id
    ON access_log(memory_id);

CREATE INDEX IF NOT EXISTS idx_access_log_timestamp
    ON access_log(timestamp);
