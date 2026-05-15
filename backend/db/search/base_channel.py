"""Shared types and abstract base class for search channels.

A "channel" is a single retrieval source (FTS5 keyword, vector semantic,
entity, ...) that returns a *ranked* list of :class:`SearchResult` items.
Channels do not perform fusion themselves; fusion (e.g. RRF) is the job of
:class:`backend.db.search.rrf_fusion.RRFFusion`.

This module is **intentionally side-effect free**: importing it does not open
a database connection. Channels accept their dependencies (e.g. an
``SQLiteClient``) via the constructor so they can be wired up by either the
production code path or by offline benchmarks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional


@dataclass
class SearchResult:
    """A single chunk-level hit returned by a search channel.

    The shape mirrors the per-row dictionaries built inside
    :meth:`SQLiteClient.search_advanced` so channels can be composed with the
    existing scoring pipeline without an intermediate translation.

    Attributes:
        uri: ``"<domain>://<path>"`` identifier used for deduplication and
            ground-truth comparison in benchmarks.
        memory_id: parent memory primary key. ``None`` for legacy fallback rows
            that bypass the chunk index.
        chunk_id: chunk primary key. ``None`` for legacy fallback rows.
        chunk_text: raw chunk text (used for snippets / rerank inputs).
        char_start, char_end: chunk character offsets within the parent memory.
        domain: e.g. ``"notes"``.
        path: e.g. ``"project_alpha/risk_summary"``.
        priority: lower is "more important" (0 == highest priority).
        disclosure: opt-in disclosure tag inherited from the path.
        created_at: best-effort ISO-8601 string or ``None``.
        score: raw channel score (e.g. BM25 derived, cosine similarity). Larger
            = more relevant. Channels normalise this *only* if they have a
            natural normalisation (vector similarity in ``[0, 1]``); otherwise
            leave it raw -- fusion uses *ranks*, not absolute scores.
        rank: 1-indexed position within this channel's result list. Set by
            :meth:`BaseChannel._finalise`.
        metadata: per-row extras (e.g. ``bm25`` raw score, similarity, dim
            mismatch reasons). Channels MAY populate this; consumers MUST treat
            it as opt-in.
    """

    uri: str
    memory_id: Optional[int]
    chunk_id: Optional[int]
    chunk_text: str
    char_start: int
    char_end: int
    domain: str
    path: str
    priority: int
    disclosure: Optional[str]
    created_at: Optional[Any]
    score: float
    rank: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(
        cls,
        row: Mapping[str, Any],
        *,
        score: float,
        rank: int = 0,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> "SearchResult":
        """Build a :class:`SearchResult` from a ``search_advanced``-shaped row.

        Accepts the dict shape used by ``keyword_rows`` / ``semantic_rows``
        inside :meth:`SQLiteClient.search_advanced` so wrapping channels do not
        need to reshape the underlying SQL output.
        """

        domain = str(row.get("domain") or "core")
        path = str(row.get("path") or "")
        return cls(
            uri=f"{domain}://{path}",
            memory_id=row.get("memory_id"),
            chunk_id=row.get("chunk_id"),
            chunk_text=str(row.get("chunk_text") or ""),
            char_start=int(row.get("char_start") or 0),
            char_end=int(row.get("char_end") or 0),
            domain=domain,
            path=path,
            priority=int(row.get("priority") or 0),
            disclosure=row.get("disclosure"),
            created_at=row.get("created_at"),
            score=float(score),
            rank=int(rank),
            metadata=dict(metadata) if metadata else {},
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable dict view, useful for logging / golden tests."""

        return {
            "uri": self.uri,
            "memory_id": self.memory_id,
            "chunk_id": self.chunk_id,
            "domain": self.domain,
            "path": self.path,
            "priority": self.priority,
            "score": self.score,
            "rank": self.rank,
            "metadata": dict(self.metadata),
        }


class BaseChannel(ABC):
    """Abstract base class for a single retrieval channel.

    Concrete subclasses MUST implement :meth:`search`. They MAY override
    :meth:`name` to identify the channel in fusion logs; the default returns
    the class name lowercased without the ``Channel`` suffix.
    """

    #: Channel identifier used in fusion logs / RRF channel selection.
    channel_name: str = "base"

    @property
    def name(self) -> str:
        """Return the channel identifier (e.g. ``"fts5"``, ``"vector"``)."""

        return self.channel_name

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int,
        **kwargs: Any,
    ) -> List[SearchResult]:
        """Run the channel's retrieval logic and return a ranked list.

        Implementations MUST:
        - Return at most ``max_results`` items (the fusion layer may request a
          larger candidate pool by passing a bigger ``max_results``).
        - Order results by descending relevance from this channel's POV.
        - Set ``SearchResult.rank`` starting at 1 for the most relevant hit.
        - Return ``[]`` (not ``None``) when the channel is unavailable or the
          query is empty -- this lets the fusion layer fall back cleanly.

        Implementations MUST NOT raise on a degraded backend; instead, return
        ``[]`` and attach a ``degrade_reasons`` entry in
        :attr:`SearchResult.metadata` of a *sentinel* row when observability
        is needed.
        """

    @staticmethod
    def _finalise(results: List[SearchResult]) -> List[SearchResult]:
        """Assign 1-indexed ranks in-place and return ``results`` for chaining."""

        for index, item in enumerate(results, start=1):
            item.rank = index
        return results


__all__ = ["SearchResult", "BaseChannel"]
