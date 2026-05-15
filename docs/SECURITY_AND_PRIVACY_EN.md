# Memory Palace Security and Privacy Guide

This document is intended for users who deploy and maintain Memory Palace, covering key management, interface authentication, Docker security, and pre-sharing or official release security self-checks.

---

## 1. What You Need to Protect

The following keys **should only exist in local .env or protected deployment environment variables** and should not be committed to Git repositories.

> For the full key list, please refer to [`.env.example`](../.env.example).

| Key | Usage | Corresponding Variable in `.env.example` |
|---|---|---|
| `MCP_API_KEY` | Maintenance API, Review API, Browse read/write, and SSE authentication | `MCP_API_KEY=` |
| `RETRIEVAL_EMBEDDING_API_KEY` | Embedding model API access | `RETRIEVAL_EMBEDDING_API_KEY=` |
| `RETRIEVAL_RERANKER_API_KEY` | Reranker model API access | `RETRIEVAL_RERANKER_API_KEY=` |
| `WRITE_GUARD_LLM_API_KEY` | Write Guard LLM decision | `WRITE_GUARD_LLM_API_KEY=` |
| `COMPACT_GIST_LLM_API_KEY` | Compact Context Gist LLM (automatically falls back to Write Guard if empty) | `COMPACT_GIST_LLM_API_KEY=` |
| `INTENT_LLM_API_KEY` | Experimental Intent LLM decision | `INTENT_LLM_API_KEY=` |
| `ROUTER_API_KEY` | Embedding API access in Router mode; and the fallback key when `RETRIEVAL_RERANKER_API_KEY` is not explicitly configured for the Reranker | `ROUTER_API_KEY=` |

---

## 2. Best Practices

- ✅ Only commit `.env.example`, **do not commit** `.env` (already added to [`.gitignore`](../.gitignore))
- ✅ Only use placeholders like `<YOUR_API_KEY>` in documentation
- ✅ Ensure screenshots do not contain real keys, usernames, or absolute paths before sharing publicly
- ✅ Do not print request headers and keys in external logs
- ✅ Periodically rotate API Keys, especially after changes in team members
- ✅ In Docker scenarios, prioritize using server-side proxy forwarding for authentication headers instead of writing keys into frontend static resources

---

## 3. Interface Authentication Strategy

### Protected API Scope

The following interfaces are protected by default:

| API Prefix | Protection Scope | Code Source |
|---|---|---|
| `/maintenance/*` | All requests | `backend/api/maintenance.py` — `require_maintenance_api_key` as a route dependency |
| `/review/*` | All requests | `backend/api/review.py` — imports and depends on the same authentication function |
| `/browse/*` | All requests (including read operations) | `backend/api/browse.py` — routes are uniformly mounted with `Depends(require_maintenance_api_key)` |
| `/api/layering/*` | All requests | `backend/api/layering.py` — routes depend on the same authentication function |
| `/api/forgetting/*` | All requests | `backend/api/forgetting.py` — routes depend on the same authentication function |
| `/search/quality-metrics` | All requests | `backend/api/search_quality.py` — Search Quality panel API, still maintenance-key protected |
| SSE Interfaces | `/sse` and `/messages` | `backend/run_sse.py` — reusable ASGI auth middleware and SSE transport, used both by standalone `run_sse.py` and by mounts inside `backend/main.py` |

> 📖 `GET` requests for `/browse/node` are also within the scope of authentication; please include `X-MCP-API-Key` or `Authorization: Bearer`.

### Authentication Methods (Choose one)

**Header Method (Recommended):**

```
X-MCP-API-Key: <MCP_API_KEY>
```

**Bearer Token Method:**

```
Authorization: Bearer <MCP_API_KEY>
```

> The backend uses `hmac.compare_digest` for constant-time comparison (see the authentication logic in `backend/api/maintenance.py` and `backend/run_sse.py`) to prevent timing attacks.

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

That client principal is currently built from the **resolved client address** first; when the request carries an API key / Bearer token, the current implementation also mixes in a stable hash of that token. In plain language: reconnecting with a fresh `session_id` no longer clears the `/messages` burst bucket by accident.

If this SSE path is running **behind a trusted proxy** (for example the repository-shipped Docker frontend proxy, or your own private reverse proxy), the current rate-limit key now prefers:

- the first valid IP in `X-Forwarded-For`
- otherwise `X-Real-IP`
- and only falls back to the direct peer address when the request is not coming through a trusted proxy

“Trusted proxy” also does not mean “any request that happens to carry forwarding headers.” The current default trust boundary only includes loopback proxies; for your own non-loopback reverse proxy, you must explicitly allowlist it through `SSE_TRUSTED_PROXY_HOSTS` or `SSE_TRUSTED_PROXY_CIDRS`, otherwise those forwarded headers are ignored for rate-limit bucketing.

In plain language, on the default Docker proxy path, `/messages` burst limiting no longer treats every client as the same frontend-container address; on your own deployment, forwarded IP headers only take effect after that proxy is explicitly allowlisted.

The `/sse` stream also sends heartbeat pings by default (currently every 15 seconds). The goal is simple: make long-lived streams less likely to look silently stuck when they pass through proxies.

This limit is mainly there to catch **misconfigured clients or single-principal bursts**. It is not a substitute for public-edge protection such as VPN, reverse-proxy rate limiting, or network ACLs.

### Default Behavior When No Key is Provided

Authentication follows a **fail-closed** strategy, with the specific logic as follows:

| Condition | Behavior | HTTP Response |
|---|---|---|
| `MCP_API_KEY` is set and the request carries the correct key | ✅ Allowed | — |
| `MCP_API_KEY` is set but the key is incorrect or missing | ❌ Denied | `401`, `reason: invalid_or_missing_api_key` |
| `MCP_API_KEY` is empty, `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`, the request comes from loopback and does not contain `Forwarded` / `X-Forwarded-*` / `X-Real-IP` or other forwarding headers | ✅ Allowed | — |
| `MCP_API_KEY` is empty, `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`, the request comes from loopback but contains `Forwarded` / `X-Forwarded-*` / `X-Real-IP` or other forwarding headers | ❌ Denied | `401`, `reason: insecure_local_override_requires_loopback` |
| `MCP_API_KEY` is empty, `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`, the request is not from loopback | ❌ Denied | `401`, `reason: insecure_local_override_requires_loopback` |
| `MCP_API_KEY` is empty, insecure local is not enabled | ❌ Denied | `401`, `reason: api_key_not_configured` |

> 📌 Loopback addresses only include `127.0.0.1`, `::1`, and `localhost` (code constant `_LOOPBACK_CLIENT_HOSTS`); and the request must be a direct request to the local machine (no `Forwarded` / `X-Forwarded-*` / `X-Real-IP` or other forwarding headers).

### Authentication Anchors in the Current Repository

The above authentication logic is covered in the following test files in the current repository:

- `backend/tests/test_week6_maintenance_auth.py` — Maintenance API five authentication scenarios
- `backend/tests/test_week6_sse_auth.py` — SSE authentication scenarios
- `backend/tests/test_week6_sse_auth.py::test_sse_messages_rate_limit_returns_429` — `/messages` rate limit and `Retry-After` behavior
- `backend/tests/test_week6_sse_auth.py::test_sse_messages_reject_oversized_body_with_413` — `/messages` request-body size ceiling
- `backend/tests/test_week6_sse_auth.py::test_sse_rate_limit_prefers_forwarded_client_ip_for_trusted_proxy` — trusted-proxy path prefers the real client IP
- `backend/tests/test_sensitive_api_auth.py` — Review and Browse read/write authentication
- `backend/tests/test_review_rollback.py` — Review operation authentication test
- `backend/tests/test_reflection_workflow_service.py` — verifies Dashboard `/browse` writes can seed the reflection workflow and that reflection `execute` still enters the write lane
- `backend/tests/test_reflection_workflow_api.py` — verifies reflection rollback still checks an explicitly supplied `session_id`, can recover the original `session_id` when only `job_id` is provided, and still performs best-effort namespace cleanup after the review rollback path
- `backend/tests/test_reflection_observability_summary.py` — verifies `reflection_workflow` summary counters stay restart-stable
- `backend/tests/test_setup_api.py` — verifies loopback access, remote auth, explicit remote embedding-dimension requirements, runtime-default `/setup/status` summary, and Docker fail-closed behavior
- `backend/tests/test_layering_engine.py` / `backend/tests/test_forgetting_engine.py` — verify the L2 read-only boundary, forgetting candidates, and human-confirmed archive behavior
- `backend/tests/test_sse_deploy_contracts.py` — verifies the Docker frontend proxy injects `X-MCP-API-Key` only for protected routes, including `/api/layering/*`, `/api/forgetting/*`, and `/api/search/quality-metrics`
- `backend/tests/test_artifact_stripper.py` / `backend/tests/test_prompt_cache_adapter.py` — verify opt-in adapters default to no-op and only activate when both env flag and host capability are present

---

## 4. Frontend Key Injection (Runtime)

The frontend does not hardcode keys at build time; instead, it reads them via runtime injection. This method is more suitable for local debugging or private deployment environments that you control:

```html
<script>
  window.__MEMORY_PALACE_RUNTIME__ = {
    maintenanceApiKey: "<YOUR_MCP_API_KEY>",
    maintenanceApiKeyMode: "header"  // Optional values: "header" | "bearer"
  };
</script>
```

> ⚠️ This is suitable for local debugging or deployment environments you control. Do not write the real `MCP_API_KEY` directly into public pages or any static resources that will be exposed to end users, as this global object can be read directly in the browser.

**How it Works** (see `frontend/src/lib/api.js`):

1. `readRuntimeMaintenanceAuth()` reads `window.__MEMORY_PALACE_RUNTIME__`
2. axios request interceptor `isProtectedApiRequest()` determines if the request needs authentication
3. Automatically injects authentication headers for `/maintenance/*`, `/review/*`, `/browse/*`, `/setup/*`, `/layering/*`, `/forgetting/*`, and `/search/quality-metrics`
4. Observability now reuses the same auth path for `/sse`: without a browser-side Dashboard key it stays on native `EventSource`; with a key it switches to fetch-based SSE so the same header/bearer auth can be sent without putting the key in the URL; each reconnect also re-resolves the current browser auth while still carrying `Last-Event-ID`, and terminal `4xx` auth failures stop retrying. Changing or clearing browser-side Dashboard auth now also emits a maintenance-auth change event, and the Observability page uses that signal, plus a focus-time recheck, to rebuild its authenticated stream when auth changes or after a terminal `401` stopped retries.

> Compatibility: Also supports the old field name `window.__MCP_RUNTIME_CONFIG__` (see the runtime config fallback logic in `frontend/src/lib/api.js`).

### Security Boundary of the First-run Setup Assistant

The current release adds a Dashboard first-run setup assistant, but it is not a generic “edit server config from the browser” backdoor:

- `/setup/status` is allowed when:
  - the request is a direct loopback request (`127.0.0.1` / `::1` / `localhost`, with no forwarded headers, and with a loopback host in the request itself), or
  - the request carries a valid `MCP_API_KEY`
- the `/setup/config` **write path is loopback-only**; even a request with a valid `MCP_API_KEY` cannot rewrite the host `.env` remotely
- the assistant only writes a white-listed set of env keys; it is not an arbitrary file writer
- it only targets the local checkout `.env`
- `/setup/status` now reports the runtime's real retrieval-default summary as well; when the related env values are unset, a local runtime shows `hash / 64`. The first-run assistant's auto-open `Profile A` baseline is still only a frontend guidance state, not a promise that the HTTP status endpoint will pretend the runtime is `none`
- the first local `.env` save now also requires a non-empty Dashboard key; leaving it blank is rejected by the backend instead of being treated like an anonymous bootstrap
- when the current process is running inside Docker, the assistant explicitly returns `setup_apply_unsupported` and stays in guidance mode instead of pretending it persisted container env / proxy changes
- existing secrets are never echoed back into the UI; the frontend only receives masked “configured vs missing” summaries
- only the Dashboard `MCP_API_KEY` may be stored in the current browser session's `sessionStorage`; embedding / reranker / LLM provider keys are not stored in the browser. If a legacy `localStorage` value is detected, the frontend still only migrates it forward once, but now only removes the old copy when it can confirm that `localStorage` still holds that same old value. This avoids one tab deleting a newer value that was just written by another tab.
- Observability `/sse` subscriptions now follow that same browser-side Dashboard auth path: without a browser-side key they stay on native `EventSource`; with a key they switch to fetch-based SSE. This keeps the key out of the URL, still allows reconnect after transient disconnects, re-resolves the current browser auth on each reconnect while keeping `Last-Event-ID`, and stops retrying on terminal `4xx` auth failures.
- when you switch profiles or turn optional providers back off, the assistant now clears hidden stale router / API fields before saving. In plain language: once a field is no longer active on screen, the browser no longer quietly keeps the old secret around for the next save.
- for remote embedding backends, the assistant now persists the actual `RETRIEVAL_EMBEDDING_DIM` together with the backend selection, and `openai` is part of the supported embedding backend list.
- provider API base fields now go through normalization and validation first: common suffixes such as `/embeddings`, `/rerank`, `/chat/completions`, and `/responses` are trimmed automatically; malformed, credential-bearing, or link-local targets are rejected before save. Loopback IP literals such as `127.0.0.1` / `::1`, plus `localhost`, still stay allowed by default; if you intentionally point at another private IP literal, or at a hostname that resolves to a private non-loopback address, add it to `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` first.
- if the runtime later reads an invalid `chat / embedding / reranker` API base from env, it also fails closed on that value: the bad base is ignored and the code falls back / degrades instead of continuing to send requests to it.
- if a host cannot provide a native confirm dialog, the Memory page now fails closed and keeps the current state instead of silently deleting data or navigating away.
- `ArtifactStripper` and `PromptCacheAdapter` are both opt-in adapters. The stripper requires `ARTIFACT_STRIPPING_ENABLED` plus host capability `can_strip_tool_artifacts=true`; the prompt-cache split requires `PROMPT_CACHE_SPLIT_ENABLED` plus `can_set_system_context=true`. By default they are no-op and do not change `read_memory("system://boot")` or the MCP tool return contract.

**New validation anchors:**

- `backend/tests/test_setup_api.py` — Verifies loopback access, remote auth, white-listed `.env` writes, explicit remote embedding-dimension requirements, the runtime-default `/setup/status` summary, and Docker fail-closed behavior
- `backend/tests/test_reflection_workflow_api.py` — Verifies reflection rollback still checks an explicitly supplied `session_id`, can recover the original `session_id` when only `job_id` is provided, and still performs best-effort namespace cleanup after the review rollback path
- `frontend/src/App.test.jsx` — Verifies first-run auto-open behavior, including the browser-only Dashboard-key flow on the proxy-backed path
- `frontend/src/features/observability/ObservabilityPage.test.jsx` — Verifies Observability switches to the auth-capable SSE path when browser auth exists, refreshes summary after receiving events, and re-establishes the authenticated stream after auth changes
- `frontend/src/lib/api.test.js` — Verifies browser-side maintenance-auth change notifications fire on save/clear and matching storage events
- `frontend/src/features/memory/MemoryBrowser.test.jsx` — Verifies the Memory page blocks destructive actions when confirm is unavailable
- `frontend/src/lib/api.contract.test.js` — Verifies `/setup/*` also goes through the unified auth-header injection path
- `frontend/src/lib/sse.test.js` — Verifies the auth-capable fetch-based SSE path reconnects after transient disconnects, refreshes current browser auth on reconnect while keeping `Last-Event-ID`, and stops retrying on terminal `4xx` auth failures
- `backend/tests/test_external_import_guard_security.py` — Verifies external import rejects oversized single files and oversized batches before content hydration, and rejects invalid UTF-8 as `file_read_failed` without surfacing fd double-close errors

**Default approach for Docker one-click deployment is different:**

- `apply_profile.*` will automatically generate a local key if `MCP_API_KEY` is found to be empty under the `docker` platform.
- The frontend container will not write this key into the page; instead, Nginx proxy will forward the `X-MCP-API-Key` at the server side only to the protected Dashboard API routes, plus `/sse` and `/messages`.
- This way the browser can use the Dashboard directly without exposing the real key in the page source.
- On that trusted proxy path, the first-run assistant should not auto-open just because the browser itself does not hold a stored key. If protected requests already work, the safer proxy-held path is already acting as the configured auth path.
- This convenience path assumes the frontend port itself is trusted. Anyone who can directly reach the Docker Dashboard port can also use those proxied protected routes, so `MCP_API_KEY` is **not** acting as end-user auth at that layer. Put your own VPN, reverse-proxy auth, or network ACL in front of `3000` before exposing it beyond a trusted environment.

**Frontend Test Coverage:**

- `frontend/src/lib/api.contract.test.js` — Verifies runtime config injection and authentication header attachment.

---

## 5. Docker Security

The following security configurations can be directly verified in the project's Docker files:

| Security Measure | Implementation Method | File Reference |
|---|---|---|
| Non-root execution (Backend) | `groupadd --gid 10001 app && useradd --uid 10001` | `deploy/docker/Dockerfile.backend` |
| Non-root execution (Frontend) | Using `nginxinc/nginx-unprivileged:1.27-alpine` base image | `deploy/docker/Dockerfile.frontend` |
| Frontend proxy authentication | Nginx forwards `X-MCP-API-Key` at the server side; the real key is not stored on the browser side. The proxy now injects that header only for protected `/api/maintenance/*`, `/api/review/*`, `/api/browse/*`, `/api/setup/*`, `/api/layering/*`, `/api/forgetting/*`, the exact `/api/search/quality-metrics` route, plus `/sse` / `/messages`, instead of attaching it to every `/api/*` request. Special characters in the proxy-held key are escaped before the final config is generated | `deploy/docker/nginx.conf.template` |
| Prohibit privilege escalation | `security_opt: no-new-privileges:true` | `docker-compose.yml` |
| Data persistence | Docker volumes are isolated per compose project by default: `<compose-project>_data` → `/app/data`, `<compose-project>_snapshots` → `/app/snapshots` | `docker-compose.yml` |
| Health check (Backend) | `python /usr/local/bin/backend-healthcheck.py`; internally it requests `http://127.0.0.1:8000/health` and requires the payload to report `status == "ok"`. The request timeout can be tuned with `MEMORY_PALACE_BACKEND_HEALTHCHECK_TIMEOUT_SEC`. The backend image now also wires this into Docker `HEALTHCHECK` | `backend.healthcheck` in `docker-compose.yml`, `deploy/docker/backend-healthcheck.py`, `deploy/docker/Dockerfile.backend` |
| Health check (Frontend) | `wget -q -O - http://127.0.0.1:8080/` | `frontend.healthcheck` in `docker-compose.yml` |

---

<p align="center">
  <img src="images/security_checklist.png" width="900" alt="Pre-sharing security self-check checklist" />
</p>

## 6. Pre-sharing or Release Self-check Checklist

Before sharing the project, delivering environments, or official release, please complete the following repository hygiene and security self-check steps:

0. **One-click Self-check (Recommended)**:

   ```bash
   bash scripts/pre_publish_check.sh
   ```

   The script checks: common local sensitive artifacts / tool configs / local reports presence, git tracking status, key patterns in tracked files, personal absolute path leaks, and `.env.example` API key placeholder status. It now also blocks tracked `.audit` / `.playwright-mcp` artifacts and scans tracked files for local-only endpoint/key patterns such as `sk-local-*` plus loopback/private provider bases with ports. It's more like a "repository hygiene check before sharing"; finding local files usually results in a `WARN` rather than a `FAIL`.

1. **Check Workspace Status** — Confirm no accidental exposure:

   ```bash
   git status
   ```

   Ensure the following files are not in the commit (already configured in `.gitignore`):
   - `.env`, `.env.*` (keep `.env.example`; if you explicitly reused a fixed Docker env file, this also includes `.env.docker`)
   - `.venv`, `.mcp.json`, `.mcp.json.bak`, `.claude/`, `.codex/`, `.cursor/`, `.opencode/`, `.gemini/`, `.agent/`, `.tmp/`, `.playwright-cli/` (usually generated by your local sync / install / browser-debugging scripts)
   - `*.db` (Database files)
   - `*.init.lock`, `*.migrate.lock` (Database initialization / migration lock files)
   - `backend/backend.log`, `frontend/frontend.log`
   - `snapshots/`, `frontend/dist/`
   - `backend/tests/benchmark/.real_profile_cache/`
   - `docs/skills/TRIGGER_SMOKE_REPORT.md`, `docs/skills/MCP_LIVE_E2E_REPORT.md`
   - Any `.DS_Store`

2. **Keyword Scan** — Check for residual real keys in code and documentation:

   ```bash
   # Search for possible key leaks (suggest looking only at filenames to avoid echoing real values in terminal)
   rg -n -l "sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY" .
   ```

3. **Check Absolute Paths** — Ensure documentation does not contain local machine paths:

   ```bash
   # If you need to check manually, please replace the placeholders below with your actual path prefix
   grep -rn "<user-home>" --include="*.md" <repo-root>
   grep -rn "C:/absolute/path/to/" --include="*.md" <repo-root>
   ```

4. **Verify Running** — Confirm project can be reproducibly built:

   ```bash
   # Minimal check
   bash scripts/pre_publish_check.sh
   curl -fsS http://127.0.0.1:8000/health

   # Frontend build check
   cd frontend && npm ci && npm run test && npm run build
   ```

   > For deeper verification, run `cd backend && .venv/bin/python -m pip install -r requirements-dev.txt && .venv/bin/python -m pytest tests -q` as well.

---

## 7. Local Files That Usually Should Not Be Committed

| File / Directory | Description |
|---|---|
| `.env`, `.env.*` (keep `.env.example`) | May contain real API keys |
| `.venv`, `backend/.venv`, `frontend/.venv` | Local virtual environments, should not enter the repository |
| `.mcp.json`, `.mcp.json.bak`, `.claude/`, `.codex/`, `.cursor/`, `.opencode/`, `.gemini/`, `.agent/`, `.tmp/`, `.playwright-cli/` | Local tool / MCP / browser-debugging artifact directories (usually generated by your local sync / install / debugging scripts) |
| `*.db` | SQLite database files (e.g., `demo.db`) |
| `*.init.lock`, `*.migrate.lock` | Lock files generated during database initialization / migration |
| `backend/backend.log` | Backend running logs |
| `frontend/frontend.log` | Frontend running logs |
| `snapshots/` | Local snapshot directory |
| `backend/tests/benchmark/.real_profile_cache/` | Local benchmark temporary database |
| `__pycache__/`, `.pytest_cache/`, `backend/.pytest_cache/` | Python cache |
| `frontend/node_modules` | NPM dependencies |
| `frontend/dist/` | Frontend build artifacts |
| `.DS_Store` | macOS system files |
| `backups/` | Local backup directory |
| `docs/improvement/` | Phase-specific plans, retest drafts, troubleshooting records |
| `<repo-root>/docs/skills/TRIGGER_SMOKE_REPORT.md` | Local skill smoke summary |
| `<repo-root>/docs/skills/MCP_LIVE_E2E_REPORT.md` | Local MCP e2e summary |
| `backend/docs/benchmark_*.md` | Local benchmark analysis notes |
| `backend/tests/benchmark_results.md` | One-off benchmark summary draft |
| `docs/evaluation_old_vs_new_executive_summary_2026-03-05.md` | One-off comparison summary |
| `docs/changelog/current_code_improvements_vs_legacy_docs.md` | Supplemental difference list |

> 💡 Keep `.env.example` as a configuration template committed to the repository.
>
> 💡 These two local validation reports default to the `docs/skills/` paths listed above; if you redirected them via `MEMORY_PALACE_SKILL_REPORT_PATH` / `MEMORY_PALACE_MCP_E2E_REPORT_PATH`, remember to review that custom file before sharing too.
>
> 💡 Use placeholders in public documentation:
>
> - `<repo-root>`: Repository root directory
> - `<user-home>`: User home directory
> - `/absolute/path/to/...`: macOS / Linux absolute path example
> - `C:/absolute/path/to/...`: Windows absolute path example
