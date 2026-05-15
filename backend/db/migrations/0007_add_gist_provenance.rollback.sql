-- Rollback for 0007_add_gist_provenance.sql
--
-- IMPORTANT — EXPORT REQUIRED BEFORE RUNNING:
--   The migration_gate tool dumps the current memory_gists rows
--   (including the new provenance columns) to
--   `0007_memory_gists.export.jsonl` BEFORE invoking this script.
--   Manual rollback MUST perform the equivalent export first.
--
-- SQLite < 3.35 does not support ALTER TABLE ... DROP COLUMN.
-- Use the portable table-rebuild pattern:
--   1. Rename memory_gists to memory_gists_pre_0007.
--   2. Recreate memory_gists with the original (pre-0007) schema.
--   3. INSERT ... SELECT only the original columns.
--   4. DROP the rename-target.
--   5. Restore the unique index from migration 0002.

BEGIN TRANSACTION;

ALTER TABLE memory_gists RENAME TO memory_gists_pre_0007;

CREATE TABLE memory_gists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER NOT NULL,
    gist_text TEXT NOT NULL,
    source_content_hash TEXT NOT NULL,
    gist_method TEXT NOT NULL DEFAULT 'fallback',
    quality_score REAL,
    created_at DATETIME,
    FOREIGN KEY(memory_id) REFERENCES memories(id)
);

INSERT INTO memory_gists (
    id, memory_id, gist_text, source_content_hash,
    gist_method, quality_score, created_at
)
SELECT
    id, memory_id, gist_text, source_content_hash,
    gist_method, quality_score, created_at
FROM memory_gists_pre_0007;

DROP TABLE memory_gists_pre_0007;

CREATE INDEX IF NOT EXISTS idx_memory_gists_memory_id
    ON memory_gists(memory_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_gists_memory_source_hash_unique
    ON memory_gists(memory_id, source_content_hash);

DELETE FROM schema_migrations WHERE version = '0007';

COMMIT;
