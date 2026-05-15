import logging
import json
import threading
import time
import ctypes as stdlib_ctypes
from pathlib import Path

import pytest
from fastapi import HTTPException
from api import review as review_api
import db.snapshot as snapshot_module
from db.snapshot import SnapshotManager


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


def _write_snapshot_session(
    snapshot_dir: Path,
    *,
    session_id: str,
    created_at: str,
    scope: dict[str, str],
    resource_id: str | None = None,
) -> None:
    resource_uri = resource_id or f"notes://{session_id}"
    session_dir = snapshot_dir / session_id
    resources_dir = session_dir / "resources"
    resources_dir.mkdir(parents=True, exist_ok=True)
    resource_file = "snapshot.json"

    (resources_dir / resource_file).write_text(
        json.dumps(
            {
                "resource_id": resource_uri,
                "resource_type": "path",
                "snapshot_time": created_at,
                "data": {
                    "uri": resource_uri,
                    "operation_type": "create",
                },
            }
        ),
        encoding="utf-8",
    )
    (session_dir / "manifest.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "created_at": created_at,
                "database_fingerprint": scope["database_fingerprint"],
                "database_label": scope["database_label"],
                "resources": {
                    resource_uri: {
                        "resource_type": "path",
                        "snapshot_time": created_at,
                        "operation_type": "create",
                        "file": resource_file,
                        "uri": resource_uri,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_get_snapshot_manager_uses_a_single_instance_under_thread_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSnapshotManager:
        init_calls = 0

        def __init__(self) -> None:
            type(self).init_calls += 1
            time.sleep(0.01)

    monkeypatch.setattr(snapshot_module, "SnapshotManager", _FakeSnapshotManager)
    monkeypatch.setattr(snapshot_module, "_snapshot_manager", None)
    monkeypatch.setattr(snapshot_module, "_snapshot_manager_lock", threading.Lock())

    created_instances: list[object] = []

    def _load_manager() -> None:
        created_instances.append(snapshot_module.get_snapshot_manager())

    threads = [threading.Thread(target=_load_manager) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert _FakeSnapshotManager.init_calls == 1
    assert len({id(instance) for instance in created_instances}) == 1


def test_snapshot_manager_filters_sessions_by_current_database_scope(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manager = SnapshotManager(str(tmp_path / "snapshots"))
    db_a = tmp_path / "scope-a.db"
    db_b = tmp_path / "scope-b.db"

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(db_a))
    created = manager.create_snapshot(
        "session-a",
        "notes://alpha",
        "path",
        {
            "uri": "notes://alpha",
            "operation_type": "create",
        },
    )
    assert created is True

    manifest_a = json.loads(
        (tmp_path / "snapshots" / "session-a" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest_a["database_label"] == "scope-a.db"
    assert manager.list_sessions()[0]["session_id"] == "session-a"

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(db_b))
    created = manager.create_snapshot(
        "session-b",
        "notes://beta",
        "path",
        {
            "uri": "notes://beta",
            "operation_type": "create",
        },
    )
    assert created is True

    sessions = manager.list_sessions()
    assert [item["session_id"] for item in sessions] == ["session-b"]
    assert manager.list_snapshots("session-a") == []
    assert manager.get_snapshot("session-a", "notes://alpha") is None


def test_snapshot_manager_isolates_reused_session_ids_by_database_scope(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manager = SnapshotManager(str(tmp_path / "snapshots"))
    db_a = tmp_path / "scope-a.db"
    db_b = tmp_path / "scope-b.db"
    session_id = "shared-session"

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(db_a))
    assert manager.create_snapshot(
        session_id,
        "notes://alpha",
        "path",
        {
            "uri": "notes://alpha",
            "operation_type": "create",
        },
    ) is True

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(db_b))
    assert manager.create_snapshot(
        session_id,
        "notes://beta",
        "path",
        {
            "uri": "notes://beta",
            "operation_type": "create",
        },
    ) is True

    manifest = manager._load_manifest(session_id)
    sessions = manager.list_sessions()
    snapshots = manager.list_snapshots(session_id)

    assert [item["session_id"] for item in sessions] == [session_id]
    assert manifest["database_label"] == "scope-b.db"
    assert set(manifest["resources"]) == {"notes://beta"}
    assert [item["resource_id"] for item in snapshots] == ["notes://beta"]
    assert manager.get_snapshot(session_id, "notes://alpha") is None


def test_snapshot_manager_preserves_other_database_session_on_session_id_collision(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manager = SnapshotManager(str(tmp_path / "snapshots"))
    db_a = tmp_path / "scope-a.db"
    db_b = tmp_path / "scope-b.db"
    session_id = "shared-session"

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(db_a))
    assert manager.create_snapshot(
        session_id,
        "notes://alpha",
        "path",
        {
            "uri": "notes://alpha",
            "operation_type": "create",
        },
    ) is True

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(db_b))
    assert manager.create_snapshot(
        session_id,
        "notes://beta",
        "path",
        {
            "uri": "notes://beta",
            "operation_type": "create",
        },
    ) is True

    assert [item["resource_id"] for item in manager.list_snapshots(session_id)] == [
        "notes://beta"
    ]
    assert manager.get_snapshot(session_id, "notes://beta") is not None

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(db_a))
    assert [item["resource_id"] for item in manager.list_snapshots(session_id)] == [
        "notes://alpha"
    ]
    restored = manager.get_snapshot(session_id, "notes://alpha")
    assert restored is not None
    assert restored["data"]["uri"] == "notes://alpha"


def test_snapshot_manager_hides_legacy_unscoped_sessions_when_database_scope_is_set(
    caplog: pytest.LogCaptureFixture,
    monkeypatch,
    tmp_path: Path,
) -> None:
    snapshot_dir = tmp_path / "snapshots"
    session_dir = snapshot_dir / "legacy-session"
    resources_dir = session_dir / "resources"
    resources_dir.mkdir(parents=True, exist_ok=True)

    (resources_dir / "legacy.json").write_text(
        json.dumps(
            {
                "resource_id": "notes://legacy",
                "resource_type": "path",
                "snapshot_time": "2026-03-11T00:00:00",
                "data": {
                    "uri": "notes://legacy",
                    "operation_type": "create",
                },
            }
        ),
        encoding="utf-8",
    )
    (session_dir / "manifest.json").write_text(
        json.dumps(
            {
                "session_id": "legacy-session",
                "created_at": "2026-03-11T00:00:00",
                "resources": {
                    "notes://legacy": {
                        "resource_type": "path",
                        "snapshot_time": "2026-03-11T00:00:00",
                        "operation_type": "create",
                        "file": "legacy.json",
                        "uri": "notes://legacy",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(tmp_path / "active.db"))
    manager = SnapshotManager(str(snapshot_dir))

    with caplog.at_level(logging.WARNING):
        assert manager.list_sessions() == []
        assert manager.list_snapshots("legacy-session") == []
        assert manager.get_snapshot("legacy-session", "notes://legacy") is None

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Hiding legacy snapshot session without database_fingerprint" in message
        for message in messages
    )


def test_snapshot_manager_serializes_same_session_manifest_updates(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manager = SnapshotManager(str(tmp_path / "snapshots"))
    session_id = "shared-session"
    first_save_started = threading.Event()
    release_first_save = threading.Event()
    second_save_started = threading.Event()
    save_call_count = 0
    save_call_guard = threading.Lock()
    original_save_manifest = manager._save_manifest
    failures: list[Exception] = []
    results: dict[str, bool] = {}

    def delayed_save_manifest(
        target_session_id: str,
        manifest: dict[str, object],
        **kwargs,
    ) -> None:
        nonlocal save_call_count
        with save_call_guard:
            save_call_count += 1
            current_call = save_call_count
        if target_session_id == session_id and current_call == 1:
            first_save_started.set()
            assert release_first_save.wait(timeout=2)
        elif target_session_id == session_id and current_call == 2:
            second_save_started.set()
        original_save_manifest(target_session_id, manifest, **kwargs)

    def create_named_snapshot(name: str) -> None:
        try:
            results[name] = manager.create_snapshot(
                session_id,
                f"notes://{name}",
                "path",
                {
                    "uri": f"notes://{name}",
                    "operation_type": "create",
                },
            )
        except Exception as exc:  # pragma: no cover - surfaced by assertion below
            failures.append(exc)

    monkeypatch.setattr(manager, "_save_manifest", delayed_save_manifest)

    first_thread = threading.Thread(target=create_named_snapshot, args=("alpha",))
    second_thread = threading.Thread(target=create_named_snapshot, args=("beta",))

    first_thread.start()
    assert first_save_started.wait(timeout=2)

    second_thread.start()
    assert not second_save_started.wait(timeout=0.3)

    release_first_save.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert failures == []
    assert results == {"alpha": True, "beta": True}

    manifest = json.loads(
        (tmp_path / "snapshots" / session_id / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(manifest["resources"]) == {"notes://alpha", "notes://beta"}


def test_snapshot_manager_windows_pid_check_uses_win32_api(
    monkeypatch,
) -> None:
    class _FakeKernel32:
        def __init__(self) -> None:
            self.closed_handles: list[int] = []

        def OpenProcess(self, access: int, inherit: bool, pid: int) -> int:
            assert access == 0x1000
            assert inherit is False
            assert pid == 4242
            return 99

        def GetExitCodeProcess(self, handle: int, exit_code_ptr) -> int:
            assert handle == 99
            exit_code_ptr._obj.value = 259
            return 1

        def CloseHandle(self, handle: int) -> int:
            self.closed_handles.append(handle)
            return 1

    fake_kernel32 = _FakeKernel32()
    class _FakeCtypes:
        c_ulong = stdlib_ctypes.c_ulong
        byref = staticmethod(stdlib_ctypes.byref)

        @staticmethod
        def WinDLL(*_args, **_kwargs):
            return fake_kernel32

        @staticmethod
        def get_last_error():
            return 0

    monkeypatch.setattr(snapshot_module, "_is_windows_host", lambda: True)
    monkeypatch.setattr(
        snapshot_module,
        "_get_ctypes_module",
        lambda: _FakeCtypes,
    )
    monkeypatch.setattr(
        snapshot_module.os,
        "kill",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("os.kill should not be used on Windows")
        ),
        raising=False,
    )

    assert SnapshotManager._pid_is_alive(4242) is True
    assert fake_kernel32.closed_handles == [99]


@pytest.mark.parametrize(
    "session_id",
    [
        "\u200b",
        "abc\u200bdef",
        "abc\u200ddef",
        "abc\x1fdef",
        " abc",
        "abc ",
        "\tabc",
        "abc\t",
        "abc\n",
        "abc def",
        "abc.",
    ],
)
def test_session_id_validation_rejects_invisible_and_control_characters(
    session_id: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="(invisible or control characters|must not contain whitespace|must not end with dot or space)",
    ):
        SnapshotManager._validate_session_id(session_id)

    with pytest.raises(
        HTTPException,
        match="(invisible or control characters|must not contain whitespace|must not end with dot or space)",
    ):
        review_api._validate_session_id_or_400(session_id)


def test_write_json_atomic_retries_retryable_windows_replace_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target_path = tmp_path / "manifest.json"
    replace_calls: list[tuple[str, str]] = []
    original_replace = snapshot_module.os.replace

    def _flaky_replace(src: str, dst: str) -> None:
        replace_calls.append((src, dst))
        if len(replace_calls) == 1:
            raise PermissionError("sharing violation")
        original_replace(src, dst)

    monkeypatch.setattr(snapshot_module.os, "replace", _flaky_replace)

    snapshot_module._write_json_atomic(
        str(target_path),
        {"session_id": "retryable-session"},
    )

    assert json.loads(target_path.read_text(encoding="utf-8")) == {
        "session_id": "retryable-session"
    }
    assert len(replace_calls) == 2


def test_delete_snapshot_keeps_resource_file_when_manifest_save_fails(
    tmp_path: Path,
) -> None:
    manager = SnapshotManager(str(tmp_path / "snapshots"))
    session_id = "delete-order"
    first_uri = "notes://first"
    second_uri = "notes://second"

    assert manager.create_snapshot(
        session_id,
        first_uri,
        "path",
        {"uri": first_uri, "operation_type": "create"},
    )
    assert manager.create_snapshot(
        session_id,
        second_uri,
        "path",
        {"uri": second_uri, "operation_type": "create"},
    )

    manifest = manager._load_manifest(session_id)
    resource_file = manifest["resources"][first_uri]["file"]
    resource_path = tmp_path / "snapshots" / session_id / "resources" / resource_file
    assert resource_path.exists()

    original_save_manifest = manager._save_manifest

    def _failing_save_manifest(
        _session_id: str,
        _manifest: dict[str, object],
        **_kwargs,
    ) -> None:
        raise RuntimeError("save_failed")

    manager._save_manifest = _failing_save_manifest  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="save_failed"):
        manager.delete_snapshot(session_id, first_uri)

    manager._save_manifest = original_save_manifest  # type: ignore[method-assign]
    assert resource_path.exists()


def test_create_snapshot_removes_resource_file_when_manifest_save_fails(
    tmp_path: Path,
) -> None:
    manager = SnapshotManager(str(tmp_path / "snapshots"))
    session_id = "create-order"
    uri = "notes://created"

    def _failing_save_manifest(
        _session_id: str,
        _manifest: dict[str, object],
        **_kwargs,
    ) -> None:
        raise RuntimeError("save_failed")

    manager._save_manifest = _failing_save_manifest  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="save_failed"):
        manager.create_snapshot(
            session_id,
            uri,
            "path",
            {"uri": uri, "operation_type": "create"},
        )

    resources_dir = tmp_path / "snapshots" / session_id / "resources"
    assert not list(resources_dir.glob("*.json"))


def test_force_create_snapshot_restores_previous_resource_when_manifest_save_fails(
    tmp_path: Path,
) -> None:
    manager = SnapshotManager(str(tmp_path / "snapshots"))
    session_id = "force-create-order"
    uri = "notes://forced"

    assert manager.create_snapshot(
        session_id,
        uri,
        "path",
        {"uri": uri, "operation_type": "modify_meta", "content": "before"},
    )
    before_snapshot = manager.get_snapshot(session_id, uri)
    assert before_snapshot is not None

    original_save_manifest = manager._save_manifest

    def _failing_save_manifest(
        _session_id: str,
        _manifest: dict[str, object],
        **_kwargs,
    ) -> None:
        raise RuntimeError("save_failed")

    manager._save_manifest = _failing_save_manifest  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="save_failed"):
        manager.create_snapshot(
            session_id,
            uri,
            "path",
            {"uri": uri, "operation_type": "delete", "content": "after"},
            force=True,
        )

    manager._save_manifest = original_save_manifest  # type: ignore[method-assign]
    restored_snapshot = manager.get_snapshot(session_id, uri)
    assert restored_snapshot == before_snapshot
    assert restored_snapshot["data"]["operation_type"] == "modify_meta"


def test_delete_snapshot_removes_manifest_entry_when_resource_file_is_missing(
    tmp_path: Path,
) -> None:
    manager = SnapshotManager(str(tmp_path / "snapshots"))
    session_id = "ghost-session"
    uri = "notes://ghost"

    assert manager.create_snapshot(
        session_id,
        uri,
        "path",
        {"uri": uri, "operation_type": "create"},
    )

    manifest = manager._load_manifest(session_id)
    resource_file = manifest["resources"][uri]["file"]
    resource_path = tmp_path / "snapshots" / session_id / "resources" / resource_file
    resource_path.unlink()

    assert manager.delete_snapshot(session_id, uri) is True
    assert manager.list_snapshots(session_id) == []
    assert (tmp_path / "snapshots" / session_id).exists() is False


def test_snapshot_manager_sanitize_resource_id_uses_sha256_hash_suffix(
    monkeypatch,
) -> None:
    class _FakeSha256:
        def hexdigest(self) -> str:
            return "deadbeef" * 8

    def _fake_sha256(payload: bytes) -> _FakeSha256:
        assert payload == b"core://a/b"
        return _FakeSha256()

    monkeypatch.setattr(
        snapshot_module.hashlib,
        "md5",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("md5 should not be used")
        ),
        raising=False,
    )
    monkeypatch.setattr(snapshot_module.hashlib, "sha256", _fake_sha256)

    assert SnapshotManager._sanitize_resource_id("core://a/b") == "core__a_b_deadbeef"


def test_snapshot_manager_maps_file_lock_timeout_to_timeout_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manager = SnapshotManager(str(tmp_path / "snapshots"))

    class _AlwaysBusyFileLock:
        def __init__(self, lock_path: str, timeout: float) -> None:
            assert lock_path.endswith("busy-session.lock")
            assert timeout == 5.0

        def __enter__(self):
            raise snapshot_module.FileLockTimeout("busy")

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    monkeypatch.setattr(snapshot_module, "FileLock", _AlwaysBusyFileLock)

    with pytest.raises(TimeoutError, match="Timed out waiting for snapshot session lock"):
        with manager._session_write_lock("busy-session"):
            pass


def test_snapshot_manager_rebuilds_manifest_from_resource_files_when_manifest_corrupted(
    monkeypatch,
    tmp_path: Path,
) -> None:
    snapshot_dir = tmp_path / "snapshots"
    session_dir = snapshot_dir / "corrupt-session"
    resources_dir = session_dir / "resources"
    resources_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(tmp_path / "active.db"))
    scope = snapshot_module._resolve_current_database_scope()
    (session_dir / "manifest.json").write_text("{not-valid-json", encoding="utf-8")
    (session_dir / ".scope.json").write_text(
        json.dumps(scope),
        encoding="utf-8",
    )
    (resources_dir / "memory_alpha.json").write_text(
        json.dumps(
            {
                "resource_id": "notes://alpha",
                "resource_type": "path",
                "snapshot_time": "2026-03-20T10:00:00",
                "data": {
                    "uri": "notes://alpha",
                    "operation_type": "create",
                },
            }
        ),
        encoding="utf-8",
    )

    manager = SnapshotManager(str(snapshot_dir))

    snapshots = manager.list_snapshots("corrupt-session")
    rebuilt_manifest = json.loads(
        (session_dir / "manifest.json").read_text(encoding="utf-8")
    )

    assert [item["resource_id"] for item in snapshots] == ["notes://alpha"]
    assert rebuilt_manifest["resources"]["notes://alpha"]["file"] == "memory_alpha.json"


def test_snapshot_manager_rebuilds_manifest_from_resource_files_when_manifest_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    snapshot_dir = tmp_path / "snapshots"
    session_dir = snapshot_dir / "orphan-session"
    resources_dir = session_dir / "resources"
    resources_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(tmp_path / "active.db"))
    scope = snapshot_module._resolve_current_database_scope()
    (session_dir / ".scope.json").write_text(
        json.dumps(scope),
        encoding="utf-8",
    )
    (resources_dir / "memory_alpha.json").write_text(
        json.dumps(
            {
                "resource_id": "notes://alpha",
                "resource_type": "path",
                "snapshot_time": "2026-03-20T10:00:00",
                "data": {
                    "uri": "notes://alpha",
                    "operation_type": "create",
                },
            }
        ),
        encoding="utf-8",
    )

    manager = SnapshotManager(str(snapshot_dir))

    snapshots = manager.list_snapshots("orphan-session")
    rebuilt_manifest = json.loads(
        (session_dir / "manifest.json").read_text(encoding="utf-8")
    )

    assert [item["resource_id"] for item in snapshots] == ["notes://alpha"]
    assert rebuilt_manifest["resources"]["notes://alpha"]["file"] == "memory_alpha.json"
    assert rebuilt_manifest["database_fingerprint"] == scope["database_fingerprint"]


def test_snapshot_manager_logs_and_recovers_when_manifest_json_is_invalid(
    caplog: pytest.LogCaptureFixture,
    monkeypatch,
    tmp_path: Path,
) -> None:
    snapshot_dir = tmp_path / "snapshots"
    session_dir = snapshot_dir / "broken-session"
    resources_dir = session_dir / "resources"
    resources_dir.mkdir(parents=True, exist_ok=True)
    (resources_dir / "notes_alpha.json").write_text(
        json.dumps(
            {
                "resource_id": "notes://alpha",
                "resource_type": "path",
                "snapshot_time": "2026-03-20T12:00:00",
                "data": {
                    "uri": "notes://alpha",
                    "operation_type": "create",
                },
            }
        ),
        encoding="utf-8",
    )
    (session_dir / "manifest.json").write_text("{broken-json", encoding="utf-8")

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(tmp_path / "active.db"))
    scope = snapshot_module._resolve_current_database_scope()
    (session_dir / ".scope.json").write_text(
        json.dumps(scope),
        encoding="utf-8",
    )
    manager = SnapshotManager(str(snapshot_dir))

    with caplog.at_level("WARNING"):
        snapshots = manager.list_snapshots("broken-session")

    assert snapshots == [
        {
            "resource_id": "notes://alpha",
            "resource_type": "path",
            "snapshot_time": "2026-03-20T12:00:00",
            "operation_type": "create",
            "uri": "notes://alpha",
        }
    ]
    assert "Failed to load snapshot manifest for session broken-session" in caplog.text
    assert "Recovered snapshot manifest for session broken-session" in caplog.text


def test_snapshot_manager_does_not_rebind_corrupted_manifest_to_current_database_scope(
    monkeypatch,
    tmp_path: Path,
) -> None:
    snapshot_dir = tmp_path / "snapshots"
    manager = SnapshotManager(str(snapshot_dir))
    db_a = tmp_path / "scope-a.db"
    db_b = tmp_path / "scope-b.db"

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(db_a))
    assert manager.create_snapshot(
        "cross-db-session",
        "notes://alpha",
        "path",
        {
            "uri": "notes://alpha",
            "operation_type": "create",
        },
    )

    manifest_path = snapshot_dir / "cross-db-session" / "manifest.json"
    manifest_path.write_text("{broken-json", encoding="utf-8")

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(db_b))
    sessions = manager.list_sessions()
    rebuilt_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert sessions == []
    assert rebuilt_manifest["database_label"] == "scope-a.db"
    assert rebuilt_manifest["database_fingerprint"] != snapshot_module._resolve_current_database_scope()[
        "database_fingerprint"
    ]


def test_snapshot_manager_list_sessions_does_not_delete_unrecoverable_corrupted_session(
    monkeypatch,
    tmp_path: Path,
) -> None:
    snapshot_dir = tmp_path / "snapshots"
    session_dir = snapshot_dir / "broken-session"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "manifest.json").write_text("{broken-json", encoding="utf-8")

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(tmp_path / "active.db"))
    manager = SnapshotManager(str(snapshot_dir))

    assert manager.list_sessions() == []
    assert session_dir.exists() is True


def test_snapshot_manager_list_sessions_skips_invalid_legacy_session_names(
    monkeypatch,
    tmp_path: Path,
) -> None:
    snapshot_dir = tmp_path / "snapshots"
    invalid_session_dir = snapshot_dir / "legacy session"
    invalid_session_dir.mkdir(parents=True, exist_ok=True)
    (invalid_session_dir / "manifest.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(tmp_path / "active.db"))
    manager = SnapshotManager(str(snapshot_dir))

    assert manager.list_sessions() == []


def test_snapshot_manager_age_gc_prunes_old_sessions_but_keeps_current_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snapshot_dir = tmp_path / "snapshots"
    manager = SnapshotManager(str(snapshot_dir))

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(tmp_path / "active.db"))
    monkeypatch.setenv("SNAPSHOT_RETENTION_MAX_AGE_DAYS", "1")
    monkeypatch.delenv("SNAPSHOT_RETENTION_MAX_SESSIONS", raising=False)

    scope = snapshot_module._resolve_current_database_scope()
    stale_timestamp = "2000-01-01T00:00:00+00:00"
    _write_snapshot_session(
        snapshot_dir,
        session_id="stale-session",
        created_at=stale_timestamp,
        scope=scope,
    )

    monkeypatch.setattr(snapshot_module, "_utc_iso_now", lambda: stale_timestamp)

    assert manager.create_snapshot(
        "current-session",
        "notes://current",
        "path",
        {"uri": "notes://current", "operation_type": "create"},
    )

    assert [item["session_id"] for item in manager.list_sessions()] == ["current-session"]
    assert (snapshot_dir / "stale-session").exists() is False
    assert (snapshot_dir / "current-session").exists() is True


def test_snapshot_manager_count_gc_keeps_current_session_even_when_it_is_oldest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snapshot_dir = tmp_path / "snapshots"
    manager = SnapshotManager(str(snapshot_dir))

    monkeypatch.setenv("DATABASE_URL", _sqlite_url(tmp_path / "active.db"))
    monkeypatch.setenv("SNAPSHOT_RETENTION_MAX_AGE_DAYS", "0")
    monkeypatch.setenv("SNAPSHOT_RETENTION_MAX_SESSIONS", "2")

    scope = snapshot_module._resolve_current_database_scope()
    _write_snapshot_session(
        snapshot_dir,
        session_id="recent-a",
        created_at="2026-03-03T00:00:00+00:00",
        scope=scope,
    )
    _write_snapshot_session(
        snapshot_dir,
        session_id="recent-b",
        created_at="2026-03-02T00:00:00+00:00",
        scope=scope,
    )
    _write_snapshot_session(
        snapshot_dir,
        session_id="stale-c",
        created_at="2026-03-01T00:00:00+00:00",
        scope=scope,
    )

    monkeypatch.setattr(
        snapshot_module,
        "_utc_iso_now",
        lambda: "2026-02-01T00:00:00+00:00",
    )

    assert manager.create_snapshot(
        "current-session",
        "notes://current",
        "path",
        {"uri": "notes://current", "operation_type": "create"},
    )

    assert [item["session_id"] for item in manager.list_sessions()] == [
        "recent-a",
        "current-session",
    ]
    assert (snapshot_dir / "recent-b").exists() is False
    assert (snapshot_dir / "stale-c").exists() is False
