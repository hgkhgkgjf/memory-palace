# Memory Palace CLI Compatibility Guide

## Summary

- `Claude Code`: After completing `sync/install`, you get **repo-local skill auto-discovery** + **workspace MCP direct connection**.
- `Gemini CLI`: After completing `sync/install`, you get **repo-local skill auto-discovery** + **workspace MCP direct connection**.
- `Codex CLI`: After completing `sync`, you get **repo-local skill auto-discovery**; `MCP` still primarily uses **user-scope registration**.
- `OpenCode`: After completing `sync`, you get **repo-local skill auto-discovery**; `MCP` still primarily uses **user-scope registration**.
- `IDE Hosts` (`Cursor / Windsurf / VSCode-host / Antigravity`): the primary path is now **repo-local `AGENTS.md` + MCP snippet**, not hidden skill mirrors.
- The current design is aligned with the core requirements of `Anthropic skill-creator`: `frontmatter`, `trigger description`, `references`, and `eval/smoke`.

One clarification first:

- If you only start the service through GHCR / Docker, `Dashboard / API / SSE` can already work.
- That does **not** mean local `Claude / Codex / Gemini / OpenCode / IDE host` integrations are automatically configured.
- This compatibility guide describes the **client integration layer**.

If you choose not to use the repo-local skill install path and only want to connect a client manually to Docker's `/sse` endpoint:

- the repository already provides the **generic SSE MCP skeleton**
- but client-specific field names, GUI entry points, and auth-entry steps are not perfectly identical across products
- so this guide does not guess each product's UI; it stays within the repository boundary of:
  - service address
  - auth method
  - generic JSON structure

The current public repository stance for manual remote `/sse` connection is:

- `Claude Code`: safe to document directly
- `Gemini CLI`: safe to document directly
- `Codex CLI`: stay conservative for now; prefer the repo-local stdio path
- `OpenCode`: stay conservative for now; prefer the repo-local path

The concrete manual examples now live in:

- `6.3.1 ~ 6.3.4` of `docs/GETTING_STARTED_EN.md`

## Interaction Tier Recommendation (2026-04 Public Verification)

- `Profile B` remains the recommended default for CLI / IDE day-to-day memory
  recall.
- `Profile C` / `Profile D` are now described explicitly as **deep retrieval
  tiers**. Enable them only when you intentionally want higher recall and
  ranking quality.
- In this verification round, the repo-local launcher rule is now aligned across the same three paths: `install_skill.py`, `render_ide_host_config.py`, and `evaluate_memory_palace_mcp_e2e.py` all pick from the same boundary:
  - Native Windows: `backend/mcp_wrapper.py`
  - macOS / Linux / `Git Bash` / `WSL` / MSYS / Cygwin:
    `scripts/run_memory_palace_mcp_stdio.sh`
- This guide keeps only public-safe conclusions. It does not write local
  benchmark endpoints, API keys, or model IDs into the repository.

## Reflection And C/D Config Boundary

- The public `reflection workflow` surface is now described as `prepare ->
  execute -> rollback`; when you actually need rollback, follow the rollback
  endpoint returned by the current result instead of assuming a hidden
  auto-undo path.
- The public `Profile C/D` templates no longer publish a guessed embedding
  dimension. `RETRIEVAL_EMBEDDING_DIM` must be filled with the provider's real
  vector dimension by the user.
- This guide stays public-safe. It does not freeze local benchmark endpoints,
  API keys, or model IDs into repository docs.

## Distinguish the Two Layers

The `memory-palace` link is divided into two layers:

1. **Skill Auto-discovery**
   - Responsible for letting the client know "when to enter the Memory Palace workflow."
   - Mainly determined by the `frontmatter + description` in `SKILL.md`.

2. **MCP Workspace Binding**
   - Responsible for letting the client actually call the `Memory-Palace` backend in the current repository.
   - Just discovering the skill is not enough; you must confirm that the MCP points to the current project.

One more thing to avoid pitfalls:

- This wrapper prioritizes reusing the `DATABASE_URL` from the current repository's `.env`.
- If a client passes `DATABASE_URL` as an empty string, it still treats that as “not set” and continues to use the valid value from the current repository `.env`.
- If that `.env` still points to Docker `/app/...` or `/data/...` container paths after normalizing common slash and case variants, the wrapper also refuses to start on purpose.
- In other words, as long as you don't manually mess up the client commands, the Dashboard / HTTP API / MCP will default to the same database.

Call it **truly configured** only when both checks are true:

1. The current CLI can actually discover the `memory-palace` skill in its repo-local or user-scope location.
2. The current CLI's MCP binding resolves to this checkout's repo-local launcher rather than a stale path from another repository.
   - Native Windows: `backend/mcp_wrapper.py`
   - macOS / Linux / `Git Bash` / `WSL` / MSYS / Cygwin: `scripts/run_memory_palace_mcp_stdio.sh`

## Current Local Baseline After Sync / Install

After executing `sync_memory_palace_skill.py` / `install_skill.py`, these entry points usually appear:

- `Claude Code`
  - `.claude/skills/memory-palace/`
  - `.mcp.json`
- `Codex CLI`
  - `.codex/skills/memory-palace/`
- `OpenCode`
  - `.opencode/skills/memory-palace/`
- `Gemini CLI`
  - `.gemini/skills/memory-palace/`
  - `.gemini/settings.json`
  - `.gemini/policies/memory-palace-overrides.toml`

The canonical skill source of truth is:

```text
docs/skills/memory-palace/
```

> Note: `docs/skills/memory-palace/` is a publicly existing path in the repository; `.claude/.codex/.gemini/.opencode/...`, `.mcp.json`, etc., are local artifacts generated after installation.
>
> **Windows Prerequisite Note**:
>
> - The repo-local MCP launch path is now split in two.
> - Native Windows now defaults to `backend/mcp_wrapper.py`.
> - On Windows, `install_skill.py` now writes that native path for Claude / Codex / Gemini / OpenCode.
> - `Git Bash` / `WSL` / MSYS / Cygwin are still valid, but only when you intentionally follow the POSIX `bash` wrapper route.
> - In other words, launcher selection is now based on the actual host boundary, not just "am I somewhere on Windows": native Windows gets `backend/mcp_wrapper.py`, while `Git Bash` / `WSL` / MSYS / Cygwin stay on `scripts/run_memory_palace_mcp_stdio.sh`.
> - The same split now applies when you install CLI bindings, render IDE-host snippets, or run the repo-local MCP e2e check.
> - So on native Windows, do not start by copying the `/bin/zsh` / `bash` examples. First inspect the command that the script actually generated.
> - If you use `pwsh-in-docker`, `docker_one_click.ps1` now falls back to `ss` when `Get-NetTCPConnection` is unavailable; if the environment has neither, specify ports explicitly or re-run on the target Windows host.
> - These repo-local launchers still prioritize the `DATABASE_URL` from the current repository's `.env`, preventing you from accidentally connecting to a second SQLite database on the client side.

## What install_skill.py is Responsible For

Currently, `install_skill.py` supports two types of actions:

- **Install Skill**
  - Distributes the canonical bundle to the workspace or user skill directory.
  - If the target is `gemini`, it also installs `memory-palace-overrides.toml` to avoid deprecated `__` MCP tool syntax warnings.
- **Install MCP**
  - Binds the corresponding CLI's MCP configuration to the current repository via `--with-mcp`.

It also supports:

- `--check`
  - Checks if the skill is consistent with the canonical version.
  - If `--with-mcp` is also passed, it checks if the MCP binding is in place.

One more practical boundary:

- If you omit `--targets`, the current default is the CLI-only set: `claude,codex,opencode`
- `gemini` is still recommended, but you should add it explicitly in the command
- IDE-host compatibility projections are no longer part of the default target set

There are two behaviors directly related to "avoiding pitfalls":

- If the script is about to overwrite an existing configuration, it will first leave a `*.bak` file in the original directory.
- If a config file or skill directory on Windows is only locked briefly, `install_skill.py` now also gives the final `replace` / promote / rollback step a small bounded retry, so the install is less likely to stop in a half-swapped state.
  - Common filenames look like: `.mcp.json.bak`, `settings.json.bak`, `config.toml.bak`, `memory-palace-overrides.toml.bak`.
- If a JSON configuration is already manually broken, the script will directly report the bad file path and line/column number, making it easy for you to fix the file before rerunning.

## Recommended Commands

If you want one default install path that works predictably across `Claude / Codex / Gemini / OpenCode`, prefer this first:

```bash
python scripts/install_skill.py \
  --targets claude,codex,gemini,opencode \
  --scope user \
  --with-mcp \
  --force
```

Workspace install remains an optional extra for `Claude/Gemini` when you also want repo-local project-level entries in the current repository.

### 1) Sync repo-local mirrors first

```bash
python scripts/sync_memory_palace_skill.py
python scripts/sync_memory_palace_skill.py --check
```

### 2) Enable direct workspace connection for the current repository

This step will:

- Bind `Claude Code` to `.mcp.json`.
- Bind `Gemini CLI` to `.gemini/settings.json`.
- Add `.gemini/policies/memory-palace-overrides.toml` for `Gemini CLI`.

```bash
python scripts/install_skill.py \
  --targets claude,gemini \
  --scope workspace \
  --with-mcp \
  --force
```

Check:

```bash
python scripts/install_skill.py \
  --targets claude,gemini \
  --scope workspace \
  --with-mcp \
  --check
```

If this `claude,gemini` `workspace --with-mcp --check` path passes, you can read it as: the current repository's workspace-level skill + MCP entrypoints are aligned. This does not change the public boundary for `Codex/OpenCode`: they still stay on the user-scope MCP path by default.

For workspace-local MCP, `install_skill.py` only manages stable repo-local bindings for `Claude Code` and `Gemini CLI`. Keep `Codex/OpenCode` on the user-scope MCP path.

If `workspace --check` has passed, but `user --check` is still reporting `SKILL FAIL / mismatch`, first suspect that old mirrors or old MCP configurations remain in your home directory. Usually, rerunning the same `--scope user --with-mcp --force` is enough; the script will now generate `*.bak` first and won't silently overwrite the original files.

Note:

- `Codex/OpenCode` will complete the repo-local skill mirror.
- However, `Codex/OpenCode` MCP will not automatically drop project configurations under the workspace scope.
- This is an **explicit boundary** in the current documentation, not an omission.
- If you are configuring `Codex/OpenCode` for the first time on a new machine, prioritize running `python scripts/install_skill.py --targets codex,opencode --scope user --with-mcp --force`; manual `codex mcp add` / GUI registration is better suited as a fallback troubleshooting method.

### 3) Enable user-scope MCP registration

This step is mainly for:

- `Codex CLI`
- `OpenCode`
- And `Claude/Gemini` if cross-repository reuse is needed.

```bash
python scripts/install_skill.py \
  --targets claude,codex,gemini,opencode \
  --scope user \
  --with-mcp \
  --force
```

Check:

```bash
python scripts/install_skill.py \
  --targets claude,codex,gemini,opencode \
  --scope user \
  --with-mcp \
  --check
```

## Per-CLI Strategy

### Claude Code

- Auto-discovery Layer:
  - repo-local `.claude/skills/memory-palace/`
- MCP Layer:
  - Workspace uses `.mcp.json`.
  - User-scope can write to the `~/.claude.json` current repository project block.

Conclusion:

- **The more stable default is still to start with `--scope user --with-mcp`.**
- If you also want a project-level entry in this repository, add a workspace install afterward.

### Gemini CLI

- Auto-discovery Layer:
  - repo-local `.gemini/skills/memory-palace/`
- MCP Layer:
  - Workspace uses `.gemini/settings.json`.
  - User-scope uses `~/.gemini/settings.json`.
- Policy Layer:
  - Workspace uses `.gemini/policies/memory-palace-overrides.toml`.
  - User-scope uses `~/.gemini/policies/memory-palace-overrides.toml`.

Conclusion:

- **The more stable default is still to start with `--scope user --with-mcp`.**
- If you also want a workspace entry in this repository, add a workspace install afterward.
- If you see `Policy file warning in memory-palace-overrides.toml`, rerun the same `--scope user --with-mcp --force` install first.
- When documenting it for others, the safer wording is: "regular `gemini` smoke passed in this session on the audited machine, while `gemini_live` remains an explicit opt-in path and stays `SKIP` by default."

### Codex CLI

- Auto-discovery Layer:
  - repo-local `.codex/skills/memory-palace/`
- MCP Layer:
  - Currently primarily uses `~/.codex/config.toml`.

Conclusion:

- **Do not describe Codex as "natively out-of-the-box."**
- The accurate statement is:
  - Skill can be auto-discovered repo-locally.
  - MCP is still recommended to be registered to the current repository via `--scope user --with-mcp`.
- The safer public wording for `Codex` is: the skill is still repo-locally auto-discoverable, MCP is still recommended through `--scope user --with-mcp`, and this session's repo-local smoke passed on the audited machine. Keep that as a machine-scoped verification result rather than a blanket all-host guarantee.

### OpenCode

- Auto-discovery Layer:
  - repo-local `.opencode/skills/memory-palace/`
- MCP Layer:
  - Currently primarily uses `~/.config/opencode/opencode.json`.

Conclusion:

- **Do not describe OpenCode as "natively out-of-the-box."**
- The accurate statement is:
  - Skill can be auto-discovered repo-locally.
  - MCP is still recommended to be registered to the current repository via `--scope user --with-mcp`.

## IDE Hosts

`Cursor / Windsurf / VSCode-host / Antigravity` are now treated as **IDE Hosts**, instead of being modeled as direct hidden-skill-mirror consumers.

Unified stance:

- **skill projection entry**: repo-root `AGENTS.md`
- **execution entry**: local MCP config pointing at the current repository's repo-local launcher
  - native Windows defaults to `backend/mcp_wrapper.py`
  - macOS / Linux / `Git Bash` / `WSL` / MSYS / Cygwin default to `scripts/run_memory_palace_mcp_stdio.sh`
- **host differences**: handled as small compatibility layers when needed, instead of maintaining full live-smoke workflows per IDE

In practice:

- `Cursor / Windsurf / VSCode-host`
  - use the same `AGENTS.md + MCP snippet` path
  - only when the host or extension supports local stdio MCP and workspace/project rules
- `Antigravity`
  - still belongs to the IDE Host category
  - but its rule discovery should be documented as: **prefer `AGENTS.md`, while keeping `GEMINI.md` as a legacy fallback**
  - and it may additionally project a workflow at:
    `docs/skills/memory-palace/variants/antigravity/global_workflows/memory-palace.md`

Do not hand-write these snippets. Render them directly:

```bash
python scripts/render_ide_host_config.py --host cursor
python scripts/render_ide_host_config.py --host windsurf
python scripts/render_ide_host_config.py --host vscode-host
python scripts/render_ide_host_config.py --host antigravity
```

Use `vscode-host` as the canonical flag for the documented `VSCode-host` IDE host. The script still accepts legacy `--host vscode` for backward compatibility, but this does not expand the tool beyond IDE hosts.

If a host has `stdin/stdout` or CRLF quirks, switch to the wrapper form:

```bash
python scripts/render_ide_host_config.py --host antigravity --launcher python-wrapper
```

See also:

- `IDE_HOSTS_EN.md`

## Minimal Validation Chain

### Installation Check

```bash
python scripts/install_skill.py \
  --targets claude,gemini \
  --scope workspace \
  --with-mcp \
  --check

python scripts/install_skill.py \
  --targets claude,codex,gemini,opencode \
  --scope user \
  --with-mcp \
  --check
```

### Trigger Smoke

```bash
python scripts/evaluate_memory_palace_skill.py
```

Local output:

```text
docs/skills/TRIGGER_SMOKE_REPORT.md
```

If this file is temporarily missing from a newly cloned GitHub repository, it is normal; it is a local verification summary generated after running.
If you plan to forward it to others, read the content yourself first; these
local reports might include paths on your machine, client configuration paths,
or other environment traces. `evaluate_memory_palace_skill.py` now returns a
non-zero exit code whenever any check is `FAIL`; `SKIP` / `PARTIAL` /
`MANUAL` do not fail the process by themselves. If `codex exec` does not emit
structured output before the smoke timeout, the `codex` item is reported as
`PARTIAL` instead of stalling the whole run.
If you do not want to overwrite the default file during parallel review or CI, set `MEMORY_PALACE_SKILL_REPORT_PATH` first. When you use a relative path, the script now redirects it under the system temp directory's `memory-palace-reports/` root; if you want a fully controlled destination, prefer an absolute path outside the repository.
`gemini_live` is now **explicitly opt-in**: the script only attempts that real-database `create/update/guard` round when you set `MEMORY_PALACE_ENABLE_GEMINI_LIVE=1`, and it may still leave `notes://gemini_suite_*` test memories. For a normal smoke test, keep the default or explicitly set `MEMORY_PALACE_SKIP_GEMINI_LIVE=1`.
Even when you opt in, that live round can still stop at `PARTIAL` if it hits a shared real database or a neighboring Gemini live session mutates the same note first; treat that as a live-host verification limit before assuming the isolated mainline skill/MCP path is broken.
If the current machine simply does not have the `Antigravity` host runtime, treat that item as "manual verification on the target host still pending" rather than a repository-mainline failure.
If the only remaining failed item is `mcp_bindings`, do not assume the repository is broken first. A more common cause is that your local user-scope MCP entries have not yet been synchronized to the current checkout. Rerun:

```bash
python scripts/install_skill.py --targets claude,codex,gemini,opencode --scope user --with-mcp --force
python scripts/evaluate_memory_palace_skill.py
```

### Real MCP E2E

```bash
cd backend
python ../scripts/evaluate_memory_palace_mcp_e2e.py
```

Local output:

```text
docs/skills/MCP_LIVE_E2E_REPORT.md
```

These two reports are mainly used for supplemental verification and are not intended as primary entry documentation. They are local products that "appear only after running" by default, so it's normal if they aren't in the public GitHub repository.
If you do not want to overwrite the default file during parallel review or CI, set `MEMORY_PALACE_MCP_E2E_REPORT_PATH` first. When you use a relative path, the script now redirects it under the system temp directory's `memory-palace-reports/` root; if you want a fully controlled destination, prefer an absolute path outside the repository.
`MCP_LIVE_E2E_REPORT.md` defaults to using an isolated temporary database and won't touch your official database; however, upon failure, it might still include stderr, logs, or temporary directory paths in the report, so it's also recommended to review the content yourself before forwarding.
This live e2e now follows the same repo-local wrapper path that users actually connect to, and its launcher rule is aligned with `install_skill.py` and `render_ide_host_config.py`: native Windows uses `backend/mcp_wrapper.py`, while macOS / Linux / `Git Bash` / `WSL` / MSYS / Cygwin use `scripts/run_memory_palace_mcp_stdio.sh`. It also covers wrapper behavior and `compact_context` gist persistence instead of only checking the bare tool inventory. In this 2026-05-15 review session, backend tests were `1382 passed, 22 skipped`, frontend tests were `203 passed`, and frontend build/typecheck, i18n audit, bundle budget, repo-local live MCP e2e, and focused Docker/profile/SSE/script contracts passed. Native Windows and native Linux host-runtime paths still keep explicit target-environment recheck boundaries.

## Positive / Negative Prompts

Positive prompt:

```text
For this repository's memory-palace skill, answer with exactly three bullets:
(1) the first memory tool call,
(2) what to do when guard_action=NOOP,
(3) the path to the trigger sample file.
```

Negative prompt:

```text
Please help me change the text at the beginning of the README; no need to touch Memory Palace.
```

Expectations:

- Positive prompt triggers `memory-palace`.
- Negative prompt should not mistakenly trigger `memory-palace`.

Current smoke also adds one concrete known-URI follow-up: if the prompt already
names a target URI, the skill should go straight to `read_memory(...)` for that
URI instead of bouncing through `search_memory(...)` first.

## One-Sentence Official Statement

- `Claude/Gemini`: Workspace direct-connection surfaces exist, but the default recommended install path is still `--scope user --with-mcp`.
- `Codex/OpenCode`: You get **repo-local auto-discovery** after running sync, but to "really use the current repository MCP," you should still supplement with **user-scope MCP registration**.
