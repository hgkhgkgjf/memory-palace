# GHCR Post-Pull User Acceptance Checklist

This checklist is for two situations:

- you want a quick post-release verification for yourself
- a user wants to confirm "did it really start correctly on my machine"

The default scope is **Profile B + GHCR prebuilt images** only.

---

## 1. Prerequisites

- Docker is installed
- the current directory contains:
  - `docker-compose.ghcr.yml`
  - `.env.example`
  - `scripts/apply_profile.sh` / `scripts/apply_profile.ps1`

---

## 2. Startup Commands

```bash
bash scripts/apply_profile.sh docker b .env.docker

docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

If you are using Windows PowerShell, follow the same idea with:

```powershell
.\scripts\apply_profile.ps1 -Platform docker -Profile b -Target .env.docker

docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

`apply_profile` creates `.env.docker` from the checked-in template and backs up an existing target before replacing it. Do not copy `.env.example` over `.env.docker` first.

---

## 3. Minimal Acceptance

### 3.1 Dashboard opens

Open:

- `http://localhost:3000`

Pass criteria:

- the page opens
- the language toggle is visible in the top-right corner
- the page may still show `Set API key`; that alone is not necessarily an error

### 3.2 Backend health is OK

```bash
curl -fsS http://127.0.0.1:18000/health
```

Pass criteria:

- returns JSON
- includes `"status": "ok"`

### 3.3 Docker setup assistant stays in guidance mode

```bash
curl -fsS http://127.0.0.1:3000/api/setup/status
```

Pass criteria:

- returns `200`
- includes:
  - `"running_in_docker": true`
  - `"apply_supported": false`
  - `"apply_reason": "docker_runtime_not_persisted"`

This confirms:

- the frontend proxy is working
- the backend setup route is working
- the assistant is not pretending that container `.env` changes can be persisted

### 3.4 SSE endpoint is reachable

```bash
curl -i http://127.0.0.1:3000/sse
```

Pass criteria:

- returns `200` or `401`

Interpretation:

- `200` means the current proxy + auth path already allows the request
- `401` is still useful: it means `/sse` is reachable and the remaining issue is auth, not routing

---

## 4. UI Behavior Acceptance

### 4.1 English / Chinese switching

Manual check:

- click the language toggle
- visible UI text switches
- refresh the page and confirm the selection is preserved

### 4.2 Protected requests are usable

Manual check:

- Memory / Review / Maintenance pages should not all fail into blank error states
- if the page only keeps showing `Set API key` while data still loads, that usually means the proxy holds the key but the browser page itself does not

---

## 5. The Most Common Misunderstanding

- the GHCR path solves **service startup**
- it does **not** automatically install local `skills / MCP / IDE host` integration on your machine
- if you also want `Claude / Codex / Gemini / OpenCode / Cursor / Antigravity` integration, continue with:
  - `docs/skills/README_EN.md`
  - `docs/skills/GETTING_STARTED_EN.md`

---

## 6. Stop Services

```bash
docker compose -f docker-compose.ghcr.yml down --remove-orphans
```

If you also want to clear the database and snapshots:

```bash
docker compose -f docker-compose.ghcr.yml down -v
```

---

## 7. Where to Look First If It Fails

Start with:

- `docs/GETTING_STARTED_EN.md`
- `docs/DEPLOYMENT_PROFILES_EN.md`
- `docs/SECURITY_AND_PRIVACY_EN.md`
- `docs/TROUBLESHOOTING_EN.md`
