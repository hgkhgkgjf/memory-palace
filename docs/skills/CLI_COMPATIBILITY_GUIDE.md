# Memory Palace CLI Compatibility Guide

`Claude Code / Gemini CLI / Codex CLI / OpenCode` 接入 Memory Palace 的差异、选项与边界。

如果只想最快接通，先看 [`SKILLS_QUICKSTART.md`](SKILLS_QUICKSTART.md)。这份文档放各客户端的完整选项与坑位。

---

## 1. 两层结构

| 层 | 决定的事 |
|---|---|
| skill | 客户端是否进入 Memory Palace 工作流 |
| MCP | 客户端真的调用当前仓库的 backend |

判断 “能不能直接用” 必须两层同时满足。

### Repo-local launcher

repo-local MCP launcher 按宿主环境二选一：

- 原生 Windows：`backend/mcp_wrapper.py`
- macOS / Linux / `Git Bash` / `WSL` / MSYS / Cygwin：`scripts/run_memory_palace_mcp_stdio.sh`

`install_skill.py`、`render_ide_host_config.py`、`evaluate_memory_palace_mcp_e2e.py` 都按这条规则生成配置。

Wrapper 行为：

- 优先复用当前仓库 `.env` 里的 `DATABASE_URL`
- 客户端把 `DATABASE_URL` 传成空字符串时也按 “未设置” 处理
- `.env` 写成 `/app/...` 或 `/data/...` 这类容器路径会直接拒绝启动
- shell wrapper 还会把 `localhost / 127.0.0.1 / ::1 / host.docker.internal` 合并进 `NO_PROXY`

只要别手工乱改客户端命令，Dashboard、HTTP API、MCP 默认都连同一份数据库。

---

## 2. 推荐命令

### 同步 skill 镜像

```bash
python scripts/sync_memory_palace_skill.py
python scripts/sync_memory_palace_skill.py --check
```

### user-scope 安装（推荐默认）

```bash
python scripts/install_skill.py \
  --targets claude,codex,gemini,opencode \
  --scope user --with-mcp --force
```

### workspace 安装（可选补项目级入口）

```bash
python scripts/install_skill.py \
  --targets claude,gemini \
  --scope workspace --with-mcp --force
```

`Codex / OpenCode` 在 workspace scope 下不会写 MCP 配置，user-scope 才是它们的主路径。

### 安装链检查

```bash
python scripts/install_skill.py \
  --targets claude,codex,gemini,opencode \
  --scope user --with-mcp --check
```

---

## 3. 安装后会看到什么

| 客户端 | workspace mirrors | user-scope 入口 |
|---|---|---|
| `Claude Code` | `.claude/skills/memory-palace/` + `.mcp.json` | `~/.claude/skills/memory-palace/` + `~/.claude.json` 里的当前仓库 project block |
| `Codex CLI` | `.codex/skills/memory-palace/` | `~/.codex/config.toml` |
| `Gemini CLI` | `.gemini/skills/memory-palace/` + `.gemini/settings.json` + `.gemini/policies/memory-palace-overrides.toml` | `~/.gemini/skills/memory-palace/SKILL.md` + `~/.gemini/settings.json` + `~/.gemini/policies/memory-palace-overrides.toml` |
| `OpenCode` | `.opencode/skills/memory-palace/` | `~/.config/opencode/opencode.json` |

canonical 真源始终在 `docs/skills/memory-palace/`；其他都是安装后生成的本地产物。

### install_skill.py 的几个细节

- 覆盖前会在原目录留 `*.bak`（`.mcp.json.bak` / `settings.json.bak` / `config.toml.bak` / `memory-palace-overrides.toml.bak`）
- JSON 配置坏掉时会报具体文件路径和行列号
- Windows 上文件短暂被占用时会自动重试 `replace` / promote / rollback
- 省略 `--targets` 时默认 `claude,codex,opencode`；`gemini` 推荐显式加上

---

## 4. 各 CLI 的具体接法

### Claude Code

- 自动发现：`.claude/skills/memory-palace/`
- MCP：workspace 走 `.mcp.json`，user-scope 写入 `~/.claude.json` 当前仓库的 project block
- 默认推荐：`--scope user --with-mcp`；想给当前仓库补项目级入口再跑 workspace 安装

### Gemini CLI

- 自动发现：`.gemini/skills/memory-palace/`
- MCP：workspace 走 `.gemini/settings.json`，user-scope 走 `~/.gemini/settings.json`
- Policy：`memory-palace-overrides.toml` 解决旧 `__` MCP tool 语法告警
- 看到 `Policy file warning` 时优先重跑 `--scope user --with-mcp --force`
- 看到 `Skill conflict detected ... overriding ...` 通常表示 workspace skill 在覆盖 user-level 旧版本，不是坏事

### Codex CLI

- 自动发现：`.codex/skills/memory-palace/`
- MCP：以 `~/.codex/config.toml` 为主，不能假定 “sync 完就开箱即用”
- 优先 `python scripts/install_skill.py --targets codex --scope user --with-mcp --force`
- 手工 fallback：

```bash
# native Windows
codex mcp add memory-palace -- python C:\ABS\PATH\TO\REPO\backend\mcp_wrapper.py

# macOS / Linux / Git Bash / WSL
codex mcp add memory-palace \
  -- /bin/zsh -lc 'cd /ABS/PATH/TO/REPO && bash scripts/run_memory_palace_mcp_stdio.sh'
```

### OpenCode

- 自动发现：`.opencode/skills/memory-palace/`
- MCP：以 `~/.config/opencode/opencode.json` 为主
- 优先 `python scripts/install_skill.py --targets opencode --scope user --with-mcp --force`
- 手工 fallback：在 OpenCode 自己的 MCP 管理 UI 里加 `local / stdio` server，参数：

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

## 5. IDE 宿主

`Cursor / Windsurf / VSCode-host / Antigravity` 不再走 hidden skill mirror。统一口径：

- 规则入口：仓库根的 `AGENTS.md`
- 执行入口：本地 MCP 配置指向 repo-local launcher

不要手抄，直接渲染：

```bash
python scripts/render_ide_host_config.py --host cursor
python scripts/render_ide_host_config.py --host windsurf
python scripts/render_ide_host_config.py --host vscode-host
python scripts/render_ide_host_config.py --host antigravity
```

如果宿主有 `stdin/stdout` 或 CRLF 兼容问题：

```bash
python scripts/render_ide_host_config.py --host antigravity --launcher python-wrapper
```

详见 [`IDE_HOSTS.md`](IDE_HOSTS.md)。

---

## 6. 最小验证链

```bash
# 安装链检查
python scripts/install_skill.py \
  --targets claude,codex,gemini,opencode \
  --scope user --with-mcp --check

# 触发 smoke
python scripts/evaluate_memory_palace_skill.py

# 真实 MCP e2e
cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py
```

后两条会生成本地报告 `docs/skills/TRIGGER_SMOKE_REPORT.md` 和 `docs/skills/MCP_LIVE_E2E_REPORT.md`（默认 `.gitignore`）。

环境变量：

- `MEMORY_PALACE_SKILL_REPORT_PATH` / `MEMORY_PALACE_MCP_E2E_REPORT_PATH` —— 改默认输出位置。相对路径会落到系统临时目录的 `memory-palace-reports/` 下；想完全控制位置传仓库外的绝对路径
- `MEMORY_PALACE_ENABLE_GEMINI_LIVE=1` —— 显式打开 Gemini live 真实数据库 `create/update/guard` 验证
- `MEMORY_PALACE_SKIP_GEMINI_LIVE=1` —— 显式跳过 Gemini live

转发报告前请自己检查内容（可能含本机路径或客户端配置痕迹）。

---

## 7. 正向 / 反向 prompt

正向 prompt：

```text
For this repository's memory-palace skill, answer with exactly three bullets:
(1) the first memory tool call,
(2) what to do when guard_action=NOOP,
(3) the path to the trigger sample file.
```

期望命中：

- `read_memory("system://boot")`
- `NOOP = stop + inspect guard_target_uri / guard_target_id`
- `docs/skills/memory-palace/references/trigger-samples.md`

如果 prompt 里已经明确给出 URI，应直接走 `read_memory(uri)`，不要先绕回 `search_memory(...)`。

反向 prompt：

```text
请帮我改一下 README 开头的文案，不需要碰 Memory Palace。
```

不应触发 `memory-palace`。

---

## 8. 一句话口径

- `Claude / Gemini`：sync 后可获得 repo-local skill 自动发现 + workspace MCP 直连
- `Codex / OpenCode`：sync 后可获得 repo-local skill 自动发现，但 MCP 仍以 user-scope 注册为主
- `IDE Hosts`：走 `AGENTS.md + MCP snippet`，不要把 hidden skill mirror 当默认入口
