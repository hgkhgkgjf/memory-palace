"""MCP thin tool adapters.

Each submodule in this package re-exports exactly one ``@mcp.tool()``
callable from :mod:`mcp_server` under a stable, per-tool import path.
Adapters are intentionally thin (a few lines each) so:

* tests can ``from mcp.tools.read_memory import read_memory`` without
  pulling in the full ``mcp_server`` surface,
* the future migration -- where tools call ``MemoryCore`` directly
  instead of the mcp_server free functions -- swaps the import target
  here without touching call sites,
* per-tool documentation / metadata can live alongside its adapter
  rather than buried in a 6 kLOC monolith.

Round 3 contract:
    These adapters MUST remain re-export shims.  Any logic that creeps
    into a tool file should instead move to ``MemoryCore`` or a
    repository module.
"""

from __future__ import annotations

from .add_alias import add_alias
from .compact_context import compact_context
from .create_memory import create_memory
from .delete_memory import delete_memory
from .index_status import index_status
from .read_memory import read_memory
from .rebuild_index import rebuild_index
from .search_memory import search_memory
from .update_memory import update_memory


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
