# Memory Palace Skills 快速上手

面向想最快把 `Claude / Codex / Gemini / OpenCode` 接到本仓库的人。

如果你只想跑 `Dashboard / API / SSE`，看 `docs/GHCR_QUICKSTART.md` 即可，这里不是必须。

如果你希望 AI 全程带着你装，先在客户端里安装 [`memory-palace-setup`](https://github.com/AGI-is-going-to-arrive/memory-palace-setup)，然后直接说：

```text
使用 $memory-palace-setup 帮我一步步安装配置 Memory Palace，优先走 skills + MCP。
```

---

## 1. 两层概念

| 层 | 作用 |
|---|---|
| skill | 决定 “什么时候进入 Memory Palace 工作流” |
| MCP | 决定 “真正调用 `read_memory / search_memory / update_memory` 等工具” |

两层都到位才算真的能用。

<p align="center">
  <img src="../images/skill_vs_mcp.png" width="800" alt="Skill vs MCP" />
</p>

---

## 2. 一行命令打通主链路

新机器上推荐先跑统一的 user-scope 安装：

```bash
python scripts/install_skill.py \
  --targets claude,codex,gemini,opencode \
  --scope user --with-mcp --force
```

跑完后，home 目录里通常会出现：

- `~/.claude/skills/memory-palace/`，以及 `~/.claude.json` 里指向当前仓库的 `mcpServers.memory-palace`
- `~/.codex/config.toml`
- `~/.gemini/skills/memory-palace/SKILL.md`、`~/.gemini/settings.json`、`~/.gemini/policies/memory-palace-overrides.toml`
- `~/.config/opencode/opencode.json`

如果你还想给当前仓库补一份项目级入口，再额外跑：

```bash
python scripts/install_skill.py \
  --targets claude,gemini \
  --scope workspace --with-mcp --force
```

工作区里会补齐 `.claude/skills/memory-palace/`、`.mcp.json`、`.gemini/skills/memory-palace/`、`.gemini/settings.json`、`.gemini/policies/memory-palace-overrides.toml`。

> 公开仓库默认只带 canonical bundle (`docs/skills/memory-palace/`)。`.claude / .codex / .gemini / .opencode` 这些镜像和 `.mcp.json` 都是安装后生成的本地产物。

---

## 3. 平台分支

repo-local MCP 启动器按宿主环境二选一：

- 原生 Windows -> `python backend/mcp_wrapper.py`
- macOS / Linux / `Git Bash` / `WSL` / MSYS / Cygwin -> `bash scripts/run_memory_palace_mcp_stdio.sh`

`install_skill.py` 和 `render_ide_host_config.py` 都会按实际环境自动选择，不需要你手抄。

两条 wrapper 都会优先复用当前仓库 `.env` 的 `DATABASE_URL`。如果 `.env` 写成 `/app/...` 或 `/data/...` 这类容器路径，会被直接拒绝；改成本机绝对路径或回到 Docker `/sse`。

---

## 4. 各 CLI 客户端的边界

| 客户端 | repo-local skill | MCP 主路径 |
|---|---|---|
| `Claude Code` | sync 后自动发现 | `~/.claude.json` 或 `.mcp.json` |
| `Gemini CLI` | sync 后自动发现 | `~/.gemini/settings.json` 或 `.gemini/settings.json` |
| `Codex CLI` | sync 后自动发现 | `~/.codex/config.toml`（user-scope 为主） |
| `OpenCode` | sync 后自动发现 | `~/.config/opencode/opencode.json`（user-scope 为主） |

对 `Codex / OpenCode`，workspace scope 下不会写稳定的 MCP 配置，user-scope 才是它们的主路径。

### 客户端自检

```bash
claude mcp list
gemini mcp list
codex mcp list
opencode mcp list
```

看到 `memory-palace connected` / 当前仓库 project block 出现，就基本就位。

---

## 5. 手工 fallback：单独加 MCP

只有当统一的 `install_skill.py` 在某个客户端上出问题，需要手工排障时才用：

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

OpenCode 的 fallback 在其本身的 MCP 管理 UI 里加一个 `local / stdio` server，填同样的 command/args。

> 把 `<repo-root>` / `/ABS/PATH/TO/REPO` 换成你本机的仓库根目录绝对路径。
>
> 这些 fallback 命令最终都会写到客户端的 user-scope 配置里。

---

## 6. IDE 宿主

`Cursor / Windsurf / VSCode-host / Antigravity` 走单独的接入方式：

- 规则入口：仓库根的 `AGENTS.md`
- MCP 入口：`python scripts/render_ide_host_config.py --host <cursor|windsurf|vscode-host|antigravity>`

不要把它们当成 hidden skill mirror 的消费者。详见 `IDE_HOSTS.md`。

---

## 7. 验证

```bash
# skill 镜像漂移检查
python scripts/sync_memory_palace_skill.py --check

# 多客户端 skill 触发 smoke
python scripts/evaluate_memory_palace_skill.py

# 真实 MCP 调用 e2e
cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py
```

这三条会在 `docs/skills/` 下生成本地报告（`TRIGGER_SMOKE_REPORT.md` / `MCP_LIVE_E2E_REPORT.md`），默认被 `.gitignore` 排除。这些是给你本机复核用的，不是主入口文档；转发前请先自己检查内容是否含本机路径。

需要隔离报告输出时，设置 `MEMORY_PALACE_SKILL_REPORT_PATH` / `MEMORY_PALACE_MCP_E2E_REPORT_PATH`；相对路径会被重定向到系统临时目录的 `memory-palace-reports/`，固定落点请用仓库外的绝对路径。看到 `PARTIAL` 时，把它当作宿主边界，需要按对应客户端补验；Codex/OpenCode 尤其要确认 user-scope MCP 是否绑定。

### 触发自检

正向 prompt：

```text
先从 system://boot 读一下，再帮我查最近关于部署偏好的记忆。
```

预期看到：`read_memory("system://boot")` -> `search_memory(..., include_session=true)`。

反向 prompt：

```text
给我重写 README 的开头介绍。
```

不应触发 Memory Palace 工作流。

---

## 8. 常见误区

- **看到 skill 文件就以为能用**：还需要 MCP 配到位。
- **只配了 MCP**：工具能调，但客户端可能不会自动进入工作流。
- **Codex / OpenCode 不需要配 MCP**：repo-local 自动发现 ≠ MCP 已绑定，仍要 user-scope 注册。
- **直接读 hidden 路径**：部分客户端策略会拦截 `.gemini/skills/` 等隐藏目录。引用文件时统一用 `docs/skills/memory-palace/...`。

---

## 9. 继续读什么

- `CLI_COMPATIBILITY_GUIDE.md` —— 各 CLI 的完整选项与边界
- `IDE_HOSTS.md` —— Cursor / Windsurf / VSCode-host / Antigravity 的接法
- `docs/skills/memory-palace/SKILL.md` —— 真正给模型看的 skill 本体
