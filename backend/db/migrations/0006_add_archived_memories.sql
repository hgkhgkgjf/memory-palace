-- Round 2 migration 0006 — Add archived_memories table (soft-delete surface).
--
-- Purpose: replace destructive DELETE on memories with a restorable
-- archive surface. delete_memory continues to be the MCP-facing tool,
-- but the existing /review token flow now moves rows here instead of
-- issuing a hard SQL DELETE. Restore happens through the same
-- review-token path.
--
-- Constraints honoured:
--   * Pure additive: new table plus three indexes. memories table is
--     untouched (the deprecated/migrated_to columns already handle
--     in-place version chaining).
--   * Idempotent: CREATE TABLE/INDEX IF NOT EXISTS.
--   * NO auto-delete (C2): forward migration only creates structure.
--   * Rollback: see paired 0006_add_archived_memories.rollback.sql.
--
-- Safety gate (C7):
--   1. Backup the database before applying.
--   2. migration_gate dry-run asserts table does not pre-exist.
--   3. Rollback drops the table; archived rows would be lost on
--      rollback so a Round 2 behavioural switch (delete_memory ->
--      archive) MUST export to JSONL via the application layer before
--      enabling that flow in production. This migration itself only
--      creates structure and is safe to drop.

CREATE TABLE IF NOT EXISTS archived_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_memory_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    archived_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    archive_reason TEXT NOT NULL DEFAULT 'forgetting_review',
    archived_by TEXT,
    paths_snapshot TEXT NOT NULL DEFAULT '[]',
    review_state TEXT NOT NULL DEFAULT 'human_reviewed',
    restorable_until TEXT
);

CREATE INDEX IF NOT EXISTS idx_archived_memories_original_id
    ON archived_memories(original_memory_id);

CREATE INDEX IF NOT EXISTS idx_archived_memories_archived_at
    ON archived_memories(archived_at);

CREATE INDEX IF NOT EXISTS idx_archived_memories_review_state
    ON archived_memories(review_state);
