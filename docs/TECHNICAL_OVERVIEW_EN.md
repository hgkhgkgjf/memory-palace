# Memory Palace Technical Overview

For technical users who need to understand the architecture or do further development.

## 1. Technology Stack

| Layer | Technology | Version | Role |
|---|---|---|---|
| Backend | FastAPI + SQLAlchemy + SQLite | FastAPI ≥0.109 · SQLAlchemy ≥2.0 · aiosqlite ≥0.19 | Memory R/W, retrieval, review, maintenance |
| MCP | `mcp.server.fastmcp` | mcp ≥0.1 | Unified tool surface for Codex / Claude Code / Gemini CLI / OpenCode; IDE hosts (Cursor / Windsurf / VSCode / Antigravity) use a repo-local `AGENTS.md` + MCP snippet |
| Frontend | React + Vite + TailwindCSS + Framer Motion | React ≥18.2 · Vite ≥7.3 · TailwindCSS ≥3.3 · Framer Motion ≥12.34 | Visual management Dashboard |
| Runtime | Built-in queue and worker | — | Write serialization, index rebuild, vitality decay, sleep consolidation |
| Deployment | Docker Compose + profile scripts | Docker ≥20 · Compose ≥2.0 | A/B/C/D profile deployment |

Core dependencies: `backend/requirements.txt` and `frontend/package.json`.

> The repository compose files use nested `${...:-...}` defaults for volume names. On older Compose implementations that fail to parse this, prefer `docker_one_click.sh/.ps1`, or explicitly set `MEMORY_PALACE_DATA_VOLUME`, `MEMORY_PALACE_SNAPSHOTS_VOLUME`, and `COMPOSE_PROJECT_NAME`.

---

## 2. Backend Structure

```
backend/
├── main.py               # FastAPI entry, lifecycle management
├── mcp_server.py         # Public MCP entrypoint (9 tools)
├── runtime_state.py      # Write lane, index worker, vitality decay
├── run_sse.py            # SSE transport layer (API Key auth)
├── api/
│   ├── browse.py         # Memory browsing and writing (/browse)
│   ├── review.py         # Review, rollback, integration (/review)
│   ├── maintenance.py    # Maintenance, observability, vitality cleanup (/maintenance)
│   ├── layering.py       # L2 layer summaries (/api/layering)
│   ├── forgetting.py     # Forgetting simulation, archive (/api/forgetting)
│   ├── search_quality.py # Search Quality panel (/search)
│   └── setup.py          # First-run setup, local .env write (/setup)
├── db/
│   ├── sqlite_client.py  # Core CRUD, retrieval, governance
│   ├── search/           # FTS5 / vector / RRF / entity boost channels
│   ├── snapshot.py       # Snapshot manager (per-session isolation, atomic writes, conservative retention/GC)
│   ├── migration_runner.py / migration_gate.py  # Auto migration + backup guardrails
│   └── migrations/       # SQL migration scripts
├── core/
│   ├── layering_engine.py     # L2 read-only summaries
│   ├── forgetting_engine.py   # Decay simulation, human-confirmed archive
│   ├── compression_engine.py  # Preview-only compression candidates
│   └── procedural_engine.py   # Draft procedural memories (human approval required)
├── mcp/                  # Thin tool wrappers, system://* views, host adapters
└── security/             # MCP input sanitization, artifact stripping
```

> Scripts for deployment, profile application, and pre-share self-checks live in the repo-root `scripts/` directory, not under `backend/`.

### Core Modules

- **`main.py`** — FastAPI entry. Handles database initialization, legacy DB compatibility recovery, CORS, route registration, and health checks. `/health` returns detailed runtime data for loopback requests or requests carrying a valid `MCP_API_KEY`; unauthenticated remote probes get a shallow result. Returns HTTP `503` when degraded.

- **`mcp_server.py`** — MCP public entrypoint. Provides URI parsing (`domain://path`), snapshot management, Write Guard decisions, session caching, async index enqueueing, and system URI resources (`system://boot`, `system://index`, etc.). Public entrypoints are `stdio` and SSE. The MCP boundary enforces strict contract checks: control / invisible / surrogate characters and overlong payloads are rejected.

- **`runtime_state.py`** — Manages the write lane (serialized writes), index worker, vitality decay, cleanup review approval, and sleep consolidation scheduling. The session-first retrieval cache applies in-process bounds: per-session caps plus a total session limit.

- **`run_sse.py`** — SSE transport layer. Handles API Key auth, `/sse` / `/messages` session management, and 15-second heartbeats. Sessions are cleared on client disconnect; stale `session_id` requests get `404/410`.

- **`setup.py`** — First-run setup and local `.env` write entrypoint. Distinguishes between explicit process-level overrides and values loaded from `.env` at startup. First save requires a non-empty Dashboard key; provider API bases go through normalization and validation. Without existing Dashboard auth, the first save bootstraps only `MCP_API_KEY`; retrieval/provider fields persist on the next authenticated save.

- **`db/sqlite_client.py`** — SQLite operation layer. Includes CRUD, keyword/semantic/hybrid retrieval, Write Guard logic (three-level: semantic match + keyword match + LLM decision), gist generation and caching, vitality scoring and decay, embedding retrieval, and reranker integration. Database initialization uses `.init.lock` for process-level serialization.

- **`db/migration_runner.py` / `migration_gate.py`** — Discovers and applies SQL migrations, tracks versions and checksums. Checksum normalization handles `CRLF/LF` and UTF-8 BOM. `MigrationGate` provides dry-run, backup, and export guardrails before destructive migrations.

- **`core/` engines** — `MemoryCore` is a compatibility facade and only delegates. `layering_engine` provides L2 read-only summaries; `forgetting_engine` does decay simulation and review-token archive without auto-deleting; `compression_engine` is preview-only; `procedural_engine` defaults to `review_state="draft"` and requires human approval. Derived data carries provenance fields: `source_memory_ids`, `source_hashes`, `derivation_method`, `confidence`, `review_state`.

---

## 3. HTTP API Endpoints

- `/browse` — Read and write memories (most common)
- `/review` — View diffs, rollback, integrate
- `/maintenance` — Cleanup, index rebuild, runtime status
- `/api/layering` — L2 layer summaries
- `/api/forgetting` — Forgetting candidates, human archive
- `/search/quality-metrics` — Search Quality panel

### `/browse`

| Method | Path | Description |
|---|---|---|
| `GET` | `/browse/node` | Browse memory tree (children, breadcrumbs, gist, aliases) |
| `POST` | `/browse/node` | Create memory node (with Write Guard) |
| `PUT` | `/browse/node` | Update memory node (with Write Guard) |
| `DELETE` | `/browse/node` | Delete memory path |

- Writes create Review snapshots first; session names include the database scope (e.g., `dashboard-<scope>`)
- Per-write `content` limit: `BROWSE_CONTENT_MAX_CHARS` (default 1 MiB)
- Path length limit: `BROWSE_PATH_MAX_CHARS` (default 512)
- When the write lane is saturated, returns structured `503` (`write_lane_timeout`)
- Concurrent writes to the same path return `409` (`Memory version conflict`)

### `/review`

| Method | Path | Description |
|---|---|---|
| `GET` | `/review/sessions` | List review sessions |
| `GET` | `/review/sessions/{session_id}/snapshots` | View session snapshots |
| `GET` | `/review/sessions/{session_id}/snapshots/{resource_id}` | View snapshot details |
| `GET` | `/review/sessions/{session_id}/diff/{resource_id}` | View version diff |
| `POST` | `/review/sessions/{session_id}/rollback/{resource_id}` | Execute rollback |
| `DELETE` | `/review/sessions/{session_id}/snapshots/{resource_id}` | Confirm integration (delete snapshot) |
| `DELETE` | `/review/sessions/{session_id}` | Clear all snapshots for the session |
| `GET` | `/review/deprecated` | List deprecated memories |
| `DELETE` | `/review/memories/{memory_id}` | Permanently delete reviewed memory |
| `POST` | `/review/diff` | Generic text diff |

Boundary notes:

- Snapshot files live under `snapshots/`, but session listing and snapshot reads are filtered by the current database scope
- Same-session snapshot writes are serialized; `manifest.json` and snapshot JSON files use atomic replace
- Conservative retention/GC: prunes old sessions by age/count, protects the current session, skips older sessions whose lock is busy
- Rollback returns `409` if the URI already has a newer content snapshot in another Review session
- Metadata-only rollback fail-closes on path-state checks before writing

### `/maintenance`

| Method | Path | Description |
|---|---|---|
| `GET` | `/maintenance/orphans` | View orphaned memories |
| `DELETE` | `/maintenance/orphans/{memory_id}` | Permanently delete orphan |
| `POST` | `/maintenance/import/prepare` | Prepare external import |
| `POST` | `/maintenance/import/execute` | Execute external import |
| `POST` | `/maintenance/import/jobs/{job_id}/rollback` | Rollback import |
| `POST` | `/maintenance/learn/trigger` | Trigger explicit learning |
| `POST` | `/maintenance/learn/reflection` | Trigger reflection workflow (`prepare/execute`) |
| `POST` | `/maintenance/vitality/decay` | Trigger vitality decay |
| `POST` | `/maintenance/vitality/candidates/query` | Query cleanup candidates |
| `POST` | `/maintenance/vitality/cleanup/prepare` | Prepare cleanup approval |
| `POST` | `/maintenance/vitality/cleanup/confirm` | Confirm and execute cleanup |
| `GET` | `/maintenance/index/worker` | Index worker status |
| `POST` | `/maintenance/index/rebuild` | Full index rebuild |
| `POST` | `/maintenance/index/reindex/{memory_id}` | Reindex single item |
| `POST` | `/maintenance/index/sleep-consolidation` | Trigger sleep consolidation |
| `POST` | `/maintenance/observability/search` | Observability search |
| `GET` | `/maintenance/observability/summary` | Observability overview |

Five categories:

1. **Import / Learn**: `import/*`, `learn/*`
2. **Orphan cleanup**: `orphans*`
3. **Vitality governance**: `vitality/*`
4. **Index tasks**: `index/*`
5. **Runtime observability**: `observability/*`

### `/api/layering`

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/layering/summaries` | List L2 summaries (filter by `scope` / `review_state`) |
| `GET` | `/api/layering/summaries/{summary_id}` | View one summary + source drill-down |
| `POST` | `/api/layering/summaries/generate` | Generate draft preview from L1 IDs (`persisted=false`) |

### `/api/forgetting`

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/forgetting/simulate` | Pure-read vitality decay simulation |
| `GET` | `/api/forgetting/candidates` | Candidates below threshold |
| `POST` | `/api/forgetting/archive/prepare` | Prepare archive review (returns token + confirmation phrase) |
| `POST` | `/api/forgetting/archive/confirm` | Consume token and execute archive |
| `POST` | `/api/forgetting/archive` | Low-level single-item archive |

The forgetting engine does not auto-delete memories. The current write path is human-confirmed archive: the original memory is marked deprecated and an archive copy is written to `archived_memories`.

### `/search/quality-metrics`

Docker frontend proxy path is `/api/search/quality-metrics`. Currently returns `is_mock=true`, `status=unavailable`, `reason=labelled_search_quality_samples_not_persisted`. Treat Dashboard MRR / Recall sample values as UI placeholders, not as production retrieval quality.

> The backend does not expose `/docs` by default. For route details, see this overview, [TOOLS_EN.md](TOOLS_EN.md), and the API tests under `backend/tests/`.

---

## 4. MCP Tools

| Tool | Type | Description |
|---|---|---|
| `read_memory` | Read | Full or chunked reads, includes system URIs |
| `create_memory` | Write | Create memory (Write Guard, enters write lane) |
| `update_memory` | Write | Prefers `old_string/new_string` for precise replacement; `append` for tail appending |
| `delete_memory` | Write | Delete memory path |
| `add_alias` | Write | Add alias for the same memory (cross-domain supported) |
| `search_memory` | Search | Unified retrieval (keyword/semantic/hybrid), intent classification, strategy templates |
| `compact_context` | Governance | Compress session context into long-term summary |
| `rebuild_index` | Maintenance | Full or single index rebuild, sleep consolidation |
| `index_status` | Maintenance | Query index availability and runtime status |

Details and degradation semantics: [TOOLS_EN.md](TOOLS_EN.md)

---

## 5. Frontend Structure

```
frontend/src/
├── App.jsx                    # Routes and page skeleton
├── main.jsx                   # React entry
├── RootErrorBoundary.jsx      # Root-level render crash fallback
├── i18n.js                    # react-i18next initialization
├── lib/
│   ├── api.js                 # Unified API client + runtime auth injection
│   ├── sse.js                 # Lightweight SSE helper
│   └── format.js              # Locale-aware date / number formatting
├── locales/{en,zh-CN}.js
├── features/
│   ├── memory/                # Tree browsing, L0/L1/L2 hierarchy
│   ├── review/                # diff / rollback / integrate
│   ├── maintenance/           # vitality cleanup, forgetting candidates
│   └── observability/         # retrieval stats, Search Quality panel
└── components/                # DiffViewer / GlassCard / SnapshotList etc.
```

### Dashboard Modules

| Module | Route | Function |
|---|---|---|
| Memory Browser | `/memory` | Browse by domain, inline editing, gist summaries, alias management, L0/L1/L2 hierarchy |
| Review | `/review` | View snapshot diffs, rollback, integrate, clean deprecated memories |
| Maintenance | `/maintenance` | Vitality scores, orphan cleanup, index rebuild, cleanup approval, forgetting simulation and archive |
| Observability | `/observability` | Retrieval logs, task records, index worker, system status, Search Quality panel |

**Frontend behavior**:

- First visit without saved language: common Chinese browsers (`zh`, `zh-TW`, `zh-HK`, `zh-*`) normalize to `zh-CN`; others fall back to English
- Language preference saved as `localStorage["memory-palace.locale"]`
- React root wraps `RootErrorBoundary`: render crashes show a minimal recovery shell (locale-aware)
- Browser-side Dashboard auth lives in `sessionStorage`; legacy `localStorage` values are migrated once
- Docker one-click: frontend proxy auto-forwards `MCP_API_KEY`; the browser page does not know the proxy-held key
- Setup Assistant clears hidden stale fields when switching Profile / backend; switching to remote backend only saves `RETRIEVAL_EMBEDDING_DIM` when explicitly provided
- Vitality cleanup multi-delete executes atomically when the backend supports session-backed delete; otherwise the batch is rejected to avoid partial success
- Memory Browser "leave unsaved edits" and "delete path" use fail-closed confirmation

---

## 6. Frontend Authentication Injection

The frontend does not read maintenance keys from `VITE_*` build variables; it uses runtime injection:

```html
<script>
  window.__MEMORY_PALACE_RUNTIME__ = {
    maintenanceApiKey: "<YOUR_MCP_API_KEY>",
    maintenanceApiKeyMode: "header"   // or "bearer"
  };
</script>
```

- `maintenanceApiKeyMode`: `header` (`X-MCP-API-Key`) or `bearer` (`Authorization: Bearer`)
- Compatible with the legacy field name `window.__MCP_RUNTIME_CONFIG__`
- Priority: Setup Assistant key just saved > runtime-injected key > browser-session-saved key
- When mode switches, the interceptor removes the old header before adding the new one, avoiding two competing auth headers

**Docker one-click** uses a third method: instead of injecting the key into the page, the frontend proxy forwards it automatically.

---

## 7. Data and Task Flow

### Write Path

1. `create_memory` / `update_memory` enters the **write lane** (serialized; bounded retry on transient SQLite lock conflicts)
2. **Write Guard** decision before writing (`ADD` / `UPDATE` / `NOOP` / `DELETE`; `BYPASS` is the marker for metadata-only updates)
   - Three-level chain: semantic match → keyword match → LLM decision (optional)
3. Generate **snapshot** and version changes (recorded separately by `path` and `memory` dimensions; same-session snapshot writes serialized through a file lock)
4. Enqueue **index task** (returns `index_dropped` / `queue_full` when saturated)

### Retrieval Path

1. **`preprocess_query`** preprocesses the query (whitespace normalization, tokenization, URI preservation)
2. **`classify_intent`** routes by 4 core intents:
   - `factual` → `factual_high_precision` (high-precision matching)
   - `exploratory` → `exploratory_high_recall` (high-recall exploration)
   - `temporal` → `temporal_time_filtered` (time filtering)
   - `causal` → `causal_wide_pool` (causal reasoning)
   - `unknown` → `default` (conservative fallback on conflicting / low-signal queries)
3. Execute **keyword / semantic / hybrid** retrieval
4. Optional **reranker** re-ranking
5. Supports `scope_hint`, `domain`, `path_prefix`, `max_priority`
6. Returns `results` and `degrade_reasons`

> Intent classification uses keyword scoring; no external model call required.
>
> Vector-dimension checks follow the scope the query actually targets; unrelated domains don't trigger false rebuild prompts.
>
> `scope_hint=fast|deep` is first interpreted as an interaction-tier shortcut. New callers should pass `interaction_tier` directly.

**Optional configuration**:

- `INTENT_LLM_ENABLED` disabled by default; enabled, tries LLM intent classification first and falls back to keyword rules
- `RETRIEVAL_MMR_ENABLED` is disabled by default; Profile C/D templates also keep it explicitly disabled, and it only runs under `hybrid` when manually enabled
- `RRF_ENABLED` is off in raw code defaults; Profile B explicitly enables it (`RRF_K=10`), while Profile C/D explicitly disable it (`RRF_K=60`). Profile A is not applicable. RRF runs over allowlisted `fts5` / `vector` channels
- `ENTITY_RERANK_WEIGHT` defaults to `0.0`; entity signal is a post-fusion boost, not a third RRF channel
- `RETRIEVAL_SQLITE_VEC_ENABLED` is explicitly enabled by Profile C/D templates (`RETRIEVAL_VECTOR_ENGINE=vec`); the extension path is auto-discovered from pip `sqlite-vec` when available and falls back to legacy when absent. A/B remain off

![Memory Write and Review Sequence Diagram](images/记忆写入与审查时序图.png)

---

## 8. Deployment Specifications

| Scenario | Host Port | Container Internal Port |
|---|---|---|
| Local Development | Backend `8000` · Frontend `5173` | — |
| Docker Default | Backend `18000` · Frontend `3000` · SSE `3000/sse` | Backend `8000` (serves both REST + SSE) · Frontend `8080` |

Port environment variables:

- Backend: `MEMORY_PALACE_BACKEND_PORT` (default `18000`, falls back to `NOCTURNE_BACKEND_PORT`)
- Frontend: `MEMORY_PALACE_FRONTEND_PORT` (default `3000`, falls back to `NOCTURNE_FRONTEND_PORT`)

`docker-compose.yml` and `docker-compose.ghcr.yml` bind host ports to `127.0.0.1` by default, so external machines cannot reach the services directly. For remote access, change the port variables in `.env.docker` to the `0.0.0.0:<port>` form, and make sure your firewall and `MCP_API_KEY` are in place.

> Changing the SSE listening address to `0.0.0.0` only means remote clients can connect; it does **not** mean `MCP_API_KEY`, reverse proxies, firewalls, or TLS can be bypassed.

### Related Files

- **Compose**: `docker-compose.yml`, `docker-compose.ghcr.yml`
- **Images**: `deploy/docker/Dockerfile.backend` (based on `python:3.11-slim`), `deploy/docker/Dockerfile.frontend` (build `node:22-alpine`, runtime `nginxinc/nginx-unprivileged:1.27-alpine`)
- **Healthcheck**: `deploy/docker/backend-healthcheck.py` (requires `/health` to return `status == "ok"`, default 5s timeout)
- **Nginx template**: `deploy/docker/nginx.conf.template` (injects `X-MCP-API-Key` only for protected paths and `/sse` / `/messages`; returns `no-store/no-cache/must-revalidate` on `/index.html`)
- **Entrypoints**: `deploy/docker/backend-entrypoint.sh`, `deploy/docker/frontend-entrypoint.sh`
- **Backup**: `scripts/backup_memory.sh` / `.ps1` (keeps the latest 20 by default, UTC timestamps)
- **Pre-publish check**: `scripts/pre_publish_check.sh` (blocks tracked `.audit` / `.playwright-mcp` artifacts; scans tracked files for local-only endpoint/key patterns)

Public validation results: [EVALUATION_EN.md](EVALUATION_EN.md).

---

## 9. Security Defaults

- All `/maintenance/*`, `/review/*`, `/api/layering/*`, `/api/forgetting/*`, and `/search/quality-metrics` endpoints require API Key auth
- `/browse` read/write endpoints are gated via endpoint-level `Depends(require_maintenance_api_key)`
- Public HTTP endpoints: `/` and `/health` (`/health` is shallow for public access; detailed runtime/index data is reserved for loopback or authenticated requests)
- `MCP_API_KEY` empty defaults to **fail-closed**
- `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` is loopback-only and rejects requests with forwarding headers
- `/setup/config` local `.env` write path is also fail-closed: targets only `.env*` in the current project, requires direct loopback, requires non-empty Dashboard key on first save
- Setup/provider API bases go through normalization and validation; invalid bases at runtime fail closed into fallback
- Docker containers default to non-root:
  - Backend: `app` user (UID `10001`)
  - Frontend: `nginx-unprivileged` image

Detailed policy: [SECURITY_AND_PRIVACY_EN.md](SECURITY_AND_PRIVACY_EN.md)
