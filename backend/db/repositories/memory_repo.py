"""Memory CRUD repository (Round 1 delegate facade).

This module delegates to the existing methods on ``SQLiteClient``.  The
implementation has *not* been moved here yet; the long-term plan is to
gradually migrate the bodies, but Round 1 only establishes the modular
import surface so behavior is unchanged.

Methods covered:
    - create_memory
    - update_memory
    - get_memory_by_id
    - get_memory_by_path
    - get_memories_by_paths
    - permanently_delete_memory
    - rollback_to_memory
"""

from __future__ import annotations

from typing import Any

from ._base import _RepositoryBase


class MemoryRepository(_RepositoryBase):
    """Thin delegate over ``SQLiteClient`` for memory CRUD operations."""

    async def create_memory(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.create_memory(*args, **kwargs)

    async def update_memory(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.update_memory(*args, **kwargs)

    async def get_memory_by_id(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.get_memory_by_id(*args, **kwargs)

    async def get_memory_by_path(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.get_memory_by_path(*args, **kwargs)

    async def get_memories_by_paths(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.get_memories_by_paths(*args, **kwargs)

    async def permanently_delete_memory(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.permanently_delete_memory(*args, **kwargs)

    async def rollback_to_memory(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.rollback_to_memory(*args, **kwargs)
