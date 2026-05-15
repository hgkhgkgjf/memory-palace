-- Round 3 migration 0008 — Add procedural_memories table (draft mode).
--
-- Purpose: persist procedural memories (recurring step-based patterns
-- learned from L1 memories) WITH the full provenance contract per
-- docs/superpowers/rfcs/derived-memory-contract.md (constraint C3).
--
-- Draft-by-default invariant (v1): every row inserted by the
-- ProceduralEngine starts at ``review_state = 'draft'``. Promoting a
-- draft to an active procedural memory requires the explicit
-- ``approve_draft(...)`` flow which sets ``review_state =
-- 'human_reviewed'``. Rejected drafts flip to ``review_state =
-- 'rejected'`` and stay queryable for audit purposes.
--
-- Provenance fields are MANDATORY for every row. The application layer
-- (backend/core/procedural_engine.py) enforces this at insert time;
-- the schema itself uses NOT NULL on source_memory_ids, source_hashes,
-- derivation_method, confidence, and review_state so a programmer
-- cannot accidentally bypass the contract via raw SQL.
--
-- Constraints honoured:
--   * Pure additive: new table plus three indexes (no ALTER on any
--     existing table).
--   * Idempotent: CREATE TABLE / INDEX IF NOT EXISTS.
--   * Rollback: see paired 0008_add_procedural_memories.rollback.sql.
--
-- Safety gate (C7):
--   1. Backup the database before applying.
--   2. migration_gate runs the standard dry-run preconditions.
--   3. Rollback drops the table; no export required because the table
--      is brand-new and only carries drafts during v1.

CREATE TABLE IF NOT EXISTS procedural_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    source_memory_ids TEXT NOT NULL,
    source_chunk_ids TEXT,
    source_hashes TEXT NOT NULL,
    derivation_method TEXT NOT NULL DEFAULT 'rule_based',
    confidence REAL NOT NULL DEFAULT 0.0,
    review_state TEXT NOT NULL DEFAULT 'draft',
    success_count INTEGER NOT NULL DEFAULT 0,
    last_used TEXT,
    storage_budget_bytes INTEGER,
    review_token_fingerprint TEXT,
    rejection_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_procedural_memories_review_state
    ON procedural_memories(review_state);

CREATE INDEX IF NOT EXISTS idx_procedural_memories_trigger
    ON procedural_memories(trigger);

CREATE INDEX IF NOT EXISTS idx_procedural_memories_updated_at
    ON procedural_memories(updated_at);
