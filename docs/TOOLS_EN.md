# Memory Palace — MCP Tool Reference

Memory Palace provides persistent memory for AI agents through [MCP](https://modelcontextprotocol.io/). This document is the complete reference for all 9 MCP tools.

## Contents

- [Quick Reference](#quick-reference)
- [Core Concepts](#core-concepts)
- [Tool Details](#tool-details)
  - [read_memory](#read_memory)
  - [create_memory](#create_memory)
  - [update_memory](#update_memory)
  - [delete_memory](#delete_memory)
  - [add_alias](#add_alias)
  - [search_memory](#search_memory)
  - [compact_context](#compact_context)
  - [rebuild_index](#rebuild_index)
  - [index_status](#index_status)
- [Common Return Fields](#common-return-fields)
- [Degradation Mechanism](#degradation-mechanism)
- [Recommended Workflow](#recommended-workflow)
- [Retrieval Configuration](#retrieval-configuration)

---

## Quick Reference

| Tool | Category | Description |
|---|---|---|
| `read_memory` | Read | Read memory content by URI; supports full / chunked / range reads |
| `create_memory` | Write | Create a new memory under a parent URI |
| `update_memory` | Write | Update content, priority, or disclosure of existing memory |
| `delete_memory` | Write | Delete a memory path by URI |
| `add_alias` | Write | Create an alias URI for an existing memory |
| `search_memory` | Search | Keyword / semantic / hybrid retrieval |
| `compact_context` | Governance | Compress session context into persistent summaries |
| `rebuild_index` | Maintenance | Trigger index rebuild or sleep-time consolidation |
| `index_status` | Maintenance | Query index availability, queue depth, and runtime status |

---

## Core Concepts

### URI Addressing

Memory Palace uses `domain://path`:

```
core://agent              ← "agent" path under the core domain
writer://chapter_1/scene  ← Hierarchical path under writer
system://boot             ← Built-in system URI (read-only)
```

A URI is a **Memory Palace memory address**, not a filesystem path. Windows file paths like `C:/notes.txt` are rejected.

Percent-encoded variants (`core://foo%20bar`, `core://chapter_1%2Fscene_2`) are accepted as compatibility lookups for existing paths. Decoded filesystem paths (`C%3A/...`) are still rejected.

**Common domains**:

- `core` — Core memories (personality, preferences, key facts)
- `writer` — Writing domain (stories, chapters)
- `system` — Reserved (`boot` / `index` / `index-lite` / `audit` / `recent`), non-writable

> `priority` is an integer where **lower numbers mean higher priority** (0 is highest). Values like `true/false` or `1.9` are rejected.

### Write Guard

`create_memory` and `update_memory` automatically invoke **Write Guard** before writing to:

- Detect duplicates
- Suggest merges (returns `UPDATE` / `NOOP`)

Decision methods: `keyword`, `embedding`, `llm`, `write_guard_llm`, `unknown`, `none`, `exception`.

---

## Tool Details

<a id="read_memory"></a>

### `read_memory`

Read memory content by URI.

```python
read_memory(
    uri: str,                       # Required
    chunk_id: Optional[int] = None, # Chunk index (0-based)
    range: Optional[str] = None,    # Character range (e.g., "0:500")
    max_chars: Optional[int] = None,
    include_ancestors: Optional[bool] = False
)
```

**System URIs**:

| URI | Purpose |
|---|---|
| `system://boot` | Load core memories + recent updates (call at session startup) |
| `system://index` | Full index of all memories |
| `system://index-lite` | Lightweight gist summary |
| `system://audit` | Consolidated observability summary |
| `system://recent` | 10 most recently modified memories |
| `system://recent/N` | N most recent (up to 100) |

**Return format**:

- Default (no optional parameters): formatted plain text
- Segmented (any optional parameter): JSON string with `selection` metadata

**Examples**:

```python
read_memory("system://boot")
read_memory("core://agent/my_user")
read_memory("core://agent", chunk_id=0)
read_memory("core://agent", range="0:500")
```

> `chunk_id` and `range` cannot be used simultaneously.

---

<a id="create_memory"></a>

### `create_memory`

Create a memory under a parent URI.

```python
create_memory(
    parent_uri: str,              # Required
    content: str,                 # Required
    priority: int,                # Required (lower = higher priority)
    title: Optional[str] = None,  # Path name (a-z/0-9/_/- only)
    disclosure: str = ""          # Trigger condition
)
```

**Key behaviors**:

1. Write Guard runs automatically before creation
2. If Guard returns `NOOP` / `UPDATE` / `DELETE`, creation is blocked; `guard_target_uri` / `guard_target_id` are returned as suggestions
3. If Write Guard fail-closes from a transient error, the response includes `retryable=true` and `retry_hint`
4. `title` allows only letters, digits, underscores, hyphens
5. `content` longer than `100000` chars is rejected

**Example**:

```python
create_memory(
    "core://",
    "User prefers concise coding styles",
    priority=2,
    title="coding_style",
    disclosure="When writing or reviewing code"
)
```

---

<a id="update_memory"></a>

### `update_memory`

Update an existing memory.

```python
update_memory(
    uri: str,                          # Required
    old_string: Optional[str] = None,  # Patch mode
    new_string: Optional[str] = None,  # Patch mode
    append: Optional[str] = None,      # Append mode
    priority: Optional[int] = None,
    disclosure: Optional[str] = None
)
```

**Two editing modes (mutually exclusive)**:

| Mode | Parameters | Description |
|---|---|---|
| **Patch** | `old_string` + `new_string` | Find and replace. `old_string` must match exactly once |
| **Append** | `append` | Append text to the end |

> **There is no full-replace mode**. You must specify changes via `old_string` / `new_string` to prevent accidental overwrites.
>
> Run `read_memory` first to see what you're modifying.
>
> Any of `old_string` / `new_string` / `append` longer than `100000` chars is rejected.
>
> If the memory was modified by another session between your read and write, the server returns a `Memory version conflict` error. Re-read with `read_memory` and retry.
>
> If `guard_action=UPDATE` returns a valid `guard_target_id`, the update still proceeds **in place on the current URI**. The `guard_target_uri` is a hint, not an automatic redirect.

**Examples**:

```python
# Patch mode
update_memory(
    "core://agent/my_user",
    old_string="Old preference description",
    new_string="New preference description"
)

# Append mode
update_memory("core://agent", append="\n## New Section\nAppended content")

# Metadata only (does not trigger Write Guard)
update_memory("core://agent/my_user", priority=5)
```

---

<a id="delete_memory"></a>

### `delete_memory`

Delete a URI path.

```python
delete_memory(uri: str)
```

- Deletes the **URI path**, not the underlying memory body
- With multiple aliases, deleting one does not affect the others
- Returns structured JSON: `ok` / `deleted` / `uri` / `message`

---

<a id="add_alias"></a>

### `add_alias`

Add an alias URI for the same memory.

```python
add_alias(
    new_uri: str,
    target_uri: str,
    priority: int = 0,
    disclosure: Optional[str] = None
)
```

- Aliases can cross domains (e.g., link a `writer://` memory to `core://`)
- Control characters, invisible format chars, and surrogates are rejected
- If snapshot capture fails after the alias is written, the alias is rolled back to avoid half-success state

**Example**:

```python
add_alias(
    "core://timeline/2024/05/20",
    "core://agent/my_user/first_meeting",
    priority=1,
    disclosure="When I want to recall how we first met"
)
```

---

<a id="search_memory"></a>

### `search_memory`

```python
search_memory(
    query: str,                                  # Required (up to 8000 chars)
    mode: Optional[str] = None,                  # "keyword" / "semantic" / "hybrid"
    max_results: Optional[int] = None,
    candidate_multiplier: Optional[int] = None,
    include_session: Optional[bool] = None,
    filters: Optional[Dict] = None,
    scope_hint: Optional[str] = None,
    verbose: Optional[bool] = True
)
```

**Retrieval modes**:

| Mode | Description |
|---|---|
| `keyword` | FTS/BM25 first; unsafe queries fall back to escaped LIKE |
| `semantic` | Embedding-based search (requires `hash` / `api` / `router` / `openai`) |
| `hybrid` | Keyword + semantic; reranker applied if enabled |

**Filters**:

| Field | Type | Description |
|---|---|---|
| `domain` | `str` | Restrict to a domain |
| `path_prefix` | `str` | Restrict to a path prefix |
| `max_priority` | `int` | Only return memories with priority ≤ value |
| `updated_after` | `str` | ISO time filter |

**Response fields**:

| Field | Description |
|---|---|
| `query_effective` | Actual query text used |
| `intent` | `factual` / `exploratory` / `temporal` / `causal` / `unknown` |
| `mode_applied` | Actual retrieval mode used |
| `results` | Sorted by `score` descending |
| `results[].score` | Visible ranking score |
| `degrade_reasons` | Degradation reasons (if any) |

**Notes**:

- Default is `verbose=true` (returns debug info: `query_preprocess`, `intent_profile`, `session_first_metrics`); pass `verbose=false` for shorter results
- `candidate_multiplier` is a hint with a hard cap; check `candidate_multiplier_applied` in the response
- Reserved query syntax (`AND` / `OR` / `NOT` / `NEAR`) automatically falls back to the safe path

**Examples**:

```python
search_memory("coding style")

search_memory(
    "chapter arc",
    mode="hybrid",
    max_results=8,
    include_session=True,
    filters={"domain": "writer", "path_prefix": "chapter_1"}
)
```

---

<a id="compact_context"></a>

### `compact_context`

Compress current session context into a persistent summary.

```python
compact_context(
    reason: str = "manual",
    force: bool = False,
    max_lines: int = 12       # Minimum 3
)
```

**Outputs**:

- **Gist** — brief summary for quick recall
- **Trace** — raw key points retained

**Gist generation chain (auto-degrades)**:

1. `llm_gist` — LLM-generated (requires OpenAI-compatible API)
2. `extractive_bullets` — extracted bullets
3. `sentence_fallback` — sentence-level fallback

**Response fields**:

| Field | Description |
|---|---|
| `gist_method` | Gist generation strategy used |
| `quality` | Gist quality score (0–1) |
| `source_hash` | Trace source content hash |
| `index_queued` / `index_dropped` / `index_deduped` | Indexing queue stats |
| `degrade_reasons` | Degradation reasons |

> Same-session flushes are serialized through a file lock; concurrent calls return `already_in_progress`.

---

<a id="rebuild_index"></a>

### `rebuild_index`

Trigger index rebuild or sleep-time consolidation.

```python
rebuild_index(
    memory_id: Optional[int] = None,     # Omit to rebuild all
    reason: str = "manual",
    wait: bool = False,
    timeout_seconds: int = 30,
    sleep_consolidation: bool = False
)
```

**Two modes**:

| Mode | Condition | Behavior |
|---|---|---|
| **Index Rebuild** | `sleep_consolidation=False` (default) | Run rebuild_index / reindex_memory queue tasks |
| **Sleep-time Consolidation** | `sleep_consolidation=True` | Offline scan for fragments and duplicates, generate cleanup preview |

**Sleep-time consolidation**:

- Defaults to preview-only (no actual deletion/writing)
- Set `RUNTIME_SLEEP_DEDUP_APPLY=1` to execute duplicate cleanup
- Set `RUNTIME_SLEEP_FRAGMENT_ROLLUP_APPLY=1` to write rollup gists
- `memory_id` and `sleep_consolidation=True` **cannot be used together**

**Queue saturation**:

- HTTP returns `503` + `index_job_enqueue_failed`
- MCP returns `ok=false` + `error=queue_full`

---

<a id="index_status"></a>

### `index_status`

Query index availability and runtime status. No parameters.

**Return fields**:

| Field | Description |
|---|---|
| `index_available` | Whether the index is available |
| `degraded` | Whether degraded |
| `runtime.index_worker` | Queue depth, active tasks, success/failure/cancel stats |
| `runtime.sleep_consolidation` | Sleep consolidation schedule status |
| `runtime.write_lanes` | Write lane status |

---

## Common Return Fields

### Write Guard Fields

`create_memory` and `update_memory` return:

| Field | Possible Values | Description |
|---|---|---|
| `guard_action` | `ADD` / `UPDATE` / `NOOP` / `DELETE` / `BYPASS` | Decision action |
| `guard_reason` | string | Decision reason |
| `guard_method` | `keyword` / `embedding` / `llm` / `write_guard_llm` / `unknown` / `none` / `exception` | Detection method |
| `guard_target_uri` / `guard_target_id` | string / integer | Suggested target to inspect (hint, not auto-redirect) |

### Indexing Queue Stats

`create_memory`, `update_memory`, `compact_context` return:

| Field | Description |
|---|---|
| `index_queued` | Actual number queued |
| `index_dropped` | Tasks that failed to queue |
| `index_deduped` | Tasks deduped before queueing |

> When `index_dropped > 0`, check `degrade_reasons` for alerts.

### Write-Lane Timeout

For `create_memory` / `update_memory` / `delete_memory` / `add_alias` / `compact_context`:

- When the write lane is saturated, the response carries `reason=write_lane_timeout`, `retryable=true`, `retry_hint`
- The HTTP API equivalent is a structured `503`

---

## Degradation Mechanism

On the retrieval path, when remote Embedding / Reranker services are unavailable, the system **auto-degrades** and returns `degrade_reasons`.  
On the write path, `write_guard_exception` fails closed and rejects the write.

**Common reasons**:

| Reason | Description |
|---|---|
| `embedding_fallback_hash` | Embedding API unavailable, falling back to local hash |
| `embedding_request_failed` | Embedding request failed |
| `embedding_dim_mismatch_requires_reindex` | Vector dimensions don't match config; reindex required |
| `vector_dim_mixed_requires_reindex` / `vector_dim_mismatch_requires_reindex` | Mixed dimensions in current scope; reindex required |
| `reranker_request_failed` | Reranker request failed |
| `path_revalidation_lookup_failed` | Path revalidation lookup failed; result was dropped |
| `write_guard_exception` | Write Guard error; write rejected (fail-closed) |
| `query_preprocess_failed` | Query preprocessing failed |
| `index_enqueue_dropped` | Indexing task failed to queue |

> `embedding_request_failed` / `reranker_request_failed` may carry finer-grained suffixes (`:timeout`, `:http_status:503`, `:api:timeout`). Read the base marker first, then the suffix.
>
> When degradation is detected, try `rebuild_index(wait=True)` + `index_status()` to recover. Dimension warnings follow the **current query scope**, so unrelated domains don't trigger false rebuild prompts.

---

## Recommended Workflow

### Standard Session Flow

```
1. Startup    →  read_memory("system://boot")
                 Load core memories + recent updates

2. Recall     →  search_memory(query, include_session=True)
                 read_memory(uri) when URI is known

3. Pre-write  →  read_memory(uri) / search_memory
                 Confirm no duplicates → create_memory / update_memory

4. Compact    →  compact_context(force=False)
                 System decides if compression is needed

5. Recover    →  rebuild_index(wait=True) → index_status()
                 On degradation, rebuild and confirm
```

For detailed Skills orchestration: [skills/MEMORY_PALACE_SKILLS_EN.md](skills/MEMORY_PALACE_SKILLS_EN.md)

---

## Retrieval Configuration

Profiles C/D use hybrid retrieval (`keyword + semantic + reranker`) and need OpenAI-compatible API config:

```bash
# Embedding
RETRIEVAL_EMBEDDING_BACKEND=none      # none / hash / router / api / openai
RETRIEVAL_EMBEDDING_API_BASE=
RETRIEVAL_EMBEDDING_API_KEY=
RETRIEVAL_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_EMBEDDING_DIM=<provider-vector-dim>

# Reranker
RETRIEVAL_RERANKER_ENABLED=false
RETRIEVAL_RERANKER_API_BASE=
RETRIEVAL_RERANKER_API_KEY=
RETRIEVAL_RERANKER_MODEL=your-reranker-model-id

# Weights
RETRIEVAL_RERANKER_WEIGHT=0.40
RETRIEVAL_HYBRID_KEYWORD_WEIGHT=0.7
RETRIEVAL_HYBRID_SEMANTIC_WEIGHT=0.3
```

> **Primary tuning parameter**: `RETRIEVAL_RERANKER_WEIGHT`. The `.env.example` default is `0.40`; shipped `Profile C/D` templates use `0.30` / `0.35`.
>
> `RETRIEVAL_EMBEDDING_BACKEND` only controls Embedding; Reranker has no `_BACKEND` switch. Reranker parameters prefer `RETRIEVAL_RERANKER_*`, then fall back to `ROUTER_*`, then `OPENAI_*`.
>
> Advanced configuration (`INTENT_LLM_*`, `RETRIEVAL_MMR_*`, `CORS_ALLOW_*`, etc.) is in `.env.example`. Full profile configuration: [DEPLOYMENT_PROFILES_EN.md](DEPLOYMENT_PROFILES_EN.md).
