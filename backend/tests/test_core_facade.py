"""Tests for ``MemoryCore`` (Round 3, Track C).

The facade is **pure delegation**: every public method forwards to an
existing implementation on the SQLite client or one of the engines.
These tests verify the delegation contract without spinning up the
real database:

* the facade rejects a ``None`` client at construction time,
* CRUD / search / maintenance methods forward to ``SQLiteClient`` with
  identical positional/keyword semantics,
* layering / forgetting methods forward to their respective engines,
* the facade exposes a stable public attribute surface (``db``,
  ``layering``, ``forgetting``, ``rrf_config``).

Run::

    python -m pytest backend/tests/test_core_facade.py -q
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.facade import MemoryCore
from core.forgetting_engine import ForgettingEngine
from core.layering_engine import LayeringEngine


# --------------------------------------------------------------- helpers


class _StubSession:
    """Async-context manager double that records nothing.

    Used only by the layering / forgetting engines if they are
    instantiated against this fake session factory.  The facade itself
    never invokes the session factory directly.
    """

    async def __aenter__(self) -> "_StubSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _stub_session_factory() -> _StubSession:
    return _StubSession()


def _build_fake_client(**method_returns: Any) -> MagicMock:
    """Build a MagicMock that mimics the parts of ``SQLiteClient``
    the facade touches.

    Every method we delegate to is replaced with an ``AsyncMock`` so
    the test can assert call arguments.  ``async_session`` is exposed
    as the session factory the engines will pick up.
    """
    client = MagicMock(name="SQLiteClient")
    client.async_session = _stub_session_factory

    delegated = (
        "get_memory_by_path",
        "get_memory_by_id",
        "create_memory",
        "update_memory",
        "delete_path_atomically",
        "add_path",
        "search_advanced",
        "rebuild_index",
        "get_index_status",
    )
    for name in delegated:
        mock = AsyncMock(return_value=method_returns.get(name, {"ok": True, "method": name}))
        setattr(client, name, mock)
    return client


# ------------------------------------------------------------ construction


def test_facade_rejects_none_client() -> None:
    with pytest.raises(ValueError, match="sqlite_client"):
        MemoryCore(sqlite_client=None)


def test_facade_exposes_public_surface() -> None:
    client = _build_fake_client()
    core = MemoryCore(client)
    assert core.db is client
    assert isinstance(core.layering, LayeringEngine)
    assert isinstance(core.forgetting, ForgettingEngine)
    assert core.rrf_config is None


def test_facade_accepts_engine_overrides() -> None:
    client = _build_fake_client()
    fake_layering = MagicMock(spec=LayeringEngine)
    fake_forgetting = MagicMock(spec=ForgettingEngine)
    core = MemoryCore(
        client,
        layering_engine=fake_layering,
        forgetting_engine=fake_forgetting,
    )
    assert core.layering is fake_layering
    assert core.forgetting is fake_forgetting


def test_facade_resolves_alternative_session_factory_attr() -> None:
    client = MagicMock(name="ClientWithFactoryAttr")
    client.async_session = None  # not present
    client.async_session_factory = _stub_session_factory
    core = MemoryCore(client)
    assert core.layering is not None
    assert core.forgetting is not None


# ---------------------------------------------------------------- CRUD


@pytest.mark.asyncio
async def test_read_memory_by_path_delegates() -> None:
    client = _build_fake_client(get_memory_by_path={"id": 7, "content": "ok"})
    core = MemoryCore(client)
    result = await core.read_memory_by_path("agent/my_user", domain="core")
    assert result == {"id": 7, "content": "ok"}
    client.get_memory_by_path.assert_awaited_once_with(
        path="agent/my_user", domain="core", reinforce_access=True
    )


@pytest.mark.asyncio
async def test_read_memory_by_id_delegates() -> None:
    client = _build_fake_client(get_memory_by_id={"id": 42})
    core = MemoryCore(client)
    result = await core.read_memory_by_id(42)
    assert result == {"id": 42}
    client.get_memory_by_id.assert_awaited_once_with(42)


@pytest.mark.asyncio
async def test_create_memory_delegates_with_full_kwargs() -> None:
    client = _build_fake_client(create_memory={"id": 100})
    core = MemoryCore(client)
    result = await core.create_memory(
        "agent",
        "hello world",
        priority=1,
        title="greeting",
        disclosure="when greeting starts",
        domain="core",
        index_now=False,
    )
    assert result == {"id": 100}
    client.create_memory.assert_awaited_once_with(
        parent_path="agent",
        content="hello world",
        priority=1,
        title="greeting",
        disclosure="when greeting starts",
        domain="core",
        index_now=False,
    )


@pytest.mark.asyncio
async def test_update_memory_delegates() -> None:
    client = _build_fake_client(update_memory={"new_id": 200, "old_id": 100})
    core = MemoryCore(client)
    result = await core.update_memory(
        "agent/my_user",
        content="updated",
        priority=2,
        domain="core",
    )
    assert result["new_id"] == 200
    client.update_memory.assert_awaited_once_with(
        path="agent/my_user",
        content="updated",
        priority=2,
        disclosure=None,
        domain="core",
        index_now=True,
    )


@pytest.mark.asyncio
async def test_delete_path_delegates() -> None:
    client = _build_fake_client(delete_path_atomically={"deleted": True})
    core = MemoryCore(client)
    result = await core.delete_path("agent/old", domain="core")
    assert result == {"deleted": True}
    client.delete_path_atomically.assert_awaited_once_with(
        path="agent/old",
        domain="core",
        before_delete=None,
    )


@pytest.mark.asyncio
async def test_add_alias_delegates() -> None:
    client = _build_fake_client(add_path={"alias": "ok"})
    core = MemoryCore(client)
    result = await core.add_alias(
        "timeline/2024/05/20",
        "agent/my_user/first_meeting",
        new_domain="core",
        target_domain="core",
        priority=1,
        disclosure="When I want to know how we start",
    )
    assert result == {"alias": "ok"}
    client.add_path.assert_awaited_once_with(
        new_path="timeline/2024/05/20",
        target_path="agent/my_user/first_meeting",
        new_domain="core",
        target_domain="core",
        priority=1,
        disclosure="When I want to know how we start",
    )


# -------------------------------------------------------------- Search


@pytest.mark.asyncio
async def test_search_memory_delegates_with_defaults() -> None:
    client = _build_fake_client(search_advanced={"results": []})
    core = MemoryCore(client)
    result = await core.search_memory("hello")
    assert result == {"results": []}
    client.search_advanced.assert_awaited_once_with(
        query="hello",
        mode="keyword",
        max_results=8,
        candidate_multiplier=4,
        filters=None,
        intent_profile=None,
    )


@pytest.mark.asyncio
async def test_search_memory_forwards_overrides() -> None:
    client = _build_fake_client()
    core = MemoryCore(client)
    await core.search_memory(
        "topic",
        mode="hybrid",
        max_results=20,
        candidate_multiplier=6,
        filters={"domain": "core"},
        intent_profile={"type": "exploratory"},
    )
    client.search_advanced.assert_awaited_once_with(
        query="topic",
        mode="hybrid",
        max_results=20,
        candidate_multiplier=6,
        filters={"domain": "core"},
        intent_profile={"type": "exploratory"},
    )


# ------------------------------------------------------------ Maintenance


@pytest.mark.asyncio
async def test_rebuild_index_delegates() -> None:
    client = _build_fake_client(rebuild_index={"chunks": 100})
    core = MemoryCore(client)
    result = await core.rebuild_index(include_deprecated=True, reason="audit")
    assert result == {"chunks": 100}
    client.rebuild_index.assert_awaited_once_with(
        include_deprecated=True, reason="audit"
    )


@pytest.mark.asyncio
async def test_index_status_delegates() -> None:
    client = _build_fake_client(get_index_status={"ok": True})
    core = MemoryCore(client)
    result = await core.index_status()
    assert result == {"ok": True}
    client.get_index_status.assert_awaited_once_with()


# ----------------------------------------------------------- engines


@pytest.mark.asyncio
async def test_layering_methods_delegate_to_engine() -> None:
    client = _build_fake_client()
    fake_layering = MagicMock(spec=LayeringEngine)
    fake_layering.generate_summary = AsyncMock(return_value="draft")
    fake_layering.get_summaries = AsyncMock(return_value=[{"id": 1}])
    fake_layering.drill_down = AsyncMock(return_value=[])

    core = MemoryCore(client, layering_engine=fake_layering)
    out = await core.generate_summary("core", [1, 2, 3])
    assert out == "draft"
    fake_layering.generate_summary.assert_awaited_once_with("core", [1, 2, 3])

    rows = await core.get_summaries(scope="core")
    assert rows == [{"id": 1}]
    fake_layering.get_summaries.assert_awaited_once_with(scope="core")

    drill = await core.drill_down(7)
    assert drill == []
    fake_layering.drill_down.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_forgetting_methods_delegate_to_engine() -> None:
    client = _build_fake_client()
    fake_forgetting = MagicMock(spec=ForgettingEngine)
    fake_forgetting.simulate_decay = AsyncMock(return_value=[])
    fake_forgetting.get_candidates = AsyncMock(return_value=[])
    fake_forgetting.approve_archive = AsyncMock(return_value="result")

    core = MemoryCore(client, forgetting_engine=fake_forgetting)
    sims = await core.simulate_decay(days_forward=14, limit=50)
    assert sims == []
    fake_forgetting.simulate_decay.assert_awaited_once_with(
        days_forward=14, limit=50
    )

    cands = await core.get_forgetting_candidates(threshold=0.3, limit=10)
    assert cands == []
    fake_forgetting.get_candidates.assert_awaited_once_with(
        threshold=0.3, limit=10
    )

    archived = await core.approve_archive(
        7,
        review_token="tok",
        archive_reason="cold",
    )
    assert archived == "result"
    fake_forgetting.approve_archive.assert_awaited_once_with(
        7, review_token="tok", archive_reason="cold"
    )


# -------------------------------------------------------- RRF config


def test_facade_carries_rrf_config() -> None:
    from db.search.rrf_fusion import RRFConfig

    client = _build_fake_client()
    cfg = RRFConfig(enabled=True, k=42)
    core = MemoryCore(client, rrf_config=cfg)
    assert core.rrf_config is cfg
    assert core.rrf_config.enabled is True
    assert core.rrf_config.k == 42
