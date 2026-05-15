"""Procedural memory extraction — draft mode, human approval required.

A procedural memory captures *how to do something* by abstracting a
recurring pattern from one or more L1 memories. v1 of the engine is
intentionally conservative:

* :meth:`ProceduralEngine.extract_pattern` reads the supplied L1
  memories, derives a *draft* procedural memory (trigger + ordered
  steps + provenance), persists it with ``review_state='draft'``, and
  returns the draft.
* :meth:`ProceduralEngine.get_drafts` lists every draft awaiting review.
* :meth:`ProceduralEngine.approve_draft` requires a non-empty
  ``review_token`` (verified upstream by ``backend/api/review.py``); it
  flips ``review_state`` to ``'human_reviewed'`` and records a hash of
  the token in ``review_token_fingerprint`` for audit trail purposes.
* :meth:`ProceduralEngine.reject_draft` flips a draft to
  ``review_state='rejected'`` with the supplied ``reason``.
* :meth:`ProceduralEngine.recommend_for_trigger` returns ONLY the
  ``human_reviewed`` rows that match a trigger. Drafts are never
  surfaced in recommendations even when the trigger matches; this is
  the read-side enforcement of the draft-by-default invariant.

The engine never deletes a row; rejected drafts stay queryable for
audit. The mutation surface is narrow on purpose so reviewers can
reason about its safety:

    extract → insert(draft)
    approve  → update(review_state=human_reviewed, +fingerprint)
    reject   → update(review_state=rejected, +rejection_reason)
    increment_success → update(success_count, last_used)

Every persisted row satisfies the Derived Memory Contract (C3):
``source_memory_ids``, ``source_hashes``, ``derivation_method``,
``confidence``, ``review_state``, ``storage_budget_bytes``. The
:class:`ProceduralDraft` dataclass refuses to construct an instance
with missing provenance, and the SQL schema (migration 0008) marks
those columns ``NOT NULL`` so even a bypassing caller cannot create a
provenance-less row.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

import sqlalchemy as sa


logger = logging.getLogger(__name__)


# ----------------------------------------------------------------- constants


class ProceduralReviewState:
    """String enum for the ``review_state`` column of procedural memories."""

    DRAFT = "draft"
    HUMAN_REVIEWED = "human_reviewed"
    REJECTED = "rejected"

    ALL = (DRAFT, HUMAN_REVIEWED, REJECTED)


class ProceduralDerivationMethod:
    """String enum for the ``derivation_method`` column.

    v1 only supports ``rule_based`` extraction because LLM-driven
    extraction is gated behind the (future) Round 4 approval flow.
    """

    RULE_BASED = "rule_based"
    LLM_PATTERN = "llm_pattern"
    USER_CREATED = "user_created"

    ALL = (RULE_BASED, LLM_PATTERN, USER_CREATED)


_TRIGGER_FALLBACK = "general pattern"
_STEP_BULLET_PATTERN = re.compile(
    r"^\s*(?:[\-*•]|\d+[\.)])\s*(?P<body>.+?)\s*$",
    flags=re.MULTILINE,
)
_MAX_STEPS = 25
_STEP_MAX_CHARS = 240


def _sha256_text(text: str) -> str:
    digest = hashlib.sha256()
    digest.update((text or "").encode("utf-8"))
    return digest.hexdigest()


# ---------------------------------------------------------------- dataclass


@dataclass
class ProceduralDraft:
    """In-memory draft of a ``procedural_memories`` row.

    The dataclass refuses to construct an instance without complete
    provenance (C3). Use :meth:`to_record` for the wire format used by
    inserts; :meth:`to_api` for dashboard responses.
    """

    trigger: str
    steps: List[str]
    source_memory_ids: List[int]
    source_hashes: List[str]
    derivation_method: str = ProceduralDerivationMethod.RULE_BASED
    confidence: float = 0.5
    review_state: str = ProceduralReviewState.DRAFT
    storage_budget_bytes: int = 0
    source_chunk_ids: Optional[List[int]] = None
    success_count: int = 0
    last_used: Optional[str] = None
    review_token_fingerprint: Optional[str] = None
    rejection_reason: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.trigger or not str(self.trigger).strip():
            raise ValueError("ProceduralDraft requires a non-empty trigger")
        if not self.steps:
            raise ValueError("ProceduralDraft requires at least one step")
        if not self.source_memory_ids:
            raise ValueError(
                "ProceduralDraft requires non-empty source_memory_ids"
            )
        if not self.source_hashes:
            raise ValueError("ProceduralDraft requires non-empty source_hashes")
        if len(self.source_memory_ids) != len(self.source_hashes):
            raise ValueError(
                "source_memory_ids and source_hashes must have the same length"
            )
        if self.derivation_method not in ProceduralDerivationMethod.ALL:
            raise ValueError(
                f"Unknown derivation_method={self.derivation_method!r}"
            )
        if self.review_state not in ProceduralReviewState.ALL:
            raise ValueError(f"Unknown review_state={self.review_state!r}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        # Normalize step list.
        normalized: List[str] = []
        for step in self.steps:
            text = str(step or "").strip()
            if not text:
                continue
            if len(text) > _STEP_MAX_CHARS:
                text = text[: _STEP_MAX_CHARS - 1] + "…"
            normalized.append(text)
        if not normalized:
            raise ValueError("ProceduralDraft requires at least one non-empty step")
        self.steps = normalized[:_MAX_STEPS]
        if self.storage_budget_bytes <= 0:
            payload = self.trigger + "\n" + "\n".join(self.steps)
            self.storage_budget_bytes = len(payload.encode("utf-8"))

    def to_record(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "trigger": self.trigger,
            "steps_json": json.dumps(list(self.steps), ensure_ascii=False),
            "source_memory_ids": json.dumps(list(self.source_memory_ids)),
            "source_chunk_ids": (
                json.dumps(list(self.source_chunk_ids))
                if self.source_chunk_ids
                else None
            ),
            "source_hashes": json.dumps(list(self.source_hashes)),
            "derivation_method": self.derivation_method,
            "confidence": float(self.confidence),
            "review_state": self.review_state,
            "success_count": int(self.success_count),
            "last_used": self.last_used,
            "storage_budget_bytes": int(self.storage_budget_bytes),
            "review_token_fingerprint": self.review_token_fingerprint,
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_api(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "trigger": self.trigger,
            "steps": list(self.steps),
            "source_memory_ids": list(self.source_memory_ids),
            "source_chunk_ids": (
                list(self.source_chunk_ids) if self.source_chunk_ids else None
            ),
            "source_hashes": list(self.source_hashes),
            "derivation_method": self.derivation_method,
            "confidence": float(self.confidence),
            "review_state": self.review_state,
            "success_count": int(self.success_count),
            "last_used": self.last_used,
            "storage_budget_bytes": int(self.storage_budget_bytes),
            "review_token_fingerprint": self.review_token_fingerprint,
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ------------------------------------------------------------------- engine


class ProceduralEngine:
    """Extract, persist, approve, and reject procedural memories.

    Mirrors the shape of :class:`~core.layering_engine.LayeringEngine`
    so it can be wired into the API layer the same way: takes an async
    session factory and owns no session.

    The engine does NOT call into the SQLiteClient or into other engine
    modules. It only issues SQL via SQLAlchemy core, which keeps it
    decoupled and trivial to unit-test.
    """

    def __init__(
        self,
        session_factory: Any,
        *,
        max_steps: int = _MAX_STEPS,
        review_token_validator: Optional[Any] = None,
    ) -> None:
        self._session_factory = session_factory
        self._max_steps = int(max_steps)
        self._review_token_validator = review_token_validator

    # --------------------------------------------------------- extraction

    async def extract_pattern(
        self,
        memory_ids: Sequence[int],
        *,
        trigger_hint: Optional[str] = None,
        derivation_method: str = ProceduralDerivationMethod.RULE_BASED,
        persist: bool = True,
    ) -> ProceduralDraft:
        """Derive a procedural draft from the supplied L1 memory ids.

        The draft is persisted with ``review_state='draft'`` by default;
        callers that only want a preview can pass ``persist=False``.
        Provenance is computed during extraction and immutable on the
        returned draft.
        """
        memory_ids = [int(mid) for mid in (memory_ids or [])]
        if not memory_ids:
            raise ValueError("memory_ids must be a non-empty sequence")
        if derivation_method not in ProceduralDerivationMethod.ALL:
            raise ValueError(
                f"Unknown derivation_method={derivation_method!r}"
            )

        sources = await self._load_sources(memory_ids)
        if not sources:
            raise ValueError(
                f"No source memories found for ids={memory_ids!r}; "
                "refusing to derive a procedural draft without provenance"
            )

        ordered_ids = [int(row["id"]) for row in sources]
        ordered_hashes = [
            _sha256_text(str(row.get("content") or "")) for row in sources
        ]

        trigger = (trigger_hint or self._infer_trigger(sources)).strip() or _TRIGGER_FALLBACK
        steps = self._extract_steps(sources)
        confidence = self._estimate_confidence(steps, sources)

        now_iso = datetime.now(timezone.utc).isoformat()
        draft = ProceduralDraft(
            trigger=trigger,
            steps=steps,
            source_memory_ids=ordered_ids,
            source_hashes=ordered_hashes,
            derivation_method=derivation_method,
            confidence=float(confidence),
            review_state=ProceduralReviewState.DRAFT,
            storage_budget_bytes=0,  # auto-computed in __post_init__
            success_count=0,
            created_at=now_iso,
            updated_at=now_iso,
        )

        if persist:
            await self._insert_draft(draft)
        return draft

    # ------------------------------------------------------------- reads

    async def get_drafts(
        self,
        *,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List every draft (``review_state='draft'``) awaiting review."""
        return await self._list_by_review_state(
            ProceduralReviewState.DRAFT, limit=limit
        )

    async def get_by_review_state(
        self,
        state: str,
        *,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        if state not in ProceduralReviewState.ALL:
            raise ValueError(f"Unknown review_state={state!r}")
        return await self._list_by_review_state(state, limit=limit)

    async def recommend_for_trigger(
        self,
        trigger: str,
        *,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Return ``human_reviewed`` procedural memories whose trigger
        contains ``trigger`` (case-insensitive substring match).

        DRAFT and REJECTED rows are NEVER returned from this surface —
        recommendations always go through human review first.
        """
        trigger = (trigger or "").strip().lower()
        if not trigger:
            return []
        limit = max(1, min(int(limit), 100))
        stmt = sa.text(
            """
            SELECT id, trigger, steps_json,
                   source_memory_ids, source_chunk_ids, source_hashes,
                   derivation_method, confidence, review_state,
                   success_count, last_used, storage_budget_bytes,
                   review_token_fingerprint, rejection_reason,
                   created_at, updated_at
              FROM procedural_memories
             WHERE review_state = :state
               AND LOWER(trigger) LIKE :pattern
             ORDER BY success_count DESC, updated_at DESC, id DESC
             LIMIT :lim
            """
        )
        async with self._session_factory() as session:
            result = await session.execute(
                stmt,
                {
                    "state": ProceduralReviewState.HUMAN_REVIEWED,
                    "pattern": f"%{trigger}%",
                    "lim": int(limit),
                },
            )
            rows = [dict(r) for r in result.mappings().all()]
        return [self._row_to_api(row) for row in rows]

    # ---------------------------------------------------- approval flow

    async def approve_draft(
        self,
        draft_id: int,
        *,
        review_token: str,
    ) -> Dict[str, Any]:
        """Promote a draft to ``review_state='human_reviewed'``.

        Requires a non-empty ``review_token`` that passes the configured
        ``review_token_validator`` hook. The SHA-256 of the token is
        recorded in ``review_token_fingerprint`` for audit purposes.
        """
        if not review_token or not str(review_token).strip():
            raise PermissionError(
                "approve_draft requires a non-empty review_token"
            )
        token_value = str(review_token).strip()
        await self._verify_review_token(token_value, int(draft_id))
        token_fp = _sha256_text(token_value)

        async with self._session_factory() as session:
            row = await self._fetch_for_update(session, int(draft_id))
            if row is None:
                raise ValueError(f"Procedural memory {draft_id} not found")
            current_state = str(row.get("review_state") or "")
            if current_state == ProceduralReviewState.REJECTED:
                raise ValueError(
                    f"Procedural memory {draft_id} is rejected; "
                    "create a new draft instead of approving a rejection"
                )
            if current_state == ProceduralReviewState.HUMAN_REVIEWED:
                # Idempotent — return the existing row without rewriting it.
                return self._row_to_api(row)

            now_iso = datetime.now(timezone.utc).isoformat()
            await session.execute(
                sa.text(
                    """
                    UPDATE procedural_memories
                       SET review_state = :state,
                           review_token_fingerprint = :fp,
                           updated_at = :now
                     WHERE id = :pid
                    """
                ),
                {
                    "state": ProceduralReviewState.HUMAN_REVIEWED,
                    "fp": token_fp,
                    "now": now_iso,
                    "pid": int(draft_id),
                },
            )
            await session.commit()
            refreshed = await self._fetch_for_update(session, int(draft_id))
        assert refreshed is not None
        return self._row_to_api(refreshed)

    async def reject_draft(
        self,
        draft_id: int,
        *,
        reason: str,
    ) -> Dict[str, Any]:
        """Mark ``draft_id`` as rejected with the supplied ``reason``."""
        if not reason or not str(reason).strip():
            raise ValueError("reject_draft requires a non-empty reason")
        async with self._session_factory() as session:
            row = await self._fetch_for_update(session, int(draft_id))
            if row is None:
                raise ValueError(f"Procedural memory {draft_id} not found")
            current_state = str(row.get("review_state") or "")
            if current_state == ProceduralReviewState.HUMAN_REVIEWED:
                raise ValueError(
                    f"Procedural memory {draft_id} is already human_reviewed; "
                    "reject_draft is only valid for drafts"
                )
            now_iso = datetime.now(timezone.utc).isoformat()
            await session.execute(
                sa.text(
                    """
                    UPDATE procedural_memories
                       SET review_state = :state,
                           rejection_reason = :reason,
                           updated_at = :now
                     WHERE id = :pid
                    """
                ),
                {
                    "state": ProceduralReviewState.REJECTED,
                    "reason": str(reason).strip(),
                    "now": now_iso,
                    "pid": int(draft_id),
                },
            )
            await session.commit()
            refreshed = await self._fetch_for_update(session, int(draft_id))
        assert refreshed is not None
        return self._row_to_api(refreshed)

    async def increment_success(self, draft_id: int) -> Dict[str, Any]:
        """Bump ``success_count`` and ``last_used`` for a human-reviewed row.

        Refuses to operate on drafts or rejections so the success counter
        truly reflects approved usage.
        """
        async with self._session_factory() as session:
            row = await self._fetch_for_update(session, int(draft_id))
            if row is None:
                raise ValueError(f"Procedural memory {draft_id} not found")
            if str(row.get("review_state") or "") != ProceduralReviewState.HUMAN_REVIEWED:
                raise ValueError(
                    "increment_success only operates on human_reviewed rows"
                )
            now_iso = datetime.now(timezone.utc).isoformat()
            await session.execute(
                sa.text(
                    """
                    UPDATE procedural_memories
                       SET success_count = success_count + 1,
                           last_used = :now,
                           updated_at = :now
                     WHERE id = :pid
                    """
                ),
                {"now": now_iso, "pid": int(draft_id)},
            )
            await session.commit()
            refreshed = await self._fetch_for_update(session, int(draft_id))
        assert refreshed is not None
        return self._row_to_api(refreshed)

    # ---------------------------------------------------------- internals

    async def _insert_draft(self, draft: ProceduralDraft) -> ProceduralDraft:
        record = draft.to_record()
        record.pop("id", None)
        async with self._session_factory() as session:
            stmt = sa.text(
                """
                INSERT INTO procedural_memories (
                    trigger, steps_json, source_memory_ids, source_chunk_ids,
                    source_hashes, derivation_method, confidence, review_state,
                    success_count, last_used, storage_budget_bytes,
                    review_token_fingerprint, rejection_reason,
                    created_at, updated_at
                ) VALUES (
                    :trigger, :steps_json, :source_memory_ids, :source_chunk_ids,
                    :source_hashes, :derivation_method, :confidence, :review_state,
                    :success_count, :last_used, :storage_budget_bytes,
                    :review_token_fingerprint, :rejection_reason,
                    :created_at, :updated_at
                )
                """
            )
            result = await session.execute(stmt, record)
            await session.commit()
            draft.id = int(result.lastrowid or 0)
        return draft

    async def _verify_review_token(self, review_token: str, draft_id: int) -> None:
        validator = self._review_token_validator
        if validator is None:
            raise PermissionError(
                "approve_draft requires a configured review_token_validator"
            )
        verdict = validator(review_token, int(draft_id))
        if inspect.isawaitable(verdict):
            verdict = await verdict
        if verdict is not True:
            raise PermissionError("review_token failed validation")

    async def _list_by_review_state(
        self,
        state: str,
        *,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        stmt = sa.text(
            """
            SELECT id, trigger, steps_json,
                   source_memory_ids, source_chunk_ids, source_hashes,
                   derivation_method, confidence, review_state,
                   success_count, last_used, storage_budget_bytes,
                   review_token_fingerprint, rejection_reason,
                   created_at, updated_at
              FROM procedural_memories
             WHERE review_state = :state
             ORDER BY updated_at DESC, id DESC
             LIMIT :lim
            """
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt, {"state": state, "lim": int(limit)})
            rows = [dict(r) for r in result.mappings().all()]
        return [self._row_to_api(row) for row in rows]

    async def _fetch_for_update(self, session, draft_id: int) -> Optional[Dict[str, Any]]:
        stmt = sa.text(
            """
            SELECT id, trigger, steps_json,
                   source_memory_ids, source_chunk_ids, source_hashes,
                   derivation_method, confidence, review_state,
                   success_count, last_used, storage_budget_bytes,
                   review_token_fingerprint, rejection_reason,
                   created_at, updated_at
              FROM procedural_memories
             WHERE id = :pid
            """
        )
        result = await session.execute(stmt, {"pid": int(draft_id)})
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def _load_sources(self, memory_ids: Sequence[int]) -> List[Dict[str, Any]]:
        if not memory_ids:
            return []
        placeholders = ",".join(f":id{i}" for i in range(len(memory_ids)))
        params = {f"id{i}": int(mid) for i, mid in enumerate(memory_ids)}
        stmt = sa.text(
            f"SELECT id, content FROM memories WHERE id IN ({placeholders})"
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt, params)
            rows_by_id = {
                int(r["id"]): dict(r) for r in result.mappings().all()
            }
        # Preserve caller order for stable provenance arrays.
        ordered: List[Dict[str, Any]] = []
        for mid in memory_ids:
            if int(mid) in rows_by_id:
                ordered.append(rows_by_id[int(mid)])
        return ordered

    # ------------------------------------------ pattern extraction heuristics

    def _infer_trigger(self, sources: Iterable[Dict[str, Any]]) -> str:
        """Pick the first short, descriptive line as the trigger sentence.

        The heuristic is intentionally simple — operators are expected
        to override the inferred trigger in the dashboard before
        approving a draft. The point of having one at all is to keep
        the table self-describing even when no operator has yet
        reviewed the row.
        """
        for row in sources:
            body = str(row.get("content") or "").strip()
            if not body:
                continue
            first_line = body.splitlines()[0].strip()
            if first_line:
                # Trim to the first sentence-ish chunk.
                segment = re.split(r"[.!?]\s|\n", first_line, maxsplit=1)[0]
                segment = segment.strip()
                if segment:
                    return segment[:_STEP_MAX_CHARS]
        return _TRIGGER_FALLBACK

    def _extract_steps(self, sources: Iterable[Dict[str, Any]]) -> List[str]:
        """Scan every source body for bullet/ordered-list lines.

        Falls back to the source's first non-empty line(s) when no
        explicit list markers are present, so the draft always has at
        least one step.
        """
        steps: List[str] = []
        seen: set[str] = set()
        for row in sources:
            body = str(row.get("content") or "")
            matches = _STEP_BULLET_PATTERN.findall(body)
            if matches:
                for raw in matches:
                    text = " ".join(raw.split())
                    if text and text.lower() not in seen:
                        steps.append(text)
                        seen.add(text.lower())
            else:
                # Fall back to the first non-empty line.
                for line in body.splitlines():
                    candidate = line.strip()
                    if not candidate:
                        continue
                    if candidate.lower() not in seen:
                        steps.append(candidate)
                        seen.add(candidate.lower())
                    break
            if len(steps) >= self._max_steps:
                break
        if not steps:
            steps = ["(no steps detected; operator must edit before approval)"]
        return steps[: self._max_steps]

    def _estimate_confidence(
        self,
        steps: List[str],
        sources: Iterable[Dict[str, Any]],
    ) -> float:
        """Confidence heuristic in ``[0, 1]``.

        Two source memories agreeing on the same step list is worth
        more than a single source's "best guess" — so the score scales
        with both the number of sources AND the number of distinct
        steps extracted. The cap is 0.85 because we never auto-promote
        a procedural memory above the "human review required"
        threshold.
        """
        source_count = sum(1 for _ in sources)
        if source_count == 0:
            return 0.0
        step_richness = min(len(steps) / 5.0, 1.0)
        source_richness = min(source_count / 3.0, 1.0)
        confidence = round(0.4 + 0.3 * step_richness + 0.15 * source_richness, 4)
        if not math.isfinite(confidence):
            return 0.0
        return max(0.0, min(1.0, confidence))

    # ----------------------------------------------------------- row mapping

    @staticmethod
    def _row_to_api(row: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        for key in ("source_memory_ids", "source_chunk_ids", "source_hashes"):
            raw = out.get(key)
            if raw is None:
                out[key] = None if key == "source_chunk_ids" else []
                continue
            if isinstance(raw, (list, tuple)):
                continue
            try:
                out[key] = json.loads(raw)
            except (TypeError, ValueError):
                out[key] = []
        # ``steps_json`` is stored as text; surface as a real list in the API.
        raw_steps = out.get("steps_json")
        try:
            out["steps"] = json.loads(raw_steps) if raw_steps else []
        except (TypeError, ValueError):
            out["steps"] = []
        return out


__all__ = [
    "ProceduralDerivationMethod",
    "ProceduralDraft",
    "ProceduralEngine",
    "ProceduralReviewState",
]
