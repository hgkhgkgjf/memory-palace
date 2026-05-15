"""Tests for the cascade compression preview engine.

These tests pin the v1 invariants:

* :class:`CompressionEngine.preview_cascade` is read-only — no row in
  ``memories``, ``paths``, ``memory_gists``, ``memory_summaries``, or
  ``archived_memories`` is modified after a preview run.
* Replaceability scores fall in ``[SCORE_MIN, SCORE_MAX]`` except for
  pinned / critical rows which yield ``-inf``.
* Cascade tier selection follows the budget thresholds:

  - ``budget < mild`` → every candidate is ``exempt``.
  - ``mild <= budget < aggressive`` → candidates surface in ``mild``.
  - ``aggressive <= budget < emergency`` → candidates surface in
    ``aggressive``.
  - ``budget >= emergency`` → candidates surface in ``emergency``.

* Pinned memories (via ``pinned_memory_ids``) and critical domains
  (default ``core``) are NEVER placed in the active tier even at
  ``budget=1.0``.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from core.compression_engine import (
    AGGRESSIVE_BUDGET,
    CompressionEngine,
    CompressionPreview,
    EMERGENCY_BUDGET,
    MILD_BUDGET,
    MemoryCompressionCandidate,
    compression_preview_enabled,
)
from db.migration_runner import MigrationRunner


REPO_BACKEND = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_BACKEND / "db" / "migrations"


# --------------------------------------------------------- DB fixtures


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


def _bootstrap(db_path: Path) -> None:
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


def _seed_memories(db_path: Path, rows: List[Dict[str, Any]]) -> None:
    with sqlite3.connect(db_path) as conn:
        for row in rows:
            conn.execute(
                """
                INSERT INTO memories (
                    id, content, deprecated, migrated_to, created_at,
                    vitality_score, last_accessed_at, access_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["content"],
                    int(row.get("deprecated", 0)),
                    row.get("migrated_to"),
                    row.get("created_at"),
                    float(row.get("vitality_score", 1.0)),
                    row.get("last_accessed_at"),
                    int(row.get("access_count", 0)),
                ),
            )
        conn.commit()


def _seed_paths(db_path: Path, rows: List[Dict[str, Any]]) -> None:
    with sqlite3.connect(db_path) as conn:
        for row in rows:
            conn.execute(
                """
                INSERT INTO paths (domain, path, memory_id, priority, disclosure)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row.get("domain", "core"),
                    row["path"],
                    row["memory_id"],
                    int(row.get("priority", 0)),
                    row.get("disclosure"),
                ),
            )
        conn.commit()


async def _prepare_db(db_path: Path) -> None:
    _bootstrap(db_path)
    runner = MigrationRunner(_sqlite_url(db_path), migrations_dir=MIGRATIONS_DIR)
    await runner.apply_pending()


def _make_session_factory(db_path: Path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_sqlite_url(db_path))
    return async_sessionmaker(engine, expire_on_commit=False)


# ----------------------------------------------------------------- helpers


def _snapshot_tables(db_path: Path) -> Dict[str, List[Tuple]]:
    """Return a per-table snapshot used to assert no-mutation invariants."""
    tables = (
        "memories",
        "paths",
        "memory_gists",
        "memory_summaries",
        "archived_memories",
    )
    snap: Dict[str, List[Tuple]] = {}
    with sqlite3.connect(db_path) as conn:
        for table in tables:
            try:
                rows = conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                snap[table] = list(rows)
            except sqlite3.OperationalError:
                snap[table] = []
    return snap


def _seed_default_corpus(db_path: Path) -> None:
    """Seed 6 memories spanning critical + ordinary domains."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(1, 7):
        rows.append(
            {
                "id": i,
                "content": f"memory body {i}",
                "created_at": (base - timedelta(days=i * 5)).isoformat(),
                "access_count": (i % 3) + 1,
            }
        )
    _seed_memories(db_path, rows)
    _seed_paths(
        db_path,
        [
            {"domain": "core", "path": "core/keep_me", "memory_id": 1, "priority": 10},
            {"domain": "notes", "path": "notes/jot_1", "memory_id": 2, "priority": 0},
            {"domain": "notes", "path": "notes/jot_2", "memory_id": 3, "priority": 0},
            {"domain": "writer", "path": "writer/draft_1", "memory_id": 4, "priority": 1},
            {"domain": "writer", "path": "writer/draft_2", "memory_id": 5, "priority": 0},
            {"domain": "notes", "path": "notes/older_1", "memory_id": 6, "priority": 0},
        ],
    )


# ------------------------------------------------------------------ tests


def test_compression_preview_enabled_defaults_false(monkeypatch) -> None:
    monkeypatch.delenv("COMPRESSION_PREVIEW_ENABLED", raising=False)
    assert compression_preview_enabled() is False

    for value in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("COMPRESSION_PREVIEW_ENABLED", value)
        assert compression_preview_enabled() is True

    for value in ("0", "false", "no", "off", "garbage", ""):
        monkeypatch.setenv("COMPRESSION_PREVIEW_ENABLED", value)
        assert compression_preview_enabled() is False


def test_engine_rejects_bad_thresholds() -> None:
    with pytest.raises(ValueError):
        CompressionEngine(session_factory=None, mild_budget=0.8, aggressive_budget=0.5)
    with pytest.raises(ValueError):
        CompressionEngine(session_factory=None, per_tier_limit=0)
    with pytest.raises(ValueError):
        CompressionEngine(session_factory=None, mild_budget=-0.1)


def test_compute_replaceability_score_bounds_and_pinned() -> None:
    engine = CompressionEngine(session_factory=None, pinned_memory_ids=[42])

    # Pinned via id → -inf
    score = engine.compute_replaceability_score({"memory_id": 42})
    assert score == -math.inf

    # Pinned via dict flag → -inf
    score = engine.compute_replaceability_score({"memory_id": 1, "pinned": True})
    assert score == -math.inf

    # Critical domain → -inf
    score = engine.compute_replaceability_score({"memory_id": 7, "domain": "core"})
    assert score == -math.inf

    # Ordinary row → finite, bounded.
    score = engine.compute_replaceability_score(
        {
            "memory_id": 9,
            "domain": "notes",
            "age_days": 100,
            "access_count": 0,
            "priority": 0,
        }
    )
    assert 0.0 <= score <= 10.0
    # And accessing it a lot should reduce the score.
    score_hot = engine.compute_replaceability_score(
        {
            "memory_id": 9,
            "domain": "notes",
            "age_days": 100,
            "access_count": 80,
            "priority": 0,
        }
    )
    assert score_hot < score


@pytest.mark.asyncio
async def test_preview_cascade_below_mild_yields_only_exempt(tmp_path: Path) -> None:
    db_path = tmp_path / "low.db"
    await _prepare_db(db_path)
    _seed_default_corpus(db_path)

    engine = CompressionEngine(_make_session_factory(db_path))
    preview = await engine.preview_cascade(budget_usage=0.2)

    assert isinstance(preview, CompressionPreview)
    assert preview.mild == []
    assert preview.aggressive == []
    assert preview.emergency == []
    # Critical-domain memories still show up under ``exempt``.
    assert any(c.domain == "core" for c in preview.exempt)


@pytest.mark.asyncio
async def test_preview_cascade_at_mild_only_mild_tier_populated(tmp_path: Path) -> None:
    db_path = tmp_path / "mild.db"
    await _prepare_db(db_path)
    _seed_default_corpus(db_path)

    engine = CompressionEngine(_make_session_factory(db_path))
    preview = await engine.preview_cascade(budget_usage=MILD_BUDGET + 0.05)

    assert any(c for c in preview.mild)
    assert preview.aggressive == []
    assert preview.emergency == []
    # All `mild` candidates must be non-critical, non-pinned.
    for c in preview.mild:
        assert c.domain != "core"
        assert c.pinned is False


@pytest.mark.asyncio
async def test_preview_cascade_at_aggressive_populates_aggressive(tmp_path: Path) -> None:
    db_path = tmp_path / "agg.db"
    await _prepare_db(db_path)
    _seed_default_corpus(db_path)

    engine = CompressionEngine(_make_session_factory(db_path))
    preview = await engine.preview_cascade(budget_usage=AGGRESSIVE_BUDGET + 0.01)

    assert preview.mild == []
    assert any(c for c in preview.aggressive)
    assert preview.emergency == []
    # The candidate set must be sorted by replaceability descending.
    scores = [c.replaceability_score for c in preview.aggressive]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_preview_cascade_at_emergency_populates_emergency(tmp_path: Path) -> None:
    db_path = tmp_path / "emerg.db"
    await _prepare_db(db_path)
    _seed_default_corpus(db_path)

    engine = CompressionEngine(_make_session_factory(db_path))
    preview = await engine.preview_cascade(budget_usage=EMERGENCY_BUDGET + 0.01)

    assert preview.mild == []
    assert preview.aggressive == []
    assert any(c for c in preview.emergency)


@pytest.mark.asyncio
async def test_preview_cascade_does_not_modify_any_row(tmp_path: Path) -> None:
    db_path = tmp_path / "ro.db"
    await _prepare_db(db_path)
    _seed_default_corpus(db_path)

    before = _snapshot_tables(db_path)
    engine = CompressionEngine(_make_session_factory(db_path))

    for usage in (0.1, 0.55, 0.9, 0.99):
        await engine.preview_cascade(budget_usage=usage)

    after = _snapshot_tables(db_path)
    assert before == after, "preview_cascade must be strictly read-only"


@pytest.mark.asyncio
async def test_preview_cascade_exempts_pinned_and_critical(tmp_path: Path) -> None:
    db_path = tmp_path / "exempt.db"
    await _prepare_db(db_path)
    _seed_default_corpus(db_path)

    # Pin memory 5 explicitly (writer domain so it would otherwise be eligible).
    engine = CompressionEngine(
        _make_session_factory(db_path),
        pinned_memory_ids=[5],
    )
    preview = await engine.preview_cascade(budget_usage=0.99)

    exempt_ids = {c.memory_id for c in preview.exempt}
    emergency_ids = {c.memory_id for c in preview.emergency}
    aggressive_ids = {c.memory_id for c in preview.aggressive}
    mild_ids = {c.memory_id for c in preview.mild}
    active_ids = emergency_ids | aggressive_ids | mild_ids

    assert 1 in exempt_ids, "core-domain memory must be exempt"
    assert 5 in exempt_ids, "pinned memory must be exempt even at high budget"
    assert 1 not in active_ids
    assert 5 not in active_ids


@pytest.mark.asyncio
async def test_preview_cascade_budget_usage_clamped(tmp_path: Path) -> None:
    db_path = tmp_path / "clamp.db"
    await _prepare_db(db_path)
    _seed_default_corpus(db_path)

    engine = CompressionEngine(_make_session_factory(db_path))
    low = await engine.preview_cascade(budget_usage=-1.5)
    high = await engine.preview_cascade(budget_usage=12.0)

    assert low.budget_usage == 0.0
    assert high.budget_usage == 1.0


@pytest.mark.asyncio
async def test_preview_cascade_per_tier_limit_truncates(tmp_path: Path) -> None:
    db_path = tmp_path / "trunc.db"
    await _prepare_db(db_path)

    # Seed 10 non-critical memories so we can verify truncation.
    rows = []
    for i in range(1, 11):
        rows.append(
            {
                "id": i,
                "content": f"m{i}",
                "created_at": "2026-01-01T00:00:00+00:00",
                "access_count": 0,
            }
        )
    _seed_memories(db_path, rows)
    _seed_paths(
        db_path,
        [
            {"domain": "notes", "path": f"notes/m{i}", "memory_id": i, "priority": 0}
            for i in range(1, 11)
        ],
    )

    engine = CompressionEngine(
        _make_session_factory(db_path),
        per_tier_limit=3,
    )
    preview = await engine.preview_cascade(budget_usage=0.9)
    assert len(preview.aggressive) == 3


@pytest.mark.asyncio
async def test_preview_cascade_to_api_serializable(tmp_path: Path) -> None:
    db_path = tmp_path / "api.db"
    await _prepare_db(db_path)
    _seed_default_corpus(db_path)

    engine = CompressionEngine(_make_session_factory(db_path))
    preview = await engine.preview_cascade(budget_usage=0.9)
    payload = preview.to_api()

    assert isinstance(payload, dict)
    assert payload["budget_usage"] == 0.9
    assert set(payload["tier_thresholds"].keys()) == {"mild", "aggressive", "emergency"}
    for tier_key in ("mild", "aggressive", "emergency", "exempt"):
        assert isinstance(payload[tier_key], list)
        for item in payload[tier_key]:
            assert "memory_id" in item
            assert "tier" in item
            assert "replaceability_score" in item


def test_memory_compression_candidate_to_api_round_trip() -> None:
    cand = MemoryCompressionCandidate(
        memory_id=7,
        replaceability_score=3.5,
        age_days=12.0,
        access_count=2,
        priority=0,
        pinned=False,
        domain="notes",
        tier="mild",
        reason="example",
    )
    data = cand.to_api()
    assert data == {
        "memory_id": 7,
        "replaceability_score": 3.5,
        "age_days": 12.0,
        "access_count": 2,
        "priority": 0,
        "pinned": False,
        "domain": "notes",
        "tier": "mild",
        "reason": "example",
    }
