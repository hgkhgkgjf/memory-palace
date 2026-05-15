"""Shared base for repository wrappers.

The delegate pattern lets us split ``SQLiteClient`` responsibilities into
modules without moving any implementation in Round 1.  Each repository
holds a reference to the underlying client and forwards calls.

Because importing :mod:`db.sqlite_client` at module load time would create
a circular dependency (``SQLiteClient`` imports from this package via
``db.repositories``-aware future glue), we use ``TYPE_CHECKING`` for the
type hint only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from db.sqlite_client import SQLiteClient


class _RepositoryBase:
    """Base class storing the underlying ``SQLiteClient``.

    Subclasses expose narrow, intention-revealing method surfaces that
    delegate back to the client.  This intermediate facade lets callers
    depend on a small repository instead of the whole monolith.
    """

    __slots__ = ("_client",)

    def __init__(self, client: "SQLiteClient") -> None:
        self._client = client

    @property
    def client(self) -> "SQLiteClient":
        """The underlying SQLite client (escape hatch for legacy callers)."""

        return self._client
