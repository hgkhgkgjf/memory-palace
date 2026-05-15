"""Thin adapter for the ``compact_context`` MCP tool.

Re-exports the canonical implementation from :mod:`mcp_server`.  The
``@mcp.tool()`` registration lives on the original function; importing
this module does NOT re-register the tool.
"""

from __future__ import annotations

from mcp_server import compact_context


__all__ = ["compact_context"]
