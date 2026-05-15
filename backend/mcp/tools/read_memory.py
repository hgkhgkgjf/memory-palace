"""Thin adapter for the ``read_memory`` MCP tool.

Re-exports the canonical implementation from :mod:`mcp_server`.  The
``@mcp.tool()`` registration lives on the original function; importing
this module does NOT re-register the tool.

Future migration: when the MCP layer is migrated to ``MemoryCore``,
this module flips its import target without touching callers.
"""

from __future__ import annotations

from mcp_server import read_memory


__all__ = ["read_memory"]
