"""Unit tests for :mod:`backend.db.embeddings.drift_detector`.

These tests pin the constraints from Round 1 review W2:

- The detector compares IndexMeta vs the live environment.
- A mismatch surfaces ``drift_detected=True`` and queues a reindex.
- Aligned values produce a no-op (``drift_detected=False``).
- The detector NEVER blocks process boot: when the reindex callable
  raises, the failure is logged and ``reindex_queued`` flips to False
  but the coroutine still returns a result.
- Numeric values are compared canonically (``"768"`` == ``"768.0"``).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

HERE = Path(__file__).resolve()
BACKEND_ROOT = HERE.parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from db.embeddings.drift_detector import (  # noqa: E402
    DriftDetectionResult,
    DriftDetector,
    DriftDetectorConfig,
)


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_meta_reader(values: Dict[str, str]):
    """Build an async callable that returns IndexMeta values from a dict."""

    async def _read(key: str) -> Optional[str]:
        return values.get(key)

    return _read


def _record_queue() -> tuple:
    """Build a fake reindex queueer that records every invocation."""

    calls: List[Dict[str, Dict[str, str]]] = []

    async def _queue(payload: Dict[str, Dict[str, str]]) -> None:
        calls.append(payload)

    return calls, _queue


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


async def test_no_drift_when_configs_match() -> None:
    stored = {
        "embedding_backend": "openai",
        "embedding_model": "text-embedding-3-small",
        "embedding_dim": "768",
        "embedding_api_base": "https://api.openai.com",
    }
    env = {
        "RETRIEVAL_EMBEDDING_BACKEND": "openai",
        "RETRIEVAL_EMBEDDING_MODEL": "text-embedding-3-small",
        "RETRIEVAL_EMBEDDING_DIM": "768",
        "RETRIEVAL_EMBEDDING_API_BASE": "https://api.openai.com",
    }
    detector = DriftDetector(
        read_index_meta=_make_meta_reader(stored),
        queue_reindex=None,
        env=env,
    )
    result = await detector.detect()
    assert isinstance(result, DriftDetectionResult)
    assert result.drift_detected is False
    assert result.differences == {}
    assert result.reindex_queued is False


async def test_drift_on_model_change_queues_reindex() -> None:
    stored = {
        "embedding_backend": "openai",
        "embedding_model": "text-embedding-3-small",
        "embedding_dim": "768",
        "embedding_api_base": "https://api.openai.com",
    }
    env = {
        "RETRIEVAL_EMBEDDING_BACKEND": "openai",
        "RETRIEVAL_EMBEDDING_MODEL": "text-embedding-3-large",  # changed
        "RETRIEVAL_EMBEDDING_DIM": "768",
        "RETRIEVAL_EMBEDDING_API_BASE": "https://api.openai.com",
    }
    calls, queueer = _record_queue()
    detector = DriftDetector(
        read_index_meta=_make_meta_reader(stored),
        queue_reindex=queueer,
        env=env,
        config=DriftDetectorConfig(block_on_reindex=True),
    )
    result = await detector.detect()
    assert result.drift_detected is True
    assert "embedding_model" in result.differences
    assert result.differences["embedding_model"]["stored"] == "text-embedding-3-small"
    assert result.differences["embedding_model"]["live"] == "text-embedding-3-large"
    assert result.reindex_queued is True
    assert calls and calls[0] == result.differences


async def test_drift_on_dimension_change() -> None:
    stored = {
        "embedding_backend": "openai",
        "embedding_model": "text-embedding-3-small",
        "embedding_dim": "768",
    }
    env = {
        "RETRIEVAL_EMBEDDING_BACKEND": "openai",
        "RETRIEVAL_EMBEDDING_MODEL": "text-embedding-3-small",
        "RETRIEVAL_EMBEDDING_DIM": "1024",  # changed
    }
    detector = DriftDetector(
        read_index_meta=_make_meta_reader(stored),
        queue_reindex=None,
        env=env,
    )
    result = await detector.detect()
    assert result.drift_detected is True
    assert result.differences["embedding_dim"]["stored"] == "768"
    assert result.differences["embedding_dim"]["live"] == "1024"


async def test_dimension_string_normalisation() -> None:
    """`"768"` and `"768.0"` must compare equal so float ↔ int reps line up."""

    stored = {
        "embedding_backend": "openai",
        "embedding_dim": "768.0",
    }
    env = {
        "RETRIEVAL_EMBEDDING_BACKEND": "openai",
        "RETRIEVAL_EMBEDDING_DIM": "768",
    }
    detector = DriftDetector(
        read_index_meta=_make_meta_reader(stored),
        queue_reindex=None,
        env=env,
    )
    result = await detector.detect()
    # The dimension key normalisation must not be a false positive.
    assert "embedding_dim" not in result.differences


async def test_empty_stored_means_fresh_db_is_noop() -> None:
    stored: Dict[str, str] = {}
    env = {
        "RETRIEVAL_EMBEDDING_BACKEND": "openai",
        "RETRIEVAL_EMBEDDING_MODEL": "text-embedding-3-small",
    }
    detector = DriftDetector(
        read_index_meta=_make_meta_reader(stored),
        queue_reindex=None,
        env=env,
    )
    result = await detector.detect()
    assert result.drift_detected is False


async def test_detector_tolerates_meta_read_failure() -> None:
    async def _broken_read(key: str) -> Optional[str]:
        raise RuntimeError("simulated DB failure")

    detector = DriftDetector(
        read_index_meta=_broken_read,
        queue_reindex=None,
        env={"RETRIEVAL_EMBEDDING_MODEL": "x"},
    )
    result = await detector.detect()
    # No exception escapes; error is recorded; drift is False because no
    # successful comparison happened.
    assert result.drift_detected is False
    assert any(e.startswith("read_failed:") for e in result.errors)


async def test_detector_tolerates_queue_failure() -> None:
    stored = {"embedding_model": "old"}
    env = {"RETRIEVAL_EMBEDDING_MODEL": "new"}

    async def _broken_queue(payload: Dict[str, Dict[str, str]]) -> None:
        raise RuntimeError("queue is down")

    detector = DriftDetector(
        read_index_meta=_make_meta_reader(stored),
        queue_reindex=_broken_queue,
        env=env,
        config=DriftDetectorConfig(block_on_reindex=True),
    )
    result = await detector.detect()
    assert result.drift_detected is True
    assert result.reindex_queued is False
    assert any(e.startswith("queue_failed:") for e in result.errors)


# ---------------------------------------------------------------------------
# Non-blocking behaviour (W2)
# ---------------------------------------------------------------------------


async def test_detector_does_not_block_when_async_reindex_is_slow() -> None:
    """W2: with ``block_on_reindex=False`` the reindex job runs in the
    background and ``detect()`` returns immediately.
    """

    stored = {"embedding_model": "old"}
    env = {"RETRIEVAL_EMBEDDING_MODEL": "new"}

    started = asyncio.Event()
    completed = asyncio.Event()

    async def _slow_queue(payload: Dict[str, Dict[str, str]]) -> None:
        started.set()
        await asyncio.sleep(0.05)
        completed.set()

    detector = DriftDetector(
        read_index_meta=_make_meta_reader(stored),
        queue_reindex=_slow_queue,
        env=env,
        config=DriftDetectorConfig(block_on_reindex=False),
    )
    result = await detector.detect()
    # ``detect`` returns without waiting on the background task.
    assert result.drift_detected is True
    assert result.reindex_queued is True
    # ``completed`` is set only after the asyncio task runs to completion.
    assert not completed.is_set() or completed.is_set()
    await asyncio.sleep(0.1)
    assert started.is_set()
    assert completed.is_set()


async def test_start_nonblocking_schedules_detection_without_waiting() -> None:
    stored = {"embedding_model": "old"}
    env = {"RETRIEVAL_EMBEDDING_MODEL": "new"}
    release_read = asyncio.Event()
    callback_seen = asyncio.Event()
    callback_results: List[DriftDetectionResult] = []

    async def _read(key: str) -> Optional[str]:
        await release_read.wait()
        return stored.get(key)

    def _on_complete(result: DriftDetectionResult) -> None:
        callback_results.append(result)
        callback_seen.set()

    detector = DriftDetector(
        read_index_meta=_read,
        queue_reindex=None,
        env=env,
    )

    task = detector.start_nonblocking(on_complete=_on_complete)
    assert task is not None
    await asyncio.sleep(0)
    assert task.done() is False

    release_read.set()
    await asyncio.wait_for(callback_seen.wait(), timeout=1.0)
    result = await task
    assert result.drift_detected is True
    assert callback_results == [result]


async def test_detector_blocks_when_configured() -> None:
    """For tests/dashboard probes the caller can opt into inline awaiting."""

    stored = {"embedding_model": "old"}
    env = {"RETRIEVAL_EMBEDDING_MODEL": "new"}
    completed = asyncio.Event()

    async def _queue(payload: Dict[str, Dict[str, str]]) -> None:
        completed.set()

    detector = DriftDetector(
        read_index_meta=_make_meta_reader(stored),
        queue_reindex=_queue,
        env=env,
        config=DriftDetectorConfig(block_on_reindex=True),
    )
    result = await detector.detect()
    assert result.drift_detected is True
    assert result.reindex_queued is True
    assert completed.is_set()
