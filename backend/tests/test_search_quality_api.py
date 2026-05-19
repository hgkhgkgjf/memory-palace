import pytest

from api import search_quality as search_quality_api


class _BrokenIndexStatusClient:
    async def get_index_status(self):
        raise RuntimeError("raw index status secret")


@pytest.mark.asyncio
async def test_search_quality_metrics_do_not_leak_index_status_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        search_quality_api,
        "get_sqlite_client",
        lambda: _BrokenIndexStatusClient(),
    )

    payload = await search_quality_api.get_search_quality_metrics()

    assert payload["health"] == {
        "degraded": True,
        "source": "api.search_quality",
    }
    assert "raw index status secret" not in str(payload)
