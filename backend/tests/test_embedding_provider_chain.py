import hashlib
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

import db.sqlite_client as sqlite_client_module
from db.sqlite_client import EmbeddingCache, MemoryChunkVec, SQLiteClient


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


def _clear_embedding_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS",
        "RETRIEVAL_EMBEDDING_API_BASE",
        "RETRIEVAL_EMBEDDING_BASE",
        "ROUTER_API_BASE",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
        "RETRIEVAL_EMBEDDING_API_KEY",
        "RETRIEVAL_EMBEDDING_KEY",
        "ROUTER_API_KEY",
        "OPENAI_API_KEY",
        "RETRIEVAL_EMBEDDING_MODEL",
        "ROUTER_EMBEDDING_MODEL",
        "OPENAI_EMBEDDING_MODEL",
        "RETRIEVAL_EMBEDDING_DIM",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.asyncio
async def test_embedding_provider_chain_disabled_keeps_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_embedding_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("EMBEDDING_PROVIDER_CHAIN_ENABLED", "false")

    client = SQLiteClient(_sqlite_url(tmp_path / "provider-chain-disabled.db"))
    await client.init_db()

    degrade_reasons: list[str] = []
    async with client.session() as session:
        embedding = await client._get_embedding(
            session,
            "provider chain disabled fallback sample",
            degrade_reasons=degrade_reasons,
        )
    await client.close()

    assert len(embedding) == client._embedding_dim
    assert "embedding_config_missing" in degrade_reasons
    assert "embedding_fallback_hash" in degrade_reasons


@pytest.mark.asyncio
async def test_embedding_provider_chain_uses_configured_fallback_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_embedding_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "router")
    monkeypatch.setenv("EMBEDDING_PROVIDER_CHAIN_ENABLED", "true")
    monkeypatch.setenv("EMBEDDING_PROVIDER_FAIL_OPEN", "false")
    monkeypatch.setenv("EMBEDDING_PROVIDER_FALLBACK", "api")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "https://embedding.example/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "chain-model")

    client = SQLiteClient(_sqlite_url(tmp_path / "provider-chain-fallback-api.db"))
    await client.init_db()

    call_meta: dict[str, str] = {"base": "", "endpoint": "", "api_key": ""}

    async def _fake_post_json(
        base: str,
        endpoint: str,
        payload,
        api_key: str = "",
        error_sink=None,
    ):
        call_meta["base"] = base
        call_meta["endpoint"] = endpoint
        call_meta["api_key"] = api_key
        _ = error_sink
        assert payload["model"] == "chain-model"
        assert payload["dimensions"] == client._embedding_dim
        return {"data": [{"embedding": [0.11] * client._embedding_dim}]}

    monkeypatch.setattr(client, "_post_json", _fake_post_json)
    degrade_reasons: list[str] = []
    async with client.session() as session:
        embedding = await client._get_embedding(
            session,
            "provider chain fallback provider sample",
            degrade_reasons=degrade_reasons,
        )
    await client.close()

    assert embedding == [0.11] * client._embedding_dim
    assert call_meta["base"] == "https://embedding.example/v1"
    assert call_meta["endpoint"] == "/embeddings"
    assert call_meta["api_key"] == "test-key"
    assert "embedding_fallback_hash" not in degrade_reasons


@pytest.mark.asyncio
async def test_post_json_retries_embedding_without_dimensions_when_provider_rejects_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "https://embedding.example/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "retry-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "1024")

    client = SQLiteClient(_sqlite_url(tmp_path / "embedding-dim-retry.db"))
    await client.init_db()

    calls: list[dict[str, object]] = []

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def post(self, url: str, json=None, headers=None):
            calls.append(dict(json or {}))
            request = httpx.Request("POST", url)
            if len(calls) == 1:
                return httpx.Response(
                    400,
                    json={"error": {"message": "unsupported field: dimensions"}},
                    request=request,
                )
            return httpx.Response(
                200,
                json={"data": [{"embedding": [0.5] * 1024}]},
                request=request,
            )

    monkeypatch.setattr(sqlite_client_module.httpx, "AsyncClient", _FakeAsyncClient)

    degrade_reasons: list[str] = []
    embedding = await client._fetch_remote_embedding(
        "embedding dimensions retry sample",
        degrade_reasons=degrade_reasons,
    )
    await client.close()

    assert len(calls) == 2
    assert calls[0]["dimensions"] == 1024
    assert "dimensions" not in calls[1]
    assert embedding == [0.5] * 1024
    assert degrade_reasons == []


@pytest.mark.asyncio
async def test_remote_embedding_dim_mismatch_falls_back_to_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "https://embedding.example/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "dim-check-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "16")

    client = SQLiteClient(_sqlite_url(tmp_path / "embedding-dim-mismatch.db"))
    await client.init_db()

    async def _fake_post_json(*_args, **_kwargs):
        return {"data": [{"embedding": [0.25] * 8}]}

    monkeypatch.setattr(client, "_post_json", _fake_post_json)
    degrade_reasons: list[str] = []
    async with client.session() as session:
        embedding = await client._get_embedding(
            session,
            "remote embedding dimension mismatch sample",
            degrade_reasons=degrade_reasons,
        )
    await client.close()

    assert len(embedding) == 16
    assert embedding != [0.25] * 8
    assert "embedding_response_dim_mismatch" in degrade_reasons
    assert "embedding_response_dim_mismatch:8!=16" in degrade_reasons
    assert "embedding_fallback_hash" in degrade_reasons


@pytest.mark.asyncio
async def test_invalid_link_local_embedding_base_is_ignored_at_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "http://169.254.169.254/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "dim-check-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "16")

    client = SQLiteClient(_sqlite_url(tmp_path / "embedding-invalid-base.db"))
    await client.init_db()

    degrade_reasons: list[str] = []
    async with client.session() as session:
        embedding = await client._get_embedding(
            session,
            "invalid embedding base fallback sample",
            degrade_reasons=degrade_reasons,
        )
    await client.close()

    assert client._embedding_api_base == ""
    assert len(embedding) == client._embedding_dim
    assert "embedding_config_missing" in degrade_reasons
    assert "embedding_fallback_hash" in degrade_reasons


@pytest.mark.asyncio
async def test_private_literal_embedding_base_is_ignored_without_allowlist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "http://10.0.0.8:11435/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "dim-check-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "16")
    monkeypatch.delenv("MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS", raising=False)

    client = SQLiteClient(_sqlite_url(tmp_path / "embedding-private-base-blocked.db"))
    await client.init_db()

    degrade_reasons: list[str] = []
    async with client.session() as session:
        embedding = await client._get_embedding(
            session,
            "private embedding base fallback sample",
            degrade_reasons=degrade_reasons,
        )
    await client.close()

    assert client._embedding_api_base == ""
    assert len(embedding) == client._embedding_dim
    assert "embedding_config_missing" in degrade_reasons
    assert "embedding_fallback_hash" in degrade_reasons


@pytest.mark.asyncio
async def test_private_literal_embedding_base_is_allowed_with_allowlist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "http://10.0.0.8:11435/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "dim-check-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "16")
    monkeypatch.setenv("MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS", "10.0.0.0/8")

    client = SQLiteClient(_sqlite_url(tmp_path / "embedding-private-base-allowed.db"))
    await client.init_db()

    assert client._embedding_api_base == "http://10.0.0.8:11435/v1"

    await client.close()


@pytest.mark.asyncio
async def test_embedding_provider_chain_fail_closed_when_fallback_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("EMBEDDING_PROVIDER_CHAIN_ENABLED", "true")
    monkeypatch.setenv("EMBEDDING_PROVIDER_FAIL_OPEN", "false")
    monkeypatch.setenv("EMBEDDING_PROVIDER_FALLBACK", "none")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "https://embedding.example/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "chain-model")

    client = SQLiteClient(_sqlite_url(tmp_path / "provider-chain-fail-closed.db"))
    await client.init_db()

    async def _always_fail(*_args, **_kwargs):
        return None

    monkeypatch.setattr(client, "_post_json", _always_fail)
    degrade_reasons: list[str] = []
    async with client.session() as session:
        with pytest.raises(RuntimeError, match="embedding_provider_chain_blocked"):
            await client._get_embedding(
                session,
                "provider chain fail closed sample",
                degrade_reasons=degrade_reasons,
            )
    await client.close()

    assert "embedding_provider_chain_blocked" in degrade_reasons


@pytest.mark.asyncio
async def test_embedding_provider_chain_fail_open_still_hash_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("EMBEDDING_PROVIDER_CHAIN_ENABLED", "true")
    monkeypatch.setenv("EMBEDDING_PROVIDER_FAIL_OPEN", "true")
    monkeypatch.setenv("EMBEDDING_PROVIDER_FALLBACK", "none")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "https://embedding.example/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "chain-model")

    client = SQLiteClient(_sqlite_url(tmp_path / "provider-chain-fail-open.db"))
    await client.init_db()

    async def _always_fail(*_args, **_kwargs):
        return None

    monkeypatch.setattr(client, "_post_json", _always_fail)
    degrade_reasons: list[str] = []
    async with client.session() as session:
        embedding = await client._get_embedding(
            session,
            "provider chain fail open hash fallback sample",
            degrade_reasons=degrade_reasons,
        )
    await client.close()

    assert len(embedding) == client._embedding_dim
    assert "embedding_fallback_hash" in degrade_reasons


@pytest.mark.asyncio
async def test_embedding_provider_chain_cache_hit_avoids_second_remote_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("EMBEDDING_PROVIDER_CHAIN_ENABLED", "true")
    monkeypatch.setenv("EMBEDDING_PROVIDER_FAIL_OPEN", "false")
    monkeypatch.setenv("EMBEDDING_PROVIDER_FALLBACK", "hash")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "https://embedding.example/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "cache-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "16")

    client = SQLiteClient(_sqlite_url(tmp_path / "provider-chain-cache.db"))
    await client.init_db()

    call_counter = {"value": 0}

    async def _fake_post_json(*_args, **_kwargs):
        call_counter["value"] += 1
        return {"data": [{"embedding": [0.5] * 16}]}

    monkeypatch.setattr(client, "_post_json", _fake_post_json)
    async with client.session() as session:
        first = await client._get_embedding(session, "provider chain cache sample")
        await session.flush()
        second = await client._get_embedding(session, "provider chain cache sample")
    await client.close()

    assert first == [0.5] * 16
    assert second == [0.5] * 16
    assert call_counter["value"] == 1


@pytest.mark.asyncio
async def test_embedding_provider_chain_cache_is_scoped_to_actual_provider_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_embedding_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "router")
    monkeypatch.setenv("EMBEDDING_PROVIDER_CHAIN_ENABLED", "true")
    monkeypatch.setenv("EMBEDDING_PROVIDER_FAIL_OPEN", "true")
    monkeypatch.setenv("EMBEDDING_PROVIDER_FALLBACK", "api")
    monkeypatch.setenv("ROUTER_API_BASE", "https://router.example/v1")
    monkeypatch.setenv("ROUTER_API_KEY", "router-key")
    monkeypatch.setenv("ROUTER_EMBEDDING_MODEL", "router-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "https://api.example/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_KEY", "api-key")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "api-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "16")

    client = SQLiteClient(_sqlite_url(tmp_path / "provider-chain-identity-cache.db"))
    await client.init_db()

    router_available = {"value": False}
    calls: list[tuple[str, str]] = []

    async def _fake_post_json(base: str, endpoint: str, payload, api_key: str = "", error_sink=None):
        _ = endpoint, api_key, error_sink
        model = str(payload.get("model") or "")
        calls.append((base, model))
        if model == "router-model":
            if not router_available["value"]:
                return None
            return {"data": [{"embedding": [0.2] * 16}]}
        if model == "api-model":
            return {"data": [{"embedding": [0.1] * 16}]}
        raise AssertionError(f"unexpected model: {model}")

    monkeypatch.setattr(client, "_post_json", _fake_post_json)
    async with client.session() as session:
        first = await client._get_embedding(session, "provider chain identity cache sample")
        await session.flush()
        router_available["value"] = True
        second = await client._get_embedding(session, "provider chain identity cache sample")
    await client.close()

    assert first == [0.1] * 16
    assert second == [0.2] * 16
    assert calls == [
        ("https://router.example/v1", "router-model"),
        ("https://api.example/v1", "api-model"),
        ("https://router.example/v1", "router-model"),
    ]


@pytest.mark.asyncio
async def test_embedding_provider_chain_probes_fallback_cache_for_multi_provider_fail_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_embedding_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "router")
    monkeypatch.setenv("EMBEDDING_PROVIDER_CHAIN_ENABLED", "true")
    monkeypatch.setenv("EMBEDDING_PROVIDER_FAIL_OPEN", "true")
    monkeypatch.setenv("EMBEDDING_PROVIDER_CANDIDATES", "router,api")
    monkeypatch.setenv("EMBEDDING_PROVIDER_FALLBACK", "hash")
    monkeypatch.setenv("ROUTER_API_BASE", "https://router.example/v1")
    monkeypatch.setenv("ROUTER_API_KEY", "router-key")
    monkeypatch.setenv("ROUTER_EMBEDDING_MODEL", "router-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "https://api.example/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_KEY", "api-key")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "api-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "16")

    client = SQLiteClient(_sqlite_url(tmp_path / "provider-chain-fail-open-cache.db"))
    await client.init_db()

    calls: list[tuple[str, str]] = []

    async def _fake_post_json(base: str, endpoint: str, payload, api_key: str = "", error_sink=None):
        _ = endpoint, api_key, error_sink
        model = str(payload.get("model") or "")
        calls.append((base, model))
        if "router" in base:
            return None
        return {"data": [{"embedding": [0.3] * 16}]}

    monkeypatch.setattr(client, "_post_json", _fake_post_json)

    async with client.session() as session:
        first = await client._get_embedding(session, "provider chain multi cache sample")
        await session.flush()
        second = await client._get_embedding(session, "provider chain multi cache sample")
    await client.close()

    assert first == [0.3] * 16
    assert second == [0.3] * 16
    assert calls == [
        ("https://router.example/v1", "router-model"),
        ("https://api.example/v1", "api-model"),
        ("https://router.example/v1", "router-model"),
    ]


@pytest.mark.asyncio
async def test_single_provider_remote_recovery_does_not_reuse_hash_fallback_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_embedding_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("EMBEDDING_PROVIDER_CHAIN_ENABLED", "false")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "https://api.example/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_KEY", "api-key")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "api-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "16")

    client = SQLiteClient(_sqlite_url(tmp_path / "single-provider-hash-fallback-cache.db"))
    await client.init_db()

    remote_available = {"value": False}
    calls: list[tuple[str, str, bool]] = []

    async def _fake_post_json(base: str, endpoint: str, payload, api_key: str = "", error_sink=None):
        _ = endpoint, api_key, error_sink
        model = str(payload.get("model") or "")
        calls.append((base, model, remote_available["value"]))
        if not remote_available["value"]:
            return None
        return {"data": [{"embedding": [0.9] * 16}]}

    monkeypatch.setattr(client, "_post_json", _fake_post_json)
    async with client.session() as session:
        first = await client._get_embedding(session, "single provider recovery sample")
        await session.flush()
        remote_available["value"] = True
        second = await client._get_embedding(session, "single provider recovery sample")
    await client.close()

    assert first != [0.9] * 16
    assert second == [0.9] * 16
    assert calls == [
        ("https://api.example/v1", "api-model", False),
        ("https://api.example/v1", "api-model", True),
    ]


@pytest.mark.asyncio
async def test_hash_fallback_index_degrades_after_remote_provider_recovers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_embedding_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("EMBEDDING_PROVIDER_CHAIN_ENABLED", "false")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "https://api.example/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_KEY", "api-key")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "api-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "16")

    client = SQLiteClient(_sqlite_url(tmp_path / "fallback-index-model.db"))
    await client.init_db()

    remote_available = {"value": False}

    async def _fake_post_json(*_args, **_kwargs):
        if not remote_available["value"]:
            return None
        return {"data": [{"embedding": [0.9] * 16}]}

    monkeypatch.setattr(client, "_post_json", _fake_post_json)

    await client.create_memory(
        parent_path="",
        content="fallback indexed sample",
        priority=1,
        title="fallback-indexed",
        domain="core",
    )

    async with client.session() as session:
        vector_models = [
            row[0]
            for row in (
                await session.execute(select(MemoryChunkVec.model))
            ).all()
        ]

    remote_available["value"] = True
    payload = await client.search_advanced(
        query="fallback indexed sample",
        mode="semantic",
        max_results=3,
    )
    await client.close()

    assert vector_models == ["hash:16"]
    assert payload["mode"] == "keyword"
    assert "vector_hash_fallback_requires_reindex" in payload["degrade_reasons"]


@pytest.mark.asyncio
async def test_reindex_memory_marks_hash_fallback_vector_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_embedding_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("EMBEDDING_PROVIDER_CHAIN_ENABLED", "false")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "https://api.example/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_KEY", "api-key")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "api-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "16")

    client = SQLiteClient(_sqlite_url(tmp_path / "fallback-reindex-model.db"))
    await client.init_db()

    remote_available = {"value": True}

    async def _fake_post_json(*_args, **_kwargs):
        if not remote_available["value"]:
            return None
        return {"data": [{"embedding": [0.9] * 16}]}

    monkeypatch.setattr(client, "_post_json", _fake_post_json)

    created = await client.create_memory(
        parent_path="",
        content="fallback reindex sample",
        priority=1,
        title="fallback-reindexed",
        domain="core",
        index_now=False,
    )

    remote_available["value"] = False
    await client.reindex_memory(int(created["id"]))

    async with client.session() as session:
        vector_models = [
            row[0]
            for row in (
                await session.execute(select(MemoryChunkVec.model))
            ).all()
        ]

    remote_available["value"] = True
    payload = await client.search_advanced(
        query="fallback reindex sample",
        mode="semantic",
        max_results=3,
    )
    await client.close()

    assert vector_models == ["hash:16"]
    assert payload["mode"] == "keyword"
    assert "vector_hash_fallback_requires_reindex" in payload["degrade_reasons"]


@pytest.mark.asyncio
async def test_write_guard_fails_closed_when_embedding_provider_degrades(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_embedding_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("EMBEDDING_PROVIDER_CHAIN_ENABLED", "false")
    monkeypatch.setenv("EMBEDDING_PROVIDER_FAIL_OPEN", "false")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "https://api.example/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_KEY", "api-key")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "api-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "16")

    client = SQLiteClient(_sqlite_url(tmp_path / "write-guard-provider-down.db"))
    await client.init_db()

    remote_available = {"value": True}

    async def _fake_post_json(*_args, **_kwargs):
        if not remote_available["value"]:
            return None
        return {"data": [{"embedding": [0.25] * 16}]}

    monkeypatch.setattr(client, "_post_json", _fake_post_json)
    await client.create_memory(
        parent_path="",
        content="existing provider indexed memory",
        priority=1,
        title="provider-indexed",
        domain="core",
    )

    remote_available["value"] = False
    decision = await client.write_guard(
        content="completely new memory while provider is unavailable",
        domain="core",
    )
    await client.close()

    assert decision["action"] == "NOOP"
    assert decision["reason"] == "write_guard_embedding_provider_degraded"
    assert "embedding_fallback_hash" in decision["degrade_reasons"]


@pytest.mark.asyncio
async def test_embedding_provider_chain_refreshes_stale_cached_embedding_dimension(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_embedding_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "64")

    client = SQLiteClient(_sqlite_url(tmp_path / "provider-chain-cache-dim.db"))
    await client.init_db()

    async with client.session() as session:
        first = await client._get_embedding(session, "provider chain cache dim sample")
        await session.flush()

        client._embedding_dim = 1024
        normalized = "provider chain cache dim sample"
        text_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        cache_key = client._build_embedding_cache_key(
            backend=client._embedding_backend,
            text_hash=text_hash,
            dim=client._embedding_dim,
        )
        session.add(
            EmbeddingCache(
                cache_key=cache_key,
                text_hash=text_hash,
                model=client._embedding_model,
                embedding=json.dumps(first),
            )
        )
        await session.flush()
        degrade_reasons: list[str] = []
        refreshed = await client._get_embedding(
            session,
            normalized,
            degrade_reasons=degrade_reasons,
        )

    await client.close()

    assert len(first) == 64
    assert len(refreshed) == 1024
    assert "embedding_cache_dim_mismatch" in degrade_reasons
    assert "embedding_cache_dim_mismatch:64!=1024" in degrade_reasons


@pytest.mark.asyncio
async def test_embedding_cache_key_includes_dimension(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "https://embedding.example/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "cache-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "16")

    db_path = tmp_path / "provider-chain-cache-dim.db"
    client64 = SQLiteClient(_sqlite_url(db_path))
    await client64.init_db()

    call_counter = {"value": 0}

    async def _fake_post_json_64(*_args, **_kwargs):
        call_counter["value"] += 1
        return {"data": [{"embedding": [0.64] * 16}]}

    monkeypatch.setattr(client64, "_post_json", _fake_post_json_64)
    async with client64.session() as session:
        first = await client64._get_embedding(session, "dimension-sensitive sample")
        await session.flush()
    await client64.close()

    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "32")
    client1024 = SQLiteClient(_sqlite_url(db_path))
    await client1024.init_db()

    async def _fake_post_json_1024(*_args, **_kwargs):
        call_counter["value"] += 1
        return {"data": [{"embedding": [1.024] * 32}]}

    monkeypatch.setattr(client1024, "_post_json", _fake_post_json_1024)
    async with client1024.session() as session:
        second = await client1024._get_embedding(session, "dimension-sensitive sample")
    await client1024.close()

    assert first == [0.64] * 16
    assert second == [1.024] * 32
    assert call_counter["value"] == 2
