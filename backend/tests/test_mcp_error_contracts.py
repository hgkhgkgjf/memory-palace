import json

import pytest

import mcp_server


class _MissingMemoryClient:
    async def get_memory_by_path(self, _path: str, _domain: str):
        return None


class _NoWriteClient:
    async def write_guard(self, **_kwargs):  # pragma: no cover - should never be called
        raise AssertionError("write_guard should not be called for system:// writes")

    async def get_memory_by_path(self, *_args, **_kwargs):  # pragma: no cover
        raise AssertionError("get_memory_by_path should not be called for system:// writes")

    async def remove_path(self, *_args, **_kwargs):  # pragma: no cover
        raise AssertionError("remove_path should not be called for system:// writes")

    async def add_path(self, *_args, **_kwargs):  # pragma: no cover
        raise AssertionError("add_path should not be called for system:// writes")

    async def delete_path_atomically(self, *_args, **_kwargs):  # pragma: no cover
        raise AssertionError("delete_path_atomically should not be called for system:// writes")


class _DeleteMemoryClient:
    async def delete_path_atomically(self, _path: str, _domain: str, *, before_delete=None):
        memory = {
            "id": 9,
            "content": "stale memory",
            "priority": 2,
            "created_at": "2026-01-01T00:00:00Z",
        }
        if before_delete is not None:
            await before_delete(dict(memory))
        return {
            "removed_uri": "core://agent/stale",
            "memory_id": memory["id"],
            "deleted_memory": memory,
        }


class _TimeoutWriteClient:
    async def write_guard(self, **_kwargs):
        return {"action": "ADD", "method": "stub", "reason": "timeout"}


class _SnapshotFailureCreateClient:
    def __init__(self) -> None:
        self._memory = None
        self.rollback_calls = 0

    async def write_guard(self, **_kwargs):
        return {"action": "ADD", "method": "stub", "reason": "allow"}

    async def create_memory(
        self,
        *,
        parent_path: str,
        content: str,
        priority: int,
        title: str,
        domain: str,
        disclosure=None,
        index_now: bool = True,
    ):
        _ = parent_path, priority, disclosure, index_now
        path = title
        self._memory = {
            "id": 41,
            "path": path,
            "domain": domain,
            "uri": f"{domain}://{path}",
            "content": content,
        }
        return dict(self._memory)

    async def get_memory_by_path(self, path: str, domain: str):
        if self._memory and self._memory["path"] == path and self._memory["domain"] == domain:
            return dict(self._memory)
        return None

    async def delete_path_atomically(
        self,
        path: str,
        domain: str,
        *,
        expected_memory_id=None,
        before_delete=None,
    ):
        _ = before_delete
        if expected_memory_id is not None and expected_memory_id != 41:
            raise ValueError("unexpected memory id")
        if self._memory and self._memory["path"] == path and self._memory["domain"] == domain:
            self.rollback_calls += 1
            removed = dict(self._memory)
            self._memory = None
            return {"removed_uri": removed["uri"], "memory_id": removed["id"]}
        raise ValueError("path not found")


class _SnapshotFailureAliasClient:
    def __init__(self) -> None:
        self.alias_exists = False
        self.rollback_calls = 0

    async def add_path(
        self,
        *,
        new_path: str,
        target_path: str,
        new_domain: str,
        target_domain: str,
        priority: int,
        disclosure=None,
    ):
        _ = target_path, target_domain, priority, disclosure
        self.alias_exists = True
        return {
            "new_uri": f"{new_domain}://{new_path}",
            "target_uri": "core://target-node",
            "memory_id": 41,
            "path": new_path,
        }

    async def delete_path_atomically(
        self,
        path: str,
        domain: str,
        *,
        expected_memory_id=None,
        before_delete=None,
    ):
        _ = before_delete
        if expected_memory_id is not None and expected_memory_id != 41:
            raise ValueError("unexpected memory id")
        if self.alias_exists and (domain, path) == ("core", "alias-node"):
            self.alias_exists = False
            self.rollback_calls += 1
            return {"removed_uri": f"{domain}://{path}", "memory_id": 41}
        raise ValueError("alias not found")


@pytest.mark.asyncio
async def test_read_memory_partial_validation_errors_return_json() -> None:
    raw = await mcp_server.read_memory("core://agent/index", chunk_id=-1)
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert "chunk_id must be >= 0" in payload["error"]


@pytest.mark.asyncio
async def test_read_memory_partial_not_found_returns_json(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: _MissingMemoryClient())

    raw = await mcp_server.read_memory("core://agent/missing", chunk_id=0)
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert "not found" in payload["error"]


@pytest.mark.asyncio
async def test_update_memory_identical_patch_returns_tool_response_json() -> None:
    raw = await mcp_server.update_memory(
        uri="core://agent/index",
        old_string="same-content",
        new_string="same-content",
    )
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert payload["updated"] is False
    assert "identical" in payload["message"]


@pytest.mark.asyncio
async def test_search_memory_rejects_non_string_query() -> None:
    raw = await mcp_server.search_memory(123)  # type: ignore[arg-type]
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert payload["error"] == "query must be a string."


@pytest.mark.asyncio
async def test_search_memory_invalid_mode_validated_before_db_init(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("should_not_init_db_for_invalid_mode")

    monkeypatch.setattr(mcp_server, "get_sqlite_client", _boom)

    raw = await mcp_server.search_memory("memory queue", mode="invalid-mode")
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert "Invalid mode" in payload["error"]


@pytest.mark.asyncio
async def test_search_memory_rejects_overlong_query_before_db_init(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("should_not_init_db_for_overlong_query")

    monkeypatch.setattr(mcp_server, "get_sqlite_client", _boom)

    raw = await mcp_server.search_memory("x" * 8001)
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert "at most 8000 characters" in payload["error"]


@pytest.mark.asyncio
async def test_create_memory_rejects_system_domain_writes(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: _NoWriteClient())

    raw = await mcp_server.create_memory(
        parent_uri="system://",
        content="blocked",
        priority=1,
        title="blocked",
    )
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert "read-only" in payload["message"]


@pytest.mark.asyncio
async def test_create_memory_rejects_negative_priority_before_db_write(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: _NoWriteClient())

    raw = await mcp_server.create_memory(
        parent_uri="core://",
        content="blocked",
        priority=-1,
        title="blocked",
    )
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert payload["created"] is False
    assert "priority must be an integer >= 0" in payload["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("priority", [True, False, 0.0, 1.9])
async def test_create_memory_rejects_non_integer_priority_before_db_write(
    monkeypatch,
    priority,
) -> None:
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: _NoWriteClient())

    raw = await mcp_server.create_memory(
        parent_uri="core://",
        content="blocked",
        priority=priority,
        title="blocked",
    )
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert payload["created"] is False
    assert "priority must be an integer >= 0" in payload["message"]


@pytest.mark.asyncio
async def test_create_memory_rejects_overlong_content_before_db_write(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: _NoWriteClient())

    raw = await mcp_server.create_memory(
        parent_uri="core://",
        content="x" * 100001,
        priority=1,
        title="blocked",
    )
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert payload["created"] is False
    assert "at most 100000 characters" in payload["message"]


@pytest.mark.asyncio
async def test_create_memory_write_lane_timeout_returns_retryable_tool_payload(
    monkeypatch,
) -> None:
    async def _raise_timeout(_operation: str, _task):
        raise RuntimeError("write_lane_timeout")

    async def _never_defer():
        return False

    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: _TimeoutWriteClient())
    monkeypatch.setattr(mcp_server, "_run_write_lane", _raise_timeout)
    monkeypatch.setattr(mcp_server, "_should_defer_index_on_write", _never_defer)

    raw = await mcp_server.create_memory(
        parent_uri="core://",
        content="delayed create",
        priority=1,
        title="delayed_note",
    )
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert payload["created"] is False
    assert payload["reason"] == "write_lane_timeout"
    assert payload["retryable"] is True
    assert payload["message"] == "Error: write_lane_timeout"


@pytest.mark.asyncio
async def test_create_memory_snapshot_failure_rolls_back_written_memory(
    monkeypatch,
) -> None:
    client = _SnapshotFailureCreateClient()

    async def _raise_snapshot(*_args, **_kwargs):
        raise OSError("snapshot_fs_failed")

    async def _never_defer():
        return False

    async def _run_write_inline(_operation: str, task):
        return await task()

    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(mcp_server, "_snapshot_path_create", _raise_snapshot)
    monkeypatch.setattr(mcp_server, "_should_defer_index_on_write", _never_defer)
    monkeypatch.setattr(mcp_server, "_run_write_lane", _run_write_inline)

    raw = await mcp_server.create_memory(
        parent_uri="core://",
        content="created before snapshot failure",
        priority=1,
        title="foo",
    )
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert payload["created"] is False
    assert "snapshot" in payload["message"].lower()
    assert client.rollback_calls == 1
    assert await client.get_memory_by_path("foo", "core") is None


@pytest.mark.asyncio
async def test_update_memory_rejects_system_domain_writes() -> None:
    raw = await mcp_server.update_memory(
        uri="system://boot",
        append="\nblocked",
    )
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert "read-only" in payload["message"]


@pytest.mark.asyncio
async def test_update_memory_rejects_negative_priority_before_db_write(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: _NoWriteClient())

    raw = await mcp_server.update_memory(
        uri="core://agent/index",
        priority=-1,
    )
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert payload["updated"] is False
    assert "priority must be an integer >= 0" in payload["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("priority", [True, False, 0.0, 1.9])
async def test_update_memory_rejects_non_integer_priority_before_db_write(
    monkeypatch,
    priority,
) -> None:
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: _NoWriteClient())

    raw = await mcp_server.update_memory(
        uri="core://agent/index",
        priority=priority,
    )
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert payload["updated"] is False
    assert "priority must be an integer >= 0" in payload["message"]


@pytest.mark.asyncio
async def test_update_memory_rejects_overlong_append_before_db_write(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: _NoWriteClient())

    raw = await mcp_server.update_memory(
        uri="core://agent/index",
        append="x" * 100001,
    )
    payload = json.loads(raw)

    assert payload["ok"] is False
    assert payload["updated"] is False
    assert "at most 100000 characters" in payload["message"]


@pytest.mark.asyncio
async def test_delete_memory_rejects_system_domain_writes(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: _NoWriteClient())
    raw = await mcp_server.delete_memory("system://boot")
    payload = json.loads(raw)
    assert payload["ok"] is False
    assert payload["deleted"] is False
    assert "read-only" in payload["message"]


@pytest.mark.asyncio
async def test_delete_memory_records_deletion_time_in_session_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    async def _noop_async(*_args, **_kwargs) -> None:
        return None

    async def _run_write_inline(_operation: str, task):
        return await task()

    async def _capture_session_hit(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: _DeleteMemoryClient())
    monkeypatch.setattr(mcp_server, "_snapshot_path_delete", _noop_async)
    monkeypatch.setattr(mcp_server, "_run_write_lane", _run_write_inline)
    monkeypatch.setattr(mcp_server, "_record_session_hit", _capture_session_hit)
    monkeypatch.setattr(mcp_server, "_record_flush_event", _noop_async)
    monkeypatch.setattr(mcp_server, "_maybe_auto_flush", _noop_async)
    monkeypatch.setattr(mcp_server, "_utc_iso_now", lambda: "2026-03-20T12:00:00Z")

    raw = await mcp_server.delete_memory("core://agent/stale")
    payload = json.loads(raw)

    assert payload["ok"] is True
    assert payload["deleted"] is True
    assert payload["uri"] == "core://agent/stale"
    assert payload["message"] == "Success: Memory 'core://agent/stale' deleted."
    assert captured["updated_at"] == "2026-03-20T12:00:00Z"


@pytest.mark.asyncio
async def test_add_alias_rejects_system_domain_writes(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: _NoWriteClient())
    raw = await mcp_server.add_alias("core://alias-node", "system://boot")
    assert raw.startswith("Error:")
    assert "read-only" in raw


@pytest.mark.asyncio
@pytest.mark.parametrize("priority", [True, False, 0.0, 1.9])
async def test_add_alias_rejects_non_integer_priority_before_db_write(
    monkeypatch,
    priority,
) -> None:
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: _NoWriteClient())

    raw = await mcp_server.add_alias(
        "core://alias-node",
        "core://target-node",
        priority=priority,
    )

    assert raw.startswith("Error:")
    assert "priority must be an integer >= 0" in raw


@pytest.mark.asyncio
async def test_add_alias_snapshot_failure_rolls_back_written_alias(monkeypatch) -> None:
    client = _SnapshotFailureAliasClient()

    async def _raise_snapshot(*_args, **_kwargs):
        raise OSError("snapshot_fs_failed")

    async def _run_write_inline(_operation: str, task):
        return await task()

    async def _noop_async(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(mcp_server, "_snapshot_path_create", _raise_snapshot)
    monkeypatch.setattr(mcp_server, "_run_write_lane", _run_write_inline)
    monkeypatch.setattr(mcp_server, "_record_session_hit", _noop_async)
    monkeypatch.setattr(mcp_server, "_record_flush_event", _noop_async)
    monkeypatch.setattr(mcp_server, "_maybe_auto_flush", _noop_async)

    raw = await mcp_server.add_alias("core://alias-node", "core://target-node")

    assert raw.startswith("Error:")
    assert "snapshot" in raw.lower()
    assert client.rollback_calls == 1
    assert client.alias_exists is False


def test_get_session_id_stays_stable_within_shared_context_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeRequestContext:
        def __init__(self, session_obj, request_obj) -> None:
            self.session = session_obj
            self.request = request_obj

    class _FakeContext:
        def __init__(
            self,
            *,
            client_id: str,
            request_id: str,
            session_obj,
            request_obj,
        ) -> None:
            self._client_id = client_id
            self._request_id = request_id
            self._session_obj = session_obj
            self._request_context = _FakeRequestContext(session_obj, request_obj)

        @property
        def client_id(self):
            return self._client_id

        @property
        def request_id(self):
            return self._request_id

        @property
        def session(self):
            return self._session_obj

        @property
        def request_context(self):
            return self._request_context

    shared_session = object()
    ctx_a = _FakeContext(
        client_id="client-A",
        request_id="req-001",
        session_obj=shared_session,
        request_obj=object(),
    )
    ctx_b = _FakeContext(
        client_id="client-A",
        request_id="req-002",
        session_obj=shared_session,
        request_obj=object(),
    )

    monkeypatch.setattr(mcp_server.mcp, "get_context", lambda: ctx_a)
    session_a = mcp_server.get_session_id()
    monkeypatch.setattr(mcp_server.mcp, "get_context", lambda: ctx_b)
    session_b = mcp_server.get_session_id()

    assert session_a.startswith("mcp_ctx_")
    assert session_b.startswith("mcp_ctx_")
    assert session_a == session_b


def test_get_session_id_falls_back_to_request_fragment_when_session_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeRequestContext:
        def __init__(self, request_obj) -> None:
            self.request = request_obj

    class _FakeContext:
        def __init__(self, *, client_id: str, request_id: str, request_obj) -> None:
            self._client_id = client_id
            self._request_id = request_id
            self._request_context = _FakeRequestContext(request_obj)

        @property
        def client_id(self):
            return self._client_id

        @property
        def request_id(self):
            return self._request_id

        @property
        def session(self):
            return None

        @property
        def request_context(self):
            return self._request_context

    ctx_a = _FakeContext(
        client_id="client-A",
        request_id="req-001",
        request_obj=object(),
    )
    ctx_b = _FakeContext(
        client_id="client-A",
        request_id="req-002",
        request_obj=object(),
    )

    monkeypatch.setattr(mcp_server.mcp, "get_context", lambda: ctx_a)
    session_a = mcp_server.get_session_id()
    monkeypatch.setattr(mcp_server.mcp, "get_context", lambda: ctx_b)
    session_b = mcp_server.get_session_id()

    assert session_a.startswith("mcp_ctx_")
    assert session_b.startswith("mcp_ctx_")
    assert session_a != session_b


def test_get_session_id_falls_back_when_context_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_context_error():
        raise RuntimeError("context unavailable")

    monkeypatch.setattr(mcp_server.mcp, "get_context", _raise_context_error)
    assert mcp_server.get_session_id() == mcp_server._SESSION_ID


def test_safe_int_rejects_bool_values() -> None:
    assert mcp_server._safe_int(True, default=7) == 7
    assert mcp_server._safe_int(False, default=7) == 7
    assert mcp_server._safe_int("12", default=7) == 12
