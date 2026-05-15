"""Prompt-cache split adapter for hosts that support stable system context.

This adapter is **opt-in** (constraint C4 of Round 3 Track A):

* Default behavior of ``read_memory("system://boot")`` is unchanged.
* Activation requires BOTH:
    1. The env flag ``PROMPT_CACHE_SPLIT_ENABLED`` being truthy.
    2. The caller-supplied ``host_capabilities`` dict declaring
       ``can_set_system_context=True``.
* When activation conditions are not met, ``split_boot_text(...)``
  returns ``{"unsplit": full_text}`` — a pass-through that callers
  can hand straight back to the model.

The split splits the boot text along a stable boundary so the host can:

* Push the stable half (``system_context``) onto the prompt-cache prefix
  surface so it can be reused across turns.
* Push the dynamic half (``dynamic_context``) into the per-turn surface
  where cache misses are acceptable.

The boundary is the "Recently Modified Memories" subview appended by
``_generate_boot_memory_view`` in ``backend/mcp_server.py``. Everything
above that boundary is stable across short windows of activity; the
recent-memories view is, by construction, time-sensitive and breaks
cache hits on every refresh, so it belongs on the dynamic side.

This adapter performs **string-level** splitting only. It does not
import ``backend.mcp_server`` (which has heavy module-level side
effects) and it does not touch the SQLite client. It is safe to import
from contract tests and from any wrapper that lives outside the MCP
server process.

See ``docs/superpowers/rfcs/host-capability-matrix.md`` for the host
capability matrix and the C4 contract this module honors.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional

__all__ = [
    "PromptCacheAdapter",
    "PROMPT_CACHE_SPLIT_ENV",
    "REQUIRED_HOST_FLAG",
    "BOUNDARY_MARKER",
]


PROMPT_CACHE_SPLIT_ENV = "PROMPT_CACHE_SPLIT_ENABLED"
"""Env flag that gates this adapter. Defaults to disabled."""

REQUIRED_HOST_FLAG = "can_set_system_context"
"""Host capability key required for activation."""

BOUNDARY_MARKER = "# Recently Modified Memories"
"""Header line that the boot view emits before the recent-memories block.

This marker is a stable substring of the output of
``_generate_boot_memory_view`` in ``backend/mcp_server.py`` — see the
helper that prepends ``recent_view`` to the boot output. Splitting on
this header is preferred over splitting on the ``---`` separator
because the separator is generic markdown punctuation and could appear
inside a memory body.
"""


_TRUTHY = frozenset({"1", "true", "yes", "y", "on"})


def _coerce_truthy(value: Any) -> bool:
    """Best-effort truthy check across str / int / bool inputs.

    Matches the conservative style used elsewhere in
    ``backend.security.sanitizers``: any unrecognized scalar maps to
    ``False`` so an unset env var or a misconfigured host descriptor
    cannot accidentally enable the adapter.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY
    return False


class PromptCacheAdapter:
    """Split a boot text into a stable prefix and a dynamic suffix.

    Instances are stateless and cheap to construct; the constructor
    only captures an optional explicit env-flag override so tests can
    avoid mutating ``os.environ`` globally.

    Parameters
    ----------
    env_enabled:
        Optional explicit override for the env flag. When provided,
        this value wins over ``os.environ[PROMPT_CACHE_SPLIT_ENV]``.
        Used by tests; production callers should leave this ``None``
        and rely on the env var.
    """

    def __init__(self, env_enabled: Optional[bool] = None) -> None:
        self._env_override = env_enabled

    # ---- public API -------------------------------------------------

    def split_boot_text(
        self,
        full_text: str,
        host_capabilities: Optional[Mapping[str, Any]],
    ) -> Dict[str, str]:
        """Return either a pass-through or a split view of ``full_text``.

        Parameters
        ----------
        full_text:
            The unmodified return of ``read_memory("system://boot")``.
            Empty strings and non-strings are handled defensively.
        host_capabilities:
            The declarative capability dict described in the
            host-capability-matrix RFC. Must declare
            ``can_set_system_context=True`` for splitting to occur.

        Returns
        -------
        dict
            Always contains the key ``"unsplit"`` carrying the full
            input text. When activation conditions are satisfied AND
            the boundary marker is found, the dict additionally
            contains ``"system_context"`` (stable prefix) and
            ``"dynamic_context"`` (time-sensitive suffix). When any
            activation condition fails, only ``"unsplit"`` is
            returned. This invariant is the C4 backstop: callers that
            ignore the optional keys keep the legacy behavior.

        Notes
        -----
        The default return preserves the byte-exact boot text so the
        MCP contract golden (``boot_text_hash``) is unaffected.
        """
        text = full_text if isinstance(full_text, str) else ""

        if not self._is_active(host_capabilities):
            return {"unsplit": text}

        # Empty boot text — no useful split, but still respect contract.
        if not text:
            return {"unsplit": text}

        idx = text.find(BOUNDARY_MARKER)
        if idx < 0:
            # Boundary not present (e.g. recent-memories block failed
            # to render). Pass through rather than guess a split.
            return {"unsplit": text}

        # Walk back to the start of the line containing the marker so
        # we don't strand a partial separator on the stable side.
        cut = idx
        while cut > 0 and text[cut - 1] != "\n":
            cut -= 1

        stable = text[:cut].rstrip("\n")
        dynamic = text[cut:]

        # If the rstrip collapsed the stable portion to nothing, fall
        # back to pass-through. This guards against pathological boot
        # texts that start with the marker itself.
        if not stable:
            return {"unsplit": text}

        return {
            "system_context": stable,
            "dynamic_context": dynamic,
            "unsplit": text,
        }

    # ---- internals --------------------------------------------------

    def _is_active(self, host_capabilities: Optional[Mapping[str, Any]]) -> bool:
        """Activation requires BOTH env flag AND host capability."""
        if not self._env_enabled():
            return False
        if not host_capabilities:
            return False
        return _coerce_truthy(host_capabilities.get(REQUIRED_HOST_FLAG))

    def _env_enabled(self) -> bool:
        if self._env_override is not None:
            return bool(self._env_override)
        return _coerce_truthy(os.environ.get(PROMPT_CACHE_SPLIT_ENV))
