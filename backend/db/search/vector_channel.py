"""Vector / semantic search channel.

This channel WRAPS the cosine-similarity branch of
:meth:`SQLiteClient.search_advanced` (lines ~6857-6942 in
``backend/db/sqlite_client.py``). It mirrors the existing dim-mismatch
fallback (lines ~6700-6721) so callers that bypass ``search_advanced`` -- e.g.
the offline RRF calibration harness -- still degrade gracefully when:

- the vector backend is disabled,
- no embeddings are indexed yet,
- indexed dims are mixed across rows, or
- the query embedding dim differs from the stored dim.

In every degraded case the channel returns ``[]`` and records the reasons in
``self.last_degrade_reasons`` so observability tests can assert on them
without changing the production code path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from .base_channel import BaseChannel, SearchResult

if TYPE_CHECKING:  # pragma: no cover -- type-only import to avoid cycles.
    from backend.db.sqlite_client import SQLiteClient


class VectorChannel(BaseChannel):
    """Wrap the cosine-similarity semantic retrieval path.

    Parameters:
        client: an initialised :class:`SQLiteClient`. The channel reuses its
            embedding helper, ``_get_indexed_vector_dims``,
            ``_fetch_semantic_rows_python_scoring`` /
            ``_fetch_semantic_rows_vec_native_topk``, and the
            ``_vector_available`` / ``_sqlite_vec_knn_ready`` capability flags.
        candidate_multiplier: oversampling factor applied to ``max_results``
            to obtain the candidate pool size. Mirrors the
            ``candidate_multiplier`` argument of ``search_advanced``.
    """

    channel_name = "vector"

    def __init__(
        self,
        client: "SQLiteClient",
        *,
        candidate_multiplier: int = 4,
    ) -> None:
        self._client = client
        self._candidate_multiplier = max(1, int(candidate_multiplier))
        #: Reasons collected during the most recent ``search()`` call (mirrors
        #: ``search_advanced``'s ``degrade_reasons``). Useful for tests and
        #: benchmark logs; never raised.
        self.last_degrade_reasons: List[str] = []

    async def search(
        self,
        query: str,
        max_results: int,
        *,
        embedding: Optional[Sequence[float]] = None,
        **kwargs: Any,
    ) -> List[SearchResult]:
        """Return a ranked list of cosine-similarity semantic hits.

        Args:
            query: raw user query (used for embedding lookup when
                ``embedding`` is not supplied).
            max_results: maximum number of results to return.
            embedding: optional pre-computed query embedding. When omitted the
                channel calls into :meth:`SQLiteClient._get_embedding`,
                respecting the configured backend chain.
        """

        cleaned_query = (query or "").strip()
        self.last_degrade_reasons = []
        if not cleaned_query:
            return []

        if not getattr(self._client, "_vector_available", False):
            self.last_degrade_reasons.append("vector_backend_disabled")
            return []

        max_results = max(1, int(max_results))
        candidate_limit = max_results * self._candidate_multiplier

        async with self._client.session() as session:
            where_clause = "m.deprecated = 0"
            where_params: Dict[str, Any] = {}

            # Mirror search_advanced lines ~6692-6723 for dim alignment.
            indexed_vector_dims = await self._client._get_indexed_vector_dims(
                session,
                where_clause=where_clause,
                where_params=where_params,
            )
            if not indexed_vector_dims:
                self.last_degrade_reasons.append("vector_index_empty")
                return []
            expected_dim = int(self._client._embedding_dim)
            if len(indexed_vector_dims) > 1:
                self._client._append_embedding_dim_mismatch_reasons(
                    self.last_degrade_reasons,
                    stored_dims=set(indexed_vector_dims),
                    query_dim=expected_dim,
                )
                self.last_degrade_reasons.append(
                    "vector_dim_mixed_requires_reindex"
                )
                if expected_dim not in indexed_vector_dims:
                    return []
            stored_dim = int(indexed_vector_dims[0])
            if len(indexed_vector_dims) == 1 and stored_dim != expected_dim:
                self.last_degrade_reasons.append(
                    f"embedding_dim_mismatch:{stored_dim}!={expected_dim}"
                )
                self.last_degrade_reasons.append(
                    "vector_dim_mismatch_requires_reindex"
                )
                return []
            indexed_vector_models = await self._client._get_indexed_vector_models(
                session,
                where_clause=where_clause,
                where_params=where_params,
            )
            embedding_backend = str(
                getattr(self._client, "_embedding_backend", "") or ""
            ).strip().lower()
            if (
                embedding_backend
                not in {"hash", "local", "none", "off", "disabled", "false", "0"}
                and any(
                    str(model or "").strip().lower().startswith("hash:")
                    for model in indexed_vector_models
                )
            ):
                self.last_degrade_reasons.append(
                    "vector_hash_fallback_requires_reindex"
                )
                return []

            # Resolve or compute the query embedding.
            local_reasons: List[str] = []
            query_embedding: Sequence[float]
            if embedding is not None:
                if len(embedding) != expected_dim:
                    self.last_degrade_reasons.append(
                        f"query_embedding_dim_mismatch:{len(embedding)}!={expected_dim}"
                    )
                    return []
                query_embedding = list(embedding)
            else:
                query_embedding = await self._client._get_embedding(
                    session,
                    cleaned_query,
                    degrade_reasons=local_reasons,
                )
                self.last_degrade_reasons.extend(local_reasons)
                if query_embedding is None:
                    self.last_degrade_reasons.append("query_embedding_unavailable")
                    return []

            # Pool sizing parity with search_advanced lines ~6876-6883.
            semantic_pool_limit = min(
                max(candidate_limit * 12, max_results * 64, 128),
                5000,
            )
            python_scoring_pool_limit = min(
                int(semantic_pool_limit),
                int(candidate_limit),
            )
            selected_vector_engine = self._client._resolve_vector_engine_for_query(
                cleaned_query
            )

            semantic_rows: List[Dict[str, Any]] = []
            if (
                selected_vector_engine == "vec"
                and getattr(self._client, "_sqlite_vec_knn_ready", False)
            ):
                try:
                    semantic_rows = (
                        await self._client._fetch_semantic_rows_vec_native_topk(
                            session,
                            where_clause=where_clause,
                            where_params=where_params,
                            query_embedding=query_embedding,
                            semantic_pool_limit=semantic_pool_limit,
                            candidate_limit=candidate_limit,
                        )
                    )
                except Exception:  # noqa: BLE001 -- mirror search_advanced fallback
                    self.last_degrade_reasons.append(
                        "sqlite_vec_native_query_failed"
                    )
                    semantic_rows = (
                        await self._client._fetch_semantic_rows_python_scoring(
                            session,
                            where_clause=where_clause,
                            where_params=where_params,
                            query_embedding=query_embedding,
                            semantic_pool_limit=python_scoring_pool_limit,
                            candidate_limit=candidate_limit,
                            degrade_reasons=self.last_degrade_reasons,
                        )
                    )
            else:
                if selected_vector_engine == "vec":
                    self.last_degrade_reasons.append("sqlite_vec_knn_unavailable")
                semantic_rows = (
                    await self._client._fetch_semantic_rows_python_scoring(
                        session,
                        where_clause=where_clause,
                        where_params=where_params,
                        query_embedding=query_embedding,
                        semantic_pool_limit=python_scoring_pool_limit,
                        candidate_limit=candidate_limit,
                        degrade_reasons=self.last_degrade_reasons,
                    )
                )

        # Map cosine similarity in [-1, 1] to a normalised [0, 1] score so
        # logs and rerank weighting stay intuitive. RRF itself uses ranks.
        results: List[SearchResult] = []
        for row in semantic_rows:
            similarity = float(row.get("vector_similarity", 0.0))
            score = max(0.0, min(1.0, (similarity + 1.0) / 2.0))
            results.append(
                SearchResult.from_row(
                    row,
                    score=score,
                    metadata={
                        "similarity": similarity,
                        "source": "vector",
                    },
                )
            )

        if len(results) > max_results:
            results = results[:max_results]
        return self._finalise(results)


__all__ = ["VectorChannel"]
