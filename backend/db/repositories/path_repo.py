"""Path CRUD repository (Round 1 delegate facade).

Round 1 only establishes the modular import surface; implementation
remains on ``SQLiteClient``.

Methods covered:
    - add_path
    - remove_path
    - delete_path_atomically
    - restore_path
    - get_all_paths
    - get_children
"""

from __future__ import annotations

from typing import Any

from ._base import _RepositoryBase


class PathRepository(_RepositoryBase):
    """Thin delegate over ``SQLiteClient`` for path / alias management."""

    async def add_path(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.add_path(*args, **kwargs)

    async def remove_path(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.remove_path(*args, **kwargs)

    async def delete_path_atomically(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.delete_path_atomically(*args, **kwargs)

    async def restore_path(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.restore_path(*args, **kwargs)

    async def get_all_paths(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.get_all_paths(*args, **kwargs)

    async def get_children(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.get_children(*args, **kwargs)
