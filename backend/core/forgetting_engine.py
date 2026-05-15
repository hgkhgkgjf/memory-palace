"""Forgetting engine — simulation + candidate queue + reviewed archive.

The engine has THREE responsibilities, in order of safety:

1. :meth:`ForgettingEngine.simulate_decay` projects vitality scores
   forward by N days WITHOUT modifying any row in ``memories``. Pure
   read; produces :class:`DecaySimulation` records for the dashboard.

2. :meth:`ForgettingEngine.get_candidates` produces a candidate queue
   from the simulation. Each :class:`ForgettingCandidate` is purely
   informational; it carries a recommendation but no destructive side
   effect.

3. :meth:`ForgettingEngine.approve_archive` is the ONE method that
   actually mutates state. It demands a non-empty ``review_token``,
   moves the L1 row to ``archived_memories`` (Migration 0006), and
   optionally creates a gist if none exists. The L1 row is marked
   ``deprecated=True`` (matching the existing tombstone pattern in
   ``backend/db/sqlite_client.py``); it is **never DELETEd**. Constraint
   **C2** from the Codex review.

Vitality decay uses an exponential model:

    projected_score = current_score * exp(-lambda * days_forward)

where ``lambda`` is configurable per engine instance. The default
matches a half-life of ~14 days (lambda ≈ ln(2)/14 ≈ 0.0495). Recently
accessed memories get a freshness floor so that hot rows never drop
into the candidate queue purely because of age.
"""

from __future__ import annotations

import inspect
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from .layering_engine import sha256_text

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- constants


# Half-life ~60 days for a steady-state row. Operators can override.
# (A 14-day half-life would push fresh, frequently accessed rows
# below the default 0.35 candidate threshold in under a month, which
# defeats the purpose of "forget only what is genuinely cold".)
_DEFAULT_DECAY_LAMBDA = math.log(2.0) / 60.0
_DEFAULT_CANDIDATE_THRESHOLD = 0.35
_FRESHNESS_FLOOR_DAYS = 1.0
# Floor applied to the projected score when a row has been accessed
# many times AND recently — this prevents hot rows from being shown
# as forgetting candidates due to long-horizon decay arithmetic.
_HOT_ROW_FLOOR = 0.5
_HOT_ROW_ACCESS_THRESHOLD = 5
_HOT_ROW_IDLE_LIMIT_DAYS = 14.0
_MAX_DAYS_FORWARD = 365


# ---------------------------------------------------------------------- dataclasses


@dataclass(frozen=True)
class DecaySimulation:
    """Projected vitality for one memory, ``days_forward`` from now.

    ``current_score``: the live ``vitality_score`` column.
    ``projected_score``: the result of the decay model.
    ``decay_curve``: a small set of intermediate samples for the
    dashboard sparkline (``[(day, score), ...]``).
    """

    memory_id: int
    current_score: float
    projected_score: float
    days_forward: int
    last_accessed_at: Optional[str]
    access_count: int
    decay_curve: List[tuple]


@dataclass(frozen=True)
class ForgettingCandidate:
    """One memory below the configured forgetting threshold."""

    memory_id: int
    current_score: float
    projected_score: float
    last_accessed_at: Optional[str]
    days_forward: int
    threshold: float
    recommendation: str  # 'archive' | 'review' | 'keep'
    reason: str

    def to_api(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "current_score": float(self.current_score),
            "projected_score": float(self.projected_score),
            "last_accessed_at": self.last_accessed_at,
            "days_forward": int(self.days_forward),
            "threshold": float(self.threshold),
            "recommendation": self.recommendation,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ArchiveResult:
    """Outcome of an approved archive operation."""

    memory_id: int
    archived_id: int
    archived_at: str
    archive_reason: str
    review_state: str
    review_token_fingerprint: str
    created_gist: bool

    def to_api(self) -> Dict[str, Any]:
        payload = self.__dict__.copy()
        return payload


# ----------------------------------------------------------------------- engine


class ForgettingEngine:
    """Vitality decay simulator + reviewed archive flow.

    The engine intentionally does NOT call into the SQLiteClient
    directly. It accepts an async session factory and runs explicit
    SQL through SQLAlchemy core, which keeps it test-friendly and
    side-effect free outside :meth:`approve_archive`.
    """

    def __init__(
        self,
        session_factory: Any,
        *,
        decay_lambda: float = _DEFAULT_DECAY_LAMBDA,
        threshold: float = _DEFAULT_CANDIDATE_THRESHOLD,
        review_token_validator: Optional[Any] = None,
    ) -> None:
        if decay_lambda <= 0:
            raise ValueError("decay_lambda must be positive")
        if not 0.0 < threshold < 1.0:
            raise ValueError("threshold must be in (0, 1)")
        self._session_factory = session_factory
        self._decay_lambda = float(decay_lambda)
        self._threshold = float(threshold)
        self._review_token_validator = review_token_validator

    # -------------------------------------------------------------- simulation

    async def simulate_decay(
        self,
        days_forward: int = 30,
        *,
        memory_ids: Optional[Sequence[int]] = None,
        limit: int = 200,
    ) -> List[DecaySimulation]:
        """Project vitality scores forward without mutating rows.

        Pure read. Returns at most ``limit`` simulations sorted by
        ``projected_score`` ascending (lowest = most decayed).
        """
        days_forward = max(0, min(int(days_forward or 0), _MAX_DAYS_FORWARD))
        limit = max(1, min(int(limit or 1), 1000))

        rows = await self._load_memory_vitality(
            memory_ids=memory_ids, limit=limit
        )
        now = datetime.now(timezone.utc)
        simulations: List[DecaySimulation] = []
        for row in rows:
            current_score = float(row.get("vitality_score") or 0.0)
            last_accessed = self._coerce_datetime(row.get("last_accessed_at"))
            access_count = int(row.get("access_count") or 0)

            # Idle-time factor: rows that haven't been touched
            # recently decay faster than ones touched today.
            idle_days = self._idle_days(now, last_accessed)
            effective_days = float(days_forward) + max(
                0.0, idle_days - _FRESHNESS_FLOOR_DAYS
            )
            projected = self._project(current_score, effective_days)
            # Hot-row floor: frequently and recently accessed rows
            # are protected from candidate-queue inclusion through
            # arithmetic alone.
            if (
                access_count >= _HOT_ROW_ACCESS_THRESHOLD
                and idle_days <= _HOT_ROW_IDLE_LIMIT_DAYS
            ):
                projected = max(projected, _HOT_ROW_FLOOR)

            curve = self._build_curve(
                start_score=current_score,
                idle_days=idle_days,
                days_forward=days_forward,
                access_count=access_count,
            )
            simulations.append(
                DecaySimulation(
                    memory_id=int(row["id"]),
                    current_score=current_score,
                    projected_score=projected,
                    days_forward=days_forward,
                    last_accessed_at=(
                        last_accessed.isoformat() if last_accessed else None
                    ),
                    access_count=access_count,
                    decay_curve=curve,
                )
            )

        simulations.sort(key=lambda s: s.projected_score)
        return simulations

    # ---------------------------------------------------------------- candidates

    async def get_candidates(
        self,
        *,
        threshold: Optional[float] = None,
        days_forward: int = 30,
        limit: int = 100,
    ) -> List[ForgettingCandidate]:
        """Return memories below ``threshold`` after ``days_forward`` of decay.

        Pure read. Does not mutate any row.
        """
        used_threshold = float(
            threshold if threshold is not None else self._threshold
        )
        if not 0.0 < used_threshold < 1.0:
            raise ValueError("threshold must be in (0, 1)")

        simulations = await self.simulate_decay(
            days_forward=days_forward, limit=max(limit * 4, limit)
        )
        candidates: List[ForgettingCandidate] = []
        for sim in simulations:
            if sim.projected_score >= used_threshold:
                continue
            recommendation, reason = self._classify(sim, used_threshold)
            candidates.append(
                ForgettingCandidate(
                    memory_id=sim.memory_id,
                    current_score=sim.current_score,
                    projected_score=sim.projected_score,
                    last_accessed_at=sim.last_accessed_at,
                    days_forward=sim.days_forward,
                    threshold=used_threshold,
                    recommendation=recommendation,
                    reason=reason,
                )
            )
            if len(candidates) >= limit:
                break
        return candidates

    # ---------------------------------------------------------------- archive

    async def approve_archive(
        self,
        memory_id: int,
        *,
        review_token: str,
        archived_by: Optional[str] = None,
        archive_reason: str = "forgetting_review",
    ) -> ArchiveResult:
        """Move ``memory_id`` from ``memories`` to ``archived_memories``.

        REQUIRES a non-empty ``review_token`` that passes the configured
        ``review_token_validator`` hook. The engine records a fingerprint
        of the token in the audit trail to make replay-detection possible.

        The L1 row is NOT deleted; ``deprecated`` is flipped to ``True``
        so the existing tombstone path keeps working and downstream
        searches stop returning it. Constraint **C2** from the Codex
        review.
        """
        if not review_token or not str(review_token).strip():
            raise PermissionError(
                "approve_archive requires a non-empty review_token"
            )
        token_value = str(review_token).strip()
        await self._verify_review_token(token_value, int(memory_id))
        token_fingerprint = sha256_text(token_value)

        async with self._session_factory() as session:
            row = await session.execute(
                sa.text(
                    "SELECT id, content, deprecated FROM memories WHERE id = :mid"
                ),
                {"mid": int(memory_id)},
            )
            mem = row.mappings().first()
            if mem is None:
                raise ValueError(f"Memory {memory_id} not found")

            existing_archive = await self._load_existing_archive(
                session, memory_id=int(memory_id)
            )

            paths_rows = await session.execute(
                sa.text(
                    """
                    SELECT domain, path, priority, disclosure, created_at
                      FROM paths
                     WHERE memory_id = :mid
                    """
                ),
                {"mid": int(memory_id)},
            )
            paths_snapshot = json.dumps(
                [
                    {
                        "domain": str(p.get("domain") or "").strip() or "core",
                        "path": str(p.get("path") or "").strip(),
                        "priority": int(p.get("priority") or 0),
                        "disclosure": (
                            str(p.get("disclosure"))
                            if p.get("disclosure") is not None
                            else None
                        ),
                        "created_at": (
                            str(p.get("created_at"))
                            if p.get("created_at") is not None
                            else None
                        ),
                    }
                    for p in paths_rows.mappings().all()
                ],
                ensure_ascii=False,
            )

            archived_at = datetime.now(timezone.utc).isoformat()
            if existing_archive is None:
                insert_result = await session.execute(
                    sa.text(
                        """
                        INSERT INTO archived_memories (
                            original_memory_id, content, archived_at,
                            archive_reason, archived_by, paths_snapshot,
                            review_state
                        ) VALUES (
                            :original_id, :content, :archived_at,
                            :reason, :by, :paths, :review_state
                        )
                        """
                    ),
                    {
                        "original_id": int(memory_id),
                        "content": str(mem.get("content") or ""),
                        "archived_at": archived_at,
                        "reason": str(archive_reason or "forgetting_review"),
                        "by": str(archived_by) if archived_by else None,
                        "paths": paths_snapshot,
                        "review_state": "human_reviewed",
                    },
                )
                archived_id = int(insert_result.lastrowid or 0)
                result_archived_at = archived_at
                result_archive_reason = str(archive_reason or "forgetting_review")
                result_review_state = "human_reviewed"
            else:
                archived_id = int(existing_archive["id"])
                result_archived_at = str(existing_archive.get("archived_at") or "")
                result_archive_reason = str(
                    existing_archive.get("archive_reason") or "forgetting_review"
                )
                result_review_state = str(
                    existing_archive.get("review_state") or "human_reviewed"
                )

            # Mark L1 as deprecated (NOT deleted).
            await session.execute(
                sa.text(
                    "UPDATE memories SET deprecated = 1 WHERE id = :mid"
                ),
                {"mid": int(memory_id)},
            )

            created_gist = await self._ensure_gist(
                session,
                memory_id=int(memory_id),
                content=str(mem.get("content") or ""),
            )

            await session.commit()

        return ArchiveResult(
            memory_id=int(memory_id),
            archived_id=archived_id,
            archived_at=result_archived_at,
            archive_reason=result_archive_reason,
            review_state=result_review_state,
            review_token_fingerprint=token_fingerprint,
            created_gist=created_gist,
        )

    # ----------------------------------------------------------------- helpers

    async def _load_memory_vitality(
        self,
        *,
        memory_ids: Optional[Sequence[int]] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"lim": int(limit)}
        clauses: List[str] = ["deprecated = 0"]
        if memory_ids:
            placeholders = ",".join(f":id{i}" for i in range(len(memory_ids)))
            clauses.append(f"id IN ({placeholders})")
            for i, mid in enumerate(memory_ids):
                params[f"id{i}"] = int(mid)

        where = " AND ".join(clauses)
        stmt = sa.text(
            f"""
            SELECT id, vitality_score, last_accessed_at, access_count
              FROM memories
             WHERE {where}
             ORDER BY vitality_score ASC, id ASC
             LIMIT :lim
            """
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt, params)
            rows = [dict(r) for r in result.mappings().all()]
        return rows

    async def _verify_review_token(self, review_token: str, memory_id: int) -> None:
        validator = self._review_token_validator
        if validator is None:
            raise PermissionError(
                "approve_archive requires a configured review_token_validator"
            )
        verdict = validator(review_token, int(memory_id))
        if inspect.isawaitable(verdict):
            verdict = await verdict
        if verdict is not True:
            raise PermissionError("review_token failed validation")

    @staticmethod
    async def _load_existing_archive(
        session: AsyncSession,
        *,
        memory_id: int,
    ) -> Optional[Dict[str, Any]]:
        result = await session.execute(
            sa.text(
                """
                SELECT id, archived_at, archive_reason, review_state
                  FROM archived_memories
                 WHERE original_memory_id = :mid
                 ORDER BY id DESC
                 LIMIT 1
                """
            ),
            {"mid": int(memory_id)},
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def _ensure_gist(
        self,
        session: AsyncSession,
        *,
        memory_id: int,
        content: str,
    ) -> bool:
        existing = await session.execute(
            sa.text(
                """
                SELECT id, gist_text, source_content_hash, gist_method,
                       quality_score, source_memory_ids, source_hashes,
                       derivation_method, confidence, review_state,
                       storage_budget_bytes
                  FROM memory_gists
                 WHERE memory_id = :mid
                 LIMIT 1
                """
            ),
            {"mid": int(memory_id)},
        )
        existing_row = existing.mappings().first()
        if existing_row is not None:
            await self._backfill_gist_provenance_if_needed(
                session,
                row=dict(existing_row),
                memory_id=int(memory_id),
                content=content,
            )
            return False

        if not content:
            return False

        gist_text = content.strip()
        if len(gist_text) > 240:
            gist_text = gist_text[:239] + "…"
        source_hash = sha256_text(content)
        await session.execute(
            sa.text(
                """
                INSERT INTO memory_gists (
                    memory_id, gist_text, source_content_hash,
                    gist_method, quality_score, created_at,
                    source_memory_ids, source_hashes,
                    derivation_method, confidence, review_state,
                    storage_budget_bytes
                ) VALUES (
                    :mid, :text, :hash,
                    'archive_fallback', 0.4, :now,
                    :source_ids, :source_hashes,
                    'rule_based', 0.4, 'auto_generated',
                    :budget
                )
                """
            ),
            {
                "mid": int(memory_id),
                "text": gist_text,
                "hash": source_hash,
                "now": datetime.now(timezone.utc).isoformat(),
                "source_ids": json.dumps([int(memory_id)]),
                "source_hashes": json.dumps([source_hash]),
                "budget": len(gist_text.encode("utf-8")),
            },
        )
        return True

    async def _backfill_gist_provenance_if_needed(
        self,
        session: AsyncSession,
        *,
        row: Dict[str, Any],
        memory_id: int,
        content: str,
    ) -> None:
        source_hash = str(row.get("source_content_hash") or "").strip()
        if not source_hash:
            source_hash = sha256_text(content)

        source_ids = self._parse_json_list(row.get("source_memory_ids"))
        source_hashes = self._parse_json_list(row.get("source_hashes"))
        raw_confidence = row.get("confidence", row.get("quality_score", 0.4))
        confidence = self._clamp_confidence(raw_confidence)
        try:
            raw_confidence_float = float(raw_confidence)
        except (TypeError, ValueError):
            raw_confidence_float = None
        budget = row.get("storage_budget_bytes")
        try:
            budget_int = int(budget) if budget is not None else 0
        except (TypeError, ValueError):
            budget_int = 0
        missing_budget = budget_int <= 0
        if budget_int <= 0:
            budget_int = len(str(row.get("gist_text") or content).encode("utf-8"))

        needs_backfill = (
            source_ids != [int(memory_id)]
            or not source_hashes
            or not str(row.get("derivation_method") or "").strip()
            or raw_confidence_float is None
            or raw_confidence_float != confidence
            or not str(row.get("review_state") or "").strip()
            or missing_budget
            or not str(row.get("source_content_hash") or "").strip()
        )
        if not needs_backfill:
            return

        await session.execute(
            sa.text(
                """
                UPDATE memory_gists
                   SET source_content_hash = CASE
                           WHEN source_content_hash IS NULL OR TRIM(source_content_hash) = ''
                           THEN :hash
                           ELSE source_content_hash
                       END,
                       source_memory_ids = :source_ids,
                       source_hashes = :source_hashes,
                       derivation_method = :method,
                       confidence = :confidence,
                       review_state = :review_state,
                       storage_budget_bytes = :budget
                 WHERE id = :gid
                """
            ),
            {
                "hash": source_hash,
                "source_ids": json.dumps([int(memory_id)]),
                "source_hashes": json.dumps(source_hashes or [source_hash]),
                "method": str(
                    row.get("derivation_method")
                    or row.get("gist_method")
                    or "rule_based"
                ),
                "confidence": confidence,
                "review_state": str(row.get("review_state") or "auto_generated"),
                "budget": budget_int,
                "gid": int(row["id"]),
            },
        )

    @staticmethod
    def _parse_json_list(value: Any) -> List[Any]:
        if isinstance(value, list):
            return value
        if value is None:
            return []
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []

    @staticmethod
    def _clamp_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            confidence = 0.0
        if not math.isfinite(confidence):
            return 0.0
        return max(0.0, min(1.0, confidence))

    def _project(self, score: float, effective_days: float) -> float:
        """Exponential decay model with score clamped to [0, 1]."""
        if score <= 0.0:
            return 0.0
        projected = float(score) * math.exp(-self._decay_lambda * effective_days)
        if projected < 0.0:
            return 0.0
        if projected > 1.0:
            return 1.0
        return projected

    def _build_curve(
        self,
        *,
        start_score: float,
        idle_days: float,
        days_forward: int,
        access_count: int = 0,
    ) -> List[tuple]:
        if days_forward <= 0:
            return [(0, float(start_score))]
        steps = min(8, max(2, days_forward))
        out: List[tuple] = []
        step_days = days_forward / steps
        hot = (
            access_count >= _HOT_ROW_ACCESS_THRESHOLD
            and idle_days <= _HOT_ROW_IDLE_LIMIT_DAYS
        )
        for i in range(steps + 1):
            d = i * step_days
            projected = self._project(start_score, d + max(0.0, idle_days - _FRESHNESS_FLOOR_DAYS))
            if hot:
                projected = max(projected, _HOT_ROW_FLOOR)
            out.append((round(d, 2), round(projected, 4)))
        return out

    @staticmethod
    def _classify(
        sim: DecaySimulation, threshold: float
    ) -> tuple[str, str]:
        """Heuristic recommendation. Pure function for testability."""
        if sim.projected_score < threshold * 0.4:
            return (
                "archive",
                f"projected score {sim.projected_score:.3f} far below threshold {threshold:.2f}",
            )
        if sim.access_count == 0 and (sim.last_accessed_at is None):
            return (
                "archive",
                f"never accessed and decayed below threshold {threshold:.2f}",
            )
        if sim.projected_score < threshold:
            return (
                "review",
                f"projected score {sim.projected_score:.3f} below threshold {threshold:.2f}",
            )
        return ("keep", "above threshold")

    @staticmethod
    def _idle_days(now: datetime, last_accessed: Optional[datetime]) -> float:
        if last_accessed is None:
            return 7.0  # Treat unknown as a week of idleness.
        delta = now - last_accessed
        if delta.total_seconds() < 0:
            return 0.0
        return delta.total_seconds() / 86400.0

    @staticmethod
    def _coerce_datetime(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        try:
            text = str(value).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(text)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None


__all__ = [
    "ArchiveResult",
    "DecaySimulation",
    "ForgettingCandidate",
    "ForgettingEngine",
]
