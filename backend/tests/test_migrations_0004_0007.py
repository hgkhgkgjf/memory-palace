"""Migration tests for 0004-0007.

These tests cover:

* Fresh DB boot with all migrations applied.
* Upgrade from a DB that already has 0001-0003.
* Rollback for each new migration.
* Idempotence (forward migration run twice yields zero net change).
* The migration_gate safety wrapper: backup taken, dry-run preconditions
  enforced, audit log structured.

The tests deliberately import the migration runner / migration gate
directly (no full SQLiteClient.init_db) so each migration is exercised
in isolation; one separate test then drives the full init_db path.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Dict, List

import pytest

from db.migration_gate import MigrationGate
from db.migration_runner import MigrationRunner


REPO_BACKEND = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_BACKEND / "db" / "migrations"


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


def _table_names(db_path: Path) -> List[str]:
    with sqlite3.connect(db_path) as conn:
        return sorted(
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        )


def _index_names(db_path: Path) -> List[str]:
    with sqlite3.connect(db_path) as conn:
        return sorted(
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        )


def _columns(db_path: Path, table: str) -> List[str]:
    with sqlite3.connect(db_path) as conn:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _applied_versions(db_path: Path) -> List[str]:
    with sqlite3.connect(db_path) as conn:
        return sorted(
            row[0]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        )


def _bootstrap_legacy_schema(db_path: Path) -> None:
    """Build the minimal pre-0001 schema the bootstrap migration expects.

    The production path is ``SQLiteClient.init_db`` which calls
    ``Base.metadata.create_all`` first, so the tables that migration
    0001's ``ALTER TABLE`` statements target (``memories``) and the
    later migrations target (``paths``) already exist when migrations
    run. We mirror that by creating the minimum required tables here.
    """
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                deprecated INTEGER DEFAULT 0,
                migrated_to INTEGER,
                created_at DATETIME
            );

            CREATE TABLE IF NOT EXISTS paths (
                domain TEXT NOT NULL DEFAULT 'core',
                path TEXT NOT NULL,
                memory_id INTEGER NOT NULL,
                created_at DATETIME,
                priority INTEGER DEFAULT 0,
                disclosure TEXT,
                PRIMARY KEY (domain, path)
            );

            CREATE TABLE IF NOT EXISTS memory_gists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id INTEGER NOT NULL,
                gist_text TEXT NOT NULL,
                source_content_hash TEXT,
                gist_method TEXT,
                quality_score REAL,
                created_at DATETIME
            );

            CREATE TABLE IF NOT EXISTS memory_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id INTEGER NOT NULL,
                tag_type TEXT NOT NULL,
                tag_value TEXT NOT NULL,
                confidence REAL,
                created_at DATETIME
            );
            """
        )
        conn.commit()


async def _run_pending_async(db_path: Path) -> List[str]:
    runner = MigrationRunner(_sqlite_url(db_path), migrations_dir=MIGRATIONS_DIR)
    return await runner.apply_pending()


@pytest.mark.asyncio
async def test_fresh_boot_applies_all_migrations(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    _bootstrap_legacy_schema(db_path)

    runner = MigrationRunner(_sqlite_url(db_path), migrations_dir=MIGRATIONS_DIR)
    applied = await runner.apply_pending()

    expected = ["0001", "0002", "0003", "0004", "0005", "0006", "0007", "0008"]
    assert applied == expected, f"Unexpected apply order: {applied}"
    assert _applied_versions(db_path) == expected

    tables = _table_names(db_path)
    for required in (
        "access_log",
        "memory_summaries",
        "archived_memories",
        "procedural_memories",
    ):
        assert required in tables, f"Missing table after migrations: {required}"

    gist_cols = _columns(db_path, "memory_gists")
    for required in (
        "source_memory_ids",
        "source_hashes",
        "derivation_method",
        "confidence",
        "review_state",
        "storage_budget_bytes",
        "source_chunk_ids",
    ):
        assert required in gist_cols, f"Missing provenance column on memory_gists: {required}"

    summary_cols = _columns(db_path, "memory_summaries")
    for required in (
        "source_memory_ids",
        "source_hashes",
        "derivation_method",
        "confidence",
        "review_state",
        "storage_budget_bytes",
        "scope",
        "title",
        "summary_text",
    ):
        assert required in summary_cols

    archived_cols = _columns(db_path, "archived_memories")
    for required in (
        "original_memory_id",
        "content",
        "archived_at",
        "archive_reason",
        "paths_snapshot",
        "review_state",
    ):
        assert required in archived_cols


@pytest.mark.asyncio
async def test_upgrade_from_existing_0001_0003(tmp_path: Path) -> None:
    """A DB that already has 0001-0003 must only apply 0004-0007 on the next run."""
    db_path = tmp_path / "upgrade.db"
    _bootstrap_legacy_schema(db_path)

    # Apply 0001-0003 from a sandbox migrations dir.
    sandbox_dir = tmp_path / "sandbox_migrations"
    sandbox_dir.mkdir()
    for name in (
        "0001_add_vitality_and_support_tables.sql",
        "0002_add_memory_gists_unique_index.sql",
        "0003_optimize_vitality_cleanup_candidate_indexes.sql",
    ):
        (sandbox_dir / name).write_text(
            (MIGRATIONS_DIR / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    pre_runner = MigrationRunner(_sqlite_url(db_path), migrations_dir=sandbox_dir)
    await pre_runner.apply_pending()
    assert _applied_versions(db_path) == ["0001", "0002", "0003"]

    # Now apply the real migrations dir (which contains 0004-0008 too).
    runner = MigrationRunner(_sqlite_url(db_path), migrations_dir=MIGRATIONS_DIR)
    applied = await runner.apply_pending()
    assert applied == ["0004", "0005", "0006", "0007", "0008"]
    assert _applied_versions(db_path) == [
        "0001",
        "0002",
        "0003",
        "0004",
        "0005",
        "0006",
        "0007",
        "0008",
    ]


@pytest.mark.asyncio
async def test_idempotence_run_twice(tmp_path: Path) -> None:
    db_path = tmp_path / "idem.db"
    _bootstrap_legacy_schema(db_path)
    runner = MigrationRunner(_sqlite_url(db_path), migrations_dir=MIGRATIONS_DIR)

    applied_first = await runner.apply_pending()
    applied_second = await runner.apply_pending()

    assert applied_first == [
        "0001",
        "0002",
        "0003",
        "0004",
        "0005",
        "0006",
        "0007",
        "0008",
    ]
    assert applied_second == [], "Second run should be a no-op"

    # Schema and indexes must not double up.
    tables_first = _table_names(db_path)
    indexes_first = _index_names(db_path)
    await runner.apply_pending()
    assert _table_names(db_path) == tables_first
    assert _index_names(db_path) == indexes_first


@pytest.mark.asyncio
async def test_rollback_0004_drops_access_log(tmp_path: Path) -> None:
    db_path = tmp_path / "rb4.db"
    _bootstrap_legacy_schema(db_path)
    await _run_pending_async(db_path)
    assert "access_log" in _table_names(db_path)

    rollback_sql = (MIGRATIONS_DIR / "0004_add_access_log.rollback.sql").read_text(
        encoding="utf-8"
    )
    with sqlite3.connect(db_path) as conn:
        conn.executescript(rollback_sql)
    assert "access_log" not in _table_names(db_path)
    assert "0004" not in _applied_versions(db_path)
    # Rolling back twice must be safe.
    with sqlite3.connect(db_path) as conn:
        conn.executescript(rollback_sql)
    assert "0004" not in _applied_versions(db_path)


@pytest.mark.asyncio
async def test_rollback_0005_drops_memory_summaries(tmp_path: Path) -> None:
    db_path = tmp_path / "rb5.db"
    _bootstrap_legacy_schema(db_path)
    await _run_pending_async(db_path)
    assert "memory_summaries" in _table_names(db_path)

    rollback_sql = (MIGRATIONS_DIR / "0005_add_memory_summaries.rollback.sql").read_text(
        encoding="utf-8"
    )
    with sqlite3.connect(db_path) as conn:
        conn.executescript(rollback_sql)
    assert "memory_summaries" not in _table_names(db_path)
    assert "0005" not in _applied_versions(db_path)


@pytest.mark.asyncio
async def test_rollback_0006_drops_archived_memories(tmp_path: Path) -> None:
    db_path = tmp_path / "rb6.db"
    _bootstrap_legacy_schema(db_path)
    await _run_pending_async(db_path)
    assert "archived_memories" in _table_names(db_path)

    rollback_sql = (MIGRATIONS_DIR / "0006_add_archived_memories.rollback.sql").read_text(
        encoding="utf-8"
    )
    with sqlite3.connect(db_path) as conn:
        conn.executescript(rollback_sql)
    assert "archived_memories" not in _table_names(db_path)
    assert "0006" not in _applied_versions(db_path)


@pytest.mark.asyncio
async def test_rollback_0007_rebuilds_memory_gists_to_pre_0007_schema(tmp_path: Path) -> None:
    """0007 rollback must restore the original column set via table-rebuild."""
    db_path = tmp_path / "rb7.db"
    _bootstrap_legacy_schema(db_path)
    await _run_pending_async(db_path)

    cols_after = _columns(db_path, "memory_gists")
    assert "source_memory_ids" in cols_after

    rollback_sql = (MIGRATIONS_DIR / "0007_add_gist_provenance.rollback.sql").read_text(
        encoding="utf-8"
    )
    with sqlite3.connect(db_path) as conn:
        conn.executescript(rollback_sql)

    cols_rolled = _columns(db_path, "memory_gists")
    assert "source_memory_ids" not in cols_rolled
    assert "source_hashes" not in cols_rolled
    # Original columns still present.
    for required in ("id", "memory_id", "gist_text", "source_content_hash", "gist_method"):
        assert required in cols_rolled
    assert "0007" not in _applied_versions(db_path)


@pytest.mark.asyncio
async def test_rollback_0008_drops_procedural_memories_and_schema_record(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "rb8.db"
    _bootstrap_legacy_schema(db_path)
    await _run_pending_async(db_path)
    assert "procedural_memories" in _table_names(db_path)

    rollback_sql = (
        MIGRATIONS_DIR / "0008_add_procedural_memories.rollback.sql"
    ).read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(rollback_sql)
    assert "procedural_memories" not in _table_names(db_path)
    assert "0008" not in _applied_versions(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.executescript(rollback_sql)
    assert "0008" not in _applied_versions(db_path)


@pytest.mark.asyncio
async def test_migration_gate_takes_backup_and_records_audit(tmp_path: Path) -> None:
    db_path = tmp_path / "gated.db"
    _bootstrap_legacy_schema(db_path)
    backups = tmp_path / "backups"

    gate = MigrationGate(
        _sqlite_url(db_path),
        migrations_dir=MIGRATIONS_DIR,
        backup_dir=backups,
        export_dir=tmp_path / "exports",
    )
    report = gate.run()

    assert report.ok, f"Gate aborted: {report.abort_reason} | log={report.audit_log}"
    assert report.backup_path is not None
    assert report.backup_path.exists()

    # Audit log must contain a backup_taken event and at least one applied
    # event with a known version.
    events = {entry.get("event") for entry in report.audit_log}
    assert "backup_taken" in events
    applied_events = [
        entry for entry in report.audit_log if entry.get("event") == "applied"
    ]
    versions = {entry.get("version") for entry in applied_events}
    for required in {"0004", "0005", "0006", "0007"}:
        assert required in versions

    # All migrations should be recorded.
    assert sorted(report.applied) == [
        "0001",
        "0002",
        "0003",
        "0004",
        "0005",
        "0006",
        "0007",
        "0008",
    ]


@pytest.mark.asyncio
async def test_migration_gate_handles_inmemory_database(tmp_path: Path) -> None:
    gate = MigrationGate(
        "sqlite+aiosqlite:///:memory:",
        migrations_dir=MIGRATIONS_DIR,
        backup_dir=tmp_path / "backups",
        export_dir=tmp_path / "exports",
    )
    report = gate.run()
    assert report.ok
    # In-memory DBs do not get a backup file, and the runner records
    # zero applied versions (since there is no on-disk schema_migrations
    # to track against). The gate logs the skip explicitly.
    events = {entry.get("event") for entry in report.audit_log}
    assert "skip_backup" in events


@pytest.mark.asyncio
async def test_migration_gate_export_jsonl_for_0007(tmp_path: Path) -> None:
    """Gate produces the 0007 export file before applying."""
    db_path = tmp_path / "export.db"
    _bootstrap_legacy_schema(db_path)
    export_dir = tmp_path / "exports"
    gate = MigrationGate(
        _sqlite_url(db_path),
        migrations_dir=MIGRATIONS_DIR,
        backup_dir=tmp_path / "backups",
        export_dir=export_dir,
    )
    report = gate.run()
    assert report.ok
    # Export file MUST exist after a successful run, even when empty.
    export_path = export_dir / "0007_memory_gists.export.jsonl"
    assert export_path.exists(), f"Missing export: {export_path}"


@pytest.mark.asyncio
async def test_migration_gate_targeted_version_does_not_apply_other_pending(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "targeted.db"
    _bootstrap_legacy_schema(db_path)

    sandbox_dir = tmp_path / "sandbox_migrations"
    sandbox_dir.mkdir()
    for name in (
        "0001_add_vitality_and_support_tables.sql",
        "0002_add_memory_gists_unique_index.sql",
        "0003_optimize_vitality_cleanup_candidate_indexes.sql",
    ):
        (sandbox_dir / name).write_text(
            (MIGRATIONS_DIR / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    pre_runner = MigrationRunner(_sqlite_url(db_path), migrations_dir=sandbox_dir)
    await pre_runner.apply_pending()
    assert _applied_versions(db_path) == ["0001", "0002", "0003"]

    gate = MigrationGate(
        _sqlite_url(db_path),
        migrations_dir=MIGRATIONS_DIR,
        backup_dir=tmp_path / "backups",
        export_dir=tmp_path / "exports",
    )
    report = gate.run(versions=["0004"], take_backup=False)

    assert report.ok, f"Gate aborted: {report.abort_reason} | log={report.audit_log}"
    assert report.applied == ["0004"]
    assert _applied_versions(db_path) == ["0001", "0002", "0003", "0004"]
    assert "access_log" in _table_names(db_path)
    assert "memory_summaries" not in _table_names(db_path)
    assert "archived_memories" not in _table_names(db_path)
    assert "procedural_memories" not in _table_names(db_path)


@pytest.mark.asyncio
async def test_migration_gate_rejects_preexisting_incomplete_0008_table(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "bad-0008.db"
    _bootstrap_legacy_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL,
                checksum TEXT NOT NULL
            );
            CREATE TABLE procedural_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger TEXT NOT NULL,
                review_state TEXT,
                updated_at TEXT
            );
            """
        )

    gate = MigrationGate(
        _sqlite_url(db_path),
        migrations_dir=MIGRATIONS_DIR,
        backup_dir=tmp_path / "backups",
        export_dir=tmp_path / "exports",
    )
    report = gate.run(versions=["0008"], take_backup=False)

    assert not report.ok
    assert report.aborted_at == "0008"
    assert "procedural_memories table exists" in str(report.abort_reason)
    assert "0008" not in _applied_versions(db_path)


@pytest.mark.asyncio
async def test_migration_gate_rejects_recorded_but_incomplete_0008_schema(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "bad-recorded-0008.db"
    _bootstrap_legacy_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL,
                checksum TEXT NOT NULL
            );
            INSERT INTO schema_migrations(version, applied_at, checksum)
            VALUES ('0008', '2026-01-01T00:00:00Z', 'placeholder');
            CREATE TABLE procedural_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger TEXT NOT NULL,
                review_state TEXT,
                updated_at TEXT
            );
            """
        )

    gate = MigrationGate(
        _sqlite_url(db_path),
        migrations_dir=MIGRATIONS_DIR,
        backup_dir=tmp_path / "backups",
        export_dir=tmp_path / "exports",
    )
    report = gate.run(versions=["0008"], take_backup=False)

    assert not report.ok
    assert report.aborted_at == "0008"
    assert "procedural_memories schema incomplete" in str(report.abort_reason)


@pytest.mark.asyncio
async def test_migration_gate_prepare_rollback_exports_drop_risk_tables(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "drop-risk.db"
    _bootstrap_legacy_schema(db_path)
    await _run_pending_async(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO archived_memories(original_memory_id, content, paths_snapshot)
            VALUES (1, 'archived body', '[]')
            """
        )
        conn.execute(
            """
            INSERT INTO procedural_memories(
                trigger, steps_json, source_memory_ids, source_hashes
            )
            VALUES ('repeat task', '["step"]', '[1]', '["hash"]')
            """
        )
        conn.commit()

    export_dir = tmp_path / "exports"
    gate = MigrationGate(
        _sqlite_url(db_path),
        migrations_dir=MIGRATIONS_DIR,
        backup_dir=tmp_path / "backups",
        export_dir=export_dir,
    )
    report = gate.prepare_rollback(versions=["0006", "0008"], take_backup=False)

    assert report.ok, f"Gate aborted: {report.abort_reason} | log={report.audit_log}"
    archived_export = export_dir / "0006_archived_memories.export.jsonl"
    procedural_export = export_dir / "0008_procedural_memories.export.jsonl"
    assert archived_export.exists()
    assert procedural_export.exists()

    archived_rows = [
        json.loads(line)
        for line in archived_export.read_text(encoding="utf-8").splitlines()
    ]
    procedural_rows = [
        json.loads(line)
        for line in procedural_export.read_text(encoding="utf-8").splitlines()
    ]
    assert archived_rows[0]["content"] == "archived body"
    assert procedural_rows[0]["trigger"] == "repeat task"
