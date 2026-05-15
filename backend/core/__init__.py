"""Backend ``core`` package — derivation + forgetting engines.

This package hosts the Round 2 building blocks that turn the
existing memory store into a layered memory system:

* :mod:`core.layering_engine` — produces L2 summaries from L1
  memories. Read-only via the public API; the only writer is the
  internal job that ``generate_summary`` triggers explicitly. Every
  row emitted carries the full provenance contract documented in
  ``docs/superpowers/rfcs/derived-memory-contract.md``.

* :mod:`core.forgetting_engine` — runs vitality decay as a SIMULATION
  and exposes a candidate queue. **No auto-delete.** Archiving a
  memory requires a human-approved review token routed through the
  same flow that ``backend/api/review.py`` already uses.

Both modules are intentionally small, dependency-light, and import
nothing from ``backend/api`` — the API layer wires them up, not the
other way around.
"""

from .layering_engine import (
    DerivationMethod,
    LayeringEngine,
    MemorySummaryDraft,
    ReviewState,
    SummarySource,
    sha256_text,
)
from .forgetting_engine import (
    ArchiveResult,
    DecaySimulation,
    ForgettingCandidate,
    ForgettingEngine,
)
from .compression_engine import (
    AGGRESSIVE_BUDGET,
    CompressionEngine,
    CompressionPreview,
    EMERGENCY_BUDGET,
    MILD_BUDGET,
    MemoryCompressionCandidate,
    compression_preview_enabled,
)
from .procedural_engine import (
    ProceduralDerivationMethod,
    ProceduralDraft,
    ProceduralEngine,
    ProceduralReviewState,
)
from .facade import MemoryCore

__all__ = [
    "DerivationMethod",
    "LayeringEngine",
    "MemoryCore",
    "MemorySummaryDraft",
    "ReviewState",
    "SummarySource",
    "sha256_text",
    "ArchiveResult",
    "DecaySimulation",
    "ForgettingCandidate",
    "ForgettingEngine",
    "AGGRESSIVE_BUDGET",
    "CompressionEngine",
    "CompressionPreview",
    "EMERGENCY_BUDGET",
    "MILD_BUDGET",
    "MemoryCompressionCandidate",
    "compression_preview_enabled",
    "ProceduralDerivationMethod",
    "ProceduralDraft",
    "ProceduralEngine",
    "ProceduralReviewState",
]
