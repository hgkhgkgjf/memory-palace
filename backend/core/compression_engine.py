"""Cascade compression preview — read-only in v1.

This engine answers a single question:

    "If the context budget hits N% utilization, which memories *would*
     be compressed at which severity tier?"

It does NOT modify any row, never writes to ``memory_gists`` /
``memory_summaries`` / ``archived_memories``, and never enqueues a job.
The dashboard is expected to call :meth:`CompressionEngine.preview_cascade`
to render a "what-if" view, and to gate any actual compression behind an
explicit, human-approved follow-up action.

The cascade has three tiers, mirroring the Round 3 plan:

* **mild** — budget usage above ``MILD_BUDGET`` (default 0.50). Memories in
  this tier *would* have their bodies replaced by an existing gist when
  rendered into the context window. (No row is rewritten; this is purely a
  rendering hint.)
* **aggressive** — budget usage above ``AGGRESSIVE_BUDGET`` (default 0.85).
  Memories in this tier *would* be folded into a topic summary by the
  layering engine. (Again, no immediate write — the summary draft would
  still go through the existing C3 provenance contract.)
* **emergency** — budget usage above ``EMERGENCY_BUDGET`` (default 0.95).
  Memories in this tier *would* be hard-pruned (moved to
  ``archived_memories`` via the existing forgetting engine review-token
  flow). This tier is only reached when the system is genuinely about to
  spill its budget; even then the engine simply *previews* the candidate
  set.

A `replaceability score` orders the candidate set within each tier. Memories
with a high score (cold + low access + non-critical type) are previewed
first; pinned / critical / "do-not-forget" memories are *exempt* from every
tier regardless of decay arithmetic.

Constraint C2 (no auto-delete) and the v1 read-only invariant are both
enforced structurally: the engine is constructed with an *async* session
factory but only ever issues ``SELECT`` statements through it. The unit
tests verify the no-mutation invariant by snapshotting every table the
engine touches and asserting bit-equality afterwards.

Environment flag: ``COMPRESSION_PREVIEW_ENABLED`` defaults to ``"false"``.
Callers should consult :func:`compression_preview_enabled` before showing
the preview surface; the function never raises and always returns ``bool``.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

import sqlalchemy as sa


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- constants


MILD_BUDGET = 0.50
AGGRESSIVE_BUDGET = 0.85
EMERGENCY_BUDGET = 0.95

# Replaceability score range; higher = better candidate for cascade.
SCORE_MIN = 0.0
SCORE_MAX = 10.0

# Score weights — kept small and explicit so reviewers can sanity-check
# the math without reading the source.
_W_AGE_PER_DAY = 0.02       # +0.02 per idle-day, capped.
_W_AGE_CAP = 4.0            # No more than +4.0 from age alone.
_W_ACCESS_FACTOR = 3.5      # Subtract up to 3.5 for frequently accessed rows.
_W_LOW_PRIORITY = 1.5       # Bonus when the path priority is <= 0.
_W_TYPE_NOTE = 0.5          # Tiny bias against "notes" domain (cheap-to-redo).
_W_PINNED_EXEMPT = math.inf  # Score is forced to -inf when pinned.

# Domains we treat as critical and exempt by default. The dashboard can
# always override per-row via ``critical_memory_ids``.
_CRITICAL_DOMAINS: tuple[str, ...] = ("core",)


# -------------------------------------------------------------------- env


def compression_preview_enabled() -> bool:
    """Return ``True`` only when ``COMPRESSION_PREVIEW_ENABLED`` is truthy.

    Treats the canonical truthy strings (``"1"``, ``"true"``, ``"yes"``,
    ``"on"``) case-insensitively. Everything else (including the unset
    case) returns ``False``. The default is intentionally opt-in so the
    preview surface only appears when an operator wants it.
    """
    raw = os.getenv("COMPRESSION_PREVIEW_ENABLED", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


# ------------------------------------------------------------- dataclasses


@dataclass(frozen=True)
class MemoryCompressionCandidate:
    """One memory's projected position in the cascade.

    The dashboard renders this verbatim; the API layer is expected to
    serialize via :meth:`to_api` (a plain dict).
    """

    memory_id: int
    replaceability_score: float
    age_days: float
    access_count: int
    priority: int
    pinned: bool
    domain: str
    tier: str  # 'mild' | 'aggressive' | 'emergency' | 'exempt'
    reason: str

    def to_api(self) -> Dict[str, Any]:
        return {
            "memory_id": int(self.memory_id),
            "replaceability_score": float(self.replaceability_score),
            "age_days": float(self.age_days),
            "access_count": int(self.access_count),
            "priority": int(self.priority),
            "pinned": bool(self.pinned),
            "domain": str(self.domain),
            "tier": str(self.tier),
            "reason": str(self.reason),
        }


@dataclass(frozen=True)
class CompressionPreview:
    """Top-level preview payload.

    ``mild``, ``aggressive``, and ``emergency`` each contain at most
    ``per_tier_limit`` candidates ordered by descending
    ``replaceability_score``. ``exempt`` lists protected memories that
    would NOT be touched at this budget level even if the arithmetic
    suggested otherwise.
    """

    budget_usage: float
    tier_thresholds: Dict[str, float]
    mild: List[MemoryCompressionCandidate]
    aggressive: List[MemoryCompressionCandidate]
    emergency: List[MemoryCompressionCandidate]
    exempt: List[MemoryCompressionCandidate]
    notes: List[str] = field(default_factory=list)

    def to_api(self) -> Dict[str, Any]:
        return {
            "budget_usage": float(self.budget_usage),
            "tier_thresholds": {k: float(v) for k, v in self.tier_thresholds.items()},
            "mild": [c.to_api() for c in self.mild],
            "aggressive": [c.to_api() for c in self.aggressive],
            "emergency": [c.to_api() for c in self.emergency],
            "exempt": [c.to_api() for c in self.exempt],
            "notes": list(self.notes),
        }


# ------------------------------------------------------------------ engine


class CompressionEngine:
    """Preview-only cascade compression decisions.

    All public methods are pure reads. The engine deliberately mirrors
    the :class:`~core.forgetting_engine.ForgettingEngine` constructor
    shape so it can be wired up next to it in :mod:`backend.api` without
    growing a parallel session-factory surface.
    """

    def __init__(
        self,
        session_factory: Any,
        *,
        mild_budget: float = MILD_BUDGET,
        aggressive_budget: float = AGGRESSIVE_BUDGET,
        emergency_budget: float = EMERGENCY_BUDGET,
        per_tier_limit: int = 25,
        pinned_memory_ids: Optional[Iterable[int]] = None,
        critical_domains: Sequence[str] = _CRITICAL_DOMAINS,
    ) -> None:
        if not 0.0 <= mild_budget < aggressive_budget < emergency_budget <= 1.0:
            raise ValueError(
                "compression budget thresholds must satisfy "
                "0 <= mild < aggressive < emergency <= 1"
            )
        if per_tier_limit <= 0:
            raise ValueError("per_tier_limit must be positive")
        self._session_factory = session_factory
        self._mild_budget = float(mild_budget)
        self._aggressive_budget = float(aggressive_budget)
        self._emergency_budget = float(emergency_budget)
        self._per_tier_limit = int(per_tier_limit)
        self._pinned_ids = frozenset(int(mid) for mid in (pinned_memory_ids or ()))
        self._critical_domains = frozenset(d for d in critical_domains if d)

    # ----------------------------------------------------------- public API

    async def preview_cascade(
        self,
        budget_usage: float,
        *,
        limit: int = 200,
    ) -> CompressionPreview:
        """Project which memories *would* be compressed at ``budget_usage``.

        The return value is a :class:`CompressionPreview` instance. No row
        in the database is modified.

        Parameters
        ----------
        budget_usage:
            Float in ``[0, 1]``. Values outside the range are clamped.
        limit:
            Maximum number of memories the engine considers (per tier
            then truncated by ``per_tier_limit``). Default 200, matching
            the existing :class:`ForgettingEngine` cap.
        """
        usage = max(0.0, min(1.0, float(budget_usage)))
        candidates = await self._load_candidates(limit=limit)

        mild: List[MemoryCompressionCandidate] = []
        aggressive: List[MemoryCompressionCandidate] = []
        emergency: List[MemoryCompressionCandidate] = []
        exempt: List[MemoryCompressionCandidate] = []

        for cand in candidates:
            scored = self._score_candidate(cand, usage)
            tier = scored.tier
            if tier == "exempt":
                exempt.append(scored)
                continue
            if tier == "mild":
                mild.append(scored)
            elif tier == "aggressive":
                aggressive.append(scored)
            elif tier == "emergency":
                emergency.append(scored)

        # Sort highest replaceability first, then truncate per the
        # configured limit.
        mild.sort(key=lambda c: c.replaceability_score, reverse=True)
        aggressive.sort(key=lambda c: c.replaceability_score, reverse=True)
        emergency.sort(key=lambda c: c.replaceability_score, reverse=True)
        mild = mild[: self._per_tier_limit]
        aggressive = aggressive[: self._per_tier_limit]
        emergency = emergency[: self._per_tier_limit]

        notes: List[str] = []
        if usage < self._mild_budget:
            notes.append(
                "Budget usage below mild threshold; no cascade actions are previewed."
            )
        if not compression_preview_enabled():
            notes.append(
                "COMPRESSION_PREVIEW_ENABLED is false; this preview is "
                "for diagnostic use only."
            )

        return CompressionPreview(
            budget_usage=usage,
            tier_thresholds={
                "mild": self._mild_budget,
                "aggressive": self._aggressive_budget,
                "emergency": self._emergency_budget,
            },
            mild=mild,
            aggressive=aggressive,
            emergency=emergency,
            exempt=exempt,
            notes=notes,
        )

    def compute_replaceability_score(
        self,
        memory: Dict[str, Any],
    ) -> float:
        """Pure-function replaceability score in ``[SCORE_MIN, SCORE_MAX]``.

        Exposed as a standalone method so the dashboard, tests, and
        downstream tooling can score arbitrary dicts without going
        through the database round-trip. Pinned / critical memories
        return ``-inf`` so they sort to the bottom of any cascade list.
        """
        pinned = bool(memory.get("pinned"))
        if pinned or int(memory.get("memory_id", 0)) in self._pinned_ids:
            return -math.inf
        domain = str(memory.get("domain") or "").strip()
        if domain in self._critical_domains:
            return -math.inf

        age_days = float(memory.get("age_days") or 0.0)
        access_count = int(memory.get("access_count") or 0)
        priority = int(memory.get("priority") or 0)

        # Age contribution — older = more replaceable, capped.
        age_score = min(_W_AGE_CAP, max(0.0, age_days) * _W_AGE_PER_DAY)
        # Access contribution — frequent access *reduces* replaceability.
        # Use log1p so a row with 50 accesses doesn't blow out the score.
        access_penalty = _W_ACCESS_FACTOR * math.log1p(max(0, access_count)) / math.log1p(100)
        # Priority contribution — low-priority paths are easier to drop.
        priority_bonus = _W_LOW_PRIORITY if priority <= 0 else 0.0
        # Domain contribution — "notes" are cheap to regenerate.
        type_bonus = _W_TYPE_NOTE if domain == "notes" else 0.0

        raw_score = age_score - access_penalty + priority_bonus + type_bonus
        # Clamp to the documented range.
        return max(SCORE_MIN, min(SCORE_MAX, raw_score))

    # --------------------------------------------------------- internals

    def _score_candidate(
        self,
        memory: Dict[str, Any],
        budget_usage: float,
    ) -> MemoryCompressionCandidate:
        score = self.compute_replaceability_score(memory)
        domain = str(memory.get("domain") or "core").strip() or "core"
        memory_id = int(memory.get("memory_id") or memory.get("id") or 0)
        pinned = bool(memory.get("pinned")) or memory_id in self._pinned_ids
        critical = domain in self._critical_domains

        # Compute the tier from budget_usage. Exempt rows short-circuit.
        if pinned or critical or score == -math.inf:
            tier = "exempt"
            reason = (
                "memory is pinned"
                if pinned
                else f"domain={domain!r} is critical"
            )
            tier_score = SCORE_MIN
        elif budget_usage >= self._emergency_budget:
            tier = "emergency"
            reason = (
                f"budget usage {budget_usage:.2f} >= emergency "
                f"{self._emergency_budget:.2f}"
            )
            tier_score = score
        elif budget_usage >= self._aggressive_budget:
            tier = "aggressive"
            reason = (
                f"budget usage {budget_usage:.2f} >= aggressive "
                f"{self._aggressive_budget:.2f}"
            )
            tier_score = score
        elif budget_usage >= self._mild_budget:
            tier = "mild"
            reason = (
                f"budget usage {budget_usage:.2f} >= mild "
                f"{self._mild_budget:.2f}"
            )
            tier_score = score
        else:
            tier = "exempt"
            reason = (
                f"budget usage {budget_usage:.2f} below mild threshold "
                f"{self._mild_budget:.2f}"
            )
            tier_score = score

        return MemoryCompressionCandidate(
            memory_id=memory_id,
            replaceability_score=float(tier_score),
            age_days=float(memory.get("age_days") or 0.0),
            access_count=int(memory.get("access_count") or 0),
            priority=int(memory.get("priority") or 0),
            pinned=pinned,
            domain=domain,
            tier=tier,
            reason=reason,
        )

    async def _load_candidates(self, *, limit: int = 200) -> List[Dict[str, Any]]:
        """Load candidate memory rows (read-only).

        Returns enriched dicts with ``age_days``, ``priority``, and
        ``domain`` already resolved so the scoring function can stay
        pure. We deliberately use a single LEFT JOIN against the
        ``paths`` table to pick the *highest* priority path (lowest
        ``priority`` integer in this codebase means most-important) so
        that multi-domain memories are treated by their most-important
        binding.
        """
        limit = max(1, min(int(limit), 1000))
        now = datetime.now(timezone.utc)
        stmt = sa.text(
            """
            SELECT m.id AS memory_id,
                   m.created_at AS created_at,
                   m.last_accessed_at AS last_accessed_at,
                   m.access_count AS access_count,
                   COALESCE(p.priority, 0) AS priority,
                   COALESCE(p.domain, 'core') AS domain
              FROM memories AS m
              LEFT JOIN paths AS p ON p.memory_id = m.id
             WHERE COALESCE(m.deprecated, 0) = 0
             ORDER BY m.id ASC
             LIMIT :lim
            """
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt, {"lim": int(limit)})
            rows = [dict(r) for r in result.mappings().all()]

        # Deduplicate by memory_id; keep the row with the LOWEST priority
        # value (i.e. the most-important binding) because tests do not
        # require ranking by domain.
        per_memory: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            mid = int(row["memory_id"])
            if mid not in per_memory:
                per_memory[mid] = row
                continue
            current = per_memory[mid]
            if int(row.get("priority") or 0) < int(current.get("priority") or 0):
                per_memory[mid] = row

        enriched: List[Dict[str, Any]] = []
        for row in per_memory.values():
            age_days = self._age_days(now, row.get("created_at"))
            enriched.append(
                {
                    "memory_id": int(row["memory_id"]),
                    "age_days": age_days,
                    "access_count": int(row.get("access_count") or 0),
                    "priority": int(row.get("priority") or 0),
                    "domain": str(row.get("domain") or "core").strip() or "core",
                    "pinned": False,  # v1 has no schema-level "pinned"; uses pinned_memory_ids.
                }
            )
        return enriched

    @staticmethod
    def _age_days(now: datetime, created_at: Any) -> float:
        if created_at is None:
            return 0.0
        if isinstance(created_at, datetime):
            anchor = created_at
        else:
            try:
                text = str(created_at).replace("Z", "+00:00")
                anchor = datetime.fromisoformat(text)
            except (TypeError, ValueError):
                return 0.0
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        delta = now - anchor
        seconds = delta.total_seconds()
        if seconds < 0:
            return 0.0
        return seconds / 86400.0


__all__ = [
    "AGGRESSIVE_BUDGET",
    "CompressionEngine",
    "CompressionPreview",
    "EMERGENCY_BUDGET",
    "MILD_BUDGET",
    "MemoryCompressionCandidate",
    "compression_preview_enabled",
]
