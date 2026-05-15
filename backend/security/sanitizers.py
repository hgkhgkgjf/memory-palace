"""Pure value-sanitization helpers used by the MCP tool layer.

These helpers were extracted from :mod:`mcp_server` in Round 1 of the
facade-preserving refactor.  They have no dependency on the FastMCP
server, the SQLite client, or the runtime state, so they can live in
:mod:`security` next to the existing import-guard module.

The originals in ``mcp_server.py`` continue to work because that module
re-imports the names from here; existing call sites are unaffected.

Functions
---------
* :func:`validate_mcp_text_length` -- enforce an upper bound on a
  user-supplied text length.
* :func:`validate_uri_text` -- reject empty / control / surrogate
  characters in a memory URI.
* :func:`safe_int` -- best-effort ``int`` coercion with a default.
* :func:`safe_non_negative_int` -- best-effort non-negative ``int``
  coercion (returns ``0`` on failure).
* :func:`coerce_bool` -- best-effort boolean coercion across common
  representations.
* :func:`normalize_path_prefix` -- normalize a ``path_prefix`` argument
  to a canonical relative path or the ``"corrections"`` fallback.

The historical ``_underscore_prefixed`` aliases are also exported so
that internal mcp_server code can keep using the original spelling
without modification.
"""

from __future__ import annotations

import unicodedata
from typing import Any, Optional


__all__ = [
    "validate_mcp_text_length",
    "validate_uri_text",
    "safe_int",
    "safe_non_negative_int",
    "coerce_bool",
    "normalize_path_prefix",
    # underscore-prefixed aliases for in-place compatibility:
    "_validate_mcp_text_length",
    "_validate_uri_text",
    "_safe_int",
    "_safe_non_negative_int",
    "_coerce_bool",
    "_normalize_path_prefix",
]


def validate_mcp_text_length(
    value: Optional[str], *, field_name: str, max_chars: int
) -> None:
    """Raise :class:`ValueError` if ``value`` exceeds ``max_chars`` characters.

    ``None`` is treated as "absent" and passes validation -- callers
    decide elsewhere whether absence is acceptable.
    """

    if value is None:
        return
    if len(value) > max_chars:
        raise ValueError(f"{field_name} must be at most {max_chars} characters.")


def validate_uri_text(uri: str) -> str:
    """Validate a memory URI string and return its stripped form.

    Rejects empty strings, surrogate code points, and control / format
    characters.  Returns the stripped, normalized value on success.
    """

    value = str(uri or "").strip()
    if not value:
        raise ValueError("URI must not be empty.")
    for ch in value:
        category = unicodedata.category(ch)
        if category == "Cs":
            raise ValueError("URI must not contain surrogate characters.")
        if category in {"Cc", "Cf"}:
            raise ValueError(
                "URI must not contain control or invisible format characters."
            )
    return value


def safe_int(value: Any, default: int = 0) -> int:
    """Coerce ``value`` to ``int``, returning ``default`` on failure.

    Booleans are not treated as integers; passing ``True`` / ``False``
    yields ``default`` so accidental flag-as-count bugs do not slip
    through.
    """

    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_non_negative_int(value: Any) -> int:
    """Coerce ``value`` to a non-negative ``int`` (``max(0, int(value))``).

    Returns ``0`` on any failure, including ``None`` or non-numeric input.
    """

    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def coerce_bool(value: Any, default: bool = False) -> bool:
    """Best-effort boolean coercion across common representations.

    Strings such as ``"1" / "true" / "yes" / "on" / "enabled"`` map to
    ``True``; ``"0" / "false" / "no" / "off" / "disabled"`` map to
    ``False``.  Unknown strings return ``default``.  Numeric values fall
    back to ``bool(value)``.  ``None`` returns ``default``.
    """

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "enabled"}:
            return True
        if lowered in {"0", "false", "no", "off", "disabled"}:
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def normalize_path_prefix(path_prefix: Optional[str]) -> str:
    """Normalize a ``path_prefix`` argument.

    The result is always a non-empty relative path with no leading or
    trailing slash; empty / ``None`` / whitespace-only inputs collapse
    to the ``"corrections"`` fallback used by review tooling.
    """

    raw = str(path_prefix or "").strip().strip("/")
    if not raw:
        return "corrections"
    parts = [part for part in raw.split("/") if part]
    return "/".join(parts) if parts else "corrections"


# ---------------------------------------------------------------------------
# Underscore-prefixed aliases preserve the original private spelling used
# inside ``mcp_server.py``.  Importing the canonical names is preferred for
# new code, but these aliases let the existing module keep its internal
# call sites unchanged after the extraction.
# ---------------------------------------------------------------------------
_validate_mcp_text_length = validate_mcp_text_length
_validate_uri_text = validate_uri_text
_safe_int = safe_int
_safe_non_negative_int = safe_non_negative_int
_coerce_bool = coerce_bool
_normalize_path_prefix = normalize_path_prefix
