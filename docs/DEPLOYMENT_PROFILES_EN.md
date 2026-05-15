# Memory Palace Deployment Profiles

This document helps you choose the appropriate Memory Palace configuration profile (A / B / C / D) based on your hardware conditions and usage scenarios, and guides you through the deployment process.

---

## Quick Navigation

| Section | Content |
|---|---|
| [1. Three-Step Quick Start](#1-three-step-quick-start) | The fastest way to get started |
| [2. Profiles Overview](#2-profiles-overview) | Differences between A/B/C/D configurations |
| [3. Detailed Configuration for Each Profile](#3-detailed-configuration-for-each-profile) | `.env` parameter descriptions for each profile |
| [4. Optional LLM Parameters (write_guard / compact_context / intent)](#4-optional-llm-parameters-write_guard--compact_context--intent) | Write Guard, context compaction, and intent enhancement |
| [5. Docker One-Click Deployment](#5-docker-one-click-deployment-recommended) | Recommended containerized deployment method |
| [6. Manual Startup](#6-manual-startup) | Local startup method without Docker |
| [7. Local Inference Service Reference](#7-local-inference-service-reference) | Ollama / LM Studio / vLLM / SGLang |
| [8. Vitality Parameters](#8-vitality-parameters) | Memory vitality decay and cleanup mechanism |
| [9. API Authentication](#9-api-authentication) | Security for Maintenance / SSE / Browse / Review interfaces |
| [10. Tuning and Troubleshooting](#10-tuning-and-troubleshooting) | Common issues and optimization suggestions |
| [11. Assistant Scripts Overview](#11-assistant-scripts-overview) | List of all deployment-related scripts |

---

## 1. Three-Step Quick Start

1.  **Choose a Profile**: Select `A`, `B`, `C`, or `D` based on your hardware (choose **B** if unsure; if you already have stable model services and explicitly want stronger semantic retrieval, then move to **C/D**).
2.  **Generate Configuration**: Run the `apply_profile` script to generate the `.env` file.
3.  **Start Services**: Use Docker one-click deployment **OR** manually start the backend + frontend.

> `deploy/profiles/*/profile-*.env` files are template inputs, not the final `.env` files we recommend you copy, commit, or run directly. The stable user path is still: run `apply_profile.sh/.ps1` first, then fine-tune the generated result for your real environment.

> **💡 Note**: **Profile B remains the default starting profile** because it has zero external dependencies. `Profile C/D` are better described as deep-retrieval profiles once your model services are actually ready, not as a seamless hot switch. Before upgrading, confirm that embedding / reranker are reachable and that the vector-dimension settings are correct. If the current database already contains old vectors, check with `index_status()` first and run `rebuild_index(wait=true)` when needed, or validate against a fresh database.

---

## 2. Profiles Overview

| Profile | Search Mode | Embedding Method | Reranker | Use Case |
|:---:|---|---|---|---|
| **A** | `keyword` | Disabled (`none`) | ❌ Disabled | Minimum requirements, pure keyword search, fast verification |
| **B** | `hybrid` | Local Hash (`hash`) | ❌ Disabled | **Default starting profile**, single-machine development, no extra services |
| **C** | `hybrid` | API Call (`router`) | ✅ Enabled | Deep-retrieval profile once local/private embedding+rereanker services are ready |
| **D** | `hybrid` | API Call (`router`) | ✅ Enabled | Quality-first remote API profile, no local GPU required |

**Key Differences**:

*   **A → B**: Upgrades from pure keyword to hybrid search using built-in hash vectors (no external dependencies).
*   **B → C/D**: Once connected to real embedding + reranker models, you may get much better semantic retrieval; if the existing index was written with a different embedding backend / model / dimension, the runtime degrades first and asks for reindex instead of pretending the switch already succeeded.
*   **C vs D**: Identical algorithm paths; the main difference in the default template is the model service address (local vs remote) and the default `RETRIEVAL_RERANKER_WEIGHT` (C=`0.30`, D=`0.35`).

> **Terminology Note (to avoid confusion with evaluation docs)**: The deployment templates describe the actual profile defaults you apply locally, while `docs/EVALUATION_EN.md` summarizes what the public A/B/C/D reruns looked like on that verification round. Use the deployment templates to decide what gets written into `.env`; use the evaluation page to understand how those profiles behaved in the published checks. Neither page is promising a seamless hot-switch on top of old vectors.
>
> **Additional Note**: C/D templates follow the `router` path by default. If your deployment doesn't use a unified router, you can also directly configure `RETRIEVAL_EMBEDDING_*`, `RETRIEVAL_RERANKER_*`, and `WRITE_GUARD_LLM_* / COMPACT_GIST_LLM_*` to connect to OpenAI-compatible services.
>
> **The first-run assistant follows the same wording**: `Profile C` / `Profile D` in the assistant only prefill a more local/private-style router starting point versus a more remote-style router starting point. They do not mean the setup is already valid. Before save, you still need to replace the required router base/model fields with your real values; if you are not using a router, you can switch directly to the `api` / `openai` embedding backend instead. `openai` is an embedding-backend option, not a brand-new extra profile tier. The API-base wording is the same as the backend: enter the provider service base/root (usually up to `/v1`), not a concrete endpoint suffix such as `/embeddings`, `/rerank`, or `/chat/completions`; common suffixes are trimmed automatically, but malformed or link-local targets still fail closed. Loopback IP literals such as `127.0.0.1` / `::1`, plus `localhost`, still stay allowed by default; if you intentionally use another private IP literal, add it to `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` first. One more boundary now matters on a non-Docker local checkout: if there is still no configured Dashboard auth and the first assistant save already contains remote provider-chain fields, the backend first bootstraps only `MCP_API_KEY` / `MCP_API_KEY_ALLOW_INSECURE_LOCAL`; save again after auth is active if you want the retrieval/provider fields to persist.
>
> **One local-template note**: the repository's local `profile c/d` templates now also keep `RUNTIME_AUTO_FLUSH_ENABLED=true` explicitly, so `.env` files generated through `apply_profile.sh/.ps1` keep the same auto-flush default as A/B unless you override it yourself.
>
> **Why not force everything through a router?**
> - The models, addresses, keys, and failure modes for `embedding`, `reranker`, and `llm` links are different. Configuring them separately makes them easier to locate and replace.
> - The repository already supports independent configuration: `RETRIEVAL_EMBEDDING_*`, `RETRIEVAL_RERANKER_*`, and `WRITE_GUARD_LLM_* / COMPACT_GIST_LLM_*` can all work independently.
> - The primary value of a `router` is on the production side: unified entry point, model orchestration, authentication, rate limiting, auditing, and subsequent provider switching. It is suitable as the **default template standard**, but it is not the only supported method.
>
> **Configuration Priority (to avoid misconfiguration)**:
> - `RETRIEVAL_EMBEDDING_BACKEND` only affects the Embedding link, not the Reranker.
> - There is no `RETRIEVAL_RERANKER_BACKEND` switch; whether it is enabled is controlled solely by `RETRIEVAL_RERANKER_ENABLED`.
> - Reranker addresses/keys prioritize `RETRIEVAL_RERANKER_API_BASE/API_KEY`. If missing, they fall back to `ROUTER_API_BASE/ROUTER_API_KEY`, then finally to `OPENAI_BASE_URL/OPENAI_API_BASE` and `OPENAI_API_KEY`.

---

## 3. Detailed Configuration for Each Profile

### Profile A —— Pure Keyword (Minimal)

Zero dependencies, uses keyword matching only:

```bash
# Core Configuration (see deploy/profiles/linux/profile-a.env)
SEARCH_DEFAULT_MODE=keyword
RETRIEVAL_EMBEDDING_BACKEND=none
RETRIEVAL_RERANKER_ENABLED=false
RUNTIME_INDEX_WORKER_ENABLED=false    # No index worker needed
```

### Profile B —— Hybrid Retrieval + Local Hash (Default)

Uses built-in 64-dimensional hash vectors to provide basic semantic capabilities:

```bash
# Core Configuration (see deploy/profiles/linux/profile-b.env)
SEARCH_DEFAULT_MODE=hybrid
RETRIEVAL_EMBEDDING_BACKEND=hash
RETRIEVAL_EMBEDDING_MODEL=hash-v1
RETRIEVAL_EMBEDDING_DIM=64
RETRIEVAL_RERANKER_ENABLED=false
RUNTIME_INDEX_WORKER_ENABLED=true     # Enable asynchronous indexing
RUNTIME_INDEX_DEFER_ON_WRITE=true
```

### Profile C/D —— Hybrid Retrieval + Real Models (Deep Retrieval Profiles)

Profiles C and D use the same algorithm path, both calling OpenAI-compatible APIs via a `router`; in the default template, D has a higher reranker weight (`0.35`).

> **The Bottom Line**:
> - **Profile B**: Default start, ensures you can get up and running today.
> - **Profile C**: Deep-retrieval profile once model services are ready.
> - **Profile D**: Quality-first remote API profile.
>
> **Minimum requirements before upgrading to Profile C**:
> - Embedding: `RETRIEVAL_EMBEDDING_*`
> - Reranker: `RETRIEVAL_RERANKER_*`
> - If you also want to enable LLM-assisted write guard / gist / intent routing: Fill in `WRITE_GUARD_LLM_*`, `COMPACT_GIST_LLM_*`, and optionally `INTENT_LLM_*`.
>
> **If you are only doing a retrieval smoke test right now**:
> - **Profile C**: first make the embedding path work; the shipped `profile-c` template still enables the Reranker by default
> - **Profile D**: keep the same Embedding + Reranker retrieval chain, but point it at remote endpoints with a higher default reranker weight
> - `WRITE_GUARD_LLM_*`, `COMPACT_GIST_LLM_*`, and `INTENT_LLM_*` are not hard prerequisites for a retrieval smoke test
>
> The repository's real-profile helper and the “minimum prep” wording are only emphasizing that Embedding is the first new dependency when you move into deeper retrieval tiers; that does **not** mean the shipped `profile-c` template disables the Reranker. The helper at `backend/tests/benchmark/helpers/profile_abcd_real_runner.py` currently uses a benchmark-only split: `profile_c = API embedding without reranker`, `profile_d = API embedding + reranker`. With the current templates, `Profile C` is still the local/private API path with the Reranker enabled by default, while `Profile D` keeps the same retrieval chain but points it at remote APIs with a higher default reranker weight. A local small-sample smoke run was rechecked against those real templates as well. This is not proof that one batch of old vectors can be smart-switched across profiles.
>
> **One more thing to keep explicit**: Profile B defaults to 64-d hash vectors, while Profile C/D depend on the external embedding dimension you really configure. As soon as backend / model / dim changes, treat "old vectors may need reindex" as a prerequisite, not as an afterthought.

**Profile C** (Local Model Services) —— Suitable for those with a GPU or using local inference like Ollama/vLLM:

```bash
# Core Configuration (see deploy/profiles/linux/profile-c.env)
SEARCH_DEFAULT_MODE=hybrid
RETRIEVAL_EMBEDDING_BACKEND=router

# Embedding Configuration
ROUTER_API_BASE=http://127.0.0.1:PORT/v1          # ← Replace PORT with actual port
ROUTER_API_KEY=replace-with-your-key
ROUTER_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_EMBEDDING_API_BASE=http://127.0.0.1:PORT/v1
RETRIEVAL_EMBEDDING_API_KEY=replace-with-your-key
RETRIEVAL_EMBEDDING_DIM=<provider-vector-dim>

# Reranker Configuration
RETRIEVAL_RERANKER_ENABLED=true
RETRIEVAL_RERANKER_API_BASE=http://127.0.0.1:PORT/v1
RETRIEVAL_RERANKER_API_KEY=replace-with-your-key
RETRIEVAL_RERANKER_MODEL=your-reranker-model-id
RETRIEVAL_RERANKER_WEIGHT=0.30                     # Recommended 0.20 ~ 0.40
```

If you do not use a unified `router`, you can also directly configure OpenAI-compatible embedding / reranker services:

```bash
# Connect directly to OpenAI-compatible services
RETRIEVAL_EMBEDDING_BACKEND=api
RETRIEVAL_RERANKER_ENABLED=true
RETRIEVAL_RERANKER_API_BASE=http://127.0.0.1:PORT/v1
RETRIEVAL_RERANKER_API_KEY=replace-with-your-key
# Fill in the following two items according to your actual model names
RETRIEVAL_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_RERANKER_MODEL=your-reranker-model-id
# Note: There is no RETRIEVAL_RERANKER_BACKEND configuration item
```

> If you use the direct API path, keep `RETRIEVAL_EMBEDDING_DIM` aligned with the vector dimension your provider actually returns. The current code still does not try to guess this value for you; it only forwards that value as `dimensions` on OpenAI-compatible `/embeddings` requests. If the provider explicitly rejects `dimensions`, the runtime retries once without that field. If the final response still comes back with the wrong vector size, the runtime now rejects that vector immediately and falls back / degrades instead of silently writing an incompatible index entry. The same "service base/root" rule also applies to `RETRIEVAL_EMBEDDING_API_BASE`, `RETRIEVAL_RERANKER_API_BASE`, and `WRITE_GUARD_LLM_API_BASE`: common endpoint suffixes are normalized automatically, while malformed or link-local values still fail closed. Loopback IP literals stay allowed by default, and `localhost` stays allowed too; if you intentionally point a provider base at another private IP literal, add it or its CIDR to `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS`.
>
> If you are using a local OpenAI-compatible path such as Ollama, prefer `/v1/embeddings` and only set `RETRIEVAL_EMBEDDING_DIM` to the real vector size that provider returns. Do not blindly copy someone else's `1024` or `4096` example.
>
> If an older index was written with another dimension and you then switch `.env` to this direct API configuration, the current runtime does not auto-migrate those old vectors. The safer order is: back up first, run `index_status()`, and if the runtime reports a dimension mismatch, run `rebuild_index(wait=true)` or move to a fresh database.

**Profile D** (Remote API Services) —— No local GPU required, uses cloud models:

```bash
# Main difference from C: API address points to remote, default reranker weight is higher
ROUTER_API_BASE=https://router.example.com/v1
RETRIEVAL_EMBEDDING_API_BASE=https://router.example.com/v1
RETRIEVAL_RERANKER_API_BASE=https://router.example.com/v1
RETRIEVAL_RERANKER_WEIGHT=0.35                     # Remote recommended slightly higher
```

> **🔑 Primary Tuning Parameter for C/D**: `RETRIEVAL_RERANKER_WEIGHT`, suggested range `0.20 ~ 0.40`, fine-tune in `0.05` increments.
>
> **One wording distinction**: the `0.30 / 0.35` values here are still the explicit defaults in the shipped `Profile C/D` templates. The generic runtime fallback in `.env.example` is now `0.40`; they are not the same layer.
>
> **Model ID Reminder**: The `your-embedding-model-id` / `your-reranker-model-id` values above are shell-safe placeholder examples. The project is not bound to any specific model family; please fill in your own provider's actual model ID.
> If you use `profile c/d`, whether you stop at `apply_profile.sh/.ps1` or continue into `docker_one_click.sh/.ps1`, those placeholder model IDs / endpoints / keys are all treated as unresolved configuration. The script stops early instead of waiting for the container startup path to fail later.
> A real local/private router endpoint such as `http://127.0.0.1:8001/v1` is **not** treated as a placeholder. The values that still block save/startup are the documented examples such as `https://router.example.com/v1`, `router-embedding-model`, `router-reranker-model`, `your-embedding-model-id`, and `your-reranker-model-id`.

If you adopt the direct connection method, note one boundary first:

- `docker_one_click.sh/.ps1` does **not** directly read your manually edited repository `.env` as the final Docker configuration.
- On each run, it first generates a Docker env file from `deploy/profiles/docker/profile-*.env`, and only then decides whether to inject runtime overrides based on the script arguments.
- So if you only write your final direct-API settings into the repository-root `.env` and then run `bash scripts/docker_one_click.sh --profile c`, the actual startup still uses the profile template path, not necessarily the final values you just wrote.

> As rechecked in the current validation, the local `profile c/d + --allow-runtime-env-injection` path now follows the intended order: generate the Docker env from the template first, defer template placeholder validation for that run, write the injected runtime values, and then still fail closed if the required external settings remain unresolved. In plain language: template placeholders no longer block local debugging before your real values land, but missing injected values are still treated as a hard stop.
>
> On the native Windows PowerShell path, later env rewrites in `docker_one_click.ps1` now also keep that generated Docker env file in UTF-8 without BOM, so the same file can continue to be handed to Docker Compose without a PowerShell 5.1 encoding mismatch.
>
> One more boundary to keep explicit after this rerun: on the one-click `profile c/d + --allow-runtime-env-injection` path, loopback provider bases from your current shell (`127.0.0.1` / `localhost` / `::1`) are now rewritten to `host.docker.internal` inside the generated Docker env, so host-side local router / chat services stay reachable from the container. That rewritten host is also appended to `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` for this run because the backend still validates provider bases under the private-address rules. Other private IP literals are kept as-is and only append their exact host instead of widening the trust range. The script does not append unresolved `host:PORT` placeholder strings as trusted hosts. If you bypass the one-click path and prepare the Docker env yourself, you still need to write the container-reachable address explicitly.

The minimum verification path should therefore be split into two cases:

```bash
# Option A: local debugging via the one-click script (explicit injection)
# Use this when your current shell already has the embedding / reranker / LLM API base, key, and model values prepared.
bash scripts/docker_one_click.sh --profile c --allow-runtime-env-injection
```

```bash
# Option B: verify the final Docker env file you actually plan to deploy
# In this case, explicitly point compose to that file instead of assuming the one-click script will read the repository .env
MEMORY_PALACE_DOCKER_ENV_FILE=/absolute/path/to/your-docker.env docker compose up -d --build
```

Then verify the basic interfaces:

```bash
curl -fsS http://127.0.0.1:18000/health
curl -fsS http://127.0.0.1:18000/browse/node -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>"
```

Here, `<YOUR_MCP_API_KEY>` means:

- local manual startup: the `MCP_API_KEY` in your repository `.env`
- Docker / GHCR startup: the `MCP_API_KEY` in the Docker env file for that run (for example `.env.docker`)

Decision Criteria:

1.  Please only compare and accept results from the **same final deployment configuration**. Do not mix results from different paths.
2.  For `docker_one_click`, `--allow-runtime-env-injection` is a **local debugging path**, not a promise that the script is consuming the repository `.env` as the final Docker config.
3.  If you want to validate the exact direct-API Docker configuration you plan to deploy, start from that final Docker env file and then run the startup + health checks against that same file.
4.  If startup fails under placeholder endpoints/keys/model IDs, it is an expected fail-closed; please replace them with real, available values and re-verify.

### Model ID Examples

It is recommended that you fill these in based on "Purpose -> Real model ID":

| Purpose | Suggested Writing | Description |
|---|---|---|
| Embedding | `your-embedding-model-id` | Fill in your provider's actual embedding model ID |
| Reranker | `your-reranker-model-id` | Fill in your provider's actual reranker model ID |
| Optional LLM | `your-chat-model-id` | Used for `write_guard` / `compact_context` / `intent` |

Whether you go through a `router` or a direct API, the project simply passes these strings as-is to your OpenAI-compatible service; it does not enforce any specific model brand or family.

---

## 4. Optional LLM Parameters (write_guard / compact_context / intent)

These parameters control three optional LLM features: **Write Guard** (quality filtering), **Context Compaction** (summary generation), and **Intent enhancement** (experimental classification support).

Configure these in `.env`:

```bash
# Write Guard LLM (Filters low-quality memories)
WRITE_GUARD_LLM_ENABLED=false
WRITE_GUARD_LLM_API_BASE=             # OpenAI-compatible /chat/completions endpoint
WRITE_GUARD_LLM_API_KEY=
WRITE_GUARD_LLM_MODEL=your-chat-model-id

# Compact Context Gist LLM (Generates summaries)
COMPACT_GIST_LLM_ENABLED=false
COMPACT_GIST_LLM_API_BASE=
COMPACT_GIST_LLM_API_KEY=
COMPACT_GIST_LLM_MODEL=your-chat-model-id

# Intent LLM (Experimental intent classification enhancement)
INTENT_LLM_ENABLED=false
INTENT_LLM_API_BASE=
INTENT_LLM_API_KEY=
INTENT_LLM_MODEL=your-chat-model-id
```

> **Fallback Mechanism**: When `COMPACT_GIST_LLM_*` is not configured, `compact_context` will automatically fall back to using the `WRITE_GUARD_LLM_*` configuration. Both links use the OpenAI-compatible chat interface (`/chat/completions`).
>
> **Note**: The model IDs here are only placeholders. As long as your service is compatible with OpenAI-style `/embeddings`, `/chat/completions`, or reranker endpoints, you can change them to your own actual model IDs.
>
> If your provider uses a different model ID naming convention, please keep within the same model family and change it to your provider's actual model ID.
>
> **Additional Note**: `INTENT_LLM_*` is an experimental capability. When disabled or unavailable, it will fall back to keyword rules directly without affecting the default retrieval path.
>
> **Complete Advanced Configuration**: `CORS_ALLOW_*`, `RETRIEVAL_MMR_*`, `INDEX_LITE_ENABLED`, `AUDIT_VERBOSE`, runtime observation/sleep consolidation limits, etc., are not covered in detail in this section. Please refer to `.env.example` for the full list.
>
> **Enabling Suggestions (Recommended to follow these)**:
> - `INTENT_LLM_ENABLED=false`
>   - Suitable for default production / default user deployments.
>   - Only try this if you have a stable chat model and want to enhance intent classification for fuzzy queries.
> - `RETRIEVAL_MMR_ENABLED=false`
>   - Keep disabled by default.
>   - Open only if the redundancy in the top hybrid retrieval results is noticeably high.
> - `CORS_ALLOW_ORIGINS=`
>   - Leave blank for local development to use the built-in local allowlist.
>   - For production browser access, please explicitly list allowed domains; using `*` is not recommended.
> - `RETRIEVAL_SQLITE_VEC_ENABLED=false`
>   - Currently remains a rollout switch.
>   - Not recommended for standard user deployments; enable only during maintenance to verify extension paths, readiness, and fallback links.

---

## 5. Docker One-Click Deployment (Recommended)

### 5.0 GHCR Prebuilt Images (Recommended for End Users with Local Build Problems)

If your main problem is "local image build keeps failing," prefer the GHCR path first:

```bash
cd <project-root>
cp .env.example .env.docker
bash scripts/apply_profile.sh docker b .env.docker

docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

```powershell
cd <project-root>
Copy-Item .env.example .env.docker
.\scripts\apply_profile.ps1 -Platform docker -Profile b -Target .env.docker

docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

This path is for **running the service quickly**:

- It avoids local image build.
- It still assumes you have a checkout of this repository, because the compose file and profile helpers live here.
- It covers `Dashboard / API / SSE`.
- It does **not** automatically install local `skills / MCP / IDE host` entries.
- If you want the current repo's repo-local skill + MCP installation path, continue with `docs/skills/GETTING_STARTED_EN.md`.
- If you only want MCP without repo-local install automation, configure an SSE-capable client manually against `http://localhost:3000/sse`. For this GHCR path, `<YOUR_MCP_API_KEY>` normally means the `MCP_API_KEY` written into the `.env.docker` file you just generated.
- Unlike `docker_one_click.sh/.ps1`, this path does **not** auto-adjust ports. Set `MEMORY_PALACE_FRONTEND_PORT` / `MEMORY_PALACE_BACKEND_PORT` explicitly if the defaults are occupied.
- If a containerized C / D setup still needs to reach a **model service running on your host machine**, do not use `127.0.0.1` as the host-side address from inside the container. From the container's point of view, `127.0.0.1` loops back to the container itself, not your host. Prefer `host.docker.internal` (or your actual reachable host address). The compose files now add `host.docker.internal:host-gateway`, so this also works on modern Linux Docker.
- Do **not** assume the repo-local stdio wrapper shares container data automatically. `scripts/run_memory_palace_mcp_stdio.sh` needs a host-side local repository `.env` and the local `backend/.venv`; it does not reuse container data from `/app/data`.
- If you later switch back to a local `stdio` client, your local `.env` must contain a host-accessible absolute path. If `.env` is missing while `.env.docker` exists, or if `.env` / an explicit `DATABASE_URL` still points to `/app/...` or `/data/...`, the wrapper refuses to start and tells you to use a host path or Docker `/sse` instead.

The rest of this section describes the **local build / maintainer path** using `docker_one_click.sh/.ps1`.

### Prerequisites

*   [Docker](https://docs.docker.com/get-docker/) installed and Docker Engine running.
*   Supports `docker compose` (included by default in Docker Desktop).

### macOS / Linux

```bash
cd <project-root>
bash scripts/docker_one_click.sh --profile b
# To inject the current shell's API address/key/model into this Docker env file (disabled by default):
bash scripts/docker_one_click.sh --profile c --allow-runtime-env-injection
```

### Windows PowerShell

```powershell
cd <project-root>
.\scripts\docker_one_click.ps1 -Profile b
# To inject the current PowerShell process environment into this Docker env file (disabled by default):
.\scripts\docker_one_click.ps1 -Profile c -AllowRuntimeEnvInjection
```

> `apply_profile.ps1` now performs a unified deduplication of **all duplicate env keys**, keeping the last value, instead of just handling `DATABASE_URL`.
>
> If you are running `apply_profile.ps1` from PowerShell on Linux / WSL, `-Platform linux` is now accepted too; it uses a dedicated local Linux template. On native Windows, keep using `-Platform windows`.
>
> If the current machine does not have `pwsh` installed but does have Docker, you can run `bash scripts/smoke_apply_profile_ps1_in_docker.sh` for a repo-local `apply_profile.ps1` smoke run.
>
> For native Windows / `pwsh`, it is still recommended to run it separately in the target environment; these steps are for deployment verification and are not intended for beginner-level reading.
>
> `docker_one_click.sh/.ps1` will generate an independent temporary Docker env file for each run by default and pass it to `docker compose` via `MEMORY_PALACE_DOCKER_ENV_FILE`. It will only reuse a specified path if that environment variable is explicitly set, rather than always sharing `.env.docker`.
>
> On the macOS / Linux shell path, if you explicitly point `MEMORY_PALACE_DOCKER_ENV_FILE` at your own custom file, `docker_one_click.sh` now updates that file through temp files created in the same directory, so replacing it is less likely to degrade into a cross-filesystem copy when the file lives outside the default temp area. That final commit now also gets a small bounded retry, so a short transient lock on the custom env file is less likely to abort the whole update.
>
> If the `MCP_API_KEY` in this Docker env file is empty, `apply_profile.sh/.ps1` will automatically generate a local key for both the Dashboard proxy and SSE.
>
> The current compose first waits for the `backend` `/health` check to pass, and the one-click script then adds one extra frontend-proxied `/sse` reachability check before the frontend is considered ready. If you see the container has just started but the browser isn't connecting, wait a few seconds first; do not immediately judge it as a deployment failure.
>
> On the macOS / Linux shell path, `docker_one_click.sh` now also gives transient `docker compose up` failures a small bounded retry with backoff before surfacing a hard error. In plain language: short-lived pull / daemon / startup hiccups get another chance, but repeated or clearly non-retryable failures still stop the run and print the last real error.
>
> Concurrent one-click deployments under the same checkout will be serialized by a deployment lock to prevent shared compose projects/env files from overwriting each other.
>
> WAL safety boundary: the repository defaults only treat **named volume + WAL** as a supported Docker path. If you replace backend `/app/data` with a bind mount on NFS/CIFS/SMB or another network filesystem, explicitly switch back to `MEMORY_PALACE_DOCKER_WAL_ENABLED=false` and `MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete`. `docker_one_click.sh/.ps1` now performs that preflight before `docker compose up` and aborts on the risky combination; if you bypass the one-click script and run `docker compose up` manually, you need to enforce the same rule yourself.
>
> If you enable `--allow-runtime-env-injection` for `profile c/d`, the script switches that run to explicit API mode and additionally forces `RETRIEVAL_EMBEDDING_BACKEND=api`. The current injection path also carries:
>
> - explicit `RETRIEVAL_EMBEDDING_*`
> - explicit `RETRIEVAL_RERANKER_ENABLED` / `RETRIEVAL_RERANKER_*`
> - optional `WRITE_GUARD_LLM_*`, `COMPACT_GIST_LLM_*`, and `INTENT_LLM_*`
>
> When `RETRIEVAL_EMBEDDING_API_*` / `RETRIEVAL_RERANKER_API_*` are not explicitly provided, it prioritizes `ROUTER_API_BASE/ROUTER_API_KEY` from the current process as the fallback source for embedding / reranker API base+key. When `RETRIEVAL_RERANKER_MODEL` is not explicitly provided, it also falls back to `ROUTER_RERANKER_MODEL`.
>
> Current validation snapshot (2026-05-15): Docker/Linux `Profile B/C/D` were rerun. `Profile B` used the project's existing settings; backend/frontend health passed, `/sse` returned an endpoint event, and browser smoke on the Memory / Observability / Maintenance pages had no console errors. The same pass verified the protected frontend proxy routes for `/api/layering/*`, `/api/forgetting/*`, and `/api/search/quality-metrics`. `Profile C/D` used explicit runtime injection with a 1024-dimension external embedding / reranker setup; the generated container env rewrote the host-side loopback chat base to `host.docker.internal` and added that host to the run allowlist. Create/search/delete smoke passed for both profiles, search returned `degrade_reasons=None`, and SSE plus browser smoke passed. This pass did not recalculate the native Windows / native Linux host-runtime benchmark tables.
>
> The local build path now also uses checkout-scoped stable image names. The practical effect is simple: once this checkout has completed one successful build, `--no-build` can keep reusing those local images even if you change `COMPOSE_PROJECT_NAME`; you only need to build again on the first run or after deleting the local images.

### Access Addresses After Deployment

| Service | Host Default Port | Container Internal Port | Access Method |
|---|:---:|:---:|---|
| Frontend (Web UI) | `3000` | `8080` | `http://localhost:3000` |
| Backend (API) | `18000` | `8000` | `http://localhost:18000` |
| SSE (Frontend Proxy) | `3000` | `8080 -> 8000` | `http://localhost:3000/sse` |
| Health Check | `18000` | `8000` | `http://localhost:18000/health` |

### What the One-Click Script Does

1.  Calls the profile script to generate the Docker env file for this run from the template (per-run temporary file by default; reuses the specified path only if `MEMORY_PALACE_DOCKER_ENV_FILE` is explicitly set).
2.  Disables runtime environment injection by default to avoid implicit template overwriting; parameters are only overridden when injection is explicitly enabled. For `profile c/d`, the injection mode additionally forces `RETRIEVAL_EMBEDDING_BACKEND=api` for local debugging; if explicit `RETRIEVAL_*` is not provided, it prioritizes reusing `ROUTER_API_BASE/ROUTER_API_KEY` as a fallback for the embedding / reranker API base+key, while also passing through explicit retrieval parameters such as `RETRIEVAL_EMBEDDING_DIM` and the optional `INTENT_LLM_*`. On that same one-click path, loopback router / chat-style API bases from the current shell are now rewritten to `host.docker.internal` in the generated Docker env, and that host is appended to the run allowlist; non-loopback private provider literals keep their original value and only append their exact host to `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` for that generated env.
3.  Automatically detects port conflicts; if the default port is occupied, it automatically increments to find an idle port.
4.  Detects and injects Docker persistent volumes: by default they are isolated per compose project (`<compose-project>_data` for the database and `<compose-project>_snapshots` for Review snapshots); old volumes are reused only when `MEMORY_PALACE_DATA_VOLUME` / `MEMORY_PALACE_SNAPSHOTS_VOLUME` is explicitly set.
5.  Fails fast before startup if backend `/app/data` has been changed to a bind mount on NFS/CIFS/SMB or another network filesystem while WAL would still be enabled.
6.  Adds a deployment lock to concurrent deployments under the same checkout to prevent multiple `docker_one_click` instances from overwriting each other.
7.  On the macOS / Linux shell path, retries transient `docker compose up` failures a few times with short backoff before giving up.
8.  Uses `docker compose` to build and start the backend plus frontend containers; SSE is served by the backend and exposed through the frontend proxy in the default topology.

### Security Notes

*   **Backend Container**: Runs as a non-root user (`UID=10001`, see `deploy/docker/Dockerfile.backend`).
*   **Frontend Container**: Uses the `nginxinc/nginx-unprivileged` image (default `UID=101`).
*   Docker Compose is configured with `security_opt: no-new-privileges:true`.

### Stopping Services

```bash
cd <project-root>
COMPOSE_PROJECT_NAME=<printed-compose-project-name> docker compose -f docker-compose.yml down --remove-orphans
```

> The `down --remove-orphans` command above will not delete the data/snapshots volumes for the current compose project; the database and Review snapshots are cleared only when you explicitly execute `down -v` or manually delete those volumes.

---

## 6. Manual Startup

If you are not using Docker, you can start the backend and frontend manually.

### Step 1: Generate `.env` Configuration

```bash
# macOS / Linux (Generates Profile B configuration by default; Linux also uses the `macos` template value)
cd <project-root>
bash scripts/apply_profile.sh macos b

# If your embedding / reranker model services are ready, switch to Profile C
# bash scripts/apply_profile.sh macos c

# Windows PowerShell
.\scripts\apply_profile.ps1 -Platform windows -Profile b

# If model services are ready, switch to Profile C
# .\scripts\apply_profile.ps1 -Platform windows -Profile c
```

> Script Logic: Copies `.env.example` to the generated env file, then appends the override parameters from `deploy/profiles/<platform>/profile-<x>.env`. For local platforms, the default target remains `.env`; if you run the `docker` variant without an explicit target, the default target is now `.env.docker`. On the shell path, `apply_profile.sh` also rewrites the common local `DATABASE_URL` placeholder for the current checkout, including `/Users/...` and `/home/...`. On macOS / Linux, `apply_profile.sh` now also creates a `*.bak` backup before overwriting an existing target file; if another `apply_profile.sh` process is already writing the same target file, the later one exits early and asks you to retry instead of letting the two runs overwrite each other. Its staged/update temp files are also created next to the target file, reducing cross-filesystem replace surprises. Those adjacent temp-file commits now also get a small bounded retry, so a short-lived file lock or indexer touch is less likely to abort the rewrite midway.
>
> Native Windows PowerShell now follows the same guardrails on its own path. `apply_profile.ps1` also creates a `*.bak` backup before overwrite, rejects a second `apply_profile.ps1` writer for the same target file, and writes the staged temp file next to the target file instead of assuming a shared temp directory. The final replace/move step now also gets a small bounded retry for the common transient Windows lock case. If you only want to preview the final result first, use `bash scripts/apply_profile.sh --dry-run ...` on macOS / Linux, or `.\scripts\apply_profile.ps1 -Platform windows -Profile b -DryRun` on PowerShell. Both preview paths print the final env content without modifying the target file.
>
> `apply_profile.sh/.ps1` currently deduplicates env keys after generation to prevent inconsistent behavior across different parsers for keys that appear multiple times.
>
> Treat `deploy/profiles/*/*.env` as **Profile template inputs**, not as final `.env` files to copy by hand. For example, the local shell templates intentionally keep a placeholder `DATABASE_URL` first, then let `apply_profile.*` rewrite it for the current checkout. If the generated result still leaves placeholder segments such as `<...>` or `__REPLACE_ME__` inside `DATABASE_URL`, the script/backend now fail closed instead of continuing with a broken sqlite path. In particular, do not copy Docker template values like `sqlite+aiosqlite:////app/data/...`, or any `/data/...`-style container-only sqlite path, into a local `.env`; that is a container path, and the repo-local stdio wrapper treats it as a misconfiguration and refuses to start.
>
> If you are just running the repository manually for the first time, Profile B is the safest start; switch to Profile C only when the embedding / reranker links are available.

### Step 2: Start the Backend

```bash
cd <project-root>/backend
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# If you also plan to run backend tests afterwards
# pip install -r requirements-dev.txt
uvicorn main:app --host 127.0.0.1 --port 18000
```

### Step 3: Start the Frontend

```bash
cd <project-root>/frontend
npm install
MEMORY_PALACE_API_PROXY_TARGET=http://127.0.0.1:18000 npm run dev -- --host 127.0.0.1 --port 3000
```

If you also want the local Vite entry to proxy same-origin SSE, add:

```bash
MEMORY_PALACE_SSE_PROXY_TARGET=http://127.0.0.1:8010

That `/sse` proxy is intentionally kept as the local development path for same-origin SSE / MCP debugging; the frontend now has a shared `frontend/src/lib/sse.js` helper for that path. Without browser-side auth it still behaves like the lightweight native `EventSource` path; with browser-side auth it switches to fetch-based SSE so the client can send auth headers and reconnect after a non-terminal stream drop. If the browser's Dashboard auth changes at runtime, the next non-terminal reconnect re-reads that current auth state instead of reusing the initial header/bearer snapshot.
```

This also forwards `/sse`, `/messages`, and `/sse/messages` to your separately started local `run_sse.py` process, specifically for local Vite-entry debugging.

---

## 7. Local Inference Service Reference

If using Profile C, you need to run embedding/reranker models locally. Below are common local inference services:

| Service | Official Documentation | Hardware Recommendations |
|---|---|---|
| Ollama | [docs.ollama.com](https://docs.ollama.com/gpu) | Can run on CPU; GPU recommended based on model size for VRAM |
| LM Studio | [lmstudio.ai](https://lmstudio.ai/docs/app/system-requirements) | 16GB+ RAM recommended |
| vLLM | [docs.vllm.ai](https://docs.vllm.ai/en/stable/getting_started/installation/gpu.html) | Linux-first; NVIDIA compute capability 7.0+ |
| SGLang | [docs.sglang.ai](https://docs.sglang.ai/index.html) | Supports NVIDIA / AMD / CPU / TPU |

**OpenAI-compatible Interface Documentation**:

*   Ollama: [OpenAI Compatibility](https://docs.ollama.com/api/openai-compatibility)
*   LM Studio: [OpenAI Endpoints](https://lmstudio.ai/docs/app/api/endpoints/openai)

> **Important**: Memory Palace embedding/reranker calls are made via the OpenAI-compatible API. If you enable the reranker (enabled by default in C/D), the backend service needs an available rerank endpoint in addition to `/v1/embeddings` (calls `/rerank` by default).

---

## 8. Vitality Parameters

The Vitality system is used for automatic memory lifecycle management: **Access Reinforcement → Natural Decay → Cleanup Candidate → Manual Confirmation**.

| Parameter | Default Value | Description |
|---|:---:|---|
| `VITALITY_MAX_SCORE` | `3.0` | Maximum vitality score |
| `VITALITY_REINFORCE_DELTA` | `0.08` | Score increase per retrieval hit |
| `VITALITY_DECAY_HALF_LIFE_DAYS` | `30` | Decay half-life (days); vitality halves after 30 days |
| `VITALITY_DECAY_MIN_SCORE` | `0.05` | Decay floor; will not drop below this value |
| `VITALITY_CLEANUP_THRESHOLD` | `0.35` | Memories below this value are listed as cleanup candidates |
| `VITALITY_CLEANUP_INACTIVE_DAYS` | `14` | Inactivity threshold, used with vitality score to determine candidates |
| `RUNTIME_VITALITY_DECAY_CHECK_INTERVAL_SECONDS` | `600` | Decay check interval (seconds); default 10 minutes |
| `RUNTIME_CLEANUP_REVIEW_TTL_SECONDS` | `900` | Cleanup confirmation window (seconds); default 15 minutes |
| `RUNTIME_CLEANUP_REVIEW_MAX_PENDING` | `64` | Maximum pending cleanup confirmations |

**Tuning Suggestions**:

1.  Keep default values first and observe for 1-2 weeks before adjusting.
2.  If there are too many cleanup candidates → increase `VITALITY_CLEANUP_THRESHOLD` or `VITALITY_CLEANUP_INACTIVE_DAYS`.
3.  If the confirmation window is too short → increase `RUNTIME_CLEANUP_REVIEW_TTL_SECONDS`.

---

## 9. API Authentication

The following interfaces are protected by `MCP_API_KEY` (**fail-closed**: returns `401` if the key is not configured):

*   `GET/POST/DELETE /maintenance/*`
*   `GET/POST/PUT/DELETE /browse/*` and `GET/POST/DELETE /review/*`
*   SSE interfaces (`/sse` and `/messages`; standalone local debugging can start them from `run_sse.py`, while the default Docker path serves them from inside the `backend` process)

### Header Format (Choose one)

```
X-MCP-API-Key: <YOUR_MCP_API_KEY>
Authorization: Bearer <YOUR_MCP_API_KEY>
```

`<YOUR_MCP_API_KEY>` always means the actual `MCP_API_KEY` value from the env file used by that runtime:

- local manual startup -> repository `.env`
- Docker / GHCR startup -> the Docker env file for that run (for example `.env.docker`)

### Local Debugging Override

Setting `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` allows skipping authentication during local debugging:

*   Only takes effect for loopback requests (`127.0.0.1` / `::1` / `localhost`).
*   Non-loopback requests still return `401` (with `reason=insecure_local_override_requires_loopback`).

> **MCP stdio mode** does not go through the HTTP/SSE authentication middleware and is therefore not subject to this restriction.

### Frontend Access to Protected Interfaces

When **manually starting frontend and backend locally**, if you are just debugging locally, you can inject the API Key at runtime (not recommended in build variables):

```html
<script>
  window.__MEMORY_PALACE_RUNTIME__ = {
    maintenanceApiKey: "<MCP_API_KEY>",
    maintenanceApiKeyMode: "header"   // or "bearer"
  };
</script>
```

> Do not put real `MCP_API_KEY` in public pages, shared static resources, or HTML files delivered to end users. The browser can read this global object directly. For deployments intended for others, a server-side proxy is recommended over exposing the key in frontend pages.
>
> Also compatible with the old field name: `window.__MCP_RUNTIME_CONFIG__`

When using **Docker one-click deployment**, you don't need to write the key into the browser page:

*   The frontend container automatically includes the same `MCP_API_KEY` for protected Dashboard API routes, `/sse`, and `/messages` at the proxy layer; it does not attach that key to every generic `/api/*` path.
*   This key is saved in the Docker env file used for this run by default.
*   The browser only sees the proxied results and does not directly receive the real key.
*   Treat that frontend port as a trusted admin/operator surface. If you expose `3000` beyond a trusted network, add your own VPN, reverse-proxy auth, or network ACL in front of it.
*   If you really need a split-origin admin deployment, you can additionally set `FRONTEND_CSP_CONNECT_SRC` in the Docker env file; when left empty, the frontend keeps the more conservative default `connect-src 'self'`.
*   If you deploy on a shared host and do not want to hard-code limits into the default compose file, copy `docker-compose.override.example.yml` to `docker-compose.override.yml` and tune the resource values for that machine.

### SSE Startup Example

```bash
HOST=127.0.0.1 PORT=8010 python run_sse.py
```

> `python run_sse.py` prefers loopback (`HOST=127.0.0.1`, `PORT=8000`) and automatically falls back to `127.0.0.1:8010` when local `8000` is already occupied by the main backend, so `HOST=127.0.0.1` here is still the normal local debugging shape. If you bind `HOST=localhost`, the probe now treats `127.0.0.1` as the required loopback candidate and `::1` as best-effort, so a host without IPv6 loopback support no longer gets pushed to `8010` just because `::1` is unavailable. When fallback really does happen, the startup log also prints the final `/sse` URL and tells you to update the client config or set `PORT` explicitly. To allow other machines to access it, change it to `0.0.0.0` (or your actual listening address) and supplement with your own `MCP_API_KEY`, network isolation, reverse proxy, and TLS protection. If your remote hostname / origin should also pass MCP transport-security host/origin checks, add it explicitly through `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS`.
>
> In Docker / Compose, SSE is now served directly by the `backend` process and then reached through the frontend proxy; there is no separate `sse` container in the default topology anymore.

For Docker one-click deployment, access directly at:

```bash
http://localhost:3000/sse
```

---

## 10. Tuning and Troubleshooting

### Common Issues

| Issue | Cause and Solution |
|---|---|
| Poor retrieval results | Confirm if `SEARCH_DEFAULT_MODE` is `hybrid`; for C/D profiles, check if `RETRIEVAL_RERANKER_WEIGHT` is reasonable |
| Model service unavailable | The system will downgrade automatically; check the `degrade_reasons` field in the response to locate the specific cause |
| C/D shows `embedding_request_failed` / `embedding_fallback_hash` | Usually indicates the external embedding/reranker link is unreachable (e.g., local router model not deployed), not a backend crash; see "C/D Downgrade Signal Troubleshooting" below |
| Docker port conflict | One-click script automatically finds idle ports; can also be manually specified (bash: `--frontend-port` / `--backend-port`, PowerShell: `-FrontendPort` / `-BackendPort`) |
| SSE startup fail `address already in use` | Free the port or switch via `PORT=<idle-port>` |
| Database lost after upgrade | The backend automatically restores from historical filenames (`agent_memory.db` / `nocturne_memory.db` / `nocturne.db`) on startup |

### C/D Downgrade Signal Troubleshooting (Local Debugging)

```bash
# First check if the service is actually up
curl -fsS http://127.0.0.1:18000/health
```

1.  If the log or results still contain `embedding_request_failed` / `embedding_fallback_hash`, first check if the embedding/reranker service itself is reachable and if the API key is valid.
2.  Checking the actual calling endpoints directly is more reliable than just looking at the config file:

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

> If your local service does not require an API key, drop the `Authorization` header. If the embedding provider rejects `dimensions`, the runtime retries once without that field, but the final vector size still needs to match `RETRIEVAL_EMBEDDING_DIM`.

3.  If troubleshooting only on the current machine, you can temporarily change to `RETRIEVAL_EMBEDDING_BACKEND=api` and directly configure embedding / reranker / llm; restore the target environment's `router` config and re-verify once before going live.

### PowerShell / Windows Verification Suggestions

*   Both `scripts/apply_profile.sh` and `scripts/apply_profile.ps1` perform unified deduplication of duplicate env keys.
*   If you use Docker for a `pwsh-in-docker` equivalence check, `docker_one_click.ps1` now tries `Get-NetTCPConnection` first for port probing and automatically falls back to `ss` when that Windows cmdlet is unavailable. If the target environment has neither, specify fixed ports explicitly or re-run on the target Windows host.
*   If delivering to a Windows environment, it is recommended to run the startup and smoke tests on the target Windows machine using the same template.
*   The main documentation only keeps steps that are publicly executable; target environment-specific verification suggestions should be recorded separately.

### Tuning Tips

1.  **`RETRIEVAL_RERANKER_WEIGHT`**: Too high an emphasis will over-rely on the reranking model; suggested debugging step is `0.05`.
2.  **Docker Data Persistence**: By default, two compose-project-scoped volumes are used together (`<compose-project>_data` mounted at `/app/data` and `<compose-project>_snapshots` mounted at `/app/snapshots`) to persist the database and review snapshots respectively (see `docker-compose.yml`).
3.  **Legacy Compatibility**: The one-click script automatically identifies legacy `NOCTURNE_*` environment variables and historical data volumes.
4.  **Migration Lock**: `DB_MIGRATION_LOCK_FILE` (default `<db_file>.migrate.lock`) and `DB_MIGRATION_LOCK_TIMEOUT_SEC` (default `10` seconds) are used to prevent concurrent migration conflicts across multiple processes.

---

## 11. Assistant Scripts Overview

| Script | Description |
|---|---|
| `scripts/apply_profile.sh` | Generates the env file from template (`.env` by default for local platforms; `.env.docker` by default for `docker` when target is omitted) |
| `scripts/apply_profile.ps1` | Generates the env file from template (`.env` by default for local platforms; `.env.docker` by default for `docker` when target is omitted) |
| `scripts/docker_one_click.sh` | Docker one-click deployment (macOS / Linux) |
| `scripts/docker_one_click.ps1` | Docker one-click deployment (Windows PowerShell) |

### Configuration Template File Structure

```
deploy/profiles/
├── macos/
│   ├── profile-a.env
│   ├── profile-b.env
│   ├── profile-c.env
│   └── profile-d.env
├── windows/
│   ├── profile-a.env
│   ├── profile-b.env
│   ├── profile-c.env
│   └── profile-d.env
└── docker/
    ├── profile-a.env
    ├── profile-b.env
    ├── profile-c.env
    └── profile-d.env
```
