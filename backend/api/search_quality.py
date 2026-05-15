"""Search quality observability API.

This surface is intentionally explicit about unavailable quality samples.
It gives the dashboard a real authenticated endpoint while the project
does not yet persist labelled MRR/recall evaluation runs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends

from db import get_sqlite_client

from .maintenance import require_maintenance_api_key


router = APIRouter(
    prefix="/search",
    tags=["search-quality"],
    dependencies=[Depends(require_maintenance_api_key)],
)


@router.get("/quality-metrics")
async def get_search_quality_metrics() -> Dict[str, Any]:
    client = get_sqlite_client()
    try:
        index_status = await client.get_index_status()
    except Exception as exc:
        index_status = {"degraded": True, "reason": str(exc)}

    rrf_config = getattr(client, "_rrf_config", None)
    rrf_payload = {
        "enabled": bool(getattr(rrf_config, "enabled", False)),
        "k": int(getattr(rrf_config, "k", 60) or 60),
        "reason": (
            "quality_samples_not_persisted"
            if not bool(getattr(rrf_config, "enabled", False))
            else "rrf_enabled_no_labelled_quality_samples"
        ),
    }
    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "is_mock": True,
        "status": "unavailable",
        "reason": "labelled_search_quality_samples_not_persisted",
        "modes": [],
        "channel_contribution": {
            "fts5_weight": None,
            "vector_weight": None,
            "rrf_weight": None,
            "fts5_contribution": None,
            "vector_contribution": None,
            "rrf_contribution": None,
        },
        "rrf": rrf_payload,
        "history": [],
        "sample_window_days": 0,
        "health": {
            "degraded": bool(index_status.get("degraded")),
            "source": "api.search_quality",
        },
    }


__all__ = ["router"]
