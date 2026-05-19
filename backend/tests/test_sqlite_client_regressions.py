import inspect
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import text

import db.sqlite_client as sqlite_client_module
from db.sqlite_client import Memory, SQLiteClient


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


class _CaptureCursor:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, sql: str) -> None:
        self.executed.append(sql)


async def _get_memory_index_counts(
    client: SQLiteClient,
    memory_id: int,
    *,
    include_fts: bool = False,
) -> dict[str, int]:
    async with client.session() as session:
        chunk_count = await session.execute(
            text("SELECT COUNT(*) FROM memory_chunks WHERE memory_id = :memory_id"),
            {"memory_id": int(memory_id)},
        )
        vec_count = await session.execute(
            text("SELECT COUNT(*) FROM memory_chunks_vec WHERE memory_id = :memory_id"),
            {"memory_id": int(memory_id)},
        )
        counts = {
            "memory_chunks": int(chunk_count.scalar() or 0),
            "memory_chunks_vec": int(vec_count.scalar() or 0),
        }
        if include_fts:
            fts_count = await session.execute(
                text(
                    "SELECT COUNT(*) FROM memory_chunks_fts "
                    "WHERE memory_id = :memory_id"
                ),
                {"memory_id": int(memory_id)},
            )
            counts["memory_chunks_fts"] = int(fts_count.scalar() or 0)
        return counts


@pytest.fixture(autouse=True)
def _force_local_retrieval_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RETRIEVAL_RERANKER_ENABLED", "false")


@pytest.mark.asyncio
async def test_get_index_status_does_not_persist_missing_fts_state(
    tmp_path: Path,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "fts-status-regression.db"))
    await client.init_db()

    if not client._fts_available:
        await client.close()
        pytest.skip("SQLite FTS5 not available in this environment")

    async with client.session() as session:
        await session.execute(text("DROP TABLE IF EXISTS memory_chunks_fts"))

    missing_status = await client.get_index_status()
    assert missing_status["capabilities"]["fts_available"] is False
    assert client._fts_available is True

    async with client.session() as session:
        await session.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks_fts "
                "USING fts5(chunk_id UNINDEXED, memory_id UNINDEXED, chunk_text)"
            )
        )

    restored_status = await client.get_index_status()
    await client.close()

    assert restored_status["capabilities"]["fts_available"] is True


@pytest.mark.asyncio
async def test_init_db_runs_integrity_check_for_existing_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "init-db-integrity-check.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()
    await client.close()

    seen_paths: list[Path | None] = []
    original_check = sqlite_client_module._validate_existing_sqlite_file_integrity

    def _capture_check(path: Path | None) -> None:
        seen_paths.append(path)
        original_check(path)

    monkeypatch.setattr(
        sqlite_client_module,
        "_validate_existing_sqlite_file_integrity",
        _capture_check,
    )

    reloaded = SQLiteClient(_sqlite_url(db_path))
    await reloaded.init_db()
    await reloaded.close()

    assert seen_paths == [db_path]


@pytest.mark.asyncio
async def test_init_db_fails_closed_for_corrupt_existing_database(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "init-db-corrupt-existing.db"
    db_path.write_bytes(b"not a sqlite database")

    client = SQLiteClient(_sqlite_url(db_path))
    with pytest.raises(RuntimeError, match="quick_check failed"):
        await client.init_db()
    await client.close()


@pytest.mark.asyncio
async def test_invalid_fts_query_degrades_only_current_request_without_disabling_fts(
    tmp_path: Path,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "fts-invalid-query-regression.db"))
    await client.init_db()

    if not client._fts_available:
        await client.close()
        pytest.skip("SQLite FTS5 not available in this environment")

    await client.create_memory(
        parent_path="",
        content="quoted search target",
        priority=1,
        title="quoted-target",
        domain="core",
    )

    result = await client.search_advanced(
        query='"',
        mode="keyword",
        max_results=5,
        candidate_multiplier=4,
        filters={},
    )
    status = await client.get_index_status()
    await client.close()

    assert result["degraded"] is True
    assert "fts_query_invalid" in result["degrade_reasons"]
    assert client._fts_available is True
    assert status["capabilities"]["fts_available"] is True


@pytest.mark.asyncio
async def test_reserved_fts_operators_do_not_control_query_semantics(
    tmp_path: Path,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "fts-reserved-operator-regression.db"))
    await client.init_db()

    await client.create_memory(
        parent_path="",
        content="apple only fruit",
        priority=1,
        title="apple",
        domain="core",
    )
    await client.create_memory(
        parent_path="",
        content="banana only fruit",
        priority=1,
        title="banana",
        domain="core",
    )

    result = await client.search_advanced(
        query="apple OR banana",
        mode="keyword",
        max_results=5,
        candidate_multiplier=4,
        filters={},
    )
    await client.close()

    uris = [row["uri"] for row in result["results"]]
    assert "fts_query_invalid" not in result.get("degrade_reasons", [])
    assert "core://apple" in uris
    assert "core://banana" in uris


@pytest.mark.asyncio
async def test_special_character_queries_skip_invalid_fts_errors(
    tmp_path: Path,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "fts-special-char-regression.db"))
    await client.init_db()

    await client.create_memory(
        parent_path="",
        content="记忆 宫殿 中文",
        priority=1,
        title="cjk",
        domain="core",
    )

    result = await client.search_advanced(
        query="记忆 OR 宫殿",
        mode="keyword",
        max_results=5,
        candidate_multiplier=4,
        filters={},
    )
    wildcard_result = await client.search_advanced(
        query="***",
        mode="keyword",
        max_results=5,
        candidate_multiplier=4,
        filters={},
    )
    await client.close()

    assert "fts_query_invalid" not in result.get("degrade_reasons", [])
    assert "fts_query_invalid" not in wildcard_result.get("degrade_reasons", [])


@pytest.mark.asyncio
async def test_semantic_python_scoring_pool_limit_respects_candidate_cap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "semantic-pool-cap-regression.db"))
    await client.init_db()
    client._vector_available = True

    captured: dict[str, int] = {}

    async def _fake_get_indexed_vector_dims(*args, **kwargs) -> list[int]:
        return [int(client._embedding_dim)]

    async def _fake_get_embedding(*args, **kwargs) -> list[float]:
        return [0.0] * int(client._embedding_dim)

    async def _fake_fetch_semantic_rows_python_scoring(*args, **kwargs):
        captured["semantic_pool_limit"] = int(kwargs["semantic_pool_limit"])
        captured["candidate_limit"] = int(kwargs["candidate_limit"])
        return []

    monkeypatch.setattr(client, "_resolve_vector_engine_for_query", lambda query: "legacy")
    monkeypatch.setattr(client, "_get_indexed_vector_dims", _fake_get_indexed_vector_dims)
    monkeypatch.setattr(client, "_get_embedding", _fake_get_embedding)
    monkeypatch.setattr(
        client,
        "_fetch_semantic_rows_python_scoring",
        _fake_fetch_semantic_rows_python_scoring,
    )

    payload = await client.search_advanced(
        query="semantic pool hard cap regression",
        mode="semantic",
        max_results=100,
        candidate_multiplier=50,
        filters={},
    )
    await client.close()

    metadata = payload["metadata"]
    assert metadata["vector_engine_path"] == "legacy_python_scoring"
    assert metadata["candidate_limit_applied"] == client._search_candidate_limit_hard_cap
    assert captured["candidate_limit"] == client._search_candidate_limit_hard_cap
    assert captured["semantic_pool_limit"] <= client._search_candidate_limit_hard_cap


@pytest.mark.asyncio
async def test_sqlite_identifier_hardening_rejects_invalid_table_name(
    tmp_path: Path,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "sqlite-identifier-hardening.db"))
    await client.init_db()

    assert client._quote_sqlite_identifier("memory_chunks_vec0") == '"memory_chunks_vec0"'
    with pytest.raises(ValueError, match="invalid sqlite identifier"):
        client._quote_sqlite_identifier("memory_chunks_vec0; DROP TABLE memories; --")

    await client.close()


@pytest.mark.asyncio
async def test_runtime_write_pragma_hardening_validates_names_and_values(
    tmp_path: Path,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "sqlite-pragma-hardening.db"))
    await client.init_db()

    cursor = _CaptureCursor()
    client._execute_sqlite_pragma(cursor, "busy_timeout", 5000)
    client._execute_sqlite_pragma(
        cursor,
        "journal_mode",
        "WAL",
        allowed_values={"WAL", "DELETE"},
    )

    assert cursor.executed == [
        "PRAGMA busy_timeout=5000",
        "PRAGMA journal_mode=WAL",
    ]

    with pytest.raises(ValueError, match="unsupported pragma"):
        client._execute_sqlite_pragma(cursor, "busy_timeout; DROP TABLE memories", 1)

    with pytest.raises(ValueError, match="invalid pragma value"):
        client._execute_sqlite_pragma(
            cursor,
            "journal_mode",
            "WAL; DROP TABLE memories",
            allowed_values={"WAL", "DELETE"},
        )

    await client.close()


@pytest.mark.asyncio
async def test_keyword_fallback_escapes_like_wildcards_in_query(
    tmp_path: Path,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "fts-like-wildcard-regression.db"))
    await client.init_db()

    await client.create_memory(
        parent_path="",
        content="alpha note",
        priority=1,
        title="alpha",
        domain="core",
    )
    await client.create_memory(
        parent_path="",
        content="beta note",
        priority=1,
        title="beta",
        domain="core",
    )

    result = await client.search_advanced(
        query="%",
        mode="keyword",
        max_results=5,
        candidate_multiplier=4,
        filters={},
    )
    await client.close()

    assert result["degraded"] is True
    assert "fts_query_invalid" in result["degrade_reasons"]
    assert result["results"] == []


@pytest.mark.asyncio
async def test_resolve_migration_chain_supports_long_noncyclic_chains(
    tmp_path: Path,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "migration-chain-regression.db"))
    await client.init_db()

    async with client.session() as session:
        chain = [Memory(content=f"version-{idx}", deprecated=(idx < 59)) for idx in range(60)]
        session.add_all(chain)
        await session.flush()

        for idx, memory in enumerate(chain[:-1]):
            memory.migrated_to = chain[idx + 1].id
            session.add(memory)

        resolved = await client._resolve_migration_chain(session, chain[0].id)

    await client.close()

    assert resolved is not None
    assert resolved["id"] == chain[-1].id


@pytest.mark.asyncio
async def test_legacy_search_forwards_requested_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "legacy-search-mode.db"))
    await client.init_db()

    captured: dict[str, object] = {}

    async def _fake_search_advanced(**kwargs):
        captured.update(kwargs)
        return {"results": []}

    monkeypatch.setattr(client, "search_advanced", _fake_search_advanced)

    await client.search("legacy mode sample", limit=3, domain="core", mode="hybrid")
    await client.close()

    assert captured["mode"] == "hybrid"
    assert captured["filters"] == {"domain": "core"}
    assert captured["max_results"] == 3


@pytest.mark.asyncio
async def test_permanently_delete_memory_rejects_referenced_orphan_chain_tail(
    tmp_path: Path,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "chain-tail-guard.db"))
    await client.init_db()

    await client.create_memory(
        parent_path="",
        content="version-1",
        priority=1,
        title="chain_tail_guard",
        domain="core",
    )
    await client.update_memory(path="chain_tail_guard", content="version-2", domain="core")
    second = await client.update_memory(
        path="chain_tail_guard",
        content="version-3",
        domain="core",
    )
    tail_id = int(second["new_memory_id"])

    await client.remove_path(path="chain_tail_guard", domain="core")

    with pytest.raises(PermissionError, match="final target"):
        await client.permanently_delete_memory(tail_id, require_orphan=True)

    async with client.session() as session:
        still_exists = await session.get(Memory, tail_id)

    await client.close()

    assert still_exists is not None


@pytest.mark.asyncio
async def test_update_memory_rejects_stale_expected_memory_id(tmp_path: Path) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "update-memory-cas.db"))
    await client.init_db()

    await client.create_memory(
        parent_path="",
        content="version-1",
        priority=1,
        title="cas-target",
        domain="core",
    )
    initial = await client.get_memory_by_path(
        "cas-target",
        domain="core",
        reinforce_access=False,
    )
    assert initial is not None
    stale_id = int(initial["id"])

    await client.update_memory(
        path="cas-target",
        content="version-2",
        domain="core",
        expected_memory_id=stale_id,
    )

    with pytest.raises(ValueError, match="Memory version conflict"):
        await client.update_memory(
            path="cas-target",
            content="version-3",
            domain="core",
            expected_memory_id=stale_id,
        )

    current = await client.get_memory_by_path(
        "cas-target",
        domain="core",
        reinforce_access=False,
    )
    assert current is not None
    assert current["content"] == "version-2"

    await client.close()


@pytest.mark.asyncio
async def test_update_memory_allows_legacy_call_without_expected_memory_id(
    tmp_path: Path,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "update-memory-cas-none.db"))
    await client.init_db()

    await client.create_memory(
        parent_path="",
        content="version-1",
        priority=1,
        title="cas-none-target",
        domain="core",
    )
    await client.update_memory(
        path="cas-none-target",
        content="version-2",
        domain="core",
    )

    updated = await client.update_memory(
        path="cas-none-target",
        content="version-3",
        domain="core",
        expected_memory_id=None,
    )
    current = await client.get_memory_by_path(
        "cas-none-target",
        domain="core",
        reinforce_access=False,
    )

    await client.close()

    assert int(updated["new_memory_id"]) == int(current["id"])
    assert current["content"] == "version-3"


@pytest.mark.asyncio
async def test_update_memory_rejects_invalid_expected_memory_id(
    tmp_path: Path,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "update-memory-cas-invalid.db"))
    await client.init_db()

    await client.create_memory(
        parent_path="",
        content="version-1",
        priority=1,
        title="cas-invalid-target",
        domain="core",
    )

    with pytest.raises(ValueError, match="Memory version conflict"):
        await client.update_memory(
            path="cas-invalid-target",
            content="version-2",
            domain="core",
            expected_memory_id="not-an-int",  # type: ignore[arg-type]
        )

    current = await client.get_memory_by_path(
        "cas-invalid-target",
        domain="core",
        reinforce_access=False,
    )

    await client.close()

    assert current is not None
    assert current["content"] == "version-1"


def test_create_memory_has_no_expected_memory_id_parameter() -> None:
    signature = inspect.signature(SQLiteClient.create_memory)

    assert "expected_memory_id" not in signature.parameters


@pytest.mark.asyncio
async def test_permanently_delete_memory_clears_chunk_tables_and_fts_rows(
    tmp_path: Path,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "permanent-delete-index-cleanup.db"))
    await client.init_db()

    if not client._fts_available:
        await client.close()
        pytest.skip("SQLite FTS5 not available in this environment")

    created = await client.create_memory(
        parent_path="",
        content="记忆宫殿 删除回归测试 " * 20,
        priority=1,
        title="delete-index-cleanup",
        domain="core",
    )
    memory_id = int(created["id"])

    before_counts = await _get_memory_index_counts(client, memory_id, include_fts=True)
    await client.permanently_delete_memory(memory_id)
    after_counts = await _get_memory_index_counts(client, memory_id, include_fts=True)

    async with client.session() as session:
        deleted_memory = await session.get(Memory, memory_id)

    await client.close()

    assert before_counts["memory_chunks"] > 0
    assert before_counts["memory_chunks_vec"] == before_counts["memory_chunks"]
    assert before_counts["memory_chunks_fts"] == before_counts["memory_chunks"]
    assert deleted_memory is None
    assert after_counts == {
        "memory_chunks": 0,
        "memory_chunks_vec": 0,
        "memory_chunks_fts": 0,
    }


@pytest.mark.asyncio
async def test_init_db_rebuilds_fts_rows_when_fts_table_was_missing(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "init-db-fts-repair.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    if not client._fts_available:
        await client.close()
        pytest.skip("SQLite FTS5 not available in this environment")

    created = await client.create_memory(
        parent_path="",
        content="记忆 宫殿 FTS repair regression " * 16,
        priority=1,
        title="fts-repair-target",
        domain="core",
    )
    memory_id = int(created["id"])
    before_counts = await _get_memory_index_counts(client, memory_id, include_fts=True)

    async with client.session() as session:
        await session.execute(text("DROP TABLE memory_chunks_fts"))

    await client.close()

    repair_client = SQLiteClient(_sqlite_url(db_path))
    await repair_client.init_db()

    async with repair_client.session() as session:
        fts_exists_result = await session.execute(
            text(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'table' AND name = 'memory_chunks_fts'"
            )
        )
        fts_exists = int(fts_exists_result.scalar() or 0)

    after_counts = await _get_memory_index_counts(
        repair_client,
        memory_id,
        include_fts=True,
    )
    await repair_client.close()

    assert before_counts["memory_chunks"] > 0
    assert before_counts["memory_chunks_fts"] == before_counts["memory_chunks"]
    assert fts_exists == 1
    assert after_counts["memory_chunks"] == before_counts["memory_chunks"]
    assert after_counts["memory_chunks_fts"] == before_counts["memory_chunks"]


@pytest.mark.asyncio
async def test_cjk_control_word_query_returns_term_matches(tmp_path: Path) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "cjk-control-word-regression.db"))
    await client.init_db()

    await client.create_memory(
        parent_path="",
        content="这条记录包含记忆与宫殿两个词。",
        priority=1,
        title="cjk-control-word-hit",
        domain="core",
    )
    await client.create_memory(
        parent_path="",
        content="这里只有花园，没有目标词。",
        priority=1,
        title="cjk-control-word-miss",
        domain="core",
    )

    result = await client.search_advanced(
        query="记忆 OR 宫殿",
        mode="keyword",
        max_results=5,
        candidate_multiplier=4,
        filters={},
    )
    await client.close()

    uris = [row["uri"] for row in result["results"]]
    assert "fts_query_invalid" not in result.get("degrade_reasons", [])
    assert "core://cjk-control-word-hit" in uris


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "   \n\t  "])
async def test_create_memory_rejects_blank_content(
    tmp_path: Path,
    content: str,
) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "blank-content-regression.db"))
    await client.init_db()

    with pytest.raises(ValueError, match="content must not be empty"):
        await client.create_memory(
            parent_path="",
            content=content,
            priority=1,
            title="blank-content",
            domain="core",
        )

    await client.close()


@pytest.mark.asyncio
async def test_priority_inputs_reject_negative_values(tmp_path: Path) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "priority-validation.db"))
    await client.init_db()

    with pytest.raises(ValueError, match="priority must be an integer >= 0"):
        await client.create_memory(
            parent_path="",
            content="invalid create priority",
            priority=-1,
            title="invalid-priority",
            domain="core",
        )

    created = await client.create_memory(
        parent_path="",
        content="valid root",
        priority=0,
        title="valid-root",
        domain="core",
    )
    assert created["priority"] == 0

    with pytest.raises(ValueError, match="priority must be an integer >= 0"):
        await client.update_memory(
            path="valid-root",
            priority=-3,
            domain="core",
        )

    with pytest.raises(ValueError, match="priority must be an integer >= 0"):
        await client.add_path(
            new_path="valid-root-alias",
            target_path="valid-root",
            new_domain="core",
            target_domain="core",
            priority=-2,
        )

    with pytest.raises(ValueError, match="priority must be an integer >= 0"):
        await client.restore_path_metadata(
            path="valid-root",
            priority=-4,
            disclosure=None,
            domain="core",
        )

    await client.close()


@pytest.mark.asyncio
async def test_priority_inputs_reject_non_integer_numeric_values(tmp_path: Path) -> None:
    client = SQLiteClient(_sqlite_url(tmp_path / "priority-non-integer-validation.db"))
    await client.init_db()

    with pytest.raises(ValueError, match="priority must be an integer >= 0"):
        await client.create_memory(
            parent_path="",
            content="invalid float priority",
            priority=1.9,
            title="invalid-float-priority",
            domain="core",
        )

    await client.create_memory(
        parent_path="",
        content="valid priority target",
        priority=1,
        title="valid-priority-target",
        domain="core",
    )

    with pytest.raises(ValueError, match="priority must be an integer >= 0"):
        await client.update_memory(
            path="valid-priority-target",
            priority=True,
            domain="core",
        )

    with pytest.raises(ValueError, match="priority must be an integer >= 0"):
        await client.restore_path_metadata(
            path="valid-priority-target",
            priority=False,
            disclosure=None,
            domain="core",
        )

    await client.close()


def test_get_sqlite_client_initializes_singleton_once_under_thread_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_urls: list[str] = []
    original_client = sqlite_client_module._sqlite_client
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:////tmp/threadsafe-singleton.db")

    class _FakeClient:
        def __init__(self, database_url: str) -> None:
            created_urls.append(database_url)
            time.sleep(0.02)
            self.database_url = database_url

        async def close(self) -> None:
            return None

    monkeypatch.setattr(sqlite_client_module, "SQLiteClient", _FakeClient)
    sqlite_client_module._sqlite_client = None

    def _resolve_client():
        return sqlite_client_module.get_sqlite_client()

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            clients = list(pool.map(lambda _: _resolve_client(), range(8)))
    finally:
        sqlite_client_module._sqlite_client = original_client

    assert len(created_urls) == 1
    assert len({id(client) for client in clients}) == 1


def test_parse_iso_datetime_normalizes_timezone_offsets_to_utc_naive() -> None:
    parsed = SQLiteClient._parse_iso_datetime("2026-03-21T16:30:00+08:00")

    assert parsed == sqlite_client_module.datetime(2026, 3, 21, 8, 30, 0)
    assert parsed.tzinfo is None


def test_mmr_tokens_keep_cjk_chunks_and_bigrams() -> None:
    tokens = SQLiteClient._mmr_tokens(
        {
            "snippet": "部署 deployment guide",
            "metadata": {"path": "部署/指南"},
        }
    )

    assert "deployment" in tokens
    assert "guide" in tokens
    assert "部署" in tokens
    assert "部" not in tokens


def test_jaccard_similarity_detects_overlap_for_pure_cjk_results() -> None:
    first = SQLiteClient._mmr_tokens(
        {
            "snippet": "部署指南",
            "metadata": {"path": "部署/手册"},
        }
    )
    second = SQLiteClient._mmr_tokens(
        {
            "snippet": "部署文档",
            "metadata": {"path": "部署/教程"},
        }
    )

    assert first
    assert second
    assert SQLiteClient._jaccard_similarity(first, second) > 0.0


def test_hash_embedding_keeps_cjk_tokens_in_mixed_text() -> None:
    client = SQLiteClient("sqlite+aiosqlite:///:memory:")

    mixed = client._hash_embedding("部署 deployment guide", dim=64)
    latin_only = client._hash_embedding("deployment guide", dim=64)
    pure_cjk = client._hash_embedding("部署 指南", dim=64)

    assert mixed != latin_only
    assert any(value != 0.0 for value in pure_cjk)


@pytest.mark.asyncio
async def test_reranker_invalid_success_payload_adds_degrade_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RETRIEVAL_RERANKER_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_RERANKER_API_BASE", "https://rerank.example/v1")
    monkeypatch.setenv("RETRIEVAL_RERANKER_MODEL", "rerank-model")

    client = SQLiteClient(_sqlite_url(tmp_path / "reranker-invalid-payload.db"))
    await client.init_db()

    async def _fake_post_json_with_optional_error_sink(
        base: str,
        endpoint: str,
        payload,
        api_key: str = "",
        error_sink=None,
    ):
        _ = base, endpoint, payload, api_key, error_sink
        return {"results": [{"index": "nope", "score": "bad"}]}

    monkeypatch.setattr(
        client,
        "_post_json_with_optional_error_sink",
        _fake_post_json_with_optional_error_sink,
    )
    degrade_reasons: list[str] = []
    scores = await client._get_rerank_scores(
        "reranker invalid payload sample",
        ["alpha", "beta"],
        degrade_reasons=degrade_reasons,
    )
    await client.close()

    assert scores == {}
    assert "reranker_response_invalid" in degrade_reasons


def test_hash_embedding_normalizes_fullwidth_latin_tokens() -> None:
    client = SQLiteClient("sqlite+aiosqlite:///:memory:")

    fullwidth = client._hash_embedding("ＡＰＩ 错误", dim=64)
    ascii_text = client._hash_embedding("API 错误", dim=64)
    tokens = SQLiteClient._mmr_tokens(
        {
            "snippet": "ＡＰＩ 错误 修复记录",
            "metadata": {"path": "api/错误"},
        }
    )

    assert fullwidth == ascii_text
    assert "api" in tokens


def test_apply_mmr_rerank_avoids_duplicate_pure_cjk_results() -> None:
    client = SQLiteClient("sqlite+aiosqlite:///:memory:")

    selected, metadata = client._apply_mmr_rerank(
        [
            {
                "uri": "core://a",
                "snippet": "部署指南",
                "metadata": {"path": "部署/指南"},
                "scores": {"final": 1.0},
            },
            {
                "uri": "core://b",
                "snippet": "部署指南",
                "metadata": {"path": "部署/指南-副本"},
                "scores": {"final": 0.99},
            },
            {
                "uri": "core://c",
                "snippet": "恢复手册",
                "metadata": {"path": "恢复/手册"},
                "scores": {"final": 0.95},
            },
        ],
        max_results=2,
    )

    assert metadata["mmr_applied"] is True
    assert [row["uri"] for row in selected] == ["core://a", "core://c"]
