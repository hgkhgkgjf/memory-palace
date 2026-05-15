"""Maintenance-domain MCP tool views (Round 1 facade).

Thin re-exports of ``compact_context``, ``rebuild_index`` and
``index_status`` from :mod:`mcp_server`.
"""

from __future__ import annotations

from mcp_server import compact_context, index_status, rebuild_index


__all__ = ["compact_context", "index_status", "rebuild_index"]
