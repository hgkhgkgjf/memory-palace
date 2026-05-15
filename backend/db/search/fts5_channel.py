"""FTS5 keyword search channel.

This channel WRAPS the FTS5 + legacy-fallback path inside
:meth:`SQLiteClient.search_advanced` (lines ~6725-6855 in
``backend/db/sqlite_client.py``). It does NOT modify the production code path;
instead it issues the same SQL via the public session helper so callers can
obtain a ranked, BM25-derived list independently of the weighted-fusion
scoring layer.

The channel is consumed by:

- The offline RRF calibration harness
  (``backend/tests/benchmark/rrf_calibration.py``).
- Future RRF code paths once the feature flag is flipped ON.

Production ``search_advanced`` is unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import text

from .base_channel import BaseChannel, SearchResult

if TYPE_CHECKING:  # pragma: no cover -- type-only import to avoid cycles.
    from backend.db.sqlite_client import SQLiteClient


class FTS5Channel(BaseChannel):
    """Wrap the FTS5 BM25 keyword retrieval path.

    Parameters:
        client: an initialised :class:`SQLiteClient`. The channel reuses its
            session factory, ``_build_safe_fts_query``, fallback term builder,
            and the ``_fts_available`` capability flag.
        candidate_multiplier: oversampling factor applied to ``max_results``
            to obtain the candidate pool size. Mirrors the
            ``candidate_multiplier`` argument of ``search_advanced``.
    """

    channel_name = "fts5"

    def __init__(
        self,
        client: "SQLiteClient",
        *,
        candidate_multiplier: int = 4,
    ) -> None:
        self._client = client
        self._candidate_multiplier = max(1, int(candidate_multiplier))

    async def search(
        self,
        query: str,
        max_results: int,
        **kwargs: Any,
    ) -> List[SearchResult]:
        """Return a ranked list of FTS5 keyword hits.

        Behaviour mirrors the keyword branch of ``search_advanced``:

        1. Build a safe FTS5 MATCH query.
        2. Issue the BM25-ordered query against ``memory_chunks_fts``.
        3. Fall back to ``LIKE`` term scan when FTS5 is unavailable or the
           MATCH query yields zero rows.
        4. Fall back to the legacy ``memories+paths`` table for pre-index data.
        """

        cleaned_query = (query or "").strip()
        if not cleaned_query:
            return []

        max_results = max(1, int(max_results))
        candidate_limit = max_results * self._candidate_multiplier

        rows: List[Dict[str, Any]] = []
        async with self._client.session() as session:
            where_clause = "m.deprecated = 0"
            where_params: Dict[str, Any] = {}

            if getattr(self._client, "_fts_available", False):
                fts_query = self._client._build_safe_fts_query(cleaned_query)
                if fts_query:
                    try:
                        result = await session.execute(
                            text(
                                "SELECT "
                                "mc.id AS chunk_id, mc.memory_id AS memory_id, "
                                "mc.chunk_text AS chunk_text, "
                                "mc.char_start AS char_start, "
                                "mc.char_end AS char_end, "
                                "p.domain AS domain, p.path AS path, "
                                "p.priority AS priority, "
                                "p.disclosure AS disclosure, "
                                "m.created_at AS created_at, "
                                "bm25(memory_chunks_fts) AS text_rank "
                                "FROM memory_chunks_fts "
                                "JOIN memory_chunks mc "
                                "  ON mc.id = memory_chunks_fts.chunk_id "
                                "JOIN memories m ON m.id = mc.memory_id "
                                "JOIN paths p ON p.memory_id = mc.memory_id "
                                f"WHERE {where_clause} "
                                "AND memory_chunks_fts MATCH :fts_query "
                                "ORDER BY text_rank ASC "
                                "LIMIT :candidate_limit"
                            ),
                            {
                                **where_params,
                                "fts_query": fts_query,
                                "candidate_limit": candidate_limit,
                            },
                        )
                        rows = [dict(row) for row in result.mappings().all()]
                    except Exception:  # noqa: BLE001 -- mirror existing tolerant path
                        rows = []

            if not rows:
                fallback_terms = self._client._build_keyword_fallback_terms(
                    cleaned_query
                )
                if not fallback_terms:
                    fallback_terms = [
                        self._client._normalize_retrieval_text(cleaned_query)
                    ]
                term_conditions: List[str] = []
                term_params: Dict[str, Any] = {
                    **where_params,
                    "candidate_limit": candidate_limit,
                }
                for index, term in enumerate(fallback_terms):
                    escaped_term = self._client._escape_like_pattern(term.lower())
                    param_name = f"like_pattern_{index}"
                    term_conditions.append(
                        f"LOWER(mc.chunk_text) LIKE :{param_name} ESCAPE '\\' "
                        f"OR LOWER(p.path) LIKE :{param_name} ESCAPE '\\'"
                    )
                    term_params[param_name] = f"%{escaped_term}%"
                if term_conditions:
                    result = await session.execute(
                        text(
                            "SELECT "
                            "mc.id AS chunk_id, mc.memory_id AS memory_id, "
                            "mc.chunk_text AS chunk_text, "
                            "mc.char_start AS char_start, "
                            "mc.char_end AS char_end, "
                            "p.domain AS domain, p.path AS path, "
                            "p.priority AS priority, "
                            "p.disclosure AS disclosure, "
                            "m.created_at AS created_at "
                            "FROM memory_chunks mc "
                            "JOIN memories m ON m.id = mc.memory_id "
                            "JOIN paths p ON p.memory_id = mc.memory_id "
                            f"WHERE {where_clause} "
                            f"AND ({' OR '.join(term_conditions)}) "
                            "ORDER BY p.priority ASC, m.created_at DESC "
                            "LIMIT :candidate_limit"
                        ),
                        term_params,
                    )
                    rows = [dict(row) for row in result.mappings().all()]

        # Map raw rows to ranked SearchResult objects. BM25 returns smaller =
        # better; we invert it to "larger = better" so RRF can ignore signs
        # (RRF itself uses ranks, not scores, but this keeps logs intuitive).
        results: List[SearchResult] = []
        for row in rows:
            text_rank = row.get("text_rank")
            if text_rank is not None:
                try:
                    score = 1.0 / (1.0 + max(float(text_rank), 0.0))
                except (TypeError, ValueError):
                    score = self._client._like_text_score(
                        cleaned_query,
                        row.get("chunk_text", ""),
                        row.get("path", ""),
                    )
            else:
                score = self._client._like_text_score(
                    cleaned_query,
                    row.get("chunk_text", ""),
                    row.get("path", ""),
                )
            results.append(
                SearchResult.from_row(
                    row,
                    score=float(score),
                    metadata={"text_rank": text_rank, "source": "fts5"},
                )
            )

        # Channels MAY return more than ``max_results`` candidates so that the
        # downstream fusion layer can rerank across a wider pool. Stay
        # consistent with the existing ``candidate_limit`` truncation by
        # honouring the caller's ceiling explicitly.
        if len(results) > max_results:
            results = results[:max_results]
        return self._finalise(results)


__all__ = ["FTS5Channel"]
