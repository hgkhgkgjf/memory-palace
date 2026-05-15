"""Repository wrappers that segment ``SQLiteClient`` responsibilities.

Round 1 of the facade-preserving refactor.  These modules define thin
delegate classes that take an ``SQLiteClient`` instance and forward calls to
the existing methods on it.  They establish the import surface without
moving the implementation; the underlying methods remain on
``SQLiteClient`` so behavior is unchanged.

Future rounds will migrate the implementation into these repositories.

Example
-------
>>> from db.repositories import MemoryRepository
>>> from db import get_sqlite_client
>>> client = await get_sqlite_client()
>>> repo = MemoryRepository(client)
>>> await repo.get_memory_by_id(1)
"""

from .gist_repo import GistRepository
from .index_repo import IndexRepository
from .maintenance_repo import MaintenanceRepository
from .memory_repo import MemoryRepository
from .path_repo import PathRepository
from .search_repo import SearchRepository
from .vitality_repo import VitalityRepository

__all__ = [
    "GistRepository",
    "IndexRepository",
    "MaintenanceRepository",
    "MemoryRepository",
    "PathRepository",
    "SearchRepository",
    "VitalityRepository",
]
