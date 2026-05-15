"""Search repository (Round 1 delegate facade).

Round 1 only establishes the modular import surface; implementation
remains on ``SQLiteClient``.

Notes
-----
``preprocess_query`` and ``classify_intent`` are synchronous helpers on
the current client, so they are exposed as plain methods here.
``classify_intent_with_llm`` is intentionally *not* in this surface
because it is an LLM-tier concern that lives in the runtime layer.

Methods covered:
    - search
    - search_advanced
    - preprocess_query (sync)
    - classify_intent (sync)
"""

from __future__ import annotations

from typing import Any

from ._base import _RepositoryBase


class SearchRepository(_RepositoryBase):
    """Thin delegate over ``SQLiteClient`` for retrieval operations."""

    async def search(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.search(*args, **kwargs)

    async def search_advanced(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client.search_advanced(*args, **kwargs)

    def preprocess_query(self, *args: Any, **kwargs: Any) -> Any:
        return self._client.preprocess_query(*args, **kwargs)

    def classify_intent(self, *args: Any, **kwargs: Any) -> Any:
        return self._client.classify_intent(*args, **kwargs)
