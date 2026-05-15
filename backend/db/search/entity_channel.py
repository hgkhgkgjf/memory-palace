"""Entity rerank-boost channel.

This module implements the **entity rerank boost** described in Round 1
Track C. Per the C6 constraint, the entity signal is *not* a co-equal RRF
channel; it is a multiplicative boost applied *after* fusion produces a
ranked candidate list. The split is intentional:

- RRF assumes channels are roughly comparable in coverage (e.g. keyword
  BM25 vs. cosine similarity). The entity index is intrinsically sparser
  -- a memory either has a matching tag or it doesn't -- and adding it as
  a fourth RRF channel would penalise high-quality semantic matches that
  happen not to have structured tags yet.
- Entity matches are highly precise (``error_code == "EPIPE"`` literally
  matches) and therefore make better *boosters* of an existing ranking
  than they do contributors to a fresh ranking.

The boost is opt-in (default weight 0.0) and works on top of *either* the
weighted-fusion path or the RRF fusion path inside
:meth:`SQLiteClient.search_advanced` -- callers do not need to know which
fusion strategy is in use.

The detection logic is deliberately conservative: we extract entities
that match well-known structural patterns (URIs, dotted package paths,
``ERR_`` / ``E\\d+`` style error codes, snake-case identifiers, version
numbers, and lower-cased word tokens of length >= 3). False positives
are fine because we then *intersect* them with stored ``MemoryTag.tag_value``
rows; entities that match nothing produce a zero boost.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from sqlalchemy import text

LOGGER = logging.getLogger(__name__)


if TYPE_CHECKING:  # pragma: no cover -- type-only.
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Entity extraction patterns
# ---------------------------------------------------------------------------

#: ``scheme://path`` URIs (notes://, https://, file://, ...).
_URI_PATTERN = re.compile(r"\b[a-z][a-z0-9+.\-]{1,30}://[A-Za-z0-9_./%\-]+", re.IGNORECASE)

#: Dotted package paths (e.g. ``backend.db.search``).
_DOTTED_PATTERN = re.compile(
    r"\b[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*){1,}\b"
)

#: Error codes such as ``ERR_INTERNAL`` / ``E1001`` / ``EPIPE`` / ``ENOMEM``.
_ERROR_CODE_PATTERN = re.compile(
    r"\b(?:ERR_[A-Z0-9_]{2,}|E[A-Z]{2,}|E\d{2,5})\b"
)

#: snake_case identifiers (rough heuristic; matches at least one underscore).
_SNAKE_CASE_PATTERN = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")

#: Semantic version strings (``v1.2.3``, ``1.2.0``, etc.).
_VERSION_PATTERN = re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b")

#: Generic word tokens (length >= 3, alphanumeric). Used as last-resort
#: fallback so a query like ``"redis cache"`` can still boost memories tagged
#: ``cache`` or ``redis``.
_WORD_PATTERN = re.compile(r"\b[a-z][a-z0-9]{2,}\b", re.IGNORECASE)


@dataclass(frozen=True)
class ExtractedEntity:
    """A single entity extracted from a user query."""

    value: str
    kind: str  # "uri" | "dotted" | "error_code" | "snake" | "version" | "word"


class EntityBoostUnavailable(RuntimeError):
    """Raised when entity boost cannot be computed safely."""


def extract_entities(query: str, *, max_entities: int = 32) -> List[ExtractedEntity]:
    """Return a deduplicated list of entities recognised in ``query``.

    Order is preserved -- earlier patterns win when the same span matches
    multiple rules. The list is capped at ``max_entities`` to bound the SQL
    parameter count later.
    """

    cleaned = (query or "").strip()
    if not cleaned:
        return []

    seen: Set[str] = set()
    entities: List[ExtractedEntity] = []

    def _record(value: str, kind: str) -> None:
        key = value.lower()
        if key in seen:
            return
        seen.add(key)
        entities.append(ExtractedEntity(value=value, kind=kind))

    for match in _URI_PATTERN.finditer(cleaned):
        _record(match.group(0), "uri")
    for match in _ERROR_CODE_PATTERN.finditer(cleaned):
        _record(match.group(0), "error_code")
    for match in _DOTTED_PATTERN.finditer(cleaned):
        _record(match.group(0), "dotted")
    for match in _SNAKE_CASE_PATTERN.finditer(cleaned):
        _record(match.group(0), "snake")
    for match in _VERSION_PATTERN.finditer(cleaned):
        _record(match.group(0), "version")
    if len(entities) < max_entities:
        for match in _WORD_PATTERN.finditer(cleaned):
            _record(match.group(0), "word")
            if len(entities) >= max_entities:
                break

    return entities[:max_entities]


# ---------------------------------------------------------------------------
# Boost computation
# ---------------------------------------------------------------------------


def _normalise_score(per_kind_count: Mapping[str, int]) -> float:
    """Map a per-kind hit counter to a normalised boost in [0, 1].

    The mapping favours *kinds* that suggest high precision. ``uri`` and
    ``error_code`` matches are exact identifiers, so a single hit is enough
    to saturate; ``word`` matches need multiple hits before contributing
    meaningfully so we don't reward generic keyword overlap.
    """

    if not per_kind_count:
        return 0.0
    kind_weights = {
        "uri": 1.0,
        "error_code": 0.9,
        "dotted": 0.7,
        "snake": 0.55,
        "version": 0.5,
        "word": 0.2,
    }
    total = 0.0
    for kind, count in per_kind_count.items():
        weight = kind_weights.get(kind, 0.2)
        # Diminishing returns: log-style saturation so 1 -> ~weight, 2 ->
        # ~weight*1.5, 3 -> ~weight*1.7, etc.
        total += weight * (1.0 + 0.5 * (count - 1)) if count else 0.0
    return max(0.0, min(1.0, total / 2.0))


async def compute_boost(
    query: str,
    memory_ids: Sequence[int],
    session: "AsyncSession",
    *,
    max_entities: int = 32,
    confidence_floor: float = 0.0,
) -> Dict[int, float]:
    """Return a ``{memory_id: boost_score}`` map.

    The score is in ``[0.0, 1.0]``. Memory ids that do not match any
    extracted entity are *omitted* from the result so callers can default
    their score to zero and avoid an O(N) walk over the candidate list.

    Args:
        query: raw user query.
        memory_ids: candidate memory ids (typically the post-fusion top-K
            from ``search_advanced``).
        session: an active async session (the caller owns the lifetime).
        max_entities: cap on the number of entities considered.
        confidence_floor: ignore ``memory_tags`` rows with confidence below
            this threshold. ``0.0`` keeps every row.

    Raises:
        EntityBoostUnavailable: if the tag lookup fails. ``SQLiteClient``
            catches this and reports visible degradation instead of marking
            the boost as applied.
    """

    if not memory_ids:
        return {}

    entities = extract_entities(query, max_entities=max_entities)
    if not entities:
        return {}

    # Build the SQL parameter map.
    params: Dict[str, Any] = {
        "confidence_floor": float(confidence_floor),
    }
    in_clauses: List[str] = []
    for index, mid in enumerate(memory_ids):
        params[f"mid_{index}"] = int(mid)
        in_clauses.append(f":mid_{index}")
    if not in_clauses:
        return {}

    entity_clauses: List[str] = []
    entity_kinds: Dict[str, str] = {}
    for index, ent in enumerate(entities):
        # Case-insensitive equality match against the stored tag_value.
        # MemoryTag.tag_value is indexed (idx_tags_value); LOWER() prevents
        # using the index for equality but is acceptable for the small set
        # of candidate memories.
        param = f"ent_{index}"
        params[param] = ent.value.lower()
        entity_kinds[param] = ent.kind
        entity_clauses.append(
            f"LOWER(tag_value) = :{param}"
        )

    sql = (
        "SELECT memory_id, LOWER(tag_value) AS tag_value, COALESCE(confidence, 1.0) AS confidence "
        "FROM memory_tags "
        f"WHERE memory_id IN ({', '.join(in_clauses)}) "
        f"AND ({' OR '.join(entity_clauses)}) "
        "AND COALESCE(confidence, 1.0) >= :confidence_floor"
    )

    try:
        result = await session.execute(text(sql), params)
        rows = result.mappings().all()
    except Exception as exc:  # noqa: BLE001 -- caller must surface degradation.
        LOGGER.warning(
            "entity_channel.compute_boost failed; entity boost not applied: %s",
            exc,
        )
        raise EntityBoostUnavailable("entity_boost_failed") from exc

    # Aggregate hits per (memory_id, kind).
    aggregate: Dict[int, Dict[str, int]] = {}
    # Build a reverse lookup from lowercased entity value back to its kind.
    value_to_kind = {p[1]: entity_kinds[p[0]] for p in zip(
        [f"ent_{i}" for i in range(len(entities))],
        [e.value.lower() for e in entities],
    )}

    for row in rows:
        try:
            mid = int(row["memory_id"])
        except (KeyError, TypeError, ValueError):
            continue
        tag_value = str(row["tag_value"] or "")
        kind = value_to_kind.get(tag_value)
        if not kind:
            continue
        confidence_value = float(row.get("confidence") or 0.0)
        bucket = aggregate.setdefault(mid, {})
        bucket[kind] = bucket.get(kind, 0) + max(0, int(round(confidence_value * 10)))

    # Map to normalised boost scores.
    boosts: Dict[int, float] = {}
    for mid, counts in aggregate.items():
        boosts[mid] = _normalise_score(counts)
    return boosts


__all__ = [
    "EntityBoostUnavailable",
    "ExtractedEntity",
    "extract_entities",
    "compute_boost",
]
