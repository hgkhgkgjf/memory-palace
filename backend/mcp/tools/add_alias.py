"""Thin adapter for the ``add_alias`` MCP tool.

Re-exports the canonical implementation from :mod:`mcp_server`.  The
``@mcp.tool()`` registration lives on the original function; importing
this module does NOT re-register the tool.
"""

from __future__ import annotations

from mcp_server import add_alias


__all__ = ["add_alias"]
