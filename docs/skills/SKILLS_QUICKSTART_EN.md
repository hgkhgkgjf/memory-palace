# Memory Palace Skills Quick Start

For users who want to wire `Claude / Codex / Gemini / OpenCode` into this repository as quickly as possible.

If you only want to run `Dashboard / API / SSE`, see `docs/GHCR_QUICKSTART_EN.md`. This page is not required.

If you want AI to guide installation step by step, install [`memory-palace-setup`](https://github.com/AGI-is-going-to-arrive/memory-palace-setup) in your client and say:

```text
Use $memory-palace-setup to install and configure Memory Palace step by step.
Prefer skills + MCP.
```

---

## 1. Two Layers

| Layer | Role |
|---|---|
| skill | Decides "when to enter the Memory Palace workflow" |
| MCP | Decides "actually calling tools like `read_memory / search_memory / update_memory`" |

You need both for it to truly work.

<p align="center">
  <img src="../images/skill_vs_mcp.png" width="800" alt="Skill vs MCP" />
</p>

---

## 2. One Command for the Main Path

On a new machine, prefer the unified user-scope install:

```bash
python scripts/install_skill.py \
  --targets claude,codex,gemini,opencode \
  --scope user --with-mcp --force
```

After that, your home directory typically contains:

- `~/.claude/skills/memory-palace/` and an `mcpServers.memory-palace` block in `~/.claude.json` pointing at this repo
- `~/.codex/config.toml`
- `~/.gemini/skills/memory-palace/SKILL.md`, `~/.gemini/settings.json`, `~/.gemini/policies/memory-palace-overrides.toml`
- `~/.config/opencode/opencode.json`

If you also want a project-level entry in the current repository, additionally run:

```bash
python scripts/install_skill.py \
  --targets claude,gemini \
  --scope workspace --with-mcp --force
```

The workspace will get `.claude/skills/memory-palace/`, `.mcp.json`, `.gemini/skills/memory-palace/`, `.gemini/settings.json`, `.gemini/policies/memory-palace-overrides.toml`.

> The public repository only ships the canonical bundle (`docs/skills/memory-palace/`). `.claude / .codex / .gemini / .opencode` mirrors and `.mcp.json` are local artifacts generated after install.

---

## 3. Platform Branches

The repo-local MCP launcher selects automatically by host:

- Native Windows -> `python backend/mcp_wrapper.py`
- macOS / Linux / `Git Bash` / `WSL` / MSYS / Cygwin -> `bash scripts/run_memory_palace_mcp_stdio.sh`

Both `install_skill.py` and `render_ide_host_config.py` pick the right one automatically.

Both wrappers reuse the `DATABASE_URL` from the current repository's `.env`. If `.env` points at `/app/...` or `/data/...` container paths, the wrapper refuses to start - use a host absolute path or go back to Docker `/sse`.

---

## 4. Per-CLI Boundaries

| Client | repo-local skill | MCP main path |
|---|---|---|
| `Claude Code` | Auto-discovered after sync | `~/.claude.json` or `.mcp.json` |
| `Gemini CLI` | Auto-discovered after sync | `~/.gemini/settings.json` or `.gemini/settings.json` |
| `Codex CLI` | Auto-discovered after sync | `~/.codex/config.toml` (user-scope) |
| `OpenCode` | Auto-discovered after sync | `~/.config/opencode/opencode.json` (user-scope) |

For `Codex / OpenCode`, workspace scope does not write a stable MCP binding. User-scope is their primary path.

### Client self-check

```bash
claude mcp list
gemini mcp list
codex mcp list
opencode mcp list
```

Seeing `memory-palace connected` / a project block for the current repo means it is wired.

---

## 5. Manual Fallback: Add MCP Directly

Only use this when `install_skill.py` fails for a specific client:

```bash
# Codex - native Windows
codex mcp add memory-palace -- python C:\ABS\PATH\TO\REPO\backend\mcp_wrapper.py

# Codex - macOS / Linux / Git Bash / WSL
codex mcp add memory-palace \
  -- /bin/zsh -lc 'cd /ABS/PATH/TO/REPO && bash scripts/run_memory_palace_mcp_stdio.sh'
```

```bash
# Gemini - native Windows
gemini mcp add -s project memory-palace python <repo-root>\backend\mcp_wrapper.py

# Gemini - macOS / Linux / Git Bash / WSL
gemini mcp add -s project memory-palace \
  /bin/zsh -lc 'cd <repo-root> && bash scripts/run_memory_palace_mcp_stdio.sh'
```

For OpenCode, add a `local / stdio` server in its own MCP management UI with the same command/args.

> Replace `<repo-root>` / `/ABS/PATH/TO/REPO` with your real repo root.
>
> These fallback commands write into the client's user-scope config.

---

## 6. IDE Hosts

`Cursor / Windsurf / VSCode-host / Antigravity` use a different integration path:

- Rules entry: repo-root `AGENTS.md`
- MCP entry: `python scripts/render_ide_host_config.py --host <cursor|windsurf|vscode-host|antigravity>`

Do not treat them as hidden-skill-mirror consumers. See `IDE_HOSTS_EN.md`.

---

## 7. Verification

```bash
# Skill mirror drift check
python scripts/sync_memory_palace_skill.py --check

# Multi-client skill trigger smoke
python scripts/evaluate_memory_palace_skill.py

# Real MCP call e2e
cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py
```

These three generate local reports under `docs/skills/` (`TRIGGER_SMOKE_REPORT.md` / `MCP_LIVE_E2E_REPORT.md`). They are gitignored by default and exist for local review. Check the content before forwarding - they may include local paths.

For isolated report output, set `MEMORY_PALACE_SKILL_REPORT_PATH` / `MEMORY_PALACE_MCP_E2E_REPORT_PATH`; relative paths are redirected under the system temp directory's `memory-palace-reports/`, while absolute paths outside the repository give you a fixed location. Treat `PARTIAL` as a host boundary that needs targeted follow-up, especially for Codex/OpenCode user-scope MCP binding.

### Trigger self-check

Positive prompt:

```text
Read from system://boot first, then help me check for recent memories regarding deployment preferences.
```

Expected: `read_memory("system://boot")` -> `search_memory(..., include_session=true)`.

Negative prompt:

```text
Rewrite the introductory paragraph of the README for me.
```

Should NOT trigger the Memory Palace workflow.

---

## 8. Common Misconceptions

- **Skill file present means it works**: You also need MCP wired.
- **Only MCP configured**: Tools are callable but the client may not auto-enter the workflow.
- **Codex / OpenCode don't need MCP**: repo-local auto-discovery is not the same as MCP binding; user-scope registration is still required.
- **Reading hidden paths directly**: Some clients block `.gemini/skills/` and similar. Always reference `docs/skills/memory-palace/...` for file paths.

---

## 9. What to Read Next

- `CLI_COMPATIBILITY_GUIDE_EN.md` - Full per-CLI options and boundaries
- `IDE_HOSTS_EN.md` - Integration for Cursor / Windsurf / VSCode-host / Antigravity
- `docs/skills/memory-palace/SKILL.md` - The actual skill body the model reads
