import builtins
import importlib.util
import re
from pathlib import Path
from typing import Optional

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api import _write_lane as write_lane_api
from api import review as review_api
from db.snapshot import SnapshotManager
from db.sqlite_client import SQLiteClient


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


def test_review_api_source_uses_english_only_strings_and_docstrings() -> None:
    source = (Path(__file__).resolve().parents[1] / "api" / "review.py").read_text(
        encoding="utf-8"
    )

    assert re.search(r"[\u4e00-\u9fff]", source) is None


@pytest.mark.asyncio
async def test_review_run_write_lane_surfaces_write_lane_timeout_as_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _raise_timeout(*, session_id: Optional[str], operation: str, task):
        _ = session_id, operation, task
        raise RuntimeError("write_lane_timeout")

    monkeypatch.setattr(write_lane_api.runtime_state.write_lanes, "run_write", _raise_timeout)
    monkeypatch.setattr(review_api, "_ENABLE_WRITE_LANE_QUEUE", True)

    with pytest.raises(HTTPException) as exc_info:
        await review_api._run_write_lane("unit_test", lambda: None)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {"error": "write_lane_timeout"}


def test_review_formats_permanently_deleted_details_in_english() -> None:
    assert review_api._format_permanently_deleted_detail(
        17,
        action="restore",
        uri="core://agent/note",
    ) == (
        "Old version (memory_id=17) was permanently deleted. "
        "Cannot restore 'core://agent/note'."
    )
    assert review_api._format_permanently_deleted_detail(
        23,
        action="roll back",
    ) == "Old version (memory_id=23) was permanently deleted. Cannot roll back."


@pytest.mark.asyncio
async def test_review_run_write_lane_preserves_review_operation_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, str | None] = {}

    async def _capture_run_write(*, session_id: Optional[str], operation: str, task):
        recorded["session_id"] = session_id
        recorded["operation"] = operation
        return await task()

    async def _task() -> str:
        return "ok"

    monkeypatch.setattr(write_lane_api.runtime_state.write_lanes, "run_write", _capture_run_write)
    monkeypatch.setattr(review_api, "_ENABLE_WRITE_LANE_QUEUE", True)

    result = await review_api._run_write_lane("unit_test", _task)

    assert result == "ok"
    assert recorded == {
        "session_id": "review.unit_test",
        "operation": "review.unit_test",
    }


def test_review_module_source_contains_only_english_docstrings_and_literals() -> None:
    source = Path(review_api.__file__).read_text(encoding="utf-8")

    assert not any("\u4e00" <= char <= "\u9fff" for char in source)


@pytest.mark.asyncio
async def test_diff_memory_content_uses_english_deleted_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _DeletedOldVersionClient:
        async def get_memory_version(self, memory_id: int):
            _ = memory_id
            return None

        async def get_memory_by_path(
            self,
            path: str,
            domain: str,
            reinforce_access: bool = False,
        ):
            _ = path, domain, reinforce_access
            return None

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: _DeletedOldVersionClient())

    payload = await review_api._diff_memory_content(
        {
            "data": {
                "memory_id": 123,
                "path": "agent/node",
                "domain": "core",
                "uri": "core://agent/node",
                "all_paths": [],
            }
        },
        "memory:123",
    )

    assert payload["snapshot_data"]["content"] == (
        "[Permanently deleted, old content unavailable]"
    )


@pytest.mark.asyncio
async def test_rollback_memory_content_returns_structured_deleted_version_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _DeletedVersionClient:
        async def get_memory_version(self, memory_id: int):
            _ = memory_id
            return None

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: _DeletedVersionClient())

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_memory_content(
            {
                "memory_id": 123,
                "path": "agent/node",
                "domain": "core",
                "uri": "core://agent/node",
                "all_paths": [],
            }
        )

    assert exc_info.value.status_code == 410
    assert exc_info.value.detail == {
        "error": "memory_permanently_deleted",
        "reason": "Old version (memory_id=123) was permanently deleted. Cannot roll back.",
        "memory_id": 123,
        "action": "roll back",
    }


@pytest.mark.asyncio
async def test_rollback_path_create_cascades_descendants_and_cleans_orphans(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-create-cascade.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    root = await client.create_memory(
        parent_path="",
        content="root content",
        priority=1,
        title="parent",
        domain="core",
    )
    child = await client.create_memory(
        parent_path="parent",
        content="child content",
        priority=1,
        title="child",
        domain="core",
    )
    grandchild = await client.create_memory(
        parent_path="parent/child",
        content="grandchild content",
        priority=1,
        title="grand",
        domain="core",
    )

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: client)

    payload = await review_api._rollback_path(
        {
            "operation_type": "create",
            "domain": "core",
            "path": "parent",
            "uri": "core://parent",
            "memory_id": root["id"],
        }
    )

    assert payload["deleted"] is True
    assert payload["descendants_deleted"] == 2
    assert payload["orphan_memories_deleted"] >= 2

    assert await client.get_memory_by_path("parent", "core") is None
    assert await client.get_memory_by_path("parent/child", "core") is None
    assert await client.get_memory_by_path("parent/child/grand", "core") is None

    assert await client.get_memory_by_id(root["id"]) is None
    assert await client.get_memory_by_id(child["id"]) is None
    assert await client.get_memory_by_id(grandchild["id"]) is None

    await client.close()


@pytest.mark.asyncio
async def test_rollback_path_create_uses_single_write_lane_for_tree_delete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-create-single-lane.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    root = await client.create_memory(
        parent_path="",
        content="root content",
        priority=1,
        title="parent",
        domain="core",
    )
    await client.create_memory(
        parent_path="parent",
        content="child content",
        priority=1,
        title="child",
        domain="core",
    )
    await client.create_memory(
        parent_path="parent/child",
        content="grandchild content",
        priority=1,
        title="grand",
        domain="core",
    )

    lane_calls: list[tuple[str, str | None]] = []

    async def _inline_run_write_lane(operation: str, task, *, session_id=None):
        lane_calls.append((operation, session_id))
        return await task()

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(review_api, "_run_write_lane", _inline_run_write_lane)

    payload = await review_api._rollback_path(
        {
            "operation_type": "create",
            "domain": "core",
            "path": "parent",
            "uri": "core://parent",
            "memory_id": root["id"],
        },
        lane_session_id="review-single-lane",
    )

    assert payload["deleted"] is True
    assert lane_calls == [("rollback.delete_create_tree", "review-single-lane")]
    await client.close()


@pytest.mark.asyncio
async def test_rollback_path_create_tree_deletes_descendants_added_before_write_lane_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-create-late-descendants.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    root = await client.create_memory(
        parent_path="",
        content="root content",
        priority=1,
        title="parent",
        domain="core",
    )

    async def _run_write_lane_stub(operation: str, task, *, session_id=None):
        _ = operation, session_id
        late_child = await client.create_memory(
            parent_path="parent",
            content="late child",
            priority=1,
            title="late-child",
            domain="core",
        )
        late_grandchild = await client.create_memory(
            parent_path="parent/late-child",
            content="late grandchild",
            priority=1,
            title="late-grandchild",
            domain="core",
        )
        payload = await task()
        payload["_late_ids"] = (
            late_child["id"],
            late_grandchild["id"],
        )
        return payload

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(review_api, "_run_write_lane", _run_write_lane_stub)

    payload = await review_api._rollback_path(
        {
            "operation_type": "create",
            "domain": "core",
            "path": "parent",
            "uri": "core://parent",
            "memory_id": root["id"],
        },
        lane_session_id="review.rollback:late-descendants",
    )

    late_child_id, late_grandchild_id = payload.pop("_late_ids")

    assert payload["deleted"] is True
    assert payload["descendants_deleted"] == 2
    assert payload["orphan_memories_deleted"] >= 2
    assert await client.get_memory_by_path("parent", "core", reinforce_access=False) is None
    assert (
        await client.get_memory_by_path(
            "parent/late-child", "core", reinforce_access=False
        )
        is None
    )
    assert (
        await client.get_memory_by_path(
            "parent/late-child/late-grandchild",
            "core",
            reinforce_access=False,
        )
        is None
    )
    assert await client.get_memory_by_id(root["id"]) is None
    assert await client.get_memory_by_id(late_child_id) is None
    assert await client.get_memory_by_id(late_grandchild_id) is None

    await client.close()


@pytest.mark.asyncio
async def test_rollback_path_create_tree_rechecks_current_target_inside_atomic_delete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-create-stale-target.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    original = await client.create_memory(
        parent_path="",
        content="original content",
        priority=1,
        title="parent",
        domain="core",
    )

    async def _run_write_lane_stub(operation: str, task, *, session_id=None):
        _ = operation, session_id
        updated = await client.update_memory(
            path="parent",
            domain="core",
            content="newer content",
        )
        try:
            return await task()
        finally:
            _run_write_lane_stub.updated_memory_id = updated["new_memory_id"]

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(review_api, "_run_write_lane", _run_write_lane_stub)

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_path(
            {
                "operation_type": "create",
                "domain": "core",
                "path": "parent",
                "uri": "core://parent",
                "memory_id": original["id"],
            },
            lane_session_id="review.rollback:stale-target",
        )

    current = await client.get_memory_by_path("parent", "core", reinforce_access=False)

    assert exc_info.value.status_code == 409
    assert "expected memory_id" in str(exc_info.value.detail)
    assert current is not None
    assert current["id"] == _run_write_lane_stub.updated_memory_id
    assert current["content"] == "newer content"

    await client.close()


@pytest.mark.asyncio
async def test_rollback_path_create_cascades_descendants_under_alias_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-create-alias-cascade.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    root = await client.create_memory(
        parent_path="",
        content="root content",
        priority=1,
        title="parent",
        domain="core",
    )
    await client.add_path(
        new_path="aliasparent",
        target_path="parent",
        new_domain="writer",
        target_domain="core",
    )
    alias_child = await client.create_memory(
        parent_path="aliasparent",
        content="alias child content",
        priority=1,
        title="child",
        domain="writer",
    )

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: client)

    payload = await review_api._rollback_path(
        {
            "operation_type": "create",
            "domain": "core",
            "path": "parent",
            "uri": "core://parent",
            "memory_id": root["id"],
        }
    )

    assert payload["deleted"] is True
    assert payload["descendants_deleted"] >= 1
    assert await client.get_memory_by_path("parent", "core", reinforce_access=False) is None
    assert await client.get_memory_by_path(
        "aliasparent", "writer", reinforce_access=False
    ) is None
    assert await client.get_memory_by_path(
        "aliasparent/child", "writer", reinforce_access=False
    ) is None
    assert await client.get_memory_by_id(alias_child["id"]) is None

    await client.close()


@pytest.mark.asyncio
async def test_rollback_path_delete_rejects_restore_when_parent_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-delete-missing-parent.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    await client.create_memory(
        parent_path="",
        content="root content",
        priority=1,
        title="parent",
        domain="core",
    )
    child = await client.create_memory(
        parent_path="parent",
        content="child content",
        priority=1,
        title="child",
        domain="core",
    )

    await client.remove_path("parent/child", "core")
    await client.remove_path("parent", "core")

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: client)

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_path(
            {
                "operation_type": "delete",
                "domain": "core",
                "path": "parent/child",
                "uri": "core://parent/child",
                "memory_id": child["id"],
                "priority": 1,
                "disclosure": None,
            }
        )

    assert exc_info.value.status_code == 409
    assert "Parent path 'core://parent' not found" in str(exc_info.value.detail)
    assert (
        await client.get_memory_by_path("parent/child", "core", reinforce_access=False)
        is None
    )
    await client.close()


@pytest.mark.asyncio
async def test_rollback_path_create_alias_returns_409_when_alias_still_exists_after_remove_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _AliasStillExistsClient:
        async def remove_path(self, path: str, domain: str) -> None:
            _ = path
            _ = domain
            raise ValueError("alias_remove_failed")

        async def get_memory_by_path(
            self,
            path: str,
            domain: str,
            reinforce_access: bool = False,
        ):
            _ = path
            _ = domain
            _ = reinforce_access
            return {"id": 42}

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: _AliasStillExistsClient())

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_path(
            {
                "operation_type": "create_alias",
                "domain": "core",
                "path": "parent-alias",
                "uri": "core://parent-alias",
            }
        )

    assert exc_info.value.status_code == 409
    assert "Cannot rollback alias 'core://parent-alias'" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_rollback_path_create_alias_rejects_when_alias_now_points_to_different_memory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-alias-rebind.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    source = await client.create_memory(
        parent_path="",
        content="source content",
        priority=1,
        title="source",
        domain="core",
    )
    target = await client.create_memory(
        parent_path="",
        content="target content",
        priority=1,
        title="target",
        domain="core",
    )
    await client.add_path(
        new_path="shared-alias",
        target_path="source",
        new_domain="core",
        target_domain="core",
    )
    await client.remove_path("shared-alias", "core")
    await client.add_path(
        new_path="shared-alias",
        target_path="target",
        new_domain="core",
        target_domain="core",
    )

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: client)

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_path(
            {
                "operation_type": "create_alias",
                "domain": "core",
                "path": "shared-alias",
                "uri": "core://shared-alias",
                "memory_id": source["id"],
            }
        )

    assert exc_info.value.status_code == 409
    assert "points to a different memory" in str(exc_info.value.detail)
    current = await client.get_memory_by_path("shared-alias", "core", reinforce_access=False)
    assert current is not None
    assert current["id"] == target["id"]
    await client.close()


class _StubSnapshotManager:
    def get_snapshot(self, _session_id: str, resource_id: str):
        return {
            "resource_id": resource_id,
            "resource_type": "path",
            "snapshot_time": "2026-02-19T00:00:00",
            "data": {
                "operation_type": "create",
                "domain": "core",
                "path": resource_id,
                "uri": f"core://{resource_id}",
            },
        }


class _PercentSnapshotManager:
    def get_snapshot(self, _session_id: str, resource_id: str):
        if resource_id != "core://foo%20bar":
            return None
        return {
            "resource_id": resource_id,
            "resource_type": "path",
            "snapshot_time": "2026-02-19T00:00:00Z",
            "data": {
                "operation_type": "create",
                "domain": "core",
                "path": "foo%20bar",
                "uri": resource_id,
            },
        }


@pytest.mark.asyncio
async def test_snapshot_detail_prefers_exact_percent_literal_resource_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        review_api,
        "get_snapshot_manager",
        lambda: _PercentSnapshotManager(),
    )

    detail = await review_api.get_snapshot_detail("s1", "core://foo%20bar")

    assert detail.resource_id == "core://foo%20bar"


def test_parse_snapshot_time_normalizes_naive_and_aware_values() -> None:
    naive = review_api._parse_snapshot_time("2026-03-20T10:00:00")
    aware = review_api._parse_snapshot_time("2026-03-20T18:00:00+08:00")

    assert naive == aware
    assert naive.tzinfo is not None


def test_rollback_endpoint_returns_5xx_when_internal_error_occurs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(_data: dict, **_kwargs) -> dict:
        raise RuntimeError("boom-secret-detail")

    monkeypatch.setattr(review_api, "get_snapshot_manager", lambda: _StubSnapshotManager())
    monkeypatch.setattr(review_api, "_rollback_path", _boom)
    monkeypatch.setenv("MCP_API_KEY", "review-test-secret")
    monkeypatch.delenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", raising=False)

    app = FastAPI()
    app.include_router(review_api.router)

    with TestClient(app) as client:
        response = client.post(
            "/review/sessions/s1/rollback/parent",
            json={},
            headers={"X-MCP-API-Key": "review-test-secret"},
        )

    assert response.status_code == 500
    assert response.json().get("detail") == {
        "error": "rollback_failed",
        "reason": "internal_error",
        "operation": "rollback_resource",
    }


def test_list_deprecated_endpoint_hides_internal_error_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingClient:
        async def get_deprecated_memories(self):
            raise RuntimeError("deprecated-secret-detail")

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: _FailingClient())
    monkeypatch.setenv("MCP_API_KEY", "review-test-secret")
    monkeypatch.delenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", raising=False)

    app = FastAPI()
    app.include_router(review_api.router)

    with TestClient(app) as client:
        response = client.get(
            "/review/deprecated",
            headers={"X-MCP-API-Key": "review-test-secret"},
        )

    assert response.status_code == 500
    assert response.json().get("detail") == {
        "error": "list_deprecated_failed",
        "reason": "internal_error",
        "operation": "list_deprecated_memories",
    }


def test_compare_text_hides_internal_error_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_text_a: str, _text_b: str):
        raise RuntimeError("diff-secret-detail")

    monkeypatch.setattr(review_api, "get_text_diff", _boom)
    monkeypatch.setenv("MCP_API_KEY", "review-test-secret")
    monkeypatch.delenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", raising=False)

    app = FastAPI()
    app.include_router(review_api.router)

    with TestClient(app) as client:
        response = client.post(
            "/review/diff",
            json={"text_a": "old", "text_b": "new"},
            headers={"X-MCP-API-Key": "review-test-secret"},
        )

    assert response.status_code == 500
    assert response.json().get("detail") == {
        "error": "compare_text_failed",
        "reason": "internal_error",
        "operation": "compare_text",
    }


def test_utils_module_imports_without_diff_match_patch() -> None:
    module_path = Path(review_api.__file__).with_name("utils.py")
    original_import = builtins.__import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "diff_match_patch":
            raise ModuleNotFoundError("No module named 'diff_match_patch'")
        return original_import(name, globals, locals, fromlist, level)

    spec = importlib.util.spec_from_file_location("review_utils_without_dmp", module_path)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    builtins.__import__ = _guarded_import
    try:
        spec.loader.exec_module(module)
    finally:
        builtins.__import__ = original_import

    diff_html, diff_unified, summary = module.get_text_diff("old line\n", "new line\n")
    assert "<table class=\"diff\"" in diff_html
    assert "--- old_version" in diff_unified
    assert "+++ new_version" in diff_unified
    assert "change" in summary.lower()


def test_review_module_keeps_deleted_messages_in_english() -> None:
    review_text = Path(review_api.__file__).read_text(encoding="utf-8")

    assert "[Permanently deleted, old content unavailable]" in review_text
    assert "[已被永久删除，无法显示旧内容]" not in review_text
    assert "旧版本" not in review_text


@pytest.mark.asyncio
async def test_rollback_memory_content_reports_structured_deleted_version_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MissingVersionClient:
        async def get_memory_version(self, memory_id: int):
            _ = memory_id
            return None

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: _MissingVersionClient())

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_memory_content(
            {
                "memory_id": 17,
                "path": "legacy",
                "domain": "core",
                "uri": "core://legacy",
            }
        )

    assert exc_info.value.status_code == 410
    assert exc_info.value.detail == {
        "error": "memory_permanently_deleted",
        "reason": "Old version (memory_id=17) was permanently deleted. Cannot roll back.",
        "memory_id": 17,
        "action": "roll back",
    }


@pytest.mark.asyncio
async def test_get_surviving_paths_stops_after_bounded_chain_traversal() -> None:
    call_order: list[int] = []

    class _LongChainClient:
        async def get_memory_version(self, memory_id: int):
            call_order.append(int(memory_id))
            current = int(memory_id)
            if current <= (review_api._VERSION_CHAIN_MAX_HOPS + 5):
                return {
                    "id": current,
                    "migrated_to": current + 1,
                    "paths": [f"core://node-{current}"],
                }
            return {"id": current, "migrated_to": None, "paths": [f"core://node-{current}"]}

    paths = await review_api._get_surviving_paths(_LongChainClient(), 1)

    assert paths == ["core://node-1"]
    assert len(call_order) == review_api._VERSION_CHAIN_MAX_HOPS + 1


def test_diff_endpoint_rejects_invalid_session_id_with_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_API_KEY", "review-test-secret")
    monkeypatch.delenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", raising=False)

    app = FastAPI()
    app.include_router(review_api.router)

    with TestClient(app) as client:
        response = client.get(
            "/review/sessions/abc%5Cdef/diff/core%3A%2F%2Fmemory-palace",
            headers={"X-MCP-API-Key": "review-test-secret"},
        )

    assert response.status_code == 400
    assert "Invalid session_id" in str(response.json().get("detail"))


def test_snapshot_manager_rejects_traversal_session_id(tmp_path: Path) -> None:
    manager = SnapshotManager(str(tmp_path / "snapshots"))
    with pytest.raises(ValueError):
        manager.clear_session("..")


def test_snapshot_manager_recovers_from_corrupted_manifest_using_resource_files(
    tmp_path: Path,
) -> None:
    manager = SnapshotManager(str(tmp_path / "snapshots"))
    created = manager.create_snapshot(
        "session-1",
        "memory:1",
        "memory",
        {
            "uri": "core://agent/example",
            "content": "before update",
            "operation_type": "modify",
        },
    )

    assert created is True

    manifest_path = tmp_path / "snapshots" / "session-1" / "manifest.json"
    manifest_path.write_text("{not valid json", encoding="utf-8")

    snapshot = manager.get_snapshot("session-1", "memory:1")
    listed = manager.list_snapshots("session-1")

    assert snapshot is not None
    assert snapshot["resource_id"] == "memory:1"
    assert listed == [
        {
            "resource_id": "memory:1",
            "resource_type": "memory",
            "snapshot_time": snapshot["snapshot_time"],
            "operation_type": "modify",
            "uri": "core://agent/example",
        }
    ]


@pytest.mark.asyncio
async def test_rollback_resource_returns_409_when_newer_memory_snapshot_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ConflictSnapshotManager:
        def get_snapshot(self, session_id: str, resource_id: str):
            _ = resource_id
            assert session_id == "session-1"
            return {
                "resource_id": "memory:10",
                "resource_type": "memory",
                "snapshot_time": "2026-03-20T10:00:00",
                "data": {
                    "operation_type": "modify_content",
                    "memory_id": 10,
                    "path": "agent/node",
                    "domain": "core",
                    "uri": "core://agent/node",
                    "all_paths": [],
                },
            }

        def list_sessions(self):
            return [
                {"session_id": "session-2", "created_at": "2026-03-20T10:00:01"},
                {"session_id": "session-1", "created_at": "2026-03-20T10:00:00"},
            ]

        def list_snapshots(self, session_id: str):
            if session_id == "session-2":
                return [
                    {
                        "resource_id": "memory:11",
                        "resource_type": "memory",
                        "snapshot_time": "2026-03-20T10:00:01",
                        "operation_type": "modify_content",
                        "uri": "core://agent/node",
                    }
                ]
            return [
                {
                    "resource_id": "memory:10",
                    "resource_type": "memory",
                    "snapshot_time": "2026-03-20T10:00:00",
                    "operation_type": "modify_content",
                    "uri": "core://agent/node",
                }
            ]

    class _NoRollbackClient:
        async def get_memory_version(self, memory_id: int):
            return {"id": memory_id, "migrated_to": None}

        async def get_memory_by_path(
            self,
            path: str,
            domain: str,
            reinforce_access: bool = False,
        ):
            _ = path, domain, reinforce_access
            return {"id": 10, "content": "current"}

        async def rollback_to_memory(self, path: str, memory_id: int, domain: str):
            _ = path, memory_id, domain
            raise AssertionError("rollback_to_memory should not run on conflict")

    monkeypatch.setattr(
        review_api, "get_snapshot_manager", lambda: _ConflictSnapshotManager()
    )
    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: _NoRollbackClient())

    with pytest.raises(HTTPException) as exc_info:
        await review_api.rollback_resource(
            "session-1",
            "memory:10",
            review_api.RollbackRequest(),
        )

    assert exc_info.value.status_code == 409
    assert "newer review snapshot exists" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_rollback_resource_rechecks_newer_snapshot_inside_write_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ConflictSnapshotManager:
        def __init__(self) -> None:
            self.inject_conflict = False

        def get_snapshot(self, session_id: str, resource_id: str):
            _ = resource_id
            assert session_id == "session-1"
            return {
                "resource_id": "memory:10",
                "resource_type": "memory",
                "snapshot_time": "2026-03-20T10:00:00",
                "data": {
                    "operation_type": "modify_content",
                    "memory_id": 123,
                    "path": "agent/node",
                    "domain": "core",
                    "uri": "core://agent/node",
                    "all_paths": [],
                },
            }

        def list_sessions(self):
            return [
                {"session_id": "session-2", "created_at": "2026-03-20T10:00:01"},
                {"session_id": "session-1", "created_at": "2026-03-20T10:00:00"},
            ]

        def list_snapshots(self, session_id: str):
            if session_id == "session-2" and self.inject_conflict:
                return [
                    {
                        "resource_id": "memory:11",
                        "resource_type": "memory",
                        "snapshot_time": "2026-03-20T10:00:01",
                        "uri": "core://agent/node",
                    }
                ]
            return []

    class _NoRollbackClient:
        async def get_memory_version(self, memory_id: int):
            if int(memory_id) == 123:
                return {"id": 123, "migrated_to": 999}
            if int(memory_id) == 999:
                return {"id": 999, "migrated_to": None}
            return None

        async def get_memory_by_path(
            self,
            path: str,
            domain: str,
            reinforce_access: bool = False,
        ):
            _ = path, domain, reinforce_access
            return {"id": 999, "content": "current"}

        async def rollback_to_memory(
            self,
            path: str,
            memory_id: int,
            domain: str,
            *,
            expected_current_memory_id: int | None = None,
        ):
            _ = path, memory_id, domain, expected_current_memory_id
            raise AssertionError("rollback_to_memory should not run after late conflict")

    manager = _ConflictSnapshotManager()

    async def _run_write_lane_stub(operation: str, task, *, session_id=None):
        _ = operation, session_id
        manager.inject_conflict = True
        return await task()

    monkeypatch.setattr(review_api, "get_snapshot_manager", lambda: manager)
    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: _NoRollbackClient())
    monkeypatch.setattr(review_api, "_run_write_lane", _run_write_lane_stub)

    with pytest.raises(HTTPException) as exc_info:
        await review_api.rollback_resource(
            "session-1",
            "memory:10",
            review_api.RollbackRequest(),
        )

    assert exc_info.value.status_code == 409
    assert "newer review snapshot exists" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_rollback_path_create_alias_routes_writes_through_write_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane_calls = []
    before_delete_payloads = []

    class _AliasClient:
        async def get_memory_by_path(
            self,
            path: str,
            domain: str,
            reinforce_access: bool = False,
        ):
            _ = path, domain, reinforce_access
            return None

        async def delete_path_atomically(
            self,
            path: str,
            domain: str,
            *,
            before_delete=None,
        ):
            if before_delete is not None:
                payload = {"id": 42, "path": path, "domain": domain}
                before_delete_payloads.append(payload)
                await before_delete(dict(payload))
            return {"removed_uri": f"{domain}://{path}"}

    async def _run_write_lane_stub(operation: str, task, *, session_id=None):
        lane_calls.append({"operation": operation, "session_id": session_id})
        return await task()

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: _AliasClient())
    monkeypatch.setattr(review_api, "_run_write_lane", _run_write_lane_stub)

    payload = await review_api._rollback_path(
        {
            "operation_type": "create_alias",
            "domain": "core",
            "path": "alias-node",
            "uri": "core://alias-node",
        },
        lane_session_id="review.rollback:lane-path",
    )

    assert payload == {"deleted": True, "alias_removed": True}
    assert lane_calls == [
        {
            "operation": "rollback.remove_alias",
            "session_id": "review.rollback:lane-path",
        }
    ]
    assert before_delete_payloads == [{"id": 42, "path": "alias-node", "domain": "core"}]


@pytest.mark.asyncio
async def test_rollback_path_create_alias_rechecks_current_target_inside_atomic_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _AliasRaceClient:
        async def get_memory_by_path(
            self,
            path: str,
            domain: str,
            reinforce_access: bool = False,
        ):
            _ = path, domain, reinforce_access
            return {"id": 42}

        async def delete_path_atomically(
            self,
            path: str,
            domain: str,
            *,
            before_delete=None,
        ):
            _ = path, domain
            await before_delete({"id": 99, "path": path, "domain": domain})
            raise AssertionError("delete_path_atomically should stop before delete")

    async def _run_write_lane_stub(operation: str, task, *, session_id=None):
        _ = operation, session_id
        return await task()

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: _AliasRaceClient())
    monkeypatch.setattr(review_api, "_run_write_lane", _run_write_lane_stub)

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_path(
            {
                "operation_type": "create_alias",
                "domain": "core",
                "path": "alias-node",
                "uri": "core://alias-node",
                "memory_id": 42,
            }
        )

    assert exc_info.value.status_code == 409
    assert "points to a different memory" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_rollback_memory_content_routes_writes_through_write_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane_calls = []

    class _MemoryContentClient:
        async def get_memory_version(self, memory_id: int):
            memory_id = int(memory_id)
            if memory_id == 123:
                return {"id": 123, "migrated_to": 999}
            if memory_id == 999:
                return {"id": 999, "migrated_to": None}
            return None

        async def get_memory_by_path(
            self,
            path: str,
            domain: str,
            reinforce_access: bool = False,
        ):
            _ = path, domain, reinforce_access
            return {"id": 999, "content": "current"}

        async def rollback_to_memory(
            self,
            path: str,
            memory_id: int,
            domain: str,
            *,
            expected_current_memory_id: int | None = None,
        ):
            _ = path, domain
            assert expected_current_memory_id == 999
            return {"restored_memory_id": int(memory_id)}

    async def _run_write_lane_stub(operation: str, task, *, session_id=None):
        lane_calls.append({"operation": operation, "session_id": session_id})
        return await task()

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: _MemoryContentClient())
    monkeypatch.setattr(review_api, "_run_write_lane", _run_write_lane_stub)

    payload = await review_api._rollback_memory_content(
        {
            "memory_id": 123,
            "path": "agent/node",
            "domain": "core",
            "uri": "core://agent/node",
            "all_paths": [],
        },
        lane_session_id="review.rollback:lane-memory",
    )

    assert payload == {"new_version": 123}
    assert lane_calls == [
        {
            "operation": "rollback.rollback_to_memory",
            "session_id": "review.rollback:lane-memory",
        }
    ]


@pytest.mark.asyncio
async def test_rollback_path_create_tree_is_atomic_when_root_delete_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-tree-atomic.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    root = await client.create_memory(
        parent_path="",
        content="root content",
        priority=1,
        title="parent",
        domain="core",
    )
    child = await client.create_memory(
        parent_path="parent",
        content="child content",
        priority=1,
        title="child",
        domain="core",
    )
    grandchild = await client.create_memory(
        parent_path="parent/child",
        content="grandchild content",
        priority=1,
        title="grand",
        domain="core",
    )

    original_delete = getattr(client, "_permanently_delete_memory_in_session", None)

    async def _fail_on_root(session, memory_id: int, *, require_orphan: bool = False, expected_state_hash: str | None = None):
        if int(memory_id) == root["id"]:
            raise RuntimeError("root delete failed")
        if original_delete is not None:
            return await original_delete(
                session,
                memory_id,
                require_orphan=require_orphan,
                expected_state_hash=expected_state_hash,
            )
        return await client.permanently_delete_memory(
            memory_id,
            require_orphan=require_orphan,
            expected_state_hash=expected_state_hash,
        )

    monkeypatch.setattr(
        client,
        "_permanently_delete_memory_in_session",
        _fail_on_root,
        raising=False,
    )
    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: client)

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_path(
            {
                "operation_type": "create",
                "domain": "core",
                "path": "parent",
                "uri": "core://parent",
                "memory_id": root["id"],
            }
        )

    assert exc_info.value.status_code == 409
    assert await client.get_memory_by_path("parent", "core", reinforce_access=False) is not None
    assert await client.get_memory_by_path("parent/child", "core", reinforce_access=False) is not None
    assert await client.get_memory_by_path("parent/child/grand", "core", reinforce_access=False) is not None
    assert await client.get_memory_by_id(root["id"]) is not None
    assert await client.get_memory_by_id(child["id"]) is not None
    assert await client.get_memory_by_id(grandchild["id"]) is not None

    await client.close()


@pytest.mark.asyncio
async def test_rollback_legacy_modify_routes_combined_restore_through_single_write_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane_calls = []

    class _LegacyModifyClient:
        async def get_memory_version(self, memory_id: int):
            memory_id = int(memory_id)
            if memory_id == 123:
                return {"id": 123, "migrated_to": 999}
            if memory_id == 999:
                return {"id": 999, "migrated_to": None}
            return None

        async def get_memory_by_path(
            self,
            path: str,
            domain: str,
            reinforce_access: bool = False,
        ):
            _ = path, domain, reinforce_access
            return {"id": 999, "priority": 5, "disclosure": "new"}

        async def rollback_to_memory(
            self,
            path: str,
            memory_id: int,
            domain: str,
            *,
            restore_path_metadata: bool = False,
            restore_priority: int | None = None,
            restore_disclosure: str | None = None,
        ):
            _ = path, domain
            assert restore_path_metadata is True
            assert restore_priority == 1
            assert restore_disclosure == "old"
            return {"restored_memory_id": int(memory_id)}

        async def update_memory(self, **_: object):
            raise AssertionError("update_memory should not run for combined legacy rollback")

    async def _run_write_lane_stub(operation: str, task, *, session_id=None):
        lane_calls.append({"operation": operation, "session_id": session_id})
        return await task()

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: _LegacyModifyClient())
    monkeypatch.setattr(review_api, "_run_write_lane", _run_write_lane_stub)

    payload = await review_api._rollback_legacy_modify(
        {
            "memory_id": 123,
            "path": "agent/node",
            "domain": "core",
            "uri": "core://agent/node",
            "priority": 1,
            "disclosure": "old",
        },
        lane_session_id="review.rollback:legacy-combined",
    )

    assert payload == {"new_version": 123}
    assert lane_calls == [
        {
            "operation": "rollback.restore_legacy_modify",
            "session_id": "review.rollback:legacy-combined",
        }
    ]


@pytest.mark.asyncio
async def test_rollback_legacy_modify_returns_409_when_combined_restore_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LegacyConflictClient:
        async def get_memory_version(self, memory_id: int):
            memory_id = int(memory_id)
            if memory_id == 123:
                return {"id": 123, "migrated_to": 999}
            if memory_id == 999:
                return {"id": 999, "migrated_to": None}
            return None

        async def get_memory_by_path(
            self,
            path: str,
            domain: str,
            reinforce_access: bool = False,
        ):
            _ = path, domain, reinforce_access
            return {"id": 999, "priority": 5, "disclosure": "new"}

        async def rollback_to_memory(
            self,
            path: str,
            memory_id: int,
            domain: str,
            *,
            expected_current_memory_id: int | None = None,
            restore_path_metadata: bool = False,
            restore_priority: int | None = None,
            restore_disclosure: str | None = None,
        ):
            _ = path, memory_id, domain
            assert expected_current_memory_id == 999
            assert restore_path_metadata is True
            assert restore_priority == 1
            assert restore_disclosure == "old"
            raise ValueError("expected_current_memory_id mismatch")

    async def _run_write_lane_stub(operation: str, task, *, session_id=None):
        _ = operation, session_id
        return await task()

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: _LegacyConflictClient())
    monkeypatch.setattr(review_api, "_run_write_lane", _run_write_lane_stub)

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_legacy_modify(
            {
                "memory_id": 123,
                "path": "agent/node",
                "domain": "core",
                "uri": "core://agent/node",
                "priority": 1,
                "disclosure": "old",
            },
            lane_session_id="review.rollback:legacy-combined-conflict",
        )

    assert exc_info.value.status_code == 409
    assert "expected_current_memory_id mismatch" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_rollback_legacy_modify_returns_409_when_version_only_restore_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LegacyVersionOnlyConflictClient:
        async def get_memory_version(self, memory_id: int):
            memory_id = int(memory_id)
            if memory_id == 123:
                return {"id": 123, "migrated_to": 999}
            if memory_id == 999:
                return {"id": 999, "migrated_to": None}
            return None

        async def get_memory_by_path(
            self,
            path: str,
            domain: str,
            reinforce_access: bool = False,
        ):
            _ = path, domain, reinforce_access
            return {"id": 999, "priority": 1, "disclosure": "old"}

        async def rollback_to_memory(
            self,
            path: str,
            memory_id: int,
            domain: str,
            *,
            expected_current_memory_id: int | None = None,
        ):
            _ = path, memory_id, domain
            assert expected_current_memory_id == 999
            raise ValueError("current memory changed")

    async def _run_write_lane_stub(operation: str, task, *, session_id=None):
        _ = operation, session_id
        return await task()

    monkeypatch.setattr(
        review_api, "get_sqlite_client", lambda: _LegacyVersionOnlyConflictClient()
    )
    monkeypatch.setattr(review_api, "_run_write_lane", _run_write_lane_stub)

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_legacy_modify(
            {
                "memory_id": 123,
                "path": "agent/node",
                "domain": "core",
                "uri": "core://agent/node",
                "priority": 1,
                "disclosure": "old",
            },
            lane_session_id="review.rollback:legacy-version-conflict",
        )

    assert exc_info.value.status_code == 409
    assert "current memory changed" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_rollback_legacy_modify_restores_content_and_metadata_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-legacy-modify-success.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    created = await client.create_memory(
        parent_path="",
        content="original content",
        priority=1,
        title="node",
        domain="core",
    )
    await client.update_memory(
        path="node",
        domain="core",
        content="current content",
        priority=5,
        disclosure="current disclosure",
    )

    lane_calls = []

    async def _run_write_lane_stub(operation: str, task, *, session_id=None):
        lane_calls.append({"operation": operation, "session_id": session_id})
        return await task()

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(review_api, "_run_write_lane", _run_write_lane_stub)

    payload = await review_api._rollback_legacy_modify(
        {
            "memory_id": created["id"],
            "path": "node",
            "domain": "core",
            "uri": "core://node",
            "priority": 1,
            "disclosure": None,
        },
        lane_session_id="review.rollback:legacy-success",
    )

    current = await client.get_memory_by_path("node", "core", reinforce_access=False)

    assert payload == {"new_version": created["id"]}
    assert current is not None
    assert current["id"] == created["id"]
    assert current["content"] == "original content"
    assert current["priority"] == 1
    assert current["disclosure"] is None
    assert lane_calls == [
        {
            "operation": "rollback.restore_legacy_modify",
            "session_id": "review.rollback:legacy-success",
        }
    ]

    await client.close()


@pytest.mark.asyncio
async def test_rollback_legacy_modify_failure_does_not_leave_partial_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-legacy-modify-failure.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    created = await client.create_memory(
        parent_path="",
        content="original content",
        priority=1,
        title="node",
        domain="core",
    )
    updated = await client.update_memory(
        path="node",
        domain="core",
        content="current content",
        priority=5,
        disclosure="current disclosure",
    )

    async def _boom_reindex(self, session, memory_id: int):
        _ = self, session, memory_id
        raise RuntimeError("reindex failed")

    async def _run_write_lane_stub(_operation: str, task, *, session_id=None):
        _ = session_id
        return await task()

    monkeypatch.setattr(SQLiteClient, "_reindex_memory", _boom_reindex)
    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(review_api, "_run_write_lane", _run_write_lane_stub)

    with pytest.raises(RuntimeError, match="reindex failed"):
        await review_api._rollback_legacy_modify(
            {
                "memory_id": created["id"],
                "path": "node",
                "domain": "core",
                "uri": "core://node",
                "priority": 1,
                "disclosure": None,
            },
            lane_session_id="review.rollback:legacy-failure",
        )

    current = await client.get_memory_by_path("node", "core", reinforce_access=False)

    assert current is not None
    assert current["id"] == updated["new_memory_id"]
    assert current["content"] == "current content"
    assert current["priority"] == 5
    assert current["disclosure"] == "current disclosure"

    await client.close()


@pytest.mark.asyncio
async def test_rollback_path_modify_meta_can_clear_disclosure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-modify-meta-clear-disclosure.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    await client.create_memory(
        parent_path="",
        content="content",
        priority=5,
        title="node",
        domain="core",
    )
    await client.update_memory(
        path="node",
        domain="core",
        priority=8,
        disclosure="current disclosure",
    )

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: client)

    payload = await review_api._rollback_path(
        {
            "operation_type": "modify_meta",
            "domain": "core",
            "path": "node",
            "uri": "core://node",
            "priority": 5,
            "disclosure": None,
        }
    )

    current = await client.get_memory_by_path("node", "core", reinforce_access=False)

    assert payload == {"metadata_restored": True}
    assert current is not None
    assert current["priority"] == 5
    assert current["disclosure"] is None

    await client.close()


@pytest.mark.asyncio
async def test_rollback_path_modify_meta_returns_409_when_metadata_changes_inside_write_lane(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-modify-meta-conflict.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    await client.create_memory(
        parent_path="",
        content="content",
        priority=5,
        title="node",
        domain="core",
        disclosure="old disclosure",
    )
    await client.restore_path_metadata(
        path="node",
        domain="core",
        priority=8,
        disclosure="current disclosure",
    )

    async def _run_write_lane_stub(operation: str, task, *, session_id=None):
        _ = operation, session_id
        await client.restore_path_metadata(
            path="node",
            domain="core",
            priority=9,
            disclosure="newer disclosure",
        )
        return await task()

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(review_api, "_run_write_lane", _run_write_lane_stub)

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_path(
            {
                "operation_type": "modify_meta",
                "domain": "core",
                "path": "node",
                "uri": "core://node",
                "priority": 5,
                "disclosure": "old disclosure",
            }
        )

    current = await client.get_memory_by_path("node", "core", reinforce_access=False)

    assert exc_info.value.status_code == 409
    assert "Cannot rollback 'core://node':" in str(exc_info.value.detail)
    assert current is not None
    assert current["priority"] == 9
    assert current["disclosure"] == "newer disclosure"

    await client.close()


@pytest.mark.asyncio
async def test_rollback_path_modify_meta_returns_404_when_path_disappears_inside_write_lane(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-modify-meta-missing.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    created = await client.create_memory(
        parent_path="",
        content="content",
        priority=5,
        title="node",
        domain="core",
        disclosure="old disclosure",
    )
    await client.restore_path_metadata(
        path="node",
        domain="core",
        priority=8,
        disclosure="current disclosure",
    )

    async def _run_write_lane_stub(operation: str, task, *, session_id=None):
        _ = operation, session_id
        await client.remove_path("node", "core")
        return await task()

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(review_api, "_run_write_lane", _run_write_lane_stub)

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_path(
            {
                "operation_type": "modify_meta",
                "domain": "core",
                "path": "node",
                "uri": "core://node",
                "memory_id": created["id"],
                "priority": 5,
                "disclosure": "old disclosure",
            }
        )

    assert exc_info.value.status_code == 404
    assert "Cannot rollback 'core://node':" in str(exc_info.value.detail)

    await client.close()


@pytest.mark.asyncio
async def test_rollback_path_create_returns_409_when_snapshot_memory_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-create-mismatch.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    original = await client.create_memory(
        parent_path="",
        content="original content",
        priority=1,
        title="parent",
        domain="core",
    )
    await client.remove_path("parent", "core")
    replacement = await client.create_memory(
        parent_path="",
        content="replacement content",
        priority=1,
        title="parent",
        domain="core",
    )

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: client)

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_path(
            {
                "operation_type": "create",
                "domain": "core",
                "path": "parent",
                "uri": "core://parent",
                "memory_id": original["id"],
            }
        )

    assert exc_info.value.status_code == 409
    assert "does not match current memory_id" in str(exc_info.value.detail)
    current = await client.get_memory_by_path("parent", "core", reinforce_access=False)
    assert current is not None
    assert current["id"] == replacement["id"]
    await client.close()


@pytest.mark.asyncio
async def test_rollback_memory_content_returns_409_for_cross_chain_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CrossChainClient:
        async def get_memory_version(self, memory_id: int):
            versions = {
                10: {"id": 10, "migrated_to": 11},
                11: {"id": 11, "migrated_to": None},
                99: {"id": 99, "migrated_to": None},
            }
            return versions.get(int(memory_id))

        async def get_memory_by_path(
            self,
            path: str,
            domain: str,
            reinforce_access: bool = False,
        ):
            _ = path, domain, reinforce_access
            return {"id": 99, "content": "current"}

        async def rollback_to_memory(self, path: str, memory_id: int, domain: str):
            _ = path, memory_id, domain
            raise AssertionError("rollback_to_memory should not run for cross-chain rollback")

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: _CrossChainClient())

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_memory_content(
            {
                "memory_id": 10,
                "path": "agent/node",
                "domain": "core",
                "uri": "core://agent/node",
                "all_paths": [],
            }
        )

    assert exc_info.value.status_code == 409
    assert "not in the same version chain" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_rollback_legacy_modify_returns_409_for_cross_chain_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CrossChainLegacyClient:
        async def get_memory_version(self, memory_id: int):
            versions = {
                20: {"id": 20, "migrated_to": 21},
                21: {"id": 21, "migrated_to": None},
                88: {"id": 88, "migrated_to": None},
            }
            return versions.get(int(memory_id))

        async def get_memory_by_path(
            self,
            path: str,
            domain: str,
            reinforce_access: bool = False,
        ):
            _ = path, domain, reinforce_access
            return {"id": 88, "priority": 2, "disclosure": "internal"}

        async def rollback_to_memory(self, path: str, memory_id: int, domain: str):
            _ = path, memory_id, domain
            raise AssertionError("rollback_to_memory should not run for cross-chain rollback")

        async def update_memory(
            self,
            path: str,
            domain: str,
            priority: int | None = None,
            disclosure: str | None = None,
        ):
            _ = path, domain, priority, disclosure
            raise AssertionError("update_memory should not run for cross-chain rollback")

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: _CrossChainLegacyClient())

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_legacy_modify(
            {
                "memory_id": 20,
                "path": "agent/node",
                "domain": "core",
                "uri": "core://agent/node",
                "priority": 1,
                "disclosure": "public",
            }
        )

    assert exc_info.value.status_code == 409
    assert "not in the same version chain" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_rollback_legacy_modify_meta_only_returns_409_when_metadata_changes_inside_write_lane(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-legacy-meta-conflict.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    await client.create_memory(
        parent_path="",
        content="content",
        priority=5,
        title="node",
        domain="core",
        disclosure="old disclosure",
    )
    current = await client.get_memory_by_path("node", "core", reinforce_access=False)
    assert current is not None
    await client.restore_path_metadata(
        path="node",
        domain="core",
        priority=8,
        disclosure="current disclosure",
    )

    async def _run_write_lane_stub(operation: str, task, *, session_id=None):
        _ = operation, session_id
        await client.restore_path_metadata(
            path="node",
            domain="core",
            priority=9,
            disclosure="newer disclosure",
        )
        return await task()

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(review_api, "_run_write_lane", _run_write_lane_stub)

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_legacy_modify(
            {
                "memory_id": current["id"],
                "path": "node",
                "domain": "core",
                "uri": "core://node",
                "priority": 5,
                "disclosure": "old disclosure",
            },
            lane_session_id="review.rollback:legacy-meta-conflict",
        )

    latest = await client.get_memory_by_path("node", "core", reinforce_access=False)

    assert exc_info.value.status_code == 409
    assert "Cannot rollback 'core://node':" in str(exc_info.value.detail)
    assert latest is not None
    assert latest["priority"] == 9
    assert latest["disclosure"] == "newer disclosure"

    await client.close()


@pytest.mark.asyncio
async def test_rollback_legacy_modify_meta_only_returns_404_when_path_disappears_inside_write_lane(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-legacy-meta-missing.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    created = await client.create_memory(
        parent_path="",
        content="content",
        priority=5,
        title="node",
        domain="core",
        disclosure="old disclosure",
    )
    await client.restore_path_metadata(
        path="node",
        domain="core",
        priority=8,
        disclosure="current disclosure",
    )

    async def _run_write_lane_stub(operation: str, task, *, session_id=None):
        _ = operation, session_id
        await client.remove_path("node", "core")
        return await task()

    monkeypatch.setattr(review_api, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(review_api, "_run_write_lane", _run_write_lane_stub)

    with pytest.raises(HTTPException) as exc_info:
        await review_api._rollback_legacy_modify(
            {
                "memory_id": created["id"],
                "path": "node",
                "domain": "core",
                "uri": "core://node",
                "priority": 5,
                "disclosure": "old disclosure",
            },
            lane_session_id="review.rollback:legacy-meta-missing",
        )

    assert exc_info.value.status_code == 404
    assert "Cannot rollback 'core://node':" in str(exc_info.value.detail)

    await client.close()


@pytest.mark.asyncio
async def test_sqlite_client_rollback_to_memory_restores_path_metadata(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-restore-meta.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    original = await client.create_memory(
        parent_path="",
        content="version 1",
        priority=1,
        title="agent",
        domain="core",
        disclosure="old disclosure",
    )
    await client.update_memory(
        path="agent",
        content="version 2",
        priority=5,
        disclosure="new disclosure",
        domain="core",
    )

    payload = await client.rollback_to_memory(
        "agent",
        original["id"],
        "core",
        restore_path_metadata=True,
        restore_priority=1,
        restore_disclosure="old disclosure",
    )

    current = await client.get_memory_by_path("agent", "core", reinforce_access=False)
    assert payload["restored_memory_id"] == original["id"]
    assert current is not None
    assert current["id"] == original["id"]
    assert current["priority"] == 1
    assert current["disclosure"] == "old disclosure"

    await client.close()


@pytest.mark.asyncio
async def test_sqlite_client_restore_path_metadata_rejects_expected_current_memory_id_mismatch(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-restore-meta-memory-mismatch.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    original = await client.create_memory(
        parent_path="",
        content="original content",
        priority=1,
        title="node",
        domain="core",
    )
    await client.remove_path("node", "core")
    replacement = await client.create_memory(
        parent_path="",
        content="replacement content",
        priority=3,
        title="node",
        domain="core",
    )

    with pytest.raises(ValueError, match="expected memory_id"):
        await client.restore_path_metadata(
            path="node",
            domain="core",
            priority=7,
            disclosure="replacement disclosure",
            expected_current_memory_id=original["id"],
        )

    current = await client.get_memory_by_path("node", "core", reinforce_access=False)
    assert current is not None
    assert current["id"] == replacement["id"]
    assert current["priority"] == 3

    await client.close()


@pytest.mark.asyncio
async def test_sqlite_client_restore_path_metadata_rejects_expected_current_metadata_mismatch(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-restore-meta-state-mismatch.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    await client.create_memory(
        parent_path="",
        content="content",
        priority=1,
        title="node",
        domain="core",
        disclosure="old disclosure",
    )
    await client.restore_path_metadata(
        path="node",
        domain="core",
        priority=5,
        disclosure="current disclosure",
    )

    with pytest.raises(ValueError, match="expected priority"):
        await client.restore_path_metadata(
            path="node",
            domain="core",
            priority=7,
            disclosure="replacement disclosure",
            expected_current_priority=1,
            expected_current_disclosure="old disclosure",
        )

    current = await client.get_memory_by_path("node", "core", reinforce_access=False)
    assert current is not None
    assert current["priority"] == 5
    assert current["disclosure"] == "current disclosure"

    await client.close()


@pytest.mark.asyncio
async def test_sqlite_client_rollback_to_memory_rolls_back_on_reindex_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "review-rollback-atomicity.db"
    client = SQLiteClient(_sqlite_url(db_path))
    await client.init_db()

    original = await client.create_memory(
        parent_path="",
        content="version 1",
        priority=1,
        title="agent",
        domain="core",
        disclosure="old disclosure",
    )
    update_payload = await client.update_memory(
        path="agent",
        content="version 2",
        priority=5,
        disclosure="new disclosure",
        domain="core",
    )
    current_id = update_payload["new_memory_id"]

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("reindex boom")

    monkeypatch.setattr(client, "_reindex_memory", _boom)

    with pytest.raises(RuntimeError, match="reindex boom"):
        await client.rollback_to_memory(
            "agent",
            original["id"],
            "core",
            restore_path_metadata=True,
            restore_priority=1,
            restore_disclosure="old disclosure",
        )

    current = await client.get_memory_by_path("agent", "core", reinforce_access=False)
    assert current is not None
    assert current["id"] == current_id
    assert current["priority"] == 5
    assert current["disclosure"] == "new disclosure"

    await client.close()
