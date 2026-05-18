# Memory Palace Deployment Profiles

Choose a profile (A / B / C / D) based on your hardware and use case, then deploy.

## Contents

- [1. Quick Start](#1-quick-start)
- [2. Profile Overview](#2-profile-overview)
- [3. Per-Profile Configuration](#3-per-profile-configuration)
- [4. Optional LLM Parameters](#4-optional-llm-parameters)
- [5. Docker One-Click Deployment](#5-docker-one-click-deployment)
- [6. Manual Startup](#6-manual-startup)
- [7. Local Inference Services](#7-local-inference-services)
- [8. Vitality Parameters](#8-vitality-parameters)
- [9. API Authentication](#9-api-authentication)
- [10. Troubleshooting](#10-troubleshooting)
- [11. Scripts Reference](#11-scripts-reference)

---

## 1. Quick Start

1. **Pick a profile**: choose **B** when in doubt (zero external dependencies); move to C / D once your model services are ready.
2. **Generate `.env`**: run `scripts/apply_profile.sh` (or `.ps1`).
3. **Start services**: Docker one-click **or** manual startup.

> `deploy/profiles/*/profile-*.env` files are templates, not the final `.env`. Run `apply_profile` first, then fine-tune the generated result for your environment.

---

## 2. Profile Overview

| Profile | Search Mode | Embedding | Reranker | Use Case |
|:---:|---|---|:---:|---|
| **A** | `keyword` | Off (`none`) | Off | Minimum requirements, pure keyword search |
| **B** | `hybrid` | Local hash (`hash`) | Off | **Default starting profile**, zero external dependencies |
| **C** | `hybrid` | API (`router`) | On | Use once local/private embedding + reranker services are ready |
| **D** | `hybrid` | API (`router`) | On | Remote API, no local GPU required |

**Notes**:

- A → B: upgrades from pure keyword to hybrid search (built-in 64-dim hash, no external deps).
- B → C/D: real embedding + reranker for stronger semantic retrieval.
- C vs D: same algorithm path. Defaults differ on endpoint (local vs remote) and reranker weight (C `0.30`, D `0.35`).

> **Before upgrading**: if your database already contains vectors written by a different embedding backend, run `index_status()` first. If dimensions don't match, run `rebuild_index(wait=true)` or validate against a fresh database. The system does not auto-migrate old vectors.

> **Configuration priority**:
> - `RETRIEVAL_EMBEDDING_BACKEND` only controls Embedding, not Reranker.
> - Reranker has no `_BACKEND` switch; it is toggled solely by `RETRIEVAL_RERANKER_ENABLED`.
> - Reranker addresses/keys prefer `RETRIEVAL_RERANKER_API_BASE/API_KEY`, falling back to `ROUTER_*`, then `OPENAI_*`.
> - the shipped `profile-c` template still enables the Reranker by default; if your service has no `/rerank`, disable `RETRIEVAL_RERANKER_ENABLED` first or stay on B.

---

## 3. Per-Profile Configuration

### Profile A — Pure Keyword

```bash
SEARCH_DEFAULT_MODE=keyword
RETRIEVAL_EMBEDDING_BACKEND=none
RETRIEVAL_RERANKER_ENABLED=false
RUNTIME_INDEX_WORKER_ENABLED=false
```

### Profile B — Hybrid + Local Hash (Default)

```bash
SEARCH_DEFAULT_MODE=hybrid
RETRIEVAL_EMBEDDING_BACKEND=hash
RETRIEVAL_EMBEDDING_MODEL=hash-v1
RETRIEVAL_EMBEDDING_DIM=64
RETRIEVAL_RERANKER_ENABLED=false
RUNTIME_INDEX_WORKER_ENABLED=true
RUNTIME_INDEX_DEFER_ON_WRITE=true
```

### Profile C — Local / Private API

```bash
SEARCH_DEFAULT_MODE=hybrid
RETRIEVAL_EMBEDDING_BACKEND=router

# Embedding
ROUTER_API_BASE=http://127.0.0.1:PORT/v1
ROUTER_API_KEY=replace-with-your-key
ROUTER_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_EMBEDDING_API_BASE=http://127.0.0.1:PORT/v1
RETRIEVAL_EMBEDDING_API_KEY=replace-with-your-key
RETRIEVAL_EMBEDDING_DIM=<provider-vector-dim>

# Reranker
RETRIEVAL_RERANKER_ENABLED=true
RETRIEVAL_RERANKER_API_BASE=http://127.0.0.1:PORT/v1
RETRIEVAL_RERANKER_API_KEY=replace-with-your-key
RETRIEVAL_RERANKER_MODEL=your-reranker-model-id
RETRIEVAL_RERANKER_WEIGHT=0.30
```

Without a unified `router`, configure directly:

```bash
RETRIEVAL_EMBEDDING_BACKEND=api
RETRIEVAL_RERANKER_ENABLED=true
RETRIEVAL_RERANKER_API_BASE=http://127.0.0.1:PORT/v1
RETRIEVAL_RERANKER_API_KEY=replace-with-your-key
RETRIEVAL_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_RERANKER_MODEL=your-reranker-model-id
```

### Profile D — Remote API

Difference from C: endpoints point to remote, default reranker weight is higher.

```bash
ROUTER_API_BASE=https://router.example.com/v1
RETRIEVAL_EMBEDDING_API_BASE=https://router.example.com/v1
RETRIEVAL_RERANKER_API_BASE=https://router.example.com/v1
RETRIEVAL_RERANKER_WEIGHT=0.35
```

### Key Tips

- **`RETRIEVAL_EMBEDDING_DIM`** must match the actual dimension returned by your provider. It is sent as `dimensions` on OpenAI-compatible `/embeddings` requests; if the provider rejects it, the runtime retries once without that field.
- **API base means the service root** (usually up to `/v1`). Do not write specific endpoint suffixes like `/embeddings`, `/rerank`, `/chat/completions` — common suffixes are normalized automatically, but malformed or link-local addresses fail closed.
- **`127.0.0.1` / `::1` / `localhost`** are allowed by default. Other private IP literals require `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS`.
- **Placeholder values are rejected**: example values like `https://router.example.com/v1` or `your-embedding-model-id` will be blocked on save or startup. Replace them with real values.
- **Primary tuning parameter**: `RETRIEVAL_RERANKER_WEIGHT`, suggested range `0.20 ~ 0.40`, tune in `0.05` increments.

---

## 4. Optional LLM Parameters

Three optional LLM features: Write Guard, context compaction, intent enhancement.

```bash
# Write Guard (filters low-quality writes)
WRITE_GUARD_LLM_ENABLED=false
WRITE_GUARD_LLM_API_BASE=
WRITE_GUARD_LLM_API_KEY=
WRITE_GUARD_LLM_MODEL=your-chat-model-id

# Compact Context Gist (generates session summaries)
COMPACT_GIST_LLM_ENABLED=false
COMPACT_GIST_LLM_API_BASE=
COMPACT_GIST_LLM_API_KEY=
COMPACT_GIST_LLM_MODEL=your-chat-model-id

# Intent (experimental intent classification)
INTENT_LLM_ENABLED=false
INTENT_LLM_API_BASE=
INTENT_LLM_API_KEY=
INTENT_LLM_MODEL=your-chat-model-id
```

- When `COMPACT_GIST_LLM_*` is unset, it falls back to `WRITE_GUARD_LLM_*`.
- Both paths use OpenAI-compatible `/chat/completions`.
- `INTENT_LLM` is experimental; falls back to keyword rules when disabled.
- Advanced parameters (`CORS_ALLOW_*`, `RETRIEVAL_MMR_*`, `INDEX_LITE_ENABLED`, etc.) are documented in `.env.example`.

---

## 5. Docker One-Click Deployment

### Option 1: GHCR Prebuilt Images (recommended when local builds keep failing)

```bash
cd <project-root>
bash scripts/apply_profile.sh docker b .env.docker

docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

```powershell
cd <project-root>
.\scripts\apply_profile.ps1 -Platform docker -Profile b -Target .env.docker

docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

Notes:

- This path covers Dashboard / API / SSE but does not auto-install local skills / MCP / IDE host config.
- **Ports are not auto-adjusted**. If `3000` / `18000` are taken, set `MEMORY_PALACE_FRONTEND_PORT` / `MEMORY_PALACE_BACKEND_PORT` explicitly.
- To reach a host model service from inside a container, use `host.docker.internal`, not `127.0.0.1`.

### Option 2: Local Build via One-Click Script

```bash
# macOS / Linux
cd <project-root>
bash scripts/docker_one_click.sh --profile b

# Profile C/D — inject API base / key / model from current shell
bash scripts/docker_one_click.sh --profile c --allow-runtime-env-injection
```

```powershell
# Windows PowerShell
cd <project-root>
.\scripts\docker_one_click.ps1 -Profile b
.\scripts\docker_one_click.ps1 -Profile c -AllowRuntimeEnvInjection
```

The script:

1. Generates a per-run Docker env file from the profile template
2. Detects port conflicts, persistent volumes, and risky bind mounts
3. Adds a deployment lock so concurrent runs under the same checkout don't overwrite each other
4. Starts backend + frontend, waits for `/health`, then verifies `/sse` reachability

**Runtime env injection is limited to `profile c/d`**. Passing the flag to `profile a/b` is rejected.

### Access After Deployment

| Service | Host Port | URL |
|---|:---:|---|
| Frontend | `3000` | `http://localhost:3000` |
| Backend | `18000` | `http://localhost:18000` |
| SSE | `3000` | `http://localhost:3000/sse` |
| Health Check | `18000` | `http://localhost:18000/health` |

### Security

- Backend container runs as non-root (UID `10001`)
- Frontend uses the `nginxinc/nginx-unprivileged` image
- Compose sets `security_opt: no-new-privileges:true`

### Stopping Services

```bash
COMPOSE_PROJECT_NAME=<printed-compose-project-name> docker compose -f docker-compose.yml down --remove-orphans
```

> `down --remove-orphans` keeps your data volumes. Use `down -v` to wipe the database and review snapshots.

**WAL boundary**: defaults are `named volume + WAL`. If you replace `/app/data` with an NFS/CIFS/SMB bind mount, set `MEMORY_PALACE_DOCKER_WAL_ENABLED=false` and `MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete`. The one-click script preflights this before startup; if you bypass the one-click script and run `docker compose up` manually, do the same preflight yourself.

---

## 6. Manual Startup

### Step 1: Generate `.env`

```bash
# macOS / Linux (Profile B)
cd <project-root>
bash scripts/apply_profile.sh macos b

# Windows PowerShell
.\scripts\apply_profile.ps1 -Platform windows -Profile b
```

> The script copies `.env.example`, then appends overrides from `deploy/profiles/<platform>/profile-<x>.env`. Local platform default target is `.env`; for `docker` it is `.env.docker`. Existing targets are backed up to `*.bak` first.

To preview only, use `--dry-run`:

```bash
bash scripts/apply_profile.sh --dry-run macos b
.\scripts\apply_profile.ps1 -Platform windows -Profile b -DryRun
```

### Step 2: Start the Backend

```bash
cd <project-root>/backend
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 18000
```

### Step 3: Start the Frontend

```bash
cd <project-root>/frontend
npm install
MEMORY_PALACE_API_PROXY_TARGET=http://127.0.0.1:18000 npm run dev -- --host 127.0.0.1 --port 3000
```

To proxy same-origin SSE through Vite, add:

```bash
MEMORY_PALACE_SSE_PROXY_TARGET=http://127.0.0.1:8010
```

---

## 7. Local Inference Services

Profile C needs local embedding / reranker models. Common services:

| Service | Documentation | Hardware |
|---|---|---|
| Ollama | [docs.ollama.com](https://docs.ollama.com/gpu) | CPU OK; GPU sized by model |
| LM Studio | [lmstudio.ai](https://lmstudio.ai/docs/app/system-requirements) | 16GB+ RAM |
| vLLM | [docs.vllm.ai](https://docs.vllm.ai/en/stable/getting_started/installation/gpu.html) | Linux-first; NVIDIA compute 7.0+ |
| SGLang | [docs.sglang.ai](https://docs.sglang.ai/index.html) | NVIDIA / AMD / CPU / TPU |

OpenAI-compatible interfaces:

- Ollama: [OpenAI Compatibility](https://docs.ollama.com/api/openai-compatibility)
- LM Studio: [OpenAI Endpoints](https://lmstudio.ai/docs/app/api/endpoints/openai)

> Memory Palace calls embedding and reranker through OpenAI-compatible APIs. When reranker is enabled, the service must also expose a `/rerank` endpoint.

---

## 8. Vitality Parameters

The vitality system manages memory lifecycle: **access reinforcement → natural decay → cleanup candidate → manual confirmation**.

| Parameter | Default | Description |
|---|:---:|---|
| `VITALITY_MAX_SCORE` | `3.0` | Maximum vitality score |
| `VITALITY_REINFORCE_DELTA` | `0.08` | Increase per retrieval hit |
| `VITALITY_DECAY_HALF_LIFE_DAYS` | `30` | Decay half-life (days) |
| `VITALITY_DECAY_MIN_SCORE` | `0.05` | Decay floor |
| `VITALITY_CLEANUP_THRESHOLD` | `0.35` | Below this becomes a cleanup candidate |
| `VITALITY_CLEANUP_INACTIVE_DAYS` | `14` | Inactivity threshold (days) |
| `RUNTIME_VITALITY_DECAY_CHECK_INTERVAL_SECONDS` | `600` | Decay check interval (seconds) |
| `RUNTIME_CLEANUP_REVIEW_TTL_SECONDS` | `900` | Cleanup confirmation window (seconds) |
| `RUNTIME_CLEANUP_REVIEW_MAX_PENDING` | `64` | Maximum pending confirmations |

**Tuning**:

1. Keep defaults for 1-2 weeks before adjusting
2. Too many cleanup candidates → raise `VITALITY_CLEANUP_THRESHOLD` or `VITALITY_CLEANUP_INACTIVE_DAYS`
3. Confirmation window too short → increase `RUNTIME_CLEANUP_REVIEW_TTL_SECONDS`

---

## 9. API Authentication

These endpoints are protected by `MCP_API_KEY` (**fail-closed**, returns `401` when unset):

- `/maintenance/*`, `/browse/*`, `/review/*`
- `/api/layering/*`, `/api/forgetting/*`, `/search/quality-metrics`
- SSE: `/sse` and `/messages`

**Header format (either works)**:

```
X-MCP-API-Key: <YOUR_MCP_API_KEY>
Authorization: Bearer <YOUR_MCP_API_KEY>
```

### Local Debug Override

Setting `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` bypasses auth:

- Only effective for loopback requests (`127.0.0.1` / `::1` / `localhost`)
- Non-loopback requests still return `401`

> MCP stdio mode does not go through the HTTP/SSE auth middleware.

### Frontend Access

**Manual local startup** — inject at runtime in your page:

```html
<script>
  window.__MEMORY_PALACE_RUNTIME__ = {
    maintenanceApiKey: "<MCP_API_KEY>",
    maintenanceApiKeyMode: "header"   // or "bearer"
  };
</script>
```

> Don't put a real key in public pages. For shared deployments use a server-side proxy.

**Docker one-click** — the frontend proxy forwards `MCP_API_KEY` automatically for protected paths. Treat the frontend `3000` port as a trusted admin entry; to expose it beyond a trusted network, add a VPN, reverse-proxy auth, or ACL.

### SSE Startup Example

```bash
HOST=127.0.0.1 PORT=8010 python run_sse.py
```

> `run_sse.py` tries `127.0.0.1:8000` first and falls back to `8010` if occupied. To serve other hosts, bind `0.0.0.0`, then add `MCP_API_KEY`, network isolation, a reverse proxy, and TLS. Remote hostnames / origins also need `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS`.

---

## 10. Troubleshooting

### Common Issues

| Issue | Solution |
|---|---|
| Poor retrieval | Confirm `SEARCH_DEFAULT_MODE=hybrid`; for C/D check `RETRIEVAL_RERANKER_WEIGHT` |
| Model service unavailable | System degrades automatically; inspect `degrade_reasons` in the response |
| `embedding_request_failed` / `embedding_fallback_hash` | External embedding/reranker is unreachable; see below |
| Docker port conflict | One-click finds free ports automatically; or set `--frontend-port` / `--backend-port` |
| SSE `address already in use` | Free the port or pass `PORT=<free-port>` |
| Database missing after upgrade | Backend auto-recovers from historical filenames (`agent_memory.db` / `nocturne_memory.db`) |

### C/D Degradation Diagnostics

```bash
# 1. Is the service up?
curl -fsS http://127.0.0.1:18000/health

# 2. Hit the embedding / reranker endpoints directly
curl -fsS -X POST <RETRIEVAL_EMBEDDING_API_BASE>/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <RETRIEVAL_EMBEDDING_API_KEY>" \
  -d '{"model":"<RETRIEVAL_EMBEDDING_MODEL>","input":"ping","dimensions":<RETRIEVAL_EMBEDDING_DIM>}'

curl -fsS -X POST <RETRIEVAL_RERANKER_API_BASE>/rerank \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <RETRIEVAL_RERANKER_API_KEY>" \
  -d '{"model":"<RETRIEVAL_RERANKER_MODEL>","query":"ping","documents":["pong"]}'
```

For local debugging, temporarily switch to `RETRIEVAL_EMBEDDING_BACKEND=api` with direct config. Restore the target environment's `router` config and re-verify before going live.

### Tuning Notes

- **`RETRIEVAL_RERANKER_WEIGHT`**: too high over-relies on the reranker; tune in `0.05` increments.
- **Data persistence**: two compose-project-scoped volumes by default (`<project>_data` mounted at `/app/data`, `<project>_snapshots` at `/app/snapshots`).
- **Migration lock**: `DB_MIGRATION_LOCK_FILE` (default `<db_file>.migrate.lock`) and `DB_MIGRATION_LOCK_TIMEOUT_SEC` (default `10` seconds) prevent concurrent migrations.

---

## 11. Scripts Reference

| Script | Description |
|---|---|
| `scripts/apply_profile.sh` | Generate env file from template (local default `.env`; docker default `.env.docker`) |
| `scripts/apply_profile.ps1` | Windows PowerShell equivalent |
| `scripts/docker_one_click.sh` | Docker one-click deployment (macOS / Linux) |
| `scripts/docker_one_click.ps1` | Docker one-click deployment (Windows) |
| `scripts/backup_memory.sh` / `.ps1` | Database backup (keeps the latest 20 by default, UTC timestamps) |

### Template File Structure

```
deploy/profiles/
├── macos/
├── windows/
├── linux/
└── docker/
    profile-{a,b,c,d}.env
```
