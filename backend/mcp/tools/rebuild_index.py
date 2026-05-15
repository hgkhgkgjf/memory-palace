"""Thin adapter for the ``rebuild_index`` MCP tool.

Re-exports the canonical implementation from :mod:`mcp_server`.  The
``@mcp.tool()`` registration lives on the original function; importing
this module does NOT re-register the tool.
"""

from __future__ import annotations

from mcp_server import rebuild_index


__all__ = ["rebuild_index"]
