"""Runtime coordinators package (Round 1 facade-preserving extraction).

The legacy ``backend/runtime_state.py`` monolith remains the canonical
implementation site for coordinators (``WriteLaneCoordinator``,
``ReflectionLaneCoordinator``, ``IndexTaskWorker``, ``RuntimeState``, the
module-level ``runtime_state`` singleton, and friends).  This package
re-exports those symbols so callers can migrate to ``from runtime import
...`` over time without breaking existing ``from runtime_state import
...`` callers.

Round 1 intentionally does *not* move implementation: this package is a
re-export facade only.
"""

from __future__ import annotations

# Re-export the canonical implementations.  ``runtime.state`` mirrors the
# original module surface 1:1; importing it here guarantees that any side
# effect from the original module (singleton construction) has run once.
from . import state as state  # noqa: F401  (re-exported)
from .state import (
    # functions
    _env_float,
    _normalize_session_id,
    _normalize_runtime_search_text,
    _tokenize_query,
    # dataclasses / value objects
    SessionSearchHit,
    SessionRecentReadEntry,
    GuardDecisionEvent,
    ImportLearnAuditEvent,
    SessionPromotionEvent,
    CleanupReviewRecord,
    IndexTask,
    # coordinators / trackers
    WriteLaneCoordinator,
    ReflectionLaneCoordinator,
    SessionSearchCache,
    SessionRecentReadCache,
    SessionFlushTracker,
    GuardDecisionTracker,
    ImportLearnAuditTracker,
    SessionPromotionTracker,
    CleanupReviewCoordinator,
    VitalityDecayCoordinator,
    IndexTaskWorker,
    SleepTimeConsolidator,
    RuntimeState,
    # singleton
    runtime_state,
)


__all__ = [
    "state",
    "_env_float",
    "_normalize_session_id",
    "_normalize_runtime_search_text",
    "_tokenize_query",
    "SessionSearchHit",
    "SessionRecentReadEntry",
    "GuardDecisionEvent",
    "ImportLearnAuditEvent",
    "SessionPromotionEvent",
    "CleanupReviewRecord",
    "IndexTask",
    "WriteLaneCoordinator",
    "ReflectionLaneCoordinator",
    "SessionSearchCache",
    "SessionRecentReadCache",
    "SessionFlushTracker",
    "GuardDecisionTracker",
    "ImportLearnAuditTracker",
    "SessionPromotionTracker",
    "CleanupReviewCoordinator",
    "VitalityDecayCoordinator",
    "IndexTaskWorker",
    "SleepTimeConsolidator",
    "RuntimeState",
    "runtime_state",
]
