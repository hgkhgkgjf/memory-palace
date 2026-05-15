"""Host-specific opt-in adapters for the MCP tool layer.

Adapters in this package are **opt-in** by design (Round 3, Track A,
constraint C4): they MUST NOT change the default return of
``read_memory("system://boot")`` or any other MCP tool. Each adapter is
guarded by both an environment flag and a host-capability declaration;
when either is false, the adapter returns its input unchanged.

See ``docs/superpowers/rfcs/host-capability-matrix.md`` for the
per-host capability matrix and the contract every adapter must respect.
"""

from __future__ import annotations

from .cache_adapter import PromptCacheAdapter

__all__ = ["PromptCacheAdapter"]
