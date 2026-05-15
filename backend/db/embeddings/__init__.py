"""Embedding-related helpers extracted from ``db.sqlite_client``.

Currently exposes:

- :class:`DriftDetectorConfig` / :class:`DriftDetector` -- compare the
  embedding configuration recorded in ``IndexMeta`` against the live
  environment so operators get a non-blocking warning (plus a queued
  reindex hint) when the embedding model or dimension changes between
  process restarts.

The package is additive: importing it does not modify any storage or
runtime state. Failures inside the drift detector are tolerated -- the
detector logs and returns a structured report; it never raises during
boot (constraint W2).
"""

from __future__ import annotations

from .drift_detector import (
    DriftDetectionResult,
    DriftDetector,
    DriftDetectorConfig,
)

__all__ = [
    "DriftDetectionResult",
    "DriftDetector",
    "DriftDetectorConfig",
]
