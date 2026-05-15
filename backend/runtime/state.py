"""Re-export shim for the legacy ``runtime_state`` module.

This module exists so the ``runtime`` package can offer a stable import
surface (``from runtime.state import ...``) during Round 1 of the
facade-preserving refactor.  The canonical implementation still lives in
``backend/runtime_state.py``; nothing is moved here.  Importing this
module is equivalent to importing the top-level ``runtime_state`` module,
including its module-level ``runtime_state`` singleton.

The wildcard re-export below pulls in every public name defined in the
original module so future code can depend on ``runtime.state`` without
needing to track new additions.
"""

from __future__ import annotations

# NOTE: ``runtime_state`` is the *original* module name (kept for BC).  We
# do a star-import so any new symbol added there is automatically visible
# here without further maintenance.
from runtime_state import *  # noqa: F401,F403  (re-export shim)

# Explicit re-exports for tooling that does not follow wildcards.  Keeping
# this list in sync with ``runtime/__init__.py`` makes static analysis
# happier and gives readers a quick map of the public surface.
from runtime_state import (  # noqa: F401  (explicit re-exports)
    _env_float,
    _normalize_session_id,
    _normalize_runtime_search_text,
    _tokenize_query,
    SessionSearchHit,
    SessionRecentReadEntry,
    WriteLaneCoordinator,
    ReflectionLaneCoordinator,
    SessionSearchCache,
    SessionRecentReadCache,
    SessionFlushTracker,
    GuardDecisionEvent,
    GuardDecisionTracker,
    ImportLearnAuditEvent,
    ImportLearnAuditTracker,
    SessionPromotionEvent,
    SessionPromotionTracker,
    CleanupReviewRecord,
    CleanupReviewCoordinator,
    VitalityDecayCoordinator,
    IndexTask,
    IndexTaskWorker,
    SleepTimeConsolidator,
    RuntimeState,
    runtime_state,
)
