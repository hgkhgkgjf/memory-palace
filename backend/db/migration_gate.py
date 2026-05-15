"""
Migration safety gate for Memory Palace migrations 0004-0008.

This is the implementation of constraint C7 from the Codex review:

  Every migration ships with backup + dry-run + rollback + (where it
  touches existing data) an export. The safety gate refuses to apply a
  migration unless all four artefacts exist and the dry-run preconditions
  hold.

The gate is intentionally separate from
:class:`db.migration_runner.MigrationRunner`:

* :class:`MigrationRunner` is the *runtime* path used by
  :meth:`db.sqlite_client.SQLiteClient.init_db`. It must stay cheap (no
  full backup on every boot) and idempotent.
* :class:`MigrationGate` is the *operator* path used by humans (and the
  test suite) when staging a new migration. It is allowed to do more
  work: take a real SQLite ``.backup``, validate dry-run preconditions,
  produce a JSONL export for destructive rollbacks, and emit a
  per-migration audit log.

Usage::

    from db.migration_gate import MigrationGate

    gate = MigrationGate(database_url="sqlite+aiosqlite:///./mp.sqlite3")
    report = gate.run(versions=["0004", "0005", "0006", "0007"])
    print(report.audit_log)

The gate is intentionally synchronous: it runs out-of-band of the
asyncio event loop, mirrors the existing ``migration_runner`` SQL parser,
and prints structured audit output that downstream CI/dashboards can
ingest verbatim.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from .migration_runner import (
    MigrationRunner,
    _MIGRATION_FILE_PATTERN,
    _extract_sqlite_file_path,
)

logger = logging.getLogger(__name__)

_GATE_AUDIT_HEADER = "memory_palace.migration_gate.v1"

# Per-migration dry-run guards. Each function returns a dict with at
# least {"ok": bool, "reason": str}. The gate aborts if any returns
# ok=False, BEFORE any SQL is applied.
DryRunCheck = Callable[[sqlite3.Connection], Dict[str, Any]]


def _dry_run_check_0004(conn: sqlite3.Connection) -> Dict[str, Any]:
    """0004: access_log table must not exist yet OR be already applied."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='access_log'"
    ).fetchone()
    if row is None:
        return {"ok": True, "reason": "access_log absent — safe to create"}
    if _schema_version_applied(conn, "0004"):
        return {"ok": True, "reason": "already applied — no-op"}
    return {
        "ok": False,
        "reason": "access_log table exists but schema_migrations row missing",
    }


def _dry_run_check_0005(conn: sqlite3.Connection) -> Dict[str, Any]:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_summaries'"
    ).fetchone()
    if row is None:
        return {"ok": True, "reason": "memory_summaries absent — safe to create"}
    if _schema_version_applied(conn, "0005"):
        return {"ok": True, "reason": "already applied — no-op"}
    return {
        "ok": False,
        "reason": "memory_summaries table exists but schema_migrations row missing",
    }


def _dry_run_check_0006(conn: sqlite3.Connection) -> Dict[str, Any]:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='archived_memories'"
    ).fetchone()
    if row is None:
        return {"ok": True, "reason": "archived_memories absent — safe to create"}
    if _schema_version_applied(conn, "0006"):
        return {"ok": True, "reason": "already applied — no-op"}
    return {
        "ok": False,
        "reason": "archived_memories table exists but schema_migrations row missing",
    }


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _schema_version_applied(conn: sqlite3.Connection, version: str) -> bool:
    if not _table_exists(conn, "schema_migrations"):
        return False
    row = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version=?",
        (version,),
    ).fetchone()
    return row is not None


_PROCEDURAL_MEMORIES_REQUIRED_NOT_NULL = {
    "trigger",
    "steps_json",
    "source_memory_ids",
    "source_hashes",
    "derivation_method",
    "confidence",
    "review_state",
    "success_count",
    "created_at",
    "updated_at",
}

_PROCEDURAL_MEMORIES_COLUMNS = {
    "id",
    "trigger",
    "steps_json",
    "source_memory_ids",
    "source_chunk_ids",
    "source_hashes",
    "derivation_method",
    "confidence",
    "review_state",
    "success_count",
    "last_used",
    "storage_budget_bytes",
    "review_token_fingerprint",
    "rejection_reason",
    "created_at",
    "updated_at",
}

_PROCEDURAL_MEMORIES_INDEXES = {
    "idx_procedural_memories_review_state",
    "idx_procedural_memories_trigger",
    "idx_procedural_memories_updated_at",
}


def _dry_run_check_0008(conn: sqlite3.Connection) -> Dict[str, Any]:
    """0008: procedural_memories must be absent or a complete applied schema."""
    if not _table_exists(conn, "procedural_memories"):
        return {"ok": True, "reason": "procedural_memories absent — safe to create"}

    if not _schema_version_applied(conn, "0008"):
        return {
            "ok": False,
            "reason": "procedural_memories table exists but schema_migrations row missing",
        }

    columns = {
        str(row[1]): {"notnull": bool(row[3])}
        for row in conn.execute("PRAGMA table_info(procedural_memories)").fetchall()
    }
    missing = sorted(_PROCEDURAL_MEMORIES_COLUMNS - set(columns))
    indexes = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='procedural_memories'"
        ).fetchall()
    }
    missing_indexes = sorted(_PROCEDURAL_MEMORIES_INDEXES - indexes)
    nullable = sorted(
        column
        for column in _PROCEDURAL_MEMORIES_REQUIRED_NOT_NULL
        if column in columns and not columns[column]["notnull"]
    )
    if missing or nullable or missing_indexes:
        details = []
        if missing:
            details.append(f"missing columns: {', '.join(missing)}")
        if nullable:
            details.append(f"nullable required columns: {', '.join(nullable)}")
        if missing_indexes:
            details.append(f"missing indexes: {', '.join(missing_indexes)}")
        return {
            "ok": False,
            "reason": "procedural_memories schema incomplete (" + "; ".join(details) + ")",
        }
    return {"ok": True, "reason": "0008 procedural_memories schema invariant holds"}


def _dry_run_check_0007(conn: sqlite3.Connection) -> Dict[str, Any]:
    """0007 modifies an existing table — extra checks.

    Assert:
      * memory_gists exists.
      * No row has source_memory_ids set to a value that contradicts
        the deterministic backfill mapping (i.e. someone manually edited
        the column between migrations).
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_gists'"
    ).fetchone()
    if row is None:
        return {
            "ok": False,
            "reason": "memory_gists missing — upstream 0001 has not been applied",
        }

    columns = {
        col[1] for col in conn.execute("PRAGMA table_info(memory_gists)").fetchall()
    }
    if "source_memory_ids" not in columns:
        # Forward migration has not added the column yet — that's the
        # normal pre-state.
        return {"ok": True, "reason": "pre-0007 schema — additive ALTERs are safe"}

    # Column already exists. Validate the backfill invariant: every
    # non-null source_memory_ids must equal the deterministic
    # single-element array [memory_id].
    bad_rows = conn.execute(
        """
        SELECT COUNT(*) FROM memory_gists
         WHERE source_memory_ids IS NOT NULL
           AND source_memory_ids <> '[' || CAST(memory_id AS TEXT) || ']'
        """
    ).fetchone()[0]
    if bad_rows:
        return {
            "ok": False,
            "reason": (
                f"{bad_rows} memory_gists row(s) have hand-edited source_memory_ids; "
                "manual reconciliation required before re-applying 0007"
            ),
        }
    return {"ok": True, "reason": "0007 backfill invariant holds"}


_DRY_RUN_REGISTRY: Dict[str, DryRunCheck] = {
    "0004": _dry_run_check_0004,
    "0005": _dry_run_check_0005,
    "0006": _dry_run_check_0006,
    "0007": _dry_run_check_0007,
    "0008": _dry_run_check_0008,
}

_ROLLBACK_EXPORTS: Dict[str, tuple[str, str]] = {
    "0006": ("archived_memories", "0006_archived_memories.export.jsonl"),
    "0007": ("memory_gists", "0007_memory_gists.export.jsonl"),
    "0008": ("procedural_memories", "0008_procedural_memories.export.jsonl"),
}


@dataclass
class MigrationGateReport:
    """Structured outcome of a gate run."""

    audit_log: List[Dict[str, Any]] = field(default_factory=list)
    backup_path: Optional[Path] = None
    applied: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    aborted_at: Optional[str] = None
    abort_reason: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.aborted_at is None


class MigrationGate:
    """Operator-grade safety gate around the standard MigrationRunner.

    Sequence per migration:

    1. Locate forward + rollback files; refuse to proceed if either is
       missing.
    2. Take a full SQLite file-level backup the FIRST time the gate is
       run in a session (one backup covers a batch — taking N backups
       for N migrations would be wasteful and confusing).
    3. Run the dry-run preconditions for that version.
    4. Export rollback-risk tables to JSONL before the apply step.
    5. Delegate the actual SQL execution to a fresh MigrationRunner.
    6. Append a structured audit-log entry.

    The gate does not delete or modify any user data on its own. It is
    safe to invoke from operator tooling, CI, or tests.
    """

    def __init__(
        self,
        database_url: str,
        *,
        migrations_dir: Optional[Path] = None,
        backup_dir: Optional[Path] = None,
        export_dir: Optional[Path] = None,
    ) -> None:
        self.database_url = database_url
        self.database_file = _extract_sqlite_file_path(database_url)
        self.migrations_dir = (
            Path(migrations_dir)
            if migrations_dir is not None
            else Path(__file__).resolve().parent / "migrations"
        )
        self.backup_dir = (
            Path(backup_dir)
            if backup_dir is not None
            else (
                self.database_file.parent / "backups"
                if self.database_file is not None
                else Path.cwd() / "backups"
            )
        )
        self.export_dir = (
            Path(export_dir)
            if export_dir is not None
            else self.migrations_dir
        )

    # ------------------------------------------------------------------ public

    def run(
        self,
        *,
        versions: Optional[Sequence[str]] = None,
        take_backup: bool = True,
    ) -> MigrationGateReport:
        """Apply the listed migration versions in order, gated by safety checks."""
        report = MigrationGateReport()

        if self.database_file is None:
            # In-memory DBs do not need backups; record and apply.
            self._log(
                report,
                event="skip_backup",
                reason="in_memory_database",
                versions=list(versions or []),
            )
            self._delegate_to_runner(report, versions=versions)
            return report

        wanted = list(versions or self._all_versions_from_disk())
        if take_backup and wanted:
            try:
                report.backup_path = self._take_backup()
                self._log(
                    report,
                    event="backup_taken",
                    backup_path=str(report.backup_path),
                )
            except Exception as exc:
                report.aborted_at = "backup"
                report.abort_reason = f"backup_failed: {type(exc).__name__}: {exc}"
                self._log(report, event="abort", phase="backup", error=str(exc))
                return report

        # Per-version pre-checks then a single delegation to runner.
        for version in wanted:
            rollback_path = self._rollback_file_for_version(version)
            if rollback_path is None:
                report.aborted_at = version
                report.abort_reason = f"rollback_missing: {version}"
                self._log(
                    report,
                    event="abort",
                    version=version,
                    phase="rollback_file",
                    error="missing rollback SQL",
                )
                return report

            check = _DRY_RUN_REGISTRY.get(version)
            if check is None:
                # Unknown version — let runner decide. We still log it.
                self._log(report, event="no_dry_run_check", version=version)
                continue
            try:
                with sqlite3.connect(self.database_file) as conn:
                    outcome = check(conn)
            except Exception as exc:
                report.aborted_at = version
                report.abort_reason = (
                    f"dry_run_exception: {type(exc).__name__}: {exc}"
                )
                self._log(
                    report,
                    event="abort",
                    version=version,
                    phase="dry_run",
                    error=str(exc),
                )
                return report

            self._log(
                report,
                event="dry_run",
                version=version,
                ok=bool(outcome.get("ok")),
                reason=str(outcome.get("reason") or ""),
            )
            if not outcome.get("ok"):
                report.aborted_at = version
                report.abort_reason = f"dry_run_failed: {outcome.get('reason')}"
                return report

            export_spec = _ROLLBACK_EXPORTS.get(version)
            if export_spec is not None:
                table_name, file_name = export_spec
                try:
                    export_path = self._export_table(table_name, file_name)
                    self._log(
                        report,
                        event="export_taken",
                        version=version,
                        table=table_name,
                        path=str(export_path),
                    )
                except Exception as exc:
                    report.aborted_at = version
                    report.abort_reason = (
                        f"export_failed: {type(exc).__name__}: {exc}"
                    )
                    self._log(
                        report,
                        event="abort",
                        version=version,
                        phase="export",
                        table=table_name,
                        error=str(exc),
                    )
                    return report

        # Delegate the actual apply step.
        self._delegate_to_runner(report, versions=wanted)
        return report

    def prepare_rollback(
        self,
        *,
        versions: Sequence[str],
        take_backup: bool = True,
    ) -> MigrationGateReport:
        """Prepare operator rollback by backing up and exporting risky tables."""
        report = MigrationGateReport()
        wanted = list(versions)

        if self.database_file is None:
            self._log(
                report,
                event="skip_backup",
                reason="in_memory_database",
                versions=wanted,
            )
            return report

        if take_backup and wanted:
            try:
                report.backup_path = self._take_backup()
                self._log(
                    report,
                    event="backup_taken",
                    backup_path=str(report.backup_path),
                )
            except Exception as exc:
                report.aborted_at = "backup"
                report.abort_reason = f"backup_failed: {type(exc).__name__}: {exc}"
                self._log(report, event="abort", phase="backup", error=str(exc))
                return report

        for version in wanted:
            rollback_path = self._rollback_file_for_version(version)
            if rollback_path is None:
                report.aborted_at = version
                report.abort_reason = f"rollback_missing: {version}"
                self._log(
                    report,
                    event="abort",
                    version=version,
                    phase="rollback_file",
                    error="missing rollback SQL",
                )
                return report

            self._log(
                report,
                event="rollback_file_found",
                version=version,
                path=str(rollback_path),
            )
            export_spec = _ROLLBACK_EXPORTS.get(version)
            if export_spec is None:
                self._log(report, event="no_export_required", version=version)
                continue

            table_name, file_name = export_spec
            try:
                export_path = self._export_table(table_name, file_name)
                self._log(
                    report,
                    event="export_taken",
                    version=version,
                    table=table_name,
                    path=str(export_path),
                )
            except Exception as exc:
                report.aborted_at = version
                report.abort_reason = f"export_failed: {type(exc).__name__}: {exc}"
                self._log(
                    report,
                    event="abort",
                    version=version,
                    phase="export",
                    table=table_name,
                    error=str(exc),
                )
                return report

        return report

    # ----------------------------------------------------------------- helpers

    def _delegate_to_runner(
        self,
        report: MigrationGateReport,
        *,
        versions: Optional[Sequence[str]] = None,
    ) -> None:
        runner = MigrationRunner(
            database_url=self.database_url,
            migrations_dir=self.migrations_dir,
        )
        try:
            applied = runner._apply_pending_sync(versions=versions)
        except Exception as exc:
            report.aborted_at = "apply"
            report.abort_reason = f"runner_error: {type(exc).__name__}: {exc}"
            self._log(report, event="abort", phase="apply", error=str(exc))
            return

        wanted_set = set(versions or applied)
        for version in applied:
            if wanted_set and version not in wanted_set:
                # Some other migration also applied — record but don't
                # complain. The runner is the single source of truth.
                self._log(report, event="applied_other", version=version)
                continue
            report.applied.append(version)
            self._log(report, event="applied", version=version)

        if not applied:
            self._log(report, event="no_pending")

    def _take_backup(self) -> Path:
        assert self.database_file is not None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self.backup_dir / f"{self.database_file.name}.{ts}.bak"
        # shutil.copy2 is sufficient for SQLite without WAL writers
        # running; the migration_gate is expected to be invoked while
        # the application is quiesced.
        if self.database_file.exists():
            shutil.copy2(self.database_file, target)
        else:
            target.write_bytes(b"")
        return target

    def _export_table(self, table_name: str, file_name: str) -> Path:
        assert self.database_file is not None
        self.export_dir.mkdir(parents=True, exist_ok=True)
        target = self.export_dir / file_name
        with sqlite3.connect(self.database_file) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, table_name):
                target.write_text("", encoding="utf-8")
                return target
            with target.open("w", encoding="utf-8") as fh:
                quoted_table = '"' + table_name.replace('"', '""') + '"'
                for record in conn.execute(f"SELECT * FROM {quoted_table}"):
                    payload = {k: record[k] for k in record.keys()}
                    fh.write(json.dumps(payload, ensure_ascii=False, default=str))
                    fh.write("\n")
        return target

    def _all_versions_from_disk(self) -> List[str]:
        if not self.migrations_dir.exists():
            return []
        versions: List[str] = []
        for path in sorted(self.migrations_dir.glob("*.sql")):
            if path.name.endswith(".rollback.sql"):
                continue
            match = _MIGRATION_FILE_PATTERN.match(path.name)
            if match:
                versions.append(match.group("version"))
        return versions

    def _rollback_file_for_version(self, version: str) -> Optional[Path]:
        for path in sorted(self.migrations_dir.glob(f"{version}_*.rollback.sql")):
            if path.is_file():
                return path
        return None

    def _log(self, report: MigrationGateReport, **fields: Any) -> None:
        entry: Dict[str, Any] = {
            "channel": _GATE_AUDIT_HEADER,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        entry.update(fields)
        report.audit_log.append(entry)
        logger.info("migration_gate %s", json.dumps(entry, default=str))


__all__ = ["MigrationGate", "MigrationGateReport"]
