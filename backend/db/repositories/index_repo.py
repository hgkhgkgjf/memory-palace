"""Index maintenance repository (Round 1 delegate facade).

Round 1 only establishes the modular import surface; implementation
remains on ``SQLiteClient``.

Methods covered:
    - rebuild_index
    - reindex_memory
    - get_index_status
"""

from __future__ import annotations

from typing import Any

from ._base import _RepositoryBase


class IndexRepository(_RepositoryBase):
    """Thin delegate over ``SQLiteClient`` for index management."""

    async def rebuild_index(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.rebuild_index(*args, **kwargs)

    async def reindex_memory(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.reindex_memory(*args, **kwargs)

    async def get_index_status(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.get_index_status(*args, **kwargs)
