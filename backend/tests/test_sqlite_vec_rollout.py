import json
import logging
from pathlib import Path

import pytest
from sqlalchemy import text

from db.sqlite_client import SQLiteClient


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


def _resolve_sqlite_vec_extension_path() -> str | None:
    try:
        import sqlite_vec  # type: ignore

        return str(sqlite_vec.loadable_path())
    except Exception:
        return None


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_defaults_keep_legacy_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "false")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "legacy")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_READ_RATIO", "0")

    client = SQLiteClient(_sqlite_url(tmp_path / "sqlite-vec-defaults.db"))
    await client.init_db()
    status_payload = await client.get_index_status()
    await client.close()

    capabilities = status_payload["capabilities"]
    assert capabilities["sqlite_vec_enabled"] is False
    assert capabilities["vector_engine_requested"] == "legacy"
    assert capabilities["vector_engine_effective"] == "legacy"
    assert capabilities["sqlite_vec_status"] == "disabled"
    assert capabilities["sqlite_vec_readiness"] == "hold"
    assert capabilities["sqlite_vec_read_ratio"] == 0


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_invalid_requested_engine_surfaces_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "sqlite_vec")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_READ_RATIO", "100")

    client = SQLiteClient(_sqlite_url(tmp_path / "sqlite-vec-invalid-engine.db"))
    await client.init_db()
    status_payload = await client.get_index_status()
    await client.close()

    capabilities = status_payload["capabilities"]
    assert capabilities["vector_engine_requested"] == "legacy"
    assert capabilities["vector_engine_requested_raw"] == "sqlite_vec"
    assert capabilities["vector_engine_warning"] == "unsupported_vector_engine:sqlite_vec"
    assert capabilities["vector_engine_effective"] == "legacy"


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_enabled_without_extension_falls_back_to_legacy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "vec")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_READ_RATIO", "100")
    monkeypatch.delenv("RETRIEVAL_SQLITE_VEC_EXTENSION_PATH", raising=False)
    monkeypatch.setattr(
        SQLiteClient,
        "_auto_discover_sqlite_vec_extension_path",
        staticmethod(lambda: None),
    )

    client = SQLiteClient(_sqlite_url(tmp_path / "sqlite-vec-no-extension.db"))
    await client.init_db()
    await client.create_memory(
        parent_path="",
        content="sqlite vec fallback legacy sample",
        priority=1,
        title="sqlite_vec_fallback",
        domain="core",
    )

    status_payload = await client.get_index_status()
    search_payload = await client.search_advanced(
        query="sqlite vec fallback",
        mode="semantic",
        max_results=5,
        candidate_multiplier=2,
        filters={},
    )
    await client.close()

    capabilities = status_payload["capabilities"]
    assert capabilities["sqlite_vec_enabled"] is True
    assert capabilities["vector_engine_requested"] == "vec"
    assert capabilities["vector_engine_effective"] == "legacy"
    assert capabilities["sqlite_vec_status"] == "skipped_no_extension_path"
    assert capabilities["sqlite_vec_diag_code"] == "path_not_provided"
    assert "sqlite_vec_fallback_legacy" in search_payload.get("degrade_reasons", [])
    assert search_payload["results"]
    assert (
        search_payload["metadata"]["vector_engine_selected"] == "legacy"
    )
    assert search_payload["metadata"]["vector_engine_path"] == "legacy_python_scoring"


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_auto_discovers_pip_extension_without_env_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    extension_path = _resolve_sqlite_vec_extension_path()
    if not extension_path:
        pytest.skip("sqlite-vec package not available in test environment")

    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "vec")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_READ_RATIO", "100")
    monkeypatch.delenv("RETRIEVAL_SQLITE_VEC_EXTENSION_PATH", raising=False)

    client = SQLiteClient(_sqlite_url(tmp_path / "sqlite-vec-auto-discovery.db"))
    await client.init_db()
    status_payload = await client.get_index_status()
    capabilities = status_payload["capabilities"]
    if capabilities["sqlite_vec_readiness"] != "ready":
        await client.close()
        pytest.skip("sqlite-vec extension cannot be loaded in current SQLite runtime")

    await client.create_memory(
        parent_path="",
        content="sqlite vec auto discovery native search sample",
        priority=1,
        title="sqlite_vec_auto_discovery_native",
        domain="core",
    )
    search_payload = await client.search_advanced(
        query="sqlite vec auto discovery native search",
        mode="semantic",
        max_results=5,
        candidate_multiplier=2,
        filters={},
    )
    await client.close()

    assert capabilities["sqlite_vec_status"] != "skipped_no_extension_path"
    assert capabilities["sqlite_vec_diag_code"] != "path_not_provided"
    assert capabilities["vector_engine_effective"] == "vec"
    assert capabilities["sqlite_vec_knn_ready"] is True
    expected_path = SQLiteClient._resolve_sqlite_extension_file(extension_path)
    assert expected_path is not None
    assert Path(client._sqlite_vec_capability["extension_path"]).resolve(
        strict=False
    ) == expected_path.resolve(strict=False)
    assert search_payload["results"]
    assert search_payload["metadata"]["vector_engine_path"] == "vec_native_topk_sql"


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_ready_keeps_vec_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    extension_path = _resolve_sqlite_vec_extension_path()
    if not extension_path:
        pytest.skip("sqlite-vec package not available in test environment")

    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "vec")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_READ_RATIO", "100")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_EXTENSION_PATH", extension_path)

    client = SQLiteClient(_sqlite_url(tmp_path / "sqlite-vec-ready-selection.db"))
    await client.init_db()
    status_payload = await client.get_index_status()
    if status_payload["capabilities"]["sqlite_vec_readiness"] != "ready":
        await client.close()
        pytest.skip("sqlite-vec extension cannot be loaded in current SQLite runtime")

    await client.create_memory(
        parent_path="",
        content="sqlite vec ready selection sample",
        priority=1,
        title="sqlite_vec_ready_selection",
        domain="core",
    )

    search_payload = await client.search_advanced(
        query="sqlite vec ready selection",
        mode="semantic",
        max_results=5,
        candidate_multiplier=2,
        filters={},
    )
    async with client.session() as session:
        vec0_exists_result = await session.execute(
            text(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='memory_chunks_vec0' LIMIT 1"
            )
        )
        vec0_count_result = await session.execute(
            text("SELECT COUNT(*) FROM memory_chunks_vec0")
        )

    await client.close()

    assert search_payload["results"]
    assert search_payload["metadata"]["vector_engine_selected"] == "vec"
    assert search_payload["metadata"]["vector_engine_path"] == "vec_native_topk_sql"
    assert "sqlite_vec_fallback_legacy" not in search_payload.get("degrade_reasons", [])
    assert vec0_exists_result.first() is not None
    assert int(vec0_count_result.scalar() or 0) >= 1


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_invalid_extension_path_marks_hold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "vec")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_EXTENSION_PATH", str(tmp_path / "missing_vec"))

    client = SQLiteClient(_sqlite_url(tmp_path / "sqlite-vec-invalid-path.db"))
    await client.init_db()
    status_payload = await client.get_index_status()
    await client.close()

    capabilities = status_payload["capabilities"]
    assert capabilities["vector_engine_effective"] == "legacy"
    assert capabilities["sqlite_vec_status"] == "invalid_extension_path"
    assert capabilities["sqlite_vec_diag_code"] == "path_not_found"
    assert capabilities["sqlite_vec_readiness"] == "hold"


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_prefers_extension_file_over_same_name_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base = tmp_path / "sqlite_vec"
    base.mkdir()
    extension_file = tmp_path / "sqlite_vec.dylib"
    extension_file.write_bytes(b"not-a-real-extension")

    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "vec")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_EXTENSION_PATH", str(base))

    client = SQLiteClient(_sqlite_url(tmp_path / "sqlite-vec-prefer-file.db"))
    await client.init_db()
    status_payload = await client.get_index_status()
    await client.close()

    capabilities = status_payload["capabilities"]
    assert capabilities["sqlite_vec_status"] in {
        "ok",
        "extension_load_failed",
        "extension_loading_unavailable",
        "sqlite_runtime_error",
    }
    assert capabilities["sqlite_vec_diag_code"] != "path_not_file"


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_directory_without_extension_reports_path_not_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base = tmp_path / "sqlite_vec"
    base.mkdir()

    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "vec")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_EXTENSION_PATH", str(base))

    client = SQLiteClient(_sqlite_url(tmp_path / "sqlite-vec-dir-only.db"))
    await client.init_db()
    status_payload = await client.get_index_status()
    await client.close()

    capabilities = status_payload["capabilities"]
    assert capabilities["sqlite_vec_status"] == "invalid_extension_path"
    assert capabilities["sqlite_vec_diag_code"] == "path_not_file"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_ratio", "expected_ratio"),
    [
        ("180", 100),
        ("-9", 0),
    ],
)
async def test_sqlite_vec_rollout_read_ratio_is_clamped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_ratio: str,
    expected_ratio: int,
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "dual")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_READ_RATIO", raw_ratio)
    monkeypatch.delenv("RETRIEVAL_SQLITE_VEC_EXTENSION_PATH", raising=False)

    db_path = tmp_path / f"sqlite-vec-ratio-{raw_ratio}.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()
    status_payload = await client.get_index_status()
    await client.close()

    assert status_payload["capabilities"]["sqlite_vec_read_ratio"] == expected_ratio


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_falls_back_when_vec_knn_not_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "vec")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_READ_RATIO", "100")
    monkeypatch.delenv("RETRIEVAL_SQLITE_VEC_EXTENSION_PATH", raising=False)
    monkeypatch.setattr(
        SQLiteClient,
        "_auto_discover_sqlite_vec_extension_path",
        staticmethod(lambda: None),
    )

    client = SQLiteClient(_sqlite_url(tmp_path / "sqlite-vec-native-fallback.db"))
    await client.init_db()
    await client.create_memory(
        parent_path="",
        content="sqlite vec native fallback sample",
        priority=1,
        title="sqlite_vec_native_fallback",
        domain="core",
    )
    client._sqlite_vec_enabled = True
    client._vector_engine_requested = "vec"
    client._vector_engine_effective = "vec"
    client._sqlite_vec_capability = {
        **client._sqlite_vec_capability,
        "status": "ok",
        "sqlite_vec_readiness": "ready",
        "diag_code": "",
    }

    search_payload = await client.search_advanced(
        query="sqlite vec native fallback",
        mode="semantic",
        max_results=5,
        candidate_multiplier=2,
        filters={},
    )
    await client.close()

    assert search_payload["results"]
    assert search_payload["metadata"]["vector_engine_selected"] == "vec"
    assert search_payload["metadata"]["vector_engine_path"] == "legacy_python_fallback"
    assert "sqlite_vec_knn_unavailable" in search_payload.get("degrade_reasons", [])


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_falls_back_when_vec_native_query_runtime_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    extension_path = _resolve_sqlite_vec_extension_path()
    if not extension_path:
        pytest.skip("sqlite-vec package not available in test environment")

    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "vec")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_READ_RATIO", "100")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_EXTENSION_PATH", extension_path)

    client = SQLiteClient(_sqlite_url(tmp_path / "sqlite-vec-native-query-failed.db"))
    await client.init_db()
    status_payload = await client.get_index_status()
    if status_payload["capabilities"]["sqlite_vec_readiness"] != "ready":
        await client.close()
        pytest.skip("sqlite-vec extension cannot be loaded in current SQLite runtime")

    await client.create_memory(
        parent_path="",
        content="sqlite vec native query failed sample",
        priority=1,
        title="sqlite_vec_native_query_failed",
        domain="core",
    )
    client._sqlite_vec_knn_ready = True
    client._sqlite_vec_knn_dim = 4096

    search_payload = await client.search_advanced(
        query="sqlite vec native query failed",
        mode="semantic",
        max_results=5,
        candidate_multiplier=2,
        filters={},
    )
    await client.close()

    assert search_payload["results"]
    assert search_payload["metadata"]["vector_engine_selected"] == "vec"
    assert search_payload["metadata"]["vector_engine_path"] == "legacy_python_fallback"
    assert "sqlite_vec_native_query_failed" in search_payload.get("degrade_reasons", [])


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_vec0_knn_path_with_real_extension(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sqlite_vec = pytest.importorskip("sqlite_vec")
    extension_path = str(sqlite_vec.loadable_path())

    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "vec")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_READ_RATIO", "100")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_EXTENSION_PATH", extension_path)

    client = SQLiteClient(_sqlite_url(tmp_path / "sqlite-vec-real-extension.db"))
    await client.init_db()
    await client.create_memory(
        parent_path="",
        content="sqlite vec real extension sample alpha",
        priority=1,
        title="sqlite_vec_real_extension_alpha",
        domain="core",
    )
    await client.create_memory(
        parent_path="",
        content="sqlite vec real extension sample beta",
        priority=1,
        title="sqlite_vec_real_extension_beta",
        domain="core",
    )

    status_payload = await client.get_index_status()
    capabilities = status_payload["capabilities"]
    if capabilities.get("sqlite_vec_readiness") != "ready":
        await client.close()
        pytest.skip("sqlite extension loading unavailable in current runtime")

    search_payload = await client.search_advanced(
        query="sqlite vec real extension",
        mode="semantic",
        max_results=5,
        candidate_multiplier=2,
        filters={},
    )
    await client.close()

    assert capabilities["sqlite_vec_knn_ready"] is True
    assert int(capabilities["sqlite_vec_knn_dim"]) > 0
    assert search_payload["results"]
    assert search_payload["metadata"]["vector_engine_selected"] == "vec"
    assert search_payload["metadata"]["vector_engine_path"] == "vec_native_topk_sql"
    assert search_payload["metadata"]["sqlite_vec_knn_ready"] is True
    assert "sqlite_vec_native_query_failed" not in search_payload.get("degrade_reasons", [])


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_rrf_and_native_vec_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sqlite_vec = pytest.importorskip("sqlite_vec")
    extension_path = str(sqlite_vec.loadable_path())

    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "vec")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_READ_RATIO", "100")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_EXTENSION_PATH", extension_path)
    monkeypatch.setenv("RRF_ENABLED", "true")
    monkeypatch.setenv("RRF_K", "10")

    client = SQLiteClient(_sqlite_url(tmp_path / "sqlite-vec-rrf-native.db"))
    await client.init_db()
    status_payload = await client.get_index_status()
    if status_payload["capabilities"]["sqlite_vec_readiness"] != "ready":
        await client.close()
        pytest.skip("sqlite-vec extension cannot be loaded in current SQLite runtime")

    await client.create_memory(
        parent_path="",
        content="sqlite vec rrf native fusion alpha sample",
        priority=1,
        title="sqlite_vec_rrf_native_alpha",
        domain="core",
    )
    await client.create_memory(
        parent_path="",
        content="sqlite vec rrf native fusion beta sample",
        priority=1,
        title="sqlite_vec_rrf_native_beta",
        domain="core",
    )
    search_payload = await client.search_advanced(
        query="sqlite vec rrf native fusion",
        mode="hybrid",
        max_results=5,
        candidate_multiplier=2,
        filters={},
    )
    await client.close()

    metadata = search_payload["metadata"]
    assert search_payload["results"]
    assert metadata["vector_engine_selected"] == "vec"
    assert metadata["vector_engine_path"] == "vec_native_topk_sql"
    assert metadata["sqlite_vec_knn_ready"] is True
    assert metadata["rrf_applied"] is True
    assert metadata["rrf_k"] == 10
    assert metadata["rrf_channels"] == ["fts5", "vector"]


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_recreates_vec0_when_dimension_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sqlite_vec = pytest.importorskip("sqlite_vec")
    extension_path = str(sqlite_vec.loadable_path())

    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "64")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "vec")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_READ_RATIO", "100")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_EXTENSION_PATH", extension_path)

    client = SQLiteClient(_sqlite_url(tmp_path / "sqlite-vec-dim-switch.db"))
    await client.init_db()
    status_payload = await client.get_index_status()
    if status_payload["capabilities"]["sqlite_vec_readiness"] != "ready":
        await client.close()
        pytest.skip("sqlite-vec extension cannot be loaded in current SQLite runtime")

    await client.create_memory(
        parent_path="",
        content="sqlite vec dimension switch sample",
        priority=1,
        title="sqlite_vec_dimension_switch",
        domain="core",
    )

    vector_1024 = json.dumps([0.0] * 1024, separators=(",", ":"))
    client._embedding_dim = 1024
    caplog.set_level(logging.WARNING, logger="db.sqlite_client")
    async with client.engine.begin() as conn:
        await conn.execute(
            text("UPDATE memory_chunks_vec SET vector = :vector, dim = 1024"),
            {"vector": vector_1024},
        )
        ready = await conn.run_sync(client._setup_sqlite_vec_knn_infra)
        schema_result = await conn.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'memory_chunks_vec0'")
        )
        count_result = await conn.execute(text("SELECT COUNT(*) FROM memory_chunks_vec0"))

    await client.close()

    assert ready is True
    assert "float[1024]" in str(schema_result.scalar() or "")
    assert int(count_result.scalar() or 0) >= 1
    assert "dimension change: 64 -> 1024" in caplog.text


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_rebuilds_vec0_across_restarted_dimension_switches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sqlite_vec = pytest.importorskip("sqlite_vec")
    extension_path = str(sqlite_vec.loadable_path())
    db_path = tmp_path / "sqlite-vec-dim-switch-restart.db"

    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "64")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "vec")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_READ_RATIO", "100")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_EXTENSION_PATH", extension_path)

    client64 = SQLiteClient(_sqlite_url(db_path))
    await client64.init_db()
    status64 = await client64.get_index_status()
    if status64["capabilities"]["sqlite_vec_readiness"] != "ready":
        await client64.close()
        pytest.skip("sqlite-vec extension cannot be loaded in current SQLite runtime")
    await client64.create_memory(
        parent_path="",
        content="sqlite vec restart dimension alpha sixty four",
        priority=1,
        title="sqlite_vec_restart_dimension_alpha",
        domain="core",
    )
    await client64.close()

    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "1024")
    client1024 = SQLiteClient(_sqlite_url(db_path))
    await client1024.init_db()
    await client1024.create_memory(
        parent_path="",
        content="sqlite vec restart dimension beta ten twenty four",
        priority=1,
        title="sqlite_vec_restart_dimension_beta",
        domain="core",
    )
    search1024 = await client1024.search_advanced(
        query="sqlite vec restart dimension beta ten twenty four",
        mode="semantic",
        max_results=5,
        candidate_multiplier=2,
        filters={},
    )
    async with client1024.session() as session:
        schema1024_result = await session.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'memory_chunks_vec0'")
        )
    await client1024.close()

    assert "float[1024]" in str(schema1024_result.scalar() or "")
    assert search1024["results"]
    assert search1024["mode"] == "semantic"
    assert search1024["metadata"]["indexed_vector_dim_status"] == (
        "mixed_current_aligned"
    )
    assert search1024["metadata"]["vector_engine_path"] == "vec_native_topk_sql"
    assert "vector_dim_mixed_requires_reindex" in search1024["degrade_reasons"]
    assert "embedding_dim_mismatch:64!=1024" in search1024["degrade_reasons"]

    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "64")
    client64_again = SQLiteClient(_sqlite_url(db_path))
    await client64_again.init_db()
    search64 = await client64_again.search_advanced(
        query="sqlite vec restart dimension alpha sixty four",
        mode="semantic",
        max_results=5,
        candidate_multiplier=2,
        filters={},
    )
    async with client64_again.session() as session:
        schema64_result = await session.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'memory_chunks_vec0'")
        )
    await client64_again.close()

    assert "float[64]" in str(schema64_result.scalar() or "")
    assert search64["results"]
    assert search64["mode"] == "semantic"
    assert search64["metadata"]["indexed_vector_dim_status"] == "mixed_current_aligned"
    assert search64["metadata"]["vector_engine_path"] == "vec_native_topk_sql"
    assert "embedding_dim_mismatch:1024!=64" in search64["degrade_reasons"]


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_reports_embedding_dim_mismatch_until_reindex(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "false")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "legacy")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "64")

    db_path = tmp_path / "sqlite-vec-dim-mismatch.db"
    writer_client = SQLiteClient(_sqlite_url(db_path))
    await writer_client.init_db()
    await writer_client.create_memory(
        parent_path="",
        content="dimension mismatch retrieval sample",
        priority=1,
        title="dimension_mismatch",
        domain="core",
    )
    await writer_client.close()

    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "1024")
    reader_client = SQLiteClient(_sqlite_url(db_path))
    await reader_client.init_db()
    search_payload = await reader_client.search_advanced(
        query="dimension mismatch retrieval sample",
        mode="hybrid",
        max_results=5,
        candidate_multiplier=2,
        filters={},
    )
    await reader_client.close()

    assert search_payload["results"]
    assert "embedding_dim_mismatch_requires_reindex" in search_payload["degrade_reasons"]
    assert "embedding_dim_mismatch:64!=1024" in search_payload["degrade_reasons"]


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_scope_filtered_search_ignores_external_dim_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "false")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "legacy")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "64")

    db_path = tmp_path / "sqlite-vec-scope-filter.db"
    legacy_client = SQLiteClient(_sqlite_url(db_path))
    await legacy_client.init_db()
    await legacy_client.create_memory(
        parent_path="",
        content="legacy archive vector sample",
        priority=1,
        title="legacy_archive",
        domain="writer",
    )
    await legacy_client.close()

    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "1024")
    scoped_client = SQLiteClient(_sqlite_url(db_path))
    await scoped_client.init_db()
    await scoped_client.create_memory(
        parent_path="",
        content="core scoped vector sample",
        priority=1,
        title="core_scoped",
        domain="core",
    )
    search_payload = await scoped_client.search_advanced(
        query="core scoped vector sample",
        mode="semantic",
        max_results=5,
        candidate_multiplier=2,
        filters={"domain": "core"},
    )
    await scoped_client.close()

    assert search_payload["results"]
    assert search_payload["mode"] == "semantic"
    assert (
        search_payload["metadata"]["indexed_vector_dim_status"] == "aligned"
    )
    assert "embedding_dim_mismatch_requires_reindex" not in search_payload["degrade_reasons"]
    assert "vector_dim_mixed_requires_reindex" not in search_payload["degrade_reasons"]


@pytest.mark.asyncio
async def test_sqlite_vec_rollout_mixed_dims_skip_self_contradictory_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_SQLITE_VEC_ENABLED", "false")
    monkeypatch.setenv("RETRIEVAL_VECTOR_ENGINE", "legacy")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "64")

    db_path = tmp_path / "sqlite-vec-mixed-dims.db"
    legacy_client = SQLiteClient(_sqlite_url(db_path))
    await legacy_client.init_db()
    await legacy_client.create_memory(
        parent_path="",
        content="legacy mixed vector sample",
        priority=1,
        title="legacy_mixed",
        domain="writer",
    )
    await legacy_client.close()

    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "1024")
    current_client = SQLiteClient(_sqlite_url(db_path))
    await current_client.init_db()
    await current_client.create_memory(
        parent_path="",
        content="current mixed vector sample",
        priority=1,
        title="current_mixed",
        domain="core",
    )
    search_payload = await current_client.search_advanced(
        query="mixed vector sample",
        mode="hybrid",
        max_results=5,
        candidate_multiplier=2,
        filters={},
    )
    await current_client.close()

    assert search_payload["results"]
    assert "embedding_dim_mismatch:64!=1024" in search_payload["degrade_reasons"]
    assert "embedding_dim_mismatch:1024!=1024" not in search_payload["degrade_reasons"]
