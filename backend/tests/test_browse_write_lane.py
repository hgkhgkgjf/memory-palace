from typing import Any, Dict, Optional

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api import browse as browse_api


class _FakeBrowseClient:
    def __init__(self) -> None:
        self.memory = {
            "id": 7,
            "content": "origin",
            "priority": 1,
            "disclosure": None,
        }
        self.create_called = False
        self.update_called = False
        self.delete_atomically_called = False
        self.in_lane = False
        self.guard_calls_in_lane: list[bool] = []

    async def write_guard(self, **_: Any) -> Dict[str, Any]:
        self.guard_calls_in_lane.append(self.in_lane)
        return {
            "action": "ADD",
            "reason": "allow",
            "method": "keyword",
        }

    async def create_memory(self, **_: Any) -> Dict[str, Any]:
        self.create_called = True
        return {
            "id": 11,
            "path": "agent/new_note",
            "uri": "core://agent/new_note",
            "index_targets": [11],
        }

    async def get_memory_by_path(
        self, path: str, domain: str = "core", reinforce_access: bool = True
    ) -> Optional[Dict[str, Any]]:
        _ = path
        _ = domain
        _ = reinforce_access
        return dict(self.memory)

    async def get_memory_by_id(self, memory_id: int) -> Dict[str, Any]:
        _ = memory_id
        return {"id": self.memory["id"], "paths": ["core://agent/new_note"]}

    async def update_memory(self, **_: Any) -> Dict[str, Any]:
        self.update_called = True
        return {
            "uri": "core://agent/new_note",
            "new_memory_id": 19,
            "index_targets": [19],
        }

    async def delete_path_atomically(
        self, path: str, domain: str = "core", *, before_delete=None
    ) -> Dict[str, Any]:
        self.delete_atomically_called = True
        memory = {
            "id": 19,
            "content": "updated content",
            "priority": 1,
            "disclosure": None,
            "domain": domain,
            "path": path,
        }
        if before_delete is not None:
            await before_delete(dict(memory))
        return {
            "removed_uri": f"{domain}://{path}",
            "memory_id": 19,
            "deleted_memory": memory,
        }


class _FakeBrowseClientWithLaneHeadRefresh(_FakeBrowseClient):
    async def write_guard(self, **_: Any) -> Dict[str, Any]:
        self.guard_calls_in_lane.append(self.in_lane)
        return {
            "action": "UPDATE",
            "target_id": 19,
            "reason": "head_refreshed_in_lane",
            "method": "keyword",
        }

    async def get_memory_by_path(
        self, path: str, domain: str = "core", reinforce_access: bool = True
    ) -> Optional[Dict[str, Any]]:
        _ = path
        _ = domain
        _ = reinforce_access
        memory_id = 19 if self.in_lane else 7
        return {
            "id": memory_id,
            "content": "origin",
            "priority": 1,
            "disclosure": None,
        }


class _FakeBrowseClientWithUpdateConflict(_FakeBrowseClient):
    async def update_memory(self, **_: Any) -> Dict[str, Any]:
        raise ValueError(
            "Memory version conflict for 'core://agent/new_note': "
            "expected memory id 7, current memory id 8"
        )


class _FakeSnapshotManager:
    def __init__(self) -> None:
        self.snapshots: dict[str, dict[str, dict[str, Any]]] = {}
        self.created: list[dict[str, Any]] = []
        self.deleted: list[tuple[str, str]] = []

    def has_snapshot(self, session_id: str, resource_id: str) -> bool:
        return resource_id in self.snapshots.get(session_id, {})

    def find_memory_snapshot_by_uri(self, session_id: str, uri: str) -> Optional[str]:
        for resource_id, snapshot in self.snapshots.get(session_id, {}).items():
            if (
                snapshot.get("resource_type") == "memory"
                and snapshot.get("data", {}).get("uri") == uri
            ):
                return resource_id
        return None

    def create_snapshot(
        self,
        *,
        session_id: str,
        resource_id: str,
        resource_type: str,
        snapshot_data: dict[str, Any],
        force: bool = False,
    ) -> bool:
        if not force and self.has_snapshot(session_id, resource_id):
            return False
        self.snapshots.setdefault(session_id, {})[resource_id] = {
            "resource_type": resource_type,
            "data": dict(snapshot_data),
        }
        self.created.append(
            {
                "session_id": session_id,
                "resource_id": resource_id,
                "resource_type": resource_type,
                "data": dict(snapshot_data),
                "force": force,
            }
        )
        return True

    def get_snapshot(self, session_id: str, resource_id: str) -> Optional[dict[str, Any]]:
        return self.snapshots.get(session_id, {}).get(resource_id)

    def delete_snapshot(self, session_id: str, resource_id: str) -> bool:
        bucket = self.snapshots.get(session_id, {})
        if resource_id not in bucket:
            return False
        del bucket[resource_id]
        self.deleted.append((session_id, resource_id))
        return True


@pytest.mark.asyncio
async def test_browse_write_endpoints_run_through_write_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeBrowseClient()
    fake_snapshot_manager = _FakeSnapshotManager()
    lane_calls: list[dict[str, Any]] = []

    async def _run_write(*, session_id: Optional[str], operation: str, task):
        lane_calls.append({"session_id": session_id, "operation": operation})
        fake_client.in_lane = True
        try:
            return await task()
        finally:
            fake_client.in_lane = False

    monkeypatch.setattr(browse_api, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(
        browse_api, "get_snapshot_manager", lambda: fake_snapshot_manager
    )
    monkeypatch.setattr(
        browse_api,
        "_resolve_current_database_scope",
        lambda: {"database_fingerprint": "123456789abcdeadbeef"},
    )
    monkeypatch.setattr(browse_api.runtime_state.write_lanes, "run_write", _run_write)
    monkeypatch.setattr(browse_api, "ENABLE_WRITE_LANE_QUEUE", True)

    create_payload = await browse_api.create_node(
        browse_api.NodeCreate(
            parent_path="agent",
            title="new_note",
            content="create payload",
            priority=1,
            domain="core",
        )
    )
    update_payload = await browse_api.update_node(
        path="agent/new_note",
        domain="core",
        body=browse_api.NodeUpdate(content="update payload"),
    )
    delete_payload = await browse_api.delete_node(path="agent/new_note", domain="core")

    assert create_payload["success"] is True
    assert create_payload["created"] is True
    assert update_payload["success"] is True
    assert update_payload["updated"] is True
    assert delete_payload["success"] is True

    assert fake_client.create_called is True
    assert fake_client.update_called is True
    assert fake_client.delete_atomically_called is True
    assert fake_client.guard_calls_in_lane == [True, True]
    assert lane_calls == [
        {"session_id": "dashboard", "operation": "browse.create_node"},
        {"session_id": "dashboard", "operation": "browse.update_node"},
        {"session_id": "dashboard", "operation": "browse.delete_node"},
    ]
    assert [
        (
            item["session_id"],
            item["resource_id"],
            item["resource_type"],
            item["data"].get("operation_type"),
        )
        for item in fake_snapshot_manager.created
    ] == [
        ("dashboard-123456789abc", "core://agent/new_note", "path", "create"),
        ("dashboard-123456789abc", "memory:7", "memory", "modify_content"),
    ]
    assert fake_snapshot_manager.deleted == [
        ("dashboard-123456789abc", "memory:7"),
        ("dashboard-123456789abc", "core://agent/new_note"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update", "delete"])
async def test_browse_write_endpoints_surface_write_lane_timeout_as_503(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    fake_client = _FakeBrowseClient()

    async def _run_write(*, session_id: Optional[str], operation: str, task):
        _ = session_id, operation, task
        raise RuntimeError("write_lane_timeout")

    monkeypatch.setattr(browse_api, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(browse_api.runtime_state.write_lanes, "run_write", _run_write)
    monkeypatch.setattr(browse_api, "ENABLE_WRITE_LANE_QUEUE", True)

    with pytest.raises(HTTPException) as exc_info:
        if operation == "create":
            await browse_api.create_node(
                browse_api.NodeCreate(
                    parent_path="agent",
                    title="new_note",
                    content="create payload",
                    priority=1,
                    domain="core",
                )
            )
        elif operation == "update":
            await browse_api.update_node(
                path="agent/new_note",
                domain="core",
                body=browse_api.NodeUpdate(content="update payload"),
            )
        else:
            await browse_api.delete_node(path="agent/new_note", domain="core")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {"error": "write_lane_timeout"}


def test_browse_node_models_reject_oversized_content() -> None:
    oversized_content = "x" * (browse_api._BROWSE_CONTENT_MAX_CHARS + 1)

    with pytest.raises(ValidationError):
        browse_api.NodeCreate(content=oversized_content, domain="core")

    with pytest.raises(ValidationError):
        browse_api.NodeUpdate(content=oversized_content)


@pytest.mark.asyncio
async def test_browse_create_node_rejects_overlong_resulting_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NoWriteClient:
        async def write_guard(self, **_kwargs):
            raise AssertionError("write_guard should not run for invalid path length")

    monkeypatch.setattr(browse_api, "get_sqlite_client", lambda: _NoWriteClient())

    with pytest.raises(HTTPException) as exc_info:
        await browse_api.create_node(
            browse_api.NodeCreate(
                parent_path="a" * browse_api._BROWSE_PATH_MAX_CHARS,
                title="child",
                content="payload",
                domain="core",
            )
        )

    assert exc_info.value.status_code == 422
    assert "resulting path is too long" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_browse_update_node_uses_lane_fresh_head_for_write_guard_matching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeBrowseClientWithLaneHeadRefresh()
    fake_snapshot_manager = _FakeSnapshotManager()

    async def _run_write(*, session_id: Optional[str], operation: str, task):
        _ = session_id
        _ = operation
        fake_client.in_lane = True
        try:
            return await task()
        finally:
            fake_client.in_lane = False

    monkeypatch.setattr(browse_api, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(
        browse_api, "get_snapshot_manager", lambda: fake_snapshot_manager
    )
    monkeypatch.setattr(
        browse_api,
        "_resolve_current_database_scope",
        lambda: {"database_fingerprint": "123456789abcdeadbeef"},
    )
    monkeypatch.setattr(browse_api.runtime_state.write_lanes, "run_write", _run_write)
    monkeypatch.setattr(browse_api, "ENABLE_WRITE_LANE_QUEUE", True)

    update_payload = await browse_api.update_node(
        path="agent/new_note",
        domain="core",
        body=browse_api.NodeUpdate(content="update payload"),
    )

    assert update_payload["success"] is True
    assert update_payload["updated"] is True
    assert fake_client.update_called is True
    assert fake_client.guard_calls_in_lane == [True]
    assert [
        (
            item["resource_id"],
            item["resource_type"],
            item["data"].get("operation_type"),
        )
        for item in fake_snapshot_manager.created
    ] == [("memory:19", "memory", "modify_content")]


@pytest.mark.asyncio
async def test_browse_update_node_surfaces_version_conflict_as_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeBrowseClientWithUpdateConflict()
    fake_snapshot_manager = _FakeSnapshotManager()

    async def _run_write(*, session_id: Optional[str], operation: str, task):
        _ = session_id, operation
        fake_client.in_lane = True
        try:
            return await task()
        finally:
            fake_client.in_lane = False

    monkeypatch.setattr(browse_api, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(
        browse_api, "get_snapshot_manager", lambda: fake_snapshot_manager
    )
    monkeypatch.setattr(
        browse_api,
        "_resolve_current_database_scope",
        lambda: {"database_fingerprint": "123456789abcdeadbeef"},
    )
    monkeypatch.setattr(browse_api.runtime_state.write_lanes, "run_write", _run_write)
    monkeypatch.setattr(browse_api, "ENABLE_WRITE_LANE_QUEUE", True)

    with pytest.raises(HTTPException) as exc_info:
        await browse_api.update_node(
            path="agent/new_note",
            domain="core",
            body=browse_api.NodeUpdate(content="update payload"),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Memory version conflict"


@pytest.mark.asyncio
async def test_browse_metadata_update_creates_path_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeBrowseClient()
    fake_snapshot_manager = _FakeSnapshotManager()

    async def _run_write(*, session_id: Optional[str], operation: str, task):
        _ = session_id
        _ = operation
        fake_client.in_lane = True
        try:
            return await task()
        finally:
            fake_client.in_lane = False

    monkeypatch.setattr(browse_api, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(
        browse_api, "get_snapshot_manager", lambda: fake_snapshot_manager
    )
    monkeypatch.setattr(
        browse_api,
        "_resolve_current_database_scope",
        lambda: {"database_fingerprint": "123456789abcdeadbeef"},
    )
    monkeypatch.setattr(browse_api.runtime_state.write_lanes, "run_write", _run_write)
    monkeypatch.setattr(browse_api, "ENABLE_WRITE_LANE_QUEUE", True)

    update_payload = await browse_api.update_node(
        path="agent/new_note",
        domain="core",
        body=browse_api.NodeUpdate(priority=9),
    )

    assert update_payload["success"] is True
    assert [
        (
            item["resource_id"],
            item["resource_type"],
            item["data"].get("operation_type"),
        )
        for item in fake_snapshot_manager.created
    ] == [("core://agent/new_note", "path", "modify_meta")]


@pytest.mark.asyncio
async def test_browse_delete_existing_node_creates_delete_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeBrowseClient()
    fake_snapshot_manager = _FakeSnapshotManager()

    async def _run_write(*, session_id: Optional[str], operation: str, task):
        _ = session_id
        _ = operation
        fake_client.in_lane = True
        try:
            return await task()
        finally:
            fake_client.in_lane = False

    monkeypatch.setattr(browse_api, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(
        browse_api, "get_snapshot_manager", lambda: fake_snapshot_manager
    )
    monkeypatch.setattr(
        browse_api,
        "_resolve_current_database_scope",
        lambda: {"database_fingerprint": "123456789abcdeadbeef"},
    )
    monkeypatch.setattr(browse_api.runtime_state.write_lanes, "run_write", _run_write)
    monkeypatch.setattr(browse_api, "ENABLE_WRITE_LANE_QUEUE", True)

    delete_payload = await browse_api.delete_node(path="agent/new_note", domain="core")

    assert delete_payload["success"] is True
    assert [
        (
            item["resource_id"],
            item["resource_type"],
            item["data"].get("operation_type"),
        )
        for item in fake_snapshot_manager.created
    ] == [("core://agent/new_note", "path", "delete")]
