-- Rollback for 0005_add_memory_summaries.sql
-- Drops the memory_summaries table and its indexes.
-- v1: memory_summaries is brand-new in Round 2; no cascading FK to
-- other tables. Safe to drop without export when reverting an
-- environment that has not yet started populating it.

DROP INDEX IF EXISTS idx_memory_summaries_updated_at;
DROP INDEX IF EXISTS idx_memory_summaries_review_state;
DROP INDEX IF EXISTS idx_memory_summaries_scope;
DROP TABLE IF EXISTS memory_summaries;
DELETE FROM schema_migrations WHERE version = '0005';
