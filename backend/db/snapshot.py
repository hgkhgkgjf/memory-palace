"""
Snapshot Manager for Selective Rollback

This module implements a snapshot system that allows the human to review and
selectively roll back the AI's database operations.

Design Principles:
1. Snapshots are taken BEFORE the first modification to a resource in a session
2. Multiple modifications to the same resource in one session share ONE snapshot
3. Rollback creates a NEW version with snapshot content (preserves version chain)
4. Session-based organization for easy cleanup

    Storage Structure:
    snapshots/
    └── {session_id}/
        ├── manifest.json          # Session metadata and resource index
        └── resources/
            └── {safe_resource_id}.json
"""

import errno
import json
import hashlib
import logging
import os
import re
import shutil
import stat
import tempfile
import threading
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from pathlib import Path
from urllib.parse import unquote
from filelock import FileLock, Timeout as FileLockTimeout
from shared_utils import utc_iso_now as _utc_iso_now


# Default snapshot directory (relative to workspace root)
DEFAULT_SNAPSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "snapshots"
)

_SQLITE_URL_PREFIXES = ("sqlite+aiosqlite:///", "sqlite:///")
_SESSION_LOCK_WAIT_SECONDS = 5.0
_SNAPSHOT_RETENTION_MAX_AGE_DAYS = 90
_SNAPSHOT_RETENTION_MAX_SESSIONS = 64
logger = logging.getLogger(__name__)
_SCOPE_MARKER_FILENAME = ".scope.json"
_SCOPED_SESSION_DIRNAME = ".scoped"


def _get_ctypes_module():
    import ctypes

    return ctypes


def _is_windows_host() -> bool:
    return os.name == "nt"


def _read_non_negative_int_env(name: str, default: int) -> int:
    raw_value = str(os.getenv(name) or "").strip()
    if not raw_value:
        return default
    try:
        return max(int(raw_value), 0)
    except ValueError:
        logger.warning(
            "Ignoring invalid %s=%r; expected a non-negative integer",
            name,
            raw_value,
        )
        return default


def _parse_snapshot_timestamp(raw_value: Any) -> Optional[datetime]:
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_current_database_scope() -> Dict[str, str]:
    """
    Build a stable scope identifier for the current database target.

    Review snapshots live under a repo-level directory, so switching
    DATABASE_URL inside the same checkout can otherwise expose unrelated
    rollback sessions from another SQLite file.
    """
    raw_url = str(os.getenv("DATABASE_URL") or "").strip()
    normalized = raw_url or "database_url:missing"
    label = normalized

    for prefix in _SQLITE_URL_PREFIXES:
        if not raw_url.startswith(prefix):
            continue
        raw_path = raw_url[len(prefix) :].split("?", 1)[0].split("#", 1)[0]
        raw_path = unquote(raw_path)
        if raw_path and raw_path not in {":memory:"} and not raw_path.startswith("file::memory:"):
            resolved_path = Path(raw_path).expanduser().resolve(strict=False)
            normalized = f"sqlite:{resolved_path.as_posix()}"
            label = resolved_path.name or resolved_path.as_posix()
        else:
            normalized = f"sqlite:{raw_path or ':memory:'}"
            label = raw_path or ":memory:"
        break

    fingerprint = hashlib.sha256(
        normalized.encode("utf-8", errors="ignore")
    ).hexdigest()
    return {
        "database_fingerprint": fingerprint,
        "database_label": label,
    }


def _handle_remove_readonly(func, path, exc_info):
    """Make read-only files writable before retrying removal."""
    exc_type, exc_value, _ = exc_info
    if issubclass(exc_type, PermissionError):
        try:
            os.chmod(path, stat.S_IWRITE)
        except OSError:
            pass
        func(path)
    else:
        raise exc_value


def _force_remove(path: str):
    """Delete files or directories regardless of read-only attributes."""
    if not os.path.exists(path):
        return
    if os.path.isdir(path):
        shutil.rmtree(path, onerror=_handle_remove_readonly)
    else:
        try:
            os.remove(path)
        except PermissionError:
            os.chmod(path, stat.S_IWRITE)
            os.remove(path)
        except FileNotFoundError:
            pass


def _write_json_atomic(path: str, payload: Dict[str, Any]) -> None:
    """Write JSON through a temp file and atomically replace the target."""
    parent_dir = os.path.dirname(path)
    if parent_dir:
        Path(parent_dir).mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{Path(path).name}.",
        suffix=".tmp",
        dir=parent_dir or None,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                os.replace(tmp_path, path)
                break
            except PermissionError:
                if attempt >= max_attempts - 1:
                    raise
            except OSError as exc:
                retryable = getattr(exc, "winerror", None) in {5, 32, 33} or exc.errno in {
                    errno.EACCES,
                    errno.EPERM,
                }
                if not retryable or attempt >= max_attempts - 1:
                    raise
            time.sleep(0.05 * (attempt + 1))
    finally:
        if os.path.exists(tmp_path):
            _force_remove(tmp_path)


def _write_bytes_atomic(path: str, payload: bytes) -> None:
    """Write bytes through a temp file and atomically replace the target."""
    parent_dir = os.path.dirname(path)
    if parent_dir:
        Path(parent_dir).mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{Path(path).name}.",
        suffix=".tmp",
        dir=parent_dir or None,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            _force_remove(tmp_path)


class SnapshotManager:
    """
    Manages snapshots for selective rollback functionality.
    
    Each session (typically one agent task/conversation) has its own snapshot space.
    Within a session, each resource gets at most ONE snapshot - the state before
    the first modification.

    Concurrency note:
    snapshot JSON writes rely on per-session file locks plus atomic file replace.
    Database rollback correctness still depends on the SQLite/runtime write
    serialization guarantees provided by the rest of the backend.
    """
    
    def __init__(self, snapshot_dir: Optional[str] = None):
        self.snapshot_dir = snapshot_dir or DEFAULT_SNAPSHOT_DIR
        self._warned_legacy_unscoped_sessions: set[str] = set()
        self._ensure_dir_exists(self.snapshot_dir)

    @staticmethod
    def _validate_session_id(session_id: str) -> str:
        """Validate session_id to prevent path traversal and invalid paths."""
        value = str(session_id or "")
        if not value:
            raise ValueError("session_id must not be empty")
        if value in {".", ".."}:
            raise ValueError("session_id contains invalid path segment")
        if "/" in value or "\\" in value or "\x00" in value:
            raise ValueError("session_id contains invalid characters")
        if any(char in value for char in '<>:"|?*'):
            raise ValueError("session_id contains invalid filename characters")
        if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value):
            raise ValueError("session_id contains invisible or control characters")
        if any(char.isspace() for char in value):
            raise ValueError("session_id must not contain whitespace")
        if value.endswith(".") or value.endswith(" "):
            raise ValueError("session_id must not end with dot or space")
        return value
    
    @staticmethod
    def _ensure_dir_exists(path: str):
        """Create directory if it doesn't exist."""
        Path(path).mkdir(parents=True, exist_ok=True)
    
    @staticmethod
    def _sanitize_resource_id(resource_id: str) -> str:
        """
        Convert a resource_id to a safe filename.
        
        Resource IDs like URIs "core://path/to/memory" need sanitization.
        We use a deterministic hash suffix for uniqueness to prevent collisions
        (e.g. "core://a/b" vs "core://a_b") while keeping readability.
        """
        # Calculate hash of the ORIGINAL resource_id for uniqueness
        # This prevents "core://a/b" and "core://a_b" from colliding regardless of sanitization
        id_hash = hashlib.sha256(
            resource_id.encode("utf-8", errors="ignore")
        ).hexdigest()[:8]

        # Replace problematic characters
        # 1. Handle protocol separator specifically for better readability
        safe_id = resource_id.replace("://", "__")
        
        # 2. Replace remaining colons, slashes, and backslashes
        safe_id = safe_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        
        # 3. Replace relation arrow
        safe_id = safe_id.replace(">", "_to_")
        
        # Truncate if too long (keeping enough distinct chars + hash)
        # Windows max path is ~260 chars. We leave plenty of buffer.
        if len(safe_id) > 100:
            safe_id = safe_id[:100]
        
        # Always append hash to guarantee uniqueness
        return f"{safe_id}_{id_hash}"
    
    def _get_session_dir(self, session_id: str) -> str:
        """Get the directory path for a session."""
        safe_session_id = self._validate_session_id(session_id)
        return os.path.join(self.snapshot_dir, safe_session_id)

    @staticmethod
    def _scope_fingerprint(scope: Optional[Dict[str, str]] = None) -> str:
        payload = scope or _resolve_current_database_scope()
        return str(payload.get("database_fingerprint") or "").strip()

    def _get_scoped_sessions_root(self, database_fingerprint: str) -> str:
        return os.path.join(
            self.snapshot_dir,
            _SCOPED_SESSION_DIRNAME,
            database_fingerprint,
        )

    def _get_scoped_session_dir(
        self, session_id: str, database_fingerprint: str
    ) -> str:
        safe_session_id = self._validate_session_id(session_id)
        return os.path.join(
            self._get_scoped_sessions_root(database_fingerprint),
            safe_session_id,
        )

    def _get_resources_dir(
        self, session_id: str, *, session_dir: Optional[str] = None
    ) -> str:
        """Get the resources subdirectory for a session."""
        resolved_session_dir = session_dir or self._resolve_session_dir(session_id)
        return os.path.join(resolved_session_dir, "resources")

    def _get_manifest_path(
        self, session_id: str, *, session_dir: Optional[str] = None
    ) -> str:
        """Get the manifest file path for a session."""
        resolved_session_dir = session_dir or self._resolve_session_dir(session_id)
        return os.path.join(resolved_session_dir, "manifest.json")

    def _get_snapshot_path(
        self,
        session_id: str,
        resource_id: str,
        *,
        session_dir: Optional[str] = None,
    ) -> str:
        """Get the snapshot file path for a specific resource."""
        safe_id = self._sanitize_resource_id(resource_id)
        return os.path.join(
            self._get_resources_dir(session_id, session_dir=session_dir),
            f"{safe_id}.json",
        )

    def _get_scope_marker_path(
        self, session_id: str, *, session_dir: Optional[str] = None
    ) -> str:
        """Persist session database scope outside manifest recovery paths."""
        resolved_session_dir = session_dir or self._resolve_session_dir(session_id)
        return os.path.join(resolved_session_dir, _SCOPE_MARKER_FILENAME)

    def _resolve_session_dir(
        self, session_id: str, *, scope: Optional[Dict[str, str]] = None
    ) -> str:
        current_scope = scope or _resolve_current_database_scope()
        current_fingerprint = self._scope_fingerprint(current_scope)
        primary_dir = self._get_session_dir(session_id)
        scoped_dir = (
            self._get_scoped_session_dir(session_id, current_fingerprint)
            if current_fingerprint
            else primary_dir
        )

        if os.path.isdir(scoped_dir):
            return scoped_dir
        if not os.path.isdir(primary_dir):
            return primary_dir
        if scoped_dir == primary_dir:
            return primary_dir

        manifest_path = self._get_manifest_path(session_id, session_dir=primary_dir)
        scope_marker_path = self._get_scope_marker_path(
            session_id, session_dir=primary_dir
        )
        if not os.path.exists(manifest_path) and not os.path.exists(scope_marker_path):
            return primary_dir

        primary_manifest = self._load_manifest_from_dir(
            session_id,
            primary_dir,
            current_scope=current_scope,
        )
        if self._manifest_matches_scope(primary_manifest, current_scope):
            return primary_dir
        return scoped_dir

    def _get_session_lock_path(self, session_id: str) -> str:
        """Store per-session write locks outside the session tree."""
        safe_session_id = self._validate_session_id(session_id)
        return os.path.join(self.snapshot_dir, ".locks", f"{safe_session_id}.lock")

    @staticmethod
    def _pid_is_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if _is_windows_host():
            ctypes = _get_ctypes_module()
            process_query_limited_information = 0x1000
            error_access_denied = 5
            still_active = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(
                process_query_limited_information, False, pid
            )
            if not handle:
                return ctypes.get_last_error() == error_access_denied
            try:
                exit_code = ctypes.c_ulong()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
                    return True
                return int(exit_code.value) == still_active
            finally:
                kernel32.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    @contextmanager
    def _session_write_lock(self, session_id: str):
        """Serialize write paths for one session across processes."""
        self._ensure_dir_exists(os.path.join(self.snapshot_dir, ".locks"))
        lock = FileLock(
            self._get_session_lock_path(session_id),
            timeout=_SESSION_LOCK_WAIT_SECONDS,
        )
        try:
            with lock:
                yield
        except FileLockTimeout as exc:
            raise TimeoutError(
                f"Timed out waiting for snapshot session lock: {session_id}"
            ) from exc

    @contextmanager
    def _try_session_write_lock(self, session_id: str):
        """Try to acquire a session lock without waiting."""
        self._ensure_dir_exists(os.path.join(self.snapshot_dir, ".locks"))
        lock = FileLock(self._get_session_lock_path(session_id), timeout=0)
        acquired = False
        try:
            lock.acquire(timeout=0)
            acquired = True
            yield True
        except FileLockTimeout:
            yield False
        finally:
            if acquired:
                lock.release()

    @staticmethod
    def _retention_max_age_days() -> int:
        return _read_non_negative_int_env(
            "SNAPSHOT_RETENTION_MAX_AGE_DAYS",
            _SNAPSHOT_RETENTION_MAX_AGE_DAYS,
        )

    @staticmethod
    def _retention_max_sessions() -> int:
        return _read_non_negative_int_env(
            "SNAPSHOT_RETENTION_MAX_SESSIONS",
            _SNAPSHOT_RETENTION_MAX_SESSIONS,
        )

    def _garbage_collect_sessions(self, *, current_session_id: str) -> None:
        """
        Opportunistically prune old snapshot sessions in the current DB scope.

        GC is conservative:
        - only whole sessions are removed;
        - the caller's current session is never touched;
        - sessions with a busy write lock are skipped;
        - both age/count policies can be disabled via env by setting 0.
        """
        max_age_days = self._retention_max_age_days()
        max_sessions = self._retention_max_sessions()
        if max_age_days <= 0 and max_sessions <= 0:
            return

        sessions = self.list_sessions()
        if not sessions:
            return

        protected_session_ids = {current_session_id}
        prune_session_ids: set[str] = set()

        if max_age_days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
            for session in sessions:
                session_id = str(session.get("session_id") or "").strip()
                if not session_id or session_id in protected_session_ids:
                    continue
                created_at = _parse_snapshot_timestamp(session.get("created_at"))
                if created_at is None or created_at >= cutoff:
                    continue
                prune_session_ids.add(session_id)

        if max_sessions > 0:
            retained_session_ids = set(protected_session_ids)
            for session in sessions:
                session_id = str(session.get("session_id") or "").strip()
                if not session_id or session_id in retained_session_ids:
                    continue
                if len(retained_session_ids) >= max_sessions:
                    break
                retained_session_ids.add(session_id)
            for session in sessions:
                session_id = str(session.get("session_id") or "").strip()
                if session_id and session_id not in retained_session_ids:
                    prune_session_ids.add(session_id)

        for session in reversed(sessions):
            session_id = str(session.get("session_id") or "").strip()
            if not session_id or session_id in protected_session_ids:
                continue
            if session_id not in prune_session_ids:
                continue
            with self._try_session_write_lock(session_id) as acquired:
                if not acquired:
                    continue
                self._clear_session_unlocked(session_id)

    @staticmethod
    def _build_manifest_payload(
        session_id: str,
        *,
        created_at: Optional[str] = None,
        resources: Optional[Dict[str, Any]] = None,
        scope: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "session_id": session_id,
            "created_at": created_at or _utc_iso_now(),
            "resources": resources or {},
        }
        if isinstance(scope, dict):
            fingerprint = str(scope.get("database_fingerprint") or "").strip()
            label = str(scope.get("database_label") or "").strip()
            if fingerprint:
                payload["database_fingerprint"] = fingerprint
            if label:
                payload["database_label"] = label
        return payload

    @staticmethod
    def _extract_scope_from_manifest_text(raw_text: str) -> Optional[Dict[str, str]]:
        fingerprint_match = re.search(
            r'"database_fingerprint"\s*:\s*"([^"]+)"',
            raw_text,
        )
        if fingerprint_match is None:
            return None
        label_match = re.search(
            r'"database_label"\s*:\s*"([^"]*)"',
            raw_text,
        )
        return {
            "database_fingerprint": fingerprint_match.group(1),
            "database_label": label_match.group(1) if label_match else "",
        }

    def _load_scope_marker(
        self, session_id: str, *, session_dir: Optional[str] = None
    ) -> Optional[Dict[str, str]]:
        scope_marker_path = self._get_scope_marker_path(
            session_id, session_dir=session_dir
        )
        if not os.path.exists(scope_marker_path):
            return None
        try:
            with open(scope_marker_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        fingerprint = str(payload.get("database_fingerprint") or "").strip()
        if not fingerprint:
            return None
        return {
            "database_fingerprint": fingerprint,
            "database_label": str(payload.get("database_label") or "").strip(),
        }

    def _persist_scope_marker(
        self,
        session_id: str,
        manifest: Dict[str, Any],
        *,
        session_dir: Optional[str] = None,
    ) -> None:
        fingerprint = str(manifest.get("database_fingerprint") or "").strip()
        if not fingerprint:
            return
        _write_json_atomic(
            self._get_scope_marker_path(session_id, session_dir=session_dir),
            {
                "database_fingerprint": fingerprint,
                "database_label": str(manifest.get("database_label") or "").strip(),
            },
        )

    def _load_manifest_from_dir(
        self,
        session_id: str,
        session_dir: str,
        *,
        current_scope: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Load or create a manifest from a specific on-disk session directory."""
        manifest_path = self._get_manifest_path(session_id, session_dir=session_dir)

        if os.path.exists(manifest_path):
            raw_manifest_text = ""
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    raw_manifest_text = f.read()
                manifest = json.loads(raw_manifest_text)
                if isinstance(manifest, dict) and isinstance(
                    manifest.get("resources"), dict
                ):
                    return manifest
                raise ValueError("snapshot_manifest_invalid_payload")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Failed to load snapshot manifest for session %s: %s",
                    session_id,
                    exc,
                )
                recovered_scope = (
                    self._load_scope_marker(session_id, session_dir=session_dir)
                    or self._extract_scope_from_manifest_text(raw_manifest_text)
                )
                rebuilt_manifest = self._rebuild_manifest_from_resources(
                    session_id,
                    scope=recovered_scope,
                    session_dir=session_dir,
                )
                if rebuilt_manifest is not None:
                    if recovered_scope is not None:
                        logger.warning(
                            "Recovered snapshot manifest for session %s using resource files",
                            session_id,
                        )
                        try:
                            _write_json_atomic(manifest_path, rebuilt_manifest)
                            self._persist_scope_marker(
                                session_id,
                                rebuilt_manifest,
                                session_dir=session_dir,
                            )
                        except OSError as save_exc:
                            logger.warning(
                                "Failed to persist rebuilt snapshot manifest for session %s: %s",
                                session_id,
                                save_exc,
                            )
                    else:
                        logger.warning(
                            "Recovered snapshot resources for session %s but database scope is unknown; leaving manifest unmodified",
                            session_id,
                        )
                    return rebuilt_manifest

            return self._build_manifest_payload(session_id)

        recovered_scope = (
            self._load_scope_marker(session_id, session_dir=session_dir)
            or current_scope
        )
        rebuilt_manifest = self._rebuild_manifest_from_resources(
            session_id,
            scope=recovered_scope,
            session_dir=session_dir,
        )
        if rebuilt_manifest is not None:
            try:
                _write_json_atomic(manifest_path, rebuilt_manifest)
                self._persist_scope_marker(
                    session_id,
                    rebuilt_manifest,
                    session_dir=session_dir,
                )
            except OSError as save_exc:
                logger.warning(
                    "Failed to persist rebuilt snapshot manifest for session %s: %s",
                    session_id,
                    save_exc,
                )
            return rebuilt_manifest

        return self._build_manifest_payload(
            session_id,
            scope=current_scope or _resolve_current_database_scope(),
        )

    def _load_manifest(self, session_id: str) -> Dict[str, Any]:
        """Load or create the manifest visible to the current database scope."""
        current_scope = _resolve_current_database_scope()
        session_dir = self._resolve_session_dir(session_id, scope=current_scope)
        return self._load_manifest_from_dir(
            session_id,
            session_dir,
            current_scope=current_scope,
        )

    def _rebuild_manifest_from_resources(
        self,
        session_id: str,
        *,
        scope: Optional[Dict[str, str]] = None,
        session_dir: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Best-effort manifest recovery from per-resource snapshot files."""
        resources_dir = self._get_resources_dir(session_id, session_dir=session_dir)
        if not os.path.isdir(resources_dir):
            return None

        recovered_resources: Dict[str, Dict[str, Any]] = {}
        recovered_created_at: Optional[str] = None

        for entry in sorted(os.listdir(resources_dir)):
            if not entry.endswith(".json"):
                continue
            snapshot_path = os.path.join(resources_dir, entry)
            if not os.path.isfile(snapshot_path):
                continue
            try:
                with open(snapshot_path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Skipping unreadable snapshot payload %s while rebuilding session %s: %s",
                    entry,
                    session_id,
                    exc,
                )
                continue
            if not isinstance(payload, dict):
                logger.warning(
                    "Skipping invalid snapshot payload %s while rebuilding session %s",
                    entry,
                    session_id,
                )
                continue

            resource_id = str(payload.get("resource_id") or "").strip()
            resource_type = str(payload.get("resource_type") or "").strip()
            snapshot_time = str(payload.get("snapshot_time") or "").strip()
            snapshot_data = payload.get("data")
            if not resource_id or not resource_type:
                logger.warning(
                    "Skipping incomplete snapshot payload %s while rebuilding session %s",
                    entry,
                    session_id,
                )
                continue
            if not isinstance(snapshot_data, dict):
                snapshot_data = {}

            recovered_resources[resource_id] = {
                "resource_type": resource_type,
                "snapshot_time": snapshot_time,
                "operation_type": snapshot_data.get("operation_type", "modify"),
                "file": entry,
                "uri": snapshot_data.get("uri"),
            }
            if snapshot_time and (
                recovered_created_at is None or snapshot_time < recovered_created_at
            ):
                recovered_created_at = snapshot_time

        if not recovered_resources:
            return None

        return self._build_manifest_payload(
            session_id,
            created_at=recovered_created_at or _utc_iso_now(),
            resources=recovered_resources,
            scope=scope,
        )

    @staticmethod
    def _manifest_matches_scope(
        manifest: Dict[str, Any], scope: Optional[Dict[str, str]] = None
    ) -> bool:
        current_scope = scope or _resolve_current_database_scope()
        manifest_fingerprint = str(manifest.get("database_fingerprint") or "").strip()
        current_fingerprint = str(current_scope.get("database_fingerprint") or "").strip()
        if not current_fingerprint:
            return True
        if not manifest_fingerprint:
            # Hide legacy unscoped sessions by default. They are not safe to
            # expose after switching DATABASE_URL within the same checkout.
            return False
        return manifest_fingerprint == current_fingerprint

    @staticmethod
    def _manifest_matches_current_database(manifest: Dict[str, Any]) -> bool:
        return SnapshotManager._manifest_matches_scope(manifest)

    def _warn_if_legacy_unscoped_session_hidden(
        self, session_id: str, manifest: Dict[str, Any]
    ) -> None:
        current_scope = _resolve_current_database_scope()
        current_fingerprint = str(
            current_scope.get("database_fingerprint") or ""
        ).strip()
        manifest_fingerprint = str(manifest.get("database_fingerprint") or "").strip()
        if not current_fingerprint or manifest_fingerprint:
            return
        if session_id in self._warned_legacy_unscoped_sessions:
            return
        logger.warning(
            "Hiding legacy snapshot session without database_fingerprint under "
            "the current database scope: session_id=%s current_database=%s",
            session_id,
            current_scope.get("database_label") or "unknown",
        )
        self._warned_legacy_unscoped_sessions.add(session_id)

    def _manifest_visible_for_current_database(
        self, session_id: str, manifest: Dict[str, Any]
    ) -> bool:
        visible = self._manifest_matches_current_database(manifest)
        if not visible:
            self._warn_if_legacy_unscoped_session_hidden(session_id, manifest)
        return visible

    def _save_manifest(
        self,
        session_id: str,
        manifest: Dict[str, Any],
        *,
        session_dir: Optional[str] = None,
        scope: Optional[Dict[str, str]] = None,
    ):
        """Save session manifest."""
        resolved_scope = scope or _resolve_current_database_scope()
        resolved_session_dir = session_dir or self._resolve_session_dir(
            session_id, scope=resolved_scope
        )
        self._ensure_dir_exists(resolved_session_dir)
        manifest_path = self._get_manifest_path(
            session_id, session_dir=resolved_session_dir
        )
        manifest.setdefault(
            "database_fingerprint", resolved_scope["database_fingerprint"]
        )
        manifest.setdefault("database_label", resolved_scope["database_label"])

        _write_json_atomic(manifest_path, manifest)
        self._persist_scope_marker(
            session_id,
            manifest,
            session_dir=resolved_session_dir,
        )

    def _clear_session_unlocked(
        self,
        session_id: str,
        manifest: Optional[Dict[str, Any]] = None,
        *,
        session_dir: Optional[str] = None,
    ) -> int:
        """Delete one session tree while the caller already owns the write lock."""
        resolved_session_dir = session_dir or self._resolve_session_dir(session_id)
        if not os.path.exists(resolved_session_dir):
            return 0
        payload = (
            manifest
            if manifest is not None
            else self._load_manifest_from_dir(session_id, resolved_session_dir)
        )
        count = len(payload.get("resources", {}))
        _force_remove(resolved_session_dir)
        return count
    
    def has_snapshot(self, session_id: str, resource_id: str) -> bool:
        """Check if a snapshot exists for this resource in this session."""
        # Check manifest first (handles legacy snapshots with different filename formats)
        manifest = self._load_manifest(session_id)
        if resource_id in manifest.get("resources", {}):
            return True
        
        # Fallback to file existence check
        snapshot_path = self._get_snapshot_path(session_id, resource_id)
        return os.path.exists(snapshot_path)
    
    def find_memory_snapshot_by_uri(self, session_id: str, uri: str) -> Optional[str]:
        """
        Find an existing memory content snapshot for a given URI.
        
        When a memory is updated multiple times in one session, each update
        creates a new memory_id (version chain: id=1 → id=5 → id=12 → ...).
        The snapshot resource_id is "memory:{id}", so a naive has_snapshot()
        check on the new id misses the existing snapshot for the old id.
        
        This method scans the manifest for any "memory" type snapshot whose
        stored URI matches the given one, ensuring only ONE content snapshot
        per URI per session regardless of how many updates occur.
        
        Args:
            session_id: Session identifier
            uri: The memory URI (e.g. "core://foo/bar")
            
        Returns:
            The resource_id of the existing snapshot (e.g. "memory:1"),
            or None if no matching snapshot exists.
        """
        manifest = self._load_manifest(session_id)
        for resource_id, meta in manifest.get("resources", {}).items():
            if (meta.get("resource_type") == "memory"
                    and meta.get("uri") == uri):
                return resource_id
        return None
    
    def create_snapshot(
        self,
        session_id: str,
        resource_id: str,
        resource_type: str,
        snapshot_data: Dict[str, Any],
        force: bool = False
    ) -> bool:
        """
        Create a snapshot for a resource.
        
        IMPORTANT: This should be called BEFORE any modification.
        If a snapshot already exists for this resource in this session,
        this call is a no-op (returns False) unless force=True.
        
        Args:
            session_id: Unique session identifier
            resource_id: Resource identifier (e.g., memory URI)
            resource_type: Resource type (e.g., 'memory')
            snapshot_data: The complete resource state to snapshot
            force: If True, overwrite any existing snapshot for this resource.
                   Used by delete operations to ensure the final snapshot
                   reflects the delete rather than an earlier modify.
            
        Returns:
            True if snapshot was created, False if it already existed (and force=False)
        """
        with self._session_write_lock(session_id):
            current_scope = _resolve_current_database_scope()
            session_dir = self._resolve_session_dir(session_id, scope=current_scope)
            manifest = self._load_manifest_from_dir(
                session_id,
                session_dir,
                current_scope=current_scope,
            )
            if manifest.get("resources") and not self._manifest_matches_scope(
                manifest, current_scope
            ):
                manifest = self._build_manifest_payload(
                    session_id,
                    scope=current_scope,
                )
            snapshot_path = self._get_snapshot_path(
                session_id,
                resource_id,
                session_dir=session_dir,
            )
            if not force and (
                resource_id in manifest.get("resources", {}) or os.path.exists(snapshot_path)
            ):
                return False
            if (
                not force
                and resource_type == "memory"
                and isinstance(snapshot_data.get("uri"), str)
            ):
                for existing_id, meta in manifest.get("resources", {}).items():
                    if (
                        existing_id != resource_id
                        and meta.get("resource_type") == "memory"
                        and meta.get("uri") == snapshot_data.get("uri")
                    ):
                        return False

            self._ensure_dir_exists(
                self._get_resources_dir(session_id, session_dir=session_dir)
            )
            snapshot = {
                "resource_id": resource_id,
                "resource_type": resource_type,
                "snapshot_time": _utc_iso_now(),
                "data": snapshot_data,
            }
            previous_snapshot_existed = os.path.exists(snapshot_path)
            previous_snapshot_bytes: Optional[bytes] = None
            if previous_snapshot_existed:
                try:
                    with open(snapshot_path, "rb") as handle:
                        previous_snapshot_bytes = handle.read()
                except OSError:
                    logger.warning(
                        "Failed to read previous snapshot before force overwrite: %s",
                        snapshot_path,
                        exc_info=True,
                    )
            _write_json_atomic(snapshot_path, snapshot)

            manifest["resources"][resource_id] = {
                "resource_type": resource_type,
                "snapshot_time": snapshot["snapshot_time"],
                "operation_type": snapshot_data.get("operation_type", "modify"),
                "file": os.path.basename(snapshot_path),
                "uri": snapshot_data.get("uri"),
            }
            try:
                self._save_manifest(
                    session_id,
                    manifest,
                    session_dir=session_dir,
                    scope=current_scope,
                )
            except Exception:
                if previous_snapshot_bytes is not None:
                    try:
                        _write_bytes_atomic(snapshot_path, previous_snapshot_bytes)
                    except OSError:
                        logger.warning(
                            "Failed to restore previous snapshot after manifest save failure: %s",
                            snapshot_path,
                            exc_info=True,
                        )
                elif not previous_snapshot_existed:
                    try:
                        os.remove(snapshot_path)
                    except FileNotFoundError:
                        pass
                    except OSError:
                        logger.warning(
                            "Failed to remove snapshot resource after manifest save failure: %s",
                            snapshot_path,
                            exc_info=True,
                        )
                raise
            self._garbage_collect_sessions(current_session_id=session_id)
            return True
    
    def get_snapshot(self, session_id: str, resource_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a snapshot for a resource.
        
        Returns:
            The snapshot data, or None if not found
        """
        # First, check manifest for the actual filename (handles legacy snapshots)
        manifest = self._load_manifest(session_id)
        if not self._manifest_visible_for_current_database(session_id, manifest):
            return None
        resource_meta = manifest.get("resources", {}).get(resource_id)
        
        if resource_meta and resource_meta.get("file"):
            # Use the filename recorded in manifest
            snapshot_path = os.path.join(
                self._get_resources_dir(session_id), 
                resource_meta["file"]
            )
        else:
            # Fallback to computed path (for forward compatibility)
            snapshot_path = self._get_snapshot_path(session_id, resource_id)
        
        if not os.path.exists(snapshot_path):
            return None
        
        with open(snapshot_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        List all sessions with snapshots.
        
        Returns:
            List of session metadata (id, created_at, resource_count)
        """
        sessions = []
        
        if not os.path.exists(self.snapshot_dir):
            return sessions

        current_scope = _resolve_current_database_scope()
        current_fingerprint = self._scope_fingerprint(current_scope)
        seen_session_ids: set[str] = set()
        candidate_roots = [self.snapshot_dir]
        if current_fingerprint:
            candidate_roots.append(self._get_scoped_sessions_root(current_fingerprint))

        for root_dir in candidate_roots:
            if not os.path.isdir(root_dir):
                continue
            for session_id in os.listdir(root_dir):
                if session_id.startswith(".") or session_id in seen_session_ids:
                    continue
                try:
                    safe_session_id = self._validate_session_id(session_id)
                except ValueError:
                    logger.warning(
                        "Skipping invalid snapshot session directory: %s", session_id
                    )
                    continue
                session_dir = os.path.join(root_dir, safe_session_id)
                if not os.path.isdir(session_dir):
                    continue
                manifest = self._load_manifest_from_dir(
                    safe_session_id,
                    session_dir,
                    current_scope=current_scope,
                )
                if not self._manifest_matches_scope(manifest, current_scope):
                    self._warn_if_legacy_unscoped_session_hidden(
                        safe_session_id, manifest
                    )
                    continue
                resource_count = len(manifest.get("resources", {}))
                if resource_count == 0:
                    continue

                seen_session_ids.add(safe_session_id)
                sessions.append(
                    {
                        "session_id": safe_session_id,
                        "created_at": manifest.get("created_at"),
                        "resource_count": resource_count,
                    }
                )
        
        # Sort by creation time (newest first)
        sessions.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return sessions
    
    def list_snapshots(self, session_id: str) -> List[Dict[str, Any]]:
        """
        List all snapshots in a session.
        
        Returns:
            List of snapshot metadata (resource_id, resource_type, snapshot_time, operation_type)
        """
        manifest = self._load_manifest(session_id)
        if not self._manifest_visible_for_current_database(session_id, manifest):
            return []
        snapshots = []
        
        for resource_id, meta in manifest.get("resources", {}).items():
            snapshots.append({
                "resource_id": resource_id,
                "resource_type": meta.get("resource_type"),
                "snapshot_time": meta.get("snapshot_time"),
                "operation_type": meta.get("operation_type", "modify"),
                "uri": meta.get("uri")  # Display URI
            })
        
        return snapshots
    
    def delete_snapshot(self, session_id: str, resource_id: str) -> bool:
        """
        Delete a specific snapshot.
        
        Returns:
            True if deleted, False if not found
        """
        with self._session_write_lock(session_id):
            session_dir = self._resolve_session_dir(session_id)
            manifest = self._load_manifest_from_dir(session_id, session_dir)
            resource_meta = manifest.get("resources", {}).get(resource_id)

            if resource_meta and resource_meta.get("file"):
                snapshot_path = os.path.join(
                    self._get_resources_dir(session_id, session_dir=session_dir),
                    resource_meta["file"],
                )
            else:
                snapshot_path = self._get_snapshot_path(
                    session_id,
                    resource_id,
                    session_dir=session_dir,
                )

            resource_removed = False
            if resource_id in manifest.get("resources", {}):
                del manifest["resources"][resource_id]
                resource_removed = True
                if not manifest["resources"]:
                    self._clear_session_unlocked(
                        session_id,
                        manifest,
                        session_dir=session_dir,
                    )
                else:
                    self._save_manifest(
                        session_id,
                        manifest,
                        session_dir=session_dir,
                    )

            if not os.path.exists(snapshot_path):
                if resource_removed:
                    return True
                return False

            if os.path.exists(snapshot_path):
                _force_remove(snapshot_path)

            return True
    
    def clear_session(self, session_id: str) -> int:
        """
        Delete all snapshots in a session.
        
        Returns:
            Number of snapshots deleted
        """
        with self._session_write_lock(session_id):
            return self._clear_session_unlocked(session_id)


# Global singleton
_snapshot_manager: Optional[SnapshotManager] = None
_snapshot_manager_lock = threading.Lock()


def get_snapshot_manager() -> SnapshotManager:
    """Get the global SnapshotManager instance."""
    global _snapshot_manager
    if _snapshot_manager is None:
        with _snapshot_manager_lock:
            if _snapshot_manager is None:
                _snapshot_manager = SnapshotManager()
    return _snapshot_manager
