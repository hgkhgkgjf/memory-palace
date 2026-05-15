-- Rollback for 0006_add_archived_memories.sql
-- Drops the archived_memories table and its indexes.
-- WARNING: if rows have been inserted, run an explicit
-- export-to-JSONL via the application layer BEFORE invoking this
-- rollback (see Round 2 archive behavioural switch).

DROP INDEX IF EXISTS idx_archived_memories_review_state;
DROP INDEX IF EXISTS idx_archived_memories_archived_at;
DROP INDEX IF EXISTS idx_archived_memories_original_id;
DROP TABLE IF EXISTS archived_memories;
DELETE FROM schema_migrations WHERE version = '0006';
