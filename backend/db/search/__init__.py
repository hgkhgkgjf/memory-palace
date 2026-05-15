"""Search channels package.

This package exposes modular search "channels" extracted from
``backend/db/sqlite_client.py``. Each channel is a thin wrapper that delegates
to existing :class:`SQLiteClient` helpers so the production search pipeline
(``search_advanced``) remains untouched while still allowing offline
experiments such as the Reciprocal Rank Fusion (RRF) calibration harness.

Public surface:

- :class:`SearchResult` -- chunk-level dataclass shared across channels.
- :class:`BaseChannel` -- abstract base class for future channels (e.g. entity).
- :class:`FTS5Channel` -- BM25 keyword channel built on the FTS5 virtual table.
- :class:`VectorChannel` -- cosine-similarity semantic channel with dim-mismatch fallback.
- :class:`RRFConfig`, :class:`RRFFusion` -- configurable Reciprocal Rank Fusion.

The channels are intentionally additive: ``sqlite_client.search_advanced`` is
*not* modified. New consumers (offline benchmarks, future entity rerank)
build on these channels behind a feature flag (default OFF).
"""

from __future__ import annotations

from .base_channel import BaseChannel, SearchResult
from .entity_channel import ExtractedEntity, compute_boost, extract_entities
from .fts5_channel import FTS5Channel
from .rrf_fusion import RRFConfig, RRFFusion, load_rrf_config_from_env
from .vector_channel import VectorChannel

__all__ = [
    "BaseChannel",
    "SearchResult",
    "FTS5Channel",
    "VectorChannel",
    "RRFConfig",
    "RRFFusion",
    "load_rrf_config_from_env",
    "ExtractedEntity",
    "extract_entities",
    "compute_boost",
]
