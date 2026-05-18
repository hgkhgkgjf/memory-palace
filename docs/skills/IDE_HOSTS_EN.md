# Memory Palace IDE Hosts

For IDE-style hosts: `Cursor / Windsurf / VSCode-host / Antigravity`.

Their key difference from `Claude / Codex / Gemini / OpenCode` is not branding but integration surface:

- No stable public model API for external CLIs to reuse
- The right way to project Memory Palace into them is:
  - repo-local rules files
  - a local MCP config snippet
  - a small host-specific compatibility layer when needed

So the IDE-host primary path is no longer a hidden skill mirror. It is `AGENTS.md + MCP snippet + optional compatibility layer`.

---

## 1. Core Positioning

### Canonical source unchanged

```text
docs/skills/memory-palace/
```

Still serves CLI clients and the in-repo source of truth for skill design.

### IDE hosts integrate through two projections

- **Rules entry**: repo-root `AGENTS.md`
- **Execution entry**: local MCP config pointing at the repo-local launcher
  - Native Windows: `python backend/mcp_wrapper.py`
  - macOS / Linux: `bash scripts/run_memory_palace_mcp_stdio.sh`
- **Optional compatibility layer**: host-specific wrapper / workflow

### Local prerequisites

The repo-local path is one bundle:

- The rendered IDE host snippet assumes the host can run the matching wrapper
- The wrapper assumes `backend/.venv` is ready with backend dependencies
- The wrapper reads the current repository `.env` first to decide `DATABASE_URL`
- It refuses to start when `.env` is missing while `.env.docker` exists, or when `DATABASE_URL` points at `/app/...` / `/data/...` container paths

If you only have Docker / GHCR running and no local checkout runtime, **do not** use the stdio wrapper. Point the host at the exposed `/sse` endpoint instead.

---

## 2. Per Host

### Cursor

- Primarily consumes repo-local `AGENTS.md`
- Connects through the host's local stdio MCP settings surface
- Do not treat `.cursor/skills/memory-palace/` as the default primary path

### Windsurf

Same positioning as Cursor; requires the host to support local stdio MCP and workspace/project rules.

### VSCode-host

Means "a VS Code extension host with agent / MCP capabilities." Does not assume VS Code itself has a first-class skill system. As long as the extension supports local stdio MCP and repo-local project rules, it reuses the same `AGENTS.md + MCP snippet` path.

### Antigravity

Still in the IDE Host category and uses the same MCP integration path, but with one host-specific difference:

- **Prefer `AGENTS.md`**
- **Accept legacy `GEMINI.md`**

Optional workflow projection:

```text
docs/skills/memory-palace/variants/antigravity/global_workflows/memory-palace.md
```

This is an additional layer, not a different integration category.

---

## 3. Generating Config

Don't hand-write. Render directly:

```bash
python scripts/render_ide_host_config.py --host cursor
python scripts/render_ide_host_config.py --host windsurf
python scripts/render_ide_host_config.py --host vscode-host
python scripts/render_ide_host_config.py --host antigravity
```

The canonical flag is `vscode-host`; the script still accepts the legacy `--host vscode`.

Default output by platform:

- Native Windows: `python + backend/mcp_wrapper.py`
- macOS / Linux: `bash + scripts/run_memory_palace_mcp_stdio.sh`

For hosts with `stdin/stdout` or CRLF quirks, switch to the wrapper form:

```bash
python scripts/render_ide_host_config.py --host antigravity --launcher python-wrapper
```

If you explicitly request `python-wrapper` but `backend/.venv` is not ready, the script stops with an explicit error instead of silently falling back to system Python.

---

## 4. Validation

IDE hosts do not promise a repository-level "one-click live smoke." Use layered validation:

1. **Static contract checks**
   - `AGENTS.md` exists
   - Wrapper / workflow / canonical source exists
   - MCP command points at the current repository, and the launcher / args pair is executable

2. **Host connection checks**
   - The IDE can see the `memory-palace` MCP server
   - The IDE can list Memory Palace tools

3. **Manual smoke checklist**
   - `read_memory("system://boot")`
   - Create one `notes://ide_smoke_*`
   - Try a duplicate create and confirm guard blocks it

Each host needs one manual smoke run on the target machine before upgrading the claim from "static contract aligned" to "live-ready on that host."
