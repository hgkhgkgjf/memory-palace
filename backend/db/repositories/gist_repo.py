"""Gist repository (Round 1 delegate facade).

Round 1 only establishes the modular import surface; implementation
remains on ``SQLiteClient``.

Methods covered:
    - upsert_memory_gist
    - get_latest_memory_gist
    - get_gist_stats
    - generate_compact_gist
"""

from __future__ import annotations

from typing import Any

from ._base import _RepositoryBase


class GistRepository(_RepositoryBase):
    """Thin delegate over ``SQLiteClient`` for memory gists."""

    async def upsert_memory_gist(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.upsert_memory_gist(*args, **kwargs)

    async def get_latest_memory_gist(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.get_latest_memory_gist(*args, **kwargs)

    async def get_gist_stats(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.get_gist_stats(*args, **kwargs)

    async def generate_compact_gist(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.generate_compact_gist(*args, **kwargs)
