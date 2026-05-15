"""SQLAlchemy ORM models for the Memory Palace storage layer.

Extracted from :mod:`db.sqlite_client` to keep the storage facade slim and
to allow other modules to reference the model classes without importing the
full client module.

Compatibility guarantee
-----------------------
Importing from ``db.sqlite_client`` continues to work because that module
re-exports these symbols.  Existing code that depends on
``from db.sqlite_client import Memory, MemoryGist, ...`` does not need to
change.  Tests and benchmarks already depend on that surface.

The ``_utc_now_naive`` helper used as a server default is defined here so
that the model definitions are self contained when the module is imported in
isolation (for example by migration tooling).  ``db.sqlite_client`` imports
the same helper from this module to avoid double definitions.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import declarative_base, relationship


__all__ = [
    "Base",
    "Memory",
    "Path",
    "MemoryChunk",
    "MemoryChunkVec",
    "EmbeddingCache",
    "IndexMeta",
    "SchemaMigration",
    "MemoryGist",
    "MemoryTag",
    "AccessLog",
    "MemorySummary",
    "ArchivedMemory",
    "ProceduralMemory",
    "_utc_now_naive",
]


Base = declarative_base()


def _utc_now_naive() -> datetime:
    """Naive UTC datetime used as a server default for legacy schema columns."""

    return datetime.now(timezone.utc).replace(tzinfo=None)


class Memory(Base):
    """A single memory unit with content and metadata.

    Note: The 'title' column was removed. A memory's display name is now
    derived from the last segment of its path(s) in the paths table.
    Existing DB columns named 'title' are simply ignored by SQLAlchemy.

    Version chain: When a memory is updated, the old version's `migrated_to`
    field points to the new version's ID, forming a singly-linked list:
        Memory(id=1, migrated_to=5) -> Memory(id=5, migrated_to=12) -> Memory(id=12, migrated_to=NULL)
    When a middle node is permanently deleted, the chain is repaired by
    skipping over it (A->B->C, delete B -> A->C).
    """

    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    deprecated = Column(Boolean, default=False)  # Marked for review/deletion
    migrated_to = Column(
        Integer, nullable=True
    )  # Points to successor memory ID (version chain)
    created_at = Column(DateTime, default=_utc_now_naive)
    vitality_score = Column(
        Float, default=1.0, server_default=text("1.0"), nullable=False
    )
    last_accessed_at = Column(DateTime, nullable=True)
    access_count = Column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    # Relationship to paths
    paths = relationship("Path", back_populates="memory")
    gists = relationship("MemoryGist", back_populates="memory")
    tags = relationship("MemoryTag", back_populates="memory")


class Path(Base):
    """A path pointing to a memory. Multiple paths can point to the same memory."""

    __tablename__ = "paths"

    # Composite primary key: (domain, path)
    # domain examples: "core", "writer", "game"
    # path examples: "memory-palace", "memory-palace/salem"
    domain = Column(String(64), primary_key=True, default="core")
    path = Column(String(512), primary_key=True)
    memory_id = Column(Integer, ForeignKey("memories.id"), nullable=False)
    created_at = Column(DateTime, default=_utc_now_naive)

    # Context metadata (moved from Memory to Path)
    priority = Column(Integer, default=0)  # Relative priority for ranking
    disclosure = Column(Text, nullable=True)  # When to expand this memory

    # Relationship to memory
    memory = relationship("Memory", back_populates="paths")


class MemoryChunk(Base):
    """Chunked text slices for memory-level retrieval."""

    __tablename__ = "memory_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    memory_id = Column(Integer, ForeignKey("memories.id"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    char_start = Column(Integer, nullable=False, default=0)
    char_end = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=_utc_now_naive)


class MemoryChunkVec(Base):
    """Persisted vectors for memory chunks (fallback pure-SQLite storage)."""

    __tablename__ = "memory_chunks_vec"

    chunk_id = Column(Integer, ForeignKey("memory_chunks.id"), primary_key=True)
    memory_id = Column(Integer, ForeignKey("memories.id"), nullable=False, index=True)
    vector = Column(Text, nullable=False)
    model = Column(String(64), nullable=False, default="hash-v1")
    dim = Column(Integer, nullable=False, default=64)
    created_at = Column(DateTime, default=_utc_now_naive)


class EmbeddingCache(Base):
    """Cache embeddings by deterministic text hash."""

    __tablename__ = "embedding_cache"

    cache_key = Column(String(128), primary_key=True)
    text_hash = Column(String(128), nullable=False, index=True)
    model = Column(String(64), nullable=False, default="hash-v1")
    embedding = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=_utc_now_naive, onupdate=_utc_now_naive)


class IndexMeta(Base):
    """Index runtime metadata and capability flags."""

    __tablename__ = "index_meta"

    key = Column(String(128), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=_utc_now_naive, onupdate=_utc_now_naive)


class SchemaMigration(Base):
    """Applied schema migration records."""

    __tablename__ = "schema_migrations"

    version = Column(String(32), primary_key=True)
    applied_at = Column(DateTime, default=_utc_now_naive, nullable=False)
    checksum = Column(String(128), nullable=False)


class MemoryGist(Base):
    """Compact gist materialized from a memory body.

    Provenance columns (``source_memory_ids``, ``source_hashes``,
    ``derivation_method``, ``confidence``, ``review_state``,
    ``storage_budget_bytes``, ``source_chunk_ids``) are added by
    migration 0007 to satisfy the Derived Memory Contract
    (``docs/superpowers/rfcs/derived-memory-contract.md``). They are
    nullable on disk so existing application code keeps working until
    derivation jobs are updated to populate them; new code MUST set
    them at insert time.
    """

    __tablename__ = "memory_gists"
    __table_args__ = (
        Index("idx_memory_gists_memory_id", "memory_id"),
        Index(
            "idx_memory_gists_memory_source_hash_unique",
            "memory_id",
            "source_content_hash",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    memory_id = Column(Integer, ForeignKey("memories.id"), nullable=False)
    gist_text = Column(Text, nullable=False)
    source_content_hash = Column(String(128), nullable=False)
    gist_method = Column(String(64), nullable=False, default="fallback")
    quality_score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=_utc_now_naive)

    # Provenance fields (migration 0007). Nullable on disk for backwards
    # compatibility; new writers populate them.
    source_memory_ids = Column(Text, nullable=True)
    source_chunk_ids = Column(Text, nullable=True)
    source_hashes = Column(Text, nullable=True)
    derivation_method = Column(String(64), nullable=True, default="llm_summary")
    confidence = Column(Float, nullable=True, default=0.0)
    review_state = Column(String(64), nullable=True, default="auto_generated")
    storage_budget_bytes = Column(Integer, nullable=True)

    memory = relationship("Memory", back_populates="gists")


class MemoryTag(Base):
    """Structured tag extraction output for memories."""

    __tablename__ = "memory_tags"
    __table_args__ = (
        Index("idx_tags_value", "tag_value"),
        Index("idx_memory_tags_memory_id", "memory_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    memory_id = Column(Integer, ForeignKey("memories.id"), nullable=False)
    tag_type = Column(String(64), nullable=False)
    tag_value = Column(String(255), nullable=False)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=_utc_now_naive)

    memory = relationship("Memory", back_populates="tags")


class AccessLog(Base):
    """L0 — per-memory operation log.

    Internal table written by the runtime to record read/write/search_hit
    events. NOT exposed through MCP tools. Retention is FIFO via an
    explicit maintenance job (never inline).
    """

    __tablename__ = "access_log"
    __table_args__ = (
        Index("idx_access_log_memory_id", "memory_id"),
        Index("idx_access_log_timestamp", "timestamp"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    memory_id = Column(Integer, ForeignKey("memories.id"), nullable=False)
    operation = Column(String(64), nullable=False)
    # ``timestamp`` is stored as ISO-8601 text by the SQLite default
    # (matches the forward migration); we expose it as Text here so
    # SQLAlchemy does not try to reinterpret the string.
    timestamp = Column(
        Text,
        nullable=False,
        server_default=text("(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"),
    )
    context = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)


class MemorySummary(Base):
    """L2 — topic-/scope-level summary spanning one or more L1 memories.

    Every row MUST satisfy the Derived Memory Contract:
    ``source_memory_ids``, ``source_hashes``, ``derivation_method``,
    ``confidence``, ``review_state``, ``storage_budget_bytes``.
    """

    __tablename__ = "memory_summaries"
    __table_args__ = (
        Index("idx_memory_summaries_scope", "scope"),
        Index("idx_memory_summaries_review_state", "review_state"),
        Index("idx_memory_summaries_updated_at", "updated_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)
    summary_text = Column(Text, nullable=False)
    scope = Column(Text, nullable=False)
    layer = Column(Integer, nullable=False, default=2, server_default=text("2"))
    source_memory_ids = Column(Text, nullable=False)
    source_chunk_ids = Column(Text, nullable=True)
    source_hashes = Column(Text, nullable=False)
    derivation_method = Column(
        String(64),
        nullable=False,
        default="llm_summary",
        server_default=text("'llm_summary'"),
    )
    confidence = Column(
        Float, nullable=False, default=0.0, server_default=text("0.0")
    )
    review_state = Column(
        String(64),
        nullable=False,
        default="draft",
        server_default=text("'draft'"),
    )
    storage_budget_bytes = Column(Integer, nullable=True)
    created_at = Column(
        Text,
        nullable=False,
        server_default=text("(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"),
    )
    updated_at = Column(
        Text,
        nullable=False,
        server_default=text("(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"),
    )


class ArchivedMemory(Base):
    """Soft-delete surface for memories that have left ``memories``.

    Restorable through the review-token flow. v1 does NOT auto-purge any
    row from this table; permanent purge is an explicit
    human-approved action.
    """

    __tablename__ = "archived_memories"
    __table_args__ = (
        Index("idx_archived_memories_original_id", "original_memory_id"),
        Index("idx_archived_memories_archived_at", "archived_at"),
        Index("idx_archived_memories_review_state", "review_state"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    original_memory_id = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    archived_at = Column(
        Text,
        nullable=False,
        server_default=text("(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"),
    )
    archive_reason = Column(
        String(64),
        nullable=False,
        default="forgetting_review",
        server_default=text("'forgetting_review'"),
    )
    archived_by = Column(Text, nullable=True)
    paths_snapshot = Column(
        Text,
        nullable=False,
        default="[]",
        server_default=text("'[]'"),
    )
    review_state = Column(
        String(64),
        nullable=False,
        default="human_reviewed",
        server_default=text("'human_reviewed'"),
    )
    restorable_until = Column(Text, nullable=True)


class ProceduralMemory(Base):
    """Procedural memory — a recurring step-based pattern.

    Distinct from L1 (raw memories), L2 (topic summaries), and gists
    (per-memory paraphrases). A procedural memory captures *how to do
    something* that the agent has observed across multiple L1 rows.

    Draft-by-default invariant (v1): the application layer ALWAYS
    inserts new rows with ``review_state='draft'``. Promoting a draft
    to ``review_state='human_reviewed'`` is the ONLY way the agent is
    allowed to surface the procedure inside a planning context. A
    rejected draft flips to ``review_state='rejected'`` and stays
    queryable for audit purposes; v1 never deletes a procedural row.

    Every row carries the Derived Memory Contract fields per C3:
    ``source_memory_ids``, ``source_hashes``, ``derivation_method``,
    ``confidence``, ``review_state``, ``storage_budget_bytes``.
    """

    __tablename__ = "procedural_memories"
    __table_args__ = (
        Index("idx_procedural_memories_review_state", "review_state"),
        Index("idx_procedural_memories_trigger", "trigger"),
        Index("idx_procedural_memories_updated_at", "updated_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    trigger = Column(Text, nullable=False)
    # ``steps_json`` is the canonical wire-format for the ordered step
    # list. We store JSON-as-text so the schema stays SQLite-portable.
    steps_json = Column(Text, nullable=False)
    source_memory_ids = Column(Text, nullable=False)
    source_chunk_ids = Column(Text, nullable=True)
    source_hashes = Column(Text, nullable=False)
    derivation_method = Column(
        String(64),
        nullable=False,
        default="rule_based",
        server_default=text("'rule_based'"),
    )
    confidence = Column(
        Float, nullable=False, default=0.0, server_default=text("0.0")
    )
    review_state = Column(
        String(64),
        nullable=False,
        default="draft",
        server_default=text("'draft'"),
    )
    success_count = Column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_used = Column(Text, nullable=True)
    storage_budget_bytes = Column(Integer, nullable=True)
    review_token_fingerprint = Column(Text, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(
        Text,
        nullable=False,
        server_default=text("(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"),
    )
    updated_at = Column(
        Text,
        nullable=False,
        server_default=text("(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"),
    )
