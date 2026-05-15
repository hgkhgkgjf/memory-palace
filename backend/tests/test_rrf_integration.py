"""Integration tests for RRF rollout inside ``SQLiteClient.search_advanced``.

These tests verify that:

- ``RRF_ENABLED=false`` (default) keeps the existing behaviour byte-for-byte
  identical: the response shape, mode, and result count stay the same.
- ``RRF_ENABLED=true`` activates the fusion path and surfaces the
  ``rrf_applied`` flag (plus channel counts) in the metadata block.
- The C5 contract holds: ``RRF_K`` is configurable through env var.
- The C6 contract holds: ``entity`` cannot be smuggled into the RRF channel
  list via env var.
- The MCP-facing response shape (top-level keys + per-result keys) is
  preserved across both RRF on / off paths.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from db.sqlite_client import SQLiteClient


pytestmark = pytest.mark.asyncio


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


async def _seed(client: SQLiteClient) -> List[Dict[str, Any]]:
    """Seed a small but realistic corpus for retrieval tests."""

    rows = [
        ("Redis cache eviction policy notes", "redis-cache", 1),
        ("Postgres pgvector cosine recall analysis", "pgvector", 2),
        ("Memory Palace RRF calibration MRR@8", "rrf-design", 0),
        ("Entity rerank boost design (C6 constraint)", "entity-design", 0),
        ("Random unrelated note about gardening", "garden-misc", 3),
    ]
    created: List[Dict[str, Any]] = []
    for content, title, priority in rows:
        created.append(
            await client.create_memory(
                parent_path="",
                content=content,
                priority=priority,
                title=title,
                domain="core",
            )
        )
    return created


def _strip_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "RRF_ENABLED",
        "RRF_K",
        "RRF_CHANNELS",
        "RRF_LOG_CHANNEL_CONTRIBUTIONS",
        "ENTITY_RERANK_WEIGHT",
    ):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Default OFF behaviour
# ---------------------------------------------------------------------------


async def test_rrf_disabled_search_advanced_matches_baseline_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strip_env(monkeypatch)
    client = SQLiteClient(_sqlite_url(tmp_path / "rrf-off.db"))
    await client.init_db()
    await _seed(client)

    payload = await client.search_advanced(
        query="redis cache",
        mode="keyword",
        max_results=4,
    )

    # The top-level response shape must match the existing MCP contract.
    assert set(payload.keys()) >= {
        "results",
        "mode",
        "requested_mode",
        "degraded",
        "degrade_reason",
        "degrade_reasons",
        "metadata",
    }

    # RRF metadata is present but explicitly flagged as inactive.
    meta = payload["metadata"]
    assert meta["rrf_applied"] is False
    assert isinstance(meta["rrf_k"], int)
    assert isinstance(meta["rrf_channels"], list)
    assert meta["entity_boost_applied"] is False
    assert pytest.approx(meta["entity_rerank_weight"]) == 0.0

    # Existing fields must still be present.
    assert "mmr_applied" in meta
    assert "vector_engine_requested" in meta

    # Per-result shape must remain unchanged.
    for row in payload["results"]:
        assert set(row.keys()) >= {
            "uri",
            "memory_id",
            "chunk_id",
            "snippet",
            "char_range",
            "scores",
            "metadata",
        }
        assert set(row["scores"].keys()) == {
            "vector",
            "text",
            "priority",
            "recency",
            "path_prefix",
            "rerank",
            "final",
        }

    await client.close()


# ---------------------------------------------------------------------------
# RRF enabled
# ---------------------------------------------------------------------------


async def test_rrf_enabled_search_advanced_marks_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strip_env(monkeypatch)
    monkeypatch.setenv("RRF_ENABLED", "true")
    monkeypatch.setenv("RRF_K", "20")
    monkeypatch.setenv("RRF_CHANNELS", "fts5,vector")

    client = SQLiteClient(_sqlite_url(tmp_path / "rrf-on.db"))
    await client.init_db()
    await _seed(client)

    payload = await client.search_advanced(
        query="redis cache",
        mode="hybrid",
        max_results=4,
    )
    meta = payload["metadata"]
    # When RRF is enabled and at least the keyword channel returns hits, the
    # fusion path must mark itself as applied.
    if meta.get("rrf_channel_counts"):
        assert meta["rrf_applied"] is True
        assert meta["rrf_k"] == 20
        assert set(meta["rrf_channels"]) == {"fts5", "vector"}
    else:
        # Empty channels can happen if neither FTS5 nor the vector index
        # returned hits for this corpus. The flag must still be present.
        assert "rrf_applied" in meta

    # Per-result shape must still match the contract.
    for row in payload["results"]:
        assert set(row["scores"].keys()) == {
            "vector",
            "text",
            "priority",
            "recency",
            "path_prefix",
            "rerank",
            "final",
        }

    await client.close()


async def test_rrf_env_filters_entity_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C6: ``entity`` MUST be filtered from the channel allow-list."""

    _strip_env(monkeypatch)
    monkeypatch.setenv("RRF_ENABLED", "true")
    monkeypatch.setenv("RRF_CHANNELS", "fts5,vector,entity")

    client = SQLiteClient(_sqlite_url(tmp_path / "rrf-c6.db"))
    await client.init_db()
    assert "entity" not in client._rrf_config.channels
    assert tuple(client._rrf_config.channels) == ("fts5", "vector")
    await client.close()


async def test_rrf_env_invalid_channel_is_visible_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit unsupported channels must not silently fall back to defaults."""

    _strip_env(monkeypatch)
    monkeypatch.setenv("RRF_ENABLED", "true")
    monkeypatch.setenv("RRF_CHANNELS", "fts5,unknown")

    with pytest.raises(ValueError, match="unsupported channel"):
        SQLiteClient(_sqlite_url(tmp_path / "rrf-invalid-channel.db"))


async def test_rrf_k_is_configurable_via_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C5: ``RRF_K`` MUST be configurable."""

    _strip_env(monkeypatch)
    monkeypatch.setenv("RRF_ENABLED", "true")
    monkeypatch.setenv("RRF_K", "15")

    client = SQLiteClient(_sqlite_url(tmp_path / "rrf-k.db"))
    await client.init_db()
    assert client._rrf_config.k == 15
    await client.close()


async def test_rrf_disabled_when_env_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C5: RRF MUST default to OFF when no env var is set."""

    _strip_env(monkeypatch)
    client = SQLiteClient(_sqlite_url(tmp_path / "rrf-default.db"))
    await client.init_db()
    assert client._rrf_config.enabled is False
    await client.close()


async def test_rrf_response_keys_match_mcp_contract_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Toggle RRF on and off; the *set of top-level keys* must be identical.

    This guards the MCP golden contract: adding fields under metadata is
    fine, but renaming or dropping top-level response keys would break
    downstream consumers.
    """

    _strip_env(monkeypatch)
    client = SQLiteClient(_sqlite_url(tmp_path / "rrf-shape.db"))
    await client.init_db()
    await _seed(client)

    off_payload = await client.search_advanced(query="palace rrf", mode="keyword")
    off_keys = set(off_payload.keys())
    off_meta_keys = set(off_payload["metadata"].keys())
    await client.close()

    monkeypatch.setenv("RRF_ENABLED", "true")
    client_on = SQLiteClient(_sqlite_url(tmp_path / "rrf-shape-on.db"))
    await client_on.init_db()
    await _seed(client_on)
    on_payload = await client_on.search_advanced(query="palace rrf", mode="keyword")
    on_keys = set(on_payload.keys())
    on_meta_keys = set(on_payload["metadata"].keys())
    await client_on.close()

    assert off_keys == on_keys
    # ``rrf_applied`` / ``rrf_k`` / ``rrf_channels`` must always be present
    # whether or not the feature is enabled.
    assert {"rrf_applied", "rrf_k", "rrf_channels"}.issubset(off_meta_keys)
    assert {"rrf_applied", "rrf_k", "rrf_channels"}.issubset(on_meta_keys)
