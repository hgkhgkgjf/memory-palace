-- Round 2 migration 0005 — Add memory_summaries table (L2 layer).
--
-- Purpose: persist topic-/scope-level summaries that span one or more L1
-- memories. Complements memory_gists (per-memory) by providing
-- per-topic summaries with FULL provenance per
-- docs/superpowers/rfcs/derived-memory-contract.md.
--
-- Read-only in v1: writes happen only through the internal
-- layering_engine job; no MCP write tool is added.
--
-- Provenance fields are MANDATORY for every row (constraint C3 from the
-- Codex review). Empty source_memory_ids / source_hashes are a
-- write-error, asserted at the application layer.
--
-- Constraints honoured:
--   * Pure additive: new table plus three indexes.
--   * Idempotent: CREATE TABLE/INDEX IF NOT EXISTS.
--   * Rollback: see paired 0005_add_memory_summaries.rollback.sql.
--
-- Safety gate (C7):
--   1. Backup the database before applying.
--   2. migration_gate runs a dry-run check (assert table not pre-existing
--      OR that schema_migrations row is already recorded).
--   3. Rollback drops the table; no export required because the table is
--      empty at migration time (v1 only writes via the read-only engine
--      from Round 2 onwards).

CREATE TABLE IF NOT EXISTS memory_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    scope TEXT NOT NULL,
    layer INTEGER NOT NULL DEFAULT 2,
    source_memory_ids TEXT NOT NULL,
    source_chunk_ids TEXT,
    source_hashes TEXT NOT NULL,
    derivation_method TEXT NOT NULL DEFAULT 'llm_summary',
    confidence REAL NOT NULL DEFAULT 0.0,
    review_state TEXT NOT NULL DEFAULT 'draft',
    storage_budget_bytes INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_memory_summaries_scope
    ON memory_summaries(scope);

CREATE INDEX IF NOT EXISTS idx_memory_summaries_review_state
    ON memory_summaries(review_state);

CREATE INDEX IF NOT EXISTS idx_memory_summaries_updated_at
    ON memory_summaries(updated_at);
