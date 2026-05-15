"""Embedding-provider drift detection.

This module compares the embedding configuration recorded in ``IndexMeta``
(the durable runtime metadata table used by :class:`SQLiteClient`) against
the live environment. When a mismatch is detected we:

1. Log a warning with the specific keys that drifted.
2. Set a ``drift_detected`` flag on the result object so the dashboard /
   ``index_status`` endpoint can surface it.
3. Queue a background reindex job via the supplied callable (typically a
   wrapper around the existing reindex maintenance task). The job is fire-
   and-forget; it MUST NOT block startup.
4. Return a structured :class:`DriftDetectionResult` for tests and logs.

The detector intentionally has no opinion on *what* should be reindexed --
the queueing callable is supplied by the caller so production code can pick
the appropriate scope (per-domain, per-priority, full corpus). For tests we
supply a recording stub.

Constraint W2: this module MUST NOT block process boot. The ``detect``
coroutine catches every exception, logs it, and returns a result with
``drift_detected=False, errors=[...]``. The caller decides whether to wait
on the background queue (typically: do not).
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
)

LOGGER = logging.getLogger(__name__)


#: Keys we compare between IndexMeta and the live environment. Each entry
#: maps the IndexMeta key to a callable returning the current env value as
#: a string. Stored values are always strings in IndexMeta.
DEFAULT_DRIFT_KEYS = (
    "embedding_backend",
    "embedding_model",
    "embedding_dim",
    "embedding_api_base",
)


@dataclass
class DriftDetectorConfig:
    """Configuration for :class:`DriftDetector`.

    Attributes:
        env_var_map: maps IndexMeta key -> env var to look up.
            ``embedding_dim`` resolves to the integer dim used by the
            client (``RETRIEVAL_EMBEDDING_DIM``).
        watched_keys: subset of :data:`DEFAULT_DRIFT_KEYS` that the
            detector should monitor. Defaults to all known keys.
        block_on_reindex: when True, the reindex job is awaited inline.
            Default False (W2: never block boot).
    """

    env_var_map: Mapping[str, str] = field(
        default_factory=lambda: {
            "embedding_backend": "RETRIEVAL_EMBEDDING_BACKEND",
            "embedding_model": "RETRIEVAL_EMBEDDING_MODEL",
            "embedding_dim": "RETRIEVAL_EMBEDDING_DIM",
            "embedding_api_base": "RETRIEVAL_EMBEDDING_API_BASE",
        }
    )
    watched_keys: tuple = DEFAULT_DRIFT_KEYS
    block_on_reindex: bool = False


@dataclass
class DriftDetectionResult:
    """Outcome of a single :meth:`DriftDetector.detect` call."""

    drift_detected: bool = False
    differences: Dict[str, Dict[str, str]] = field(default_factory=dict)
    reindex_queued: bool = False
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "drift_detected": self.drift_detected,
            "differences": dict(self.differences),
            "reindex_queued": self.reindex_queued,
            "errors": list(self.errors),
        }


# Type aliases for clarity.
ReadIndexMetaCallable = Callable[[str], Awaitable[Optional[str]]]
ReindexQueueCallable = Callable[[Dict[str, Dict[str, str]]], Awaitable[None]]
DetectionCallback = Callable[[DriftDetectionResult], None]


class DriftDetector:
    """Detect embedding-provider drift between IndexMeta and the environment.

    Typical usage from inside :class:`SQLiteClient.init_db`::

        detector = DriftDetector(
            read_index_meta=client.get_runtime_meta,
            queue_reindex=client._queue_background_reindex,  # fire-and-forget
        )
        result = await detector.detect()
        client._drift_detection_result = result

    The detector does **not** touch the database directly; it goes through
    ``read_index_meta`` so tests can provide an in-memory stub and so the
    same code can be reused by background diagnostic jobs.
    """

    def __init__(
        self,
        *,
        read_index_meta: ReadIndexMetaCallable,
        queue_reindex: Optional[ReindexQueueCallable] = None,
        config: Optional[DriftDetectorConfig] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._read_index_meta = read_index_meta
        self._queue_reindex = queue_reindex
        self._config = config or DriftDetectorConfig()
        self._env: Mapping[str, str] = env if env is not None else os.environ

    # ------------------------------------------------------------------ core
    def start_nonblocking(
        self,
        *,
        on_complete: Optional[DetectionCallback] = None,
        task_name: str = "memory-palace-drift-detection",
    ) -> Optional[asyncio.Task[DriftDetectionResult]]:
        """Schedule drift detection without blocking startup.

        Returns the created task when called inside a running event loop.
        ``on_complete`` is invoked with the structured result after detection
        finishes; callback failures are logged and swallowed.
        """

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            LOGGER.warning(
                "drift_detector: cannot start nonblocking detection without "
                "a running event loop"
            )
            return None

        task = loop.create_task(self.detect(), name=task_name)
        task.add_done_callback(
            lambda completed: self._handle_detection_task(completed, on_complete)
        )
        return task

    async def detect(self) -> DriftDetectionResult:
        """Compare stored vs live values and react to mismatches.

        Returns a :class:`DriftDetectionResult`. Never raises. When drift is
        detected, this method queues a background reindex via
        ``queue_reindex`` (if supplied) and returns immediately.
        """

        result = DriftDetectionResult()
        differences: Dict[str, Dict[str, str]] = {}

        for key in self._config.watched_keys:
            try:
                stored = await self._read_index_meta(key)
            except Exception as exc:  # noqa: BLE001 -- detector must not raise.
                LOGGER.warning(
                    "drift_detector: failed reading IndexMeta key=%s: %s", key, exc
                )
                result.errors.append(f"read_failed:{key}")
                continue

            env_name = self._config.env_var_map.get(key)
            live_value = self._env.get(env_name, "") if env_name else ""
            stored_normalised = self._normalise(stored)
            live_normalised = self._normalise(live_value)

            # Skip when stored is empty (fresh DB) or both sides are empty:
            # there is no "previous" config to drift away from.
            if not stored_normalised:
                continue
            if stored_normalised == live_normalised:
                continue
            differences[key] = {
                "stored": stored_normalised,
                "live": live_normalised,
                "env_var": env_name or "",
            }

        result.differences = differences
        result.drift_detected = bool(differences)

        if result.drift_detected:
            LOGGER.warning(
                "embedding provider drift detected: %s -- queueing reindex",
                ", ".join(sorted(differences.keys())),
            )
            if self._queue_reindex is not None:
                try:
                    if self._config.block_on_reindex:
                        await self._queue_reindex(differences)
                    else:
                        # Schedule the reindex without awaiting it. The
                        # caller continues to boot.
                        asyncio.create_task(self._run_reindex_queue(differences))
                    result.reindex_queued = True
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning(
                        "drift_detector: failed to queue reindex: %s", exc
                    )
                    result.errors.append(f"queue_failed:{type(exc).__name__}")
                    result.reindex_queued = False

        return result

    # ----------------------------------------------------------- helpers
    async def _run_reindex_queue(self, differences: Dict[str, Dict[str, str]]) -> None:
        if self._queue_reindex is None:
            return
        try:
            await self._queue_reindex(differences)
        except Exception as exc:  # noqa: BLE001 -- background task must not leak.
            LOGGER.warning("drift_detector: background reindex failed: %s", exc)

    @staticmethod
    def _handle_detection_task(
        task: "asyncio.Task[DriftDetectionResult]",
        on_complete: Optional[DetectionCallback],
    ) -> None:
        try:
            result = task.result()
        except Exception as exc:  # noqa: BLE001 -- defensive; detect() should not raise.
            LOGGER.warning("drift_detector: background detection failed: %s", exc)
            return
        if on_complete is None:
            return
        try:
            on_complete(result)
        except Exception as exc:  # noqa: BLE001 -- callback must not affect startup.
            LOGGER.warning("drift_detector: completion callback failed: %s", exc)

    @staticmethod
    def _normalise(value: Optional[str]) -> str:
        """Normalise a stored/live value for equality comparison.

        - ``None`` becomes ``""``.
        - Strings are stripped and lowercased.
        - Numeric strings are coerced to their canonical integer form so
          ``"768"`` and ``"768.0"`` compare equal.
        """

        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        # Try integer coercion for dimension-like keys.
        try:
            return str(int(float(text)))
        except (TypeError, ValueError):
            return text.lower()


__all__ = [
    "DriftDetector",
    "DriftDetectorConfig",
    "DriftDetectionResult",
]
