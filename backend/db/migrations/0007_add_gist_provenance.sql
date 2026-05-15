-- Round 2 migration 0007 — Upgrade memory_gists to the provenance contract.
--
-- Purpose: bring memory_gists into compliance with the Derived Memory
-- Contract (docs/superpowers/rfcs/derived-memory-contract.md). Every
-- derived row must carry source_memory_ids, source_hashes,
-- derivation_method, confidence, review_state, storage_budget_bytes
-- (and optional source_chunk_ids).
--
-- The new columns are added as NULLABLE so existing application code
-- continues to work without modification until the derivation jobs are
-- updated. An idempotent UPDATE backfills the new columns for any row
-- where source_memory_ids IS NULL using a 1:1 mapping from existing
-- (memory_id, source_content_hash, gist_method, quality_score,
-- gist_text) values.
--
-- Constraints honoured:
--   * Touches an existing table — extra care.
--   * Idempotent: the migration_runner ignores
--     "duplicate column name" errors on ALTER TABLE ... ADD COLUMN, so
--     re-running this file is a no-op after the first apply.
--   * Backfill keyed on source_memory_ids IS NULL — re-running changes
--     nothing.
--   * NO destructive SQL: no DROP COLUMN, no DELETE.
--   * Rollback uses the table-rebuild pattern; see paired
--     0007_add_gist_provenance.rollback.sql for the required export
--     step.
--
-- Safety gate (C7):
--   1. Backup the database before applying.
--   2. migration_gate dry-run asserts no row has
--      source_memory_ids != json_array(memory_id) (no manual edits
--      before migration).
--   3. EXPORT REQUIRED before rollback: dump memory_gists to
--      0007_memory_gists.export.jsonl. The rollback file documents
--      this expectation; the migration_gate tool produces the export
--      automatically before invoking the rollback.

ALTER TABLE memory_gists ADD COLUMN source_memory_ids TEXT;
ALTER TABLE memory_gists ADD COLUMN source_hashes TEXT;
ALTER TABLE memory_gists ADD COLUMN derivation_method TEXT DEFAULT 'llm_summary';
ALTER TABLE memory_gists ADD COLUMN confidence REAL DEFAULT 0.0;
ALTER TABLE memory_gists ADD COLUMN review_state TEXT DEFAULT 'auto_generated';
ALTER TABLE memory_gists ADD COLUMN storage_budget_bytes INTEGER;
ALTER TABLE memory_gists ADD COLUMN source_chunk_ids TEXT;

UPDATE memory_gists
   SET source_memory_ids   = COALESCE(source_memory_ids,
                                      '[' || CAST(memory_id AS TEXT) || ']'),
       source_hashes       = COALESCE(source_hashes,
                                      '["' || COALESCE(source_content_hash, '') || '"]'),
       derivation_method   = COALESCE(derivation_method, COALESCE(gist_method, 'fallback')),
       confidence          = COALESCE(confidence, COALESCE(quality_score, 0.5)),
       review_state        = COALESCE(review_state, 'auto_generated'),
       storage_budget_bytes = COALESCE(storage_budget_bytes, LENGTH(gist_text))
 WHERE source_memory_ids IS NULL
    OR source_hashes IS NULL;
