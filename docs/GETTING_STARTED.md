# 快速上手

本指南帮你在几分钟内跑起 Memory Palace。

> Memory Palace 是为 AI Agent 设计的长期记忆系统，通过 [MCP 协议](https://modelcontextprotocol.io/) 向 Claude Code、Codex、Gemini CLI、OpenCode 等客户端提供 9 个工具。如果你接的是 Cursor / Windsurf / VSCode 等 IDE 宿主，请看 `docs/skills/IDE_HOSTS.md`。
>
> 如果你想配置的是 CLI 客户端里的 skill + MCP，请直接看 `docs/skills/GETTING_STARTED.md`。

---

## 1. 环境要求

| 依赖 | 最低版本 |
|---|---|
| Python | 3.10+ |
| Node.js | 20.19+ 或 22.12+ |
| npm | 9+ |
| Docker（可选） | 20+ |
| Docker Compose（可选） | 2.0+（建议使用较新的 `docker compose` plugin） |

如果你的机器上 Python 命令叫 `python3`，把下面命令里的 `python` 换成 `python3`。

---

## 2. 三种启动方式

| 方式 | 适合谁 | 入口 |
|---|---|---|
| Docker 一键部署 | 想最快用上 | 4.1 节 |
| GHCR 拉取镜像 | 本地构建有问题 | 4.2 节 |
| 本地源码运行 | 想改代码或调试 | 3 节 |

下面分别说明。

---

## 3. 本地开发

### Step 1：准备配置

```bash
cp .env.example .env
```

打开 `.env`，把 `DATABASE_URL` 改成你机器上的绝对路径：

```
DATABASE_URL=sqlite+aiosqlite:////absolute/path/to/memory_palace/demo.db
```

注意：
- macOS / Linux 绝对路径前缀是 `sqlite+aiosqlite:////`（4 个斜杠）
- Windows 是 `sqlite+aiosqlite:///C:/...`（3 个斜杠）
- 本地路径必须是宿主机真实路径，包括 `/Users/...` 和 `/home/...`
- 不要把 Docker 容器里的 `/app/...` 或 `/data/...` 路径抄到本地 `.env`，本地 stdio wrapper 会拒绝启动

repo-local MCP wrapper 按平台选择：
- 原生 Windows：`python backend/mcp_wrapper.py`
- macOS / Linux / Git Bash / WSL：`bash scripts/run_memory_palace_mcp_stdio.sh`

也可以用脚本生成预设配置：

```bash
# macOS / Linux
bash scripts/apply_profile.sh macos b

# Windows PowerShell
.\scripts\apply_profile.ps1 -Platform windows -Profile b
```

参数说明：第二位是 Profile 档位（`a` / `b` / `c` / `d`），第三位可选指定输出文件。详见 [DEPLOYMENT_PROFILES.md](DEPLOYMENT_PROFILES.md)。

**常用配置项**（更多见 `.env.example`）：

| 配置项 | 说明 |
|---|---|
| `DATABASE_URL` | SQLite 数据库路径（建议绝对路径） |
| `SEARCH_DEFAULT_MODE` | 检索模式：`keyword` / `semantic` / `hybrid` |
| `RETRIEVAL_EMBEDDING_BACKEND` | Embedding 后端：`none` / `hash` / `router` / `api` / `openai` |
| `RETRIEVAL_EMBEDDING_DIM` | Embedding 向量维度，必须和 provider 实际返回一致 |
| `RETRIEVAL_RERANKER_ENABLED` | 是否启用 Reranker |
| `MCP_API_KEY` | HTTP/SSE 接口鉴权密钥 |
| `MCP_API_KEY_ALLOW_INSECURE_LOCAL` | 本地回环放行（仅限调试） |
| `VALID_DOMAINS` | 允许的可写记忆 URI 域 |

如果用 Profile C/D 接远端 embedding/reranker，必须用真实的 endpoint / key / model / dimension 替换示例值，脚本会拒绝占位符。`RETRIEVAL_EMBEDDING_DIM=1024` 只是某些示例的默认模板值；切到远端 backend 时必须由你填写 provider 实际维度，向导不再默认替你补 `1024`。

### Step 2：启动后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate           # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

正常启动会显示：

```
Memory API starting.
SQLite database initialized.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### Step 3：启动前端

```bash
cd frontend
npm install
npm run dev
```

浏览器访问 `http://127.0.0.1:5173`。

如果右上角显示 `设置 API 密钥`（英文 `Set API key`），点击它可以打开首启配置向导：
- 只想让 Dashboard 通过鉴权：选「只保存 Dashboard 密钥」（保存在 `sessionStorage`）
- 想写入配置到 `.env`：仅在非 Docker 本地运行时可用，且必须从本机回环地址访问

Dashboard 使用指南见 [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md)。

---

## 4. Docker 部署

### 4.1 一键脚本（推荐）

```bash
# macOS / Linux
bash scripts/docker_one_click.sh --profile b

# Windows PowerShell
.\scripts\docker_one_click.ps1 -Profile b
```

脚本会自动生成 Docker env、检测端口冲突、构建并启动容器。

启动后访问：

| 服务 | 地址 |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:18000 |
| SSE | http://localhost:3000/sse |
| Health Check | http://localhost:18000/health |

如果默认端口被占用，脚本会自动换到附近空闲端口，以最终打印出的地址为准。也可以手动指定：

```bash
bash scripts/docker_one_click.sh --profile b --frontend-port 3100 --backend-port 18100
```

停止服务：

```bash
COMPOSE_PROJECT_NAME=<console 打印的 project> docker compose -f docker-compose.yml down --remove-orphans
```

`down --remove-orphans` 不会删除数据卷；只有 `down -v` 才会清空数据库和 review snapshots。

**Profile C/D 本地联调**：如果想把宿主机的 router/API 注入 Docker，需显式开启注入开关：

```bash
bash scripts/docker_one_click.sh --profile c --allow-runtime-env-injection
```

注入后宿主机的 `127.0.0.1` / `localhost` 会自动改写成 `host.docker.internal`，便于容器访问宿主机服务。

**数据卷与 WAL 安全**：
- 默认数据卷按 compose project 隔离：`<compose-project>_data` 和 `<compose-project>_snapshots`
- 仓库默认只支持 Docker named volume + WAL 组合
- 如果你把 `/app/data` 改成 NFS/CIFS/SMB bind mount，必须设置 `MEMORY_PALACE_DOCKER_WAL_ENABLED=false` 和 `MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete`；如果绕过一键脚本，手动 `docker compose up`，也要自己遵守同一条规则

**访问宿主机模型服务**：在容器里不要用 `127.0.0.1`，那指向容器本身。用 `host.docker.internal`，compose 已配置 `host-gateway`。

### 4.2 GHCR 预构建镜像

如果本地构建总失败，用 GHCR 拉取的镜像直接跑：

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

注意：
- 这条路径不会自动换端口。如果 3000 / 18000 已被占用，先设置 `MEMORY_PALACE_FRONTEND_PORT` / `MEMORY_PALACE_BACKEND_PORT`
- 这条路径不会自动配置 skills / MCP / IDE host，那部分仍按 `docs/skills/GETTING_STARTED.md` 走
- 仍然需要这个仓库 checkout，因为要用 `docker-compose.ghcr.yml` 和 profile 脚本

停止服务：

```bash
docker compose -f docker-compose.ghcr.yml down --remove-orphans
```

### 4.3 备份数据库

```bash
# macOS / Linux
bash scripts/backup_memory.sh

# Windows PowerShell
.\scripts\backup_memory.ps1
```

备份文件默认写入 `backups/`，使用 UTC 时间戳命名，默认保留最近 20 份。

```bash
# 指定保留数量
bash scripts/backup_memory.sh --keep 10
```

---

## 5. 验证服务可用

### 健康检查

```bash
# 本地开发
curl -fsS http://127.0.0.1:8000/health

# Docker
curl -fsS http://localhost:18000/health
```

返回 `{"status":"ok",...}` 即正常。本机回环或带 `MCP_API_KEY` 的请求会返回详细的 `index` / `runtime` 信息；未鉴权远端请求只返回浅信息。如果系统已降级，会返回 HTTP `503`。

### 浏览记忆树

```bash
curl -fsS "http://127.0.0.1:8000/browse/node?domain=core&path=" \
  -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>"
```

`domain` 对应 `.env` 里 `VALID_DOMAINS` 的域名。

> Swagger `/docs` 默认不开放；要看接口请参考本文档和 [TECHNICAL_OVERVIEW.md](TECHNICAL_OVERVIEW.md)、[TOOLS.md](TOOLS.md)。

---

## 6. MCP 接入

Memory Palace 提供 9 个 MCP 工具（定义在 `backend/mcp_server.py`）：

| 工具 | 用途 |
|---|---|
| `read_memory` | 读取记忆（支持 `system://boot`、`system://index` 等特殊 URI） |
| `create_memory` | 创建记忆节点 |
| `update_memory` | 更新记忆（优先使用 diff patch） |
| `delete_memory` | 删除记忆 |
| `add_alias` | 添加别名 |
| `search_memory` | 搜索（keyword / semantic / hybrid） |
| `compact_context` | 压缩上下文 |
| `rebuild_index` | 重建搜索索引 |
| `index_status` | 查看索引状态 |

完整语义见 [TOOLS.md](TOOLS.md)。

### 6.1 stdio 模式（推荐本地使用）

stdio 模式直接通过进程标准输入输出通信，不经过 HTTP 鉴权层。

客户端配置（按平台选择 wrapper）：

**macOS / Linux / Git Bash / WSL：**

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

**原生 Windows：**

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

直接用 venv 里的 `python.exe`，避免系统 `PATH` 里没有正确解释器时 wrapper 找不到。把 `C:\\ABS\\PATH\\TO\\REPO` 换成你的实际仓库路径；JSON 里反斜杠要双写（`\\`）。

两条 wrapper 都依赖本地 `backend/.venv`，使用当前仓库的 `.env`。如果还没创建 `.venv`，先回到 **Step 2**。

### 6.2 SSE 模式

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

不显式设置 `PORT` 时，如果 8000 被占用，会自动回退到 8010；显式设置 `PORT` 会固定使用该端口。SSE 模式仍受 `MCP_API_KEY` 保护。

只有真要让远程客户端访问时，才把 `HOST` 改成 `0.0.0.0`，同时自行补齐 API Key、防火墙、反向代理等保护。

Docker 部署下 SSE 直接挂在 backend 进程内，通过前端代理暴露在 `http://127.0.0.1:3000/sse`。

客户端配置（8010 为 8000 被占用时的回退端口）：

```json
{
  "mcpServers": {
    "memory-palace": {
      "url": "http://127.0.0.1:8010/sse"
    }
  }
}
```

大多数客户端还需要在 headers 里加 `X-MCP-API-Key`，具体字段名以客户端自己的 MCP 文档为准。

### 6.3 远程 SSE 客户端示例

**Claude Code：**

```bash
claude mcp add \
  --transport sse \
  --scope project \
  --header "X-MCP-API-Key: <YOUR_MCP_API_KEY>" \
  memory-palace \
  http://127.0.0.1:3000/sse
```

**Gemini CLI：**

```bash
gemini mcp add \
  --transport sse \
  --scope project \
  --header "X-MCP-API-Key: <YOUR_MCP_API_KEY>" \
  memory-palace \
  http://127.0.0.1:3000/sse
```

Docker / GHCR 部署时，`<YOUR_MCP_API_KEY>` 即 `.env.docker` 里的 `MCP_API_KEY`。

Codex CLI 和 OpenCode 当前优先走 repo-local stdio 路径，远程 SSE 直连尚未验证。

### 6.4 多客户端并发

如果多个 stdio MCP 客户端同时指向同一份 SQLite 库，建议在 `.env` 加上：

```env
RUNTIME_WRITE_WAL_ENABLED=true
RUNTIME_WRITE_JOURNAL_MODE=wal
RUNTIME_WRITE_WAL_SYNCHRONOUS=normal
RUNTIME_WRITE_BUSY_TIMEOUT_MS=5000
```

Docker 部署默认已经强制 `wal`，这组配置主要给 repo-local stdio 用。

---

## 7. HTTP/SSE 鉴权

`MCP_API_KEY` 保护以下接口（fail-closed：未配置 key 时直接返回 401）：

| 路径 | 说明 |
|---|---|
| `/maintenance/*` | 维护接口 |
| `/review/*` | 审查接口 |
| `/browse/*` | 记忆树读写 |
| `/sse` 和 `/messages` | MCP SSE 通道 |

请求时带上 Header（任选一种）：

```bash
curl -fsS http://127.0.0.1:8000/maintenance/orphans \
  -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>"

# 或
curl -fsS http://127.0.0.1:8000/maintenance/orphans \
  -H "Authorization: Bearer <YOUR_MCP_API_KEY>"
```

**本地调试跳过鉴权**：在 `.env` 设置 `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`，仅对 `127.0.0.1` / `::1` / `localhost` 的直连请求生效，不影响 stdio 模式。

stdio 模式不经过鉴权层，不需要 key。

---

## 8. 新手常见问题

| 问题 | 解决 |
|---|---|
| 启动后端 `ModuleNotFoundError` | 没用 `backend/.venv`。先 `source .venv/bin/activate && pip install -r requirements.txt` |
| `DATABASE_URL` 报错 | 用绝对路径，带 `sqlite+aiosqlite:///` 前缀。不要用 Docker 容器内路径 |
| 本地 stdio 报错或断开 | 检查 `.env` 是否写成了 `/app/...` 或 `/data/...`（那是容器路径） |
| 前端访问 API 返回 502 | 确认后端在 8000 端口运行 |
| 受保护接口返回 401 | 配置 `MCP_API_KEY` 或开启 `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` |
| Docker 端口冲突 | `docker_one_click.sh` 会自动换端口，也可用 `--frontend-port` / `--backend-port` 指定 |

更多排查请看 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。

---

## 9. 继续阅读

| 文档 | 内容 |
|---|---|
| [DEPLOYMENT_PROFILES.md](DEPLOYMENT_PROFILES.md) | 部署档位 A/B/C/D 详解 |
| [TOOLS.md](TOOLS.md) | 9 个 MCP 工具的完整语义 |
| [TECHNICAL_OVERVIEW.md](TECHNICAL_OVERVIEW.md) | 系统架构与数据流 |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 常见问题排查 |
| [SECURITY_AND_PRIVACY.md](SECURITY_AND_PRIVACY.md) | 安全与隐私 |
| [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md) | Dashboard 操作指南 |
