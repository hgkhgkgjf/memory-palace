"""Memory-domain MCP tool views (Round 1 facade).

These re-export the existing tool functions defined in ``mcp_server``;
they do not redefine any ``@mcp.tool()`` registrations.  Callers may
``from mcp.views.memory_views import read_memory`` to avoid pulling in
the full :mod:`mcp_server` surface.
"""

from __future__ import annotations

from mcp_server import (
    create_memory,
    delete_memory,
    read_memory,
    update_memory,
)


__all__ = ["create_memory", "delete_memory", "read_memory", "update_memory"]
