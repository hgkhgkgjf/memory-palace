"""Reciprocal Rank Fusion (RRF) implementation.

RRF combines multiple ranked lists into a single ranking using the formula::

    score(d) = sum over channels j of  1 / (k + rank_j(d))

where ``rank_j(d)`` is the 1-indexed rank of document ``d`` inside channel
``j``'s result list (documents missing from a channel contribute zero).

Hard constraints (Round 1, Track B):

- ``C5``: RRF MUST be **OFF by default** and the ``k`` value MUST be
  configurable. The benchmark harness
  (``backend/tests/benchmark/rrf_calibration.py``) decides the optimal value
  before the flag is flipped on.
- ``C6``: The **entity** channel is reserved for a future rerank boost; it
  is NOT included in the default RRF channel list. ``RRFConfig.channels``
  defaults to ``("fts5", "vector")`` and the loader filters ``entity`` out.

This module is **pure**: it does not touch the database and has no side
effects on import. Channel I/O happens in the channel modules; this module
only fuses already-retrieved ranked lists.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .base_channel import SearchResult


LOGGER = logging.getLogger(__name__)

#: Default RRF k -- chosen to match the value popularised by Cormack et al.
#: (2009). The offline calibration harness writes the recommended value into
#: ``backend/tests/benchmark/rrf_calibration_results.json``; the production
#: default stays at 60 until the operator explicitly opts in.
DEFAULT_RRF_K: int = 60

#: Lower / upper bounds for the adaptive ``k = clamp(2 * max_channel_depth)``
#: formula recommended by the calibration harness.
RRF_K_MIN: int = 10
RRF_K_MAX: int = 60

#: Default channel list. ``entity`` is intentionally excluded -- C6.
DEFAULT_RRF_CHANNELS: Tuple[str, ...] = ("fts5", "vector")
VALID_RRF_CHANNELS = frozenset(DEFAULT_RRF_CHANNELS)


class RRFConfigError(ValueError):
    """Raised when an explicit RRF channel configuration is invalid."""


def _parse_bool(raw: Optional[str], default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_int(raw: Optional[str], default: int) -> int:
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _parse_channel_list(raw: Optional[str]) -> Tuple[str, ...]:
    if raw is None or not raw.strip():
        return DEFAULT_RRF_CHANNELS
    parsed: List[str] = []
    invalid: List[str] = []
    for chunk in raw.split(","):
        name = chunk.strip().lower()
        if not name:
            continue
        if name == "entity":  # C6: entity is rerank boost only.
            invalid.append(name)
            LOGGER.warning(
                "RRF channel list contains 'entity'; ignoring (C6: entity is "
                "rerank boost only, not equal-weight RRF fusion)."
            )
            continue
        if name not in VALID_RRF_CHANNELS:
            invalid.append(name)
            continue
        if name not in parsed:
            parsed.append(name)
    if invalid and not parsed:
        raise RRFConfigError(
            "RRF_CHANNELS must include at least one supported channel "
            f"({', '.join(DEFAULT_RRF_CHANNELS)}); invalid: "
            f"{', '.join(sorted(set(invalid)))}"
        )
    if invalid:
        unsupported = sorted({name for name in invalid if name != "entity"})
        if unsupported:
            raise RRFConfigError(
                "RRF_CHANNELS contains unsupported channel(s): "
                f"{', '.join(unsupported)}. Supported channels: "
                f"{', '.join(DEFAULT_RRF_CHANNELS)}"
            )
    return tuple(parsed) if parsed else DEFAULT_RRF_CHANNELS


@dataclass
class RRFConfig:
    """Runtime configuration for :class:`RRFFusion`.

    Attributes:
        enabled: master feature flag. **Default False** (C5: OFF by default).
        k: rank smoothing constant. Larger ``k`` flattens the contribution
            curve; smaller ``k`` concentrates weight on top ranks.
        channels: ordered channel allow-list. ``entity`` is filtered out
            because the entity channel is reserved for rerank boost only (C6).
        single_channel_fallback: when only one channel reports results,
            return that channel's ranking unchanged (still RRF-scored when
            False).
        log_channel_contributions: if True, log a per-document breakdown of
            channel ranks. Used by the calibration harness; do NOT enable in
            production -- it is verbose.
        adaptive_k_max_channel_depth: optional adaptive ``k`` hint. When set,
            :meth:`RRFConfig.suggested_k` returns
            ``clamp(2 * max_channel_depth, RRF_K_MIN, RRF_K_MAX)``.
    """

    enabled: bool = False
    k: int = DEFAULT_RRF_K
    channels: Tuple[str, ...] = DEFAULT_RRF_CHANNELS
    single_channel_fallback: bool = True
    log_channel_contributions: bool = False
    adaptive_k_max_channel_depth: Optional[int] = None

    def __post_init__(self) -> None:
        # Defensive copy + validation. ``channels`` must always be a tuple of
        # lowercase supported channels without ``entity`` (C6). Explicitly
        # invalid channel names raise instead of silently falling back.
        self.channels = _parse_channel_list(
            ",".join(str(channel) for channel in self.channels)
        )
        self.k = max(1, int(self.k))

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "RRFConfig":
        """Build a config from the ``RRF_*`` environment variables.

        Recognises:

        - ``RRF_ENABLED`` (bool, default ``false``)
        - ``RRF_K`` (int, default ``60``)
        - ``RRF_CHANNELS`` (comma-separated, default ``"fts5,vector"``)
        - ``RRF_LOG_CHANNEL_CONTRIBUTIONS`` (bool, default ``false``)
        """

        source: Mapping[str, str] = env if env is not None else os.environ
        return cls(
            enabled=_parse_bool(source.get("RRF_ENABLED"), default=False),
            k=_parse_int(source.get("RRF_K"), default=DEFAULT_RRF_K),
            channels=_parse_channel_list(source.get("RRF_CHANNELS")),
            log_channel_contributions=_parse_bool(
                source.get("RRF_LOG_CHANNEL_CONTRIBUTIONS"), default=False
            ),
        )

    def suggested_k(self, max_channel_depth: Optional[int] = None) -> int:
        """Return the adaptive ``k`` suggestion clamped to ``[10, 60]``.

        ``max_channel_depth`` overrides the stored hint when provided.
        """

        depth = max_channel_depth or self.adaptive_k_max_channel_depth or 0
        if depth <= 0:
            return self.k
        candidate = 2 * int(depth)
        return max(RRF_K_MIN, min(RRF_K_MAX, candidate))


def load_rrf_config_from_env(env: Optional[Mapping[str, str]] = None) -> RRFConfig:
    """Convenience wrapper. Mirrors :meth:`RRFConfig.from_env`."""

    return RRFConfig.from_env(env)


@dataclass
class _FusionRow:
    """Internal accumulator used during fusion."""

    result: SearchResult
    rrf_score: float = 0.0
    per_channel: Dict[str, int] = field(default_factory=dict)


class RRFFusion:
    """Apply Reciprocal Rank Fusion across multiple channel result lists.

    Usage::

        fusion = RRFFusion(RRFConfig(enabled=True, k=20))
        merged = fusion.fuse({"fts5": fts_rows, "vector": vec_rows})

    Behaviour:

    - Documents are deduplicated by ``SearchResult.uri``; the surviving copy
      keeps the highest per-channel ``score`` (for log readability only --
      ranking is driven by the RRF sum).
    - When only one channel has results AND
      :attr:`RRFConfig.single_channel_fallback` is True, that channel's
      ranking is returned untouched.
    - Channels absent from :attr:`RRFConfig.channels` are silently ignored,
      even if the caller passes them in. This protects C6 (entity is filtered
      out at config build time).
    """

    def __init__(self, config: Optional[RRFConfig] = None) -> None:
        self.config = config or RRFConfig()

    # ------------------------------------------------------------------ core
    def fuse(
        self,
        channel_results: Mapping[str, Sequence[SearchResult]],
        *,
        max_results: Optional[int] = None,
    ) -> List[SearchResult]:
        """Merge ``channel_results`` into a single ranked list.

        Args:
            channel_results: mapping ``{channel_name: [SearchResult, ...]}``.
                Result lists MUST already be sorted by their channel's
                relevance (rank 1 first). Empty / missing channels are fine.
            max_results: optional truncation. When ``None`` the fused list is
                returned in full.

        Returns:
            A new list of :class:`SearchResult` sorted by descending RRF
            score. ``rank`` is updated to reflect the fused position;
            ``metadata["rrf"]`` carries the per-channel rank breakdown for
            observability.
        """

        allowed = tuple(self.config.channels)
        filtered: Dict[str, Sequence[SearchResult]] = {}
        for name, rows in channel_results.items():
            if not rows:
                continue
            lower = name.lower()
            if lower not in allowed:
                # Silent drop: this is how C6 (entity) stays out of fusion.
                LOGGER.debug(
                    "RRFFusion: dropping channel '%s' (not in allow-list %s)",
                    lower,
                    allowed,
                )
                continue
            deduped_rows = self._dedupe_channel_rows(rows)
            if deduped_rows:
                filtered[lower] = deduped_rows

        if not filtered:
            return []

        # Single-channel fallback (graceful when the other channel is degraded).
        if len(filtered) == 1 and self.config.single_channel_fallback:
            only_name, only_rows = next(iter(filtered.items()))
            cloned: List[SearchResult] = []
            for index, row in enumerate(only_rows, start=1):
                channel_rank = self._channel_rank(row, index)
                meta = dict(row.metadata)
                meta["rrf"] = {
                    "channels": {only_name: channel_rank},
                    "k": int(self.config.k),
                    "single_channel_fallback": True,
                    "score": float(1.0 / (self.config.k + channel_rank)),
                }
                cloned.append(
                    SearchResult(
                        uri=row.uri,
                        memory_id=row.memory_id,
                        chunk_id=row.chunk_id,
                        chunk_text=row.chunk_text,
                        char_start=row.char_start,
                        char_end=row.char_end,
                        domain=row.domain,
                        path=row.path,
                        priority=row.priority,
                        disclosure=row.disclosure,
                        created_at=row.created_at,
                        score=meta["rrf"]["score"],
                        rank=index,
                        metadata=meta,
                    )
                )
            if max_results is not None:
                cloned = cloned[: max(1, int(max_results))]
            if self.config.log_channel_contributions:
                self._log_contributions(cloned)
            return cloned

        # Multi-channel fusion.
        k = int(self.config.k)
        accumulator: Dict[Tuple[str, str], _FusionRow] = {}
        for channel_name, rows in filtered.items():
            for index, row in enumerate(rows, start=1):
                key = self._dedup_identity(row)
                entry = accumulator.get(key)
                if entry is None:
                    # Clone the underlying SearchResult so callers cannot
                    # mutate the channel's original list.
                    cloned_row = SearchResult(
                        uri=row.uri,
                        memory_id=row.memory_id,
                        chunk_id=row.chunk_id,
                        chunk_text=row.chunk_text,
                        char_start=row.char_start,
                        char_end=row.char_end,
                        domain=row.domain,
                        path=row.path,
                        priority=row.priority,
                        disclosure=row.disclosure,
                        created_at=row.created_at,
                        score=row.score,
                        rank=row.rank,
                        metadata=dict(row.metadata),
                    )
                    entry = _FusionRow(result=cloned_row)
                    accumulator[key] = entry
                if channel_name in entry.per_channel:
                    continue
                channel_rank = self._channel_rank(row, index)
                # RRF contribution.
                entry.rrf_score += 1.0 / float(k + channel_rank)
                # Record the per-channel rank for observability.
                entry.per_channel[channel_name] = channel_rank
                # Keep the best per-channel raw score as a courtesy for logs.
                if row.score > entry.result.score:
                    entry.result.score = row.score

        ordered = sorted(
            accumulator.values(),
            key=lambda item: (-item.rrf_score, item.result.priority, item.result.uri),
        )

        merged: List[SearchResult] = []
        for index, entry in enumerate(ordered, start=1):
            entry.result.rank = index
            entry.result.metadata.setdefault("rrf", {})
            entry.result.metadata["rrf"] = {
                "channels": dict(entry.per_channel),
                "k": k,
                "score": float(entry.rrf_score),
                "single_channel_fallback": False,
            }
            # The exported ``score`` field carries the RRF score so downstream
            # consumers (benchmark harness, future entity rerank) can use it
            # directly. The original per-channel score remains in
            # ``metadata["rrf"]`` via ``channels`` -> rank lookup.
            entry.result.score = entry.rrf_score
            merged.append(entry.result)

        if max_results is not None:
            merged = merged[: max(1, int(max_results))]

        if self.config.log_channel_contributions:
            self._log_contributions(merged)

        return merged

    # ----------------------------------------------------------- introspection
    def _dedupe_channel_rows(
        self, rows: Sequence[SearchResult]
    ) -> List[SearchResult]:
        """Drop duplicate document/chunk identities within one channel."""

        deduped: List[SearchResult] = []
        seen: set[Tuple[str, str]] = set()
        for row in rows:
            key = self._dedup_identity(row)
            if key in seen:
                LOGGER.debug("RRFFusion: dropping duplicate identity %s", key)
                continue
            seen.add(key)
            deduped.append(row)
        return deduped

    @staticmethod
    def _dedup_identity(row: SearchResult) -> Tuple[str, str]:
        """Return the stable document/chunk identity used for RRF scoring."""

        if row.memory_id is not None:
            return ("memory_id", str(row.memory_id))
        if row.chunk_id is not None:
            return ("chunk_id", str(row.chunk_id))
        if row.uri:
            return ("uri", row.uri.strip().lower())
        return ("path", f"{row.domain}://{row.path}".strip().lower())

    @staticmethod
    def _channel_rank(row: SearchResult, fallback: int) -> int:
        try:
            rank = int(row.rank)
        except (TypeError, ValueError):
            rank = 0
        return rank if rank > 0 else fallback

    @staticmethod
    def _log_contributions(rows: Iterable[SearchResult]) -> None:
        for row in rows:
            meta = row.metadata.get("rrf", {})
            LOGGER.info(
                "RRF rank=%s uri=%s score=%.6f channels=%s k=%s",
                row.rank,
                row.uri,
                meta.get("score", row.score),
                meta.get("channels"),
                meta.get("k"),
            )


__all__ = [
    "DEFAULT_RRF_K",
    "DEFAULT_RRF_CHANNELS",
    "RRF_K_MIN",
    "RRF_K_MAX",
    "RRFConfigError",
    "RRFConfig",
    "RRFFusion",
    "load_rrf_config_from_env",
]
