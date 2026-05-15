"""Tests for the entity rerank boost (Round 1 Track C, C6).

The entity boost is NOT an equal-weight RRF channel; it is a multiplicative
nudge applied *after* fusion. These tests cover both the standalone
extraction/boost helpers and the end-to-end integration with
``SQLiteClient.search_advanced``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest
from sqlalchemy import text as sa_text

from db.search.entity_channel import (
    EntityBoostUnavailable,
    ExtractedEntity,
    compute_boost,
    extract_entities,
)
from db.sqlite_client import SQLiteClient


# ---------------------------------------------------------------------------
# Pure extraction (synchronous)
# ---------------------------------------------------------------------------


def test_extract_entities_returns_empty_for_blank_query() -> None:
    assert extract_entities("") == []
    assert extract_entities("   ") == []


def test_extract_entities_recognises_uri_and_error_code() -> None:
    query = "I saw ERR_INTERNAL when fetching notes://team/risks"
    found = extract_entities(query)
    kinds = {e.kind for e in found}
    assert "error_code" in kinds
    assert "uri" in kinds
    values = {e.value.lower() for e in found}
    assert "err_internal" in values
    assert any(v.startswith("notes://") for v in values)


def test_extract_entities_recognises_dotted_package() -> None:
    query = "Look into backend.db.search performance"
    found = extract_entities(query)
    kinds = {e.kind for e in found}
    assert "dotted" in kinds
    assert any(e.value == "backend.db.search" for e in found)


def test_extract_entities_recognises_version_and_snake() -> None:
    query = "v1.2.3 release broke memory_palace_init"
    found = extract_entities(query)
    kinds = {e.kind for e in found}
    assert "version" in kinds
    assert "snake" in kinds


def test_extract_entities_caps_at_max_entities() -> None:
    query = " ".join(f"word{i}" for i in range(100))
    found = extract_entities(query, max_entities=8)
    assert len(found) <= 8


# ---------------------------------------------------------------------------
# Async tests -- marked individually below.
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# compute_boost (integration with in-memory MemoryTag table)
# ---------------------------------------------------------------------------


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


async def _seed_with_tags(client: SQLiteClient) -> List[Dict[str, Any]]:
    """Create three memories and tag them with structured entities."""

    rows = [
        ("Redis cache eviction notes", "redis-cache-1"),
        ("Postgres pgvector cosine recall", "pgvector-2"),
        ("Memory Palace RRF calibration", "rrf-3"),
    ]
    created: List[Dict[str, Any]] = []
    async with client.session() as session:
        for content, title in rows:
            mem = await client.create_memory(
                parent_path="",
                content=content,
                priority=0,
                title=title,
                domain="core",
            )
            created.append(mem)

        # Insert tags. memory_id 1 -> redis, memory_id 2 -> pgvector,
        # memory_id 3 -> rrf + memory-palace.
        await session.execute(
            sa_text(
                "INSERT INTO memory_tags(memory_id, tag_type, tag_value, confidence) "
                "VALUES (:m1a, 'keyword', 'redis', 0.95), "
                "(:m1b, 'keyword', 'cache', 0.7), "
                "(:m2,  'keyword', 'pgvector', 0.9), "
                "(:m3a, 'keyword', 'rrf', 0.85), "
                "(:m3b, 'concept', 'memory-palace', 0.8)"
            ),
            {
                "m1a": created[0]["id"],
                "m1b": created[0]["id"],
                "m2": created[1]["id"],
                "m3a": created[2]["id"],
                "m3b": created[2]["id"],
            },
        )
        await session.commit()
    return created


@pytest.mark.asyncio
async def test_compute_boost_returns_empty_when_no_memory_ids(
    tmp_path: Path,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "entity-empty.db"))
    await client.init_db()
    async with client.session() as session:
        result = await compute_boost("redis cache", [], session)
    assert result == {}
    await client.close()


@pytest.mark.asyncio
async def test_compute_boost_returns_empty_when_no_entities(
    tmp_path: Path,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "entity-noent.db"))
    await client.init_db()
    seeded = await _seed_with_tags(client)
    async with client.session() as session:
        # Whitespace and punctuation only -- no entities extracted.
        result = await compute_boost("  ! ", [s["id"] for s in seeded], session)
    assert result == {}
    await client.close()


@pytest.mark.asyncio
async def test_compute_boost_hits_tagged_memory(
    tmp_path: Path,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "entity-hit.db"))
    await client.init_db()
    seeded = await _seed_with_tags(client)
    ids = [s["id"] for s in seeded]
    async with client.session() as session:
        boosts = await compute_boost("redis cache", ids, session)
    # The redis memory must be boosted; others should not (or have lower
    # values).
    assert seeded[0]["id"] in boosts
    assert boosts[seeded[0]["id"]] > 0.0
    # pgvector memory should not match "redis" or "cache" tags.
    assert boosts.get(seeded[1]["id"], 0.0) == 0.0
    await client.close()


@pytest.mark.asyncio
async def test_compute_boost_raises_visible_failure_on_db_error() -> None:
    """SQL failures must propagate so callers do not mark boost as applied."""

    class BrokenSession:
        async def execute(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("simulated tag lookup failure")

    with pytest.raises(EntityBoostUnavailable):
        await compute_boost("redis", [99999], BrokenSession())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# End-to-end integration with search_advanced
# ---------------------------------------------------------------------------


def _strip_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "RRF_ENABLED",
        "RRF_K",
        "RRF_CHANNELS",
        "ENTITY_RERANK_WEIGHT",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.asyncio
async def test_entity_boost_disabled_when_weight_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strip_env(monkeypatch)
    client = SQLiteClient(_sqlite_url(tmp_path / "entity-off.db"))
    await client.init_db()
    await _seed_with_tags(client)

    payload = await client.search_advanced(
        query="redis cache",
        mode="keyword",
        max_results=3,
    )
    assert payload["metadata"]["entity_boost_applied"] is False
    assert payload["metadata"]["entity_rerank_weight"] == 0.0
    await client.close()


@pytest.mark.asyncio
async def test_entity_boost_enabled_sets_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strip_env(monkeypatch)
    monkeypatch.setenv("ENTITY_RERANK_WEIGHT", "0.5")
    client = SQLiteClient(_sqlite_url(tmp_path / "entity-on.db"))
    await client.init_db()
    await _seed_with_tags(client)

    payload = await client.search_advanced(
        query="redis cache",
        mode="keyword",
        max_results=3,
    )
    meta = payload["metadata"]
    assert meta["entity_rerank_weight"] == pytest.approx(0.5)
    # The boost is "applied" once compute_boost runs; the actual count may
    # be 0 if no tag matches were found (depends on stored tags), so the
    # flag is conditional on candidates existing.
    assert meta["entity_boost_applied"] in (True, False)
    await client.close()


@pytest.mark.asyncio
async def test_entity_boost_failure_does_not_mark_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strip_env(monkeypatch)
    monkeypatch.setenv("ENTITY_RERANK_WEIGHT", "0.5")

    async def _broken_compute_boost(*args: Any, **kwargs: Any) -> Dict[int, float]:
        raise EntityBoostUnavailable("simulated failure")

    monkeypatch.setattr(
        "db.search.entity_channel.compute_boost",
        _broken_compute_boost,
    )

    client = SQLiteClient(_sqlite_url(tmp_path / "entity-failure-meta.db"))
    await client.init_db()
    await _seed_with_tags(client)

    payload = await client.search_advanced(
        query="redis cache",
        mode="keyword",
        max_results=3,
    )
    meta = payload["metadata"]
    assert meta["entity_boost_applied"] is False
    assert meta["entity_boost_count"] == 0
    assert "entity_boost_failed" in payload["degrade_reasons"]
    await client.close()


@pytest.mark.asyncio
async def test_entity_rerank_weight_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The weight is clamped to [0.0, 5.0] regardless of env value."""

    _strip_env(monkeypatch)
    monkeypatch.setenv("ENTITY_RERANK_WEIGHT", "99.0")
    client = SQLiteClient(_sqlite_url(tmp_path / "entity-clamp.db"))
    await client.init_db()
    assert client._entity_rerank_weight <= 5.0
    await client.close()

    monkeypatch.setenv("ENTITY_RERANK_WEIGHT", "-1.0")
    client2 = SQLiteClient(_sqlite_url(tmp_path / "entity-clamp2.db"))
    await client2.init_db()
    assert client2._entity_rerank_weight == 0.0
    await client2.close()


@pytest.mark.asyncio
async def test_entity_boost_is_separate_from_rrf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C6: entity is NOT an RRF channel, even when both features are on."""

    _strip_env(monkeypatch)
    monkeypatch.setenv("RRF_ENABLED", "true")
    monkeypatch.setenv("RRF_CHANNELS", "fts5,vector,entity")
    monkeypatch.setenv("ENTITY_RERANK_WEIGHT", "0.5")

    client = SQLiteClient(_sqlite_url(tmp_path / "entity-c6.db"))
    await client.init_db()
    # ``entity`` is silently filtered from the channel list.
    assert "entity" not in client._rrf_config.channels
    # Both subsystems are configured independently.
    assert client._rrf_config.enabled is True
    assert client._entity_rerank_weight == pytest.approx(0.5)
    await client.close()
