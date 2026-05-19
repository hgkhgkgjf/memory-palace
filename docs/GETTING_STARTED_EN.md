# Quick Start

This guide helps you get Memory Palace running in a few minutes.

> Memory Palace is a long-term memory system for AI Agents. It exposes 9 tools via the [MCP protocol](https://modelcontextprotocol.io/) for clients like Claude Code, Codex, Gemini CLI, and OpenCode. If you are integrating an IDE host such as Cursor / Windsurf / VSCode, see `docs/skills/IDE_HOSTS_EN.md`.
>
> If what you need is the CLI-side skill + MCP installation path, go to `docs/skills/GETTING_STARTED_EN.md`.

---

## 1. Requirements

| Dependency | Minimum Version |
|---|---|
| Python | 3.10+ |
| Node.js | 20.19+ or 22.12+ |
| npm | 9+ |
| Docker (optional) | 20+ |
| Docker Compose (optional) | 2.0+ (a recent `docker compose` plugin is recommended) |

If your machine exposes Python as `python3`, replace `python` with `python3` in the commands below.

---

## 2. Three Ways to Start

| Method | When to Use | Section |
|---|---|---|
| Docker one-click | You want it running fast | 4.1 |
| GHCR prebuilt images | Local build keeps failing | 4.2 |
| Local source | You want to edit or debug | 3 |

---

## 3. Local Development

### Step 1: Prepare Configuration

```bash
cp .env.example .env
```

Edit `.env` and set `DATABASE_URL` to an absolute path on your machine:

```
DATABASE_URL=sqlite+aiosqlite:////absolute/path/to/memory_palace/demo.db
```

Notes:
- macOS / Linux absolute path prefix is `sqlite+aiosqlite:////` (4 slashes)
- Windows is `sqlite+aiosqlite:///C:/...` (3 slashes)
- The local path must be a real host path, including `/Users/...` and `/home/...`
- Do not copy container paths like `/app/...` or `/data/...` into your local `.env`. The local stdio wrapper refuses to start with them.

Repo-local MCP wrapper by platform:
- native Windows: `python backend/mcp_wrapper.py`
- macOS / Linux / Git Bash / WSL: `bash scripts/run_memory_palace_mcp_stdio.sh`

You can also use the profile script to generate a preset config:

```bash
# macOS / Linux
bash scripts/apply_profile.sh macos b

# Windows PowerShell
.\scripts\apply_profile.ps1 -Platform windows -Profile b
```

The second argument is the Profile (`a` / `b` / `c` / `d`); the third is an optional output file. See [DEPLOYMENT_PROFILES_EN.md](DEPLOYMENT_PROFILES_EN.md) for details.

**Common configuration items** (more in `.env.example`):

| Item | Description |
|---|---|
| `DATABASE_URL` | SQLite database path (absolute path recommended) |
| `SEARCH_DEFAULT_MODE` | Search mode: `keyword` / `semantic` / `hybrid` |
| `RETRIEVAL_EMBEDDING_BACKEND` | Embedding backend: `none` / `hash` / `router` / `api` / `openai` |
| `RETRIEVAL_EMBEDDING_DIM` | Embedding vector dimension; must match what the provider returns |
| `RETRIEVAL_RERANKER_ENABLED` | Whether to enable the reranker |
| `MCP_API_KEY` | Authentication key for HTTP/SSE interfaces |
| `MCP_API_KEY_ALLOW_INSECURE_LOCAL` | Loopback bypass (debug only) |
| `VALID_DOMAINS` | Allowed writable memory URI domains |

If you use Profile C/D with a remote embedding/reranker, replace the example values with real endpoint / key / model / dimension. The script rejects placeholders. `RETRIEVAL_EMBEDDING_DIM=1024` is only a sample default template value; you must provide the provider's real dimension for remote backends, and the assistant no longer auto-fills `1024` for you.

### Step 2: Start the Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate           # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

On a successful start you should see:

```
Memory API starting...
SQLite database initialized.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### Step 3: Start the Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173` in your browser.

If you see `Set API key` in the top-right corner, click it to open the first-run setup assistant:
- To only authenticate the Dashboard, choose **Save dashboard key only** (stored in `sessionStorage`)
- To write configuration to `.env`, the option is available only when running locally (not via Docker) and accessed from the loopback address

Dashboard usage is documented in [DASHBOARD_GUIDE_EN.md](DASHBOARD_GUIDE_EN.md).

---

## 4. Docker Deployment

### 4.1 One-Click Script (Recommended)

```bash
# macOS / Linux
bash scripts/docker_one_click.sh --profile b

# Windows PowerShell
.\scripts\docker_one_click.ps1 -Profile b
```

The script generates the Docker env file, detects port conflicts, builds, and starts the containers.

Once it's running:

| Service | Address |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:18000 |
| SSE | http://localhost:3000/sse |
| Health Check | http://localhost:18000/health |

If the default ports are occupied, the script picks free ones automatically; use the addresses printed at the end of the script. You can also specify them manually:

```bash
bash scripts/docker_one_click.sh --profile b --frontend-port 3100 --backend-port 18100
```

Stop services:

```bash
COMPOSE_PROJECT_NAME=<project printed by the console> docker compose -f docker-compose.yml down --remove-orphans
```

`down --remove-orphans` does not delete data volumes; only `down -v` clears the database and review snapshots.

**Profile C/D local debugging**: To inject your host's router/API into Docker, explicitly enable the injection flag:

```bash
bash scripts/docker_one_click.sh --profile c --allow-runtime-env-injection
```

When this flag is on, host-side `127.0.0.1` / `localhost` is rewritten to `host.docker.internal` so containers can reach host services.

**Data volumes and WAL safety**:
- Data volumes are isolated per compose project: `<compose-project>_data` and `<compose-project>_snapshots`
- The repository supports only the Docker named volume + WAL combination
- If you bind-mount `/app/data` to NFS/CIFS/SMB, set `MEMORY_PALACE_DOCKER_WAL_ENABLED=false` and `MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete`; if you bypass the one-click script and run `docker compose up` manually, enforce the same rule yourself

**Accessing host model services**: Do not use `127.0.0.1` inside the container; it points to the container itself. Use `host.docker.internal` — compose already adds `host-gateway`.

### 4.2 GHCR Prebuilt Images

If your local build keeps failing, pull the prebuilt images:

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
- This path does not auto-pick ports. If 3000 / 18000 are taken, set `MEMORY_PALACE_FRONTEND_PORT` / `MEMORY_PALACE_BACKEND_PORT` first
- This path does not auto-configure skills / MCP / IDE host; follow `docs/skills/GETTING_STARTED_EN.md` separately
- You still need the repository checkout because it uses `docker-compose.ghcr.yml` and the profile scripts

Stop services:

```bash
docker compose -f docker-compose.ghcr.yml down --remove-orphans
```

### 4.3 Back Up the Database

```bash
# macOS / Linux
bash scripts/backup_memory.sh

# Windows PowerShell
.\scripts\backup_memory.ps1
```

Backups are written to `backups/` with UTC timestamp names; the latest 20 are kept by default.

```bash
# Custom retention
bash scripts/backup_memory.sh --keep 10
```

---

## 5. Verify the Service

### Health Check

```bash
# Local
curl -fsS http://127.0.0.1:8000/health

# Docker
curl -fsS http://localhost:18000/health
```

A `{"status":"ok",...}` response means the service is up. Loopback or authenticated requests receive detailed `index` / `runtime` fields; unauthenticated remote calls receive only a shallow payload. The endpoint returns HTTP `503` if the system is degraded.

### Browse the Memory Tree

```bash
curl -fsS "http://127.0.0.1:8000/browse/node?domain=core&path=" \
  -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>"
```

`domain` corresponds to `VALID_DOMAINS` in `.env`.

> Swagger `/docs` is not exposed by default. For interface details, see this guide plus [TECHNICAL_OVERVIEW_EN.md](TECHNICAL_OVERVIEW_EN.md) and [TOOLS_EN.md](TOOLS_EN.md).

---

## 6. MCP Integration

Memory Palace provides 9 MCP tools (defined in `backend/mcp_server.py`):

| Tool | Purpose |
|---|---|
| `read_memory` | Read memory (supports `system://boot`, `system://index`, etc.) |
| `create_memory` | Create a new memory node |
| `update_memory` | Update memory (diff patch preferred) |
| `delete_memory` | Delete a memory node |
| `add_alias` | Add an alias |
| `search_memory` | Search (keyword / semantic / hybrid) |
| `compact_context` | Compact context |
| `rebuild_index` | Rebuild the search index |
| `index_status` | Inspect the index state |

Full semantics in [TOOLS_EN.md](TOOLS_EN.md).

### 6.1 stdio Mode (Recommended for Local Use)

stdio talks via the process's standard input/output and bypasses the HTTP auth layer.

Client configuration (pick the wrapper for your platform):

**macOS / Linux / Git Bash / WSL:**

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

**Native Windows:**

```json
{
  "mcpServers": {
    "memory-palace": {
      "command": "C:\\ABS\\PATH\\TO\\REPO\\backend\\.venv\\Scripts\\python.exe",
      "args": ["C:\\ABS\\PATH\\TO\\REPO\\backend\\mcp_wrapper.py"]
    }
  }
}
```

Use the venv's `python.exe` directly so the wrapper finds the right interpreter even when system `PATH` doesn't include it. Replace `C:\\ABS\\PATH\\TO\\REPO` with your real repository path; JSON requires the backslashes to be escaped (`\\`).

Both wrappers rely on the local `backend/.venv` and the current repository's `.env`. If you haven't created `.venv` yet, go back to **Step 2**.

### 6.2 SSE Mode

```bash
cd backend
HOST=127.0.0.1 python run_sse.py
```

```powershell
cd backend
$env:HOST = "127.0.0.1"
Remove-Item Env:PORT -ErrorAction SilentlyContinue
python run_sse.py
```

When `PORT` is not set, an occupied 8000 falls back to 8010 automatically. Setting `PORT` pins the server to that port. SSE remains protected by `MCP_API_KEY`.

Only set `HOST=0.0.0.0` when you really need remote clients; you are responsible for the API Key, firewall, and reverse proxy in that case.

In a Docker deployment, SSE is mounted inside the backend process and exposed at `http://127.0.0.1:3000/sse` via the frontend proxy.

Client configuration:

```json
{
  "mcpServers": {
    "memory-palace": {
      "url": "http://127.0.0.1:8010/sse"
    }
  }
}
```

Most clients also need an `X-MCP-API-Key` header; check your client's MCP documentation for the exact field.

### 6.3 Remote SSE Client Examples

**Claude Code:**

```bash
claude mcp add \
  --transport sse \
  --scope project \
  --header "X-MCP-API-Key: <YOUR_MCP_API_KEY>" \
  memory-palace \
  http://127.0.0.1:3000/sse
```

**Gemini CLI:**

```bash
gemini mcp add \
  --transport sse \
  --scope project \
  --header "X-MCP-API-Key: <YOUR_MCP_API_KEY>" \
  memory-palace \
  http://127.0.0.1:3000/sse
```

For Docker / GHCR deployments, `<YOUR_MCP_API_KEY>` is the `MCP_API_KEY` value in `.env.docker`.

For Codex CLI and OpenCode, prefer the repo-local stdio path for now; the remote SSE path has not been validated.

### 6.4 Multiple Concurrent Clients

If multiple stdio MCP clients point to the same SQLite file, add to `.env`:

```env
RUNTIME_WRITE_WAL_ENABLED=true
RUNTIME_WRITE_JOURNAL_MODE=wal
RUNTIME_WRITE_WAL_SYNCHRONOUS=normal
RUNTIME_WRITE_BUSY_TIMEOUT_MS=5000
```

Docker deployments already force `wal`; this block is mainly for repo-local stdio.

---

## 7. HTTP/SSE Authentication

`MCP_API_KEY` protects these routes (fail-closed: missing key returns 401):

| Path | Description |
|---|---|
| `/maintenance/*` | Maintenance interfaces |
| `/review/*` | Review interfaces |
| `/browse/*` | Memory tree read/write |
| `/sse` and `/messages` | MCP SSE channel |

Send the key as a header (pick one):

```bash
curl -fsS http://127.0.0.1:8000/maintenance/orphans \
  -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>"

# Or
curl -fsS http://127.0.0.1:8000/maintenance/orphans \
  -H "Authorization: Bearer <YOUR_MCP_API_KEY>"
```

**Skip auth for local debugging**: set `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` in `.env`. It only applies to direct loopback requests (`127.0.0.1` / `::1` / `localhost`) and does not affect stdio mode.

stdio mode does not go through the auth layer; no key is needed.

---

## 8. Common Issues

| Issue | Solution |
|---|---|
| Backend `ModuleNotFoundError` on start | You are not using `backend/.venv`. Run `source .venv/bin/activate && pip install -r requirements.txt` |
| `DATABASE_URL` error | Use an absolute path with `sqlite+aiosqlite:///` prefix. Do not use Docker container paths |
| Local stdio errors out or disconnects | Check whether `.env` points to `/app/...` or `/data/...` (those are container paths) |
| Frontend returns 502 | Confirm the backend is running on port 8000 |
| Protected interface returns 401 | Set `MCP_API_KEY` or enable `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` |
| Docker port conflict | `docker_one_click.sh` auto-picks free ports; you can also use `--frontend-port` / `--backend-port` |

For more troubleshooting, see [TROUBLESHOOTING_EN.md](TROUBLESHOOTING_EN.md).

---

## 9. Further Reading

| Document | Content |
|---|---|
| [DEPLOYMENT_PROFILES_EN.md](DEPLOYMENT_PROFILES_EN.md) | Deployment profiles A/B/C/D in detail |
| [TOOLS_EN.md](TOOLS_EN.md) | Full semantics of the 9 MCP tools |
| [TECHNICAL_OVERVIEW_EN.md](TECHNICAL_OVERVIEW_EN.md) | System architecture and data flow |
| [TROUBLESHOOTING_EN.md](TROUBLESHOOTING_EN.md) | Common troubleshooting |
| [SECURITY_AND_PRIVACY_EN.md](SECURITY_AND_PRIVACY_EN.md) | Security and privacy |
| [DASHBOARD_GUIDE_EN.md](DASHBOARD_GUIDE_EN.md) | Dashboard usage guide |
