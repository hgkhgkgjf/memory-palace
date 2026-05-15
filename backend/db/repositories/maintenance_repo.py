"""Maintenance repository (Round 1 delegate facade).

Round 1 only establishes the modular import surface; implementation
remains on ``SQLiteClient``.

This repository groups the remaining maintenance / lifecycle methods
that did not naturally fit one of the focused repositories above.

Methods covered:
    - init_db
    - close
    - session (returns an async context manager — usable without await)
    - get_runtime_meta / set_runtime_meta
    - get_recent_read_state
    - get_recent_memories
    - get_memory_version
    - get_deprecated_memories
    - get_all_orphan_memories
    - get_orphan_detail
    - restore_path_metadata
    - delete_created_tree_atomically
    - read_memory_segment
    - write_guard
    - should_use_intent_llm (sync)
    - classify_intent_with_llm
"""

from __future__ import annotations

from typing import Any

from ._base import _RepositoryBase


class MaintenanceRepository(_RepositoryBase):
    """Thin delegate over ``SQLiteClient`` for lifecycle / maintenance ops."""

    # ---- lifecycle ----

    async def init_db(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.init_db(*args, **kwargs)

    async def close(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.close(*args, **kwargs)

    def session(self, *args: Any, **kwargs: Any) -> Any:
        # NOTE: ``SQLiteClient.session`` returns an async context manager
        # (``@asynccontextmanager``), so it is *not* awaited here.  Callers
        # should ``async with repo.session() as s: ...``.
        return self._client.session(*args, **kwargs)

    # ---- runtime metadata ----

    async def get_runtime_meta(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.get_runtime_meta(*args, **kwargs)

    async def set_runtime_meta(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.set_runtime_meta(*args, **kwargs)

    # ---- recent / version views ----

    async def get_recent_read_state(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.get_recent_read_state(*args, **kwargs)

    async def get_recent_memories(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.get_recent_memories(*args, **kwargs)

    async def get_memory_version(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.get_memory_version(*args, **kwargs)

    # ---- orphan / deprecated review ----

    async def get_deprecated_memories(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.get_deprecated_memories(*args, **kwargs)

    async def get_all_orphan_memories(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.get_all_orphan_memories(*args, **kwargs)

    async def get_orphan_detail(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.get_orphan_detail(*args, **kwargs)

    # ---- structural recovery ----

    async def restore_path_metadata(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.restore_path_metadata(*args, **kwargs)

    async def delete_created_tree_atomically(
        self, *args: Any, **kwargs: Any
    ) -> Any:
        return await self._client.delete_created_tree_atomically(*args, **kwargs)

    # ---- reads ----

    async def read_memory_segment(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.read_memory_segment(*args, **kwargs)

    # ---- write guard ----

    async def write_guard(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.write_guard(*args, **kwargs)

    # ---- LLM intent classifier ----

    def should_use_intent_llm(self, *args: Any, **kwargs: Any) -> Any:
        return self._client.should_use_intent_llm(*args, **kwargs)

    async def classify_intent_with_llm(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.classify_intent_with_llm(*args, **kwargs)
