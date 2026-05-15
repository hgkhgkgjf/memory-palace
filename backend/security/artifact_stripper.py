"""Strip injection-style artifacts from tool result text (opt-in).

This module is **opt-in** (constraint C4 of Round 3 Track A):

* Default behavior is unchanged — ``strip(content, caps)`` returns
  ``content`` byte-for-byte unless BOTH:
    1. The env flag ``ARTIFACT_STRIPPING_ENABLED`` is truthy, AND
    2. The caller-supplied ``host_capabilities`` declares
       ``can_strip_tool_artifacts=True``.
* When activation conditions are met, the stripper removes a small,
  fixed set of injection-style wrappers that some hosts inject around
  Memory Palace output:
    - ``<relevant-memories>...</relevant-memories>``
    - ``<memory-context>...</memory-context>``
    - ``<!-- memory-palace-injected -->...<!-- /memory-palace-injected -->``
* The stripper is stateless and per-call; it does not memoize across
  turns and does not coordinate with any other component.

The set of patterns is intentionally narrow — it only targets the
exact wrappers documented above. Stripping the entire body of those
wrappers (not just the tags) prevents duplicated context when the
host re-injects the same Memory Palace data into the next turn.

This module lives alongside the existing ``sanitizers.py`` helpers in
``backend/security/`` because both share the same defensive posture:
fail-closed, side-effect-free, importable from contract tests.
"""

from __future__ import annotations

import os
import re
from typing import Any, Iterable, Mapping, Optional, Pattern, Tuple

__all__ = [
    "ArtifactStripper",
    "ARTIFACT_STRIPPING_ENV",
    "REQUIRED_HOST_FLAG",
    "ARTIFACT_PATTERNS",
]


ARTIFACT_STRIPPING_ENV = "ARTIFACT_STRIPPING_ENABLED"
"""Env flag that gates this adapter. Defaults to disabled."""

REQUIRED_HOST_FLAG = "can_strip_tool_artifacts"
"""Host capability key required for activation."""


_TRUTHY = frozenset({"1", "true", "yes", "y", "on"})


def _coerce_truthy(value: Any) -> bool:
    """Best-effort truthy check; mirrors ``security.sanitizers`` style.

    Any unrecognized scalar maps to ``False`` so a misconfigured env
    var or capability dict cannot accidentally activate stripping.
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


def _compile_patterns() -> Tuple[Pattern[str], ...]:
    """Compile the fixed artifact regex set.

    Each pattern is anchored on a literal tag pair and uses non-greedy
    matching with ``re.DOTALL`` so multi-line bodies are removed in a
    single shot. The set is small on purpose; adding a new pattern is
    an intentional contract change.
    """
    raw = (
        # XML-style wrapper used by some hosts to flag injected memory.
        r"<relevant-memories\b[^>]*>.*?</relevant-memories\s*>",
        # Alternate wrapper produced by certain skill loaders.
        r"<memory-context\b[^>]*>.*?</memory-context\s*>",
        # HTML-comment fence used in markdown contexts.
        r"<!--\s*memory-palace-injected\s*-->.*?<!--\s*/memory-palace-injected\s*-->",
    )
    return tuple(re.compile(p, re.DOTALL | re.IGNORECASE) for p in raw)


ARTIFACT_PATTERNS: Tuple[Pattern[str], ...] = _compile_patterns()
"""The exact set of artifact wrappers this stripper recognizes."""


class ArtifactStripper:
    """Remove injection-style wrappers from tool result text.

    Instances are stateless and cheap to construct. The constructor
    accepts an optional env override so tests can drive activation
    without mutating ``os.environ`` globally.

    Parameters
    ----------
    env_enabled:
        Optional explicit override for the env flag. When provided,
        this value wins over ``os.environ[ARTIFACT_STRIPPING_ENV]``.
        Used by tests; production callers should leave this ``None``.
    patterns:
        Optional pattern override. Production callers should leave
        this ``None`` to use the canonical ``ARTIFACT_PATTERNS`` set.
    """

    def __init__(
        self,
        env_enabled: Optional[bool] = None,
        patterns: Optional[Iterable[Pattern[str]]] = None,
    ) -> None:
        self._env_override = env_enabled
        self._patterns: Tuple[Pattern[str], ...] = (
            tuple(patterns) if patterns is not None else ARTIFACT_PATTERNS
        )

    # ---- public API -------------------------------------------------

    def strip(
        self,
        content: str,
        host_capabilities: Optional[Mapping[str, Any]],
    ) -> str:
        """Return ``content`` with known artifact wrappers removed.

        Parameters
        ----------
        content:
            The text returned by an MCP tool (or any text the caller
            wants to defensively scrub). Non-strings and empty inputs
            are handled by returning the input unchanged.
        host_capabilities:
            The declarative capability dict described in the
            host-capability-matrix RFC. Must declare
            ``can_strip_tool_artifacts=True`` for stripping to occur.

        Returns
        -------
        str
            The cleaned content. When activation conditions are not
            met, the original ``content`` is returned byte-for-byte
            so the MCP contract golden remains intact.
        """
        if not isinstance(content, str) or not content:
            return content
        if not self._is_active(host_capabilities):
            return content

        cleaned = content
        for pattern in self._patterns:
            cleaned = pattern.sub("", cleaned)
        return cleaned

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
        return _coerce_truthy(os.environ.get(ARTIFACT_STRIPPING_ENV))
