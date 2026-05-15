"""
Review API - Selective Rollback for Database Changes (SQLite Backend)

This module provides endpoints for the human to review and selectively rollback
the AI's database modifications.

Design Philosophy:
- Snapshots are split into two dimensions matching the DB tables:
  * PATH snapshots (resource_type="path"): track path creation/deletion/metadata changes
  * MEMORY snapshots (resource_type="memory"): track content changes
- This separation allows independent rollback of path vs content changes
- Old versions are marked deprecated for review
- The human can permanently delete deprecated memories after review
"""
import difflib
import inspect
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException

from models import (
    DiffRequest, DiffResponse,
    SessionInfo, SnapshotInfo, SnapshotDetail, ResourceDiff,
    RollbackRequest, RollbackResponse
)
from .utils import get_text_diff
from .maintenance import require_maintenance_api_key
from ._write_lane import run_write_lane as _run_api_write_lane
from db.snapshot import SnapshotManager, get_snapshot_manager
from db.sqlite_client import get_sqlite_client
from shared_utils import env_bool as _env_bool

router = APIRouter(
    prefix="/review",
    tags=["review"],
    dependencies=[Depends(require_maintenance_api_key)],
)

_VERSION_CHAIN_MAX_HOPS = 64
_ENABLE_WRITE_LANE_QUEUE = _env_bool("RUNTIME_WRITE_LANE_QUEUE", True)
_PERMANENTLY_DELETED_OLD_CONTENT_PLACEHOLDER = (
    "[Permanently deleted, old content unavailable]"
)


async def _run_write_lane(
    operation: str,
    task: Callable[[], Awaitable[Any]],
    *,
    session_id: Optional[str] = None,
) -> Any:
    resolved_session_id = str(session_id or "").strip() or f"review.{operation}"
    return await _run_api_write_lane(
        f"review.{operation}",
        task,
        enabled=_ENABLE_WRITE_LANE_QUEUE,
        session_id=resolved_session_id,
    )


def _format_permanently_deleted_detail(
    memory_id: Any,
    *,
    action: str,
    uri: Optional[str] = None,
) -> str:
    target_suffix = f" '{uri}'" if uri else ""
    return (
        f"Old version (memory_id={memory_id}) was permanently deleted. "
        f"Cannot {action}{target_suffix}."
    )


def _validate_session_id_or_400(session_id: str) -> str:
    try:
        return SnapshotManager._validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid session_id: {exc}.") from exc


def _raise_review_internal_error(*, operation: str, error: str, exc: Exception) -> None:
    raise HTTPException(
        status_code=500,
        detail={
            "error": error,
            "reason": "internal_error",
            "operation": operation,
        },
    ) from exc


def _parse_snapshot_time(value: Any) -> Optional[datetime]:
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _get_snapshot_exact_or_decoded(
    manager: Any,
    session_id: str,
    resource_id: str,
) -> tuple[str, Optional[Dict[str, Any]]]:
    snapshot = manager.get_snapshot(session_id, resource_id)
    if snapshot:
        return resource_id, snapshot

    decoded_resource_id = unquote(resource_id)
    if decoded_resource_id != resource_id:
        snapshot = manager.get_snapshot(session_id, decoded_resource_id)
        if snapshot:
            return decoded_resource_id, snapshot

    return resource_id, None


def _find_newer_memory_snapshot_conflict(
    *,
    manager: Any,
    baseline_session_id: str,
    snapshot: Dict[str, Any],
) -> Optional[Dict[str, str]]:
    data = snapshot.get("data") if isinstance(snapshot.get("data"), dict) else {}
    uri = str(data.get("uri") or "").strip()
    baseline_snapshot_time = _parse_snapshot_time(snapshot.get("snapshot_time"))
    if not uri or baseline_snapshot_time is None:
        return None

    for session in manager.list_sessions():
        other_session_id = str(session.get("session_id") or "").strip()
        if not other_session_id or other_session_id == baseline_session_id:
            continue
        for candidate in manager.list_snapshots(other_session_id):
            if str(candidate.get("resource_type") or "").strip() != "memory":
                continue
            if str(candidate.get("uri") or "").strip() != uri:
                continue
            candidate_snapshot_time = _parse_snapshot_time(
                candidate.get("snapshot_time")
            )
            if (
                candidate_snapshot_time is None
                or candidate_snapshot_time <= baseline_snapshot_time
            ):
                continue
            return {
                "session_id": other_session_id,
                "snapshot_time": str(candidate.get("snapshot_time") or "").strip(),
            }
    return None


def _raise_if_newer_review_snapshot_exists(
    *,
    manager: Any,
    session_id: str,
    snapshot: Dict[str, Any],
) -> None:
    conflict = _find_newer_memory_snapshot_conflict(
        manager=manager,
        baseline_session_id=session_id,
        snapshot=snapshot,
    )
    if not conflict:
        return

    data = snapshot.get("data") if isinstance(snapshot.get("data"), dict) else {}
    uri = str(data.get("uri") or "").strip() or "unknown"
    raise HTTPException(
        status_code=409,
        detail=(
            f"Cannot rollback '{uri}': newer review snapshot exists in session "
            f"'{conflict['session_id']}' at {conflict['snapshot_time']}."
        ),
    )


# ========== Session & Snapshot Endpoints ==========

@router.get("/sessions", response_model=List[SessionInfo])
async def list_sessions():
    """
    List all sessions that currently have snapshots.

    Each MCP server runtime instance is treated as one session.
    Session IDs look like: mcp_YYYYMMDD_HHMMSS_{random}
    """
    manager = get_snapshot_manager()
    sessions = manager.list_sessions()
    return [SessionInfo(**s) for s in sessions]


@router.get("/sessions/{session_id}/snapshots", response_model=List[SnapshotInfo])
async def list_session_snapshots(session_id: str):
    """
    List all snapshots recorded for one session.

    Returns snapshot metadata for each modified resource.
    """
    session_id = _validate_session_id_or_400(session_id)
    manager = get_snapshot_manager()
    snapshots = manager.list_snapshots(session_id)
    
    if not snapshots:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found or has no snapshots"
        )
    
    return [SnapshotInfo(**s) for s in snapshots]


@router.get("/sessions/{session_id}/snapshots/{resource_id:path}", response_model=SnapshotDetail)
async def get_snapshot_detail(session_id: str, resource_id: str):
    """
    Return the full payload for one snapshot.

    Example resource_id values:
    - Memory path: "memory-palace", "memory-palace/salem"
    """
    session_id = _validate_session_id_or_400(session_id)
    
    manager = get_snapshot_manager()
    resource_id, snapshot = _get_snapshot_exact_or_decoded(
        manager,
        session_id,
        resource_id,
    )
    
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot for '{resource_id}' not found in session '{session_id}'"
        )
    
    return SnapshotDetail(
        resource_id=snapshot["resource_id"],
        resource_type=snapshot["resource_type"],
        snapshot_time=snapshot["snapshot_time"],
        data=snapshot["data"]
    )


# ========== Diff Helpers ==========

def _compute_diff(old_content: str, new_content: str) -> tuple:
    """
    Compute a textual diff and return ``(unified_diff, summary)``.
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    
    diff = difflib.unified_diff(old_lines, new_lines, fromfile='snapshot', tofile='current')
    unified = ''.join(diff)
    
    additions = sum(1 for line in unified.splitlines() if line.startswith('+') and not line.startswith('+++'))
    deletions = sum(1 for line in unified.splitlines() if line.startswith('-') and not line.startswith('---'))
    
    if additions == 0 and deletions == 0:
        summary = "No changes"
    else:
        summary = f"+{additions} / -{deletions} lines"
    
    return unified, summary


async def _get_memory_by_path_from_data(data: dict):
    """Helper: fetch current memory via path/domain stored in snapshot data."""
    client = get_sqlite_client()
    path = data.get("path")
    domain = data.get("domain", "core")
    if not path:
        return None
    return await client.get_memory_by_path(path, domain)


async def _resolve_chain_tip_memory_id(
    client: Any,
    memory_id: int,
    *,
    max_hops: int = _VERSION_CHAIN_MAX_HOPS,
) -> Optional[int]:
    """Follow migrated_to pointers and return the final memory id in the chain."""
    current_id = int(memory_id)
    visited: set[int] = set()
    for _ in range(max_hops):
        if current_id in visited:
            return None
        visited.add(current_id)
        version = await client.get_memory_version(current_id)
        if not version:
            return None
        migrated_to = version.get("migrated_to")
        if migrated_to is None:
            return current_id
        try:
            current_id = int(migrated_to)
        except (TypeError, ValueError):
            return None
    return None


async def _ensure_same_version_chain_or_409(
    client: Any,
    *,
    snapshot_memory_id: int,
    current_memory_id: int,
    uri: str,
) -> None:
    if snapshot_memory_id == current_memory_id:
        return

    snapshot_tip = await _resolve_chain_tip_memory_id(client, snapshot_memory_id)
    current_tip = await _resolve_chain_tip_memory_id(client, current_memory_id)
    if snapshot_tip is None or current_tip is None or snapshot_tip != current_tip:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot rollback '{uri}': snapshot memory_id={snapshot_memory_id} "
                f"and current memory_id={current_memory_id} are not in the same version chain."
            ),
        )


def _supports_expected_current_memory_id(client: Any) -> bool:
    rollback_to_memory = getattr(client, "rollback_to_memory", None)
    if not callable(rollback_to_memory):
        return False
    try:
        return (
            "expected_current_memory_id"
            in inspect.signature(rollback_to_memory).parameters
        )
    except (TypeError, ValueError):
        return False


def _callable_supports_parameter(callable_obj: Any, parameter_name: str) -> bool:
    if not callable(callable_obj):
        return False
    try:
        return parameter_name in inspect.signature(callable_obj).parameters
    except (TypeError, ValueError):
        return False


def _restore_path_metadata_kwargs(client: Any, current: dict) -> Dict[str, Any]:
    restore_path_metadata = getattr(client, "restore_path_metadata", None)
    kwargs: Dict[str, Any] = {}
    current_memory_id = current.get("id")
    if (
        isinstance(current_memory_id, int)
        and _callable_supports_parameter(
            restore_path_metadata, "expected_current_memory_id"
        )
    ):
        kwargs["expected_current_memory_id"] = current_memory_id
    if _callable_supports_parameter(
        restore_path_metadata, "expected_current_priority"
    ):
        kwargs["expected_current_priority"] = current.get("priority")
    if _callable_supports_parameter(
        restore_path_metadata, "expected_current_disclosure"
    ):
        kwargs["expected_current_disclosure"] = current.get("disclosure")
    return kwargs


def _map_restore_path_metadata_value_error(exc: ValueError, uri: str) -> HTTPException:
    detail = f"Cannot rollback '{uri}': {exc}"
    if "not found" in str(exc).lower():
        return HTTPException(status_code=404, detail=detail)
    return HTTPException(status_code=409, detail=detail)


# ========== Diff: PATH snapshots ==========

async def _diff_path_create(snapshot: dict, resource_id: str) -> dict:
    """Diff for path creation (create_memory). Rollback = delete memory + path."""
    snapshot_data = {"content": None, "priority": None, "disclosure": None}
    current_memory = await _get_memory_by_path_from_data(snapshot["data"])
    
    if not current_memory:
        current_data = {"content": "[DELETED]", "priority": None, "disclosure": None}
        summary = "Created then deleted"
        has_changes = False
    else:
        current_data = {
            "content": current_memory.get("content", ""),
            "priority": current_memory.get("priority"),
            "disclosure": current_memory.get("disclosure")
        }
        line_count = len(current_data["content"].splitlines())
        summary = f"Created: +{line_count} lines (rollback = delete)"
        has_changes = True
    
    unified = f"--- /dev/null\n+++ {resource_id}\n"
    if current_data["content"] and current_data["content"] != "[DELETED]":
        for line in current_data["content"].splitlines():
            unified += f"+{line}\n"
    
    return {"snapshot_data": snapshot_data, "current_data": current_data,
            "unified": unified, "summary": summary, "has_changes": has_changes}


async def _diff_path_create_alias(snapshot: dict, resource_id: str) -> dict:
    """Diff for alias creation. Rollback = remove alias path only."""
    target_uri = snapshot["data"].get("target_uri", "unknown")
    snapshot_data = {"content": None, "priority": None, "disclosure": None}
    
    current_memory = await _get_memory_by_path_from_data(snapshot["data"])
    
    if not current_memory:
        current_data = {"content": "[ALIAS REMOVED]", "priority": None, "disclosure": None}
        summary = "Alias created then removed"
        has_changes = False
    else:
        current_data = {
            "content": current_memory.get("content", ""),
            "priority": current_memory.get("priority"),
            "disclosure": current_memory.get("disclosure")
        }
        summary = f"Alias created → {target_uri} (rollback = remove alias)"
        has_changes = True
    
    unified = f"--- /dev/null\n+++ {resource_id} (alias → {target_uri})\n"
    if current_data["content"] and current_data["content"] != "[ALIAS REMOVED]":
        unified += f"+[Alias pointing to: {target_uri}]\n"
    
    return {"snapshot_data": snapshot_data, "current_data": current_data,
            "unified": unified, "summary": summary, "has_changes": has_changes}


async def _get_surviving_paths(
    client: Any,
    memory_id: int,
    *,
    max_hops: int = _VERSION_CHAIN_MAX_HOPS,
) -> list:
    """Follow the version chain from memory_id to the latest version,
    then return all living paths pointing to that memory.
    
    This lets the human see whether a deleted path was just an alias
    or the last remaining route to the memory content.
    """
    if not memory_id:
        return []

    lookup_memory_id = await _resolve_chain_tip_memory_id(
        client,
        memory_id,
        max_hops=max_hops,
    )
    if lookup_memory_id is None:
        lookup_memory_id = int(memory_id)

    latest = await client.get_memory_version(lookup_memory_id)
    if latest:
        return latest.get("paths", [])

    original = await client.get_memory_version(memory_id)
    return original.get("paths", []) if original else []


async def _diff_path_delete(snapshot: dict, resource_id: str) -> dict:
    """Diff for path deletion. Rollback = restore path.
    
    Old content is fetched from DB via memory_id rather than from the
    snapshot file, leveraging the version chain.
    Also includes surviving paths so the human can tell if this is just
    an alias removal or if the entire memory is being discarded.
    """
    client = get_sqlite_client()
    
    # --- Retrieve old content from DB ---
    old_memory_id = snapshot["data"].get("memory_id")
    old_version = await client.get_memory_version(old_memory_id) if old_memory_id else None
    
    if old_version:
        old_content = old_version.get("content", "")
    else:
        old_content = _PERMANENTLY_DELETED_OLD_CONTENT_PLACEHOLDER
    
    snapshot_data = {
        "content": old_content,
        "priority": snapshot["data"].get("priority", snapshot["data"].get("importance")),
        "disclosure": snapshot["data"].get("disclosure")
    }
    
    current_memory = await _get_memory_by_path_from_data(snapshot["data"])
    
    if not current_memory:
        current_data = {"content": "[DELETED]", "priority": None, "disclosure": None}
    else:
        current_data = {
            "content": current_memory.get("content", ""),
            "priority": current_memory.get("priority"),
            "disclosure": current_memory.get("disclosure")
        }
    
    # --- Find surviving paths for this memory ---
    surviving_paths = await _get_surviving_paths(client, old_memory_id)
    # Exclude the deleted path itself from the list
    deleted_uri = snapshot["data"].get("uri") or f"{snapshot['data'].get('domain', 'core')}://{snapshot['data'].get('path')}"
    surviving_paths = [p for p in surviving_paths if p != deleted_uri]
    
    unified, summary = _compute_diff(snapshot_data["content"], current_data["content"])
    
    if current_data["content"] == "[DELETED]":
        summary = "Deleted (rollback = restore)"
    
    current_data["surviving_paths"] = surviving_paths
    
    return {"snapshot_data": snapshot_data, "current_data": current_data,
            "unified": unified, "summary": summary, "has_changes": True}


async def _diff_path_modify_meta(snapshot: dict, resource_id: str) -> dict:
    """Diff for path metadata change (priority/disclosure). Rollback = restore metadata."""
    snapshot_data = {
        "content": None,
        "priority": snapshot["data"].get("priority", snapshot["data"].get("importance")),
        "disclosure": snapshot["data"].get("disclosure")
    }
    
    current_memory = await _get_memory_by_path_from_data(snapshot["data"])
    
    if not current_memory:
        current_data = {"content": None, "priority": None, "disclosure": None}
        summary = "Path no longer exists"
        has_changes = False
    else:
        current_data = {
            "content": None,
            "priority": current_memory.get("priority"),
            "disclosure": current_memory.get("disclosure")
        }
        
        meta_changes = []
        for key in ["priority", "disclosure"]:
            if snapshot_data.get(key) != current_data.get(key):
                meta_changes.append(f"{key}: {snapshot_data.get(key)} → {current_data.get(key)}")
        
        if meta_changes:
            summary = "Metadata: " + ", ".join(meta_changes)
            has_changes = True
        else:
            summary = "No metadata changes"
            has_changes = False
    
    return {"snapshot_data": snapshot_data, "current_data": current_data,
            "unified": "", "summary": summary, "has_changes": has_changes}


# ========== Diff: MEMORY snapshots ==========

async def _diff_memory_content(snapshot: dict, resource_id: str) -> dict:
    """Diff for memory content change. Rollback = rollback_to_memory.
    
    Old content is fetched from DB via memory_id (the deprecated Memory row
    is preserved by the version chain).  If the old row was permanently
    deleted, a fallback message is shown instead.
    """
    client = get_sqlite_client()
    
    # --- Retrieve old content from DB instead of snapshot file ---
    old_memory_id = snapshot["data"].get("memory_id")
    old_version = await client.get_memory_version(old_memory_id) if old_memory_id else None
    
    if old_version:
        old_content = old_version.get("content", "")
    else:
        old_content = _PERMANENTLY_DELETED_OLD_CONTENT_PLACEHOLDER
    
    snapshot_data = {
        "content": old_content,
        "priority": None,
        "disclosure": None
    }
    
    # --- Retrieve current content via path (with alias fallback) ---
    current_memory = await _get_memory_by_path_from_data(snapshot["data"])
    
    if not current_memory:
        for alt_uri_str in snapshot["data"].get("all_paths", []):
            if "://" in alt_uri_str:
                alt_domain, alt_path = alt_uri_str.split("://", 1)
            else:
                alt_domain, alt_path = "core", alt_uri_str
            orig_path = snapshot["data"].get("path")
            orig_domain = snapshot["data"].get("domain", "core")
            if alt_path == orig_path and alt_domain == orig_domain:
                continue
            current_memory = await client.get_memory_by_path(alt_path, alt_domain)
            if current_memory:
                break
    
    if not current_memory:
        current_data = {"content": "[PATH DELETED]", "priority": None, "disclosure": None}
    else:
        current_data = {
            "content": current_memory.get("content", ""),
            "priority": None,
            "disclosure": None
        }
    
    unified, summary = _compute_diff(snapshot_data["content"], current_data.get("content", ""))
    has_changes = snapshot_data["content"] != current_data.get("content", "")
    
    return {"snapshot_data": snapshot_data, "current_data": current_data,
            "unified": unified, "summary": summary, "has_changes": has_changes}


# ========== Diff Endpoint ==========

# Dispatch table: (resource_type, operation_type) → diff handler
_DIFF_HANDLERS = {
    ("path", "create"):       _diff_path_create,
    ("path", "create_alias"): _diff_path_create_alias,
    ("path", "delete"):       _diff_path_delete,
    ("path", "modify_meta"):  _diff_path_modify_meta,
    ("memory", "modify_content"): _diff_memory_content,
}

# Legacy compatibility: old snapshots used resource_type="memory" for everything
_LEGACY_DIFF_HANDLERS = {
    "create":       _diff_path_create,
    "create_alias": _diff_path_create_alias,
    "delete":       _diff_path_delete,
    "modify":       _diff_memory_content,  # Old "modify" = content change
}


@router.get("/sessions/{session_id}/diff/{resource_id:path}", response_model=ResourceDiff)
async def get_resource_diff(session_id: str, resource_id: str):
    """
    Compare a snapshot against the current resource state.

    Handles both new split snapshots (path/memory) and legacy snapshots.
    """
    session_id = _validate_session_id_or_400(session_id)
    
    manager = get_snapshot_manager()
    resource_id, snapshot = _get_snapshot_exact_or_decoded(
        manager,
        session_id,
        resource_id,
    )
    
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot for '{resource_id}' not found in session '{session_id}'"
        )
    
    resource_type = snapshot["resource_type"]
    operation_type = snapshot["data"].get("operation_type", "modify")
    
    # Try new dispatch table first, then legacy fallback
    handler = _DIFF_HANDLERS.get((resource_type, operation_type))
    if not handler:
        handler = _LEGACY_DIFF_HANDLERS.get(operation_type)
    if not handler:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown snapshot type: {resource_type}/{operation_type}"
        )
    
    result = await handler(snapshot, resource_id)
    
    return ResourceDiff(
        resource_id=resource_id,
        resource_type=resource_type,
        snapshot_time=snapshot["snapshot_time"],
        snapshot_data=result["snapshot_data"],
        current_data=result["current_data"],
        diff_unified=result["unified"],
        diff_summary=result["summary"],
        has_changes=result["has_changes"]
    )


# ========== Rollback Helpers ==========

async def _rollback_path(data: dict, *, lane_session_id: Optional[str] = None) -> dict:
    """Rollback a path-level operation."""
    client = get_sqlite_client()
    path = data.get("path")
    domain = data.get("domain", "core")
    operation_type = data.get("operation_type")
    uri = data.get("uri", f"{domain}://{path}")
    
    if operation_type == "create":
        snapshot_memory_id_raw = data.get("memory_id")
        snapshot_memory_id: Optional[int] = None
        if snapshot_memory_id_raw is not None:
            try:
                snapshot_memory_id = int(snapshot_memory_id_raw)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid snapshot memory_id for '{uri}'.",
                )
        current_for_validation = await client.get_memory_by_path(
            path, domain, reinforce_access=False
        )
        if snapshot_memory_id is not None and current_for_validation:
            current_memory_id = current_for_validation.get("id")
            if (
                isinstance(current_memory_id, int)
                and current_memory_id != snapshot_memory_id
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Cannot rollback create for '{uri}': snapshot memory_id="
                        f"{snapshot_memory_id} does not match current memory_id="
                        f"{current_memory_id}."
                    ),
                )

        # Rollback of create = delete the memory/path and any later descendants.
        # Descendants must be removed first to avoid leaving dangling child paths.
        descendant_targets: List[Tuple[str, str, Optional[int]]] = []

        if path:
            # Descendants may be created under any alias path that points to the same
            # memory node, so we must scan across domains before deleting the root node.
            all_paths = await client.get_all_paths(domain=None)
            current = await client.get_memory_by_path(
                path, domain, reinforce_access=False
            )
            current_memory_id = current.get("id") if isinstance(current, dict) else None

            root_aliases: set[tuple[str, str]] = set()
            if isinstance(current_memory_id, int) and current_memory_id > 0:
                for item in all_paths:
                    try:
                        item_memory_id = int(item.get("memory_id"))
                    except (TypeError, ValueError):
                        continue
                    if item_memory_id != current_memory_id:
                        continue
                    alias_domain = str(item.get("domain") or "").strip()
                    alias_path = str(item.get("path") or "").strip()
                    if alias_domain and alias_path:
                        root_aliases.add((alias_domain, alias_path))

            if not root_aliases:
                root_aliases.add((str(domain or "core"), str(path)))

            descendants_map: Dict[str, Dict[str, Any]] = {}
            for alias_domain, alias_path in root_aliases:
                descendant_prefix = f"{alias_path}/"
                for item in all_paths:
                    item_domain = str(item.get("domain") or "").strip()
                    item_path = str(item.get("path") or "").strip()
                    if item_domain != alias_domain:
                        continue
                    if not item_path.startswith(descendant_prefix):
                        continue
                    descendants_map[f"{item_domain}://{item_path}"] = item

            descendants = list(descendants_map.values())
            descendants.sort(
                key=lambda item: (
                    str(item.get("path") or "").count("/"),
                    str(item.get("domain") or ""),
                    str(item.get("path") or ""),
                ),
                reverse=True,
            )

            for item in descendants:
                child_domain = str(item.get("domain") or "").strip()
                child_path = str(item.get("path") or "").strip()
                if (
                    not child_path
                    or not child_domain
                    or (child_domain, child_path) in root_aliases
                ):
                    continue
                child_memory_id = item.get("memory_id")
                parsed_memory_id: Optional[int] = None
                try:
                    parsed_candidate = int(child_memory_id)
                    if parsed_candidate > 0:
                        parsed_memory_id = parsed_candidate
                except (TypeError, ValueError):
                    parsed_memory_id = None
                descendant_targets.append((child_domain, child_path, parsed_memory_id))

        async def _write_task_delete_create_tree() -> Dict[str, Any]:
            return await client.delete_created_tree_atomically(
                root_path=path,
                root_domain=domain,
                descendant_targets=descendant_targets,
                expected_current_memory_id=snapshot_memory_id,
            )

        try:
            return await _run_write_lane(
                "rollback.delete_create_tree",
                _write_task_delete_create_tree,
                session_id=lane_session_id,
            )
        except (ValueError, PermissionError, RuntimeError) as e:
            raise HTTPException(status_code=409, detail=f"Cannot delete '{uri}': {e}")
    
    elif operation_type == "create_alias":
        # Rollback of alias creation = remove the alias path only
        try:
            existing_alias = await client.get_memory_by_path(
                path, domain, reinforce_access=False
            )
            snapshot_memory_id = data.get("memory_id")
            if (
                existing_alias is not None
                and snapshot_memory_id is not None
                and existing_alias.get("id") != snapshot_memory_id
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Cannot rollback alias '{uri}': "
                        "it now points to a different memory."
                    ),
                )

            async def _before_delete_alias(current_deleted: Dict[str, Any]) -> None:
                if (
                    snapshot_memory_id is not None
                    and current_deleted.get("id") != snapshot_memory_id
                ):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Cannot rollback alias '{uri}': "
                            "it now points to a different memory."
                        ),
                    )

            async def _write_task_remove_alias() -> Any:
                delete_path_atomically = getattr(client, "delete_path_atomically", None)
                if callable(delete_path_atomically):
                    return await delete_path_atomically(
                        path,
                        domain,
                        before_delete=_before_delete_alias,
                    )
                return await client.remove_path(path, domain)

            await _run_write_lane(
                "rollback.remove_alias",
                _write_task_remove_alias,
                session_id=lane_session_id,
            )
        except HTTPException:
            raise
        except ValueError as exc:
            existing_alias = await client.get_memory_by_path(
                path, domain, reinforce_access=False
            )
            if existing_alias is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot rollback alias '{uri}': {exc}",
                ) from exc
            return {"deleted": True, "alias_removed": False, "no_change": True}
        return {"deleted": True, "alias_removed": True}
    
    elif operation_type == "delete":
        # Rollback of delete = restore the path
        memory_id = data.get("memory_id")
        
        # Verify the target memory still exists in DB
        target_version = await client.get_memory_version(memory_id) if memory_id else None
        if not target_version:
            raise HTTPException(
                status_code=410,
                detail=_format_permanently_deleted_detail(
                    memory_id,
                    action="restore",
                    uri=uri,
                ),
            )
        
        try:
            async def _write_task_restore_path() -> Any:
                return await client.restore_path(
                    path=path,
                    domain=domain,
                    memory_id=memory_id,
                    priority=data.get("priority", data.get("importance", 0)),
                    disclosure=data.get("disclosure"),
                )

            await _run_write_lane(
                "rollback.restore_path",
                _write_task_restore_path,
                session_id=lane_session_id,
            )
            return {"restored": True, "new_version": memory_id}
        except ValueError as e:
            raise HTTPException(status_code=409, detail=f"Cannot restore '{uri}': {e}")
    
    elif operation_type == "modify_meta":
        # Rollback of metadata change = restore original priority/disclosure
        current = await client.get_memory_by_path(
            path, domain, reinforce_access=False
        )
        if not current:
            raise HTTPException(status_code=404, detail=f"'{uri}' no longer exists")

        async def _write_task_update_meta() -> Any:
            return await client.restore_path_metadata(
                path=path,
                domain=domain,
                priority=data.get("priority", data.get("importance", 0)),
                disclosure=data.get("disclosure"),
                **_restore_path_metadata_kwargs(client, current),
            )

        try:
            await _run_write_lane(
                "rollback.update_meta",
                _write_task_update_meta,
                session_id=lane_session_id,
            )
        except ValueError as exc:
            raise _map_restore_path_metadata_value_error(exc, uri) from exc
        return {"metadata_restored": True}
    
    else:
        raise HTTPException(status_code=400, detail=f"Unknown path operation: {operation_type}")


async def _rollback_memory_content(
    data: dict,
    *,
    lane_session_id: Optional[str] = None,
    newer_snapshot_guard: Optional[Callable[[], None]] = None,
) -> dict:
    """Rollback a memory content change."""
    client = get_sqlite_client()
    memory_id_raw = data.get("memory_id")
    try:
        memory_id = int(memory_id_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Snapshot missing memory_id")
    path = data.get("path")
    domain = data.get("domain", "core")
    uri = data.get("uri", f"{domain}://{path}")
    
    if memory_id <= 0:
        raise HTTPException(status_code=400, detail="Snapshot missing memory_id")
    
    # Verify the target memory still exists in DB (not permanently deleted)
    target_version = await client.get_memory_version(memory_id)
    if not target_version:
        raise HTTPException(
            status_code=410,
            detail=_format_permanently_deleted_detail(
                memory_id,
                action="roll back",
            ),
        )
    
    current = await client.get_memory_by_path(
        path, domain, reinforce_access=False
    )
    
    # Fallback: if original path was deleted, try alternative paths from snapshot
    if not current:
        for alt_uri_str in data.get("all_paths", []):
            if "://" in alt_uri_str:
                alt_domain, alt_path = alt_uri_str.split("://", 1)
            else:
                alt_domain, alt_path = "core", alt_uri_str
            if alt_path == path and alt_domain == domain:
                continue  # Skip the one we already tried
            current = await client.get_memory_by_path(
                alt_path, alt_domain, reinforce_access=False
            )
            if current:
                path, domain = alt_path, alt_domain
                break
    
    if not current:
        raise HTTPException(
            status_code=404,
            detail=f"Path '{uri}' no longer exists and no alternative paths found. Cannot rollback content."
        )

    current_memory_id = current.get("id")
    if not isinstance(current_memory_id, int):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot rollback '{uri}': current memory_id is invalid.",
        )

    if memory_id == current_memory_id:
        if newer_snapshot_guard is not None:
            newer_snapshot_guard()
        return {"no_change": True, "new_version": memory_id}

    await _ensure_same_version_chain_or_409(
        client,
        snapshot_memory_id=memory_id,
        current_memory_id=current_memory_id,
        uri=uri,
    )

    async def _write_task_rollback_to_memory() -> Any:
        if newer_snapshot_guard is not None:
            newer_snapshot_guard()
        kwargs: Dict[str, Any] = {}
        if _supports_expected_current_memory_id(client):
            kwargs["expected_current_memory_id"] = current_memory_id
        return await client.rollback_to_memory(
            path,
            memory_id,
            domain,
            **kwargs,
        )

    try:
        result = await _run_write_lane(
            "rollback.rollback_to_memory",
            _write_task_rollback_to_memory,
            session_id=lane_session_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot rollback '{uri}': {exc}",
        ) from exc
    return {"new_version": result["restored_memory_id"]}


async def _rollback_legacy_modify(
    data: dict,
    *,
    lane_session_id: Optional[str] = None,
    newer_snapshot_guard: Optional[Callable[[], None]] = None,
) -> dict:
    """Rollback for legacy 'modify' snapshots that combined content + metadata."""
    client = get_sqlite_client()
    path = data.get("path")
    domain = data.get("domain", "core")
    uri = data.get("uri", f"{domain}://{path}")
    snapshot_memory_id_raw = data.get("memory_id")
    try:
        snapshot_memory_id = int(snapshot_memory_id_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Snapshot missing memory_id")
    
    if snapshot_memory_id <= 0:
        raise HTTPException(status_code=400, detail="Snapshot missing memory_id")
    
    # Verify the target memory still exists in DB
    target_version = await client.get_memory_version(snapshot_memory_id)
    if not target_version:
        raise HTTPException(
            status_code=410,
            detail=_format_permanently_deleted_detail(
                snapshot_memory_id,
                action="roll back",
            ),
        )
    
    current = await client.get_memory_by_path(
        path, domain, reinforce_access=False
    )
    if not current:
        raise HTTPException(status_code=404, detail=f"'{uri}' no longer exists")

    current_memory_id = current.get("id")
    if not isinstance(current_memory_id, int):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot rollback '{uri}': current memory_id is invalid.",
        )

    await _ensure_same_version_chain_or_409(
        client,
        snapshot_memory_id=snapshot_memory_id,
        current_memory_id=current_memory_id,
        uri=uri,
    )
    
    snapshot_priority = data.get("priority", data.get("importance"))
    snapshot_disclosure = data.get("disclosure")
    has_version_change = snapshot_memory_id != current_memory_id
    has_meta_change = (
        snapshot_priority != current.get("priority") or
        snapshot_disclosure != current.get("disclosure")
    )

    if not has_version_change and not has_meta_change:
        if newer_snapshot_guard is not None:
            newer_snapshot_guard()
        return {"no_change": True, "new_version": current.get("id")}
    
    restored_id = current.get("id")
    
    if has_version_change and has_meta_change:
        async def _write_task_restore_legacy_modify() -> Any:
            if newer_snapshot_guard is not None:
                newer_snapshot_guard()
            kwargs: Dict[str, Any] = {}
            if _supports_expected_current_memory_id(client):
                kwargs["expected_current_memory_id"] = current_memory_id
            return await client.rollback_to_memory(
                path,
                snapshot_memory_id,
                domain,
                restore_path_metadata=True,
                restore_priority=snapshot_priority,
                restore_disclosure=snapshot_disclosure,
                **kwargs,
            )

        try:
            result = await _run_write_lane(
                "rollback.restore_legacy_modify",
                _write_task_restore_legacy_modify,
                session_id=lane_session_id,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot rollback '{uri}': {exc}",
            ) from exc
        restored_id = result["restored_memory_id"]
    elif has_version_change:
        async def _write_task_rollback_to_memory() -> Any:
            if newer_snapshot_guard is not None:
                newer_snapshot_guard()
            kwargs: Dict[str, Any] = {}
            if _supports_expected_current_memory_id(client):
                kwargs["expected_current_memory_id"] = current_memory_id
            return await client.rollback_to_memory(
                path,
                snapshot_memory_id,
                domain,
                **kwargs,
            )

        try:
            result = await _run_write_lane(
                "rollback.rollback_to_memory",
                _write_task_rollback_to_memory,
                session_id=lane_session_id,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot rollback '{uri}': {exc}",
            ) from exc
        restored_id = result["restored_memory_id"]
    
    if has_meta_change and not has_version_change:
        async def _write_task_update_legacy_meta() -> Any:
            if newer_snapshot_guard is not None:
                newer_snapshot_guard()
            return await client.restore_path_metadata(
                path=path,
                domain=domain,
                priority=snapshot_priority if snapshot_priority is not None else 0,
                disclosure=snapshot_disclosure,
                **_restore_path_metadata_kwargs(client, current),
            )

        try:
            await _run_write_lane(
                "rollback.update_meta",
                _write_task_update_legacy_meta,
                session_id=lane_session_id,
            )
        except ValueError as exc:
            raise _map_restore_path_metadata_value_error(exc, uri) from exc

    return {"new_version": restored_id}


# ========== Rollback Endpoint ==========

@router.post("/sessions/{session_id}/rollback/{resource_id:path}", response_model=RollbackResponse)
async def rollback_resource(session_id: str, resource_id: str, request: RollbackRequest):
    """
    Roll a resource back to the selected snapshot state.

    Path snapshots (resource_type="path"):
    - create -> delete the newly created memory/path
    - create_alias -> remove the alias path
    - delete -> restore the deleted path
    - modify_meta -> restore priority/disclosure

    Content snapshots (resource_type="memory"):
    - modify_content -> point the path back to the older memory version
    """
    session_id = _validate_session_id_or_400(session_id)
    
    manager = get_snapshot_manager()
    resource_id, snapshot = _get_snapshot_exact_or_decoded(
        manager,
        session_id,
        resource_id,
    )
    
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot for '{resource_id}' not found in session '{session_id}'"
        )
    
    resource_type = snapshot["resource_type"]
    data = snapshot["data"]
    operation_type = data.get("operation_type", "modify")
    lane_session_id = f"review.rollback:{session_id}"
    
    try:
        # Dispatch based on resource_type
        if resource_type == "path":
            result = await _rollback_path(data, lane_session_id=lane_session_id)
        elif resource_type == "memory":
            newer_snapshot_guard = None
            if operation_type in {"modify_content", "modify"}:
                def newer_snapshot_guard() -> None:
                    _raise_if_newer_review_snapshot_exists(
                        manager=manager,
                        session_id=session_id,
                        snapshot=snapshot,
                    )
            if operation_type == "modify_content":
                result = await _rollback_memory_content(
                    data,
                    lane_session_id=lane_session_id,
                    newer_snapshot_guard=newer_snapshot_guard,
                )
            elif operation_type == "modify":
                # Legacy: old "modify" snapshots with resource_type="memory"
                result = await _rollback_legacy_modify(
                    data,
                    lane_session_id=lane_session_id,
                    newer_snapshot_guard=newer_snapshot_guard,
                )
            elif operation_type in ("create", "delete", "create_alias"):
                # Legacy: old snapshots used resource_type="memory" for all operations
                result = await _rollback_path(
                    data,
                    lane_session_id=lane_session_id,
                )
            else:
                raise HTTPException(status_code=400, detail=f"Unknown memory operation: {operation_type}")
        else:
            raise HTTPException(status_code=400, detail=f"Unknown resource type: {resource_type}")
        
        # Build response message
        message = _build_rollback_message(resource_id, operation_type, result)
        
        return RollbackResponse(
            resource_id=resource_id,
            resource_type=resource_type,
            success=True,
            message=message,
            new_version=result.get("new_version")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        _raise_review_internal_error(
            operation="rollback_resource",
            error="rollback_failed",
            exc=e,
        )


def _build_rollback_message(resource_id: str, operation_type: str, result: dict) -> str:
    """Generate a human-readable rollback result message."""
    if result.get("no_change"):
        return "No changes detected. Already matches snapshot."
    
    messages = {
        "create":         f"Deleted created resource '{resource_id}'.",
        "create_alias":   f"Removed alias '{resource_id}'.",
        "delete":         f"Restored deleted resource '{resource_id}'.",
        "modify_meta":    f"Restored metadata for '{resource_id}'.",
        "modify_content": f"Restored content to snapshot version (memory_id={result.get('new_version')}).",
        "modify":         f"Restored to snapshot version (memory_id={result.get('new_version')}).",
    }
    
    return messages.get(operation_type, f"Rollback completed for '{resource_id}'.")


@router.delete("/sessions/{session_id}/snapshots/{resource_id:path}")
async def delete_snapshot(session_id: str, resource_id: str):
    """
    Delete one snapshot after confirming rollback is no longer needed.
    """
    session_id = _validate_session_id_or_400(session_id)
    
    manager = get_snapshot_manager()
    resource_id, snapshot = _get_snapshot_exact_or_decoded(
        manager,
        session_id,
        resource_id,
    )
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot for '{resource_id}' not found in session '{session_id}'"
        )

    deleted = manager.delete_snapshot(session_id, resource_id)
    
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot for '{resource_id}' not found in session '{session_id}'"
        )
    
    return {"message": f"Snapshot for '{resource_id}' deleted"}


@router.delete("/sessions/{session_id}")
async def clear_session(session_id: str):
    """
    Clear every snapshot belonging to one session.

    Call this after the human confirms the session no longer needs review.
    """
    session_id = _validate_session_id_or_400(session_id)
    manager = get_snapshot_manager()
    count = manager.clear_session(session_id)
    
    if count == 0:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found or already empty"
        )
    
    return {"message": f"Session '{session_id}' cleared, {count} snapshots deleted"}


# ========== Deprecated Memory Management (Human Only) ==========

@router.get("/deprecated")
async def list_deprecated_memories():
    """
    List all memories currently marked as deprecated.

    These are older versions left behind by AI updates/deletes and waiting for
    human review before permanent deletion.
    """
    client = get_sqlite_client()
    
    try:
        memories = await client.get_deprecated_memories()
        return {
            "count": len(memories),
            "memories": memories
        }
    except Exception as e:
        _raise_review_internal_error(
            operation="list_deprecated_memories",
            error="list_deprecated_failed",
            exc=e,
        )


@router.delete("/memories/{memory_id}")
async def permanently_delete_memory(memory_id: int):
    """
    Permanently delete one memory.

    This is irreversible and intended for human-triggered dashboard actions
    only.
    """
    client = get_sqlite_client()
    
    try:
        async def _write_task_delete_memory() -> Any:
            return await client.permanently_delete_memory(
                memory_id,
                require_orphan=True,
            )

        await _run_write_lane(
            "deprecated.permanently_delete_memory",
            _write_task_delete_memory,
            session_id="review.deprecated_delete",
        )
        return {"message": f"Memory {memory_id} permanently deleted"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        _raise_review_internal_error(
            operation="permanently_delete_memory",
            error="delete_deprecated_failed",
            exc=e,
        )


# ========== Utility Endpoints ==========

@router.post("/diff", response_model=DiffResponse)
async def compare_text(request: DiffRequest):
    """
    Compare two texts and return HTML plus unified diff output.

    Args:
        request: Request body with ``text_a`` and ``text_b``.

    Returns:
        DiffResponse: Includes ``diff_html``, ``diff_unified``, and ``summary``.
    """
    try:
        diff_html, diff_unified, summary = get_text_diff(
            request.text_a,
            request.text_b
        )
        return DiffResponse(
            diff_html=diff_html,
            diff_unified=diff_unified,
            summary=summary
        )
    except Exception as e:
        _raise_review_internal_error(
            operation="compare_text",
            error="compare_text_failed",
            exc=e,
        )
