# Memory Palace Quick Start

This guide helps you set up the Memory Palace local development environment or Docker deployment in 5 minutes.

> **Memory Palace** is a long-term memory system designed for AI Agents. It provides 9 tools via the [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) protocol, enabling persistent memory capabilities for clients such as Claude Code, Codex, Gemini CLI, and OpenCode. If you are integrating an IDE host such as `Cursor / Windsurf / VSCode-host / Antigravity`, start with `docs/skills/IDE_HOSTS_EN.md`.
>
> **If what you are trying to fix right now is the CLI-side skill + MCP installation path, stop following this page** and go directly to `docs/skills/GETTING_STARTED_EN.md`.

---

## 1. Requirements

| Dependency | Minimum Version | Check Command |
|---|---|---|
| Python | `3.10+` | `python --version` |
| Node.js | `20.19+` (or `>=22.12`) | `node --version` |
| npm | `9+` | `npm --version` |
| Docker (Optional) | `20+` | `docker --version` |
| Docker Compose (Optional) | `2.0+` (a recent `docker compose` plugin is recommended when running the repository compose files manually) | `docker compose version` |

> **Tip**: macOS users are recommended to use [Homebrew](https://brew.sh) to install Python and Node.js. Windows users should download installers from official sites or use [Scoop](https://scoop.sh). If your machine exposes Python as `python3` instead of `python`, replace `python` with `python3` in the commands below.
>
> **Compose compatibility boundary**: the repository-shipped `docker-compose.yml` / `docker-compose.ghcr.yml` use nested `${...:-...}` defaults for volume names. If you run those compose files manually, prefer a recent `docker compose` plugin; some older implementations or classic `docker-compose` may fail during parsing. When that happens, prefer `docker_one_click.sh/.ps1`, or pre-set `MEMORY_PALACE_DATA_VOLUME`, `MEMORY_PALACE_SNAPSHOTS_VOLUME`, and `COMPOSE_PROJECT_NAME` before startup.

---

## 2. Repository Structure at a Glance

```
memory-palace/
├── backend/              # FastAPI + SQLite backend
│   ├── main.py           # Application entry (FastAPI instance, /health endpoint)
│   ├── mcp_server.py     # Implementation of 9 MCP tools (FastMCP)
│   ├── runtime_state.py  # Write Lane, Index Worker, session cache
│   ├── run_sse.py        # MCP SSE transport layer (Starlette + API Key auth)
│   ├── mcp_wrapper.py    # MCP wrapper
│   ├── requirements.txt  # Python dependency list
│   ├── requirements-dev.txt # Backend test dependencies
│   ├── db/               # Database Schema, search engine
│   ├── api/              # HTTP routes
│   │   ├── browse.py     # Memory tree browsing (GET /browse/node)
│   │   ├── review.py     # Review interfaces (/review/*)
│   │   ├── maintenance.py# Maintenance interfaces (/maintenance/*)
│   │   └── setup.py      # First-run setup assistant APIs (/setup/*)
├── frontend/             # React + Vite + Tailwind Dashboard
│   ├── package.json      # Version 1.0.1
│   └── vite.config.js    # Dev server port 5173, proxies to backend 8000
├── deploy/               # Docker and Profile configurations
│   ├── docker/           # Dockerfile.backend / Dockerfile.frontend
│   └── profiles/         # macOS / Linux / Windows / Docker profile templates
├── scripts/              # Operation scripts
│   ├── apply_profile.sh  # Profile application script (macOS/Linux)
│   ├── apply_profile.ps1 # Profile application script (Windows)
│   ├── docker_one_click.sh   # Docker one-click deployment (macOS/Linux)
│   ├── docker_one_click.ps1  # Docker one-click deployment (Windows)
├── docs/                 # Project documentation
├── .env.example          # Configuration template (includes all available items)
├── docker-compose.yml    # Compose orchestration file
└── LICENSE               # Open source license
```

---

<p align="center">
  <img src="images/onboarding_flow.png" width="900" alt="Memory Palace Quick Start Flowchart" />
</p>

> 📌 This diagram is only to help you quickly remember the sequence.
>
> The actual commands in the text take precedence:
>
> - Backend defaults to `uvicorn` running at `127.0.0.1:8000`
> - Frontend dev server defaults to `5173`
> - Docker default entries are `http://127.0.0.1:3000` (Dashboard) and `http://127.0.0.1:3000/sse` (SSE)

## 3. Local Development (Recommended First Path)

### Step 1: Prepare Configuration Files

```bash
cp .env.example .env
```

> The file copied here is the **more conservative `.env.example` minimal template**. It is sufficient to complete the local startup, but **does not mean Profile B has been applied**.
>
> If you want to use the default values defined in the repository for Profile B (e.g., local hash Embedding), please prioritize using the Profile scripts below; if you continue to manually modify `.env.example`, that's fine too—just understand it as "supplementing configuration as needed from a minimal template."

> **Important**: After copying, please check `DATABASE_URL` in `.env` and change the path to your actual path. Absolute paths are highly recommended for shared environments or near-production scenarios. For example:
>
> ```
> DATABASE_URL=sqlite+aiosqlite:////absolute/path/to/memory_palace/demo.db
> ```
>
> The slash count is platform-specific: absolute paths on `macOS / Linux` are usually `sqlite+aiosqlite:////...`, while `Windows` drive-letter paths are usually `sqlite+aiosqlite:///C:/...`. If you edit `.env` manually, do not mix these two forms.
>
> Another very common misconfiguration: do not copy the Docker / GHCR value `sqlite+aiosqlite:////app/data/...`, or any other container-only sqlite path such as `/data/...`, into a local `.env`. `/app/...` and `/data/...` are container-internal paths, not the database file on your host machine; the repo-local `stdio` wrapper now refuses this configuration explicitly. For local `stdio`, use a host absolute path instead. If you actually want to reuse the Docker-side data and service, connect to the Docker-exposed `/sse` endpoint instead.

You can also use the Profile script to quickly generate an `.env` with default configurations:

```bash
# macOS / Linux —— Parameters: Platform Profile [Target File]
# Current script accepted template values are macos|linux|windows|docker; `linux` now uses a dedicated local Linux template.
bash scripts/apply_profile.sh macos b

# Windows PowerShell
.\scripts\apply_profile.ps1 -Platform windows -Profile b
```

> `deploy/profiles/*/profile-*.env` files are input templates for the scripts, not the final `.env` files we recommend you copy directly. For the user path, keep using `apply_profile.sh/.ps1`; it is the safer path because it also fills paths automatically and deduplicates repeated keys.

> The `apply_profile` script copies `.env.example` to a generated env file and then appends the override configuration for the corresponding Profile. Local shell runs (`macos` / `linux`) and native Windows still default to `.env`; if you run the `docker` variant without an explicit target, it now defaults to `.env.docker`. On the shell path, `apply_profile.sh` also automatically rewrites the common local `DATABASE_URL` placeholder, including `/Users/...` and `/home/...`. On macOS / Linux, `apply_profile.sh` now also creates a `*.bak` backup before overwriting an existing target file. If another `apply_profile.sh` process is already writing the same target file, the later one exits early and asks you to retry instead of letting the two runs overwrite each other; its staged/update temp files are also created next to the target file, reducing cross-filesystem replace surprises. Those adjacent temp-file commits now also get a small bounded retry, so a short-lived file lock or indexer touch is less likely to abort the rewrite midway.
>
> If you invoke `bash scripts/apply_profile.sh ... <Windows-absolute-target>` from PowerShell / WSL / Git Bash on a native Windows checkout, the shell path now normalizes that target more safely as well; the common separator-mangled form no longer drops a broken filename into the repository root.
>
> Native Windows PowerShell now follows the same operator-facing behavior on its own path. `apply_profile.ps1` also creates a `*.bak` backup before overwrite, rejects a second `apply_profile.ps1` writer for the same target file, writes the staged temp file next to the target file instead of assuming a shared temp directory, and gives the final replace/move step a small bounded retry for the common transient Windows lock case.
>
> `apply_profile.sh/.ps1` currently deduplicates environment keys after generation; however, running it again in the target environment is still recommended for native Windows / native `pwsh`.
>
> If you only want to preview the generated output first, on macOS / Linux you can run `bash scripts/apply_profile.sh --dry-run ...`. That path prints the final env content without writing the target file.
>
> The PowerShell version now exposes the same preview/help path as well, and that preview path stays no-op just like the shell version:
>
> ```powershell
> .\scripts\apply_profile.ps1 -DryRun -Platform windows -Profile b -Target .env.generated
> .\scripts\apply_profile.ps1 -Help
> ```
>
> Local `profile c/d` now also keeps `RUNTIME_AUTO_FLUSH_ENABLED=true` by default, so unless you override it yourself, the generated `.env` keeps the same auto-flush default as A/B.
>
> If you are running `apply_profile.ps1` from PowerShell on Linux / WSL, `-Platform linux` is now accepted as well; it uses a dedicated local Linux template. On native Windows, keep using `-Platform windows`.
>
> In addition, `profile c/d` now fail-closed at the script stage when endpoint/key/model placeholders are still unresolved. If values such as `PORT`, `replace-with-your-key`, or `your-embedding-model-id` are still present, the script stops immediately instead of carrying an obviously broken config into later startup steps.
>
> `DATABASE_URL` now follows the same guard. The common local placeholder path is rewritten automatically for the current checkout; if the generated result still contains placeholder segments such as `<...>` or `__REPLACE_ME__`, the script/backend stop early instead of continuing with a broken sqlite path.
>
> Note: **The profile-b `.env` generated locally for macOS / Windows will not automatically fill in `MCP_API_KEY`**. If you are about to open the Dashboard, or directly call `/browse` / `/review` / `/maintenance`, `/sse`, or `/messages`, please supplement `MCP_API_KEY` yourself, or set `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` for local loopback debugging only. Only the `docker` platform profile script will automatically generate a local key if the key is empty.
>
> In addition, the backend itself now fail-closes when the **active** remote retrieval configuration still contains placeholder values. If you bypass `apply_profile.*`, copy a `profile c/d` template by hand, and leave values such as `host.docker.internal:PORT`, `replace-with-your-key`, `your-embedding-model-id`, or `your-reranker-model-id` in place, startup stops immediately instead of continuing with an obviously invalid embedding / reranker config.
>
> One easy mistake to avoid: do not copy the `DATABASE_URL` from `.env.docker`, or any container-only sqlite path such as `/app/data/...` or `/data/...`, into your local `.env`. Those paths only exist inside the container; relative sqlite values such as `sqlite+aiosqlite:///demo.db` and percent-escaped container forms such as `sqlite+aiosqlite:////%2Fapp%2Fdata/...` are rejected now as well, so local `stdio` MCP on the host still needs a host-accessible absolute path.

#### Key Configuration Items

The following are the most commonly used configuration items in `.env` (for more items, please see the comments in `.env.example`):

| Config Item | Description | Template Example Value |
|---|---|---|
| `DATABASE_URL` | SQLite database path (**Absolute path recommended**) | `sqlite+aiosqlite:////absolute/path/to/memory_palace/demo.db` |
| `SEARCH_DEFAULT_MODE` | Search mode: `keyword` / `semantic` / `hybrid` | `keyword` |
| `RETRIEVAL_EMBEDDING_BACKEND` | Embedding backend: `none` / `hash` / `router` / `api` / `openai` | `none` |
| `RETRIEVAL_EMBEDDING_MODEL` | Embedding model name | `your-embedding-model-id` |
| `RETRIEVAL_EMBEDDING_DIM` | Embedding vector dimension (must match the provider's real output) | `64` (default template value; you must provide the provider's real dimension for remote backends instead of relying on an auto-filled `1024` / `4096`) |
| `RETRIEVAL_RERANKER_ENABLED` | Whether to enable Reranker | `false` |
| `RETRIEVAL_RERANKER_API_BASE` | Reranker API address | Empty |
| `RETRIEVAL_RERANKER_API_KEY` | Reranker API key | Empty |
| `RETRIEVAL_RERANKER_MODEL` | Reranker model name | `your-reranker-model-id` |
| `RETRIEVAL_REMOTE_TIMEOUT_SEC` | Timeout for remote embedding / reranker / LLM requests (seconds) | `8` |
| `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` | Explicit allowlist for trusted private provider IP literals, hostnames, or CIDRs; loopback IPs such as `127.0.0.1` / `::1` plus `localhost` are already allowed by default | Empty |
| `INTENT_LLM_ENABLED` | Experimental intent LLM toggle | `false` |
| `RETRIEVAL_MMR_ENABLED` | Deduplication / diversity re-ranking under hybrid search | `false` |
| `RETRIEVAL_SQLITE_VEC_ENABLED` | sqlite-vec rollout toggle | `false` |
| `MCP_API_KEY` | Authentication key for HTTP/SSE interfaces | Empty (see Auth section below) |
| `MCP_API_KEY_ALLOW_INSECURE_LOCAL` | Allow access without Key during local debugging (only for loopback requests) | `false` |
| `CORS_ALLOW_ORIGINS` | List of allowed origins for cross-domain access (leave empty for local default) | Empty |
| `VALID_DOMAINS` | Allowed writable memory URI domains (`system://` is built-in read-only) | `core,writer,game,notes` |

> Profile B uses local hash Embedding by default and does not enable Reranker; it remains the **default starting profile**.
>
> If you have model services ready and you explicitly want higher-quality deep retrieval, then move to `Profile C/D`: it requires you to fill in the Embedding / Reranker chain in `.env`; if you also want to enable LLM-assisted write guard / gist / intent routing, continue filling in `WRITE_GUARD_LLM_*`, `COMPACT_GIST_LLM_*`, and optional `INTENT_LLM_*`. See [DEPLOYMENT_PROFILES_EN.md](DEPLOYMENT_PROFILES_EN.md) for details.
>
> One important boundary: this is not a seamless hot-switch. B uses local hash vectors by default, while C/D depend on the real embedding dimension you configure. Once you change embedding backend / model / dimension, the old index may no longer be reusable as-is. The safer path is: back up first, check with `index_status()`, and if the runtime reports a dimension mismatch, run `rebuild_index(wait=true)` or validate against a fresh database.
>
> The table above shows template example values from `.env.example`. In particular, `RETRIEVAL_EMBEDDING_DIM` is still `64` in the default template, which means it is the **default template value; you must provide the provider's real dimension for remote backends** after you move to a real remote embedding path (`api` / `router` / `openai`). In the current setup-save path, the backend only writes the remote dimension you explicitly provide; it no longer auto-fills `1024` for you, and it no longer relies on the old public `4096` guess from the shipped C/D templates. If certain retrieval environment variables are completely missing at runtime, the backend will use its own fallback values (e.g., `hash` / `hash-v1` / `64`).
>
> Configuration semantics: `RETRIEVAL_EMBEDDING_BACKEND` only affects Embedding. Reranker does not have a `RETRIEVAL_RERANKER_BACKEND` toggle; it prioritizes reading `RETRIEVAL_RERANKER_*`, falling back to `ROUTER_*` (and finally to `OPENAI_*` base/key) if missing.
>
> For repo-local `stdio` / `python-wrapper`, `RETRIEVAL_REMOTE_TIMEOUT_SEC` is now also reused from the current repository `.env`; if you leave it unset, the repo-local default remains `8` seconds.
>
> The current Setup Assistant follows the same contract now: `Profile B/C/D` preset switches and related retrieval toggles clear hidden stale fields before save, the assistant supports the `openai` embedding backend, and switching from local hash to a remote embedding backend no longer leaves the old `64` behind. `Profile C` is the local/private router preset, so its `http://127.0.0.1:8001/v1` base is treated as a real local endpoint rather than a placeholder; `Profile D` keeps the remote template base and still expects you to replace it. `Profile C/D` also no longer make the local `.env` save button look ready until the required remote fields are real values. On any remote embedding backend (`api` / `router` / `openai`), that now also means a real positive-integer `embedding_dim`. If there is still no Dashboard auth configured and that first local save already includes remote provider-chain fields, the backend now intentionally writes only the Dashboard auth fields first and expects a follow-up authenticated save for the provider chain. Saving retrieval settings now also writes back `SEARCH_DEFAULT_MODE`: `Profile B` explicitly lands on `hybrid`, while `embedding_backend=none` returns to `keyword`. `Profile A` is now also shown explicitly in the assistant, and it still maps to the default `keyword + none` baseline. One more boundary is worth keeping in mind: when the assistant auto-opens on a fresh baseline, it still presents that documented start. When you open it manually, or when `/setup/status` already has a real runtime state, the form hydrates that current state instead. With the current code, a local runtime with no explicit retrieval env ends up showing the backend's real default `hash / 64` state rather than a synthetic `none` summary.
>
> More advanced options (such as `INTENT_LLM_*`, `RETRIEVAL_MMR_*`, `RETRIEVAL_SQLITE_VEC_*`, `CORS_ALLOW_*`, runtime observability/sleep consolidation toggles) are documented in `.env.example` and default to conservative values, not affecting the minimal startup path.
>
> Recommended defaults (usually fine to copy):
> - `INTENT_LLM_ENABLED=false`: Use built-in keyword rules first to reduce external dependencies.
> - `RETRIEVAL_MMR_ENABLED=false`: Check raw hybrid results first, only enable if "first few results are too similar."
> - `RETRIEVAL_SQLITE_VEC_ENABLED=false`: Keep the legacy path for normal deployments.
> - `CORS_ALLOW_ORIGINS=`: Leave empty for local dev; specify domains only when opening to browser cross-domain access.
>
> The model names above are just placeholder examples, not hard project dependencies. Memory Palace is not bound to a specific provider or model family; please change them to actual available embedding / reranker / chat model IDs from your own OpenAI-compatible services.
>
> If you later use `profile c/d`, whether you stop at `apply_profile.sh/.ps1` or continue into `docker_one_click.sh/.ps1`, those placeholder model IDs / endpoints / keys / embedding-dimension values are all treated as unresolved placeholders. The scripts fail-closed until you replace them with real values.
>
> If you are about to open the Dashboard locally, or directly use `curl` to call `/browse` / `/review` / `/maintenance`, it is suggested to add one of the following auth configurations to `.env`:
>
> - `MCP_API_KEY=change-this-local-key`
> - `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` (Only recommended for loopback debugging on your own machine)

### Step 2: Start Backend

```bash
cd backend
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
# .\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

> If you also plan to run backend tests afterwards, add:
>
> ```bash
> pip install -r requirements-dev.txt
> ```

Expected output:

```
Memory API starting...
SQLite database initialized.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

> The backend completes initialization via the `lifespan` context manager in `main.py`, including SQLite database creation and starting runtime states (Write Lane, Index Worker).
>
> The `uvicorn main:app --host 127.0.0.1 ...` command above is the recommended **local development** form.
>
> If you instead run `python main.py`, the current default is still loopback: `127.0.0.1:8000`. If you actually want LAN / remote direct access, bind it explicitly with `uvicorn main:app --host 0.0.0.0 --port 8000` (or your own listening address) and only do that after your `MCP_API_KEY`, firewall rules, reverse proxy, and equivalent network-side protections are already in place.

### Step 3: Start Frontend

```bash
cd frontend
npm install
npm run typecheck
npm run dev
```

> Frontend i18n dependencies are already included in `frontend/package.json` and `frontend/package-lock.json`. A normal `npm install` is sufficient; you don't need to install `i18next`, `react-i18next`, or `i18next-browser-languagedetector` separately.
>
> `frontend/package.json` now also ships a first-class `npm run typecheck` entry, so you can repeat the same frontend typecheck path locally without depending on a temporary `npx -p typescript ...` command.
>
> The Docker publish validation workflow now also runs this same `npm run typecheck` step, so local checks and pre-publish checks use the same frontend typecheck path.

Expected output:

```
VITE v7.x.x  ready in xxx ms
➜  Local:   http://127.0.0.1:5173/
```

Open your browser and visit `http://127.0.0.1:5173` to see the Memory Palace Dashboard.

If you wish to view the Dashboard buttons, fields, and typical operation flows page by page, please see:

- `docs/DASHBOARD_GUIDE_EN.md`

> If you see `Set API key` in the top right corner when starting manually, this is normal: the page is open, but protected interfaces like `/browse/*`, `/review/*`, and `/maintenance/*` are not yet authorized. Clicking this button now opens the **first-run setup assistant**, which can either save the Dashboard key in the current browser session or, when you are running against a non-Docker local checkout, write the common runtime fields into `.env`. That write path now only targets project-local `.env*` files. The assistant also has its own language toggle in the upper right corner, so you do not need to close it first just to switch to Chinese. Current status can still come back a little later, but fields you already typed yourself are no longer overwritten by that late status refresh; untouched retrieval fields continue to hydrate from the actual setup summary. On authenticated non-loopback paths, the assistant can still show the current setup summary, but the local `.env` save path stays disabled with an explicit reason because writes remain direct-loopback-only. If the backend is already running with `MCP_API_KEY`, even that loopback write path also expects the same valid key. `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` only relaxes direct loopback reads; it does not remove this local write gate. On the trusted Docker / GHCR proxy path, the assistant also no longer auto-opens just because the browser itself does not hold the key; if protected requests already work through the proxy, the page stays on the normal Dashboard flow. Section 5 will explain local validation.
>
> One more boundary tightened in this round: the first local `.env` save now also requires a non-empty Dashboard key. Leaving it blank is rejected by the backend instead of being treated like an anonymous bootstrap. The assistant also normalizes common provider API suffixes such as `/embeddings`, `/rerank`, and `/chat/completions`, and rejects malformed or link-local targets before save. Loopback IP literals such as `127.0.0.1` / `::1`, plus `localhost`, still stay allowed by default; if you intentionally point a provider base at another private IP literal, or at a hostname that resolves to a private non-loopback address, add it to `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` first.
>
> Small UI detail rechecked against the current code path: if the assistant shows interpolated labels that contain characters like `&` or `<...>`, they now render as normal text instead of showing HTML entities literally.

> If you configured `MCP_API_KEY`, click `Set API key` in the top right and enter the same key in the assistant. If you only want the Dashboard to authenticate first, prefer the browser-only save path.
> If you enabled `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`, direct requests from the local loopback address can access these protected data interfaces.

> If you choose **Save dashboard key only**, that key is stored in the current browser session (`sessionStorage`) until you clear it manually or that browser session ends. The assistant's `Profile B/C/D` presets and related retrieval toggles now clear hidden stale fields before save. `Profile C` keeps the real local/private router base `http://127.0.0.1:8001/v1`, while `Profile D` keeps the remote placeholder base `https://router.example.com/v1` and still expects you to replace it. The assistant also supports the `openai` embedding backend, and when you switch from local hash to a remote embedding backend it requires a real `RETRIEVAL_EMBEDDING_DIM` instead of silently leaving the old `64` behind. The local `.env` save path also stays disabled until the required remote fields are real values, so choosing `Profile C/D` alone is no longer enough to make the form look save-ready. On any remote embedding backend (`api` / `router` / `openai`), local `.env` save now also requires a real positive-integer `embedding_dim`. Common API suffixes such as `/embeddings`, `/rerank`, and `/chat/completions` are normalized automatically; malformed or link-local provider bases are rejected before save. Loopback IP literals still work without extra setup, and `localhost` stays allowed too, but if you intentionally use another private IP literal, or a hostname that resolves to a private non-loopback address, add it or its CIDR to `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` first. These presets still do not prove that your router is reachable, that the embedding dimension is correct, or that any old index has already been migrated. If your local router is not ready yet, switch the retrieval fields manually to direct `api` / `openai` mode for debugging. If reranker stays enabled on that direct path, you still need to fill the direct reranker base/model fields or turn reranker off first. If you just changed embedding backend / model / dimension, remember to restart the backend and reindex when needed. When the dialog is opened manually, the current code prefers the real `/setup/status` runtime state; only the first auto-open path keeps the documented `Profile A` baseline form.
>
> That browser-only save now also takes effect immediately for protected Dashboard requests in the current page, even if a runtime-injected key was already active before. When the save succeeds, the success banner stays visible until you close the dialog yourself.
>
> If you are opening the page through an authenticated non-loopback path, the setup assistant can still show the current status, but **Save local `.env` settings** stays disabled on purpose. That path is still reserved for direct loopback requests only.

> Dashboard tree writes and reflection are now connected on the same user-facing path. In plain terms: if you create or update memory through the Memory page, `/maintenance/learn/reflection` can now use that Dashboard-side write summary directly instead of stopping at `session_summary_empty` just because the change came from `/browse`.

> The assistant does not pretend that Docker env / proxy changes are hot-reloaded. If you change embedding / reranker / write-guard / intent settings, you still need to restart the affected `backend` / `sse` services afterwards. For Docker, continue using the profile scripts and container restart path.

> The frontend restores the stored language first. If there is no stored choice yet, common Chinese browser locales (`zh`, `zh-TW`, `zh-HK`, and similar `zh-*`) are normalized to `zh-CN`; other first-visit cases fall back to English. If you want to switch manually, use the language button in the top right, and the browser will remember your choice.

> If you open the Dashboard in Microsoft Edge, the current frontend now switches to a lighter visual mode automatically. In plain terms: the functions, auth flow, and setup assistant stay the same, but the page uses a static background, less blur, and less card motion to reduce local lag. Other browsers keep the normal visual treatment.

> One more small safety detail: if the current host cannot provide `confirm()`, the Memory page now fails closed for destructive confirmation flows instead of continuing as if the user had already agreed.

> The frontend dev server proxies `/api` to `MEMORY_PALACE_API_PROXY_TARGET` (default: `http://127.0.0.1:8000`) via `vite.config.js`.
>
> If you also want to verify same-origin SSE from the **local Vite dev entry**, start `run_sse.py` separately first and additionally set:
>
> ```bash
> MEMORY_PALACE_SSE_PROXY_TARGET=http://127.0.0.1:8010
> ```
>
> With that in place, `/sse`, `/messages`, and `/sse/messages` are also proxied to the local SSE process, so you do not need to hand-wire CORS just for local debugging.
>
> If you deploy the frontend under a non-root prefix and also set `VITE_API_BASE_URL`, the shared frontend SSE helper now resolves `/sse` against that prefixed API base as well, instead of always assuming the site root. Without browser-side auth it still behaves like a native `EventSource` path; with browser-side auth it switches to fetch-based SSE so the client can send auth headers and reconnect after a non-terminal drop. Changing or clearing browser-side Dashboard auth now also emits a maintenance-auth change event, and the Observability page uses that signal, plus a focus-time recheck, to rebuild its authenticated `/sse` stream when auth changes or after a terminal `401` stopped retries. That fetch-based path also pauses/resumes around `visibilitychange` / `pagehide` / `pageshow` / `beforeunload`, uses exponential-backoff retries, and aborts idle half-open streams with an idle watchdog.
>
> If you are doing a **non-root-path deployment** (for example the frontend lives under `/memory-palace/` and the backend API is exposed as `/memory-palace/api`), the frontend build can also set `VITE_API_BASE_URL`. By default it still uses `/api`, which remains the better fit for local Vite proxying and the repository-shipped Docker path.
>
> The current frontend behavior was also rechecked on this path: if `VITE_API_BASE_URL` points to a prefixed API root or to your own cross-origin API origin, the browser-saved Dashboard auth key now still follows protected `/browse`, `/review`, `/maintenance`, and `/setup` requests. It still does **not** send that key to unrelated third-party absolute URLs.

<p align="center">
  <img src="images/setup-assistant-en.png" width="900" alt="Memory Palace first-run setup assistant (English mode)" />
</p>

<p align="center">
  <img src="images/memory-palace-memory-page.png" width="900" alt="Memory Palace interface example (English mode)" />
</p>

---

## 4. Docker Deployment

### 4.1 Pull Prebuilt GHCR Images (Fastest for Users)

If your local build environment keeps failing, use the prebuilt GHCR images first. This path is for **starting the service quickly**, not for rebuilding images locally.

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

`apply_profile` creates `.env.docker` from the checked-in template and backs up an existing target before replacing it.

Default access addresses:

| Service | Address |
|---|---|
| Frontend | `http://localhost:3000` |
| Backend API | `http://localhost:18000` |
| SSE | `http://localhost:3000/sse` |

What this path does and does not do:

- It avoids **local image build**, but still assumes you have this repository checkout so you can use `docker-compose.ghcr.yml`, `.env.example`, and the profile scripts.
- It solves **Dashboard / API / SSE startup** only.
- It does **not** automatically configure local `skills / MCP / IDE host` entries on your machine.
- If you want the current repo's repo-local skill + MCP install path, keep this checkout and continue with `docs/skills/GETTING_STARTED_EN.md`.
- If you do not want the repo-local install path, any client that supports remote SSE MCP can still be configured manually to connect to `http://localhost:3000/sse` with the matching auth header / API key. For this GHCR path, `<YOUR_MCP_API_KEY>` normally means the `MCP_API_KEY` written into the `.env.docker` you just generated.
- The repository compose files use nested `${...:-...}` defaults for volume names. If your local Compose implementation is older, or you are still using classic `docker-compose`, this manual path may fail before `docker compose up` even starts the services. In that case, prefer `docker_one_click.sh/.ps1`, or pre-set `MEMORY_PALACE_DATA_VOLUME` / `MEMORY_PALACE_SNAPSHOTS_VOLUME` / `COMPOSE_PROJECT_NAME`.
- Unlike `docker_one_click.sh/.ps1`, this GHCR compose path does **not** auto-adjust ports. If `3000` / `18000` are occupied, set `MEMORY_PALACE_FRONTEND_PORT` / `MEMORY_PALACE_BACKEND_PORT` explicitly before `docker compose up`.
- If the container still needs to reach a **model service running on your host machine**, do not write `127.0.0.1` as the host-side address from inside the container. For the container, `127.0.0.1` points back to the container itself, not your host. Prefer `host.docker.internal` (or your actual reachable host address). The compose files now add `host.docker.internal:host-gateway`, so this path also works on modern Linux Docker.
- Do **not** assume the repo-local stdio wrapper reuses container data automatically. `scripts/run_memory_palace_mcp_stdio.sh` needs a host-side local repository `.env` and the local `backend/.venv`; it does not reuse container data from `/app/data`.
- If you later switch back to a local `stdio` client, your local `.env` must contain a host-accessible absolute path. If `.env` is missing while `.env.docker` exists, or if `.env` / an explicit `DATABASE_URL` still points to `/app/...` or `/data/...`, the wrapper refuses to start and tells you to use a host path or Docker `/sse` instead.

Stop services:

```bash
docker compose -f docker-compose.ghcr.yml down --remove-orphans
```

### 4.2 Docker One-Click Deployment

```bash
# macOS / Linux
bash scripts/docker_one_click.sh --profile b

# Windows PowerShell
.\scripts\docker_one_click.ps1 -Profile b

# If you need to inject the runtime API address/key from the current process into the Docker env file for this run (e.g., profile c/d)
# The injection toggle must be explicitly enabled (default is off):
bash scripts/docker_one_click.sh --profile c --allow-runtime-env-injection
# or
.\scripts\docker_one_click.ps1 -Profile c -AllowRuntimeEnvInjection
```

> If you enable this kind of local joint debugging injection under `profile c/d`, the script will switch this run to an explicit API mode and additionally force `RETRIEVAL_EMBEDDING_BACKEND=api`. The current injection path also carries explicit `RETRIEVAL_EMBEDDING_*` (including `RETRIEVAL_EMBEDDING_DIM`), `RETRIEVAL_RERANKER_*`, and optional `INTENT_LLM_*` / `WRITE_GUARD_LLM_*` / `COMPACT_GIST_LLM_*` values. When `RETRIEVAL_EMBEDDING_API_*` / `RETRIEVAL_RERANKER_API_*` are not explicitly provided, it will prioritize reusing `ROUTER_API_BASE/ROUTER_API_KEY` from the current process as a fallback; if you also set `INTENT_LLM_*`, this chain will also be injected. This mode is more suitable for local troubleshooting and is not equivalent to verifying the final release `router` template.
>
> On this path, `profile c/d + --allow-runtime-env-injection` now defers the template placeholder check until the injected runtime values have been written, and then still fail-closes if the required external settings remain missing.
>
> If you only want a fast smoke check first, hit the real `/embeddings` and `/rerank` endpoints with the same model and key you plan to use. That is usually quicker than starting from a full backend run.
>
> Note that `--runtime-env-mode` / `--runtime-env-file` are **not** arguments of `docker_one_click.sh/.ps1`. If you pass them directly to the one-click script, the command fails with `Unknown argument`. For public-repo `profile c/d` local debugging, keep using the explicit injection switches shown above. If you also need a stricter release-style verification, switch back to the actual `.env` / router configuration you plan to deploy and re-run that validation path separately.

> `docker_one_click.sh/.ps1` defaults to generating an independent temporary Docker env file for **each run**, passed to `docker compose` via `MEMORY_PALACE_DOCKER_ENV_FILE`; it only reuses a specific file if that environment variable is explicitly set, rather than sharing a fixed `.env.docker`.
>
> Concurrent deployments under the same checkout will be serialized by a deployment lock; if another one-click deployment is already executing, subsequent processes will exit immediately with a prompt to retry later.
>
> If you explicitly set `MEMORY_PALACE_DOCKER_ENV_FILE`, both one-click scripts now resolve it to a stable absolute path before they regenerate the file or hand it to `docker compose`, so the run no longer depends on which directory you launched it from. On the macOS / Linux shell path, `docker_one_click.sh` still updates that custom file through temp files created in the same directory, so replacing it is less likely to degrade into a cross-filesystem copy when the file lives outside the default temp area.
>
> The local build path now also uses checkout-scoped stable image names. In practice, once this checkout has completed one successful build, `--no-build` can keep reusing those images even if you change `COMPOSE_PROJECT_NAME`; you only need `--build` again on the first run or after deleting the local images.
>
> If `MCP_API_KEY` in the Docker env file is empty, `apply_profile.*` will automatically generate a local key. The Docker frontend will automatically include this key in its proxy layer, so **when starting via the recommended one-click script path**, protected requests usually already work; however, the page may still keep showing `Set API key`, because the browser page itself does not know the proxy-held key. Treat that as expected unless protected data also starts failing with `401` or empty states. Even then, the first-run setup assistant stays in guidance mode for Docker instead of pretending it can persist container env changes.
>
> Currently, Docker Compose first waits for the `backend` `/health` check to pass, and the one-click script then adds one extra frontend-proxied `/sse` reachability check before treating the frontend as truly ready. In practice, when the container first shows `running`, the page may still take a few more seconds to become truly available, which is normal.
>
> The backend container-side check is no longer “HTTP 200 from `/health` is enough”. It also runs `deploy/docker/backend-healthcheck.py`, which requires the payload to report `status == "ok"`. If detailed `/health` is already degraded, Docker keeps the backend unhealthy; when the request fails, the JSON is invalid, or the status is not `ok`, the script now prints one short failure reason first, which makes container-side diagnosis less guessy.
>
> On both the shell and PowerShell one-click paths, the local readiness probes now also force a loopback `NO_PROXY` / `no_proxy` bypass for `127.0.0.1`, `localhost`, `::1`, and `host.docker.internal`. In practice, a host proxy is less likely to make a healthy local `/health` or proxied `/sse` probe look broken.
>
> If your environment starts slowly, you can also tune that probe timeout through `MEMORY_PALACE_BACKEND_HEALTHCHECK_TIMEOUT_SEC`; the helper currently defaults to `5` seconds.
>
> Keep the WAL safety boundary in mind as well: the repository defaults only treat **Docker named volume + WAL** as a supported path. If you replace backend `/app/data` with a bind mount to NFS/CIFS/SMB or another network filesystem, explicitly switch back to `MEMORY_PALACE_DOCKER_WAL_ENABLED=false` and `MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete`. `docker_one_click.sh/.ps1` now performs that preflight check before `docker compose up` and aborts on the risky combination; manual `docker compose up` / `docker compose -f docker-compose.ghcr.yml up` does not do that validation for you.
>
> The Docker frontend also serves `/index.html` with `Cache-Control: no-store, no-cache, must-revalidate` to reduce the chance that a browser keeps an old entry page after a frontend update. If you still see an obviously old page right after upgrading the image, first confirm the new container is actually running, then refresh the page once. Only continue checking cache behavior if you also put your own reverse proxy or corporate cache in front of it.
>
> Docker also persists two runtime data paths by default: the database volume is isolated per compose project as `<compose-project>_data` (container path `/app/data`), and the Review snapshots volume is isolated as `<compose-project>_snapshots` (container path `/app/snapshots`). If you intentionally want to reuse an old shared volume, set `MEMORY_PALACE_DATA_VOLUME` / `MEMORY_PALACE_SNAPSHOTS_VOLUME` explicitly. If you execute `docker compose down -v` or manually delete these volumes, both parts are cleared together.
>
> **C/D Local Joint Debugging Suggestions**:
>
> - If your local machine's `router` hasn't connected embedding / reranker / llm yet, you can first directly configure `RETRIEVAL_EMBEDDING_*`, `RETRIEVAL_RERANKER_*`, `WRITE_GUARD_LLM_*` / `COMPACT_GIST_LLM_*` separately.
> - This makes it easier to determine which specific chain is unreachable, avoiding misjudging "one model not configured correctly" as the entire system being down.
> - Whether you finally adopt the `router` solution or direct configuration for `RETRIEVAL_EMBEDDING_*` / `RETRIEVAL_RERANKER_*`, it is recommended to run the startup and health checks again according to the **final actual deployment configuration**.

> The script automatically performs the following steps:
>
> 1. Calls the Profile script to generate the Docker env file for this run (defaults to a temporary file; reuses the specified path if `MEMORY_PALACE_DOCKER_ENV_FILE` is set).
> 2. Defaults to not reading current process environment variables to override template strategy keys (avoiding implicit profile changes); injects API address/key/model fields and explicit retrieval parameters such as `RETRIEVAL_EMBEDDING_DIM` only when the injection toggle is explicitly enabled.
> 3. Detects port conflicts and automatically finds available ports.
> 4. Parses and injects Docker persistent volumes: by default the script isolates them per compose project (`<compose-project>_data` for the database and `<compose-project>_snapshots` for Review snapshots); it only reuses an old volume when `MEMORY_PALACE_DATA_VOLUME` / `MEMORY_PALACE_SNAPSHOTS_VOLUME` is explicitly set.
> 5. Fails fast before startup if backend `/app/data` has been changed to a bind mount on NFS/CIFS/SMB or another network filesystem while WAL would still be enabled.
> 6. Locks concurrent deployments for the same checkout to avoid multiple `docker_one_click` instances overwriting each other.
> 7. Builds and starts containers via `docker compose`.

Default access addresses:

| Service | Address |
|---|---|
| Frontend | `http://localhost:3000` |
| Backend API | `http://localhost:18000` |
| SSE | `http://localhost:3000/sse` |
| Health Check | `http://localhost:18000/health` |

> **Port Mapping Explanation** (from `docker-compose.yml`):
>
> - The frontend container internally runs on port `8080`, mapped externally to `3000` (can be overridden by the `MEMORY_PALACE_FRONTEND_PORT` environment variable).
> - The backend container internally runs on port `8000`, mapped externally to `18000` (can be overridden by the `MEMORY_PALACE_BACKEND_PORT` environment variable).
> - Docker by default persists the database volume (`/app/data`) and review snapshot volume (`/app/snapshots`).
>
> Swagger `/docs` is no longer exposed by default; direct access will usually return `404`. For route details, use this guide plus [TECHNICAL_OVERVIEW_EN.md](TECHNICAL_OVERVIEW_EN.md) and [TOOLS_EN.md](TOOLS_EN.md).

Stop services:

```bash
COMPOSE_PROJECT_NAME=<compose project printed in console> docker compose -f docker-compose.yml down --remove-orphans
```

> The `down --remove-orphans` command above will not delete data volumes; the database and review snapshots will only be cleared if you explicitly use `docker compose ... down -v` or manually delete the corresponding volumes.

> If you need to verify Windows paths, it is recommended to run startup and smoke tests directly in the target Windows environment.

### 4.3 Backup Current Database

Before performing batch tests, migration verification, or wide-range configuration switching, it is recommended to make a consistent SQLite backup:

```bash
# macOS / Linux
bash scripts/backup_memory.sh

# Specify env / output directory
bash scripts/backup_memory.sh --env-file .env --output-dir backups

# Keep only the latest 10 backups
bash scripts/backup_memory.sh --env-file .env --output-dir backups --keep 10
```

```powershell
# Windows PowerShell
.\scripts\backup_memory.ps1

# Keep only the latest 10 backups
.\scripts\backup_memory.ps1 -EnvFile .env -OutputDir backups -Keep 10
```

> Backup files are written to `backups/` by default. If you are preparing to share the repository or package it for delivery, you usually don't need to include them.
>
> Both backup scripts read `DATABASE_URL` from the selected env file, strip optional query / fragment suffixes such as `?mode=...` or `#...`, and then back up the resolved SQLite file. On native Windows, prefer `backup_memory.ps1`; on `Git Bash` / `WSL`, `backup_memory.sh` is fine. Both scripts now add `busy_timeout`, copy in small page batches, and remove a partial backup file if the run fails halfway, so a failed backup does not leave behind a misleading artifact. Backup filenames now use UTC timestamps so mixed host/container runs sort more consistently. They also keep the latest `20` backups by default; use `--keep <count>` / `-Keep <count>` to change that, or pass `0` to disable rotation.
>
> If you only want to see the usage first, run `bash scripts/backup_memory.sh --help` or `.\scripts\backup_memory.ps1 -?`. On native Windows, the PowerShell script now checks the repo `backend/.venv` first and then falls back to common launchers such as `python3` / `py`, so a normal local repo setup usually does not need a special PATH tweak before backup.

### 4.4 Files Typically Not Needed for Submission

The repository has already placed typical local artifacts into `<repo-root>/.gitignore`:

- Environment and secret files: `.env`, `.env.*` (keep `.env.example`)
- Runtime databases: `*.db`, `*.sqlite`, `*.sqlite3`
- Database lock files: `*.init.lock`, `*.migrate.lock`
- Local tool configurations: `.mcp.json`, `.mcp.json.bak`, `.claude/`, `.codex/`, `.cursor/`, `.opencode/`, `.gemini/`, `.agent/`, `.playwright-cli/`
- Local cache and temporary directories: `.tmp/`, `.pytest_cache/`, `backend/.pytest_cache/`
- Frontend local artifacts: `frontend/node_modules/`, `frontend/dist/`
- Logs and snapshots: `*.log`, `snapshots/`, `backups/`
- Temporary test drafts: `frontend/src/*.tmp.test.jsx`
- Internal maintenance documents: `docs/improvement/`, `backend/docs/benchmark_*.md`
- One-time comparison summaries: `docs/evaluation_old_vs_new_*.md`
- Local validation reports: `docs/skills/TRIGGER_SMOKE_REPORT.md`, `docs/skills/MCP_LIVE_E2E_REPORT.md`

If you are preparing to share the project, package it for delivery, or just want to perform an environment self-check, it is recommended to execute:

```bash
bash scripts/pre_publish_check.sh
```

It checks for common local sensitive artifacts, tool configs, local validation reports, personal paths, and `.env.example` placeholders, helping you quickly confirm if the repository is suitable for direct delivery. If it only finds these local files exist, it will usually give a `WARN` to remind you to confirm them yourself before sharing.

If you additionally run these validation scripts:

```bash
python scripts/evaluate_memory_palace_skill.py
cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py
```

The scripts default to generating summaries in `<repo-root>/docs/skills/TRIGGER_SMOKE_REPORT.md` and `<repo-root>/docs/skills/MCP_LIVE_E2E_REPORT.md` respectively. These two results are mainly for local review and are not the primary instruction documents. The current scripts also redact common secret-like values, local absolute paths, and session tokens in those reports, and use private file permissions where the host supports them. `evaluate_memory_palace_skill.py` now returns a non-zero exit code whenever any check is `FAIL`; `SKIP` / `PARTIAL` / `MANUAL` do not fail the process by themselves. If you only want to override the Gemini smoke model locally for one run, set `MEMORY_PALACE_GEMINI_TEST_MODEL`; if you also need a separate fallback model, add `MEMORY_PALACE_GEMINI_FALLBACK_MODEL`. If `codex exec` does not emit structured output before the smoke timeout, the `codex` item is now reported as `PARTIAL` instead of stalling the whole run.
If you need isolated output during parallel review or CI, set `MEMORY_PALACE_SKILL_REPORT_PATH` / `MEMORY_PALACE_MCP_E2E_REPORT_PATH` first. When those variables use relative paths, the scripts now redirect them under the system temp directory's `memory-palace-reports/` root instead of writing back into the repository; if you want a fully controlled location, prefer an absolute path outside the repo.
If you just cloned the GitHub repository, it is normal if you don't see these two files yet; they are local artifacts generated after running the scripts.

---

## 5. Initial Validation

> The checks here focus on "getting the system running"; if you need additional local Markdown validation summaries, run the validation scripts mentioned above.
>
> Current real verification wording: this 2026-05-15 review session reran backend `1382 passed, 22 skipped`, frontend `203 passed`, frontend typecheck/build, i18n audit, bundle budget, repo-local live MCP e2e, and focused Docker/profile/SSE/script contracts. The public A/B/C/D benchmark tables were not recalculated in this pass, and native Windows / native Linux host runtime paths still keep explicit target-environment recheck boundaries.

### 5.1 Health Check

```bash
# Local Development
curl -fsS http://127.0.0.1:8000/health

# Docker Deployment
curl -fsS http://localhost:18000/health
```

Expected return (from the `/health` endpoint in `main.py`):

```json
{
  "status": "ok",
  "timestamp": "2026-02-19T08:00:00Z",
  "index": {
    "index_available": true,
    "degraded": false
  },
  "runtime": {
    "write_lanes": { ... },
    "index_worker": { ... }
  }
}
```

> This detailed payload with `index` / `runtime` is returned by default only for local loopback requests, or for requests carrying a valid `MCP_API_KEY`. Unauthenticated remote `/health` probes intentionally receive only a shallow payload such as `status` and `timestamp`.
>
> `status` as `"ok"` indicates the system is normal; if the index is unavailable or an error occurs, `status` will become `"degraded"`. For these **detailed health checks** on loopback or authenticated requests, the endpoint now also returns HTTP `503` whenever it is degraded, so Docker health checks and operators can treat it as not ready. Unauthenticated remote shallow health checks still stay on HTTP `200`.

### 5.2 Browsing Memory Tree

```bash
curl -fsS "http://127.0.0.1:8000/browse/node?domain=core&path=" \
  -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>"
```

> This endpoint comes from `api/browse.py`'s `GET /browse/node` and is used to view the memory node tree under a specific domain. The `domain` parameter corresponds to the domains configured in `VALID_DOMAINS` in `.env`.
>
> - If you configured `MCP_API_KEY`, please include the `X-MCP-API-Key` as shown above.
> - If you enabled `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` and the request comes from the local loopback address (and has no forwarded headers), you can omit the authentication header.

### 5.3 Checking Route Documentation

The backend no longer exposes `http://127.0.0.1:8000/docs` by default; direct access will usually return `404`. That is the default security boundary, not a startup failure.

If you need to inspect the interfaces:

- Start with Sections 5 and 6 in this guide
- Then read the HTTP / MCP overview in [TECHNICAL_OVERVIEW_EN.md](TECHNICAL_OVERVIEW_EN.md)
- For the most exact current behavior, check the API tests under `backend/tests/`

---

## 6. MCP Access

Memory Palace provides **9 tools** via the [MCP protocol](https://modelcontextprotocol.io/) (defined in `mcp_server.py`):

| Tool Name | Purpose |
|---|---|
| `read_memory` | Read memory (supports special URIs like `system://boot`, `system://index`) |
| `create_memory` | Create a new memory node (explicitly filling `title` is recommended) |
| `update_memory` | Update existing memory (priority use of diff patch) |
| `delete_memory` | Delete a memory node |
| `add_alias` | Add an alias for a memory node |
| `search_memory` | Search memory (keyword / semantic / hybrid modes) |
| `compact_context` | Compact context (cleanup old session logs) |
| `rebuild_index` | Rebuild search index |
| `index_status` | View index status |

### 6.1 stdio Mode (Recommended for Local Use)

```bash
cd backend
python mcp_server.py

# If you are starting in a new terminal or client configuration, this one is more stable
./.venv/bin/python mcp_server.py   # Windows PowerShell: .\.venv\Scripts\python.exe mcp_server.py
```

> In `stdio` mode, MCP tools communicate directly through the process's standard input/output, **bypassing the HTTP/SSE authentication layer**. `MCP_API_KEY` is not required.
>
> The `python mcp_server.py` here assumes you are still using the **`backend/.venv` created and populated with dependencies in Step 2**. If you switch to a new terminal or are configuring local MCP in a client, prioritize using the project's own `.venv` interpreter. Otherwise, errors like `ModuleNotFoundError: No module named 'sqlalchemy'` will occur before the MCP process truly starts.
>
> If you are wiring MCP in a client configuration, choose the repo-local wrapper by platform:
>
> - native Windows: `python backend/mcp_wrapper.py`
> - macOS / Linux / Git Bash / WSL: `bash scripts/run_memory_palace_mcp_stdio.sh`
>
> These repo-local wrappers keep the same boundary conditions: they depend on the local `backend/.venv`, reuse the current repository `.env` / `DATABASE_URL` first, and also keep using `RETRIEVAL_REMOTE_TIMEOUT_SEC` from that same `.env` when it is set; if you leave it unset, the repo-local default remains `8` seconds. They only fall back to the repo's default SQLite path when neither a local `.env` nor `.env.docker` exists. If the repository only has `.env.docker`, or if a local `.env` / explicit `DATABASE_URL` still points at a Docker-internal path such as `sqlite+aiosqlite:////app/data/memory_palace.db`, `sqlite+aiosqlite://///app/data/memory_palace.db`, an uppercase `/APP/...` form, a `/data/...` variant, or a percent-escaped form such as `sqlite+aiosqlite:////%2Fapp%2Fdata/...`, they refuse to start on purpose. Relative sqlite values such as `sqlite+aiosqlite:///demo.db` are rejected as well. In a Docker-only setup, prefer the exposed `/sse` endpoint instead.
>
> On the shell-wrapper path, `run_memory_palace_mcp_stdio.sh` also exports `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1` before it starts Python. In plain language: a non-UTF-8 locale is less likely to break local stdio traffic.
>
> Both repo-local wrappers now also merge any existing `NO_PROXY` / `no_proxy` values and add `localhost`, `127.0.0.1`, `::1`, and `host.docker.internal`. In plain language: if you run Ollama or another local OpenAI-compatible service on the same machine, repo-local stdio is less likely to be misrouted through a host proxy. This protection applies to the repository's two built-in repo-local wrappers; it does not mean every possible backend launch path gets the same proxy bypass by default.

### 6.2 SSE Mode

```bash
cd backend
HOST=127.0.0.1 PORT=8010 python run_sse.py
```

```powershell
cd backend
$env:HOST = "127.0.0.1"
$env:PORT = "8010"
python run_sse.py
```

> `python run_sse.py` first tries loopback `127.0.0.1:8000`; if local `8000` is already occupied by the main backend, it automatically falls back to `127.0.0.1:8010`. If you explicitly bind `HOST=::1`, it checks `::1:8000` separately and does not fall back just because IPv4 `8000` is busy. When that happens, the startup log also prints the final `/sse` URL and tells you to update the client config or set `PORT` explicitly. You can still override both `HOST` and `PORT` explicitly. SSE mode remains protected by `MCP_API_KEY`.
>
> The same SSE process also provides a lightweight `/health` endpoint, mainly for standalone local debugging; the truly open streaming entry point for MCP clients remains `/sse`.
>
> On this local operator path, stopping `run_sse.py` while an `/sse` stream is still active now exits quietly instead of printing the previous ASGI shutdown traceback.
>
> The command above deliberately binds to `127.0.0.1`, which is more suitable for local machine debugging. If you truly need to allow access from other machines, change `HOST` to `0.0.0.0` (or your actual listening address). This will allow remote clients to connect to the listening address, but API Key, reverse proxy, firewall, and transport layer security will still need to be completed by you.
>
> If you use Docker one-click deployment or the GHCR compose path, SSE is no longer served by an independent `sse` container. It is mounted directly inside the `backend` process and then exposed at `http://127.0.0.1:3000/sse` through the frontend proxy. In practice, the Docker topology is now `backend + frontend`, while the public `/sse`, `/messages`, and `/sse/messages` endpoints stay the same.
>
> For containerized Profile C / D setups, the compose files also add `host.docker.internal:host-gateway`, so `host.docker.internal` is the preferred way to reach a model service running on your host machine, including modern Linux Docker.
>
> Treat that Docker frontend port as a trusted admin surface, not as public end-user auth. Anyone who can directly reach `3000` can use the Dashboard and its proxied protected routes, so add your own VPN, reverse-proxy auth, or network ACL before exposing it outside a trusted network.
>
> The `HOST=127.0.0.1 PORT=8010` example above is for **local loopback**. Only if you indeed want to open it to remote clients should you change it to `HOST=0.0.0.0` (or the target binding address) and complete the network-side security controls yourself.
>
> If you connect to `/sse` once with `curl` or a script, then disconnect and separately send the same `session_id` to `/messages`, seeing a `404` / `410` is normal: it indicates the previous SSE session has closed. The correct normal chain should be "keep the `/sse` connection alive first, and then have the client continue sending requests to `/messages`."

### 6.2.1 Multi-client concurrency (optional, but recommended)

If multiple CLI / IDE hosts will point to the **same SQLite file**, add this block to `.env`:

```env
RUNTIME_WRITE_WAL_ENABLED=true
RUNTIME_WRITE_JOURNAL_MODE=wal
RUNTIME_WRITE_WAL_SYNCHRONOUS=normal
RUNTIME_WRITE_BUSY_TIMEOUT_MS=5000
```

In plain language:

- each stdio MCP client is usually a separate Python process
- different processes do not share the same in-process write lock
- WAL plus a larger `busy_timeout` reduces `database is locked` failures when several clients write at the same time

One more note about the current default path:

- if you use the repository-shipped Docker / GHCR compose path, compose already forces the journal mode to `wal`
- the `.env` block above is mainly for **repo-local stdio / manually started multi-process local paths**

### 6.3 Client Configuration Examples

**stdio Mode**

Native Windows (preferred there):

```json
{
  "mcpServers": {
    "memory-palace": {
      "command": "python",
      "args": ["/ABS/PATH/TO/REPO/backend/mcp_wrapper.py"]
    }
  }
}
```

macOS / Linux / Git Bash / WSL:

```json
{
  "mcpServers": {
    "memory-palace": {
      "command": "bash",
      "args": ["/ABS/PATH/TO/REPO/scripts/run_memory_palace_mcp_stdio.sh"]
    }
  }
}
```

> If you haven't created `backend/.venv` yet, go back to **Step 2** to complete the virtual environment and dependency installation.
>
> In a native Windows environment, prefer `python + backend/mcp_wrapper.py` directly. Only keep `bash + run_memory_palace_mcp_stdio.sh` when you already have Git Bash / WSL available and want to stay on the shell-wrapper path.
>
> If a Windows-style host still ends up launching `backend/mcp_wrapper.py` from `Git Bash / MSYS / Cygwin`, the wrapper now also prefers `.venv/Scripts/python.exe` first. This is only a fallback guard; it does not change the recommended path above.

**SSE Mode**:

```json
{
  "mcpServers": {
    "memory-palace": {
      "url": "http://127.0.0.1:8010/sse"
    }
  }
}
```

> ⚠️ Replace `127.0.0.1:8010` here with the actual host and port you used when starting `run_sse.py`.
>
> ⚠️ SSE is still protected by `MCP_API_KEY`. Most clients also need to configure request headers or a Bearer Token; please refer to the client's own MCP documentation for specific field names.
>
> ⚠️ `HOST=0.0.0.0` only means "allow remote connection to this listening address," not "allow unauthenticated access."

### 6.3.1 What is currently safe to document

If your goal is to connect a client manually to Docker's exposed `/sse`, the current public guidance should be split into two groups:

| Client | Current public stance | Recommended path |
|---|---|---|
| `Claude Code` | Official CLI already exposes a remote SSE option | Safe to document directly below |
| `Gemini CLI` | Official CLI already exposes a remote SSE option | Safe to document directly below |
| `Codex CLI` | Current official evidence is remote `--url` for streamable HTTP | For this repository today, prefer the repo-local stdio path |
| `OpenCode` | Current official evidence is the generic `remote + url` structure | For this repository today, prefer the repo-local path unless you are comfortable mapping the generic remote config yourself |

In other words:

- if you want to connect a client manually to `http://localhost:3000/sse`
- the **publicly supported direct path today is Claude Code and Gemini CLI first**
- for `Codex` / `OpenCode`, this repository should not yet describe `/sse` as a fully validated copy-paste path

For the Docker / GHCR paths in Section 4, read `<YOUR_MCP_API_KEY>` from the `MCP_API_KEY` value in the `.env.docker` file you just generated.

### 6.3.2 Claude Code manual `/sse` connection

```bash
claude mcp add \
  --transport sse \
  --scope project \
  --header "X-MCP-API-Key: <YOUR_MCP_API_KEY>" \
  memory-palace \
  http://127.0.0.1:3000/sse
```

Check:

```bash
claude mcp list
```

Notes:

- Claude Code officially supports `stdio`, `sse`, and `http`
- if Memory Palace later exposes a clearer HTTP / streamable HTTP MCP entry, prefer `http`
- for the current public repository, the remote entry users can connect to directly is `/sse`
- treat `/sse` as the canonical public URL; `/sse/` is now only a compatibility spelling and is forwarded to the same backend SSE path
- for the GHCR / Docker path above, `<YOUR_MCP_API_KEY>` normally comes from `.env.docker`, not from a repo-local stdio wrapper

### 6.3.3 Gemini CLI manual `/sse` connection

```bash
gemini mcp add \
  --transport sse \
  --scope project \
  --header "X-MCP-API-Key: <YOUR_MCP_API_KEY>" \
  memory-palace \
  http://127.0.0.1:3000/sse
```

Check:

```bash
gemini mcp list
```

If you prefer editing `settings.json` directly, the minimal public skeleton we can safely confirm is:

```json
{
  "mcpServers": {
    "memory-palace": {
      "url": "http://127.0.0.1:3000/sse",
      "headers": {
        "X-MCP-API-Key": "<YOUR_MCP_API_KEY>"
      }
    }
  }
}
```

For the GHCR / Docker path above, `<YOUR_MCP_API_KEY>` normally comes from the `MCP_API_KEY` in `.env.docker`.

### 6.3.4 Why there is no direct `/sse` copy-paste block for `Codex / OpenCode` here

This does **not** mean they can never support remote MCP. It means the current public evidence is still narrower than what would be needed for this repository to claim that `/sse` is already a fully validated copy-paste path:

- `Codex CLI` currently documents `codex mcp add <name> --url <URL>` for remote MCP / streamable HTTP
- `OpenCode` currently documents the generic `type = remote` / `url` structure
- but the public remote endpoint exposed and validated by this repository today is `/sse`

So, to avoid misleading users:

- `Codex / OpenCode` should still prefer the repo-local installation path today
- once we complete a dedicated validation path for `Memory Palace /sse`, that client-specific remote example can be promoted into public copy-paste docs

---

## 7. HTTP/SSE Interface Authentication

Some HTTP interfaces of Memory Palace are protected by `MCP_API_KEY`, adopting a **fail-closed** strategy (defaults to `401` if Key is not configured).

### Protected Interfaces

| Route Prefix | Description | Auth Method |
|---|---|---|
| `/maintenance/*` | Maintenance interfaces (orphan node cleanup, etc.) | `require_maintenance_api_key` |
| `/review/*` | Review interfaces (content audit process) | `require_maintenance_api_key` |
| `/browse/*` (GET/POST/PUT/DELETE) | Memory tree read/write operations | `require_maintenance_api_key` |
| `/sse` and `/messages` in `run_sse.py` | MCP SSE transport channel and message entry | `apply_mcp_api_key_middleware` |

### Authentication Methods

The backend supports two types of Headers for passing the API Key (defined in `api/maintenance.py` and `run_sse.py`):

```bash
# Method 1: Custom Header
curl -fsS http://127.0.0.1:8000/maintenance/orphans \
  -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>"

# Method 2: Bearer Token
curl -fsS http://127.0.0.1:8000/maintenance/orphans \
  -H "Authorization: Bearer <YOUR_MCP_API_KEY>"
```

### Frontend Auth Configuration

If the frontend also needs to access protected interfaces, runtime configuration can be injected in **local debugging or your own controlled private deployment environment** (frontend `src/lib/api.js` will read `window.__MEMORY_PALACE_RUNTIME__`):

```html
<script>
  window.__MEMORY_PALACE_RUNTIME__ = {
    maintenanceApiKey: "<YOUR_MCP_API_KEY>",
    maintenanceApiKeyMode: "header"
  };
</script>
```

> Do not write the real `MCP_API_KEY` into any public pages, shared static resources, or HTML delivered to end users. This global object can be read directly in the browser.

> This configuration is mainly for the scenario of **manually starting front and back ends locally**.
>
> Docker one-click deployment by default does not require writing the key into the page: the frontend container forwards the same `MCP_API_KEY` to protected Dashboard API routes, `/sse`, and `/messages` at the proxy layer. It no longer attaches that key to every generic `/api/*` path.

### Skipping Auth for Local Debugging

If you don't want to configure an API Key during local development, set the following in `.env`:

```env
MCP_API_KEY_ALLOW_INSECURE_LOCAL=true
```

> This option only applies to **direct requests** from `127.0.0.1` / `::1` / `localhost`; if the request has forwarded headers, it will still be rejected. It only affects HTTP/SSE interfaces and **does not affect** stdio mode (stdio does not go through the auth layer).

---

## 8. Common FAQ

| Issue | Cause and Solution |
|---|---|
| `ModuleNotFoundError` when starting backend | Most common cause is not using `backend/.venv` or not installing dependencies in that environment. Execute `source .venv/bin/activate && pip install -r requirements.txt` first; if it's local stdio MCP, prioritize using `./.venv/bin/python mcp_server.py` (Windows: `.\.venv\Scripts\python.exe mcp_server.py`). |
| `DATABASE_URL` error | Absolute paths are recommended, and it must have the `sqlite+aiosqlite:///` prefix. Example: `sqlite+aiosqlite:////absolute/path/to/memory_palace.db`. |
| Local stdio MCP in a client fails with `startup failed`, `initialize response`, or a similar startup interruption | Check whether `.env` or an explicit `DATABASE_URL` points to `/app/...` or `/data/...`. That is a Docker container path; `scripts/run_memory_palace_mcp_stdio.sh` now refuses to start with it on purpose. Use a host-accessible absolute path instead, or keep using Docker `/sse`. |
| Frontend accessing API returns `502` or `Network Error` | Confirm the backend has started and is running on port `8000`. Check if the proxy target in `vite.config.js` matches the backend port. |
| Protected interface returns `401` | Local manual startup: configure `MCP_API_KEY` or set `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`; Docker: confirm if using the Docker env file generated by `apply_profile.*` / `docker_one_click.*`. |
| SSE `/messages` returns `429` or `413` | `429` means the same client principal is posting too many messages in a short window; the current bucket key prefers the resolved client address and, when auth is present, adds a stable hash of that auth token, so simply reconnecting with a new `session_id` no longer clears the bucket by accident. Check for duplicate retries or retry loops first. `413` means one request body exceeds `SSE_MESSAGE_MAX_BODY_BYTES`, so reduce the payload size or raise the backend limit intentionally. |
| Docker startup port conflict | `docker_one_click.sh` automatically finds idle ports by default. You can also specify manually via `--frontend-port` / `--backend-port`. |

For more troubleshooting, please refer to [TROUBLESHOOTING_EN.md](TROUBLESHOOTING_EN.md).

---

## 9. Further Reading

| Document | Content |
|---|---|
| [DEPLOYMENT_PROFILES_EN.md](DEPLOYMENT_PROFILES_EN.md) | Detailed parameter explanation and selection guide for deployment profiles (A/B/C/D). |
| [TOOLS_EN.md](TOOLS_EN.md) | Complete semantics, parameters, and return formats for the 9 MCP tools. |
| [TECHNICAL_OVERVIEW_EN.md](TECHNICAL_OVERVIEW_EN.md) | System architecture, data flow, and technical details. |
| [TROUBLESHOOTING_EN.md](TROUBLESHOOTING_EN.md) | Common issue troubleshooting and diagnosis. |
| [SECURITY_AND_PRIVACY_EN.md](SECURITY_AND_PRIVACY_EN.md) | Security model and privacy design. |
