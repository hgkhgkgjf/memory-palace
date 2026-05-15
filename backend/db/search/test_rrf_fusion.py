"""Unit tests for :mod:`backend.db.search.rrf_fusion`.

These tests are pure: they construct :class:`SearchResult` rows by hand and
exercise the fusion logic without touching SQLite. Anything that crosses the
database boundary belongs in the benchmark harness instead.

Constraints under test:

- ``C5``: RRF is OFF by default (``RRFConfig().enabled`` is False) and ``k``
  is configurable.
- ``C6``: ``entity`` MUST be filtered out of the channel list.
- Formula correctness for the canonical k=60 case.
- Single-channel fallback when only one channel reports hits.
- Deduplication by URI across channels.
- Channel contribution logging shape under
  ``log_channel_contributions=True``.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import List

import pytest

# Ensure ``backend`` is importable when this file is executed in isolation
# (the rest of the test suite uses a conftest at backend/tests).
HERE = Path(__file__).resolve()
BACKEND_ROOT = HERE.parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from db.search.base_channel import SearchResult  # noqa: E402
from db.search.rrf_fusion import (  # noqa: E402
    DEFAULT_RRF_CHANNELS,
    DEFAULT_RRF_K,
    RRF_K_MAX,
    RRF_K_MIN,
    RRFConfig,
    RRFConfigError,
    RRFFusion,
    load_rrf_config_from_env,
)


def _make_result(uri: str, *, score: float = 0.5, priority: int = 0) -> SearchResult:
    """Build a minimal :class:`SearchResult` for fusion tests."""

    domain, _, path = uri.partition("://")
    return SearchResult(
        uri=uri,
        memory_id=hash(uri) & 0xFFFFFF,
        chunk_id=hash(uri) & 0xFFFF,
        chunk_text=f"text for {uri}",
        char_start=0,
        char_end=len(uri),
        domain=domain or "notes",
        path=path,
        priority=priority,
        disclosure=None,
        created_at=None,
        score=score,
    )


def _ranked(uris: List[str]) -> List[SearchResult]:
    """Helper: build a ranked list of results in the supplied order."""

    rows = [_make_result(uri) for uri in uris]
    for index, row in enumerate(rows, start=1):
        row.rank = index
    return rows


# --------------------------------------------------------------------- config


def test_rrf_default_is_off() -> None:
    """C5: feature flag MUST default to False."""

    config = RRFConfig()
    assert config.enabled is False
    assert config.k == DEFAULT_RRF_K
    assert config.channels == DEFAULT_RRF_CHANNELS


def test_rrf_config_filters_entity_channel() -> None:
    """C6: entity is rerank boost only and MUST be dropped from channels."""

    config = RRFConfig(channels=("fts5", "vector", "entity"))
    assert "entity" not in config.channels
    assert config.channels == ("fts5", "vector")


def test_rrf_config_from_env_respects_overrides() -> None:
    env = {
        "RRF_ENABLED": "true",
        "RRF_K": "20",
        "RRF_CHANNELS": "fts5,vector,entity",
    }
    config = RRFConfig.from_env(env)
    assert config.enabled is True
    assert config.k == 20
    assert "entity" not in config.channels  # C6
    assert config.channels == ("fts5", "vector")


def test_rrf_config_rejects_unknown_channel() -> None:
    env = {
        "RRF_ENABLED": "true",
        "RRF_CHANNELS": "fts5,unknown",
    }
    with pytest.raises(RRFConfigError, match="unsupported channel"):
        RRFConfig.from_env(env)


def test_rrf_config_rejects_entity_only_channel_list() -> None:
    with pytest.raises(RRFConfigError, match="at least one supported"):
        RRFConfig(channels=("entity",))


def test_rrf_config_from_env_default_on_missing() -> None:
    config = RRFConfig.from_env({})
    assert config.enabled is False
    assert config.k == DEFAULT_RRF_K
    assert config.channels == DEFAULT_RRF_CHANNELS


def test_load_rrf_config_helper_reads_os_environ(monkeypatch) -> None:
    monkeypatch.setenv("RRF_ENABLED", "1")
    monkeypatch.setenv("RRF_K", "15")
    monkeypatch.setenv("RRF_CHANNELS", "fts5,vector")
    config = load_rrf_config_from_env()
    assert config.enabled is True
    assert config.k == 15


def test_rrf_config_suggested_k_clamps() -> None:
    config = RRFConfig()
    assert config.suggested_k(0) == config.k  # falls back to stored k
    assert config.suggested_k(2) == RRF_K_MIN  # 2*2=4 -> clamped to 10
    assert config.suggested_k(20) == 40  # 2*20=40
    assert config.suggested_k(100) == RRF_K_MAX  # clamped


# ---------------------------------------------------------------- correctness


def test_rrf_formula_two_channels_same_doc() -> None:
    """Documents appearing in both channels MUST sum their RRF contributions."""

    fts = _ranked(["notes://a", "notes://b", "notes://c"])
    vec = _ranked(["notes://b", "notes://a", "notes://d"])
    fusion = RRFFusion(RRFConfig(enabled=True, k=60))
    merged = fusion.fuse({"fts5": fts, "vector": vec})

    uris = [r.uri for r in merged]
    # ``b`` and ``a`` both appear in both lists -- ``b`` is rank 1 in vec and
    # rank 2 in fts, ``a`` is rank 1 in fts and rank 2 in vec. Their RRF
    # scores tie, so deterministic ordering falls back to ``priority`` then
    # ``uri`` (alphabetical). ``a`` wins.
    assert uris[0] == "notes://a"
    assert uris[1] == "notes://b"
    # Solo docs (c, d) appear only once each -> lower score, behind both.
    assert set(uris) == {"notes://a", "notes://b", "notes://c", "notes://d"}

    top = merged[0]
    assert top.metadata["rrf"]["channels"] == {"fts5": 1, "vector": 2}
    expected_score = 1.0 / (60 + 1) + 1.0 / (60 + 2)
    assert top.metadata["rrf"]["score"] == pytest.approx(expected_score, rel=1e-9)
    assert top.score == pytest.approx(expected_score, rel=1e-9)


def test_rrf_k_value_impact_ordering_changes() -> None:
    """Small k concentrates weight on top ranks; large k flattens the curve."""

    # Channel A: ranks ``x`` first, then 4 distractors.
    chan_a = _ranked([
        "notes://x",
        "notes://d1",
        "notes://d2",
        "notes://d3",
        "notes://d4",
    ])
    # Channel B: ``y`` first, then ``x`` deep in the tail.
    chan_b = _ranked([
        "notes://y",
        "notes://d5",
        "notes://d6",
        "notes://d7",
        "notes://x",
    ])

    # With a tiny k, the rank-1 contribution dominates and ``y`` should win.
    small_k = RRFFusion(RRFConfig(enabled=True, k=1)).fuse(
        {"fts5": chan_a, "vector": chan_b}
    )
    # With a large k, the curve flattens and ``x`` -- which appears in both
    # channels -- accumulates enough to potentially overtake ``y``.
    large_k = RRFFusion(RRFConfig(enabled=True, k=60)).fuse(
        {"fts5": chan_a, "vector": chan_b}
    )
    # Specifically, ``x`` should rank no worse with large k than with small k.
    x_rank_small = next(i for i, r in enumerate(small_k) if r.uri == "notes://x")
    x_rank_large = next(i for i, r in enumerate(large_k) if r.uri == "notes://x")
    assert x_rank_large <= x_rank_small


def test_rrf_deduplicates_results_across_channels() -> None:
    fts = _ranked(["notes://a", "notes://b"])
    vec = _ranked(["notes://a", "notes://c"])
    merged = RRFFusion(RRFConfig(enabled=True, k=10)).fuse(
        {"fts5": fts, "vector": vec}
    )
    uris = [r.uri for r in merged]
    assert uris.count("notes://a") == 1
    assert set(uris) == {"notes://a", "notes://b", "notes://c"}


def test_rrf_dedup_identity_scores_same_memory_once_per_channel() -> None:
    """Same document/chunk identities must not contribute twice in one channel."""

    first = _make_result("notes://canonical")
    first.memory_id = 123
    first.chunk_id = 10
    duplicate = _make_result("notes://alias")
    duplicate.memory_id = 123
    duplicate.chunk_id = 11
    other = _make_result("notes://other")
    for index, row in enumerate([first, duplicate, other], start=1):
        row.rank = index

    vector_same_doc = _make_result("notes://vector-alias")
    vector_same_doc.memory_id = 123
    vector_same_doc.chunk_id = 12
    vector_same_doc.rank = 1

    merged = RRFFusion(RRFConfig(enabled=True, k=10)).fuse(
        {"fts5": [first, duplicate, other], "vector": [vector_same_doc]}
    )

    doc_rows = [row for row in merged if row.memory_id == 123]
    assert len(doc_rows) == 1
    assert doc_rows[0].metadata["rrf"]["channels"] == {"fts5": 1, "vector": 1}
    assert doc_rows[0].score == pytest.approx(2.0 / 11.0)


def test_rrf_single_channel_fallback_deduplicates_same_chunk() -> None:
    first = _make_result("notes://a")
    duplicate = _make_result("notes://a-duplicate")
    first.memory_id = None
    duplicate.memory_id = None
    first.chunk_id = 77
    duplicate.chunk_id = 77
    other = _make_result("notes://b")
    other.memory_id = None
    other.chunk_id = 88
    for index, row in enumerate([first, duplicate, other], start=1):
        row.rank = index

    merged = RRFFusion(RRFConfig(enabled=True, k=10)).fuse(
        {"fts5": [first, duplicate, other]}
    )

    assert [row.chunk_id for row in merged] == [77, 88]
    assert merged[0].metadata["rrf"]["channels"] == {"fts5": 1}


def test_rrf_max_results_truncation() -> None:
    fts = _ranked([f"notes://{c}" for c in "abcde"])
    vec = _ranked([f"notes://{c}" for c in "fghij"])
    merged = RRFFusion(RRFConfig(enabled=True, k=20)).fuse(
        {"fts5": fts, "vector": vec},
        max_results=3,
    )
    assert len(merged) == 3


# ------------------------------------------------------------- single channel


def test_rrf_single_channel_fallback_returns_input_order() -> None:
    fts = _ranked(["notes://a", "notes://b", "notes://c"])
    merged = RRFFusion(RRFConfig(enabled=True, k=60)).fuse({"fts5": fts})
    assert [r.uri for r in merged] == ["notes://a", "notes://b", "notes://c"]
    # The fallback path MUST flag itself in metadata for observability.
    assert merged[0].metadata["rrf"]["single_channel_fallback"] is True


def test_rrf_drops_empty_channels() -> None:
    fts = _ranked(["notes://a", "notes://b"])
    merged = RRFFusion(RRFConfig(enabled=True, k=60)).fuse(
        {"fts5": fts, "vector": []}
    )
    assert [r.uri for r in merged] == ["notes://a", "notes://b"]


def test_rrf_returns_empty_when_no_channels_match_allow_list() -> None:
    """C6: entity-only fusion request MUST yield ``[]``."""

    entity = _ranked(["notes://a", "notes://b"])
    merged = RRFFusion(RRFConfig(enabled=True, k=60)).fuse({"entity": entity})
    assert merged == []


# ---------------------------------------------------- channel contribution log


def test_rrf_log_channel_contributions_emits_records(caplog) -> None:
    fts = _ranked(["notes://a", "notes://b"])
    vec = _ranked(["notes://b", "notes://a"])
    fusion = RRFFusion(
        RRFConfig(enabled=True, k=10, log_channel_contributions=True)
    )
    with caplog.at_level(logging.INFO, logger="db.search.rrf_fusion"):
        merged = fusion.fuse({"fts5": fts, "vector": vec})
    assert len(merged) == 2
    # Both records should mention the RRF score.
    log_messages = "\n".join(record.message for record in caplog.records)
    assert "RRF rank=1" in log_messages
    assert "score=" in log_messages


def test_rrf_metadata_contains_per_channel_rank_breakdown() -> None:
    fts = _ranked(["notes://a", "notes://b"])
    vec = _ranked(["notes://b", "notes://a"])
    merged = RRFFusion(RRFConfig(enabled=True, k=60)).fuse(
        {"fts5": fts, "vector": vec}
    )
    for row in merged:
        meta = row.metadata.get("rrf")
        assert meta is not None
        assert set(meta["channels"].keys()) == {"fts5", "vector"}
        assert meta["k"] == 60
        assert meta["score"] > 0.0


# ----------------------------------------------------------- defaults & guard


def test_rrf_disabled_config_still_callable_for_dry_run() -> None:
    """Even with ``enabled=False`` the fusion method is callable.

    ``enabled`` is a contract flag for the *caller*; we do not gate the math
    inside :class:`RRFFusion` itself so dry-run benchmarks can compare metrics
    without flipping production behaviour.
    """

    fusion = RRFFusion(RRFConfig(enabled=False, k=30))
    merged = fusion.fuse(
        {
            "fts5": _ranked(["notes://a", "notes://b"]),
            "vector": _ranked(["notes://b", "notes://a"]),
        }
    )
    assert {r.uri for r in merged} == {"notes://a", "notes://b"}
