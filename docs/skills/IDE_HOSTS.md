# Memory Palace IDE Hosts

面向 `Cursor / Windsurf / VSCode-host / Antigravity` 这类 IDE 宿主。

它们与 `Claude / Codex / Gemini / OpenCode` 的关键区别不是品牌，而是接入表面：

- 没有稳定公开的模型 API 给外部 CLI 直接复用
- 适合把 Memory Palace 投影为：
  - repo-local 规则文件
  - 本地 MCP 配置片段
  - 少量宿主特化兼容层

因此 IDE hosts 的主路径不再是 hidden skill mirror，而是 `AGENTS.md + MCP snippet + 可选兼容层`。

---

## 1. 核心口径

### canonical 真源不变

```text
docs/skills/memory-palace/
```

继续服务 CLI 客户端与仓内 skill 设计真源。

### IDE hosts 通过两条投影接入

- **规则入口**：仓库根的 `AGENTS.md`
- **执行入口**：本地 MCP 配置指向 repo-local launcher
  - 原生 Windows：`python backend/mcp_wrapper.py`
  - macOS / Linux：`bash scripts/run_memory_palace_mcp_stdio.sh`
- **可选兼容层**：宿主特定的 wrapper / workflow

### 本地前提

repo-local 路径作为一个整体使用：

- 渲染出来的 IDE host 片段假设宿主能跑对应平台的 wrapper
- wrapper 假设 `backend/.venv` 已经装好仓库依赖
- wrapper 先读当前仓库 `.env` 决定 `DATABASE_URL`
- `.env` 缺失但有 `.env.docker`、或 `DATABASE_URL` 指向 `/app/...` / `/data/...` 容器路径时拒绝启动

如果你只有 Docker / GHCR 在跑、本地 checkout 没准备 runtime，**不要**用 stdio wrapper。把宿主指向 Docker 暴露的 `/sse` 端点。

---

## 2. 各宿主

### Cursor

- 主要消费 repo-local `AGENTS.md`
- 通过宿主自带的本地 stdio MCP 设置接入
- 不把 `.cursor/skills/memory-palace/` 当默认主路径

### Windsurf

口径与 Cursor 一致；前提是宿主支持本地 stdio MCP 和 workspace/project rules。

### VSCode-host

指 “带 agent / MCP 能力的 VS Code 扩展宿主”。不假设 VS Code 本体就有统一的技能系统。只要扩展支持本地 stdio MCP 和 repo-local project rules，就走同一条 `AGENTS.md + MCP snippet` 路径。

### Antigravity

仍属 IDE Host 子集，使用同一条 MCP 接入路径，但有一个宿主特化差异：

- **优先读取 `AGENTS.md`**
- **兼容旧 `GEMINI.md`**

并保留可选 workflow 投影：

```text
docs/skills/memory-palace/variants/antigravity/global_workflows/memory-palace.md
```

这是附加层，不改变它属于 IDE Host 的本质。

---

## 3. 生成配置

不要手抄。直接渲染：

```bash
python scripts/render_ide_host_config.py --host cursor
python scripts/render_ide_host_config.py --host windsurf
python scripts/render_ide_host_config.py --host vscode-host
python scripts/render_ide_host_config.py --host antigravity
```

规范参数名为 `vscode-host`，脚本兼容旧的 `--host vscode`。

默认输出按平台：

- 原生 Windows：`python + backend/mcp_wrapper.py`
- macOS / Linux：`bash + scripts/run_memory_palace_mcp_stdio.sh`

如果宿主有 `stdin/stdout` 或 CRLF 兼容问题，切到 wrapper 版本：

```bash
python scripts/render_ide_host_config.py --host antigravity --launcher python-wrapper
```

显式要求 `python-wrapper` 但 `backend/.venv` 没准备好时，脚本会直接报错，不再静默退回到系统 Python。

---

## 4. 验证

IDE hosts 不承诺仓内 “一键 live smoke”。分层验证：

1. **静态契约检查**
   - `AGENTS.md` 存在
   - wrapper / workflow / canonical 真源存在
   - MCP 命令确实指向当前仓库，且 launcher / args 组合可执行

2. **宿主连接检查**
   - IDE 能看到 `memory-palace` MCP server
   - IDE 能列出 Memory Palace 工具

3. **手工 smoke checklist**
   - `read_memory("system://boot")`
   - 创建一条 `notes://ide_smoke_*`
   - 再试一次重复创建，确认 guard 阻断

每个宿主都需要在目标环境里各做一次手工 smoke，才能从 “静态契约对齐” 升级到 “该宿主 live 可用”。
