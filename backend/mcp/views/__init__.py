"""Per-domain view wrappers around the MCP tool functions.

The wrappers are intentionally thin: each one imports the canonical
implementation from :mod:`mcp_server` and re-exports it under a stable
name.  Importing this package therefore does **not** double-register any
``@mcp.tool()`` -- it just exposes the already-registered tool callable
through a narrow per-domain module.

Why a separate package?
-----------------------
``mcp_server.py`` is large (6k+ LOC) and mixes tool definitions, helpers
and configuration.  Splitting the public tool surface into domain
modules lets callers and tests depend on a focused interface even
before the implementations themselves are relocated in future rounds.
"""

from __future__ import annotations

from .alias_views import add_alias
from .maintenance_views import compact_context, index_status, rebuild_index
from .memory_views import (
    create_memory,
    delete_memory,
    read_memory,
    update_memory,
)
from .search_views import search_memory


__all__ = [
    "add_alias",
    "compact_context",
    "create_memory",
    "delete_memory",
    "index_status",
    "read_memory",
    "rebuild_index",
    "search_memory",
    "update_memory",
]
