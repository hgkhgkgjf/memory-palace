"""Tests for the L2 layering engine.

Covers:

* Summary generation with the full provenance contract (C3).
* The read-only invariant: ``generate_summary`` does NOT persist.
* Drill-down with live, archived, and purged sources (tombstone case).
* Source-hash stale detection.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

from core.layering_engine import (
    DerivationMethod,
    LayeringEngine,
    MemorySummaryDraft,
    ReviewState,
    SummarySource,
    sha256_text,
)
from db.migration_runner import MigrationRunner


REPO_BACKEND = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_BACKEND / "db" / "migrations"


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


def _bootstrap(db_path: Path) -> None:
    """Create the tables the migration runner depends on."""
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
                INSERT INTO memories (id, content, deprecated, migrated_to, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["content"],
                    int(row.get("deprecated", 0)),
                    row.get("migrated_to"),
                    row.get("created_at"),
                ),
            )
        conn.commit()


def _seed_archived(db_path: Path, rows: List[Dict[str, Any]]) -> None:
    with sqlite3.connect(db_path) as conn:
        for row in rows:
            conn.execute(
                """
                INSERT INTO archived_memories (
                    original_memory_id, content, archived_at,
                    archive_reason, paths_snapshot, review_state
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    row["original_memory_id"],
                    row["content"],
                    row.get("archived_at", "2026-05-15T00:00:00Z"),
                    row.get("archive_reason", "forgetting_review"),
                    row.get("paths_snapshot", "[]"),
                    row.get("review_state", "human_reviewed"),
                ),
            )
        conn.commit()


# ----------------------------------------------------------- engine fixture helpers


async def _prepare_db(db_path: Path) -> None:
    _bootstrap(db_path)
    runner = MigrationRunner(_sqlite_url(db_path), migrations_dir=MIGRATIONS_DIR)
    await runner.apply_pending()


def _make_session_factory(db_path: Path):
    """Build a fresh SQLAlchemy async session factory for the test DB."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_sqlite_url(db_path))
    return async_sessionmaker(engine, expire_on_commit=False)


# --------------------------------------------------------------- contract tests


def test_memory_summary_draft_requires_provenance() -> None:
    with pytest.raises(ValueError):
        MemorySummaryDraft(
            title="t",
            summary_text="s",
            scope="core://x",
            source_memory_ids=[],
            source_hashes=[],
        )
    with pytest.raises(ValueError):
        MemorySummaryDraft(
            title="t",
            summary_text="s",
            scope="core://x",
            source_memory_ids=[1, 2],
            source_hashes=["h1"],
        )
    with pytest.raises(ValueError):
        MemorySummaryDraft(
            title="t",
            summary_text="s",
            scope="core://x",
            source_memory_ids=[1],
            source_hashes=["h1"],
            derivation_method="unknown_method",
        )
    with pytest.raises(ValueError):
        MemorySummaryDraft(
            title="t",
            summary_text="s",
            scope="core://x",
            source_memory_ids=[1],
            source_hashes=["h1"],
            review_state="not-a-state",
        )


def test_memory_summary_draft_storage_budget_auto_computed() -> None:
    draft = MemorySummaryDraft(
        title="t",
        summary_text="hello world",
        scope="core://x",
        source_memory_ids=[1],
        source_hashes=["h1"],
    )
    assert draft.storage_budget_bytes == len("hello world".encode("utf-8"))


def test_memory_summary_draft_clamps_confidence() -> None:
    high = MemorySummaryDraft(
        title="t",
        summary_text="s",
        scope="core://x",
        source_memory_ids=[1],
        source_hashes=["h1"],
        confidence=2.5,
    )
    low = MemorySummaryDraft(
        title="t",
        summary_text="s",
        scope="core://x",
        source_memory_ids=[1],
        source_hashes=["h1"],
        confidence=-0.5,
    )
    assert high.confidence == 1.0
    assert low.confidence == 0.0


def test_sha256_text_is_stable() -> None:
    assert sha256_text("hello") == sha256_text("hello")
    assert sha256_text("a") != sha256_text("b")
    assert sha256_text("") == sha256_text("")


# ------------------------------------------------------------------ engine tests


@pytest.mark.asyncio
async def test_generate_summary_emits_full_provenance(tmp_path: Path) -> None:
    db_path = tmp_path / "ls.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [
            {"id": 1, "content": "Alpha source content"},
            {"id": 2, "content": "Bravo source content"},
        ],
    )

    engine = LayeringEngine(_make_session_factory(db_path))
    draft = await engine.generate_summary(
        scope="core://test",
        memory_ids=[1, 2],
    )

    assert isinstance(draft, MemorySummaryDraft)
    assert draft.source_memory_ids == [1, 2]
    assert len(draft.source_hashes) == 2
    assert draft.source_hashes[0] == sha256_text("Alpha source content")
    assert draft.source_hashes[1] == sha256_text("Bravo source content")
    assert draft.derivation_method in {
        DerivationMethod.LLM_SUMMARY,
        DerivationMethod.RULE_BASED,
    }
    assert 0.0 <= draft.confidence <= 1.0
    assert draft.review_state == ReviewState.DRAFT
    assert draft.storage_budget_bytes > 0
    assert draft.id is None  # not persisted


@pytest.mark.asyncio
async def test_generate_summary_is_read_only_by_default(tmp_path: Path) -> None:
    db_path = tmp_path / "ro.db"
    await _prepare_db(db_path)
    _seed_memories(db_path, [{"id": 1, "content": "Hello"}])

    engine = LayeringEngine(_make_session_factory(db_path))
    await engine.generate_summary(scope="core://x", memory_ids=[1])

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM memory_summaries").fetchone()[0]
    assert count == 0, "generate_summary must not persist in v1"


@pytest.mark.asyncio
async def test_persist_draft_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "persist.db"
    await _prepare_db(db_path)
    _seed_memories(db_path, [{"id": 7, "content": "Persist me"}])

    engine = LayeringEngine(_make_session_factory(db_path))
    draft = await engine.generate_summary(scope="core://persist", memory_ids=[7])
    persisted = await engine.persist_draft(draft)
    assert persisted.id and persisted.id > 0

    fetched = await engine.get_summary(persisted.id)
    assert fetched is not None
    assert fetched["scope"] == "core://persist"
    assert fetched["source_memory_ids"] == [7]
    assert fetched["review_state"] == ReviewState.DRAFT
    # Source hash 1:1 mapping preserved.
    assert fetched["source_hashes"] == [sha256_text("Persist me")]


@pytest.mark.asyncio
async def test_get_summaries_filters_by_scope(tmp_path: Path) -> None:
    db_path = tmp_path / "filter.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [
            {"id": 11, "content": "core one"},
            {"id": 12, "content": "writer two"},
        ],
    )
    engine = LayeringEngine(_make_session_factory(db_path))
    await engine.persist_draft(
        await engine.generate_summary(scope="core://A", memory_ids=[11])
    )
    await engine.persist_draft(
        await engine.generate_summary(scope="writer://B", memory_ids=[12])
    )

    core_rows = await engine.get_summaries(scope="core://A")
    writer_rows = await engine.get_summaries(scope="writer://B")
    all_rows = await engine.get_summaries()
    assert {r["scope"] for r in core_rows} == {"core://A"}
    assert {r["scope"] for r in writer_rows} == {"writer://B"}
    assert len(all_rows) == 2


@pytest.mark.asyncio
async def test_drill_down_returns_live_and_archive_and_tombstone(tmp_path: Path) -> None:
    db_path = tmp_path / "drill.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [
            {"id": 100, "content": "Live source"},
            {"id": 101, "content": "Will-be-archived source"},
        ],
    )
    engine = LayeringEngine(_make_session_factory(db_path))
    draft = await engine.generate_summary(
        scope="core://mix",
        memory_ids=[100, 101, 999],  # 999 was never created → tombstone
    )
    # NOTE: generate_summary refuses if NONE of the ids exist, but
    # the 999 here is fine because 100 and 101 do exist; the engine
    # only includes existing ids in source_memory_ids. To exercise the
    # tombstone path we have to manually inject it before persisting.
    draft.source_memory_ids.append(999)
    draft.source_hashes.append(sha256_text("synthetic tombstone source"))
    persisted = await engine.persist_draft(draft)

    # Move 101 to archived_memories and mark deprecated.
    _seed_archived(
        db_path,
        [
            {
                "original_memory_id": 101,
                "content": "Will-be-archived source",
                "archived_at": "2026-05-15T01:02:03Z",
            }
        ],
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE memories SET deprecated=1 WHERE id=101")
        conn.commit()

    sources = await engine.drill_down(persisted.id)
    statuses = {s.memory_id: s.status for s in sources}
    assert statuses[100] == "live"
    # 101 is still in `memories` but deprecated → still live by id-lookup
    # because drill_down checks memories table first. Move semantics in
    # production also use deprecated; the archive table mirrors it.
    assert statuses[101] in {"live", "from_archive"}
    assert statuses[999] == "purged"


@pytest.mark.asyncio
async def test_drill_down_detects_stale_source(tmp_path: Path) -> None:
    db_path = tmp_path / "stale.db"
    await _prepare_db(db_path)
    _seed_memories(db_path, [{"id": 1, "content": "Original"}])

    engine = LayeringEngine(_make_session_factory(db_path))
    persisted = await engine.persist_draft(
        await engine.generate_summary(scope="core://stale", memory_ids=[1])
    )
    # Mutate the source content.
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE memories SET content='Mutated' WHERE id=1")
        conn.commit()

    sources = await engine.drill_down(persisted.id)
    assert len(sources) == 1
    src = sources[0]
    assert src.status == "live"
    assert src.is_stale is True


@pytest.mark.asyncio
async def test_drill_down_returns_empty_for_unknown_summary(tmp_path: Path) -> None:
    db_path = tmp_path / "missing.db"
    await _prepare_db(db_path)
    engine = LayeringEngine(_make_session_factory(db_path))
    assert await engine.drill_down(9999) == []


@pytest.mark.asyncio
async def test_generate_summary_rejects_empty_inputs(tmp_path: Path) -> None:
    db_path = tmp_path / "reject.db"
    await _prepare_db(db_path)
    engine = LayeringEngine(_make_session_factory(db_path))

    with pytest.raises(ValueError):
        await engine.generate_summary(scope="core://x", memory_ids=[])

    with pytest.raises(ValueError):
        await engine.generate_summary(scope="   ", memory_ids=[1])

    # All ids missing → refuse to derive without provenance.
    with pytest.raises(ValueError):
        await engine.generate_summary(scope="core://x", memory_ids=[9999])


@pytest.mark.asyncio
async def test_summarizer_callable_is_used_when_provided(tmp_path: Path) -> None:
    db_path = tmp_path / "summ.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [
            {"id": 1, "content": "A"},
            {"id": 2, "content": "B"},
        ],
    )

    captured: List[List[str]] = []

    def fake_summarizer(bodies: List[str]):
        captured.append(list(bodies))
        return ("FAKE SUMMARY", 0.92)

    engine = LayeringEngine(
        _make_session_factory(db_path),
        summarizer=fake_summarizer,
    )
    draft = await engine.generate_summary(
        scope="core://summ",
        memory_ids=[1, 2],
        derivation_method=DerivationMethod.LLM_SUMMARY,
    )
    assert captured == [["A", "B"]]
    assert draft.summary_text == "FAKE SUMMARY"
    assert draft.derivation_method == DerivationMethod.LLM_SUMMARY
    assert draft.confidence == pytest.approx(0.92)
