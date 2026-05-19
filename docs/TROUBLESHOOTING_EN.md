# Troubleshooting

Organized by problem. Common issues first, then configuration and deep issues.

---

## 1. Frontend Won't Load or API Times Out

**Symptom**: The page opens but lists are empty, or APIs return 502 / error.

If you see `Set API key` in the top-right corner, or `Memory / Review / Maintenance / Observability` shows empty states or `401`, it's usually not a frontend failure but **unauthorized access to protected endpoints**. With Docker one-click deployment the button may still appear (the browser doesn't know the proxy holds the key), but protected data should already work.

Steps:

1. Confirm the backend is up:
   ```bash
   curl -fsS http://127.0.0.1:8000/health
   ```

2. Check the frontend proxy target. `frontend/vite.config.js` defaults to `http://127.0.0.1:8000`. If the backend listens elsewhere:
   ```bash
   MEMORY_PALACE_API_PROXY_TARGET=http://127.0.0.1:9000 npm run dev
   ```

3. For Docker, check port mapping:
   - Backend default `18000` (mapped to container `8000`)
   - Frontend default `3000` (mapped to container `8080`)
   - Override with `MEMORY_PALACE_BACKEND_PORT` / `MEMORY_PALACE_FRONTEND_PORT`

4. Check backend logs:
   ```bash
   # Local startup: read terminal output
   # Docker
   docker compose -f docker-compose.yml logs backend --tail=50
   ```

### Edge Feels Laggy but Chrome Is Smooth

The frontend detects Microsoft Edge and switches to a lighter visual mode (full functionality preserved, just trims animations and blur). If only Edge feels laggy, treat it as a browser-rendering issue rather than a backend issue.

---

## 2. Switch Between English and Chinese

There is a language toggle in the top-right corner. Your choice is remembered by the browser.

The first-run setup assistant has its own language toggle, so you don't need to close it first.

---

## 3. Local stdio MCP Disconnects Immediately

Common errors:
- `connection closed: initialize response`
- `Read-only file system: '/app'`
- `DATABASE_URL` in `.env` points at `/app/data/...` or `/data/...`

The cause: you copied a container-only path into your local `.env`. `scripts/run_memory_palace_mcp_stdio.sh` only serves the host machine; it doesn't reuse `/app/data` from a Docker container.

This shell wrapper exports `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1` before Python starts, so non-UTF-8 locales are less likely to corrupt stdio traffic.

Fix:

1. Change `DATABASE_URL` in `.env` to a host-side absolute path:
   ```dotenv
   DATABASE_URL=sqlite+aiosqlite:////absolute/path/to/memory_palace/demo.db
   ```

2. Or regenerate `.env`:
   ```bash
   bash scripts/apply_profile.sh macos b
   ```

3. If you actually want to reuse Docker data, don't use local stdio. Point the client at the Docker-exposed `/sse` instead.

---

## 4. Memory Page Doesn't React to Delete or Switch

Some WebView / IDE hosts can't show native confirm dialogs. The Memory page now fails closed: it blocks the action instead of silently deleting or navigating away.

Reproduce in a standard browser, or check whether the host disables native dialogs.

---

## 5. Protected Endpoint Returns 401

`/maintenance/*`, `/review/*`, and `/browse/*` are protected by `MCP_API_KEY` and fail closed by default.

Pick one:

```bash
# Custom header
curl -fsS http://127.0.0.1:8000/maintenance/orphans \
  -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>"

# Bearer
curl -fsS http://127.0.0.1:8000/maintenance/orphans \
  -H "Authorization: Bearer <YOUR_MCP_API_KEY>"
```

For the frontend: click `Set API key` / `Update API key` in the top right, or inject `window.__MEMORY_PALACE_RUNTIME__` in the browser (see [SECURITY_AND_PRIVACY_EN.md](SECURITY_AND_PRIVACY_EN.md)).

For local debugging, set in `.env`:
```env
MCP_API_KEY_ALLOW_INSECURE_LOCAL=true
```
Only direct loopback requests are exempted.

**If `.env` was changed but the service still uses an old key**: check whether the current shell already exported `MCP_API_KEY`. Process env vars take precedence over `.env`:

```bash
env | rg '^MCP_API_KEY=|^MCP_API_KEY_ALLOW_INSECURE_LOCAL='
unset MCP_API_KEY MCP_API_KEY_ALLOW_INSECURE_LOCAL
# Then restart backend / run_sse.py
```

Meaning of the `reason` field:

| `reason` | Meaning | Fix |
|---|---|---|
| `invalid_or_missing_api_key` | Key wrong or missing | Check the key |
| `api_key_not_configured` | `MCP_API_KEY` empty in `.env` | Set the key or enable insecure local |
| `insecure_local_override_requires_loopback` | Insecure local enabled but request isn't loopback | Access from `127.0.0.1` |

---

## 6. SSE Startup Failure or Port Conflict

`python run_sse.py` reports `address already in use`, or `http://127.0.0.1:3000/sse` fails to load.

1. Confirm the path you're on:
   - Local standalone: use the `/health` probe below
   - Docker: check `http://127.0.0.1:3000/sse` (Docker no longer has a separate sse container)

2. Probe the SSE process:
   ```bash
   curl -fsS http://127.0.0.1:8010/health
   ```
   `{"status":"ok","service":"memory-palace-sse"}` means it's up.

3. Change the port:
   ```bash
   HOST=127.0.0.1 PORT=8010 python run_sse.py
   ```
   `run_sse.py` tries `8000` first and falls back to `8010` if occupied. The log prints the final `/sse` address; update client config to match.

4. Find and release the port:
   ```bash
   # macOS / Linux
   lsof -i :8000
   kill -9 <PID>

   # Windows PowerShell
   netstat -ano | findstr :8000
   taskkill /PID <PID> /F
   ```

### `/messages` Returns 404 or 410

The `session_id` is no longer valid. `404` means the server can't find the session; `410` means the SSE writer has closed.

Once the SSE stream disconnects, do not reuse the old `session_id`. Reconnect to `/sse`:

```bash
curl -i \
  -H 'Accept: text/event-stream' \
  -H 'X-MCP-API-Key: <YOUR_MCP_API_KEY>' \
  http://127.0.0.1:8010/sse
```

Take the new `session_id` from the new `event: endpoint`, then send to `/messages/?session_id=...`.

---

## 7. Startup Reports `No module named '...'`

Most often `sqlalchemy` or `diff_match_patch`.

`sqlalchemy` is a hard backend dependency. The cause is usually that you're not using `backend/.venv`, or your client points to the system `python` instead of the project's `.venv` Python.

`diff_match_patch` now has a fallback: if missing, `/review/diff` falls back to `difflib.HtmlDiff` and the backend can still start.

Fix:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate           # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

When configuring a client MCP, set `command` to the project's `.venv` Python directly:
- macOS / Linux: `./.venv/bin/python mcp_server.py`
- Windows: `.\.venv\Scripts\python.exe mcp_server.py`

Quick check:

```bash
cd backend
./.venv/bin/python -c "import sqlalchemy; print(sqlalchemy.__version__)"
```

---

## 8. Docker One-Click Script Fails

1. Confirm Docker is available:
   ```bash
   docker compose version
   ```

2. Print help:
   ```bash
   bash scripts/docker_one_click.sh --help
   ```

3. For port conflicts, specify ports:
   ```bash
   bash scripts/docker_one_click.sh --profile b --frontend-port 3100 --backend-port 18100
   ```
   Even if those ports are also occupied, the script keeps searching. Use the addresses printed at the end.

4. Error mentions `backend /app/data`, `WAL`, or `NFS/CIFS/SMB`: this is the pre-startup safety guard. The repository only supports the Docker named volume + WAL combination; if you bypass the one-click script and run `docker compose up` manually, do the same check first. Fix:

   ```bash
   # Option A: return to the default named volume (recommended)
   unset MEMORY_PALACE_DATA_VOLUME

   # Option B: must use a network filesystem? Disable WAL
   export MEMORY_PALACE_DOCKER_WAL_ENABLED=false
   export MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete
   ```

5. Frontend container exits immediately with `MCP_API_KEY contains unsupported control characters`: your key contains characters it shouldn't (newline, carriage return, tab, backtick). Rewrite `MCP_API_KEY` as a **single-line** plain-text value, then restart.

Windows users: use the PowerShell version `scripts/docker_one_click.ps1`.

---

## 9. Search Quality Drops

The `degrade_reasons` field returned by `search_memory` tells you why retrieval degraded. Common values:

| `degrade_reasons` | Meaning |
|---|---|
| `embedding_fallback_hash` | Embedding API unreachable, fell back to local hash |
| `embedding_config_missing` | Embedding config missing |
| `embedding_request_failed` | Embedding API request failed |
| `embedding_dim_mismatch_requires_reindex` | Vector dimension differs from current config; reindex needed |
| `vector_dim_mixed_requires_reindex` | Mixed vector dimensions in the query scope |
| `reranker_request_failed` | Reranker API request failed |
| `reranker_config_missing` | Reranker config missing |
| `fts_query_invalid` | Query unsafe for FTS; safe fallback used |
| `path_revalidation_lookup_failed` | Path revalidation failed; affected result dropped |
| `intent_llm_model_unavailable` | Intent LLM unavailable |
| `compact_gist_llm_empty` | Compact Gist LLM returned empty |
| `index_enqueue_dropped` | Indexing task enqueue dropped |

Request-failure suffixes: `:timeout`, `:http_status:503`, `:connection_failure`, `:rate_limited`, `:upstream_unavailable`, `:retry_exhausted`.

Check Embedding / Reranker API reachability:

```bash
curl -fsS -X POST <RETRIEVAL_EMBEDDING_API_BASE>/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <RETRIEVAL_EMBEDDING_API_KEY>" \
  -d '{"model":"<RETRIEVAL_EMBEDDING_MODEL>","input":"ping","dimensions":<RETRIEVAL_EMBEDDING_DIM>}'

curl -fsS -X POST <RETRIEVAL_RERANKER_API_BASE>/rerank \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <RETRIEVAL_RERANKER_API_KEY>" \
  -d '{"model":"<RETRIEVAL_RERANKER_MODEL>","query":"ping","documents":["pong"]}'
```

Notes:
- `RETRIEVAL_*_API_BASE` may already include `/v1`; don't append it again
- If the local service doesn't require a key, drop the `Authorization` header
- Non-loopback private IP literals must be added to `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS`

Rebuild the index:

```python
rebuild_index(wait=true)
index_status()
```

View the observability summary:

```bash
curl -fsS http://127.0.0.1:8000/maintenance/observability/summary \
  -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>"
```

---

## 10. Frontend Build Failure

```bash
cd frontend
rm -rf node_modules                  # Windows: rmdir /s /q node_modules
npm ci
npm run build
```

Common causes:
- Node.js version mismatch: 20.19+ or 22.12+ recommended
- Network issue: configure an NPM mirror

---

## 11. Database Migration Exception

Startup reports `Timed out waiting for migration lock`.

1. Check for duplicate processes starting at the same time

2. Adjust the lock timeout (`.env`, default 10s):
   ```env
   DB_MIGRATION_LOCK_TIMEOUT_SEC=30
   ```

3. Specify the lock file path manually:
   ```env
   DB_MIGRATION_LOCK_FILE=/tmp/memory_palace.migrate.lock
   ```

   By default the lock file is `<database>.migrate.lock` next to the database file. A second lock `<database>.init.lock` serializes `init_db()` to prevent `backend` and `sse` from racing on first startup. `:memory:` databases don't generate these locks.

4. Delete leftover lock files and restart:
   ```bash
   rm -f /path/to/demo.db.migrate.lock
   rm -f /path/to/demo.db.init.lock
   ```

---

## 12. No Improvement After Index Rebuild

1. Confirm the index is ready:
   ```python
   index_status()  # Should include index_available=true
   ```

2. Check the Embedding backend (see `.env.example`):

   | Profile | `RETRIEVAL_EMBEDDING_BACKEND` |
   |---|---|
   | Profile A | `none` |
   | Profile B | `hash` |
   | Profile C/D | `api` or `router` |

3. Confirm there's actual memory content:
   ```bash
   curl -fsS \
     -H "X-MCP-API-Key: ${MCP_API_KEY}" \
     "http://127.0.0.1:8000/browse/node?domain=core&path="
   ```

4. Try Sleep Consolidation for a deep rebuild:
   ```python
   rebuild_index(sleep_consolidation=true, wait=true)
   ```

5. Check `degrade_reasons` (see section 9)

---

## 13. CORS Errors

Frontend requests to the backend report CORS errors.

Default behavior: when `CORS_ALLOW_ORIGINS` is empty, only common local origins are allowed:

```
http://localhost:5173
http://127.0.0.1:5173
http://localhost:3000
http://127.0.0.1:3000
```

Common causes:
- Frontend dev server proxy not configured (check `frontend/vite.config.js`)
- Docker Nginx not forwarding correctly (check `deploy/docker/nginx.conf.template`)
- Your browser origin isn't in the allowlist

For production, list the explicit origins:

```env
CORS_ALLOW_ORIGINS=https://app.example.com,https://admin.example.com
```

Avoid `*`, especially when you also need credentials / cookies.

---

## 14. Page Still Looks Old After a Docker Update

The Docker frontend `nginx.conf.template` serves `/index.html` with `Cache-Control: no-store, no-cache, must-revalidate`. If you still see the old page:

1. Confirm the frontend container was actually rebuilt and started
2. Hard-refresh the browser
3. If only one external entry shows the problem, check whether that layer overwrote the cache headers

---

## 15. Dashboard Edit Returns 409 / Memory Version Conflict

If you see `409` or `Memory version conflict` when saving on the Memory page, it means the memory was modified by another session (MCP tool, another browser tab, etc.) after you opened it.

Fix: refresh the page to load the latest content, then edit again.

This is the same semantics as the Review page `409` — both prevent overwriting a newer version of the memory.

---

## 16. Getting Help

If the steps above don't help:

1. Read the full backend logs: locally read the terminal, for Docker run `docker compose -f docker-compose.yml logs backend --tail=200`
2. Check `status` and `index` returned by `GET /health`
3. Call `GET /maintenance/observability/summary` (with `X-MCP-API-Key`) for an overview
4. When filing an issue, include: error message, OS, Python version, Node.js version, profile used
