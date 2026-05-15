"""Tests for the forgetting engine.

Covers:

* Simulation does NOT modify any row (key invariant for C2).
* Candidate queue returns rows below the threshold; the row never
  drops out of ``memories``.
* ``approve_archive`` requires a non-empty review_token, copies the
  row to ``archived_memories``, marks the L1 row deprecated, and
  creates a gist when none exists.
* Archive is NOT a SQL DELETE — the row stays present in ``memories``.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from core.forgetting_engine import (
    ArchiveResult,
    DecaySimulation,
    ForgettingCandidate,
    ForgettingEngine,
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


def _valid_archive_token(token: str, memory_id: int) -> bool:
    return token.startswith("valid-") and memory_id > 0


def _now_iso(offset_days: float = 0.0) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(days=offset_days)
    ).isoformat()


def _all_memory_state(db_path: Path) -> List[tuple]:
    with sqlite3.connect(db_path) as conn:
        return list(
            conn.execute(
                "SELECT id, content, deprecated, vitality_score FROM memories"
            ).fetchall()
        )


# ----------------------------------------------------------- simulation tests


@pytest.mark.asyncio
async def test_simulate_decay_does_not_mutate_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "sim.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [
            {
                "id": 1,
                "content": "old",
                "vitality_score": 0.8,
                "last_accessed_at": _now_iso(60),
                "access_count": 2,
            },
            {
                "id": 2,
                "content": "fresh",
                "vitality_score": 0.95,
                "last_accessed_at": _now_iso(0),
                "access_count": 10,
            },
        ],
    )
    before = _all_memory_state(db_path)

    engine = ForgettingEngine(_make_session_factory(db_path))
    sims = await engine.simulate_decay(days_forward=30)
    assert sims, "Should produce at least one simulation"
    assert all(isinstance(s, DecaySimulation) for s in sims)

    after = _all_memory_state(db_path)
    assert before == after, "simulate_decay must not mutate the memories table"


@pytest.mark.asyncio
async def test_simulate_decay_orders_by_projected_score(tmp_path: Path) -> None:
    db_path = tmp_path / "order.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [
            {
                "id": 1,
                "content": "hot",
                "vitality_score": 0.9,
                "last_accessed_at": _now_iso(0),
                "access_count": 50,
            },
            {
                "id": 2,
                "content": "cold",
                "vitality_score": 0.2,
                "last_accessed_at": _now_iso(90),
                "access_count": 0,
            },
        ],
    )
    engine = ForgettingEngine(_make_session_factory(db_path))
    sims = await engine.simulate_decay(days_forward=30)
    scores = [s.projected_score for s in sims]
    assert scores == sorted(scores)
    # Coldest row appears first.
    assert sims[0].memory_id == 2


@pytest.mark.asyncio
async def test_simulate_decay_accepts_naive_iso_last_accessed(tmp_path: Path) -> None:
    db_path = tmp_path / "naive_time.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [
            {
                "id": 1,
                "content": "naive timestamp",
                "vitality_score": 0.4,
                "last_accessed_at": "2026-01-01T00:00:00",
            }
        ],
    )
    engine = ForgettingEngine(_make_session_factory(db_path))

    sims = await engine.simulate_decay(days_forward=1)

    assert len(sims) == 1
    assert sims[0].memory_id == 1


@pytest.mark.asyncio
async def test_get_candidates_returns_below_threshold_only(tmp_path: Path) -> None:
    db_path = tmp_path / "cand.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [
            {
                "id": 1,
                "content": "hot",
                "vitality_score": 0.95,
                "last_accessed_at": _now_iso(0),
                "access_count": 100,
            },
            {
                "id": 2,
                "content": "cold",
                "vitality_score": 0.2,
                "last_accessed_at": _now_iso(90),
                "access_count": 0,
            },
        ],
    )
    engine = ForgettingEngine(_make_session_factory(db_path))
    cands = await engine.get_candidates(threshold=0.35, days_forward=30)
    ids = {c.memory_id for c in cands}
    assert 2 in ids
    assert 1 not in ids
    for c in cands:
        assert c.projected_score < 0.35
        assert c.recommendation in {"archive", "review"}


@pytest.mark.asyncio
async def test_get_candidates_is_read_only(tmp_path: Path) -> None:
    db_path = tmp_path / "cand_ro.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [
            {
                "id": 5,
                "content": "stale",
                "vitality_score": 0.1,
                "last_accessed_at": _now_iso(180),
                "access_count": 0,
            }
        ],
    )
    before = _all_memory_state(db_path)
    engine = ForgettingEngine(_make_session_factory(db_path))
    cands = await engine.get_candidates(threshold=0.35, days_forward=30)
    after = _all_memory_state(db_path)
    assert before == after
    # Memory is still there even though it's in the candidate list.
    assert before[0][2] == 0  # deprecated remains 0
    assert any(c.memory_id == 5 for c in cands)


# ------------------------------------------------------------- archive tests


@pytest.mark.asyncio
async def test_approve_archive_requires_review_token(tmp_path: Path) -> None:
    db_path = tmp_path / "tok.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [{"id": 1, "content": "x", "vitality_score": 0.1}],
    )
    engine = ForgettingEngine(_make_session_factory(db_path))
    with pytest.raises(PermissionError):
        await engine.approve_archive(1, review_token="")
    with pytest.raises(PermissionError):
        await engine.approve_archive(1, review_token="   ")
    with pytest.raises(PermissionError):
        await engine.approve_archive(1, review_token="any-non-empty-token")

    engine = ForgettingEngine(
        _make_session_factory(db_path),
        review_token_validator=_valid_archive_token,
    )
    with pytest.raises(PermissionError):
        await engine.approve_archive(1, review_token="invalid-token")


@pytest.mark.asyncio
async def test_approve_archive_moves_memory_without_destructive_delete(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "arch.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [{"id": 42, "content": "Archive me", "vitality_score": 0.05}],
    )
    _seed_paths(
        db_path,
        [{"path": "core/x/archive_target", "memory_id": 42, "priority": 1}],
    )

    engine = ForgettingEngine(
        _make_session_factory(db_path),
        review_token_validator=_valid_archive_token,
    )
    result = await engine.approve_archive(
        42, review_token="valid-review-token-xyz", archived_by="tester"
    )

    assert isinstance(result, ArchiveResult)
    assert result.memory_id == 42
    assert result.archived_id and result.archived_id > 0
    assert result.review_state == "human_reviewed"
    assert result.review_token_fingerprint != "valid-review-token-xyz"
    assert len(result.review_token_fingerprint) == 64  # SHA-256 hex

    second = await engine.approve_archive(
        42, review_token="valid-review-token-second", archived_by="tester"
    )
    assert second.archived_id == result.archived_id

    with sqlite3.connect(db_path) as conn:
        # Memory row still present — NO DELETE.
        row = conn.execute(
            "SELECT id, content, deprecated FROM memories WHERE id=42"
        ).fetchone()
        assert row is not None
        assert row[1] == "Archive me"
        assert row[2] == 1, "deprecated must flip to 1 (tombstone)"

        # Archive row created.
        archived = conn.execute(
            """
            SELECT original_memory_id, content, archive_reason, review_state,
                   paths_snapshot
              FROM archived_memories WHERE original_memory_id=42
            """
        ).fetchone()
        archive_count = conn.execute(
            "SELECT COUNT(*) FROM archived_memories WHERE original_memory_id=42"
        ).fetchone()[0]
        assert archived is not None
        assert archived[0] == 42
        assert archived[1] == "Archive me"
        assert archived[3] == "human_reviewed"
        assert "core/x/archive_target" in archived[4]
        assert archive_count == 1


@pytest.mark.asyncio
async def test_approve_archive_creates_gist_when_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "gist.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [{"id": 7, "content": "Need a gist", "vitality_score": 0.05}],
    )
    engine = ForgettingEngine(
        _make_session_factory(db_path),
        review_token_validator=_valid_archive_token,
    )
    result = await engine.approve_archive(7, review_token="valid-tok-xyz-abc-1234")
    assert result.created_gist is True

    with sqlite3.connect(db_path) as conn:
        gist = conn.execute(
            """
            SELECT memory_id, gist_text, derivation_method,
                   source_memory_ids, source_hashes, review_state,
                   storage_budget_bytes
              FROM memory_gists WHERE memory_id=7
            """
        ).fetchone()
    assert gist is not None
    assert gist[0] == 7
    assert "Need a gist" in gist[1]
    assert gist[2] == "rule_based"
    assert gist[3] == "[7]"
    assert len(json.loads(gist[4])[0]) == 64
    assert gist[5] == "auto_generated"
    assert gist[6] > 0


@pytest.mark.asyncio
async def test_approve_archive_skips_gist_when_one_exists(tmp_path: Path) -> None:
    db_path = tmp_path / "gist2.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [{"id": 8, "content": "Has a gist already", "vitality_score": 0.05}],
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO memory_gists (memory_id, gist_text, source_content_hash, gist_method)
            VALUES (8, 'existing', 'hash-prev', 'manual')
            """
        )
        conn.commit()
    engine = ForgettingEngine(
        _make_session_factory(db_path),
        review_token_validator=_valid_archive_token,
    )
    result = await engine.approve_archive(8, review_token="valid-another-token-1234")
    assert result.created_gist is False
    with sqlite3.connect(db_path) as conn:
        gist = conn.execute(
            """
            SELECT source_memory_ids, source_hashes, derivation_method,
                   confidence, review_state, storage_budget_bytes
              FROM memory_gists WHERE memory_id=8
            """
        ).fetchone()
    assert gist is not None
    assert gist[0] == "[8]"
    assert json.loads(gist[1]) == ["hash-prev"]
    assert gist[2]
    assert 0.0 <= float(gist[3]) <= 1.0
    assert gist[4] == "auto_generated"
    assert int(gist[5]) > 0


@pytest.mark.asyncio
async def test_approve_archive_unknown_memory_raises_value_error(tmp_path: Path) -> None:
    db_path = tmp_path / "miss.db"
    await _prepare_db(db_path)
    engine = ForgettingEngine(
        _make_session_factory(db_path),
        review_token_validator=_valid_archive_token,
    )
    with pytest.raises(ValueError):
        await engine.approve_archive(9999, review_token="valid-token-abc-1234")


@pytest.mark.asyncio
async def test_no_auto_delete_anywhere(tmp_path: Path) -> None:
    """Top-level invariant: no method in the engine ever deletes from memories."""
    db_path = tmp_path / "no_delete.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [
            {"id": i, "content": f"row {i}", "vitality_score": 0.05}
            for i in range(1, 6)
        ],
    )
    initial_ids = sorted(r[0] for r in _all_memory_state(db_path))
    engine = ForgettingEngine(
        _make_session_factory(db_path),
        review_token_validator=_valid_archive_token,
    )

    await engine.simulate_decay(days_forward=365)
    await engine.get_candidates(threshold=0.9, days_forward=365)

    after_ids = sorted(r[0] for r in _all_memory_state(db_path))
    assert after_ids == initial_ids, "Simulation/candidates must not delete rows"

    # Even after archiving, the row remains in the memories table.
    await engine.approve_archive(3, review_token="valid-some-review-token-xyz")
    final_ids = sorted(r[0] for r in _all_memory_state(db_path))
    assert final_ids == initial_ids, "Archive must not delete from memories table"


def test_forgetting_engine_validates_constructor_inputs(tmp_path: Path) -> None:
    """Configuration errors should surface immediately."""
    factory = _make_session_factory(tmp_path / "cfg.db")
    with pytest.raises(ValueError):
        ForgettingEngine(factory, decay_lambda=0.0)
    with pytest.raises(ValueError):
        ForgettingEngine(factory, threshold=0.0)
    with pytest.raises(ValueError):
        ForgettingEngine(factory, threshold=1.0)


@pytest.mark.asyncio
async def test_archive_records_token_fingerprint_and_no_plaintext(tmp_path: Path) -> None:
    db_path = tmp_path / "fp.db"
    await _prepare_db(db_path)
    _seed_memories(
        db_path,
        [{"id": 99, "content": "track fingerprint", "vitality_score": 0.05}],
    )
    engine = ForgettingEngine(
        _make_session_factory(db_path),
        review_token_validator=_valid_archive_token,
    )
    result = await engine.approve_archive(
        99, review_token="valid-super-secret-token-9999"
    )
    assert "valid-super-secret-token" not in result.review_token_fingerprint
    assert result.review_token_fingerprint == "{}".format(
        # Compare against the engine's own hashing.
        __import__("core.layering_engine", fromlist=["sha256_text"]).sha256_text(
            "valid-super-secret-token-9999"
        )
    )
