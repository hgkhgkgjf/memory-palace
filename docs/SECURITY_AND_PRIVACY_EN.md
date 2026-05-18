# Memory Palace Security and Privacy Guide

This document is for users who deploy and maintain Memory Palace. It covers key management, interface authentication, Docker security, and pre-sharing or pre-release security self-checks.

---

## 1. What You Need to Protect

The following keys **should only exist in local `.env` or protected deployment environment variables** and should not be committed to Git. For the full key list, see [`.env.example`](../.env.example).

| Key | Usage | Variable in `.env.example` |
|---|---|---|
| `MCP_API_KEY` | Maintenance API, Review API, Browse read/write, and SSE authentication | `MCP_API_KEY=` |
| `RETRIEVAL_EMBEDDING_API_KEY` | Embedding model API access | `RETRIEVAL_EMBEDDING_API_KEY=` |
| `RETRIEVAL_RERANKER_API_KEY` | Reranker model API access | `RETRIEVAL_RERANKER_API_KEY=` |
| `WRITE_GUARD_LLM_API_KEY` | Write Guard LLM decision | `WRITE_GUARD_LLM_API_KEY=` |
| `COMPACT_GIST_LLM_API_KEY` | Compact Context Gist LLM (falls back to Write Guard when empty) | `COMPACT_GIST_LLM_API_KEY=` |
| `INTENT_LLM_API_KEY` | Experimental Intent LLM decision | `INTENT_LLM_API_KEY=` |
| `ROUTER_API_KEY` | Embedding API access in Router mode; and the fallback key when `RETRIEVAL_RERANKER_API_KEY` is not explicitly set | `ROUTER_API_KEY=` |

---

## 2. Best Practices

- Only commit `.env.example`; **do not commit** `.env` (already in [`.gitignore`](../.gitignore))
- Only use placeholders like `<YOUR_API_KEY>` in documentation
- Ensure screenshots do not contain real keys, usernames, or absolute paths before sharing
- Do not print request headers and keys in external logs
- Rotate API keys periodically, especially after team member changes
- In Docker scenarios, prefer server-side proxy forwarding for authentication headers instead of writing keys into frontend static resources

---

## 3. Interface Authentication Strategy

### Protected API Scope

The following interfaces are protected by default:

| API Prefix | Protection Scope |
|---|---|
| `/maintenance/*` | All requests |
| `/review/*` | All requests |
| `/browse/*` | All requests (including read operations) |
| `/api/layering/*` | All requests |
| `/api/forgetting/*` | All requests |
| `/search/quality-metrics` | All requests |
| SSE Interfaces | `/sse` and `/messages` |

> `GET` requests for `/browse/node` are also within the scope of authentication; include `X-MCP-API-Key` or `Authorization: Bearer`.

### Authentication Methods (Choose one)

**Header Method (Recommended):**

```
X-MCP-API-Key: <MCP_API_KEY>
```

**Bearer Token Method:**

```
Authorization: Bearer <MCP_API_KEY>
```

> The backend uses `hmac.compare_digest` for constant-time comparison to prevent timing attacks.

### SSE `/messages` Burst Rate Limit

`/messages` is not an unlimited ingress path. The current implementation applies an in-process burst limit to a **stable client principal**:

| Setting | Default | Purpose |
|---|---|---|
| `SSE_MESSAGE_RATE_LIMIT_WINDOW_SECONDS` | `10` | Accounting window in seconds |
| `SSE_MESSAGE_RATE_LIMIT_MAX_REQUESTS` | `120` | Maximum allowed POSTs for one client principal inside the window |
| `SSE_MESSAGE_MAX_BODY_BYTES` | `1048576` | Hard body-size ceiling for one `/messages` request |

When the limit is hit:

- the server returns `429 Too Many Requests`
- the response includes `Retry-After`
- the affected client principal must wait for the window to drain before posting again
- if the body exceeds `SSE_MESSAGE_MAX_BODY_BYTES`, the server returns `413` before JSON parsing

The client principal is built from the **resolved client address** first; when the request carries an API key / Bearer token, a stable hash of that token is mixed in. Reconnecting with a fresh `session_id` does not clear the `/messages` burst bucket.

If this SSE path runs **behind a trusted proxy** (the repository-shipped Docker frontend proxy, or your own private reverse proxy), the rate-limit key prefers:

- the first valid IP in `X-Forwarded-For`
- otherwise `X-Real-IP`
- and only falls back to the direct peer address when not behind a trusted proxy

The default trust boundary only includes loopback proxies; for your own non-loopback reverse proxy, explicitly allowlist it through `SSE_TRUSTED_PROXY_HOSTS` or `SSE_TRUSTED_PROXY_CIDRS`, otherwise forwarded headers are ignored for rate-limit bucketing.

The `/sse` stream also sends heartbeat pings by default (every 15 seconds), so long-lived streams are less likely to look silently stuck through proxies.

This limit is mainly there to catch **misconfigured clients or single-principal bursts**. It is not a substitute for public-edge protection such as VPN, reverse-proxy rate limiting, or network ACLs.

### Default Behavior When No Key Is Provided

Authentication follows a **fail-closed** strategy:

| Condition | Behavior | HTTP Response |
|---|---|---|
| `MCP_API_KEY` is set and the request carries the correct key | ✅ Allowed | — |
| `MCP_API_KEY` is set but the key is incorrect or missing | ❌ Denied | `401`, `reason: invalid_or_missing_api_key` |
| `MCP_API_KEY` empty, `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`, request comes from loopback and contains no forwarding headers | ✅ Allowed | — |
| `MCP_API_KEY` empty, `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`, request comes from loopback but contains `Forwarded` / `X-Forwarded-*` / `X-Real-IP` headers | ❌ Denied | `401`, `reason: insecure_local_override_requires_loopback` |
| `MCP_API_KEY` empty, `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`, request is not from loopback | ❌ Denied | `401`, `reason: insecure_local_override_requires_loopback` |
| `MCP_API_KEY` empty, insecure local not enabled | ❌ Denied | `401`, `reason: api_key_not_configured` |

> Loopback addresses only include `127.0.0.1`, `::1`, and `localhost`; the request must be a direct request to the local machine (no `Forwarded` / `X-Forwarded-*` / `X-Real-IP` headers).

---

## 4. Frontend Key Injection (Runtime)

The frontend does not hardcode keys at build time; it reads them via runtime injection. This is suitable for local debugging or private deployment environments that you control:

```html
<script>
  window.__MEMORY_PALACE_RUNTIME__ = {
    maintenanceApiKey: "<YOUR_MCP_API_KEY>",
    maintenanceApiKeyMode: "header"  // "header" | "bearer"
  };
</script>
```

> ⚠️ Do not write the real `MCP_API_KEY` directly into public pages or any static resources exposed to end users — this global object can be read directly in the browser.

How it works:

1. The frontend reads `window.__MEMORY_PALACE_RUNTIME__`
2. The axios request interceptor determines if the request needs authentication
3. Authentication headers are injected automatically for `/maintenance/*`, `/review/*`, `/browse/*`, `/setup/*`, `/layering/*`, `/forgetting/*`, and `/search/quality-metrics`
4. Observability reuses the same auth path for `/sse`: without a browser-side Dashboard key it stays on native `EventSource`; with a key it switches to fetch-based SSE so the same header/bearer auth can be sent without putting the key in the URL; each reconnect re-resolves the current browser auth while still carrying `Last-Event-ID`, and terminal `4xx` auth failures stop retrying

> Compatibility: the old field name `window.__MCP_RUNTIME_CONFIG__` is still supported.
>
> If server-side Dashboard auth is already active (especially the standard Docker proxy-held key path), the frontend does not auto-open the first-run assistant just because the browser itself does not hold a stored key.

### Security Boundary of the First-run Setup Assistant

The Dashboard first-run setup assistant is not a generic "edit server config from the browser" backdoor:

- `/setup/status` is allowed when:
  - the request is a direct loopback request (`127.0.0.1` / `::1` / `localhost`, with no forwarded headers, and with a loopback host in the request itself), or
  - the request carries a valid `MCP_API_KEY`
- the `/setup/config` **write path is loopback-only**; even a request with a valid `MCP_API_KEY` cannot rewrite the host `.env` remotely
- the assistant only writes a white-listed set of env keys; it is not an arbitrary file writer
- it only targets the local checkout `.env`
- the first local `.env` save requires a non-empty Dashboard key; leaving it blank is rejected by the backend
- when the current process is running inside Docker, the assistant explicitly returns `setup_apply_unsupported` and stays in guidance mode instead of pretending it persisted container env / proxy changes
- existing secrets are never echoed back into the UI; the frontend only receives masked "configured vs missing" summaries
- only the Dashboard `MCP_API_KEY` is stored in the current browser session's `sessionStorage`; embedding / reranker / LLM provider keys are not stored in the browser
- Observability `/sse` subscriptions follow the same browser-side Dashboard auth path
- when you switch profiles or turn optional providers back off, the assistant clears hidden stale router / API fields before saving
- provider API base fields are normalized and validated: common suffixes such as `/embeddings`, `/rerank`, `/chat/completions`, and `/responses` are trimmed automatically; malformed, credential-bearing, or link-local targets are rejected. Loopback IP literals (`127.0.0.1` / `::1`) and `localhost` stay allowed; other private targets require `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS`
- if the runtime later reads an invalid `chat / embedding / reranker` API base from env, it fails closed on that value: the bad base is ignored and the code falls back / degrades instead of continuing to send requests to it

**Default approach for Docker one-click deployment is different:**

- `apply_profile.*` automatically generates a local key if `MCP_API_KEY` is found empty under the `docker` platform
- the frontend container does not write this key into the page; instead, Nginx proxy forwards the `X-MCP-API-Key` at the server side only to the protected Dashboard API routes, plus `/sse` and `/messages`
- the browser can use the Dashboard directly without exposing the real key in the page source
- this convenience path assumes the frontend port itself is trusted. Anyone who can directly reach the Docker Dashboard port can also use the proxied protected routes, so `MCP_API_KEY` is **not** end-user auth at that layer. Put your own VPN, reverse-proxy auth, or network ACL in front of `3000` before exposing it beyond a trusted environment

---

## 5. Docker Security

The following security configurations can be directly verified in the project's Docker files:

| Security Measure | Implementation | File Reference |
|---|---|---|
| Non-root execution (Backend) | `groupadd --gid 10001 app && useradd --uid 10001` | `deploy/docker/Dockerfile.backend` |
| Non-root execution (Frontend) | `nginxinc/nginx-unprivileged:1.27-alpine` base image | `deploy/docker/Dockerfile.frontend` |
| Frontend proxy authentication | Nginx forwards `X-MCP-API-Key` server-side; the real key is not stored on the browser side. The proxy injects that header only for protected routes (`/api/maintenance/*`, `/api/review/*`, `/api/browse/*`, `/api/setup/*`, `/api/layering/*`, `/api/forgetting/*`, `/api/search/quality-metrics`, plus `/sse` / `/messages`) | `deploy/docker/nginx.conf.template` |
| Prohibit privilege escalation | `security_opt: no-new-privileges:true` | `docker-compose.yml` |
| Data persistence | Docker volumes are isolated per compose project: `<compose-project>_data` → `/app/data`, `<compose-project>_snapshots` → `/app/snapshots` | `docker-compose.yml` |
| Health check (Backend) | `python /usr/local/bin/backend-healthcheck.py`; internally requests `http://127.0.0.1:8000/health` and requires `status == "ok"`. Timeout tunable via `MEMORY_PALACE_BACKEND_HEALTHCHECK_TIMEOUT_SEC` | `docker-compose.yml`, `deploy/docker/backend-healthcheck.py` |
| Health check (Frontend) | `wget -q -O - http://127.0.0.1:8080/` | `docker-compose.yml` |

---

<p align="center">
  <img src="images/security_checklist.png" width="900" alt="Pre-sharing security self-check checklist" />
</p>

## 6. Pre-Sharing or Pre-Release Self-Check Checklist

1. **One-click self-check (recommended)**:

   ```bash
   bash scripts/pre_publish_check.sh
   ```

   The script checks: common local sensitive artifacts / tool configs presence, git tracking status, key patterns in tracked files, personal absolute path leaks, and `.env.example` API key placeholder status. It's a "repository hygiene check before sharing"; finding local files usually results in a `WARN` rather than a `FAIL`.

2. **Check workspace status** — confirm no accidental exposure:

   ```bash
   git status
   ```

   Ensure the following files are not in the commit (already in `.gitignore`):
   - `.env`, `.env.*` (keep `.env.example`)
   - `.venv`, `.mcp.json`, `.mcp.json.bak`, `.claude/`, `.codex/`, `.cursor/`, `.opencode/`, `.gemini/`, `.agent/`, `.tmp/`, `.playwright-cli/`
   - `.pytest_cache/`, `backend/.pytest_cache/` (local test caches)
   - `*.db` (database files)
   - `*.init.lock`, `*.migrate.lock`
   - `backend/backend.log`, `frontend/frontend.log`
   - `snapshots/`, `frontend/dist/`
   - Local validation report outputs (default under `docs/skills/` but not tracked in Git)
   - Any `.DS_Store`

3. **Keyword scan** — check for residual real keys in code and documentation:

   ```bash
   rg -n -l "sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY" .
   ```

4. **Check absolute paths** — ensure documentation does not contain local machine paths:

   ```bash
   grep -rn "<user-home>" --include="*.md" <repo-root>
   grep -rn "C:/absolute/path/to/" --include="*.md" <repo-root>
   ```

5. **Verify build** — confirm the project can be reproducibly built:

   ```bash
   bash scripts/pre_publish_check.sh
   curl -fsS http://127.0.0.1:8000/health
   cd frontend && npm ci && npm run test && npm run build
   ```

---

## 7. Local Files That Usually Should Not Be Committed

| File / Directory | Description |
|---|---|
| `.env`, `.env.*` (keep `.env.example`) | May contain real API keys |
| `.venv`, `backend/.venv`, `frontend/.venv` | Local virtual environments |
| `.mcp.json`, `.mcp.json.bak`, `.claude/`, `.codex/`, `.cursor/`, `.opencode/`, `.gemini/`, `.agent/`, `.tmp/`, `.playwright-cli/` | Local tool / MCP / browser-debugging artifact directories |
| `*.db` | SQLite database files |
| `*.init.lock`, `*.migrate.lock` | Database initialization / migration lock files |
| `backend/backend.log`, `frontend/frontend.log` | Backend / frontend run logs |
| `snapshots/` | Local snapshot directory |
| `__pycache__/`, `.pytest_cache/` | Python cache |
| `frontend/node_modules`, `frontend/dist/` | NPM dependencies and frontend build artifacts |
| `.DS_Store` | macOS system files |
| `backups/` | Local backup directory |

> Use placeholders in public documentation:
>
> - `<repo-root>`: Repository root directory
> - `<user-home>`: User home directory
> - `/absolute/path/to/...`: macOS / Linux absolute path example
> - `C:/absolute/path/to/...`: Windows absolute path example
</content>
