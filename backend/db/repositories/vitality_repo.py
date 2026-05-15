"""Vitality repository (Round 1 delegate facade).

Round 1 only establishes the modular import surface; implementation
remains on ``SQLiteClient``.

Methods covered:
    - apply_vitality_decay
    - get_vitality_cleanup_candidates
    - get_vitality_stats
"""

from __future__ import annotations

from typing import Any

from ._base import _RepositoryBase


class VitalityRepository(_RepositoryBase):
    """Thin delegate over ``SQLiteClient`` for vitality scoring / decay."""

    async def apply_vitality_decay(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.apply_vitality_decay(*args, **kwargs)

    async def get_vitality_cleanup_candidates(
        self, *args: Any, **kwargs: Any
    ) -> Any:
        return await self._client.get_vitality_cleanup_candidates(*args, **kwargs)

    async def get_vitality_stats(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.get_vitality_stats(*args, **kwargs)
