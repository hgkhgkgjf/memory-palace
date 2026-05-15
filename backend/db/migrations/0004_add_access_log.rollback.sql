-- Rollback for 0004_add_access_log.sql
-- Drops the access_log table and its indexes. Safe to run multiple times.
-- This is the only surface that owns the rows; no FK from other tables
-- references access_log, so no cascading dump is required.

DROP INDEX IF EXISTS idx_access_log_timestamp;
DROP INDEX IF EXISTS idx_access_log_memory_id;
DROP TABLE IF EXISTS access_log;
DELETE FROM schema_migrations WHERE version = '0004';
