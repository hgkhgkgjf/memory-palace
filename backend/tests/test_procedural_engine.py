"""Tests for the procedural memory engine.

Pins the Round 3 Track B (Step B3) invariants:

* Provenance contract (C3): every extracted draft carries
  ``source_memory_ids``, ``source_hashes``, ``derivation_method``,
  ``confidence``, ``review_state``, ``storage_budget_bytes``.
* Default ``review_state`` is ``"draft"`` and the engine refuses to
  surface drafts in :meth:`recommend_for_trigger`.
* Approval flow requires a non-empty ``review_token``; rejection flow
  requires a non-empty ``reason``.
* Rejected drafts can be queried but cannot be approved.
* Increment-success only operates on ``human_reviewed`` rows.
* Migration 0008 adds a ``procedural_memories`` table that the engine
  can write into; the rollback drops it cleanly.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest

from core.procedural_engine import (
    ProceduralDerivationMethod,
    ProceduralDraft,
    ProceduralEngine,
    ProceduralReviewState,
)
from db.migration_runner import MigrationRunner


REPO_BACKEND = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_BACKEND / "db" / "migrations"


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


async def _prepare_db(db_path: Path) -> None:
    _bootstrap(db_path)
    runner = MigrationRunner(_sqlite_url(db_path), migrations_dir=MIGRATIONS_DIR)
    await runner.apply_pending()


def _make_session_factory(db_path: Path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_sqlite_url(db_path))
    return async_sessionmaker(engine, expire_on_commit=False)


def _valid_review_token(token: str, draft_id: int) -> bool:
    return token.startswith("valid-") and draft_id > 0


# ----------------------------------------------------------- dataclass tests


def test_procedural_draft_requires_provenance() -> None:
    with pytest.raises(ValueError):
        ProceduralDraft(
            trigger="how to commit",
            steps=["one"],
            source_memory_ids=[],
            source_hashes=[],
        )
    with pytest.raises(ValueError):
        ProceduralDraft(
            trigger="how to commit",
            steps=["one"],
            source_memory_ids=[1, 2],
            source_hashes=["h1"],  # length mismatch
        )
    with pytest.raises(ValueError):
        ProceduralDraft(
            trigger="how to commit",
            steps=[],
            source_memory_ids=[1],
            source_hashes=["h1"],
        )
    with pytest.raises(ValueError):
        ProceduralDraft(
            trigger="",
            steps=["one"],
            source_memory_ids=[1],
            source_hashes=["h1"],
        )
    with pytest.raises(ValueError):
        ProceduralDraft(
            trigger="t",
            steps=["one"],
            source_memory_ids=[1],
            source_hashes=["h1"],
            review_state="not-a-state",
        )
    with pytest.raises(ValueError):
        ProceduralDraft(
            trigger="t",
            steps=["one"],
            source_memory_ids=[1],
            source_hashes=["h1"],
            derivation_method="unknown_method",
        )
    with pytest.raises(ValueError):
        ProceduralDraft(
            trigger="t",
            steps=["one"],
            source_memory_ids=[1],
            source_hashes=["h1"],
            confidence=2.5,
        )


def test_procedural_draft_normalizes_steps_and_storage_budget() -> None:
    draft = ProceduralDraft(
        trigger="do thing",
        steps=["  one  ", "", None, "two"],  # type: ignore[list-item]
        source_memory_ids=[1],
        source_hashes=["h1"],
    )
    assert draft.steps == ["one", "two"]
    assert draft.storage_budget_bytes > 0
    record = draft.to_record()
    assert isinstance(record["steps_json"], str)
    assert json.loads(record["steps_json"]) == ["one", "two"]


def test_procedural_draft_to_api_shape() -> None:
    draft = ProceduralDraft(
        trigger="trig",
        steps=["a", "b"],
        source_memory_ids=[1, 2],
        source_hashes=["h1", "h2"],
        confidence=0.5,
    )
    api = draft.to_api()
    assert api["trigger"] == "trig"
    assert api["steps"] == ["a", "b"]
    assert api["source_memory_ids"] == [1, 2]
    assert api["source_hashes"] == ["h1", "h2"]
    assert api["review_state"] == ProceduralReviewState.DRAFT
    assert api["storage_budget_bytes"] > 0


# -------------------------------------------------------------- engine tests


@pytest.mark.asyncio
async def test_migration_creates_procedural_memories_table(tmp_path: Path) -> None:
    db_path = tmp_path / "m.db"
    await _prepare_db(db_path)
    with sqlite3.connect(db_path) as conn:
        names = sorted(
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        )
        cols = [
            row[1]
            for row in conn.execute("PRAGMA table_info(procedural_memories)").fetchall()
        ]
    assert "procedural_memories" in names
    for required in (
        "trigger",
        "steps_json",
        "source_memory_ids",
        "source_hashes",
        "derivation_method",
        "confidence",
        "review_state",
        "success_count",
        "last_used",
    ):
        assert required in cols, f"missing column: {required}"


@pytest.mark.asyncio
async def test_extract_pattern_persists_draft_with_provenance(tmp_path: Path) -> None:
    db_path = tmp_path / "x.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [
            {"id": 1, "content": "How to commit\n- stage files\n- write message\n- run git commit"},
            {"id": 2, "content": "Commit workflow\n- stage files\n- review diff\n- commit with message"},
        ],
    )

    engine = ProceduralEngine(_make_session_factory(db_path))
    draft = await engine.extract_pattern([1, 2])

    assert isinstance(draft, ProceduralDraft)
    assert draft.id is not None and draft.id > 0
    assert draft.review_state == ProceduralReviewState.DRAFT
    assert draft.source_memory_ids == [1, 2]
    assert len(draft.source_hashes) == 2
    assert all(len(h) == 64 for h in draft.source_hashes)
    assert draft.derivation_method == ProceduralDerivationMethod.RULE_BASED
    assert draft.confidence > 0.0
    assert draft.storage_budget_bytes > 0
    assert draft.steps  # at least one extracted step

    # The persisted row should be queryable.
    with sqlite3.connect(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM procedural_memories WHERE review_state='draft'"
        ).fetchone()[0]
    assert count == 1


@pytest.mark.asyncio
async def test_extract_pattern_default_review_state_is_draft(tmp_path: Path) -> None:
    db_path = tmp_path / "draft.db"
    await _prepare_db(db_path)
    _seed_memories(db_path, [{"id": 1, "content": "trigger\n- one\n- two"}])

    engine = ProceduralEngine(_make_session_factory(db_path))
    draft = await engine.extract_pattern([1])
    assert draft.review_state == ProceduralReviewState.DRAFT


@pytest.mark.asyncio
async def test_extract_pattern_rejects_empty_inputs(tmp_path: Path) -> None:
    db_path = tmp_path / "rej.db"
    await _prepare_db(db_path)
    engine = ProceduralEngine(_make_session_factory(db_path))

    with pytest.raises(ValueError):
        await engine.extract_pattern([])
    with pytest.raises(ValueError):
        await engine.extract_pattern([9999])  # nothing exists
    with pytest.raises(ValueError):
        await engine.extract_pattern([1], derivation_method="bogus")


@pytest.mark.asyncio
async def test_get_drafts_returns_only_drafts(tmp_path: Path) -> None:
    db_path = tmp_path / "list.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [
            {"id": 1, "content": "A\n- step a1\n- step a2"},
            {"id": 2, "content": "B\n- step b1\n- step b2"},
        ],
    )

    engine = ProceduralEngine(_make_session_factory(db_path))
    d1 = await engine.extract_pattern([1])
    d2 = await engine.extract_pattern([2])
    drafts = await engine.get_drafts()
    ids = {d["id"] for d in drafts}
    assert d1.id in ids
    assert d2.id in ids
    for d in drafts:
        assert d["review_state"] == ProceduralReviewState.DRAFT


@pytest.mark.asyncio
async def test_approve_draft_requires_review_token(tmp_path: Path) -> None:
    db_path = tmp_path / "ap.db"
    await _prepare_db(db_path)
    _seed_memories(db_path, [{"id": 1, "content": "A\n- one"}])

    engine = ProceduralEngine(_make_session_factory(db_path))
    draft = await engine.extract_pattern([1])

    with pytest.raises(PermissionError):
        await engine.approve_draft(draft.id, review_token="")
    with pytest.raises(PermissionError):
        await engine.approve_draft(draft.id, review_token="   ")
    with pytest.raises(PermissionError):
        await engine.approve_draft(draft.id, review_token="any-non-empty-token")

    engine = ProceduralEngine(
        _make_session_factory(db_path),
        review_token_validator=_valid_review_token,
    )
    with pytest.raises(PermissionError):
        await engine.approve_draft(draft.id, review_token="invalid-token")


@pytest.mark.asyncio
async def test_approve_draft_promotes_and_records_fingerprint(tmp_path: Path) -> None:
    db_path = tmp_path / "ap2.db"
    await _prepare_db(db_path)
    _seed_memories(db_path, [{"id": 1, "content": "Approve me\n- one"}])

    engine = ProceduralEngine(
        _make_session_factory(db_path),
        review_token_validator=_valid_review_token,
    )
    draft = await engine.extract_pattern([1])
    promoted = await engine.approve_draft(draft.id, review_token="valid-opaque-token-123")

    assert promoted["review_state"] == ProceduralReviewState.HUMAN_REVIEWED
    assert isinstance(promoted["review_token_fingerprint"], str)
    assert len(promoted["review_token_fingerprint"]) == 64

    # Idempotent — calling again with the same token should NOT raise
    # and should leave the row in human_reviewed.
    again = await engine.approve_draft(draft.id, review_token="valid-opaque-token-123")
    assert again["review_state"] == ProceduralReviewState.HUMAN_REVIEWED


@pytest.mark.asyncio
async def test_reject_draft_records_reason(tmp_path: Path) -> None:
    db_path = tmp_path / "rej2.db"
    await _prepare_db(db_path)
    _seed_memories(db_path, [{"id": 1, "content": "Reject me\n- one"}])

    engine = ProceduralEngine(
        _make_session_factory(db_path),
        review_token_validator=_valid_review_token,
    )
    draft = await engine.extract_pattern([1])
    rejected = await engine.reject_draft(draft.id, reason="incorrect steps")

    assert rejected["review_state"] == ProceduralReviewState.REJECTED
    assert rejected["rejection_reason"] == "incorrect steps"

    # Cannot approve a rejected draft.
    with pytest.raises(ValueError):
        await engine.approve_draft(draft.id, review_token="valid-some-token")


@pytest.mark.asyncio
async def test_reject_draft_requires_reason(tmp_path: Path) -> None:
    db_path = tmp_path / "rej3.db"
    await _prepare_db(db_path)
    _seed_memories(db_path, [{"id": 1, "content": "x\n- one"}])

    engine = ProceduralEngine(_make_session_factory(db_path))
    draft = await engine.extract_pattern([1])
    with pytest.raises(ValueError):
        await engine.reject_draft(draft.id, reason="")


@pytest.mark.asyncio
async def test_reject_after_approve_is_blocked(tmp_path: Path) -> None:
    db_path = tmp_path / "ra.db"
    await _prepare_db(db_path)
    _seed_memories(db_path, [{"id": 1, "content": "x\n- one"}])

    engine = ProceduralEngine(
        _make_session_factory(db_path),
        review_token_validator=_valid_review_token,
    )
    draft = await engine.extract_pattern([1])
    await engine.approve_draft(draft.id, review_token="valid-tok")
    with pytest.raises(ValueError):
        await engine.reject_draft(draft.id, reason="changed mind")


@pytest.mark.asyncio
async def test_unapproved_drafts_excluded_from_recommendations(tmp_path: Path) -> None:
    db_path = tmp_path / "rec.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [
            {"id": 1, "content": "deploy to staging\n- pull image\n- restart pod"},
            {"id": 2, "content": "deploy to prod\n- pull image\n- restart pod\n- verify"},
        ],
    )

    engine = ProceduralEngine(
        _make_session_factory(db_path),
        review_token_validator=_valid_review_token,
    )
    d1 = await engine.extract_pattern([1], trigger_hint="deploy to staging")
    d2 = await engine.extract_pattern([2], trigger_hint="deploy to prod")
    # Approve only the prod one.
    await engine.approve_draft(d2.id, review_token="valid-t")

    matches = await engine.recommend_for_trigger("deploy")
    states = {m["review_state"] for m in matches}
    assert states == {ProceduralReviewState.HUMAN_REVIEWED}
    ids = {m["id"] for m in matches}
    assert d2.id in ids
    assert d1.id not in ids


@pytest.mark.asyncio
async def test_recommend_for_trigger_returns_empty_for_blank_trigger(tmp_path: Path) -> None:
    db_path = tmp_path / "blank.db"
    await _prepare_db(db_path)
    engine = ProceduralEngine(_make_session_factory(db_path))
    assert await engine.recommend_for_trigger("") == []
    assert await engine.recommend_for_trigger("   ") == []


@pytest.mark.asyncio
async def test_increment_success_only_for_human_reviewed(tmp_path: Path) -> None:
    db_path = tmp_path / "succ.db"
    await _prepare_db(db_path)
    _seed_memories(db_path, [{"id": 1, "content": "x\n- one"}])

    engine = ProceduralEngine(
        _make_session_factory(db_path),
        review_token_validator=_valid_review_token,
    )
    draft = await engine.extract_pattern([1])
    with pytest.raises(ValueError):
        await engine.increment_success(draft.id)

    await engine.approve_draft(draft.id, review_token="valid-tok")
    promoted = await engine.increment_success(draft.id)
    assert promoted["success_count"] == 1
    assert promoted["last_used"] is not None

    second = await engine.increment_success(draft.id)
    assert second["success_count"] == 2


@pytest.mark.asyncio
async def test_get_by_review_state_rejects_unknown(tmp_path: Path) -> None:
    db_path = tmp_path / "bad.db"
    await _prepare_db(db_path)
    engine = ProceduralEngine(_make_session_factory(db_path))
    with pytest.raises(ValueError):
        await engine.get_by_review_state("nope")


@pytest.mark.asyncio
async def test_extract_pattern_preview_mode_skips_persist(tmp_path: Path) -> None:
    db_path = tmp_path / "prev.db"
    await _prepare_db(db_path)
    _seed_memories(db_path, [{"id": 1, "content": "x\n- one"}])

    engine = ProceduralEngine(_make_session_factory(db_path))
    draft = await engine.extract_pattern([1], persist=False)
    assert draft.id is None
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM procedural_memories").fetchone()[0]
    assert count == 0


@pytest.mark.asyncio
async def test_approve_draft_missing_id_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "miss.db"
    await _prepare_db(db_path)
    engine = ProceduralEngine(
        _make_session_factory(db_path),
        review_token_validator=_valid_review_token,
    )
    with pytest.raises(ValueError):
        await engine.approve_draft(12345, review_token="valid-t")
    with pytest.raises(ValueError):
        await engine.reject_draft(12345, reason="r")


@pytest.mark.asyncio
async def test_rollback_migration_drops_procedural_table(tmp_path: Path) -> None:
    db_path = tmp_path / "rb.db"
    await _prepare_db(db_path)
    # Sanity — table exists.
    with sqlite3.connect(db_path) as conn:
        before = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "procedural_memories" in before

    # Manually apply rollback script and verify table disappears.
    rollback_sql = (MIGRATIONS_DIR / "0008_add_procedural_memories.rollback.sql").read_text(
        encoding="utf-8"
    )
    with sqlite3.connect(db_path) as conn:
        conn.executescript(rollback_sql)
    with sqlite3.connect(db_path) as conn:
        after = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "procedural_memories" not in after
