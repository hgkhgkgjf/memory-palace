import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import mcp_server
from api import maintenance as maintenance_api


@pytest.mark.asyncio
@pytest.mark.parametrize("max_priority", [True, False, 2.0, 1.9])
async def test_mcp_search_memory_rejects_bool_and_float_max_priority_filters(
    monkeypatch: pytest.MonkeyPatch,
    max_priority,
) -> None:
    def _boom():
        raise AssertionError("get_sqlite_client should not be called for invalid filters")

    monkeypatch.setattr(mcp_server, "get_sqlite_client", _boom)

    raw = await mcp_server.search_memory(
        "release plan",
        filters={"max_priority": max_priority},
    )
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert payload["error"] == "filters.max_priority must be an integer"


@pytest.mark.asyncio
@pytest.mark.parametrize("max_priority", [True, False, 2.0, 1.9])
async def test_observability_search_rejects_bool_and_float_max_priority_filters(
    max_priority,
) -> None:
    payload = maintenance_api.SearchConsoleRequest(
        query="release plan",
        filters={"max_priority": max_priority},
    )

    with pytest.raises(HTTPException) as exc_info:
        await maintenance_api.run_observability_search(payload)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == {
        "error": "invalid_search_filters",
        "reason": "ValueError",
    }


def test_observability_search_request_rejects_overlong_query() -> None:
    with pytest.raises(ValidationError, match="at most 8000 characters"):
        maintenance_api.SearchConsoleRequest(query="x" * 8001)
