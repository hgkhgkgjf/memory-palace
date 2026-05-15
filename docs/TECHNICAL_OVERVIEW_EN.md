# Memory Palace Technical Overview

This document is intended for technical users who need to understand the internal system implementation or perform secondary development, covering the backend, frontend, MCP tool layer, runtime, and deployment architecture.

---

## 1. Technology Stack

| Layer | Technology | Version Requirement | Role |
|---|---|---|---|
| Backend | FastAPI + SQLAlchemy + SQLite | FastAPI ≥0.109 · SQLAlchemy ≥2.0 · aiosqlite ≥0.19 | Memory R/W, retrieval, review, maintenance |
| MCP | `mcp.server.fastmcp` | mcp ≥0.1 | Exposes a unified tool interface for Codex / Claude Code / Gemini CLI / OpenCode; for IDE hosts such as `Cursor / Windsurf / VSCode-host / Antigravity`, the recommended path is repo-local `AGENTS.md` plus an MCP config snippet |
| Frontend | React + Vite + TailwindCSS + Framer Motion | React ≥18.2 · Vite ≥7.3 · TailwindCSS ≥3.3 · Framer Motion ≥12.34 | Visual management Dashboard |
| Runtime | Built-in queue and worker | — | Write serialization, index rebuilding, vitality decay, sleep consolidation |
| Deployment | Docker Compose + profile scripts | Docker ≥20 · Compose ≥2.0 (a recent `docker compose` plugin is recommended when running the repository compose files manually) | Quick deployment with A/B/C/D tiers |

Core dependencies can be found in `backend/requirements.txt` and `frontend/package.json`.

Boundary note: the repository compose files use nested `${...:-...}` defaults for volume names. On older Compose implementations, a failure here is usually a parsing-compatibility issue rather than a backend startup bug. When that happens, prefer `docker_one_click.sh/.ps1`, or explicitly set `MEMORY_PALACE_DATA_VOLUME`, `MEMORY_PALACE_SNAPSHOTS_VOLUME`, and `COMPOSE_PROJECT_NAME` before manual startup.

---

## 2. Backend Structure

```
backend/
├── main.py               # FastAPI entry point, route registration, lifecycle management
├── mcp_server.py          # Public MCP entrypoint; tool signatures stay compatible while internals are split under mcp/*
├── runtime_state.py       # Management of write lane, index worker, vitality decay, cleanup review
├── run_sse.py             # SSE transport layer, supports API Key authentication gating
├── mcp_wrapper.py         # MCP startup wrapper
├── api/
│   ├── __init__.py        # Route export
│   ├── browse.py          # Memory browsing and writing interfaces (prefix: /browse)
│   ├── review.py          # Review, rollback, and integration interfaces (prefix: /review)
│   ├── maintenance.py     # Maintenance, observation, and vitality cleanup interfaces (prefix: /maintenance)
│   ├── layering.py        # L2 layer-summary interfaces (prefix: /api/layering)
│   ├── forgetting.py      # Forgetting simulation, candidate queue, and reviewed archive interfaces (prefix: /api/forgetting)
│   ├── search_quality.py  # Search Quality panel API (prefix: /search)
│   ├── setup.py           # First-run setup and local .env write interfaces (prefix: /setup)
│   └── utils.py           # Diff calculation tools (prefers diff-match-patch, falls back to difflib.HtmlDiff)
├── db/
│   ├── __init__.py        # Client factory (get_sqlite_client / close_sqlite_client)
│   ├── sqlite_client.py   # Compatibility facade; CRUD, retrieval, and governance behavior are still exposed here
│   ├── models.py          # Central SQLAlchemy model definitions
│   ├── repositories/      # Split data-access helpers
│   ├── search/            # FTS5/vector/RRF/entity-boost retrieval channels
│   ├── embeddings/        # Embedding drift detection and helpers
│   ├── migration_gate.py  # Migration dry-run / backup / export guardrails
│   ├── snapshot.py        # Snapshot manager (records pre-state by session, serializes same-session snapshot writes, and applies conservative session-level retention/GC: prunes old sessions by age/count, protects the current session, and skips older sessions whose write lock cannot be acquired; missing/damaged manifests can also be rebuilt when the original database scope is preserved; Review visibility still follows the current database scope)
│   ├── migration_runner.py# Automatic database migration executor
│   └── migrations/        # SQL migration script directory
├── core/
│   ├── facade.py          # MemoryCore compatibility facade; delegation only
│   ├── layering_engine.py # Read-only L2 summaries
│   ├── forgetting_engine.py # Decay simulation, candidates, reviewed archive
│   ├── compression_engine.py # Preview-only compression candidates
│   └── procedural_engine.py # Draft procedural memories, human approval required
├── mcp/
│   ├── tools/             # Thin re-export wrappers for the 9 MCP tools
│   ├── views/             # system://* view rendering
│   └── adapters/          # Opt-in host adapters such as prompt-cache splitting
├── security/
│   ├── sanitizers.py      # MCP input sanitization
│   └── artifact_stripper.py # Opt-in tool-result artifact stripping
├── runtime/
│   └── ...                # Runtime helper modules
├── models/
│   ├── __init__.py        # Model export
│   └── schemas.py         # Pydantic data model definitions
```

> Additional Note: Scripts for deployment, profile application, pre-sharing self-checks, etc., are located in the `scripts/` directory at the repository root, not in the `backend/` subdirectory.

### Core Module Description

- **`main.py`**: FastAPI application entry point, responsible for lifecycle management (database initialization, legacy database file compatibility recovery, and a best-effort drain of pending auto-flush summaries before shutdown), CORS configuration, route registration (`review`, `browse`, `maintenance`, `setup`, `layering`, `forgetting`, `search_quality`), and health checks. The current `/health` path returns detailed index / write-lane / index-worker runtime data only for local loopback requests or requests carrying a valid `MCP_API_KEY`; unauthenticated remote probes receive a shallow health payload instead of the full internal status dump. When that detailed health check is already degraded, the endpoint now also returns HTTP `503`, so Docker health checks and operators can treat it as not ready. Default CORS origins are converged to a local common list (`localhost/127.0.0.1` on `5173/3000`); explicitly configured wildcards (`*`) will automatically disable credentials; legacy sqlite recovery will execute regular-file + quick_check + core table existence validation before proceeding, and will strip query/fragment when parsing SQLite URLs, skipping non-file targets like `:memory:` / `file::memory:`. During startup, it also records which env keys already existed in the process before `load_dotenv(..., override=False)`, so the setup flow can tell a real process override from a value that only came from startup `.env` loading.
- **`mcp_server.py`**: Remains the public MCP entrypoint and backward-compatibility shim. The 9 MCP tool signatures are unchanged; the new `backend/mcp/tools/*.py` files are thin re-export wrappers and do not register a second tool surface. It still provides URI parsing (`domain://path` format), snapshot management, write guard decision-making, session caching, asynchronous index enqueuing, and system URI resources (`system://boot`, `system://index`, `system://index-lite`, `system://audit`, `system://recent`). The currently public MCP entry points are `stdio` and SSE: `stdio` connects directly to the tool process; remote access goes through the `/sse + /messages` SSE chain and remains subject to API Key and network-side security controls. The public MCP boundary now also enforces stricter contract checks before DB work starts: control/invisible/surrogate URI chars are rejected, and overlong `search_memory` / `create_memory` / `update_memory` payloads are blocked early. Percent-encoded memory URIs are also handled more predictably now: literal percent sequences remain valid path text, existing paths can still be resolved through decoded variants such as encoded spaces or slashes, and percent-decoded Windows filesystem paths such as `C%3A/...` are rejected as invalid memory URIs. `search_memory` now also clamps extreme `candidate_multiplier` expansion back to a hard ceiling, exposes `candidate_multiplier_applied` in the public response, and still keeps `candidate_limit_applied` in backend metadata for the hard cap; after session-first merging, it also re-sorts the final response by the exposed `score` so the returned order matches the visible ranking field. If a caller only cares about final results, it can also pass `verbose=false` to omit the noisy debug-heavy fields. The final path-state revalidation step now also prefers batched lookups, so larger result sets do not need one SQLite round-trip per row just to confirm the path still exists; that step now also skips access reinforcement, so one hit is not counted twice just because it was revalidated before the response is returned. If that revalidation lookup itself blows up, the current implementation now drops that result and exposes the degradation instead of fail-opening with stale data. When the interaction tier is `fast`, the first-round multiplier is now hard-capped at `4`, and later temporal/causal widening no longer expands it again past that cap. When `create_memory` is fail-closed because Write Guard is temporarily unavailable or degraded, the response now also surfaces `retryable` / `retry_hint`, so callers do not have to guess whether the block looks temporary. If `add_alias` writes the alias path first but snapshot capture fails afterwards, the current implementation also compensates by rolling back that alias path instead of leaving a half-success public write behind. The `compact_context` / auto-flush summary path now also takes a database-file-backed per-session process lock so two local processes are less likely to write the same session summary twice. The reflection workflow's `execute` path now also enters the same write lane, and its `reflection_workflow` counters are merged with persisted runtime metadata so observability totals survive restarts instead of resetting to the current process only. Reflection prepare now also tracks waiter lifecycles explicitly: when the last waiter cancels, the shared background task is cancelled too instead of being left behind; if cancellation cleanup itself raises a different exception, that cleanup error is now contained inside the shared task instead of spilling back into sibling waiters. The import/learn meta persist lock cache now also uses weak loop keys so finished event loops do not keep that map growing forever.
- **`runtime_state.py`**: Manages the write lane (serialized write operations), index worker (asynchronous queue processing for index rebuilding tasks), vitality decay scheduling, cleanup review approval process, and sleep consolidation scheduling. The current session-first retrieval cache and flush tracker both apply in-process bounds with **per-session caps plus a total session limit**, so long-running services do not grow without bound just because many distinct sessions have touched the process; the session-first hit cache also lazily prunes stale entries so old hits do not keep occupying capacity forever. `SessionRecentReadCache` now also refreshes hit order with real LRU semantics instead of keeping the original insertion order after a read hit.
- **`run_sse.py`**: SSE transport layer, responsible for API Key authentication and session management for the `/sse` and `/messages` links. The current implementation clears sessions upon client disconnection; if you continue to send requests to `/messages` using an old `session_id`, the server will explicitly return `404/410` instead of pretending `202 Accepted`. On trusted proxy paths it now prefers `X-Forwarded-For` / `X-Real-IP` when building the `/messages` burst-limit key, and it sends heartbeat pings every 15 seconds by default. Transport-security host/origin checks now keep the normal loopback allowlist by default; if you really need remote hostnames or origins to pass those checks, add them explicitly through `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS` instead of relying on a non-loopback bind to open everything. The repository now keeps two usage modes: standalone local debugging can still run `run_sse.py` directly, while the default Docker path mounts the same SSE entrypoints into the `main.py` backend process and exposes them through the frontend proxy.
- **`setup.py`**: First-run setup and local `.env` write entrypoint. `/setup/status` and `/setup/config` now distinguish between a real process-level explicit override and a value that was only loaded from `.env` during startup. In practice, setup status/save no longer misreads startup `.env` values as process overrides, and saving the local `.env` can refresh the current process view of setup-managed keys. The `/setup/status` support probe is now also side-effect-free: it checks the nearest existing writable parent and no longer creates missing parent directories just to answer capability status. The first local `.env` save now also requires a non-empty Dashboard key, and provider API bases are normalized/validated before write: common suffixes such as `/embeddings`, `/rerank`, `/chat/completions`, and `/responses` are trimmed automatically, while malformed or link-local targets are rejected. Loopback literals plus `localhost` stay allowed by default, but other private IP literals, and hostnames that resolve to private non-loopback addresses, now require explicit allowlisting through `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` before save. One more current edge matters here: if no Dashboard auth is configured yet and that first local save already includes remote/provider-chain settings, `/setup/config` intentionally falls back to an auth-bootstrap-only write and persists just `MCP_API_KEY` / `MCP_API_KEY_ALLOW_INSECURE_LOCAL`; the retrieval/provider fields plus `SEARCH_DEFAULT_MODE` only land on a later authenticated save. Saving retrieval settings now also writes back `SEARCH_DEFAULT_MODE`: when `embedding_backend=none` it returns to `keyword`, and every other backend currently writes `hybrid`, so saving `Profile B` now explicitly lands as `SEARCH_DEFAULT_MODE=hybrid`. When retrieval env values are otherwise unset, `/setup/status` now also reports the runtime's real default baseline as `hash / 64` instead of inventing a synthetic `none` summary.
- **`db/sqlite_client.py`**: SQLite database operation layer, containing memory CRUD, keyword/semantic/hybrid retrieval modes, write_guard logic (supports three-level determination: semantic matching + keyword matching + LLM decision), gist generation and caching, vitality scoring and decay, embedding retrieval (supports remote API and local hash modes), and reranker integration. Database initialization now uses `.init.lock` based on the database file path for process-level serialization, preventing `backend` / `sse` from competing for the database during initial concurrent startup; non-file targets like `:memory:` will not generate this lock. Existing on-disk SQLite files also fail closed during init if `PRAGMA quick_check(1)` does not return `ok`. Bootstrap indexing now repairs active memories that are missing FTS rows as well as ones missing chunk rows, and permanent memory deletion now clears chunk/vector/FTS rows for that memory instead of leaving index remnants behind. On the retrieval path, keyword search now first checks whether the query is safe for FTS: reserved control syntax such as `AND` / `OR` / `NOT` / `NEAR`, or wildcard-heavy inputs, no longer silently steer FTS semantics; the current implementation falls back for that request instead. The keyword LIKE fallback also escapes literal `%` / `_`, and the effective candidate pool can still be capped after intent-specific widening when the caller passes a stricter ceiling. If runtime env now contains an invalid `chat / embedding / reranker` API base, the code fails closed on that value: it ignores the bad base and falls back / degrades instead of continuing to send requests to it. The default factual intent is now also explicitly mapped to the `factual_high_precision` template.
- **`db/migration_runner.py` / `db/migration_gate.py`**: Discovers and applies SQL migrations while tracking versions and checksums. The checksum normalization now handles both `CRLF/LF` differences and UTF-8 BOM, so a migration file that only changed because of a Windows/Notepad-style file header does not look like schema drift. Migrations `0004`-`0008` add access logs, summaries, archived memories, procedural memories, and provenance columns; `MigrationGate` provides dry-run, backup, and export guardrails before destructive migration work.
- **`core/facade.py` and core engines**: `MemoryCore` is a compatibility facade and only delegates; it does not introduce a second behavior layer. `layering_engine.py` provides L2 summary listing, drill-down, and draft previews without writing generated drafts to the database. `forgetting_engine.py` handles decay simulation, candidate queues, and review-token archive; it never auto-deletes memories. `compression_engine.py` currently produces preview candidates only. `procedural_engine.py` defaults procedural memories to `review_state="draft"` and expects human approval before later write paths use them. Derived data carries provenance fields such as `source_memory_ids`, `source_hashes`, `derivation_method`, `confidence`, and `review_state` for reviewability.

---

## 3. HTTP API Endpoints

In plain English:

- `/browse`: The most commonly used, responsible for **viewing and writing memories**.
- `/review`: Used when changes need to be reviewed, responsible for **viewing diffs, rolling back, and confirming integration**.
- `/maintenance`: System O&M entry point, responsible for **cleanup, rebuilding indices, and viewing runtime status**.

If you are just connecting a regular client, usually looking at `/browse` and `/review` is enough.

### Browsing and Writing (`/browse`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/browse/node` | API Key | Browse memory tree (including child nodes, breadcrumbs, gist, aliases) |
| `POST` | `/browse/node` | API Key | Create memory node (includes write_guard) |
| `PUT` | `/browse/node` | API Key | Update memory node (includes write_guard) |
| `DELETE` | `/browse/node` | API Key | Delete memory path |

This is the most "business-like" group of interfaces:

- Memory tree browsing
- Create / Update / Delete memories
- Returns results including the current node, child nodes, breadcrumbs, gist, and other data for direct frontend use
- The write endpoints in this group now also create Review snapshots first; in Review, the visible session name carries the current database scope (for example `dashboard-<scope>`) so different SQLite targets do not get mixed together
- `POST / PUT /browse/node` also applies a default content-length check (`BROWSE_CONTENT_MAX_CHARS`, default 1 MiB) so accidental huge bodies do not go straight through the Dashboard write path
- `POST /browse/node` also validates the resulting path length (`BROWSE_PATH_MAX_CHARS`, default 512) before writing; if `parent_path + title` is too long, the API returns `422` immediately instead of letting the write proceed
- Successful Dashboard writes now also record a flush-tracker event, so a follow-up `/maintenance/learn/reflection` can reuse those `/browse/node` changes immediately instead of stopping at `session_summary_empty`
- If the write lane cannot hand out a write slot in time, the `browse` / `review` / `maintenance` write endpoints now return a structured `503` (`write_lane_timeout`) instead of a generic `500`; the MCP write tools return the same condition as a retryable structured error payload
- If SQLite runtime write pragmas have to fall back from `WAL` to `DELETE` because of network-filesystem risk or an unavailable `journal_mode`, the current implementation also emits an explicit warning so the problem is easier to trace back to deployment/runtime conditions instead of looking like an application-layer write bug

### Review and Rollback (`/review`)

Route-level API Key authentication (all endpoints require authentication).

One implementation boundary to keep in mind:

- snapshot files still live under the repo-level `snapshots/` directory;
- however, session listing, snapshot listing, and snapshot reads are filtered by the **current database scope**, so changing `DATABASE_URL`, switching to another temporary SQLite file, or pointing Docker at another data volume does not mix rollback sessions from a different database into the current Review queue;
- if the same `session_id` already has an older snapshot tree under another database scope, the current scope no longer physically deletes that older session directory just because the fingerprints differ; it stays preserved under its original scope and only becomes visible again when you switch back to that database;
- within the same `session_id`, snapshot writes are serialized, and both `manifest.json` and per-resource snapshot JSON files are written through atomic replace; the same snapshot directory now also applies conservative session-level retention/GC: it prunes old sessions by age/count, protects the current session, and skips older sessions whose write lock is busy; when multiple local processes share the same checkout, active sessions are less likely to be pruned by lock contention, and Review metadata is also less likely to lose entries or expose half-written JSON;
- if `manifest.json` is missing or damaged, the backend now tries to rebuild it under the original session scope first; it only persists the rebuilt manifest when that original scope can still be trusted. If the scope cannot be recovered safely, the session stays hidden and is not auto-deleted by a read-only session listing;
- legacy snapshot sessions that were created before scope metadata existed are hidden by default instead of being exposed under the wrong database context; the backend now also emits a one-time warning for those hidden legacy sessions so an upgrade does not look like snapshots vanished silently.
- if the same URI already has a later **content snapshot** in another Review session, rolling back the older snapshot now re-checks that condition inside the actual write lane and returns `409` instead of silently undoing the newer content change.
- metadata-only rollback now also follows a fail-closed path-state check inside the actual write lane: if the path disappeared before the write lands, the API now returns `404`; if the current path target or metadata already changed, it returns `409` instead of silently overwriting the newer state or bubbling out as a generic `500`.
- for `create` rollbacks with many descendants, the current implementation now batches descendant path deletion, orphan cleanup, and current-node deletion inside one write-lane execution, reducing repeated lane round-trips on large trees.

| Method | Path | Description |
|---|---|---|
| `GET` | `/review/sessions` | List review sessions |
| `GET` | `/review/sessions/{session_id}/snapshots` | View list of session snapshots |
| `GET` | `/review/sessions/{session_id}/snapshots/{resource_id}` | View snapshot details |
| `GET` | `/review/sessions/{session_id}/diff/{resource_id}` | View version diff |
| `POST` | `/review/sessions/{session_id}/rollback/{resource_id}` | Execute rollback |
| `DELETE` | `/review/sessions/{session_id}/snapshots/{resource_id}` | Confirm integration (delete snapshot) |
| `DELETE` | `/review/sessions/{session_id}` | Clear snapshots for the entire session |
| `GET` | `/review/deprecated` | List all deprecated memories |
| `DELETE` | `/review/memories/{memory_id}` | Permanently delete reviewed memory |
| `POST` | `/review/diff` | Universal text diff calculation |

This group of interfaces is more like a "change review area":

- Check session first
- Then check snapshot / diff
- Finally decide whether to rollback or integrate
- `POST /review/diff` is the generic text-compare helper: it returns `diff_html`, `diff_unified`, and a short plain-English `summary`. If `diff_match_patch` is unavailable in the environment, the HTML diff automatically falls back to `difflib.HtmlDiff`.

### Maintenance and Observability (`/maintenance`)

Route-level API Key authentication (all endpoints require authentication).

| Method | Path | Description |
|---|---|---|
| `GET` | `/maintenance/orphans` | View orphaned memories (deprecated or no path pointing to them) |
| `GET` | `/maintenance/orphans/{memory_id}` | View orphaned memory details |
| `DELETE` | `/maintenance/orphans/{memory_id}` | Permanently delete orphaned memory (if a deprecated final target is still referenced by older versions, deletion is rejected until the older chain is cleaned first) |
| `POST` | `/maintenance/import/prepare` | Prepare external import task (generates executable plan) |
| `POST` | `/maintenance/import/execute` | Execute external import task |
| `GET` | `/maintenance/import/jobs/{job_id}` | View import task status |
| `POST` | `/maintenance/import/jobs/{job_id}/rollback` | Rollback import task |
| `POST` | `/maintenance/learn/trigger` | Trigger explicit learning task |
| `POST` | `/maintenance/learn/reflection` | Trigger the reflection workflow (`prepare/execute`; `execute` enters the write lane, registers a learn job, and writes a review snapshot for the created path) |
| `GET` | `/maintenance/learn/jobs/{job_id}` | View explicit learning task status |
| `POST` | `/maintenance/learn/jobs/{job_id}/rollback` | Rollback explicit learning task (reflection execute delegates to the matching review snapshot rollback) |
| `POST` | `/maintenance/vitality/decay` | Trigger vitality decay |
| `POST` | `/maintenance/vitality/candidates/query` | Query cleanup candidate memories (supports `domain` / `path_prefix` filtering) |
| `POST` | `/maintenance/vitality/cleanup/prepare` | Prepare cleanup approval (generates review_id + token) |
| `POST` | `/maintenance/vitality/cleanup/confirm` | Confirm and execute cleanup (requires review_id + token + confirmation phrase) |
| `GET` | `/maintenance/index/worker` | View index worker status |
| `GET` | `/maintenance/index/job/{job_id}` | View index task details |
| `POST` | `/maintenance/index/job/{job_id}/cancel` | Cancel index task |
| `POST` | `/maintenance/index/job/{job_id}/retry` | Retry index task |
| `POST` | `/maintenance/index/rebuild` | Trigger full index rebuild |
| `POST` | `/maintenance/index/reindex/{memory_id}` | Reindex single item |
| `POST` | `/maintenance/index/sleep-consolidation` | Trigger sleep consolidation |
| `POST` | `/maintenance/observability/search` | Observability search (including retrieval statistics) |
| `GET` | `/maintenance/observability/summary` | Observability overview |

This group of interfaces is large but can be categorized into 5 types:

1. **Import / Learning Tasks**: `import/*`, `learn/*`
2. **Orphaned Memory Cleanup**: `orphans*`
3. **Vitality Governance**: `vitality/*`
4. **Index Tasks**: `index/*`
5. **Runtime Observability**: `observability/*`

One more current behavior boundary is worth calling out:

- `/maintenance/observability/search` now follows `SEARCH_DEFAULT_MODE` whenever the request omits `mode`; only an explicitly supplied `mode` overrides that default.
- The reflection workflow no longer depends only on MCP-side session summaries. Successful Dashboard `/browse/node` writes now seed the same reflection input path, and `/maintenance/observability/summary` merges persisted reflection counters with the current runtime view so `reflection_workflow` totals remain restart-stable.
- `POST /maintenance/import/prepare` now validates external-import batch size from file metadata before it reads file content; oversized single files or oversized batches are rejected before content hydration, and invalid UTF-8 now returns a clean `file_read_failed` result instead of surfacing a lower-level fd-close error.
- The Observability runtime snapshot now also exposes the `reflection_workflow` prepared / executed / rolled-back counters directly on the page, and the search diagnostics section shows `interaction_tier` plus whether `intent_llm_attempted` was true for that query.
- The latency card on the same page now shows a localized `P95` hint so the UI keeps the same meaning in English and zh-CN instead of hardcoding one spelling.
- After reflection `execute` succeeds, the learn job now also carries the matching review snapshot handle; `/maintenance/learn/jobs/{job_id}/rollback` delegates to the review rollback path instead of bypassing review semantics with its own delete logic.
- Reflection rollback no longer depends on an ambient session. When callers already know `session_id`, the backend still checks that `session_id` (and `actor_id` when supplied) against the learn job before it deletes anything; when rollback only carries a learn `job_id`, the backend now recovers the stored `session_id` from that job before it continues.
- If reflection execute rolls back through a review snapshot first, the backend now also does best-effort cleanup for the auto-created reflection namespace, so an empty parent path is less likely to be left behind forever.
- If the same `session_id`, `source`, `reason`, and `content` hit `prepare` concurrently, the workflow now reuses the same prepared review instead of minting multiple review IDs for the same batch.
- If the caller explicitly sends a blank or whitespace-only `session_id`, the reflection workflow now fails closed with `session_id_invalid`; the rollback path follows the same rule and no longer accepts an ambient-session fallback.

### Layer Summaries (`/api/layering`)

Route-level API Key authentication (all endpoints require authentication).

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/layering/summaries` | List existing L2 summaries, filterable by `scope` / `review_state` |
| `GET` | `/api/layering/summaries/{summary_id}` | Fetch one summary plus source-memory drill-down |
| `POST` | `/api/layering/summaries/generate` | Generate a draft preview from L1 memory ids; does not persist it |

This surface is intentionally “read and preview first.” `generate` returns `persisted=false`, so the Dashboard can show L2 drafts and provenance without silently creating a new summary just because the panel was opened.

### Forgetting Candidates (`/api/forgetting`)

Route-level API Key authentication (all endpoints require authentication).

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/forgetting/simulate` | Pure-read vitality decay simulation |
| `GET` | `/api/forgetting/candidates` | Return candidates below the threshold without mutating the database |
| `POST` | `/api/forgetting/archive/prepare` | Prepare an archive review, returning a short-lived token and confirmation phrase |
| `POST` | `/api/forgetting/archive/confirm` | Consume the review token and execute archive |
| `POST` | `/api/forgetting/archive` | Low-level single-item archive endpoint; requires a non-empty review token |

The forgetting engine does not auto-delete memories. The current write path is human-confirmed archive: the original memory is marked deprecated and an archive copy is written to `archived_memories`; destructive delete is not used.

### Search Quality (`/search/quality-metrics`)

Route-level API Key authentication. The Docker frontend proxy exposes this as the exact path `/api/search/quality-metrics`, then forwards it to backend `/search/quality-metrics`.

The endpoint is real, but it is not a benchmark-results endpoint. Because labelled search-quality samples are not persisted yet, it explicitly returns `is_mock=true`, `status=unavailable`, and `reason=labelled_search_quality_samples_not_persisted`. Treat the Dashboard panel's MRR / Recall sample values as UI placeholder/demo data, not as production retrieval quality.

The backend no longer exposes `http://127.0.0.1:8000/docs` by default; direct access will usually return `404`. For current route behavior, use this overview, [TOOLS_EN.md](TOOLS_EN.md), and the API tests under `backend/tests/`.

---

## 4. MCP Tool Implementation

Implementation file: `backend/mcp_server.py`

| Tool | Type | Description |
|---|---|---|
| `read_memory` | Read | Read memory content, supports full text and segments (chunk_id / range / max_chars), supports system URIs (`system://boot`, `system://index`, `system://index-lite`, `system://audit`, `system://recent`) |
| `create_memory` | Write | Create new memory node (includes write_guard, enters write lane for serialization; recommended to fill `title` explicitly) |
| `update_memory` | Write | Update existing memory (prefers `old_string/new_string` for precise replacement; `append` is only for true tail appending, includes write_guard) |
| `delete_memory` | Write | Delete memory path (enters write lane for serialization) |
| `add_alias` | Write | Add alias path for the same memory (can cross domains) |
| `search_memory` | Retrieval | Unified retrieval entry point (keyword/semantic/hybrid), supports intent classification and strategy templates |
| `compact_context` | Governance | Compress current session context into long-term memory summary (enters write lane for serialization) |
| `rebuild_index` | Maintenance | Full or single index rebuild, supports synchronous waiting and sleep consolidation |
| `index_status` | Maintenance | Query index availability, runtime status, and configuration switches |

For tool return conventions and degradation semantics, see: [TOOLS_EN.md](TOOLS_EN.md)

---

## 5. Frontend Structure

```
frontend/src/
├── App.jsx                                    # Routes and page skeleton
├── main.jsx                                   # React entry point
├── RootErrorBoundary.jsx                      # Root-level fallback shell for unexpected render crashes
├── i18n.js                                    # react-i18next initialization, default language, and persistence
├── index.css                                  # Global styles (TailwindCSS)
├── lib/sse.js                                 # Lightweight SSE helper: native EventSource without browser auth, fetch-based SSE with headers when auth exists
├── locales/
│   ├── en.js                                  # English copy
│   └── zh-CN.js                               # Chinese copy
├── features/
│   ├── memory/MemoryBrowser.jsx               # Tree browsing, editing, gist view
│   ├── memory/LayerHierarchyPanel.jsx         # L0/L1/L2 hierarchy view
│   ├── review/ReviewPage.jsx                  # diff, rollback, integrate
│   ├── maintenance/MaintenancePage.jsx        # vitality cleanup and maintenance tasks
│   ├── maintenance/ForgettingPanel.jsx        # forgetting simulation, candidate queue, reviewed archive
│   ├── observability/ObservabilityPage.jsx    # retrieval stats and task observability
│   └── observability/SearchQualityPanel.jsx   # Search Quality panel
├── components/
│   ├── DiffViewer.jsx                         # Diff visualization
│   ├── FluidBackground.jsx                    # Fluid animation background
│   ├── GlassCard.jsx                          # Glassmorphism card
│   └── SnapshotList.jsx                       # Snapshot list
├── lib/
│   ├── api.js                                 # Unified API client and runtime auth injection
│   ├── format.js                              # Date/number formatting following current language
│   ├── api.test.js                            # API client unit tests
│   └── api.contract.test.js                   # API auth contract tests
└── test/                                      # Frontend test directory
```

### Dashboard's Four Functional Modules

| Module | Route | Function |
|---|---|---|
| Memory Browser | `/memory` | Browse tree by domain, inline editing, view gist summaries, alias management, and L0/L1/L2 hierarchy view |
| Review | `/review` | View write snapshot diffs, support rollback and integrate confirmation, clean up deprecated memories |
| Maintenance | `/maintenance` | View vitality scores, clean up orphaned memories, trigger index rebuilds, manage cleanup approval process, support `domain` / `path_prefix` filtering, and show forgetting simulation / archive candidates |
| Observability | `/observability` | Retrieval logs and statistics, task execution records, index worker status, system status overview, support `scope_hint`, `interaction_tier`, `intent_llm_attempted`, localized `P95`, Search Quality panel, and more granular runtime snapshots |

Additional notes:

- The current frontend restores the stored language first; if there is no stored choice yet, common Chinese browser locales (`zh`, `zh-TW`, `zh-HK`, and similar `zh-*`) are normalized to `zh-CN`, and other first-visit cases fall back to English. The application shell still provides a language switch entry and a unified authentication entry in the upper right corner.
- Before React mounts, the current frontend also primes `document.lang` and the page title from that stored or detected language, so first paint is less likely to flash the wrong locale metadata.
- The React root is now also wrapped in `RootErrorBoundary`. In plain language: if a component crashes during render, the dashboard falls back to a small recovery shell instead of tearing down the whole SPA with no explanation, and that fallback copy now follows the active locale instead of staying English-only.
- Language switching supports one-click switching between English and Chinese, results will be saved in the browser's `localStorage` as `memory-palace.locale`.
- Common static copy, date/number formats, and common frontend-side error mappings will follow the current language switch.
- If authentication is not yet configured, the page shell will still open, but protected data requests will show an authorization prompt, empty state, or `401`.
- When starting via the recommended one-click Docker path, protected requests usually already work: the frontend proxy automatically forwards the same `MCP_API_KEY` on the server side. The first-run assistant now checks `/setup/status` before auto-opening, so it stays closed when proxy-held auth is already working even though the browser page itself still does not know the proxy-held key. Only when protected data also starts failing with `401` or empty states should you keep troubleshooting env / proxy configuration.
- Stored browser Dashboard auth now lives in the current browser session's `sessionStorage`; if a legacy `localStorage` value is found, the frontend still only migrates it forward once, but it now removes the old copy only when `localStorage` still contains that same old value. This avoids one tab deleting a newer value written by another tab during migration. When the Setup Assistant saves the local `.env`, it also writes the current Dashboard key into the browser session if the form still has one; if that save clears the key, the old browser-stored value is cleared too.
- The Setup Assistant now also shows `Profile A` explicitly; it still means the default `keyword + none` baseline rather than a new higher-tier profile. One small implementation boundary is worth keeping in mind: the first auto-open path still presents that documented baseline, but manual opens, or any path that already has a real `/setup/status` payload, now hydrate the current runtime state first. On a local runtime with no explicit retrieval env, that real state now shows up as `hash / 64`.
- When the Setup Assistant opens, the Dashboard API key field is focused automatically; `Escape` closes the dialog, and `Tab` / `Shift+Tab` stay inside the dialog until it is closed.
- The frontend now also has a lightweight SSE helper (`frontend/src/lib/sse.js`); the repo-local Vite `/sse` proxy is intentionally still kept. Without browser-side Dashboard auth it still uses the same-origin native `EventSource` path; once browser auth exists, Observability switches to a fetch-based SSE path so the same header/bearer key can be sent to `/sse`, each reconnect re-resolves the current browser auth while still carrying `Last-Event-ID`, and terminal `4xx` auth failures stop retrying instead of looping forever. If the frontend uses a prefixed `VITE_API_BASE_URL`, that helper now resolves `/sse` against the same prefix instead of assuming the site root.
- Reviewed vitality cleanup delete batches now execute atomically inside one DB session when session-backed delete support is available. If a multi-delete batch cannot be made atomic, the backend rejects that batch instead of partially deleting earlier items; single-delete fallback remains allowed.
- The vitality cleanup confirm flow also no longer treats every failure as a reason to discard the prepared review. For cases that look temporary, such as `401`, timeout, or network errors, the current prepared review is kept so you can fix auth/network and retry directly.
- In the Memory Browser, unsaved-navigation and delete-path confirmations now fail closed through the shared dialog helper. If a host cannot provide native `confirm()`, the page surfaces an error instead of continuing silently.
- The new hierarchy, forgetting, and Search Quality panels clearly show sample/fallback state when an API is unsupported or returns `is_mock`. In particular, Search Quality does not yet persist labelled quality samples, so its example MRR / Recall values should not be treated as benchmark conclusions.

---

## 6. Frontend Authentication Injection Model

The frontend does not read maintenance keys from `VITE_*` build variables; it uses runtime injection:

```html
<script>
  window.__MEMORY_PALACE_RUNTIME__ = {
    maintenanceApiKey: "<YOUR_MCP_API_KEY>",
    maintenanceApiKeyMode: "header"
  };
</script>
```

`maintenanceApiKeyMode` supports: `header` (sends `X-MCP-API-Key` header) or `bearer` (sends `Authorization: Bearer` header).

> Compatibility: The runtime object is also compatible with the old field name `window.__MCP_RUNTIME_CONFIG__`.
>
> Code reference: `readWindowRuntimeMaintenanceAuth()` and `getMaintenanceAuthState()` in `frontend/src/lib/api.js`.
>
> In plain language: by default, the frontend first trusts a runtime-injected key; if that is missing, it falls back to a key saved in the current browser session. There is one extra exception now: if you just saved a browser-side Dashboard key through the Setup Assistant, the frontend explicitly lets that newly saved key take priority over the runtime key for the current session. A legacy Dashboard key left in `localStorage` is still only migrated once, but the current tab only deletes it when it can confirm that the old value was not replaced by another tab in the meantime. Changing or clearing browser-side Dashboard auth now also emits a maintenance-auth change event, and the Observability page uses that signal, plus a focus-time recheck, to rebuild its authenticated `/sse` stream when auth changes or after a terminal `401` stopped retries.
>
> In plain English: the frontend makes authentication "runtime-decided," so you can either fill in the key directly at the top of the page or have it injected by a deployment script before the page loads.
>
> One more small behavior detail is now aligned with the code: if `maintenanceApiKeyMode` switches from `header` to `bearer` (or the other way around), the request interceptor first removes the old opposite header and then adds the current one. That avoids sending two competing auth headers on the same request.
>
> One more current behavior boundary is now aligned with the code: if the frontend is explicitly configured with `VITE_API_BASE_URL`, whether that is a same-origin prefixed path or your own cross-origin API origin, the frontend now resolves protected `/browse`, `/review`, `/maintenance`, and `/setup` requests against that API base and still attaches the browser-saved Dashboard key. It still does **not** send that key to unrelated third-party absolute URLs.
>
> The extra value of `run_memory_palace_mcp_stdio.sh` is not that `mcp_server.py` would otherwise "randomly pick the wrong database" by itself. Its value is that it gives CLI/client configs a safer default entry: prefer the repository `.env` / `DATABASE_URL`; if `.env` already sets `RETRIEVAL_REMOTE_TIMEOUT_SEC`, it also keeps using that value; only when the checkout has neither a local `.env` nor an `.env.docker` file does it fall back to the repo's default SQLite path. If `.env.docker` exists without `.env`, the wrapper now refuses that `demo.db` fallback explicitly so local stdio traffic does not get mixed up with Docker container data; if `.env` or an explicit `DATABASE_URL` still points to `/app/...` or `/data/...` after normalizing common slash and case variants (for example `sqlite+aiosqlite://///app/data/...` or an uppercase `/APP/...` form), it also refuses to start. On the shell-wrapper path, it also exports `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1` before starting Python so non-UTF-8 locales are less likely to break local stdio; it also merges existing `NO_PROXY` / `no_proxy` values and adds `localhost`, `127.0.0.1`, `::1`, and `host.docker.internal`, so repo-local stdio is less likely to misroute host-local model calls through a shell proxy.

> Docker one-click deployment uses a third way: it doesn't inject the key into the page but automatically forwards it at the frontend proxy layer.

---

## 7. Data and Task Flow

### Write Path

1. `create_memory` / `update_memory` enters the **write lane** (serialized write operations; transient SQLite lock conflicts get a small bounded retry first).
2. Executes **write_guard** determination before writing (core decisions: `ADD` / `UPDATE` / `NOOP` / `DELETE`; `BYPASS` is a process marker for upper-layer metadata-only updates).
   - write_guard supports a three-level determination chain: semantic matching → keyword matching → LLM decision (optional).
3. Generates **snapshot** and version changes (recorded separately by `path` and `memory` dimensions; both MCP writes and Dashboard `/browse/node` writes follow the same semantics; same-session snapshot writes are now serialized through a file lock).
   - After each successful snapshot write, the backend now also applies conservative session-level retention by age/count; the current session stays protected, and locked old sessions are skipped first.
4. Enqueues **index task** (returns `index_dropped` / `queue_full` if queue is full; DB-writing index jobs now also pass through the same write lane instead of racing the foreground write path).

### Retrieval Path

1. **`preprocess_query`** preprocesses the query text (standardizes whitespace, tokenizes, preserves multilingual/URI).
2. **`classify_intent`** routes by default based on 4 core intents; defaults to `factual` (template `factual_high_precision`) when no significant keyword signals are present, and falls back to `unknown` (template `default`) when signals conflict or are mixed with low signals:
   - `factual` → Strategy template `factual_high_precision` (High-precision matching)
   - `exploratory` → Strategy template `exploratory_high_recall` (High-recall exploration)
   - `temporal` → Strategy template `temporal_time_filtered` (Time-filtered)
   - `causal` → Strategy template `causal_wide_pool` (Causal reasoning, wide candidate pool)
   - `unknown` → Strategy template `default` (Conservative fallback when signals conflict or are mixed)
   - One easy-to-miss boundary: `why ... after/before ...` does not automatically become `unknown`. If `after/before` only describes the triggering event, the rule still prefers `causal`. The conservative fallback stays for stronger time anchors such as `when`, `timeline`, or `yesterday`.
3. Executes **keyword / semantic / hybrid** retrieval.
4. Optional **reranker** re-ranking (via remote API call).
5. Supports additional query-side constraints, such as `scope_hint`, `domain`, `path_prefix`, `max_priority`.
6. Returns `results` and `degrade_reasons`.

> Vector-dimension checks now follow the scope that the current query actually targets instead of doing a global full-table decision first. In practice, old vectors in an unrelated domain no longer force a false semantic fallback; if the vectors inside the current scope really mismatch, `degrade_reasons` now tells the caller that a reindex is required.

> One compatibility note: `scope_hint=fast|deep` is now consumed first as a legacy interaction-tier shortcut instead of being treated as a literal path scope. New callers should prefer `interaction_tier` when the goal is just to switch between fast and deep behavior.

> Intent classification is implemented using the `keyword_scoring_v2` method (`db/sqlite_client.py` `classify_intent` method), inferring intent through keyword matching scores and rankings without external model calls. The current rule set now distinguishes weak temporal connectors from strong temporal anchors, so obvious causal queries are less likely to be pushed into the conservative fallback just because they contain `after` or `before`.
>
> **Configuration Strategy Notes**:
> - This project supports two approaches: `1)` directly configuring embedding / reranker / llm separately; `2)` unifying these capabilities via a `router` proxy.
> - `INTENT_LLM_ENABLED` is disabled by default; when enabled, it will first attempt LLM intent classification and fall back to existing keyword rules if it fails.
> - `RETRIEVAL_MMR_ENABLED` is disabled by default; deduplication / diversity re-ranking only occurs under `hybrid` retrieval.
> - `RRF_ENABLED` is disabled by default; when enabled, Reciprocal Rank Fusion only runs over allowlisted `fts5` / `vector` channels, with `RRF_K=60` by default.
> - `ENTITY_RERANK_WEIGHT` defaults to `0.0`; the entity signal is a post-fusion rerank boost, not a third RRF channel.
> - `RETRIEVAL_SQLITE_VEC_ENABLED` is disabled by default; the legacy vector path remains the default implementation, with sqlite-vec undergoing controlled rollout.
> - For local development, the former is generally recommended because failures in the three links are usually independent, making it easier to confirm which model, endpoint, or set of keys has an issue.
> - `router` is more suitable as a unified entry point for production/client environments: convenient for centralized authentication, rate limiting, auditing, model switching, and fallback orchestration.
> - The Setup Assistant now keeps preset switching conservative: when you switch between Profile B / C / D or turn off router-backed fields, hidden stale router / API fields are cleared before save instead of being silently carried forward.
> - The setup API now also accepts `openai` as an embedding backend. Once you switch to any remote embedding backend, it only saves `RETRIEVAL_EMBEDDING_DIM` when you explicitly provide the real provider dimension; it no longer keeps the old `64`, and it no longer guesses `1024` for you.

![Memory Write and Review Sequence Diagram](images/记忆写入与审查时序图.png)

---

## 8. Deployment Specifications

| Scenario | Host Port | Internal Container Port | Description |
|---|---|---|---|
| Local Development | Backend `8000` · Frontend `5173` | — | Direct startup |
| Docker Default | Backend `18000` · Frontend `3000` · SSE `3000/sse` | Backend `8000` (serves both REST + SSE) · Frontend `8080` | Ports can be overridden via env vars |

Docker port environment variables:

- Backend: `MEMORY_PALACE_BACKEND_PORT` (falls back to `NOCTURNE_BACKEND_PORT`, default `18000`)
- Frontend: `MEMORY_PALACE_FRONTEND_PORT` (falls back to `NOCTURNE_FRONTEND_PORT`, default `3000`)

One more thing:

- Changing the SSE listening address to `0.0.0.0` (or another non-loopback address) only means remote clients can connect to this listening address; it does not mean `MCP_API_KEY`, reverse proxies, firewalls, or TLS security controls can be bypassed.

Related files:

- Compose files: `docker-compose.yml`, `docker-compose.ghcr.yml` (`docker-compose.yml` now unsets the inherited `http_proxy/https_proxy/all_proxy/no_proxy` family before the frontend probes `127.0.0.1:8080`, so a container-side localhost probe is less likely to get misrouted through a proxy chain; `docker-compose.ghcr.yml` keeps the backend explicitly bound to `0.0.0.0`, so the GHCR path uses the same health-gate assumption as the local compose path)
- Image definition: `deploy/docker/Dockerfile.backend` (based on `python:3.11-slim`), `deploy/docker/Dockerfile.frontend` (build stage `node:22-alpine`, run stage `nginxinc/nginx-unprivileged:1.27-alpine`)
- Backend healthcheck helper: `deploy/docker/backend-healthcheck.py` (performs a second check against `/health` inside the container and requires the payload to report `status == "ok"`; defaults to a `5` second timeout, configurable through `MEMORY_PALACE_BACKEND_HEALTHCHECK_TIMEOUT_SEC`; the backend image now wires this into Docker `HEALTHCHECK`, and the GHCR publish path verifies that the helper is actually present in the image before push)
- Nginx configuration template: `deploy/docker/nginx.conf.template` (injects `X-MCP-API-Key` only for the protected Dashboard API routes, `/api/layering/*`, `/api/forgetting/*`, the exact `/api/search/quality-metrics` route, plus `/sse` / `/messages`, and returns `no-store/no-cache/must-revalidate` on `/index.html` to reduce stale entry pages after frontend updates; the frontend entrypoint escapes special characters in the proxy-held key, rejects the remaining ASCII control characters, and then generates the final Nginx config)
- Entrypoint scripts: `deploy/docker/backend-entrypoint.sh`, `deploy/docker/frontend-entrypoint.sh` (the backend entrypoint now fails closed if `gosu` is unavailable in a root-start path)
- Backup scripts: `scripts/backup_memory.sh`, `scripts/backup_memory.ps1` (keep the latest `20` backups by default; adjust with `--keep` / `-Keep`; backup filenames use UTC timestamps so host/container runs sort consistently)
- Pre-publishing check: `scripts/pre_publish_check.sh` (blocks tracked `.audit` / `.playwright-mcp` artifacts and scans tracked files for local-only endpoint/key patterns such as `sk-local-*` plus loopback/private provider bases with ports; the repository's own frontend loopback health probe is intentionally excluded from that leak scan)

The current validate path treats frontend typecheck as a first-class check alongside frontend tests and the frontend build. In the 2026-04 full snapshot, backend `1136 passed, 22 skipped`, frontend `198 passed`, frontend build/typecheck passed, and repo-local live MCP e2e passed. The 2026-05-15 follow-up reran Docker/Linux `Profile B/C/D`: health, SSE, and browser smoke passed for all three; C/D create/search/delete also passed with `degrade_reasons=None`. The narrower 2026-04-18 benchmark table was not recalculated in that Docker follow-up, and native Windows / native Linux host runtime paths still keep explicit target-environment recheck boundaries here.

---

## 9. Security Defaults

- All `/maintenance/*`, `/review/*`, `/api/layering/*`, `/api/forgetting/*`, and `/search/quality-metrics` endpoints require API Key authentication.
- All `/browse` read/write operations (GET/POST/PUT/DELETE) are gated via endpoint-level `Depends(require_maintenance_api_key)`.
- Public HTTP endpoints include `/` and `/health`; `/health` stays public only for a shallow payload, while detailed runtime/index data is reserved for local loopback or authenticated requests. All other Browse / Review / Maintenance / Layering / Forgetting / Search Quality and SSE channels follow the same authentication logic.
- Defaults to **fail-closed** (rejects requests) if `MCP_API_KEY` is empty.
- Access is only allowed locally without a key if `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` **and** the request is loopback (`127.0.0.1` / `::1` / `localhost`), and only for direct loopback requests without forwarding headers.
- The local `/setup/config` write path is also fail-closed: it only targets project-local `.env*` files, still requires a direct loopback request, the first local save also requires a non-empty Dashboard key, and if the backend already runs with `MCP_API_KEY`, that loopback write also requires the same valid key. If there is still no Dashboard auth and that first local save already includes remote/provider-chain fields, the backend intentionally collapses it into an auth-bootstrap-only write; the retrieval/provider fields must be saved again after auth is active.
- Setup/provider API bases also go through normalization and validation first: common suffixes are trimmed automatically, malformed or link-local targets are rejected, and runtime reads of invalid bases also fail closed into fallback / degradation.
- Docker containers run as non-root users by default:
  - Backend: Custom user `app` (UID `10001`, GID `10001`)
  - Frontend: Uses official `nginx-unprivileged` non-root image

Detailed policy: [SECURITY_AND_PRIVACY_EN.md](SECURITY_AND_PRIVACY_EN.md)
