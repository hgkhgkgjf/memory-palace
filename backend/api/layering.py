"""L2 layering API.

Read-only L2 surface backed by :class:`core.layering_engine.LayeringEngine`.
Exposes three endpoints:

* ``GET /api/layering/summaries`` — list existing summaries
* ``GET /api/layering/summaries/{summary_id}`` — fetch one with source drill-down
* ``POST /api/layering/summaries/generate`` — produce a DRAFT preview from
  a list of L1 memory ids and a scope. The draft is NOT persisted; the
  endpoint is read-only with respect to the database in v1.

All endpoints are gated by the existing maintenance API key (the same
mechanism the rest of ``/maintenance``, ``/review``, etc. uses).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from core import LayeringEngine, MemorySummaryDraft, SummarySource
from core.layering_engine import DerivationMethod
from db import get_sqlite_client

from .maintenance import require_maintenance_api_key


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/layering",
    tags=["layering"],
    dependencies=[Depends(require_maintenance_api_key)],
)


# ----------------------------------------------------------------------- schemas


class SummaryGenerateRequest(BaseModel):
    """Generate a DRAFT L2 summary from a list of L1 memory ids.

    The endpoint is read-only: it returns the draft but does not write
    to the database. v1 intentionally has no MCP write tool for L2.
    """

    scope: str = Field(..., min_length=1, max_length=512)
    memory_ids: List[int] = Field(..., min_length=1, max_length=200)
    title: Optional[str] = Field(default=None, max_length=512)
    derivation_method: Optional[str] = Field(default=None, max_length=64)

    @field_validator("memory_ids")
    @classmethod
    def _ensure_positive_ids(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("memory_ids must be a non-empty list")
        cleaned = []
        for mid in v:
            try:
                cleaned.append(int(mid))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid memory id: {mid!r}") from exc
        if any(mid <= 0 for mid in cleaned):
            raise ValueError("memory ids must be positive integers")
        return cleaned

    @field_validator("derivation_method")
    @classmethod
    def _check_method(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if v not in DerivationMethod.ALL:
            raise ValueError(
                f"derivation_method must be one of {DerivationMethod.ALL!r}"
            )
        return v


# ----------------------------------------------------------------------- helpers


def _engine() -> LayeringEngine:
    """Construct a fresh engine wired to the live SQLite session factory."""
    client = get_sqlite_client()
    return LayeringEngine(client.session)


def _source_to_api(source: SummarySource) -> Dict[str, Any]:
    return {
        "memory_id": source.memory_id,
        "status": source.status,
        "current_content": source.current_content,
        "current_content_hash": source.current_content_hash,
        "source_hash_at_derivation": source.source_hash_at_derivation,
        "is_stale": bool(source.is_stale),
    }


# ----------------------------------------------------------------------- routes


@router.get("/summaries")
async def list_summaries(
    scope: Optional[str] = Query(default=None, max_length=512),
    review_state: Optional[str] = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=500),
) -> Dict[str, Any]:
    """List existing L2 summaries, filtered by scope and/or review_state."""
    engine = _engine()
    try:
        summaries = await engine.get_summaries(
            scope=scope,
            review_state=review_state,
            limit=limit,
        )
    except Exception as exc:
        logger.exception("layering.list_summaries failed")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "list_summaries_failed",
                "reason": "internal_error",
            },
        )
    return {
        "count": len(summaries),
        "summaries": summaries,
    }


@router.get("/summaries/{summary_id}")
async def get_summary(summary_id: int) -> Dict[str, Any]:
    """Fetch one summary by id plus the full source drill-down."""
    if summary_id <= 0:
        raise HTTPException(status_code=400, detail="summary_id must be positive")
    engine = _engine()
    summary = await engine.get_summary(summary_id)
    if summary is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "summary_not_found",
                "summary_id": summary_id,
            },
        )
    sources = await engine.drill_down(summary_id)
    return {
        "summary": summary,
        "sources": [_source_to_api(s) for s in sources],
    }


@router.post("/summaries/generate")
async def generate_summary(payload: SummaryGenerateRequest) -> Dict[str, Any]:
    """Produce a DRAFT summary preview from L1 memory ids + scope.

    No database row is written. The response contains the full draft
    so the caller can review it before deciding whether to persist
    (which v1 does not expose through MCP).
    """
    engine = _engine()
    try:
        draft = await engine.generate_summary(
            scope=payload.scope,
            memory_ids=payload.memory_ids,
            title=payload.title,
            derivation_method=payload.derivation_method,
        )
    except ValueError as exc:
        logger.warning("layering.generate_summary rejected invalid request", exc_info=True)
        raise HTTPException(status_code=400, detail=type(exc).__name__)
    except Exception as exc:
        logger.exception("layering.generate_summary failed")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "generate_summary_failed",
                "reason": "internal_error",
            },
        )
    return {
        "draft": draft.to_api(),
        "persisted": False,
        "note": (
            "L2 is read-only in v1; generate_summary returns a DRAFT preview "
            "but does NOT persist the row. Use the layering_engine internal "
            "job to write summaries."
        ),
    }


__all__ = ["router"]
