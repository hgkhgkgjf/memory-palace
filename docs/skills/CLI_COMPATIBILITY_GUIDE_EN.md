# Memory Palace CLI Compatibility Guide

Differences, options, and boundaries for connecting `Claude Code / Gemini CLI / Codex CLI / OpenCode` to Memory Palace.

For the fastest path, see [`SKILLS_QUICKSTART_EN.md`](SKILLS_QUICKSTART_EN.md) first. This document covers the full per-CLI options and edge cases.

---

## 1. Two-Layer Structure

| Layer | Decides |
|---|---|
| skill | Whether the client enters the Memory Palace workflow |
| MCP | Whether the client actually calls this repository's backend |

You need both to call it "ready."

### Repo-local launcher

The repo-local MCP launcher picks one of two paths by host:

- Native Windows: `backend/mcp_wrapper.py`
- macOS / Linux / `Git Bash` / `WSL` / MSYS / Cygwin: `scripts/run_memory_palace_mcp_stdio.sh`

`install_skill.py`, `render_ide_host_config.py`, and `evaluate_memory_palace_mcp_e2e.py` all generate config from the same rule.

Wrapper behavior:

- Prioritizes `DATABASE_URL` from the current repository's `.env`
- Treats an empty-string `DATABASE_URL` from the client as "unset"
- Refuses to start when `.env` points at `/app/...` or `/data/...` container paths
- The shell wrapper also merges `localhost / 127.0.0.1 / ::1 / host.docker.internal` into `NO_PROXY`

As long as you don't manually mess up client commands, Dashboard, HTTP API, and MCP all connect to the same database by default.

---

## 2. Recommended Commands

### Sync skill mirrors

```bash
python scripts/sync_memory_palace_skill.py
python scripts/sync_memory_palace_skill.py --check
```

### User-scope install (recommended default)

```bash
python scripts/install_skill.py \
  --targets claude,codex,gemini,opencode \
  --scope user --with-mcp --force
```

### Workspace install (optional, for project-level entries)

```bash
python scripts/install_skill.py \
  --targets claude,gemini \
  --scope workspace --with-mcp --force
```

`Codex / OpenCode` do not get a stable MCP binding under workspace scope; user-scope is their primary path.

### Installation chain check

```bash
python scripts/install_skill.py \
  --targets claude,codex,gemini,opencode \
  --scope user --with-mcp --check
```

---

## 3. What Appears After Install

| Client | Workspace mirrors | User-scope entries |
|---|---|---|
| `Claude Code` | `.claude/skills/memory-palace/` + `.mcp.json` | `~/.claude/skills/memory-palace/` + the current-repo project block in `~/.claude.json` |
| `Codex CLI` | `.codex/skills/memory-palace/` | `~/.codex/config.toml` |
| `Gemini CLI` | `.gemini/skills/memory-palace/` + `.gemini/settings.json` + `.gemini/policies/memory-palace-overrides.toml` | `~/.gemini/skills/memory-palace/SKILL.md` + `~/.gemini/settings.json` + `~/.gemini/policies/memory-palace-overrides.toml` |
| `OpenCode` | `.opencode/skills/memory-palace/` | `~/.config/opencode/opencode.json` |

The canonical source of truth is always `docs/skills/memory-palace/`. Everything else is a local artifact generated after install.

### install_skill.py details

- Leaves a `*.bak` in place before overwriting (`.mcp.json.bak` / `settings.json.bak` / `config.toml.bak` / `memory-palace-overrides.toml.bak`)
- Reports the specific file path and line/column when JSON config is broken
- Retries `replace` / promote / rollback on Windows when files are briefly locked
- Omitting `--targets` defaults to `claude,codex,opencode`; add `gemini` explicitly when needed

---

## 4. Per-CLI Integration

### Claude Code

- Auto-discovery: `.claude/skills/memory-palace/`
- MCP: workspace via `.mcp.json`; user-scope writes to the current-repo project block in `~/.claude.json`
- Recommended default: `--scope user --with-mcp`; add workspace install if you also want a project-level entry

### Gemini CLI

- Auto-discovery: `.gemini/skills/memory-palace/`
- MCP: workspace via `.gemini/settings.json`; user-scope via `~/.gemini/settings.json`
- Policy: `memory-palace-overrides.toml` avoids deprecated `__` MCP tool syntax warnings
- On `Policy file warning`, rerun `--scope user --with-mcp --force`
- `Skill conflict detected ... overriding ...` usually means workspace skill overrides the older user-level version (not a problem)

### Codex CLI

- Auto-discovery: `.codex/skills/memory-palace/`
- MCP: primary path is `~/.codex/config.toml`; do not assume "out-of-the-box after sync"
- Prefer `python scripts/install_skill.py --targets codex --scope user --with-mcp --force`
- Manual fallback:

```bash
# native Windows
codex mcp add memory-palace -- python C:\ABS\PATH\TO\REPO\backend\mcp_wrapper.py

# macOS / Linux / Git Bash / WSL
codex mcp add memory-palace \
  -- /bin/zsh -lc 'cd /ABS/PATH/TO/REPO && bash scripts/run_memory_palace_mcp_stdio.sh'
```

### OpenCode

- Auto-discovery: `.opencode/skills/memory-palace/`
- MCP: primary path is `~/.config/opencode/opencode.json`
- Prefer `python scripts/install_skill.py --targets opencode --scope user --with-mcp --force`
- Manual fallback: add a `local / stdio` server in OpenCode's MCP management UI with:

```text
# native Windows
name: memory-palace
type: local / stdio
command: python
args:
  - <repo-root>\backend\mcp_wrapper.py
```

```text
# macOS / Linux / Git Bash / WSL
name: memory-palace
type: local / stdio
command: /bin/zsh
args:
  - -lc
  - cd <repo-root> && bash scripts/run_memory_palace_mcp_stdio.sh
```

---

## 5. IDE Hosts

`Cursor / Windsurf / VSCode-host / Antigravity` no longer use hidden skill mirrors. Unified path:

- Rules entry: repo-root `AGENTS.md`
- Execution entry: local MCP config pointing at the repo-local launcher

Don't hand-write. Render directly:

```bash
python scripts/render_ide_host_config.py --host cursor
python scripts/render_ide_host_config.py --host windsurf
python scripts/render_ide_host_config.py --host vscode-host
python scripts/render_ide_host_config.py --host antigravity
```

For hosts with `stdin/stdout` or CRLF quirks:

```bash
python scripts/render_ide_host_config.py --host antigravity --launcher python-wrapper
```

See [`IDE_HOSTS_EN.md`](IDE_HOSTS_EN.md).

---

## 6. Minimal Validation Chain

```bash
# Installation chain check
python scripts/install_skill.py \
  --targets claude,codex,gemini,opencode \
  --scope user --with-mcp --check

# Trigger smoke
python scripts/evaluate_memory_palace_skill.py

# Real MCP e2e
cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py
```

The latter two generate local reports `docs/skills/TRIGGER_SMOKE_REPORT.md` and `docs/skills/MCP_LIVE_E2E_REPORT.md` (gitignored by default).

Environment variables:

- `MEMORY_PALACE_SKILL_REPORT_PATH` / `MEMORY_PALACE_MCP_E2E_REPORT_PATH` - Override default output paths. Relative paths land under the system temp directory's `memory-palace-reports/`; absolute paths outside the repo give you full control
- `MEMORY_PALACE_ENABLE_GEMINI_LIVE=1` - Explicitly enable Gemini live `create/update/guard` against a real database
- `MEMORY_PALACE_SKIP_GEMINI_LIVE=1` - Explicitly skip Gemini live

Review reports before forwarding - they may contain local paths or client config traces.

---

## 7. Positive / Negative Prompts

Positive prompt:

```text
For this repository's memory-palace skill, answer with exactly three bullets:
(1) the first memory tool call,
(2) what to do when guard_action=NOOP,
(3) the path to the trigger sample file.
```

Expected hits:

- `read_memory("system://boot")`
- `NOOP = stop + inspect guard_target_uri / guard_target_id`
- `docs/skills/memory-palace/references/trigger-samples.md`

When the prompt already names a URI, the skill should go straight to `read_memory(uri)` instead of bouncing through `search_memory(...)`.

Negative prompt:

```text
Please help me change the text at the beginning of the README; no need to touch Memory Palace.
```

Should not trigger `memory-palace`.

---

## 8. One-Line Summary

- `Claude / Gemini`: After sync, you get repo-local skill auto-discovery + workspace MCP direct connection
- `Codex / OpenCode`: After sync, you get repo-local skill auto-discovery, but MCP still primarily uses user-scope registration
- `IDE Hosts`: Use `AGENTS.md + MCP snippet`, not hidden skill mirrors
