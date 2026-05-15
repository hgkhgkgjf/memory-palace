"""Local ``mcp`` package for view extraction (Round 1).

This package hosts thin view wrappers around the MCP tool functions
defined in :mod:`mcp_server`.  It **must coexist** with the upstream
``mcp`` SDK package (``mcp.server.fastmcp.FastMCP``, ``mcp.ClientSession``,
etc.) that lives in ``site-packages``.  Two integration steps are needed:

1.  Extend ``__path__`` via :func:`pkgutil.extend_path` so submodule
    lookups like ``mcp.server`` continue to resolve to the SDK's
    directory on disk.
2.  Re-export the SDK's *top-level* names (``ClientSession``,
    ``StdioServerParameters``, etc.) into this package so callers that do
    ``from mcp import ClientSession`` still work.  Step 1 alone is not
    enough -- it only affects submodule resolution, not attribute
    inheritance.

Round 1 does *not* move any implementation.  The MCP tool decorators
still register tools through ``mcp_server.mcp``; the view modules under
``mcp.views`` simply import and re-export those tool functions so other
code can depend on a narrow per-domain surface instead of the full
monolith.
"""

from __future__ import annotations

import pkgutil as _pkgutil

# Step 1: extend submodule path so ``mcp.server``, ``mcp.client``,
# ``mcp.types`` etc. keep resolving to the SDK's directory in
# ``site-packages`` as well as our local directory.
__path__ = _pkgutil.extend_path(__path__, __name__)


def _reexport_upstream_top_level() -> None:
    """Re-export the SDK's ``mcp.__init__`` top-level names here.

    Once ``__path__`` is extended, the SDK's submodules (``mcp.client``,
    ``mcp.types`` and friends) become importable through our package.
    We mirror what the SDK's own ``__init__.py`` does so that
    ``from mcp import ClientSession`` continues to work without us
    having to hardcode the entire SDK API.

    Approach:
        * Read the SDK's ``__init__.py`` source from disk.
        * Pre-load each submodule listed via relative imports as
          ``mcp.<submod>`` (which already works thanks to ``__path__``).
        * Execute the SDK's source against this package's globals --
          relative imports resolve correctly because ``__name__`` is
          ``"mcp"`` and ``__path__`` covers the SDK directory.
    """

    import sys
    from pathlib import Path

    local_dir = Path(__file__).resolve().parent
    upstream_init: Path | None = None
    for candidate in __path__:
        candidate_path = Path(candidate).resolve()
        if candidate_path == local_dir:
            continue
        init_file = candidate_path / "__init__.py"
        if init_file.is_file():
            upstream_init = init_file
            break
    if upstream_init is None:
        return  # SDK not installed -- nothing to mirror.

    try:
        source = upstream_init.read_text(encoding="utf-8")
    except OSError:  # pragma: no cover - defensive
        return

    # Compile + exec against our package globals.  This makes the
    # relative imports inside the SDK init evaluate as ``mcp.client``,
    # ``mcp.types`` etc., which already resolve correctly because our
    # ``__path__`` includes the SDK directory.
    try:
        code_obj = compile(source, str(upstream_init), "exec")
        exec(code_obj, globals())
    except Exception:  # pragma: no cover - defensive
        # If the SDK init is incompatible (e.g. requires features we
        # cannot satisfy), keep this package usable for our own view
        # modules.  Submodule imports still work via ``__path__``.
        sys.stderr.write(
            "[mcp/__init__] warning: failed to mirror upstream SDK top-level "
            "names; submodule imports still work.\n"
        )


_reexport_upstream_top_level()
del _reexport_upstream_top_level
