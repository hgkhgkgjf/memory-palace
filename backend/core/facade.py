"""``MemoryCore`` — single composition root for memory subsystems.

The facade composes the existing engines and the SQLite client so that
callers (the MCP tool layer, REST API, future CLI) have **one** entry
point to memory functionality.

Design contract (Round 3, Track C):

* **Pure delegation.**  The facade owns no new behaviour.  Every method
  forwards to an existing implementation on ``SQLiteClient`` or the
  layering/forgetting engines.  This keeps the facade introduction
  facade-preserving (no logic moves) and the contract golden ZERO diff.
* **Composition over coupling.**  Engines are instantiated once per
  facade instance; callers do not poke at internals.  Future engines
  (compression, procedural) get added here without leaking through to
  the MCP layer.
* **Async-only.**  All operations are ``async`` to match the rest of
  the backend.  Synchronous callers are not supported.

This file is intentionally small and dependency-light.  It must remain
under ~300 LOC; any growth signals new behaviour leaking into the
facade and should instead live in a dedicated engine or repository.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from .forgetting_engine import ForgettingEngine
from .layering_engine import LayeringEngine

if TYPE_CHECKING:  # pragma: no cover - typing only
    from db.search.rrf_fusion import RRFConfig
    from db.sqlite_client import SQLiteClient


logger = logging.getLogger(__name__)


class MemoryCore:
    """Composition root for the memory subsystem.

    The facade does NOT replace the MCP tool functions in
    ``mcp_server.py``.  It exposes the same conceptual surface as a
    composable Python object so that:

    * tests can wire a single ``MemoryCore`` instead of patching the
      mcp_server module globals,
    * future call sites (REST API, CLI, internal scripts) avoid
      importing the heavy mcp_server module,
    * the eventual slim of mcp_server has a single delegation target.

    The constructor takes the already-initialised :class:`SQLiteClient`
    and optional engine overrides; everything else is owned by the
    instance.  Tests can inject mock engines.
    """

    def __init__(
        self,
        sqlite_client: "SQLiteClient",
        *,
        rrf_config: Optional["RRFConfig"] = None,
        layering_engine: Optional[LayeringEngine] = None,
        forgetting_engine: Optional[ForgettingEngine] = None,
    ) -> None:
        if sqlite_client is None:
            raise ValueError("MemoryCore requires a non-None sqlite_client")
        self.db = sqlite_client
        self.rrf_config = rrf_config
        # Engines take an async session factory exposed by SQLiteClient.
        session_factory = self._resolve_session_factory(sqlite_client)
        self.layering = layering_engine or LayeringEngine(session_factory)
        self.forgetting = forgetting_engine or ForgettingEngine(session_factory)
        # Future engines (compression, procedural) plug in here without
        # changing the public surface.
        # self.compression = CompressionEngine(session_factory)
        # self.procedural = ProceduralEngine(session_factory)

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _resolve_session_factory(client: Any) -> Any:
        """Return the async session factory exposed by ``client``.

        ``SQLiteClient`` historically exposes ``async_session`` /
        ``async_session_factory`` / ``_async_session`` depending on the
        slice of the module under inspection.  The facade probes each
        candidate so tests and production code share one constructor.
        """
        for attr in ("async_session", "async_session_factory", "_async_session"):
            factory = getattr(client, attr, None)
            if factory is not None:
                return factory
        # Fall back to the client itself; callers that need the factory
        # explicitly will raise a clearer error than ``AttributeError``
        # the moment they invoke it.
        return client

    # --------------------------------------------------------- Memory CRUD
    async def read_memory_by_path(
        self,
        path: str,
        *,
        domain: str = "core",
        reinforce_access: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Pure-delegation read by ``(path, domain)``.

        Mirrors ``SQLiteClient.get_memory_by_path`` 1:1; the rich URI
        parsing, system://* virtual reads and guard accounting still
        live in ``mcp_server.read_memory``.  Callers that want the full
        MCP tool semantics should keep calling the tool.
        """
        return await self.db.get_memory_by_path(
            path=path, domain=domain, reinforce_access=reinforce_access
        )

    async def read_memory_by_id(self, memory_id: int) -> Optional[Dict[str, Any]]:
        """Pure-delegation read by primary key."""
        return await self.db.get_memory_by_id(int(memory_id))

    async def create_memory(
        self,
        parent_path: str,
        content: str,
        priority: int,
        *,
        title: Optional[str] = None,
        disclosure: Optional[str] = None,
        domain: str = "core",
        index_now: bool = True,
    ) -> Dict[str, Any]:
        """Pure-delegation memory creation.

        Forwards to ``SQLiteClient.create_memory``.  The high-level URI
        validation, write-guard evaluation and snapshot accounting in
        the MCP tool remain unchanged.
        """
        return await self.db.create_memory(
            parent_path=parent_path,
            content=content,
            priority=priority,
            title=title,
            disclosure=disclosure,
            domain=domain,
            index_now=index_now,
        )

    async def update_memory(
        self,
        path: str,
        *,
        content: Optional[str] = None,
        priority: Optional[int] = None,
        disclosure: Optional[str] = None,
        domain: str = "core",
        index_now: bool = True,
    ) -> Dict[str, Any]:
        """Pure-delegation memory update by path.

        Mirrors ``SQLiteClient.update_memory``: it creates a new version
        row, marks the previous one as deprecated, and repoints the path.
        """
        return await self.db.update_memory(
            path=path,
            content=content,
            priority=priority,
            disclosure=disclosure,
            domain=domain,
            index_now=index_now,
        )

    async def delete_path(
        self,
        path: str,
        *,
        domain: str = "core",
        before_delete: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Pure-delegation atomic path delete.

        Mirrors ``SQLiteClient.delete_path_atomically``.  Permanently
        deleting a memory row (no remaining aliases) lives behind
        ``permanently_delete_memory`` and is intentionally NOT exposed
        here -- it is a review-token-gated operation owned by the
        forgetting engine.
        """
        return await self.db.delete_path_atomically(
            path=path,
            domain=domain,
            before_delete=before_delete,
        )

    async def add_alias(
        self,
        new_path: str,
        target_path: str,
        *,
        new_domain: str = "core",
        target_domain: str = "core",
        priority: int = 0,
        disclosure: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Pure-delegation alias creation via ``SQLiteClient.add_path``.

        The alias-vs-create decision and cross-domain validation that
        ``mcp_server.add_alias`` performs stay in the MCP layer; the
        facade just exposes the underlying path-creation primitive.
        """
        return await self.db.add_path(
            new_path=new_path,
            target_path=target_path,
            new_domain=new_domain,
            target_domain=target_domain,
            priority=priority,
            disclosure=disclosure,
        )

    # ------------------------------------------------------------- Search
    async def search_memory(
        self,
        query: str,
        *,
        mode: str = "keyword",
        max_results: int = 8,
        candidate_multiplier: int = 4,
        filters: Optional[Dict[str, Any]] = None,
        intent_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Pure-delegation search via ``SQLiteClient.search_advanced``.

        The RRF configuration carried on the facade governs channel
        fusion inside ``search_advanced`` (and the channel modules).
        Session-first merging, scope hints and response-shaping stay
        in ``mcp_server.search_memory``.
        """
        return await self.db.search_advanced(
            query=query,
            mode=mode,
            max_results=max_results,
            candidate_multiplier=candidate_multiplier,
            filters=filters,
            intent_profile=intent_profile,
        )

    # -------------------------------------------------------- Maintenance
    async def rebuild_index(
        self,
        *,
        include_deprecated: bool = False,
        reason: str = "manual",
    ) -> Dict[str, Any]:
        """Pure-delegation index rebuild trigger.

        Mirrors ``SQLiteClient.rebuild_index``.  Sleep-consolidation
        scheduling and runtime-worker plumbing remain in the MCP tool.
        """
        return await self.db.rebuild_index(
            include_deprecated=include_deprecated, reason=reason
        )

    async def index_status(self) -> Dict[str, Any]:
        """Pure-delegation: ``SQLiteClient.get_index_status``."""
        return await self.db.get_index_status()

    # ------------------------------------------------------------- Aliasing
    # ``compact_context`` lives at the MCP-tool layer because it needs
    # session-id resolution and flush-tracker state that are owned by
    # ``runtime_state``, not the SQLite layer.  The facade therefore
    # intentionally does NOT define ``compact_context``; the tool
    # adapter calls the original mcp_server function directly.

    # --------------------------------------------------------- Layering L2
    async def generate_summary(
        self,
        scope: str,
        memory_ids: Sequence[int],
        **extra: Any,
    ):
        """Forward to :meth:`LayeringEngine.generate_summary`."""
        return await self.layering.generate_summary(scope, memory_ids, **extra)

    async def get_summaries(self, **kwargs: Any) -> List[Dict[str, Any]]:
        """Forward to :meth:`LayeringEngine.get_summaries`."""
        return await self.layering.get_summaries(**kwargs)

    async def drill_down(self, summary_id: int):
        """Forward to :meth:`LayeringEngine.drill_down`."""
        return await self.layering.drill_down(int(summary_id))

    # ------------------------------------------------------- Forgetting
    async def simulate_decay(self, days_forward: int = 30, **kwargs: Any):
        """Forward to :meth:`ForgettingEngine.simulate_decay`."""
        return await self.forgetting.simulate_decay(
            days_forward=days_forward, **kwargs
        )

    async def get_forgetting_candidates(self, **kwargs: Any):
        """Forward to :meth:`ForgettingEngine.get_candidates`."""
        return await self.forgetting.get_candidates(**kwargs)

    async def approve_archive(
        self,
        memory_id: int,
        *,
        review_token: str,
        **kwargs: Any,
    ):
        """Forward to :meth:`ForgettingEngine.approve_archive`."""
        return await self.forgetting.approve_archive(
            int(memory_id), review_token=review_token, **kwargs
        )


__all__ = ["MemoryCore"]
