# GHCR Prebuilt Image Release Notes (2026-03-11)

This note records only the GHCR release capability that is **already implemented and verified**. It does not describe "things that should work in theory."

---

## 1. One-Sentence Conclusion

You can now pull prebuilt Memory Palace images directly from GitHub Container Registry and start the default **Profile B** with `docker compose`, avoiding local image build problems.

---

## 2. What Was Added

- A GHCR image publishing workflow
- `docker-compose.ghcr.yml`
- Compose-project-scoped default volume names
- Correct one-click script output for real reachable ports under port-conflict scenarios
- Documentation now splits the paths into:
  - user path: `docker-compose.ghcr.yml`
  - maintainer / local build path: `docker_one_click.sh/.ps1`

---

## 3. Who Should Use This Path First

This is the best fit for users who:

- can run Docker locally, but keep failing on local image builds
- only want to get Dashboard / API / SSE running first
- do not want to debug local Node / Python / buildx / Dockerfile issues up front

If your goal is "make it usable first," start with GHCR.

---

## 4. What Is Publicly Verified Right Now

This public claim only covers:

- default **Profile B**
- Dashboard reachable
- Backend API reachable
- SSE reachable
- Docker volumes isolated per compose project by default
- the first-run setup assistant staying in guidance mode under Docker instead of pretending it can persist container `.env`

This release does **not** claim full GHCR-path validation for:

- `Profile C / D` under real external model services
- native Windows / native `pwsh` end-to-end final verification
- automatic `skills / MCP / IDE host` installation

---

## 5. The Most Important Boundary

### 5.1 What This Path Solves

It solves:

- **service startup**
- meaning `Dashboard / API / SSE`

### 5.2 What This Path Does Not Auto-configure

It does not automatically set up:

- local `Claude / Codex / Gemini / OpenCode` skill installation
- IDE host integration through repo-local `AGENTS.md + MCP snippet`
- local client configuration rewrites on your machine

In other words:

- Docker starts the service side
- client integration is still a host-side configuration problem

---

## 6. Shortest User Path

```bash
git clone https://github.com/AGI-is-going-to-arrive/Memory-Palace.git
cd Memory-Palace

bash scripts/apply_profile.sh docker b .env.docker

docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

Default access addresses:

- Dashboard: `http://localhost:3000`
- Backend API: `http://localhost:18000`
- SSE: `http://localhost:3000/sse`

> Note: this GHCR compose path does **not** auto-adjust ports. If `3000` / `18000` are already occupied, set `MEMORY_PALACE_FRONTEND_PORT` / `MEMORY_PALACE_BACKEND_PORT` first.

---

## 7. What If You Also Want Client Integration

There are two different paths:

### Path A: You only want to connect MCP manually

If your client supports remote SSE MCP, configure it manually against:

- `http://localhost:3000/sse`

with the matching API key / auth header.

### Path B: You want to reuse the repo's existing skill + MCP automation

Keep the current repository checkout and continue with:

- `docs/skills/GETTING_STARTED_EN.md`
- `docs/skills/SKILLS_QUICKSTART_EN.md`

That remains a **repo-local installation path**, not a Docker auto-install path.

---

## 8. Related Documents

- `docs/GETTING_STARTED_EN.md`
- `docs/DEPLOYMENT_PROFILES_EN.md`
- `docs/SECURITY_AND_PRIVACY_EN.md`
- `docs/skills/README_EN.md`
- `docs/skills/GETTING_STARTED_EN.md`
