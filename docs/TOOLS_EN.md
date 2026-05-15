# Memory Palace — MCP Tool Reference Manual

> **Memory Palace** provides persistent memory capabilities for AI Agents through [MCP (Model Context Protocol)](https://modelcontextprotocol.io/).
> This document is a complete reference for all 9 MCP tools, suitable for new users.

---

## Table of Contents

- [Quick Reference Table](#quick-reference-table)
- [Core Concepts](#core-concepts)
- [Tool Details](#tool-details)
  - [read_memory — Read Memory](#read_memory)
  - [create_memory — Create Memory](#create_memory)
  - [update_memory — Update Memory](#update_memory)
  - [delete_memory — Delete Memory](#delete_memory)
  - [add_alias — Add Alias](#add_alias)
  - [search_memory — Search Memory](#search_memory)
  - [compact_context — Session Compaction](#compact_context)
  - [rebuild_index — Index Rebuild](#rebuild_index)
  - [index_status — Index Status Query](#index_status)
- [Common Return Fields](#common-return-fields)
- [Degradation Mechanism](#degradation-mechanism)
- [Recommended Workflow (Skills Strategy)](#recommended-workflow)
- [Retrieval Configuration (Profile C/D)](#retrieval-configuration)

---

## Quick Reference Table

| Tool | Category | Description |
|---|---|---|
| `read_memory` | 📖 Read | Read memory content by URI; supports full/chunked/range reads |
| `create_memory` | ✏️ Write | Create a new memory node under a specified parent URI |
| `update_memory` | ✏️ Write | Update content, priority, or disclosure of existing memory |
| `delete_memory` | ✏️ Write | Delete a memory path by its URI |
| `add_alias` | ✏️ Write | Create another URI entry (alias) for the same memory |
| `search_memory` | 🔍 Search | Search memory via keyword, semantic, or hybrid modes |
| `compact_context` | 🧹 Governance | Compress current session context into persistent summaries |
| `rebuild_index` | 🔧 Maintenance | Trigger index rebuild or sleep-time consolidation tasks |
| `index_status` | 🔧 Maintenance | Query index availability, queue depth, and runtime status |

---

## Core Concepts

### URI Address System

Memory Palace uses the `domain://path` format to address every memory:

```
core://agent              ← "agent" path under the core domain
writer://chapter_1/scene  ← Hierarchical path under the writer domain
system://boot             ← Built-in system URI (read-only)
```

The URI here means a **Memory Palace memory address**, not an operating-system file path. Windows file paths such as `C:/notes.txt` or `C:\notes.txt` are now explicitly rejected; if you mean a memory, use `core://...` rather than passing a local disk path into an MCP tool.

Literal percent sequences are also valid path text. In plain terms: a path named
`foo%20bar` stays literal, while public tools can still resolve an existing
memory through encoded spaces or slashes such as `core://foo%20bar` or
`core://chapter_1%2Fscene_2` when those spellings map to the stored path.
Percent-decoded Windows filesystem paths such as `C%3A/...` are rejected too.

**Common Domains:**

- `core` — Core memories (Personality, preferences, key facts)
- `writer` — Writing domain (Stories, chapters)
- `system` — System reserved (`boot` / `index` / `index-lite` / `audit` / `recent`), non-writable

> 💡 Priority (`priority`) is an integer where **lower numbers mean higher priority** (0 is highest). It determines retrieval ranking and precedence during conflict resolution. The current public tool contract expects a real integer here; values such as `true/false` or `1.9` are rejected instead of being coerced.

### Write Guard

`create_memory` and `update_memory` automatically invoke **Write Guard** before execution to:

- Detect duplicate content (avoiding redundant writes)
- Suggest merging into existing memories (returning `UPDATE` / `NOOP` actions)

Write Guard decision methods may include `keyword`, `embedding`, `llm`, `write_guard_llm`, `unknown`, `none`, or `exception`, depending on current configuration and service availability.

---

## Tool Details

<a id="read_memory"></a>

### 📖 `read_memory`

**Function:** Reads memory content by URI.

**Function Signature:**
<!-- Source: backend/mcp_server.py -->
```python
read_memory(
    uri: str,                       # Required: Memory URI
    chunk_id: Optional[int] = None, # Optional: Chunk index (0-based)
    range: Optional[str] = None,    # Optional: Character range (e.g., "0:500")
    max_chars: Optional[int] = None, # Optional: Maximum characters to return
    include_ancestors: Optional[bool] = False # Optional: Include parent chain memories (non-system URIs only)
)
```

**System URIs (Special Addresses):**

| URI | Purpose | When to Use |
|---|---|---|
| `system://boot` | Load core memories + recent updates | Call at every **session startup** |
| `system://index` | View full index of all memories | To **overview all memories** |
| `system://index-lite` | View gist lightweight index summary | For **low-cost quick overview** |
| `system://audit` | View consolidated observability/audit summary | For **troubleshooting and runtime inspection** |
| `system://recent` | 10 most recently modified memories | To see **latest changes** quickly |
| `system://recent/N` | N most recently modified memories | Custom count (up to 100) |

**Return Format:**

- **Default Mode** (no `chunk_id` / `range` / `max_chars`): Returns formatted plain text
- **Segmented Mode** (any optional parameter provided): Returns a JSON string containing `selection` metadata

**Usage Examples:**

```python
# Load core memories at session startup
read_memory("system://boot")

# Read a specific memory
read_memory("core://agent/my_user")

# Read a chunk of a large entry (Chunk 0)
read_memory("core://agent", chunk_id=0)

# Read by character range
read_memory("core://agent", range="0:500")
```

> 📌 Public tools keep a raw-path-first, decoded-variant-second lookup rule for
> existing memories. This means encoded spaces/slashes can still reach an
> existing path, while a literal percent path keeps its literal spelling.

> ⚠️ `chunk_id` and `range` **cannot be used simultaneously**.

---

<a id="create_memory"></a>

### ✏️ `create_memory`

**Function:** Creates a new memory under a parent URI.

**Function Signature:**
<!-- Source: backend/mcp_server.py -->
```python
create_memory(
    parent_uri: str,              # Required: Parent URI (e.g., "core://agent")
    content: str,                 # Required: Memory body content
    priority: int,                # Required: Retrieval priority (lower = higher priority)
    title: Optional[str] = None,  # Optional: Path name (a-z/0-9/_/- only)
    disclosure: str = ""          # Optional: Trigger condition description
)
```

**Key Behaviors:**

1. Automatically performs a **Write Guard** check before creation.
2. If Guard decides `NOOP` / `UPDATE` / `DELETE`, creation is blocked, and `guard_target_uri` / `guard_target_id` are returned as suggestions.
3. If creation is fail-closed because Write Guard is temporarily unavailable or degraded, the response may also include `retryable=true` and `retry_hint`.
4. `title` only allows letters, numbers, underscores, and hyphens (no spaces or special characters).
5. If `title` is omitted, the system auto-assigns a numeric ID.
6. `content` is now also length-checked at the MCP boundary; values longer than `100000` characters are rejected before the request enters DB / Write Guard work.
7. `parent_uri` follows the same URI contract as the read/delete tools: encoded spaces or slashes can still target an existing parent path, while a literal percent path remains literal.

**Usage Examples:**

```python
# Create a core memory
create_memory(
    "core://",
    "User prefers concise coding styles",
    priority=2,
    title="coding_style",
    disclosure="When writing or reviewing code"
)

# Create a sub-memory under an existing path
create_memory(
    "core://agent",
    "Greet the user at the start of every conversation",
    priority=1,
    title="greeting_rule",
    disclosure="At session startup"
)
```

---

<a id="update_memory"></a>

### ✏️ `update_memory`

**Function:** Updates content or metadata of an existing memory.

**Function Signature:**
<!-- Source: backend/mcp_server.py -->
```python
update_memory(
    uri: str,                          # Required: Target URI
    old_string: Optional[str] = None,  # Patch Mode: Original text to be replaced
    new_string: Optional[str] = None,  # Patch Mode: New text to replace with
    append: Optional[str] = None,      # Append Mode: Text to append to the end
    priority: Optional[int] = None,    # Optional: New priority
    disclosure: Optional[str] = None   # Optional: New trigger condition
)
```

**Two Editing Modes (Mutually Exclusive):**

| Mode | Parameters | Description |
|---|---|---|
| **Patch Mode** | `old_string` + `new_string` | Precisely finds `old_string` and replaces it with `new_string`. `old_string` must have exactly one match. |
| **Append Mode** | `append` | Appends text to the end of the existing content. |

> ⚠️ **There is no full-replacement mode.** You must explicitly specify changes via `old_string` / `new_string` to prevent accidental overwrites.
>
> ⚠️ **Please `read_memory` before updating** to ensure you understand what is being modified.
>
> ⚠️ `old_string` / `new_string` / `append` are now also length-checked at the MCP boundary; any one of them exceeding `100000` characters is rejected before DB / Write Guard work starts.
>
> 📌 If a content update returns `guard_action=UPDATE` with a valid `guard_target_id`, `update_memory` still continues as an **in-place update of the current URI**. In plain language: `guard_target_uri` / `guard_target_id` is a “there is a similar target, take a look” hint, not an automatic retargeting of this write to another URI.
>
> 📌 If `guard_action=UPDATE` does not include a valid `guard_target_id`, the tool still blocks the update fail-closed.

**Usage Examples:**

```python
# Patch Mode: Precise text replacement
update_memory(
    "core://agent/my_user",
    old_string="Old preference description",
    new_string="New preference description"
)

# Append Mode: Add content
update_memory("core://agent", append="\n## New Section\nThis is appended content")

# Update metadata only (does not trigger Write Guard)
update_memory("core://agent/my_user", priority=5)
```

---

<a id="delete_memory"></a>

### ✏️ `delete_memory`

**Function:** Deletes a specified URI path.

**Function Signature:**
<!-- Source: backend/mcp_server.py -->
```python
delete_memory(
    uri: str  # Required: URI to delete
)
```

**Notes:**

- This deletes the **URI path**, not the underlying memory body version chain.
- If a memory has multiple alias paths, deleting one does not affect others.
- It is recommended to `read_memory` to confirm content before deletion.
- The current return value is a **structured JSON string**, with common fields such as `ok`, `deleted`, `uri`, and `message`.
- The same URI compatibility applies here too: encoded spaces/slashes can still reach an existing path, while a literal percent path keeps its literal spelling.

**Usage Example:**

```python
delete_memory("core://agent/old_note")
```

---

<a id="add_alias"></a>

### ✏️ `add_alias`

**Function:** Adds an alias URI for the same memory to improve reachability.

**Function Signature:**
<!-- Source: backend/mcp_server.py -->
```python
add_alias(
    new_uri: str,                       # Required: New alias URI
    target_uri: str,                    # Required: Existing memory URI
    priority: int = 0,                  # Optional: Retrieval priority for this alias
    disclosure: Optional[str] = None    # Optional: Trigger condition for this alias
)
```

**Description:** Aliases can be cross-domain—for example, linking a memory from `writer://` to the `core://` domain.

**Current Boundaries:**

- `new_uri` / `target_uri` go through the same URI validation used by the other public write tools; control chars, invisible format chars, and surrogates are rejected
- if the alias row is written first but snapshot capture fails afterwards, the current implementation compensates by rolling back that alias path instead of leaving a half-success state behind

**Usage Example:**

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

### 🔍 `search_memory`

**Function:** Searches memories via keyword, semantic, or hybrid modes.

**Function Signature:**
<!-- Source: backend/mcp_server.py -->
```python
search_memory(
    query: str,                                  # Required: Search query (current limit: 8000 chars)
    mode: Optional[str] = None,                  # Optional: "keyword" / "semantic" / "hybrid"
    max_results: Optional[int] = None,           # Optional: Maximum results to return
    candidate_multiplier: Optional[int] = None,  # Optional: Candidate pool multiplier
    include_session: Optional[bool] = None,      # Optional: Whether to include current session memories
    filters: Optional[Dict] = None,              # Optional: Filter conditions
    scope_hint: Optional[str] = None,            # Optional: Query-side scope hint (domain/path_prefix/URI prefix)
    verbose: Optional[bool] = True               # Optional: Whether to return full debug metadata
)
```

> 📌 `candidate_multiplier` is only a first-round expansion hint, not an unlimited pool-size switch. The current implementation still keeps a hard cap; the public response now exposes `candidate_multiplier_applied`, while backend metadata still carries `candidate_limit_applied` for the hard ceiling.

**Retrieval Modes:**

| Mode | Description |
|---|---|
| `keyword` | Safe FTS/BM25 first; unsafe queries automatically fall back to the escaped LIKE path (default) |
| `semantic` | Embedding-based semantic search (requires an enabled embedding pipeline: `hash` / `api` / `router` / `openai`) |
| `hybrid` | Combined keyword + semantic retrieval; followed by reranking if Reranker is enabled |

> `RRF_ENABLED=false` is the current default. When explicitly enabled, RRF only fuses allowlisted channels such as `RRF_CHANNELS=fts5,vector`, with `RRF_K=60` by default; `RRF_LOG_CHANNEL_CONTRIBUTIONS=false` means channel-contribution logging stays off by default. `ENTITY_RERANK_WEIGHT=0.0` is also disabled by default; the entity signal is a boost after fusion, not a third RRF channel.

**Filters (`filters`):**

| Field | Type | Description |
|---|---|---|
| `domain` | `str` | Restrict to domain, e.g., `"core"` |
| `path_prefix` | `str` | Restrict to path prefix, e.g., `"agent/my_user"` |
| `max_priority` | `int` | Return only memories with priority ≤ this value |
| `updated_after` | `str` | ISO time filter, e.g., `"2026-01-31T12:00:00Z"` |

**Response Field Descriptions:**

| Field | Description |
|---|---|
| `query_effective` | The actual query text used |
| `query_preprocess` | Query preprocessing info |
| `intent` | Intent classification: `factual` / `exploratory` / `temporal` / `causal` / `unknown` |
| `mode_applied` | Actual retrieval mode used |
| `results` | List of search results; the returned order now matches the exposed `results[].score` field |
| `results[].score` | The visible ranking score; `results` are returned in descending order of this field by default |
| `degrade_reasons` | Degradation reasons (if any) |
| `session_first_metrics` | Session-first merge and path-revalidation counters such as `stale_result_dropped`, `session_queue_refreshed`, and `revalidate_lookup_failed` |

**Practical Note:**

- The default is `verbose=true`, which keeps debug-heavy fields such as `query_preprocess`, `intent_profile`, `session_first_metrics`, and `backend_metadata`
- If you only care about the final results, scores, and degrade reasons, pass `verbose=false` to keep the response shorter and more MCP-context-friendly
- If the final path-state revalidation itself hits a lookup error, the current implementation drops that result and appends `path_revalidation_lookup_failed` to `degrade_reasons`; it no longer fail-opens by returning a stale URI as if it were still current
- `candidate_multiplier` is still only a hint about how far you want the first-round pool to expand; check `candidate_multiplier_applied` in the public response first and `candidate_limit_applied` in backend metadata for the hard ceiling; on the `fast` interaction tier the first-round multiplier is now hard-capped at `4`, and later intent heuristics no longer widen it again
- `query` now also goes through an FTS-safety check first: reserved control words such as `AND` / `OR` / `NOT` / `NEAR`, or wildcard-heavy inputs, no longer silently steer FTS semantics; the current implementation falls back for that request instead of turning ordinary user text into a global retrieval failure

**Usage Examples:**

```python
# Simple keyword search
search_memory("coding style")

# Hybrid search + domain filtering
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

### 🧹 `compact_context`

**Function:** Compresses current session context into a persistent memory summary.

**Function Signature:**
<!-- Source: backend/mcp_server.py -->
```python
compact_context(
    reason: str = "manual",  # Optional: Compression reason label
    force: bool = False,     # Optional: Force compression (ignore thresholds)
    max_lines: int = 12      # Optional: Maximum lines for summary (min 3)
)
```

**Summary Outputs:**

- **Gist**: Brief summary for quick recall.
- **Trace**: Original bullet points of key context for record-keeping.

**Gist Generation Pipeline (Auto-degrades in order):**

1. `llm_gist` — Call LLM to generate summary (requires OpenAI-compatible API in `.env`)
2. `extractive_bullets` — Extracted key points
3. `sentence_fallback` — Sentence-level fallback

**Practical Note:**

- In the current verified path, both repo-local stdio and Docker `/sse` can persist `llm_gist` end-to-end
- If the remote chat path times out or is unavailable, `compact_context` degrades to the next fallback instead of pretending the LLM step succeeded
- Normal backend / SSE / repo-local stdio shutdown paths now also do one best-effort drain for pending auto-flush summaries; if write_guard blocks that write, or the drain fails during shutdown, the system skips it instead of forcing a dirty last-minute write
- Same-session flushes now also take a database-file-backed per-session process lock; if another local process is already compacting that session, the current call returns `already_in_progress`

**Response Fields:**

| Field | Description |
|---|---|
| `gist_method` | Current Gist generation strategy |
| `quality` | Gist quality score (0–1) |
| `source_hash` | Trace source content hash (for consistency checks) |
| `index_queued` / `index_dropped` / `index_deduped` | Indexing queue statistics |
| `degrade_reasons` | Degradation reasons (if any) |

**Usage Examples:**

```python
# Let the system decide if compression is needed
compact_context(force=False)

# Force compression and limit summary lines
compact_context(reason="long_session", force=True, max_lines=8)
```

---

<a id="rebuild_index"></a>

### 🔧 `rebuild_index`

**Function:** Triggers retrieval index rebuild or sleep-time consolidation tasks.

**Function Signature:**
<!-- Source: backend/mcp_server.py -->
```python
rebuild_index(
    memory_id: Optional[int] = None,     # Optional: Target memory ID (omitted = rebuild all)
    reason: str = "manual",              # Optional: Audit label
    wait: bool = False,                  # Optional: Whether to wait for task completion
    timeout_seconds: int = 30,           # Optional: Wait timeout (seconds, used if wait=True)
    sleep_consolidation: bool = False    # Optional: Trigger sleep-time consolidation task
)
```

**Two Modes:**

| Mode | Condition | Behavior |
|---|---|---|
| **Index Rebuild** | `sleep_consolidation=False` (Default) | Executes `rebuild_index` / `reindex_memory` queue tasks |
| **Sleep-time Consolidation** | `sleep_consolidation=True` | Offline scan for fragments and duplicates, generating a cleanup preview |

**Sleep-time Consolidation Details:**

- Scans for orphan candidates and generates deduplication previews.
- Generates rollup previews for fragmented paths.
- Defaults to **preview-only** (no actual deletion/writing):
  - Set `RUNTIME_SLEEP_DEDUP_APPLY=1` to execute duplicate cleanup.
  - Set `RUNTIME_SLEEP_FRAGMENT_ROLLUP_APPLY=1` to write rollup gists.
- ⚠️ `memory_id` and `sleep_consolidation=True` **cannot be used together**.

**Queue Saturation Protection:**

- HTTP maintenance interface returns `503` + `index_job_enqueue_failed`.
- MCP returns `ok=false` + `error=queue_full`.

**Usage Examples:**

```python
# Rebuild all and wait for completion
rebuild_index(wait=True)

# Rebuild index for a single memory
rebuild_index(memory_id=42, wait=True)

# Trigger sleep-time consolidation (preview only)
rebuild_index(sleep_consolidation=True, wait=True)
```

---

<a id="index_status"></a>

### 🔧 `index_status`

**Function:** Queries index availability, statistics, and runtime status.

**Function Signature:**
<!-- Source: backend/mcp_server.py -->
```python
index_status()  # No parameters
```

**Return Information Includes:**

| Field | Description |
|---|---|
| `index_available` | Whether the index is available |
| `degraded` | Whether it is degraded |
| `runtime.index_worker` | Queue depth, active tasks, success/failure/cancellation stats |
| `runtime.sleep_consolidation` | Sleep consolidation schedule status (`enabled` / `scheduled` / `reason`) |
| `runtime.write_lanes` | Write lane status |

**Usage Example:**

```python
# Check index health status
index_status()
```

---

## Common Return Fields

### Write Guard Fields

Return values for `create_memory` and `update_memory` include the following Write Guard info:

| Field | Possible Values | Description |
|---|---|---|
| `guard_action` | `ADD` / `UPDATE` / `NOOP` / `DELETE` / `BYPASS` | Decision action from Guard |
| `guard_reason` | String | Reason for the decision |
| `guard_method` | `keyword` / `embedding` / `llm` / `write_guard_llm` / `unknown` / `none` / `exception` | Detection method used |
| `guard_target_uri` / `guard_target_id` | String / Integer | Suggested target to inspect or switch to; they are hints, not an automatic write redirect |

### Indexing Queue Stats Fields

`create_memory`, `update_memory`, and `compact_context` also return:

| Field | Description |
|---|---|
| `index_queued` | Actual number of indexing tasks queued |
| `index_dropped` | Tasks failed to queue (e.g., queue full) |
| `index_deduped` | Tasks not queued due to deduplication |

> ⚠️ When `index_dropped > 0`, it means some indexing tasks failed to enter the queue. The client should treat this as a degradation signal, checking `degrade_reasons` for alerts or compensation.

### Write-Lane Timeout

For write tools such as `create_memory`, `update_memory`, `delete_memory`, `add_alias`, and `compact_context`:

- when the write lane is saturated, the response now carries `reason=write_lane_timeout`
- the same response also carries `retryable=true` and `retry_hint`
- the HTTP API equivalents surface the same condition as a structured `503`

---

## Degradation Mechanism

During retrieval, if remote Embedding / Reranker services are unavailable or return errors, the system **automatically degrades** and returns a `degrade_reasons` field in the response.  
During writing, if a `write_guard_exception` occurs, the system fails-closed, rejecting the write and logging an audit (this is not "auto-degradation for continuing the write").

**Common Degradation Reasons:**

| Reason | Description |
|---|---|
| `embedding_fallback_hash` | Embedding API unavailable, falling back to local hash |
| `embedding_request_failed` | Embedding request failed |
| `embedding_dim_mismatch_requires_reindex` | The vectors inside the current query scope do not match the active embedding dimension; reindex is required |
| `vector_dim_mixed_requires_reindex` / `vector_dim_mismatch_requires_reindex` | The current query scope contains mixed vector dimensions, or that scope's vectors do not match the active config; reindex is required |
| `reranker_request_failed` | Reranker request failed |
| `path_revalidation_lookup_failed` | Final path-state revalidation failed; the affected result was dropped instead of being exposed fail-open under a stale URI |
| `write_guard_exception` | Write Guard execution error; write rejected (fail-closed) |
| `query_preprocess_failed` | Query preprocessing failed |
| `index_enqueue_dropped` | Indexing task failed to queue |

> `embedding_request_failed` / `reranker_request_failed` still keep their base markers, but may now also carry narrower suffixes such as `:timeout`, `:http_status:503`, or `:api:timeout` on the embedding path. For troubleshooting, read the base marker first, then use the suffix for the exact failure shape.
>
> 💡 **Suggestion:** Client logic should use the `degrade_reasons` field as an alert signal. If degradation is detected, try calling `rebuild_index(wait=True)` + `index_status()` to attempt recovery. Vector-dimension warnings now follow the **current query scope**, so unrelated domains should no longer trigger a false rebuild warning.

---

## Recommended Workflow

The following workflow is a general sequence for MCP usage. For specific validated clients or known edge cases, refer to the official [skills/SKILLS_QUICKSTART_EN.md](skills/SKILLS_QUICKSTART_EN.md):

### Standard Session Process

```
┌──────────────┐
│  1. Startup   │  read_memory("system://boot")
│              │  → Load core memories + recent updates
└──────┬───────┘
       ▼
┌──────────────┐
│  2. Recall    │  search_memory(query, include_session=True) / read_memory(uri)
│              │  → Search when the URI is uncertain; go straight to read when the target URI is already known
└──────┬───────┘
       ▼
┌──────────────┐
│  3. Pre-write │  read_memory(uri) / search_memory → confirm no duplicates → create_memory / update_memory
│     Check    │  → Read the known target directly; otherwise search first to avoid redundant memories
└──────┬───────┘
       ▼
┌──────────────┐
│  4. Compact   │  compact_context(force=False)
│              │  → System auto-decides if compression is needed
└──────┬───────┘
       ▼
┌──────────────┐
│  5. Recover   │  rebuild_index(wait=True) → index_status()
│              │  → Rebuild index and confirm status if degradation detected
└──────────────┘
```

For detailed Skills orchestration strategies, see: [skills/MEMORY_PALACE_SKILLS_EN.md](skills/MEMORY_PALACE_SKILLS_EN.md)

---

## Retrieval Configuration

Memory Palace supports multiple retrieval Profiles. Profiles C and D use a hybrid retrieval path (`keyword + semantic + reranker`) and require additional configuration.

### Required Environment Variables

Configure OpenAI-compatible API parameters in `.env`:
<!-- Ref: .env.example lines 57-77 -->

```bash
# ── Embedding Config ──
RETRIEVAL_EMBEDDING_BACKEND=none      # Options: none / hash / router / api / openai
RETRIEVAL_EMBEDDING_API_BASE=         # API Base URL
RETRIEVAL_EMBEDDING_API_KEY=          # API Key
RETRIEVAL_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_EMBEDDING_DIM=<provider-vector-dim>  # User-supplied real vector dimension

# ── Reranker Config ──
RETRIEVAL_RERANKER_ENABLED=false      # Enable Reranker
RETRIEVAL_RERANKER_API_BASE=          # API Base URL
RETRIEVAL_RERANKER_API_KEY=           # API Key
RETRIEVAL_RERANKER_MODEL=your-reranker-model-id

# ── Weight Tuning ──
RETRIEVAL_RERANKER_WEIGHT=0.40        # Reranker weight (primary tuning parameter)
RETRIEVAL_HYBRID_KEYWORD_WEIGHT=0.7   # Keyword weight
RETRIEVAL_HYBRID_SEMANTIC_WEIGHT=0.3  # Semantic weight
```

> 💡 The **primary tuning parameter** is `RETRIEVAL_RERANKER_WEIGHT`. The `0.40` shown here is the generic `.env.example` default; shipped `Profile C/D` templates can still pin their own explicit values. Even for locally deployed Embedding / Rerankers, OpenAI-compatible API parameters must be configured.
>
> Configuration semantics: `RETRIEVAL_EMBEDDING_BACKEND` only controls the embedding path; there is no `RETRIEVAL_RERANKER_BACKEND` switch. Reranker parameters prioritize `RETRIEVAL_RERANKER_*`, falling back to `ROUTER_*` (and finally `OPENAI_*` base/key) if missing.
>
> `RETRIEVAL_EMBEDDING_DIM` is now also forwarded as `dimensions` on OpenAI-compatible `/embeddings` requests; if a provider explicitly rejects that field, the runtime retries once without `dimensions`. Regardless of whether that retry happens, `RETRIEVAL_EMBEDDING_DIM` should still match the actual vector size returned in the end.
>
> The model IDs here are placeholders. Memory Palace is not tied to a specific provider; please fill in the actual model IDs available in your OpenAI-compatible service.
>
> For advanced configuration (e.g., `INTENT_LLM_*`, `RETRIEVAL_MMR_*`, `CORS_ALLOW_*`, runtime observability/sleep consolidation switches), refer to `.env.example`. This section only lists the most common primary configurations.
>
> Preset Profile configuration files are located in the `deploy/profiles/` directory (macOS / Windows / Docker).

---

*This document is generated based on the `backend/mcp_server.py` source code. All parameter signatures and behavioral descriptions are traceable to the code implementation.*
