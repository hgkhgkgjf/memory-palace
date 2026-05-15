"""L2 read-only layering engine.

Implements the read-only side of the Memory Layering Schema RFC:

* ``generate_summary`` reads L1 memories by id, derives a compact
  summary text (LLM if configured, deterministic fallback otherwise)
  and returns a :class:`MemorySummaryDraft` with the full provenance
  contract attached. The draft is NOT persisted until the caller
  explicitly invokes :meth:`LayeringEngine.persist_draft`.

* ``get_summaries`` is a pure read of the ``memory_summaries`` table.

* ``drill_down`` walks the provenance pointers and returns the source
  memories (live or archived). Permanently purged sources show up as
  tombstones; nothing is silently dropped.

The engine never deletes anything. It also never modifies L1 rows.
Constraints honoured:

* **C2** — no auto-delete (this module does not delete at all).
* **C3** — every derived row carries ``source_memory_ids``,
  ``source_hashes``, ``derivation_method``, ``confidence``,
  ``review_state``, ``storage_budget_bytes``.
* **C7** — schema-level changes happen through migrations 0004-0007;
  this module assumes those have been applied.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- enums / consts


class DerivationMethod:
    """String enum for the ``derivation_method`` column."""

    LLM_SUMMARY = "llm_summary"
    RULE_BASED = "rule_based"
    USER_CREATED = "user_created"

    ALL = (LLM_SUMMARY, RULE_BASED, USER_CREATED)


class ReviewState:
    """String enum for the ``review_state`` column."""

    DRAFT = "draft"
    AUTO_GENERATED = "auto_generated"
    HUMAN_REVIEWED = "human_reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"

    ALL = (DRAFT, AUTO_GENERATED, HUMAN_REVIEWED, APPROVED, REJECTED)


_FALLBACK_SUMMARY_MAX_CHARS = 600
_FALLBACK_CONFIDENCE = 0.5


def sha256_text(text: str) -> str:
    """Return the hex SHA-256 of ``text`` encoded as UTF-8 bytes.

    Source-of-truth for the ``source_hashes`` provenance column.
    """
    digest = hashlib.sha256()
    digest.update((text or "").encode("utf-8"))
    return digest.hexdigest()


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        raise ValueError("confidence must be numeric") from None
    if not math.isfinite(confidence):
        raise ValueError("confidence must be finite")
    return max(0.0, min(1.0, confidence))


# --------------------------------------------------------------------- dataclasses


@dataclass(frozen=True)
class SummarySource:
    """One source memory's drill-down result.

    ``status`` is one of:

    * ``"live"`` — source memory still exists in ``memories``.
    * ``"from_archive"`` — source has been moved to
      ``archived_memories`` (soft-delete).
    * ``"purged"`` — source was permanently deleted via the
      review-token flow; only the recorded hash survives.

    The dashboard MUST display the status verbatim; we never silently
    drop a source.
    """

    memory_id: int
    status: str
    current_content: Optional[str]
    current_content_hash: Optional[str]
    source_hash_at_derivation: Optional[str]

    @property
    def is_stale(self) -> bool:
        """True when the current source differs from the captured hash."""
        if self.status != "live":
            return False
        if not self.current_content_hash or not self.source_hash_at_derivation:
            return False
        return self.current_content_hash != self.source_hash_at_derivation


@dataclass
class MemorySummaryDraft:
    """In-memory draft of a memory_summaries row.

    The draft mirrors the on-disk schema 1:1 plus a few derived fields
    used by the API layer. Provenance is REQUIRED; the dataclass
    refuses to construct an instance with empty source ids / hashes.
    """

    title: str
    summary_text: str
    scope: str
    source_memory_ids: List[int]
    source_hashes: List[str]
    derivation_method: str = DerivationMethod.LLM_SUMMARY
    confidence: float = _FALLBACK_CONFIDENCE
    review_state: str = ReviewState.DRAFT
    storage_budget_bytes: int = 0
    layer: int = 2
    source_chunk_ids: Optional[List[int]] = None
    id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.source_memory_ids:
            raise ValueError("MemorySummaryDraft requires non-empty source_memory_ids")
        if not self.source_hashes:
            raise ValueError("MemorySummaryDraft requires non-empty source_hashes")
        if len(self.source_memory_ids) != len(self.source_hashes):
            raise ValueError(
                "source_memory_ids and source_hashes must have the same length"
            )
        if self.derivation_method not in DerivationMethod.ALL:
            raise ValueError(
                f"Unknown derivation_method={self.derivation_method!r}"
            )
        if self.review_state not in ReviewState.ALL:
            raise ValueError(f"Unknown review_state={self.review_state!r}")
        self.confidence = _clamp_confidence(self.confidence)
        # Auto-compute storage_budget_bytes if caller passed 0.
        if self.storage_budget_bytes <= 0:
            self.storage_budget_bytes = len(
                (self.summary_text or "").encode("utf-8")
            )

    def to_record(self) -> Dict[str, Any]:
        """Wire-format dict suitable for JSON serialization or DB insert."""
        record: Dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "summary_text": self.summary_text,
            "scope": self.scope,
            "layer": self.layer,
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
            "storage_budget_bytes": int(self.storage_budget_bytes),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return record

    def to_api(self) -> Dict[str, Any]:
        """Dashboard-friendly dict — JSON arrays decoded."""
        return {
            "id": self.id,
            "title": self.title,
            "summary_text": self.summary_text,
            "scope": self.scope,
            "layer": self.layer,
            "source_memory_ids": list(self.source_memory_ids),
            "source_chunk_ids": (
                list(self.source_chunk_ids) if self.source_chunk_ids else None
            ),
            "source_hashes": list(self.source_hashes),
            "derivation_method": self.derivation_method,
            "confidence": float(self.confidence),
            "review_state": self.review_state,
            "storage_budget_bytes": int(self.storage_budget_bytes),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# --------------------------------------------------------------------------- engine


SummarizerCallable = Any  # Callable[[List[str]], Tuple[str, float, str]] kept loose for tests.


class LayeringEngine:
    """Read-only L2 layering engine.

    The engine takes an async SQLAlchemy session factory (``async with
    session_factory() as session``) and never owns the session itself.
    This mirrors the existing pattern in ``backend/api/maintenance.py``
    and keeps tests and the API layer composable.
    """

    def __init__(
        self,
        session_factory: Any,
        *,
        summarizer: Optional[SummarizerCallable] = None,
    ) -> None:
        self._session_factory = session_factory
        self._summarizer = summarizer

    # -------------------------------------------------------------- generation

    async def generate_summary(
        self,
        scope: str,
        memory_ids: Sequence[int],
        *,
        title: Optional[str] = None,
        derivation_method: Optional[str] = None,
    ) -> MemorySummaryDraft:
        """Produce a draft summary for the given memory ids.

        The draft is NOT persisted. Callers must explicitly invoke
        :meth:`persist_draft` to write it to the database. This keeps
        the L2 read-only invariant in v1 even though the engine has
        all the wiring needed to write.
        """
        memory_ids = [int(mid) for mid in memory_ids]
        if not memory_ids:
            raise ValueError("memory_ids must be a non-empty sequence")
        scope = (scope or "").strip()
        if not scope:
            raise ValueError("scope must be a non-empty string")

        sources = await self._load_sources(memory_ids)
        if not sources:
            raise ValueError(
                f"No source memories found for ids={memory_ids!r}; "
                "refusing to derive a summary without provenance"
            )

        method = derivation_method or DerivationMethod.LLM_SUMMARY
        if method not in DerivationMethod.ALL:
            raise ValueError(f"Unknown derivation_method={method!r}")

        summary_text, confidence, used_method = self._summarize(
            sources, method=method
        )
        # Provenance: hash each source's content at derivation time.
        ordered_ids: List[int] = [int(row["id"]) for row in sources]
        ordered_hashes: List[str] = [
            sha256_text(str(row.get("content") or "")) for row in sources
        ]

        now_iso = datetime.now(timezone.utc).isoformat()
        return MemorySummaryDraft(
            title=title or self._auto_title(scope, sources),
            summary_text=summary_text,
            scope=scope,
            source_memory_ids=ordered_ids,
            source_hashes=ordered_hashes,
            derivation_method=used_method,
            confidence=float(confidence),
            review_state=ReviewState.DRAFT,
            storage_budget_bytes=0,  # auto-computed in __post_init__
            layer=2,
            created_at=now_iso,
            updated_at=now_iso,
        )

    async def persist_draft(self, draft: MemorySummaryDraft) -> MemorySummaryDraft:
        """Insert ``draft`` into ``memory_summaries`` and return the persisted draft.

        This is the ONLY way a row is written by this module. Callers
        wire it up explicitly (e.g. through a dashboard "Save preview"
        action); there is no implicit auto-save.
        """
        record = draft.to_record()
        record.pop("id", None)
        async with self._session_factory() as session:
            stmt = sa.text(
                """
                INSERT INTO memory_summaries (
                    title, summary_text, scope, layer,
                    source_memory_ids, source_chunk_ids, source_hashes,
                    derivation_method, confidence, review_state,
                    storage_budget_bytes, created_at, updated_at
                ) VALUES (
                    :title, :summary_text, :scope, :layer,
                    :source_memory_ids, :source_chunk_ids, :source_hashes,
                    :derivation_method, :confidence, :review_state,
                    :storage_budget_bytes, :created_at, :updated_at
                )
                """
            )
            result = await session.execute(stmt, record)
            await session.commit()
            new_id = int(result.lastrowid or 0)
        draft.id = new_id
        return draft

    # -------------------------------------------------------------------- reads

    async def get_summaries(
        self,
        *,
        scope: Optional[str] = None,
        review_state: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Read-only query over ``memory_summaries``.

        Returns a list of API-friendly dicts (JSON arrays decoded).
        """
        limit = max(1, min(int(limit or 1), 500))
        async with self._session_factory() as session:
            rows = await self._select_summaries(
                session,
                scope=scope,
                review_state=review_state,
                limit=limit,
            )
        return [self._row_to_api(row) for row in rows]

    async def get_summary(self, summary_id: int) -> Optional[Dict[str, Any]]:
        """Fetch one summary by id, returning ``None`` if missing."""
        async with self._session_factory() as session:
            stmt = sa.text(
                """
                SELECT id, title, summary_text, scope, layer,
                       source_memory_ids, source_chunk_ids, source_hashes,
                       derivation_method, confidence, review_state,
                       storage_budget_bytes, created_at, updated_at
                  FROM memory_summaries
                 WHERE id = :sid
                """
            )
            result = await session.execute(stmt, {"sid": int(summary_id)})
            row = result.mappings().first()
        return self._row_to_api(row) if row is not None else None

    async def drill_down(self, summary_id: int) -> List[SummarySource]:
        """Return the source memories backing ``summary_id``.

        Sources that no longer exist in ``memories`` are looked up in
        ``archived_memories``; sources missing from both are returned
        as ``status='purged'`` tombstones. The contract forbids
        silently dropping any entry from the result.
        """
        summary = await self.get_summary(summary_id)
        if summary is None:
            return []

        ids = list(summary.get("source_memory_ids") or [])
        hashes = list(summary.get("source_hashes") or [])
        # Pad hashes defensively so we never index off-the-end.
        while len(hashes) < len(ids):
            hashes.append("")

        async with self._session_factory() as session:
            live_rows = await self._load_live_rows(session, ids)
            archived_rows = await self._load_archived_rows(session, ids)

        live_by_id: Dict[int, Dict[str, Any]] = {
            int(row["id"]): dict(row) for row in live_rows
        }
        archived_by_id: Dict[int, Dict[str, Any]] = {
            int(row["original_memory_id"]): dict(row) for row in archived_rows
        }

        results: List[SummarySource] = []
        for index, memory_id in enumerate(ids):
            recorded_hash = hashes[index] if index < len(hashes) else ""
            if memory_id in live_by_id:
                content = str(live_by_id[memory_id].get("content") or "")
                results.append(
                    SummarySource(
                        memory_id=int(memory_id),
                        status="live",
                        current_content=content,
                        current_content_hash=sha256_text(content),
                        source_hash_at_derivation=recorded_hash or None,
                    )
                )
                continue
            if memory_id in archived_by_id:
                content = str(archived_by_id[memory_id].get("content") or "")
                results.append(
                    SummarySource(
                        memory_id=int(memory_id),
                        status="from_archive",
                        current_content=content,
                        current_content_hash=sha256_text(content),
                        source_hash_at_derivation=recorded_hash or None,
                    )
                )
                continue
            # Tombstone — must NOT silently drop.
            results.append(
                SummarySource(
                    memory_id=int(memory_id),
                    status="purged",
                    current_content=None,
                    current_content_hash=None,
                    source_hash_at_derivation=recorded_hash or None,
                )
            )
        return results

    # --------------------------------------------------------------------- helpers

    async def _load_sources(self, memory_ids: Sequence[int]) -> List[Dict[str, Any]]:
        async with self._session_factory() as session:
            rows = await self._load_live_rows(session, memory_ids)
        # Preserve the caller-supplied order so provenance arrays line up.
        rows_by_id: Dict[int, Dict[str, Any]] = {
            int(r["id"]): dict(r) for r in rows
        }
        ordered: List[Dict[str, Any]] = []
        for mid in memory_ids:
            if int(mid) in rows_by_id:
                ordered.append(rows_by_id[int(mid)])
        return ordered

    @staticmethod
    async def _load_live_rows(
        session: AsyncSession, memory_ids: Sequence[int]
    ) -> List[Dict[str, Any]]:
        if not memory_ids:
            return []
        placeholders = ",".join(f":id{i}" for i in range(len(memory_ids)))
        params = {f"id{i}": int(mid) for i, mid in enumerate(memory_ids)}
        stmt = sa.text(
            f"SELECT id, content FROM memories WHERE id IN ({placeholders})"
        )
        result = await session.execute(stmt, params)
        return [dict(r) for r in result.mappings().all()]

    @staticmethod
    async def _load_archived_rows(
        session: AsyncSession, memory_ids: Sequence[int]
    ) -> List[Dict[str, Any]]:
        if not memory_ids:
            return []
        placeholders = ",".join(f":id{i}" for i in range(len(memory_ids)))
        params = {f"id{i}": int(mid) for i, mid in enumerate(memory_ids)}
        stmt = sa.text(
            f"""
            SELECT original_memory_id, content
              FROM archived_memories
             WHERE original_memory_id IN ({placeholders})
            """
        )
        result = await session.execute(stmt, params)
        return [dict(r) for r in result.mappings().all()]

    @staticmethod
    async def _select_summaries(
        session: AsyncSession,
        *,
        scope: Optional[str],
        review_state: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"lim": int(limit)}
        clauses = []
        if scope:
            clauses.append("scope = :scope")
            params["scope"] = str(scope)
        if review_state:
            clauses.append("review_state = :rs")
            params["rs"] = str(review_state)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        stmt = sa.text(
            f"""
            SELECT id, title, summary_text, scope, layer,
                   source_memory_ids, source_chunk_ids, source_hashes,
                   derivation_method, confidence, review_state,
                   storage_budget_bytes, created_at, updated_at
              FROM memory_summaries
              {where}
             ORDER BY updated_at DESC, id DESC
             LIMIT :lim
            """
        )
        result = await session.execute(stmt, params)
        return [dict(r) for r in result.mappings().all()]

    def _summarize(
        self,
        sources: Iterable[Dict[str, Any]],
        *,
        method: str,
    ) -> tuple[str, float, str]:
        """Produce summary text + confidence. Falls back to deterministic
        join if no LLM summarizer is configured.

        Returns ``(summary_text, confidence, used_method)``. The
        returned ``used_method`` may differ from the requested method
        when the engine has to fall back.
        """
        bodies: List[str] = []
        for row in sources:
            body = str(row.get("content") or "").strip()
            if body:
                bodies.append(body)
        if not bodies:
            return ("", 0.0, DerivationMethod.RULE_BASED)

        if method == DerivationMethod.LLM_SUMMARY and self._summarizer is not None:
            try:
                summary_text, confidence = self._summarizer(bodies)
                return (str(summary_text), float(confidence), DerivationMethod.LLM_SUMMARY)
            except Exception as exc:  # pragma: no cover — fallback path
                logger.warning(
                    "Layering summarizer failed (%s): falling back to rule_based",
                    type(exc).__name__,
                )

        # Deterministic fallback: bullet list capped at _FALLBACK_SUMMARY_MAX_CHARS.
        bullets = [f"- {self._truncate(body, 240)}" for body in bodies]
        text = "\n".join(bullets)
        if len(text) > _FALLBACK_SUMMARY_MAX_CHARS:
            text = text[: _FALLBACK_SUMMARY_MAX_CHARS - 1] + "…"
        return (text, _FALLBACK_CONFIDENCE, DerivationMethod.RULE_BASED)

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        text = " ".join(str(text or "").split())
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1] + "…"

    @staticmethod
    def _auto_title(scope: str, sources: Iterable[Dict[str, Any]]) -> str:
        count = sum(1 for _ in sources)
        return f"Summary of {count} memor{'y' if count == 1 else 'ies'} in {scope}"

    @staticmethod
    def _row_to_api(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        result = dict(row)
        for key in ("source_memory_ids", "source_chunk_ids", "source_hashes"):
            raw = result.get(key)
            if raw is None:
                result[key] = None if key == "source_chunk_ids" else []
                continue
            if isinstance(raw, (list, tuple)):
                continue
            try:
                result[key] = json.loads(raw)
            except (TypeError, ValueError):
                result[key] = []
        return result


__all__ = [
    "DerivationMethod",
    "LayeringEngine",
    "MemorySummaryDraft",
    "ReviewState",
    "SummarySource",
    "sha256_text",
]
