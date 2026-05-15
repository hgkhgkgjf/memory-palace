"""Forgetting API — decay simulation, candidate queue, reviewed archive.

Endpoints:

* ``GET /api/forgetting/simulate?days=30`` — pure-read decay simulation.
* ``GET /api/forgetting/candidates?threshold=0.35`` — candidates below the
  threshold. Does NOT mutate the database.
* ``POST /api/forgetting/archive`` — archive a single memory **after**
  the caller supplies a non-empty ``review_token``. The token is the
  same artefact the existing ``/review`` flow already produces.

The forgetting engine NEVER auto-deletes. The only write path is the
archive endpoint, which moves the row to ``archived_memories`` and
marks the original as ``deprecated=True`` — destructive ``DELETE`` is
not used.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import ArchiveResult, ForgettingEngine
from db import get_sqlite_client
from runtime_state import runtime_state

from .maintenance import require_maintenance_api_key


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/forgetting",
    tags=["forgetting"],
    dependencies=[Depends(require_maintenance_api_key)],
)


# ----------------------------------------------------------------------- schemas


class ArchiveRequest(BaseModel):
    """Archive one memory using an existing review token.

    The token is OPAQUE to this endpoint — it is recorded as a SHA-256
    fingerprint in the audit trail and forwarded to the engine which
    enforces non-emptiness. Higher-level callers (dashboard) MUST mint
    the token through the existing ``/review`` machinery; this endpoint
    is the action that human-approval enables.
    """

    memory_id: int = Field(..., gt=0)
    review_token: str = Field(..., min_length=8, max_length=512)
    archive_reason: str = Field(
        default="forgetting_review", min_length=1, max_length=64
    )
    archived_by: Optional[str] = Field(default=None, max_length=128)


class ArchivePrepareRequest(BaseModel):
    """Prepare a reviewed archive batch.

    The token returned by this endpoint is short-lived and bound to the
    selected candidate state. ``/archive/confirm`` consumes it before any
    memory row is archived.
    """

    memory_ids: List[int] = Field(..., min_length=1, max_length=100)
    threshold: float = Field(default=0.35, gt=0.0, lt=1.0)
    days: int = Field(default=30, ge=0, le=365)
    archive_reason: str = Field(
        default="forgetting_review", min_length=1, max_length=64
    )
    archived_by: Optional[str] = Field(default=None, max_length=128)
    ttl_seconds: int = Field(default=900, ge=60, le=3600)


class ArchiveConfirmRequest(BaseModel):
    review_id: str = Field(..., min_length=8, max_length=128)
    token: str = Field(..., min_length=16, max_length=256)
    confirmation_phrase: str = Field(..., min_length=8, max_length=128)


# ----------------------------------------------------------------------- helpers


def _engine(review_token_validator: Optional[Any] = None) -> ForgettingEngine:
    client = get_sqlite_client()
    return ForgettingEngine(
        client.session,
        review_token_validator=review_token_validator,
    )


def _candidate_state_hash(candidate: Dict[str, Any]) -> str:
    payload = {
        "memory_id": int(candidate.get("memory_id")),
        "current_score": round(float(candidate.get("current_score") or 0.0), 6),
        "projected_score": round(float(candidate.get("projected_score") or 0.0), 6),
        "threshold": round(float(candidate.get("threshold") or 0.0), 6),
        "days_forward": int(candidate.get("days_forward") or 0),
        "recommendation": str(candidate.get("recommendation") or ""),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _candidate_to_selection(
    candidate: Dict[str, Any],
    *,
    archive_reason: str,
    archived_by: Optional[str],
) -> Dict[str, Any]:
    return {
        "memory_id": int(candidate.get("memory_id")),
        "state_hash": _candidate_state_hash(candidate),
        "current_score": float(candidate.get("current_score") or 0.0),
        "projected_score": float(candidate.get("projected_score") or 0.0),
        "threshold": float(candidate.get("threshold") or 0.0),
        "days_forward": int(candidate.get("days_forward") or 0),
        "recommendation": str(candidate.get("recommendation") or "review"),
        "archive_reason": str(archive_reason or "forgetting_review"),
        "archived_by": str(archived_by).strip() if archived_by else None,
    }


def _selected_ids(memory_ids: Sequence[int]) -> List[int]:
    seen: set[int] = set()
    selected: List[int] = []
    for raw_id in memory_ids:
        memory_id = int(raw_id)
        if memory_id in seen:
            continue
        seen.add(memory_id)
        selected.append(memory_id)
    return selected


async def _load_selected_candidates(
    engine: ForgettingEngine,
    *,
    memory_ids: Sequence[int],
    threshold: float,
    days: int,
) -> Dict[int, Dict[str, Any]]:
    selected = _selected_ids(memory_ids)
    simulations = await engine.simulate_decay(
        days_forward=days,
        memory_ids=selected,
        limit=max(1, len(selected)),
    )
    candidates: Dict[int, Dict[str, Any]] = {}
    for sim in simulations:
        if sim.projected_score >= threshold:
            continue
        recommendation, reason = engine._classify(sim, threshold)
        payload = {
            "memory_id": int(sim.memory_id),
            "current_score": float(sim.current_score),
            "projected_score": float(sim.projected_score),
            "last_accessed_at": sim.last_accessed_at,
            "days_forward": int(sim.days_forward),
            "threshold": float(threshold),
            "recommendation": recommendation,
            "reason": reason,
        }
        candidates[int(sim.memory_id)] = payload
    return candidates


# ------------------------------------------------------------------------ routes


@router.get("/simulate")
async def simulate(
    days: int = Query(default=30, ge=0, le=365),
    limit: int = Query(default=100, ge=1, le=1000),
) -> Dict[str, Any]:
    """Project decay forward by ``days`` days for the lowest-vitality rows.

    Pure read. Does not modify any row.
    """
    engine = _engine()
    try:
        simulations = await engine.simulate_decay(
            days_forward=days, limit=limit
        )
    except Exception as exc:
        logger.exception("forgetting.simulate failed")
        raise HTTPException(
            status_code=500,
            detail={"error": "simulate_failed", "reason": str(exc)},
        )
    return {
        "count": len(simulations),
        "days_forward": int(days),
        "simulations": [
            {
                "memory_id": sim.memory_id,
                "current_score": float(sim.current_score),
                "projected_score": float(sim.projected_score),
                "days_forward": int(sim.days_forward),
                "last_accessed_at": sim.last_accessed_at,
                "access_count": int(sim.access_count),
                "decay_curve": list(sim.decay_curve),
            }
            for sim in simulations
        ],
    }


@router.get("/candidates")
async def candidates(
    threshold: float = Query(default=0.35, gt=0.0, lt=1.0),
    days: int = Query(default=30, ge=0, le=365),
    limit: int = Query(default=100, ge=1, le=1000),
) -> Dict[str, Any]:
    """Return forgetting candidates below ``threshold``.

    Pure read: no row is mutated. The dashboard surfaces this list as
    the human review queue.
    """
    engine = _engine()
    try:
        results = await engine.get_candidates(
            threshold=threshold, days_forward=days, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("forgetting.candidates failed")
        raise HTTPException(
            status_code=500,
            detail={"error": "candidates_failed", "reason": str(exc)},
        )
    return {
        "count": len(results),
        "threshold": float(threshold),
        "days_forward": int(days),
        "candidates": [c.to_api() for c in results],
    }


@router.post("/archive/prepare")
async def prepare_archive(payload: ArchivePrepareRequest) -> Dict[str, Any]:
    """Prepare a short-lived human review token for archive confirmation.

    No memory state is changed here. The returned token is stored in the
    runtime cleanup-review coordinator and must be consumed by
    ``/archive/confirm`` with the matching confirmation phrase.
    """
    engine = _engine()
    selected = _selected_ids(payload.memory_ids)
    try:
        candidates_by_id = await _load_selected_candidates(
            engine,
            memory_ids=selected,
            threshold=payload.threshold,
            days=payload.days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("forgetting.archive.prepare failed")
        raise HTTPException(
            status_code=500,
            detail={"error": "archive_prepare_failed", "reason": str(exc)},
        )

    missing_ids = [memory_id for memory_id in selected if memory_id not in candidates_by_id]
    if missing_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "archive_candidates_changed",
                "missing_ids": missing_ids,
            },
        )

    selections = [
        _candidate_to_selection(
            candidates_by_id[memory_id],
            archive_reason=payload.archive_reason,
            archived_by=payload.archived_by,
        )
        for memory_id in selected
    ]
    review = await runtime_state.cleanup_reviews.create_review(
        action="archive",
        selections=selections,
        reviewer=payload.archived_by,
        ttl_seconds=payload.ttl_seconds,
    )
    return {
        "ok": True,
        "status": "pending_confirmation",
        "selected_count": len(selections),
        "review": review,
        "preview": selections,
    }


@router.post("/archive/confirm")
async def confirm_archive(payload: ArchiveConfirmRequest) -> Dict[str, Any]:
    """Consume a prepared review and archive all selected memories."""
    consume_result = await runtime_state.cleanup_reviews.consume_review(
        review_id=payload.review_id,
        token=payload.token,
        confirmation_phrase=payload.confirmation_phrase,
    )
    if not consume_result.get("ok"):
        raise HTTPException(status_code=409, detail=str(consume_result.get("error")))

    review = consume_result.get("review") or {}
    if str(review.get("action") or "") != "archive":
        raise HTTPException(status_code=409, detail="review_action_mismatch")

    selections = review.get("selections")
    if not isinstance(selections, list) or not selections:
        raise HTTPException(status_code=409, detail="review_selection_empty")

    selected_ids = [
        int(item.get("memory_id"))
        for item in selections
        if isinstance(item, dict) and item.get("memory_id") is not None
    ]
    first_selection = next((item for item in selections if isinstance(item, dict)), {})
    threshold = float(first_selection.get("threshold") or 0.35)
    days = int(first_selection.get("days_forward") or 30)
    review_token = f"{payload.review_id}:{payload.token}"
    selected_id_set = set(selected_ids)

    def _validate_consumed_review_token(token: str, memory_id: int) -> bool:
        return str(token or "") == review_token and int(memory_id) in selected_id_set

    engine = _engine(review_token_validator=_validate_consumed_review_token)

    try:
        current_by_id = await _load_selected_candidates(
            engine,
            memory_ids=selected_ids,
            threshold=threshold,
            days=days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("forgetting.archive.confirm recheck failed")
        raise HTTPException(
            status_code=500,
            detail={"error": "archive_confirm_recheck_failed", "reason": str(exc)},
        )
    stale_ids: List[int] = []
    for item in selections:
        if not isinstance(item, dict) or item.get("memory_id") is None:
            continue
        memory_id = int(item.get("memory_id"))
        current = current_by_id.get(memory_id)
        if current is None:
            stale_ids.append(memory_id)
            continue
        if _candidate_state_hash(current) != str(item.get("state_hash") or ""):
            stale_ids.append(memory_id)
    if stale_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "archive_candidates_changed",
                "stale_ids": stale_ids,
            },
        )

    archives: List[Dict[str, Any]] = []
    try:
        for item in selections:
            if not isinstance(item, dict) or item.get("memory_id") is None:
                continue
            result: ArchiveResult = await engine.approve_archive(
                int(item.get("memory_id")),
                review_token=review_token,
                archived_by=item.get("archived_by") or review.get("reviewer"),
                archive_reason=str(item.get("archive_reason") or "forgetting_review"),
            )
            archives.append(result.to_api())
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.exception("forgetting.archive.confirm failed")
        raise HTTPException(
            status_code=500,
            detail={"error": "archive_confirm_failed", "reason": str(exc)},
        )

    return {
        "ok": True,
        "archived_count": len(archives),
        "archives": archives,
        "note": (
            "Original memory rows were marked deprecated; no DELETE was "
            "issued. Restore through the existing review-token flow."
        ),
    }


@router.post("/archive")
async def archive(payload: ArchiveRequest) -> Dict[str, Any]:
    """Archive ``memory_id`` after the caller proves human approval.

    Legacy single-row endpoint. It is intentionally fail-closed unless
    operators explicitly re-enable the old opaque-token path for a
    trusted local integration.
    """
    import os

    allow_legacy = str(
        os.getenv("FORGETTING_ALLOW_LEGACY_REVIEW_TOKEN") or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not allow_legacy:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "prepared_review_required",
                "reason": "use /api/forgetting/archive/prepare then /api/forgetting/archive/confirm",
            },
        )
    expected_legacy_token = str(payload.review_token or "").strip()

    def _validate_legacy_review_token(token: str, memory_id: int) -> bool:
        return (
            str(token or "").strip() == expected_legacy_token
            and int(memory_id) == int(payload.memory_id)
        )

    engine = _engine(review_token_validator=_validate_legacy_review_token)
    try:
        result: ArchiveResult = await engine.approve_archive(
            payload.memory_id,
            review_token=payload.review_token,
            archived_by=payload.archived_by,
            archive_reason=payload.archive_reason,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("forgetting.archive failed")
        raise HTTPException(
            status_code=500,
            detail={"error": "archive_failed", "reason": str(exc)},
        )
    return {
        "archive": result.to_api(),
        "note": (
            "Original memory row was marked deprecated; no DELETE was "
            "issued. Restore through the existing review-token flow."
        ),
    }


__all__ = ["router"]
