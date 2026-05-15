# Memory Palace 快速上手

本指南帮助你在 5 分钟内跑通 Memory Palace 本地开发环境或 Docker 部署。

> **Memory Palace** 是一个为 AI Agent 设计的长期记忆系统，通过 [MCP（Model Context Protocol）](https://modelcontextprotocol.io/) 协议提供 9 个工具，让 Claude Code、Codex、Gemini CLI、OpenCode 等客户端具备持久化记忆能力；如果你接的是 `Cursor / Windsurf / VSCode-host / Antigravity` 这类 IDE 宿主，请先看 `docs/skills/IDE_HOSTS.md`。
>
> **如果你现在卡住的是 CLI 客户端里的 skill + MCP 安装，不要继续按这份排**；那条路径请直接看 `docs/skills/GETTING_STARTED.md`。

---

## 1. 环境要求

| 依赖 | 最低版本 | 检查命令 |
|---|---|---|
| Python | `3.10+` | `python --version` |
| Node.js | `20.19+`（或 `>=22.12`） | `node --version` |
| npm | `9+` | `npm --version` |
| Docker（可选） | `20+` | `docker --version` |
| Docker Compose（可选） | `2.0+`（手动运行仓库 compose 文件时建议使用较新的 `docker compose` plugin） | `docker compose version` |

> **提示**：macOS 用户推荐使用 [Homebrew](https://brew.sh) 安装 Python 和 Node.js。Windows 用户推荐从官网下载安装包或使用 [Scoop](https://scoop.sh)。如果你机器上的 Python 命令名是 `python3` 而不是 `python`，把下面命令里的 `python` 换成 `python3` 即可。
>
> **Compose 兼容边界**：仓库自带的 `docker-compose.yml` / `docker-compose.ghcr.yml` 在卷名默认值上使用了嵌套 `${...:-...}` 语法。如果你手动运行这些 compose 文件，建议使用较新的 `docker compose` plugin；某些较旧实现或经典 `docker-compose` 可能会在解析阶段直接失败。遇到这种情况，优先改走 `docker_one_click.sh/.ps1`，或先显式设置 `MEMORY_PALACE_DATA_VOLUME`、`MEMORY_PALACE_SNAPSHOTS_VOLUME`、`COMPOSE_PROJECT_NAME` 再启动。

---

## 2. 仓库结构速览

```
memory-palace/
├── backend/              # FastAPI + SQLite 后端
│   ├── main.py           # 应用入口（FastAPI 实例、/health 端点）
│   ├── mcp_server.py     # 9 个 MCP 工具实现（FastMCP）
│   ├── runtime_state.py  # 写入 Lane、索引 Worker、会话缓存
│   ├── run_sse.py        # MCP SSE 传输层（Starlette + API Key 鉴权）
│   ├── mcp_wrapper.py    # MCP 包装器
│   ├── requirements.txt  # Python 依赖清单
│   ├── requirements-dev.txt # 后端测试依赖
│   ├── db/               # 数据库 Schema、检索引擎
│   ├── api/              # HTTP 路由
│   │   ├── browse.py     # 记忆树浏览（GET /browse/node）
│   │   ├── review.py     # 审查接口（/review/*）
│   │   ├── maintenance.py# 维护接口（/maintenance/*）
│   │   └── setup.py      # 首启配置向导接口（/setup/*）
├── frontend/             # React + Vite + Tailwind Dashboard
│   ├── package.json      # 版本 1.0.1
│   └── vite.config.js    # 开发服务器 port 5173，代理到后端 8000
├── deploy/               # Docker 与 Profile 配置
│   ├── docker/           # Dockerfile.backend / Dockerfile.frontend
│   └── profiles/         # macos / linux / windows / docker 档位模板
├── scripts/              # 运维脚本
│   ├── apply_profile.sh  # Profile 应用脚本（macOS/Linux）
│   ├── apply_profile.ps1 # Profile 应用脚本（Windows）
│   ├── docker_one_click.sh   # Docker 一键部署（macOS/Linux）
│   ├── docker_one_click.ps1  # Docker 一键部署（Windows）
├── docs/                 # 项目文档
├── .env.example          # 配置模板（包含所有可用配置项）
├── docker-compose.yml    # Compose 编排文件
└── LICENSE               # 开源许可证
```

---

<p align="center">
  <img src="images/onboarding_flow.png" width="900" alt="Memory Palace 快速开始流程图" />
</p>

> 📌 这张图只是帮助你快速记住顺序。
>
> 真正以正文命令为准：
>
> - 后端默认是 `uvicorn` 跑在 `127.0.0.1:8000`
> - 前端开发服务器默认是 `5173`
> - Docker 默认入口是 `http://127.0.0.1:3000`（Dashboard）与 `http://127.0.0.1:3000/sse`（SSE）

## 3. 本地开发（推荐先走这一条）

### Step 1：准备配置文件

```bash
cp .env.example .env
```

> 这里复制出来的是**更保守的 `.env.example` 最小模板**。它足够你先完成本地启动，但**不等于已经套用了 Profile B**。
>
> 如果你想直接使用仓库里定义好的 Profile B 默认值（例如本地 hash Embedding），请优先使用下面的 Profile 脚本；如果你继续手动改 `.env.example` 也可以，就把它理解成“从最小模板开始按需补配置”。

> **重要**：复制后请检查 `.env` 中的 `DATABASE_URL`，将路径改成你的实际路径。共享环境或接近生产的场景更推荐使用绝对路径。例如：
>
> ```
> DATABASE_URL=sqlite+aiosqlite:////absolute/path/to/memory_palace/demo.db
> ```
>
> 这条 URL 的斜杠数量是有平台差异的：`macOS / Linux` 这类绝对路径通常是 `sqlite+aiosqlite:////...`，`Windows` 盘符路径通常是 `sqlite+aiosqlite:///C:/...`。如果你是手改 `.env`，不要把这两种写法混在一起。
>
> 还有一个很常见的误配：不要把 Docker / GHCR 路径里的 `sqlite+aiosqlite:////app/data/...`，或任何 `/data/...` 这类容器内 sqlite 路径，直接抄进本地 `.env`。`/app/...`、`/data/...` 都是容器内路径，不是你宿主机上的数据库文件路径；像 `sqlite+aiosqlite:///demo.db` 这种相对 sqlite 路径，或 `sqlite+aiosqlite:////%2Fapp%2Fdata/...` 这种把容器路径做了 URL 编码的写法，本地 repo-local `stdio` wrapper 现在也会一并拒绝。本地 `stdio` 请改成宿主机绝对路径；如果你就是要复用 Docker 那边的数据和服务，请直接改连 Docker 暴露的 `/sse`。

也可以使用 Profile 脚本快速生成带有默认配置的 `.env`：

```bash
# macOS / Linux —— 参数：平台 档位 [目标文件]
# 当前脚本接受的模板值是 macos|linux|windows|docker；其中 `linux` 会使用独立的 Linux 本地模板。
bash scripts/apply_profile.sh macos b

# Windows PowerShell
.\scripts\apply_profile.ps1 -Platform windows -Profile b
```

> `deploy/profiles/*/profile-*.env` 是脚本输入模板，不是建议你直接复制使用的最终 `.env`。对用户路径来说，继续用 `apply_profile.sh/.ps1` 生成会更稳，也能自动补齐路径和去重重复 key。

> apply_profile 脚本会先生成一份环境文件，再追加对应 Profile 的覆盖配置。本地 shell 路径（`macos` / `linux`）和原生 `windows` 默认目标仍是 `.env`；如果你跑的是 `docker` 变体且没有显式传目标文件，默认目标现在会是 `.env.docker`。对 shell 路径来说，`apply_profile.sh` 也会自动改写常见的本地 `DATABASE_URL` 占位路径，包括 `/Users/...` 和 `/home/...`。其中 macOS / Linux 下的 `apply_profile.sh` 现在还会在覆盖已有目标文件前先备份一份 `*.bak`。如果另一份 `apply_profile.sh` 正在写同一个目标文件，后来的进程会直接提示你稍后重试，而不是两边互相覆盖；它生成 staged / update 临时文件时，也会直接放到目标文件同目录，减少跨文件系统替换时的意外。对这两类相邻临时文件提交，shell 路径现在还会补一层有上限的小重试，短暂的文件锁或索引器占用不再那么容易把整次改写打断。
>
> 如果你是在 native Windows checkout 上，从 PowerShell / WSL / Git Bash 调 `bash scripts/apply_profile.sh ... <Windows绝对目标路径>`，当前 shell 路径现在也会更安全地规范化这个目标路径；常见的“分隔符被 shell 吃掉”的形态，不会再往仓库根目录里落一个坏文件名。
>
> 原生 Windows PowerShell 现在也补齐了同样的操作逻辑。`apply_profile.ps1` 现在也会在覆盖前先备份 `*.bak`，如果另一份 `apply_profile.ps1` 正在写同一个目标文件，也会直接拒绝第二个写入，并且 staged 临时文件同样放在目标文件所在目录，而不是默认共享临时目录。最终 replace/move 这一步现在还会对常见的 Windows 短暂锁冲突补一层有上限的小重试。
>
> `apply_profile.sh/.ps1` 当前会在生成后统一去重重复 env key；原生 Windows / native `pwsh` 仍建议在目标环境单独补跑一次。
>
> 如果你只是想先看最终会生成什么内容，macOS / Linux 下可以直接用 `bash scripts/apply_profile.sh --dry-run ...`。这条路径只打印最终结果，不会真正写目标文件。
>
> PowerShell 版本现在也支持同样的预览和帮助入口，而且这条预览路径和 shell 一样不会真的改目标文件：
>
> ```powershell
> .\scripts\apply_profile.ps1 -DryRun -Platform windows -Profile b -Target .env.generated
> .\scripts\apply_profile.ps1 -Help
> ```
>
> 本地 `profile c/d` 现在也会默认保留 `RUNTIME_AUTO_FLUSH_ENABLED=true`，所以只要你没有手工覆盖，生成出来的 `.env` 会继续沿用和 A/B 一致的 auto-flush 默认值。
>
> 如果你是在 Linux / WSL 环境里用 PowerShell 跑 `apply_profile.ps1`，`-Platform linux` 现在也已经可用；它会使用独立的 Linux 本地模板。原生 Windows 仍然继续使用 `-Platform windows`。
>
> 另外，`profile c/d` 现在也会在脚本阶段直接拦截未替换的 endpoint / key / model 占位值；如果你还留着示例里的 `PORT`、`replace-with-your-key`、`your-embedding-model-id` 这类占位内容，脚本会先报错，而不是等到后面启动时再用一份明显错误的配置继续往下跑。
>
> `DATABASE_URL` 现在也会走同样的保护逻辑。本地模板里的常见占位路径会先自动改写成当前仓库对应的宿主机路径；如果生成结果里还留着 `<...>` 或 `__REPLACE_ME__` 这类占位段，脚本或后端都会直接拦下。
>
> 但要注意：**macOS / Windows 本地生成的 profile-b `.env` 不会自动补 `MCP_API_KEY`**。如果你接下来就要打开 Dashboard，或者直接调 `/browse` / `/review` / `/maintenance`、`/sse`、`/messages`，请再自行补 `MCP_API_KEY`，或仅在本机回环调试时设置 `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`。只有 `docker` 平台的 profile 脚本会在 key 为空时自动生成一把本地 key。
>
> 另外，现在后端本身也会对**当前正在启用的远端检索配置**做占位符 fail-closed 检查：如果你跳过 `apply_profile.*`，直接手工复制了 `profile c/d` 模板，并且还保留着 `host.docker.internal:PORT`、`replace-with-your-key`、`your-embedding-model-id`、`your-reranker-model-id` 这类示例值，启动会直接报错，而不是带着一份明显无效的 embedding / reranker 配置继续运行。
>

#### 关键配置项说明

以下是 `.env` 中最常用的配置项（更多配置项请查看 `.env.example` 中的注释说明）：

| 配置项 | 说明 | 模板示例值 |
|---|---|---|
| `DATABASE_URL` | SQLite 数据库路径（**建议使用绝对路径**） | `sqlite+aiosqlite:////absolute/path/to/memory_palace/demo.db` |
| `SEARCH_DEFAULT_MODE` | 检索模式：`keyword` / `semantic` / `hybrid` | `keyword` |
| `RETRIEVAL_EMBEDDING_BACKEND` | 嵌入后端：`none` / `hash` / `router` / `api` / `openai` | `none` |
| `RETRIEVAL_EMBEDDING_MODEL` | Embedding 模型名 | `your-embedding-model-id` |
| `RETRIEVAL_EMBEDDING_DIM` | Embedding 向量维度（必须和 provider 实际返回一致） | `64`（默认模板值；切到远端 backend 时必须由你填写 provider 实际维度，不再自动补 `1024` / `4096`） |
| `RETRIEVAL_RERANKER_ENABLED` | 是否启用 Reranker | `false` |
| `RETRIEVAL_RERANKER_API_BASE` | Reranker API 地址 | 空 |
| `RETRIEVAL_RERANKER_API_KEY` | Reranker API 密钥 | 空 |
| `RETRIEVAL_RERANKER_MODEL` | Reranker 模型名 | `your-reranker-model-id` |
| `RETRIEVAL_REMOTE_TIMEOUT_SEC` | 远程 embedding / reranker / LLM 请求超时（秒） | `8` |
| `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` | 显式放行的 private provider IP 字面量、hostname 或 CIDR；`127.0.0.1` / `::1` 这类 loopback IP 和 `localhost` 默认已允许 | 空 |
| `INTENT_LLM_ENABLED` | 实验性意图 LLM 开关 | `false` |
| `RETRIEVAL_MMR_ENABLED` | hybrid 检索下的去重 / 多样性重排 | `false` |
| `RETRIEVAL_SQLITE_VEC_ENABLED` | sqlite-vec rollout 开关 | `false` |
| `MCP_API_KEY` | HTTP/SSE 接口鉴权密钥 | 空（见下方鉴权说明） |
| `MCP_API_KEY_ALLOW_INSECURE_LOCAL` | 本地调试时允许无 Key 访问（仅对直连 loopback 请求生效） | `false` |
| `CORS_ALLOW_ORIGINS` | 允许跨域访问的来源列表（留空使用本地默认） | 空 |
| `VALID_DOMAINS` | 允许的可写记忆 URI 域（`system://` 为内建只读域） | `core,writer,game,notes` |

> B 档位默认使用本地 hash Embedding 且不启用 Reranker；它仍然是**默认起步档位**。
>
> 如果你已经准备好模型服务，并且明确要更高质量的深检索，再考虑升级到 `Profile C/D`：它需要你在 `.env` 中把 Embedding / Reranker 链路填好；如果还要启用 LLM 辅助的 write guard / gist / intent routing，再继续填写 `WRITE_GUARD_LLM_*`、`COMPACT_GIST_LLM_*`、可选的 `INTENT_LLM_*`。详见 [DEPLOYMENT_PROFILES.md](DEPLOYMENT_PROFILES.md)。
>
> 现在通过首启配置向导在 `Profile B/C/D`、或 `hash / api / router / openai` 之间来回切时，当前表单里已经隐藏掉的旧字段会一起清掉，不会再把上一档没显示出来的 router/API 值顺手带着保存。这里说的是**本次保存 payload** 会跟着收干净，不等于后端会替你做任意历史配置清理。对 `Profile C/D` 来说，真正保存到本地 `.env` 前，向导也会继续卡住缺失的远端必填字段，不会因为只点了预设就把表单伪装成已经可保存。`Profile C` 预填的是本地 router 调试地址 `http://127.0.0.1:8001/v1`，它本身不是占位符；`Profile D` 预填的是远端模板地址 `https://router.example.com/v1`，保存前必须换成真实值。对任何远端 embedding backend（`api` / `router` / `openai`）来说，本地 `.env` 保存前都必须填一个真实的正整数 `embedding_dim`，向导也不会再替你猜一个 `1024`。保存检索配置时，`SEARCH_DEFAULT_MODE` 也会跟着一起写回：`Profile B` 会明确落成 `hybrid`，`embedding_backend=none` 才会回到 `keyword`。`Profile A` 现在也会在向导里直接显示出来，它对应的仍然是默认 `keyword + none` 基线。这里再补一个容易混淆的小边界：首启自动弹出时，向导仍按这个文档基线来展示；但如果你是手动打开，或者 `/setup/status` 已经拿到了当前运行态，表单会回填真实状态。当前代码下，完全没配检索 env 的本地运行态会按后端真实默认值显示成 `hash / 64`，不再额外伪装成 `none`。
>
> 这里要特别注意：这不是“无感切档”。B 默认是本地 hash 向量，C/D 则依赖你配置的真实 embedding 维度。只要你切了 embedding backend / model / dimension，旧索引就可能不能直接复用。更稳的做法是先备份，再用 `index_status()` 检查；如果出现维度不一致告警，执行 `rebuild_index(wait=true)`，或者直接用新库验证。
>
> 上表展示的是 `.env.example` 里的模板示例值；其中 `RETRIEVAL_EMBEDDING_DIM` 在默认模板里仍是 `64`，也就是**默认模板值；切到远端 backend 时必须由你填写 provider 实际维度**。如果你走 `openai` embedding backend，也按同一条原则处理。现在如果你通过 setup 流程切到真实远端 embedding backend，保存时会继续写入你明确提供的 `RETRIEVAL_EMBEDDING_DIM`，不再默认替你补 `1024`，也不会再保留公开模板里的旧 `4096` 猜测值；`hash` 仍是 `64`；最终仍要以 provider 实际返回的维度为准。如果某些检索环境变量在运行时完全缺失，后端内部还会使用自己的回退值（例如 `hash` / `hash-v1` / `64`）。
>
> 另外，当前代码已经支持 `openai` 作为 embedding backend；这里只是配置能力补齐，不代表前端多出一个单独的新档位。Profile B/C/D 的口径还是保持原来的分层语义。
>
> 配置语义说明：`RETRIEVAL_EMBEDDING_BACKEND` 只作用于 Embedding。Reranker 不存在 `RETRIEVAL_RERANKER_BACKEND` 开关，优先读取 `RETRIEVAL_RERANKER_*`，缺失时才回退 `ROUTER_*`（最后回退 `OPENAI_*` 的 base/key）。
>
> 对 repo-local `stdio` / `python-wrapper` 来说，`RETRIEVAL_REMOTE_TIMEOUT_SEC` 现在也会继续复用当前仓库 `.env` 里的值；如果你没写，repo-local 本地默认仍是 `8` 秒。
>
> 更多高级选项（如 `INTENT_LLM_*`、`RETRIEVAL_MMR_*`、`RETRIEVAL_SQLITE_VEC_*`、`CORS_ALLOW_*`、运行时观测/睡眠整合开关）已写在 `.env.example`，默认保持保守值，不影响最小启动路径。
>
> 推荐默认值（直接照抄通常没问题）：
> - `INTENT_LLM_ENABLED=false`：先用内建关键词规则，少一层外部依赖
> - `RETRIEVAL_MMR_ENABLED=false`：先看原始 hybrid 结果，只有“前几条太像”时再开
> - `RETRIEVAL_SQLITE_VEC_ENABLED=false`：普通部署先保持 legacy 路径
> - `CORS_ALLOW_ORIGINS=`：本地开发留空；要开放给浏览器跨域访问时再写明确域名
>
> 上面这些模型名只是占位示例，不是项目硬依赖。Memory Palace 不绑定某个固定 provider 或模型家族；请直接改成你自己的 OpenAI-compatible 服务里实际可用的 embedding / reranker / chat model id。
>
> 如果你后面要用 `profile c/d`，无论是先跑 `apply_profile.sh/.ps1`，还是再走 `docker_one_click.sh/.ps1`，这些示例 model id / endpoint / key / embedding dim 占位值都会被当成未解析占位符；在换成真实值之前，脚本会直接 fail-closed。
>
> 如果你接下来就要在本地打开 Dashboard，或者直接用 `curl` 调 `/browse` / `/review` / `/maintenance`，建议在 `.env` 里再补一项鉴权配置（二选一）：
>
> - `MCP_API_KEY=change-this-local-key`
> - `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`（只建议你自己机器上的回环调试时使用）

### Step 2：启动后端

```bash
cd backend
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
# .\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

> 如果你接下来还要跑后端测试，再补一条：
>
> ```bash
> pip install -r requirements-dev.txt
> ```

预期输出：

```
Memory API starting...
SQLite database initialized.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

> 后端通过 `main.py` 中的 `lifespan` 上下文管理器完成初始化，包括 SQLite 数据库创建、运行时状态（Write Lane、Index Worker）启动等。
>
> 上面这条 `uvicorn main:app --host 127.0.0.1 ...` 是推荐的**本机开发**写法。
>
> 如果你改为直接运行 `python main.py`，当前默认也是绑定 `127.0.0.1:8000`，不会自动放开到 `0.0.0.0`。只有在你明确需要远程访问时，才手动改成 `0.0.0.0`（或你的实际绑定地址），并补齐 `MCP_API_KEY`、防火墙、反向代理或其他网络侧保护。

### Step 3：启动前端

```bash
cd frontend
npm install
npm run dev
```

> 前端的 i18n 依赖已经写在 `frontend/package.json` 和 `frontend/package-lock.json` 里。正常执行一次 `npm install` 即可，不需要再单独安装 `i18next`、`react-i18next` 或 `i18next-browser-languagedetector`。
>
> 现在前端也补了一条单独的类型检查入口。如果你改了 Dashboard 页面、Setup Assistant 或 i18n 文案，想先做一轮静态检查，直接执行：
>
> ```bash
> npm run typecheck
> ```
>
> 仓库里的 Docker publish 校验工作流现在也会跑这条 `npm run typecheck`，所以本地和发布前看到的是同一条前端类型检查路径。

预期输出：

```
VITE v7.x.x  ready in xxx ms
➜  Local:   http://127.0.0.1:5173/
```

打开浏览器访问 `http://127.0.0.1:5173`，即可看到 Memory Palace Dashboard。

如果你希望按页面逐项看 Dashboard 的按钮、字段和典型操作流程，可继续看：

- `docs/DASHBOARD_GUIDE_CN.md`

> 如果你在本地手动启动时看到右上角的 `设置 API 密钥`（英文模式下会显示 `Set API key`），这是正常现象：页面已经打开，但 `/browse/*`、`/review/*`、`/maintenance/*` 等受保护接口还没授权。现在点击这个按钮会打开**首启配置向导**，你可以只把 `MCP_API_KEY` 保存到当前浏览器会话，也可以在“本地 checkout + 非 Docker 运行”场景下把常见运行参数写进 `.env`。这条写入路径现在只会写当前项目里的 `.env*` 文件。向导右上角也自带语言切换按钮，不需要先关掉弹窗才能切中文。当前状态有时会晚一点返回，但你已经自己输入过的字段不会再被后到的状态覆盖，没碰过的检索字段会继续按当前 setup 状态补齐。对带鉴权的非 loopback 访问路径，向导现在仍然会显示当前 setup 状态，但“保存到本地 `.env`”会继续保持禁用，并明确提示这是直连回环地址才允许的操作。如果后端已经带着 `MCP_API_KEY` 在跑，那么即使是这条 loopback 写入路径，也还要带上同一把有效 key。`MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` 只会放宽直连回环地址的读请求，不会放开这条本地写入门槛。第 5 节会继续说明本地验证方式。
>
> 这轮还有一个更收口的边界：第一次往本地 `.env` 保存时，`Dashboard API key` 现在必须非空；留空会被后端直接拒绝，不再把“空 key 首次落盘”当成默认自举路径。向导还会自动归一化 `/embeddings`、`/rerank`、`/chat/completions` 这类常见 provider API 后缀；格式不对或指到 link-local 的地址会在保存前直接拦下。`127.0.0.1` / `::1` 这类 loopback IP 字面量，再加上 `localhost`，仍然默认允许；如果你故意把 provider base 指到其它 private IP 字面量，或者指到一个解析后会落到 private 非 loopback 地址的 hostname，还要先通过 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` 显式放行。
>
> 如果你走的是标准 Docker 代理这类 proxy-held auth 路径，服务端鉴权已经生效时，首启配置向导现在不会只因为浏览器本地没保存 key 就一上来自动弹出；右上角按钮还可能在，但这时只有你手动点进去才会进入向导。
>
> 如果你这里只是点“只保存 Dashboard 密钥”，这把 key 现在会立刻在当前页面生效，不需要刷新再试；成功提示也会继续留在弹窗里，直到你自己手动关闭。
>
> 再补一个这轮按代码实际行为复核过的小细节：如果向导里显示的占位文本本身带 `&` 或 `<...>` 这类字符，现在会按普通文本正常显示，不会再把 HTML 实体原样露给用户。

> 如果你配置了 `MCP_API_KEY`，打开页面后请点右上角 `设置 API 密钥`（英文模式下会显示 `Set API key`），在向导里输入同一把 key；如果你只想先让 Dashboard 鉴权通过，优先选择“只保存 Dashboard 密钥”即可。
> 如果你启用了 `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`，本机回环地址上的直连请求可直接访问这些受保护数据接口。

> 如果你选择“只保存 Dashboard 密钥”，这把 key 会保存在当前浏览器会话里（`sessionStorage`），直到你手动清除或这次浏览器会话结束。向导里的“档位 C/D”预设（英文界面显示为 `Profile C/D`）现在只会帮你填一组建议字段，不代表 router 一定可达、embedding 维度已经对齐、或旧索引已经自动迁移。`Profile C` 预填的 `http://127.0.0.1:8001/v1` 是允许直接保存的真实本地 router 地址；真正会卡住保存的是 `https://router.example.com/v1`、`router-embedding-model`、`router-reranker-model` 这类示例占位值。现在真正保存到本地 `.env` 前，向导也会继续卡住缺失的远端必填字段，不会因为点了 C/D 预设就把表单伪装成已经可保存。对任何远端 embedding backend（`api` / `router` / `openai`）来说，本地 `.env` 保存前都会继续要求一个真实的正整数 `embedding_dim`。如果当前还没有任何 Dashboard 鉴权配置，而你第一次本地保存就把这批远端 provider 链字段一起填了，后端现在会先只落 Dashboard 鉴权相关字段；provider 链字段要等下一次带鉴权的保存再真正写入。`/embeddings`、`/rerank`、`/chat/completions` 这类常见 API 后缀会自动归一化；格式不对或指到 link-local 的 provider base 会在保存前直接拦下。`127.0.0.1` / `::1` 这类 loopback IP 字面量，再加上 `localhost`，仍然默认允许；如果你本机确实要直连其它 private IP 字面量，或者指到一个解析后会落到 private 非 loopback 地址的 hostname，还要额外补上 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS`。如果你本机的 router 还没准备好，就手动把检索字段切回直连 `api` / `openai` 模式排障；如果此时 reranker 还保持开启，就也要把直连 reranker 的 base/model 补齐，或者先把 reranker 关掉。如果你刚切了 embedding backend / model / dimension，也别忘了重启后端，必要时重建索引。手动打开向导时，当前代码会优先回填 `/setup/status` 的真实运行态；只有首启自动弹出且仍处在文档基线时，才继续用 `Profile A` 的起步表单。
>
> 现在向导在 `hash / api / router / openai` 之间来回切时，也会把已经隐藏掉的旧字段一起清掉；如果你切到远端 embedding backend，保存时只会写入你明确提供的 `RETRIEVAL_EMBEDDING_DIM`。这能减少“看起来已经切档，实际还带着上一档残留字段”的情况，但它不等于自动替你验证 provider 一定可达。
>
> 如果你当前是通过带鉴权的非 loopback 路径看这个页面，首启向导仍然能显示当前状态，但“保存到本地 `.env`”会继续保持禁用。这不是 UI 异常，而是现在明确保留的安全边界。

> 这个向导不会假装自己能热更新 Docker 容器里的 env / 代理配置。只要你改的是 embedding / reranker / write_guard / intent 这类后端运行参数，保存后仍然需要重启 `backend` / `sse`（Docker 路径则继续建议用 profile 脚本重启容器）。

> 前端会先恢复浏览器里已保存的语言；如果还没有保存值，常见中文浏览器语言（例如 `zh`、`zh-TW`、`zh-HK` 和其他 `zh-*`）会自动归并到 `zh-CN`，其他首次访问场景则回退到英文。如果你想手动切换，直接点右上角语言按钮即可，浏览器也会记住你的选择。

> 如果你用 Microsoft Edge 打开 Dashboard，当前前端现在会自动切到更轻量的视觉模式。说人话就是：功能、鉴权流程和配置向导都不变，但页面会改用静态背景、减轻 blur，并收掉一部分卡片动效，优先减少本地卡顿。其他浏览器仍然保持常规视觉效果。

> 前端开发服务器通过 `vite.config.js` 中配置的 proxy 将 `/api` 代理到 `MEMORY_PALACE_API_PROXY_TARGET`（默认 `http://127.0.0.1:8000`）。
>
> 如果你还想在 **Vite 本机开发入口** 下顺手验证同源 SSE，请先单独启动 `run_sse.py`，再额外设置：
>
> ```bash
> MEMORY_PALACE_SSE_PROXY_TARGET=http://127.0.0.1:8010
> ```
>
> 这样 `/sse`、`/messages` 和 `/sse/messages` 也会一起代理到本机 SSE 进程；不需要再手动改 CORS。
>
> 如果你做的是**非根路径部署**（例如前端最终挂在 `/memory-palace/`，后端 API 走 `/memory-palace/api`），前端构建时还可以额外设置 `VITE_API_BASE_URL`。默认情况下它仍然使用 `/api`，更适合本地 Vite proxy 和仓库自带 Docker 入口。当前前端里这层共享 SSE helper 也会跟着这个前缀去解析 `/sse`：没有浏览器侧鉴权时继续走原生 `EventSource`，有鉴权时切到可带 header 的 fetch-based SSE，所以带 basename 的部署不需要再额外把 SSE 手工改回站点根路径。现在只要浏览器里的 Dashboard 鉴权在运行中变化，前端就会额外发出一条 maintenance-auth 变更事件；Observability 也会利用这条事件，再加上重新聚焦标签页时的检查，在鉴权变更后或终态 `401` 之后重建带鉴权的 `/sse` 连接。这条 fetch-based SSE 现在还会在 `visibilitychange` / `pagehide` / `pageshow` / `beforeunload` 周期里暂停和恢复，并带指数退避重连与 idle watchdog，减少“页面已挂起但连接还半开着”这种本地调试噪音。
>
> 当前前端对这条路径也补过一轮实际行为复核：如果你把 `VITE_API_BASE_URL` 指到一个带前缀的 API 根路径，或者指到你自己的跨源 API 地址，浏览器里保存的 Dashboard 鉴权 key 现在也会继续附加到 `/browse`、`/review`、`/maintenance`、`/setup` 这些受保护请求上；但它仍然不会把这把 key 发到无关第三方绝对 URL。

<p align="center">
  <img src="images/setup-assistant-zh.png" width="900" alt="Memory Palace 首启配置向导（中文模式）" />
</p>

<p align="center">
  <img src="images/memory-zh.png" width="900" alt="Memory Palace 中文界面示例" />
</p>

---

## 4. Docker 部署

### 4.1 直接拉取 GHCR 预构建镜像（最省事的用户路径）

如果你本地构建环境总是出问题，优先走 GHCR 预构建镜像。这条路径的目标是**先把服务跑起来**，不是在你机器上重新 build 镜像。

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

`apply_profile` 会从仓库模板生成 `.env.docker`，并在覆盖已有目标前先备份。

默认访问地址：

| 服务 | 地址 |
|---|---|
| Frontend | `http://localhost:3000` |
| Backend API | `http://localhost:18000` |
| SSE | `http://localhost:3000/sse` |

这条路径要注意：

- 它绕开的是**本地镜像构建**，不是“完全不需要仓库 checkout”。你仍然需要当前仓库里的 `docker-compose.ghcr.yml`、`.env.example` 和 profile 脚本。
- 它解决的是 **Dashboard / API / SSE 服务启动**。
- 它**不会**自动帮你把本机上的 `skills / MCP / IDE host` 配置一起接好。
- 如果你还想用当前仓库现成的 repo-local skill + MCP 安装链路，保留这个 checkout，再继续看 `docs/skills/GETTING_STARTED.md`。
- 如果你不走 repo-local 安装链路，也可以手工把支持远程 SSE 的 MCP 客户端指到 `http://localhost:3000/sse`，并配置同一把 API key / 鉴权头。这里的 `<YOUR_MCP_API_KEY>` 默认就填刚生成的 `.env.docker` 里的 `MCP_API_KEY`。
- `scripts/run_memory_palace_mcp_stdio.sh` 不是 Docker 客户端入口。它依赖本地 `bash` 和 `backend/.venv`，只会复用宿主机上的本地 `.env` / `DATABASE_URL`，不会复用容器里的 `/app/data`。
- 如果你后面要切回本机 `stdio` 客户端，本地 `.env` 必须写宿主机可访问的绝对路径；如果仓库里只有 `.env.docker` 而没有本地 `.env`，或者 `.env` / 显式 `DATABASE_URL` 仍写成 `/app/...` 或 `/data/...` 这类容器路径，它都会明确拒绝启动，并提示改走本机路径或 Docker 暴露的 `/sse`。
- 仓库自带的 compose 文件在卷名默认值上使用了嵌套 `${...:-...}`。如果你本机的 Compose 实现较旧，或仍在用经典 `docker-compose`，这条手动路径可能会在 `docker compose up` 前就解析失败。遇到这种情况，优先改走 `docker_one_click.sh/.ps1`，或先显式设置 `MEMORY_PALACE_DATA_VOLUME` / `MEMORY_PALACE_SNAPSHOTS_VOLUME` / `COMPOSE_PROJECT_NAME`。
- 和 `docker_one_click.sh/.ps1` 不同，这条 GHCR compose 路径**不会自动换端口**。如果 `3000` / `18000` 已被占用，请在启动前显式设置 `MEMORY_PALACE_FRONTEND_PORT` / `MEMORY_PALACE_BACKEND_PORT`。
- 如果容器还要访问**你宿主机上的本地模型服务**，不要把容器侧地址写成 `127.0.0.1`。对容器来说，`127.0.0.1` 指向的是容器自己，不是你的宿主机。优先使用 `host.docker.internal`（或你的实际可达地址）。当前 compose 已显式补 `host.docker.internal:host-gateway`，Linux Docker 也能沿这条路径访问宿主机服务。

停止服务：

```bash
docker compose -f docker-compose.ghcr.yml down --remove-orphans
```

### 4.2 Docker 一键部署

```bash
# macOS / Linux
bash scripts/docker_one_click.sh --profile b

# Windows PowerShell
.\scripts\docker_one_click.ps1 -Profile b

# 若需把当前进程中的运行时 API 地址/密钥注入本次运行的 Docker env 文件（例如 profile c/d）
# 需显式开启注入开关（默认关闭）：
bash scripts/docker_one_click.sh --profile c --allow-runtime-env-injection
# 或
.\scripts\docker_one_click.ps1 -Profile c -AllowRuntimeEnvInjection
```

> 如果你在 `profile c/d` 下开启这类本地联调注入，脚本会把这次运行切到显式 API 模式，并额外强制 `RETRIEVAL_EMBEDDING_BACKEND=api`。当前注入链路会一起带上显式的 `RETRIEVAL_EMBEDDING_*`（包括 `RETRIEVAL_EMBEDDING_DIM`）、`RETRIEVAL_RERANKER_*` 和可选的 `INTENT_LLM_*` / `WRITE_GUARD_LLM_*` / `COMPACT_GIST_LLM_*`。当 `RETRIEVAL_EMBEDDING_API_*` / `RETRIEVAL_RERANKER_API_*` 没显式提供时，它会优先复用当前进程里的 `ROUTER_API_BASE/ROUTER_API_KEY` 作为兜底；如果你还设置了 `INTENT_LLM_*`，这条链路也会一并注入。这个模式更适合本地排障，不等于你正在验证最终发布口径的 `router` 模板。
>
> 当前这条 `profile c/d + --allow-runtime-env-injection` 本地联调路径也已经重新复验过。现在脚本会先把这次运行的模板占位符校验延后到运行时注入值落盘之后，再继续做 fail-closed 检查；也就是说，模板里的占位符不再会在你真实值写进去之前提前挡住这条本地排障路径。
>
> 如果你只是想先做一轮快速 smoke check，先直接打真实的 `/embeddings` 和 `/rerank` 端点，带上你准备实际使用的 model 和 key，通常会比一上来先跑完整 backend 更快。
>
> 但要注意：`--runtime-env-mode` / `--runtime-env-file` **不是** `docker_one_click.sh/.ps1` 的参数。如果你把这两个参数直接传给一键脚本，命令会报 `Unknown argument`。公开仓用户做 `profile c/d` 本地联调时，继续使用上面这条显式注入命令即可；如果你还要做更严格的发布复验，请回到你实际部署时会使用的 `.env` / router 配置，再单独跑那条验证路径。

> `docker_one_click.sh/.ps1` 默认会为**每次运行**生成独立的临时 Docker env 文件，并通过 `MEMORY_PALACE_DOCKER_ENV_FILE` 传给 `docker compose`；只有显式设置该环境变量时才会复用指定文件，而不是固定共享 `.env.docker`。
>
> 同一 checkout 下的并发部署会被 deployment lock 串行化；若已有另一条一键部署在执行，后续进程会直接退出并提示稍后重试。
>
> 对 macOS / Linux 的 shell 路径来说，如果你显式把 `MEMORY_PALACE_DOCKER_ENV_FILE` 指到一份自定义文件，`docker_one_click.sh` 现在也会在那个文件同目录生成临时文件再替换回去，减少目标文件不在默认临时目录时出现跨文件系统替换问题的概率。
>
> 另外，如果你显式设置了 `MEMORY_PALACE_DOCKER_ENV_FILE`，`docker_one_click.sh/.ps1` 现在都会先把它解析成稳定路径，再交给 profile 脚本和后续 `docker compose` 共用。说人话就是：就算你从别的目录发命令，也不容易再出现“脚本写的是一份文件，compose 读的是另一份文件”。
>
> 当前本地 build 路径还会使用按 checkout 固定的本地镜像名。所以只要这个 checkout 里已经成功 build 过一次，即使你换了 `COMPOSE_PROJECT_NAME`，后续再跑 `--no-build` 也能继续复用这些镜像；只有第一次启动或你手动删掉本地镜像时，才需要重新 `--build`。
>
> 如果 Docker env 文件里的 `MCP_API_KEY` 为空，`apply_profile.*` 会自动生成一把本地 key。Docker 前端会在代理层自动带上这把 key，所以**按推荐的一键脚本路径启动时**，受保护请求通常已经能直接使用；但页面右上角仍可能继续显示 `设置 API 密钥`（英文模式下会显示 `Set API key`），因为浏览器页面本身并不知道代理层的真实 key。即便看到了按钮，首启配置向导在 Docker 场景下也会明确停留在“说明模式”，不会伪装成已经持久化容器 env。
>
> 如果代理层鉴权已经生效，首启配置向导现在也不会再自己误弹出来。更稳的判断方法还是先看受保护数据能不能直接打开，而不是只盯着右上角按钮在不在。
>
> 当前 Docker Compose 会先等 `backend` 的 `/health` 通过，同时一键脚本还会补做一次前端代理 `/sse` 的可达性检查，才把 frontend 视为真正 ready。也就是说，容器刚显示 `running` 时，页面可能还会晚几秒才真正可用，这属于正常现象。
>
> backend 容器侧的检查现在也不再是“`/health` 只要回 `200` 就算好”，而是会继续执行 `deploy/docker/backend-healthcheck.py`，确认返回 payload 里的 `status == "ok"`。如果详细 `/health` 已经降级，Docker 也会把 backend 继续视为 unhealthy；若请求失败、返回了非法 JSON，或状态不是 `ok`，这个脚本还会先打印一条简短失败原因，排障时比单纯看 exit code 更直接。
>
> 本地 readiness / health probe 现在还会把已有的 `NO_PROXY` / `no_proxy` 和 `127.0.0.1`、`localhost`、`::1`、`host.docker.internal` 合并起来，再去探测 loopback 地址。这样即使宿主机本身开了代理，本机 `/health`、`/sse` 这类探活也不容易被误送去代理。
>
> 如果你的环境启动比较慢，还可以通过 `MEMORY_PALACE_BACKEND_HEALTHCHECK_TIMEOUT_SEC` 调整这条探活请求的超时；当前脚本默认值是 `5` 秒。
>
> WAL 风险边界也请一起记住：仓库默认只把“Docker **named volume** + WAL”当成受支持路径。如果你把 backend 的 `/app/data` 改成 NFS/CIFS/SMB 或其它网络文件系统 bind mount，就必须显式切回 `MEMORY_PALACE_DOCKER_WAL_ENABLED=false` 和 `MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete`。当前 `docker_one_click.sh/.ps1` 已经会在 `docker compose up` 前做这层 preflight，并在发现高风险组合时直接拒绝启动；但手动 `docker compose up` / `docker compose -f docker-compose.ghcr.yml up` 不会代你做这一步。
>
> 当前 Docker 前端还会对 `/index.html` 返回 `Cache-Control: no-store, no-cache, must-revalidate`，尽量减少“前端已经更新，但浏览器还拿着旧入口页面”的情况。如果你刚升级完镜像仍看到明显旧页面，先确认容器已经是新版本，再手动刷新一次页面；只有在你额外接了自己的反向代理或企业缓存层时，才需要继续检查这些中间层是否改写了缓存头。
>
> Docker 默认还会分别持久化两类运行期数据：数据库卷会按 compose project 隔离为 `<compose-project>_data`（容器内 `/app/data`），Review snapshots 会隔离为 `<compose-project>_snapshots`（容器内 `/app/snapshots`）。如果你确实要复用旧的共享卷，请显式设置 `MEMORY_PALACE_DATA_VOLUME` / `MEMORY_PALACE_SNAPSHOTS_VOLUME`。如果你执行 `docker compose down -v` 或手动删除这些卷，这两部分都会一起清空。
>
> **C/D 本地联调建议**：
>
> - 如果你本机的 `router` 还没接好 embedding / reranker / llm，可以先直接分别配置 `RETRIEVAL_EMBEDDING_*`、`RETRIEVAL_RERANKER_*`、`WRITE_GUARD_LLM_*` / `COMPACT_GIST_LLM_*`。
> - 这样更容易判断到底是哪一条链路不可达，不会把“某个模型没配好”误判成整个系统不可用。
> - 无论你最终采用 `router` 方案，还是分别直配 `RETRIEVAL_EMBEDDING_*` / `RETRIEVAL_RERANKER_*`，都建议按**最终实际部署配置**重新跑一次启动与健康检查。

> 脚本会自动执行以下步骤：
>
> 1. 调用 Profile 脚本生成本次运行使用的 Docker env 文件（默认临时文件；若显式设置 `MEMORY_PALACE_DOCKER_ENV_FILE` 则复用指定路径）
> 2. 默认不读取当前进程环境变量覆盖模板策略键（避免隐式改档）；仅在显式开启注入开关时注入 API 地址/密钥/模型字段，以及 `RETRIEVAL_EMBEDDING_DIM` 这类显式检索参数
> 3. 检测端口占用并自动寻找可用端口
> 4. 解析并注入 Docker 持久化卷：默认按 compose project 生成隔离卷名（数据库 `<compose-project>_data`，Review snapshots `<compose-project>_snapshots`）；只有显式设置 `MEMORY_PALACE_DATA_VOLUME` / `MEMORY_PALACE_SNAPSHOTS_VOLUME` 时才复用旧卷
> 5. 若 backend `/app/data` 被改成 NFS/CIFS/SMB 等网络文件系统 bind mount，且本次配置仍会启用 WAL，则在启动前直接 fail-fast
> 6. 对同一 checkout 的并发部署加锁，避免多次 `docker_one_click` 互相覆盖
> 7. 通过 `docker compose` 构建并启动容器

默认访问地址：

| 服务 | 地址 |
|---|---|
| Frontend | `http://localhost:3000` |
| Backend API | `http://localhost:18000` |
| SSE | `http://localhost:3000/sse` |
| Health Check | `http://localhost:18000/health` |

> **端口映射说明**（来自 `docker-compose.yml`）：
>
> - 前端容器内部运行在 `8080` 端口，对外映射到 `3000`（可通过 `MEMORY_PALACE_FRONTEND_PORT` 环境变量覆盖）
> - 后端容器内部运行在 `8000` 端口，对外映射到 `18000`（可通过 `MEMORY_PALACE_BACKEND_PORT` 环境变量覆盖）
> - Docker 默认同时持久化数据库卷（`/app/data`）和 review snapshot 卷（`/app/snapshots`）
>
> 当前默认不会暴露 Swagger `/docs`；直接访问一般会得到 `404`。接口说明优先看本文、[TECHNICAL_OVERVIEW.md](TECHNICAL_OVERVIEW.md) 和 [TOOLS.md](TOOLS.md)。

停止服务：

```bash
COMPOSE_PROJECT_NAME=<控制台打印出的 compose project> docker compose -f docker-compose.yml down --remove-orphans
```

> 上面的 `down --remove-orphans` 不会删除数据卷；只有显式使用 `docker compose ... down -v`，或手动删除对应 volume 时，数据库和 review snapshots 才会一起被清空。

> 如果你需要验证 Windows 路径，建议直接在目标 Windows 环境里补跑一次启动与 smoke。

### 4.3 备份当前数据库

在做批量测试、迁移验证或大范围配置切换前，建议先做一次 SQLite 一致性备份：

```bash
# macOS / Linux
bash scripts/backup_memory.sh

# 指定 env / 输出目录
bash scripts/backup_memory.sh --env-file .env --output-dir backups

# 只保留最近 10 份备份
bash scripts/backup_memory.sh --env-file .env --output-dir backups --keep 10
```

```powershell
# Windows PowerShell
.\scripts\backup_memory.ps1

# 只保留最近 10 份备份
.\scripts\backup_memory.ps1 -EnvFile .env -OutputDir backups -Keep 10
```

> 备份文件默认写入 `backups/`。如果你准备分享仓库或打包交付，通常不需要把它一并带上。
>
> 这两条备份脚本都会先读取你指定 env 文件里的 `DATABASE_URL`，自动去掉可选的 query / fragment（例如 `?mode=...`、`#...`），再对实际 SQLite 文件做一致性备份。原生 Windows 优先用 `backup_memory.ps1`；`Git Bash` / `WSL` 继续用 `backup_memory.sh` 即可。当前这两条脚本都会先给源/目标连接加 `busy_timeout`，再按小批量页面做增量 backup；如果中途失败，也都会清理半成品备份文件，避免留下看起来像成功的空备份。备份文件名现在统一使用 UTC 时间戳，这样宿主机和 Docker/容器环境混用时排序更一致。默认还会只保留最近 `20` 份备份；如果你想自己控留存数，用 `--keep <count>` / `-Keep <count>` 即可，传 `0` 则表示不做轮转。
>
> 如果你只是想先看脚本用法，直接运行 `bash scripts/backup_memory.sh --help` 或 `.\scripts\backup_memory.ps1 -?`。原生 Windows 的 PowerShell 脚本现在也会优先检查仓库里的 `backend/.venv`，找不到时再回退到常见的 `python3` / `py`，正常本地仓库环境一般不需要额外改 PATH。

### 4.4 哪些文件通常不需要提交

当前仓库已经把以下典型本地产物放入 `<repo-root>/.gitignore`：

- 环境与密钥文件：`.env`、`.env.*`（保留 `.env.example`）
- 运行期数据库：`*.db`、`*.sqlite`、`*.sqlite3`
- 数据库锁文件：`*.init.lock`、`*.migrate.lock`
- 本地工具配置：`.mcp.json`、`.mcp.json.bak`、`.claude/`、`.codex/`、`.cursor/`、`.opencode/`、`.gemini/`、`.agent/`、`.playwright-cli/`
- 本地缓存与临时目录：`.tmp/`、`.pytest_cache/`、`backend/.pytest_cache/`
- 前端本地产物：`frontend/node_modules/`、`frontend/dist/`
- 日志与快照：`*.log`、`snapshots/`、`backups/`
- 临时测试草稿：`frontend/src/*.tmp.test.jsx`
- 维护期内部文档：`docs/improvement/`、`backend/docs/benchmark_*.md`
- 一次性对照摘要：`docs/evaluation_old_vs_new_*.md`
- 本地验证报告：`docs/skills/TRIGGER_SMOKE_REPORT.md`、`docs/skills/MCP_LIVE_E2E_REPORT.md`

如果你准备分享项目、打包交付，或者只是想做一次环境自检，建议执行：

```bash
bash scripts/pre_publish_check.sh
```

它会检查常见本地敏感产物、工具配置、本地验证报告、个人路径和 `.env.example` 占位项，帮你快速确认仓库是否适合直接交付。若只是发现这些本地文件存在，通常会给出 `WARN`，提醒你在分享前自己确认。

如果你额外运行下面这些验证脚本：

```bash
python scripts/evaluate_memory_palace_skill.py
cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py
```

脚本默认会分别在 `<repo-root>/docs/skills/TRIGGER_SMOKE_REPORT.md` 和 `<repo-root>/docs/skills/MCP_LIVE_E2E_REPORT.md` 生成摘要。这两份结果主要用于本地复核，不是主说明文档。当前脚本还会自动脱敏常见 secret、session token 和本地绝对路径，并在宿主支持时改用更私有的文件权限。`evaluate_memory_palace_skill.py` 现在只要任一检查是 `FAIL` 就会返回非零退出码；`SKIP` / `PARTIAL` / `MANUAL` 不会单独让进程失败。如果你只想在本机临时换一套 Gemini smoke 模型，可设置 `MEMORY_PALACE_GEMINI_TEST_MODEL`；如果还要把 fallback 模型单独改开，再额外设置 `MEMORY_PALACE_GEMINI_FALLBACK_MODEL`。如果 `codex exec` 在 smoke 超时前没有产出结构化输出，`codex` 那一项会记成 `PARTIAL`，而不是把整轮卡住。
如果你在并行 review 或 CI 里想隔离输出，也可以先设置 `MEMORY_PALACE_SKILL_REPORT_PATH` / `MEMORY_PALACE_MCP_E2E_REPORT_PATH`。这两个变量如果写相对路径，脚本现在会自动把结果放到系统临时目录下的 `memory-palace-reports/`，避免把日志类产物直接落进当前仓库；如果你想完全自己控制位置，优先传仓库外的绝对路径。
如果你是刚 clone 下来的 GitHub 仓库，暂时看不到这两份文件也正常；它们是运行脚本后才生成的本地产物。

---

## 5. 首次验证

> 这里的检查以“先跑通系统”为主；如果你需要额外的本地 Markdown 验证摘要，再运行上面的验证脚本即可。
>
> 当前公开验证快照（2026-05-15）：backend `1382 passed, 22 skipped`，frontend `203 passed`；
> 前端 typecheck/build、i18n audit、bundle budget、repo-local live MCP e2e，
> 以及 Docker/profile/SSE/script 重点契约通过。真实 A/B/C/D benchmark 表未重算；
> 原生 Windows / Linux host runtime 仍需目标环境复核。

### 5.1 健康检查

```bash
# 本地开发
curl -fsS http://127.0.0.1:8000/health

# Docker 部署
curl -fsS http://localhost:18000/health
```

预期返回（来自 `main.py` 的 `/health` 端点）：

```json
{
  "status": "ok",
  "timestamp": "2026-02-19T08:00:00Z",
  "index": {
    "index_available": true,
    "degraded": false
  },
  "runtime": {
    "write_lanes": { ... },
    "index_worker": { ... }
  }
}
```

> 上面这类带 `index` / `runtime` 的详细 payload，默认只会返回给本机 loopback 请求，或带有效 `MCP_API_KEY` 的请求。未鉴权的远端 `/health` 调用只会拿到 `status` 和 `timestamp` 这类浅健康信息。
>
> `status` 为 `"ok"` 表示系统正常；若 index 不可用或报错，`status` 会变为 `"degraded"`。对本机 loopback 或带有效 key 的这类**详细健康检查**，当前一旦进入降级态，HTTP 状态码也会直接变成 `503`，方便 Docker 健康检查和运维探活把它当成“未就绪”；未鉴权远端的浅健康结果仍保持 `200`。

### 5.2 浏览记忆树

```bash
curl -fsS "http://127.0.0.1:8000/browse/node?domain=core&path=" \
  -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>"
```

> 此端点来自 `api/browse.py` 的 `GET /browse/node`，用于查看指定域下的记忆节点树。`domain` 参数对应 `.env` 中 `VALID_DOMAINS` 配置的域名。
>
> - 如果你配置了 `MCP_API_KEY`，请像上面这样带 `X-MCP-API-Key`
> - 如果你启用了 `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`，并且请求来自本机回环地址（且没有 forwarded headers），也可以直接省略鉴权头
>
> 当前 Dashboard 里通过 `/browse` 成功写入的新内容，后续也已经能直接喂给 reflection workflow。说人话就是：你在 Dashboard 里新建或改完内容后，再走 `/maintenance/learn/reflection`，不应该再因为“这次写入来自 Dashboard”卡在 `session_summary_empty`。

### 5.3 查看接口说明

当前后端默认不会公开 `http://127.0.0.1:8000/docs`；直接访问一般会返回 `404`。这是默认安全边界，不是启动失败。

如果你要核对接口：

- 先看本文第 5 节和第 6 节
- 再看 [TECHNICAL_OVERVIEW.md](TECHNICAL_OVERVIEW.md) 里的 HTTP / MCP 总览
- 要看最精确的当前行为，直接看 `backend/tests/` 里的接口测试

---

## 6. MCP 接入

Memory Palace 通过 [MCP 协议](https://modelcontextprotocol.io/) 提供 **9 个工具**（定义在 `mcp_server.py`）：

| 工具名 | 用途 |
|---|---|
| `read_memory` | 读取记忆（支持 `system://boot`、`system://index` 等特殊 URI） |
| `create_memory` | 创建新记忆节点（建议显式填写 `title`） |
| `update_memory` | 更新已有记忆（优先使用 diff patch） |
| `delete_memory` | 删除记忆节点 |
| `add_alias` | 为记忆节点添加别名 |
| `search_memory` | 搜索记忆（keyword / semantic / hybrid 三种模式） |
| `compact_context` | 压缩上下文（清理旧会话日志） |
| `rebuild_index` | 重建搜索索引 |
| `index_status` | 查看索引状态 |

### 6.1 stdio 模式（推荐本地使用）

```bash
cd backend
python mcp_server.py

# 如果你是在新终端或客户端配置里启动，下面这条更稳
./.venv/bin/python mcp_server.py   # Windows PowerShell：.\.venv\Scripts\python.exe mcp_server.py
```

> `stdio` 模式下 MCP 工具直接通过进程的标准输入/输出通信，**不经过 HTTP/SSE 鉴权层**，无需配置 `MCP_API_KEY` 即可使用。
>
> 这里的 `python mcp_server.py` 默认你还在使用 **Step 2 里创建并装好依赖的 `backend/.venv`**。如果你换了一个新终端，或者是在客户端里单独配置本地 MCP，优先直接用项目自己的 `.venv` 解释器。否则会在 MCP 进程真正启动前就报 `ModuleNotFoundError: No module named 'sqlalchemy'` 这类错误。
>
> 如果你是在客户端配置里接入 MCP，优先按平台选 repo-local wrapper：
>
> - 原生 Windows：`python backend/mcp_wrapper.py`
> - macOS / Linux / Git Bash / WSL：`bash scripts/run_memory_palace_mcp_stdio.sh`
>
> 这两条 repo-local wrapper 的边界保持一致：都依赖本地 `backend/.venv`，优先复用当前仓库的 `.env` / `DATABASE_URL`；如果 `.env` 里已经设置了 `RETRIEVAL_REMOTE_TIMEOUT_SEC`，它们也会继续复用这个值；没设置时 repo-local 默认仍是 `8` 秒。只有在仓库里既没有本地 `.env`、也没有 `.env.docker` 时，才会回退到仓库默认 SQLite 路径。若仓库里只有 `.env.docker`，或者本地 `.env` / 显式 `DATABASE_URL` 仍写成 Docker 容器内路径（例如 `sqlite+aiosqlite:////app/data/memory_palace.db`、`sqlite+aiosqlite://///app/data/memory_palace.db`、大写 `/APP/...` 变体、你自己改成 `/data/...` 的变体，或 `sqlite+aiosqlite:////%2Fapp%2Fdata/...` 这种 URL 编码变体），它们都会明确拒绝启动，并提示你改走 Docker 暴露的 `/sse` 或改回宿主机绝对路径。像 `sqlite+aiosqlite:///demo.db` 这种相对 sqlite 路径，现在也不会再被放过。
>
> 对 shell wrapper 这条路径来说，`run_memory_palace_mcp_stdio.sh` 现在还会在启动 Python 前先导出 `PYTHONIOENCODING=utf-8` 和 `PYTHONUTF8=1`。说人话就是：如果当前 shell 不是 UTF-8 默认环境，本地 stdio 也更不容易因为编码问题出错。
>
> 现在这两条 repo-local wrapper 都会把已有的 `NO_PROXY` / `no_proxy` 合并起来，并额外补上 `localhost`、`127.0.0.1`、`::1`、`host.docker.internal`。说人话就是：如果你本机同时跑 Ollama 或别的 OpenAI-compatible 服务，本地 stdio 更不容易被宿主机代理误伤。这里说的是仓库自带的两条 repo-local wrapper，不等于所有后端启动方式都会自动补这一层保护。

### 6.2 SSE 模式

```bash
cd backend
HOST=127.0.0.1 PORT=8010 python run_sse.py
```

```powershell
cd backend
$env:HOST = "127.0.0.1"
$env:PORT = "8010"
python run_sse.py
```

> `run_sse.py` 本地默认会优先尝试监听 `127.0.0.1:8000`；如果本机的 `8000` 已被主后端占用，它会自动回退到 `127.0.0.1:8010`。如果你显式设置的是 `HOST=::1`，它会单独检查 `::1:8000`，不会因为 IPv4 的 `8000` 被占用就误回退。发生这类回退时，当前启动日志也会明确打印最终 `/sse` 地址，并提醒你更新客户端配置或显式设置 `PORT`。你也可以显式设置 `HOST` 和 `PORT`。只有在你真要给远程客户端接入时，才显式设置 `HOST=0.0.0.0`（或你的实际绑定地址）。SSE 模式仍受 `MCP_API_KEY` 鉴权保护。
>
> 同一个 SSE 进程还会提供一个轻量级 `/health` 端点，主要给本地独立调试做就绪检查；真正对 MCP 客户端开放的流式入口仍然是 `/sse`。
>
> 这条本地 operator 路径现在就算 `/sse` 连接仍然活着，直接停止 `run_sse.py` 也会安静退出，不再额外打印之前那条 ASGI shutdown traceback。
>
> 上面这条命令故意绑定到 `127.0.0.1`，更适合本机调试。如果你真的需要让其他机器访问，再把 `HOST` 改成 `0.0.0.0`（或你的实际监听地址）。这会让远程客户端可以连上监听地址，但 API Key、反向代理、防火墙和传输层安全仍然要你自己补齐。
>
> 如果你使用 Docker / Compose，SSE 不再由独立 `sse` 容器承载，而是直接挂在 `backend` 进程内，再通过前端代理暴露在 `http://127.0.0.1:3000/sse`。这样 Docker 路径下只有 `backend + frontend` 两个服务，但远程客户端看到的 `/sse`、`/messages`、`/sse/messages` 入口保持不变。
>
> 也请把这个 Docker 前端端口当成可信管理入口，而不是“带终端用户鉴权的公网入口”。只要有人能直接访问 `3000`，他就能使用 Dashboard 以及被代理的受保护接口；如果要暴露到受信网络之外，请先加你自己的 VPN、反向代理鉴权或网络访问控制。
>
> 上面的 `HOST=127.0.0.1 PORT=8010` 示例是**本机回环**写法。只有在你确实要开放给远程客户端时，才改为 `HOST=0.0.0.0`（或目标绑定地址），并自行补齐网络侧安全控制。
>
> 如果你自己用 `curl` 或脚本先连了一次 `/sse`，然后把这条连接断掉，再单独往 `/messages` 发同一个 `session_id`，看到 `404` / `410` 是正常的：这表示前一条 SSE session 已经关闭。真正的正常链路应该是“先保持 `/sse` 连接活着，再由客户端继续往 `/messages` 发请求”。

### 6.2.1 多客户端并发（可选，但建议提前配好）

如果你会让多个 CLI / IDE 宿主同时指向**同一份 SQLite 库**，建议在 `.env` 里显式加上这组配置：

```env
RUNTIME_WRITE_WAL_ENABLED=true
RUNTIME_WRITE_JOURNAL_MODE=wal
RUNTIME_WRITE_WAL_SYNCHRONOUS=normal
RUNTIME_WRITE_BUSY_TIMEOUT_MS=5000
```

这几项的作用可以直接理解成：

- 每个 stdio MCP 客户端通常都是独立 Python 进程
- 不同进程不会共享同一把进程内写锁，只能靠 SQLite 文件锁协调
- 打开 WAL 并适当增大 `busy_timeout`，能明显降低多客户端同时写入时的 `database is locked`

补一句当前默认口径：

- 如果你走的是仓库自带的 Docker / GHCR compose 路径，compose 已经默认把 journal mode 强制改成 `wal`
- 上面这组 `.env` 主要还是给 **repo-local stdio / 本地手动多进程** 这类路径准备的

### 6.3 客户端配置示例

**stdio 模式**

原生 Windows（优先这一条）：

```json
{
  "mcpServers": {
    "memory-palace": {
      "command": "python",
      "args": ["/ABS/PATH/TO/REPO/backend/mcp_wrapper.py"]
    }
  }
}
```

macOS / Linux / Git Bash / WSL：

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

> 如果你还没创建 `backend/.venv`，先回到 **Step 2** 完成虚拟环境和依赖安装。
>
> Windows 原生环境优先直接走 `python + backend/mcp_wrapper.py`。只有在你本来就准备好了 Git Bash / WSL 的情况下，才继续用 `bash + run_memory_palace_mcp_stdio.sh` 这条组合。
>
> 如果某个 Windows 风格宿主最后还是把 `backend/mcp_wrapper.py` 跑在了 `Git Bash / MSYS / Cygwin` 这类环境里，当前 wrapper 也会优先尝试 `.venv/Scripts/python.exe`。这只是兜底行为，不改变上面的推荐路径。

**SSE 模式**：

```json
{
  "mcpServers": {
    "memory-palace": {
      "url": "http://127.0.0.1:8010/sse"
    }
  }
}
```

> ⚠️ 请将这里的 `127.0.0.1:8010` 替换为你实际启动 `run_sse.py` 时使用的监听地址和端口。
>
> ⚠️ SSE 仍受 `MCP_API_KEY` 保护。多数客户端还需要额外配置请求头或 Bearer Token；具体字段名请以客户端自己的 MCP 文档为准。
>
> ⚠️ `HOST=0.0.0.0` 只表示“允许远程连接到这个监听地址”，不表示“允许无鉴权访问”。

### 6.3.1 当前已验证到什么程度

如果你只想手工把客户端接到 Docker 暴露出来的 `/sse`，当前公开口径建议分成两类看：

| 客户端 | 当前公开口径 | 推荐写法 |
|---|---|---|
| `Claude Code` | 已有官方 CLI 选项，可直接写远程 SSE | 可直接按下面示例配置 |
| `Gemini CLI` | 已有官方 CLI 选项，可直接写远程 SSE | 可直接按下面示例配置 |
| `Codex CLI` | 当前公开依据是远程 `--url`（streamable HTTP） | 这个仓库今天先推荐 repo-local stdio 路径 |
| `OpenCode` | 当前公开依据是通用 `remote + url` 结构 | 这个仓库今天先推荐 repo-local 路径；手工远程接法只建议熟悉 OpenCode 配置的人使用 |

也就是说：

- 如果你现在就是想手工把客户端接到 `http://localhost:3000/sse`
- **优先支持的公开路径是 `Claude Code` 和 `Gemini CLI`**
- `Codex` / `OpenCode` 当前不要在这个仓库里写成“已经验证过的直接 `/sse` 产品级路径”

### 6.3.2 Claude Code 手工接 `/sse`

```bash
claude mcp add \
  --transport sse \
  --scope project \
  --header "X-MCP-API-Key: <YOUR_MCP_API_KEY>" \
  memory-palace \
  http://127.0.0.1:3000/sse
```

> 如果你刚按上面的 GHCR / Docker 路径生成了 `.env.docker`，这里的 `<YOUR_MCP_API_KEY>` 默认就填那个文件里的 `MCP_API_KEY`。

检查：

```bash
claude mcp list
```

说明：

- `Claude Code` 当前官方 CLI 同时支持 `stdio`、`sse`、`http`
- 公开文档里仍以 `/sse` 作为规范入口；`/sse/` 现在只是兼容写法，也会被转发到同一条后端 SSE 链路
- 如果未来 Memory Palace 公开提供了更明确的 HTTP / streamable HTTP MCP 入口，优先按官方推荐切到 `http`
- 就当前仓库公开暴露的远程入口来说，用户可直接连接的是 `/sse`

### 6.3.3 Gemini CLI 手工接 `/sse`

```bash
gemini mcp add \
  --transport sse \
  --scope project \
  --header "X-MCP-API-Key: <YOUR_MCP_API_KEY>" \
  memory-palace \
  http://127.0.0.1:3000/sse
```

> 如果你刚按上面的 GHCR / Docker 路径生成了 `.env.docker`，这里的 `<YOUR_MCP_API_KEY>` 默认就填那个文件里的 `MCP_API_KEY`。

检查：

```bash
gemini mcp list
```

如果你更喜欢手改 `settings.json`，当前公开可确认的最小骨架仍然是：

```json
{
  "mcpServers": {
    "memory-palace": {
      "url": "http://127.0.0.1:3000/sse",
      "headers": {
        "X-MCP-API-Key": "<YOUR_MCP_API_KEY>"
      }
    }
  }
}
```

### 6.3.4 为什么这里没有直接给 `Codex / OpenCode` 的 `/sse` 抄写版

不是因为它们一定不支持远程 MCP，而是因为当前公开证据不足以让这个仓库把 `/sse` 直连写成“已经验证过、用户照抄即可”的口径：

- `Codex CLI` 当前公开可确认的是 `codex mcp add <name> --url <URL>` 对应远程 MCP / streamable HTTP
- `OpenCode` 当前公开可确认的是通用 `type = remote` / `url` 结构
- 但这个仓库今天公开暴露和已验证的远程入口是 `/sse`

所以为了不误导用户：

- `Codex / OpenCode` 当前优先继续按 repo-local 安装路径走
- 等我们补齐它们对 `Memory Palace /sse` 的实际验证后，再把那部分写成公开可照抄文档

---

## 7. HTTP/SSE 接口鉴权

Memory Palace 的部分 HTTP 接口受 `MCP_API_KEY` 保护，采用 **fail-closed** 策略（未配置 Key 时默认返回 `401`）。

### 受保护的接口

| 路由前缀 | 说明 | 鉴权方式 |
|---|---|---|
| `/maintenance/*` | 维护接口（孤立节点清理等） | `require_maintenance_api_key` |
| `/review/*` | 审查接口（内容审核流程） | `require_maintenance_api_key` |
| `/browse/*`（GET/POST/PUT/DELETE） | 记忆树读写操作 | `require_maintenance_api_key` |
| `run_sse.py` 的 `/sse` 与 `/messages` | MCP SSE 传输通道与消息入口 | `apply_mcp_api_key_middleware` |

### 鉴权方式

后端支持两种 Header 传递 API Key（定义在 `api/maintenance.py` 和 `run_sse.py`）：

```bash
# 方式一：自定义 Header
curl -fsS http://127.0.0.1:8000/maintenance/orphans \
  -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>"

# 方式二：Bearer Token
curl -fsS http://127.0.0.1:8000/maintenance/orphans \
  -H "Authorization: Bearer <YOUR_MCP_API_KEY>"
```

### 前端鉴权配置

如果前端也需要访问受保护接口，可以在**本地调试或你自己控制的私有部署环境**里注入运行时配置（前端 `src/lib/api.js` 会读取 `window.__MEMORY_PALACE_RUNTIME__`）：

```html
<script>
  window.__MEMORY_PALACE_RUNTIME__ = {
    maintenanceApiKey: "<YOUR_MCP_API_KEY>",
    maintenanceApiKeyMode: "header"
  };
</script>
```

> 不要把真实 `MCP_API_KEY` 写进任何公开页面、共享静态资源或会交付给最终用户的 HTML 里。浏览器里可以直接读取这个全局对象。

> 这段配置主要用于**本地手动启动前后端**的场景。
>
> Docker 一键部署默认不需要把 key 写进页面：前端容器会在代理层把同一把 `MCP_API_KEY` 转发到受保护的 Dashboard API 路径、`/sse` 和 `/messages`。通用 `/api/*` 不会一律注入这把 key。

### 本地调试跳过鉴权

如果在本地开发时不想配置 API Key，可在 `.env` 中设置：

```env
MCP_API_KEY_ALLOW_INSECURE_LOCAL=true
```

> 此选项仅对来自 `127.0.0.1` / `::1` / `localhost` 的**直连请求**生效；如果请求带有 forwarded headers，仍会被拒绝。它只影响 HTTP/SSE 接口，**不影响** stdio 模式（stdio 不经过鉴权层）。

---

## 8. 常见新手问题

| 问题 | 原因与解决 |
|---|---|
| 启动后端时 `ModuleNotFoundError` | 最常见原因是没用 `backend/.venv`，或者没在这个环境里安装依赖。先执行 `source .venv/bin/activate && pip install -r requirements.txt`；如果是本地 stdio MCP，再优先改用 `./.venv/bin/python mcp_server.py`（Windows：`.\.venv\Scripts\python.exe mcp_server.py`） |
| `DATABASE_URL` 报错 | 路径建议使用绝对路径，并且要带 `sqlite+aiosqlite:///` 前缀。示例：`sqlite+aiosqlite:////absolute/path/to/memory_palace.db` |
| 本地 stdio MCP 在客户端里报 `startup failed`、`initialize response` 或类似启动中断 | 先检查 `.env` 或显式 `DATABASE_URL` 是否写成了 `/app/...` 或 `/data/...` 这类容器路径。那是 Docker 内部路径，`scripts/run_memory_palace_mcp_stdio.sh` 会直接拒绝启动；改成宿主机可访问的绝对路径，或继续走 Docker `/sse`。 |
| 前端访问 API 返回 `502` 或 `Network Error` | 确认后端已启动且运行在 `8000` 端口。检查 `vite.config.js` 中 proxy 目标与后端端口是否一致 |
| 受保护接口返回 `401` | 本地手动启动：配置 `MCP_API_KEY` 或设置 `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`；Docker：优先确认是否使用 `apply_profile.*` / `docker_one_click.*` 生成的 Docker env 文件 |
| SSE `/messages` 返回 `429` 或 `413` | `429` 说明同一客户端主体短时间内 POST 太多；当前分桶优先看解析后的客户端地址，带鉴权时还会叠加鉴权 token 的稳定哈希，所以单纯重连换一个新的 `session_id` 已经不能直接把限流桶清零。先检查客户端是否有重复重试或死循环。`413` 说明单次请求体超过 `SSE_MESSAGE_MAX_BODY_BYTES`，需要缩小 payload 或调整后端限制 |
| Docker 启动端口冲突 | `docker_one_click.sh` 默认会自动寻找空闲端口。也可通过 `--frontend-port` / `--backend-port` 手动指定 |

更多问题排查请参考 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。

---

## 9. 继续阅读

| 文档 | 内容 |
|---|---|
| [DEPLOYMENT_PROFILES.md](DEPLOYMENT_PROFILES.md) | 部署档位（A/B/C/D）参数详解与选择指南 |
| [TOOLS.md](TOOLS.md) | 9 个 MCP 工具的完整语义、参数和返回格式 |
| [TECHNICAL_OVERVIEW.md](TECHNICAL_OVERVIEW.md) | 系统架构、数据流与技术细节 |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 常见问题排查与诊断 |
| [SECURITY_AND_PRIVACY.md](SECURITY_AND_PRIVACY.md) | 安全模型与隐私设计 |
