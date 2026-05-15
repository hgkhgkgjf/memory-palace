-- Rollback for 0008_add_procedural_memories.sql
-- Drops the procedural_memories table and its indexes.
-- v1: procedural_memories is brand-new in Round 3; no cascading FK to
-- other tables. Safe to drop without export when reverting an
-- environment that has not yet promoted any drafts to human_reviewed.
-- Operators running the rollback against a production database SHOULD
-- still take a backup beforehand because the table may carry pending
-- review work that is not recorded elsewhere.

DROP INDEX IF EXISTS idx_procedural_memories_updated_at;
DROP INDEX IF EXISTS idx_procedural_memories_trigger;
DROP INDEX IF EXISTS idx_procedural_memories_review_state;
DROP TABLE IF EXISTS procedural_memories;
DELETE FROM schema_migrations WHERE version = '0008';
