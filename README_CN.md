<p align="center">
  <img src="docs/images/系统架构图.png" width="280" alt="Memory Palace Logo" />
</p>

<h1 align="center">🏛️ Memory Palace · 记忆宫殿</h1>

<p align="center">
  <strong>为 AI Agent 提供可持久、可检索、可审计的长期记忆。</strong>
</p>

<p align="center">
  <em>"每一次对话都留下痕迹，每一道痕迹都化为记忆。"</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License" />
  <img src="https://img.shields.io/badge/python-3.10+-3776ab.svg?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-18-61dafb.svg?logo=react&logoColor=black" alt="React" />
  <img src="https://img.shields.io/badge/Vite-646cff.svg?logo=vite&logoColor=white" alt="Vite" />
  <img src="https://img.shields.io/badge/SQLite-003b57.svg?logo=sqlite&logoColor=white" alt="SQLite" />
  <img src="https://img.shields.io/badge/protocol-MCP-orange.svg" alt="MCP" />
  <img src="https://img.shields.io/badge/Docker-ready-2496ed.svg?logo=docker&logoColor=white" alt="Docker" />
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="https://agi-is-going-to-arrive.github.io/Memory-Palace/">介绍页</a> · <a href="docs/README.md">文档</a> · <a href="docs/GETTING_STARTED.md">快速开始</a> · <a href="docs/EVALUATION.md">评测报告</a>
</p>

---

## 什么是 Memory Palace？

Memory Palace 为 LLM Agent 提供持久化、可检索、可审计的外部记忆，让每次对话都能在之前的基础上继续，而不是从零开始。

通过统一的 [MCP（模型上下文协议）](https://modelcontextprotocol.io/) 接口，一个后端可同时服务 **Claude Code、Codex、Gemini CLI、OpenCode** 这类 CLI 客户端；对 `Cursor / Windsurf / VSCode-host / Antigravity` 这类 IDE 宿主，请走 **`AGENTS.md` + 渲染好的 MCP 配置片段** 的方式。最短路径：CLI 看 [SKILLS_QUICKSTART.md](docs/skills/SKILLS_QUICKSTART.md)，IDE 看 [IDE_HOSTS.md](docs/skills/IDE_HOSTS.md)。

如果希望 AI 一步步带你安装，从独立的 setup-skill 仓库开始：[`memory-palace-setup`](https://github.com/AGI-is-going-to-arrive/memory-palace-setup)。推荐口径是 **skills + MCP**，而不是只配 MCP。

### 为什么选择 Memory Palace？

| 痛点 | Memory Palace 如何解决 |
|---|---|
| 🔄 Agent 跨会话忘记前文 | 基于 SQLite 的持久化记忆，跨会话保留 |
| 🔍 过往上下文难找回 | 混合检索（关键词 + 语义 + 重排序），意图感知路由 |
| 🚫 写入内容不可控 | Write Guard 预检每次写入；快照支持完整回滚 |
| 🧩 不同客户端需要不同集成 | 统一的 MCP 接口 |
| 📊 看不到内部状态 | 内置记忆 / 审查 / 维护 / 可观测性四视图 |

---

## 这次版本更新了什么

<p align="center">
  <img src="docs/images/memory_palace_upgrade.png" width="900" alt="Memory Palace 项目升级对比图" />
</p>

- **记忆维护引擎（v2）**：四个独立引擎 —— Forgetting（活力衰减 + 归档）、Layering（L0→L1→L2 带来源追踪）、Compression（级联压缩预览）、Procedural（步骤提取）。默认只读预览；真正修改需要显式 review token 授权。
- **SSE 强化**：per-principal 限流（429 + Retry-After）、空闲看门狗、可信代理 CIDR 白名单、优雅关闭排空、loopback 端口自动回退。
- **Dashboard**：L0/L1/L2 层级树、遗忘模拟、归档候选、Search Quality 面板、可观测性 SSE 实时流 + 断连横幅。
- **检索**：B/C/D 默认开启 RRF 融合（`RRF_K=10`）。C/D 在 pip 安装了 `sqlite-vec` 时默认走 sqlite-vec 原生向量引擎，没装则自动回退 legacy scoring。中英混合处理改进、全角归一化（`ＡＰＩ → API`）、MMR 去重、embedding 漂移检测、session-first cache。
- **安全**：artifact stripper（opt-in 工具输出消毒）、external import guard（路径遍历 + 限流 + symlink 拦截）、Docker 非 root 容器。
- **MCP 边界**：畸形 URI 拒绝、超长 payload 拦截、percent-encoded URI 统一处理、`add_alias` 失败干净回滚、`system://` 写保护。
- **Docker**：部署锁、runtime env injection（opt-in）、loopback → `host.docker.internal` 自动改写、NFS/CIFS/SMB 挂载拒绝。
- **Skills + MCP**：CLI 客户端（Claude / Codex / Gemini CLI / OpenCode）和 IDE 宿主（Cursor / Windsurf / VSCode-host / Antigravity）统一安装路径。推荐 user-scope 安装。
- **跨平台**：所有脚本 ps1/sh 对等实现、CRLF 防御、UTF-8 强制编码、Windows 原生 `mcp_wrapper.py` 作为 stdio 通道。

详细每版变更：[docs/changelog/](docs/changelog/)。

---

## 核心特性

### 可审计写入流水线

每次写入都经过 **Write Guard 预检 → 快照 → 异步索引重建**。核心动作为 `ADD`、`UPDATE`、`NOOP`、`DELETE`；`BYPASS` 仅作为 metadata-only 更新场景的流程标记。Dashboard 的 `POST/PUT/DELETE /browse/node` 也遵循同一套快照语义，所以 Review 页面可以看到并回滚。同 session 快照写入通过文件锁串行化，`manifest.json` 和单文件快照都采用原子替换。

后端在 rollback 前会复核内容是否已被更晚的快照覆盖，如果是直接返回 `409`。写入饱和会返回结构化 `503`（`write_lane_timeout`），而不是通用 `500`。SQLite 的瞬时锁冲突会做小范围重试，后台索引任务也走同一条全局写门控。

### 统一检索引擎

三种检索模式 —— `keyword`、`semantic`、`hybrid` —— 支持自动降级。外部 Embedding 不可用时回退关键词搜索，并在响应里报告 `degrade_reasons`。Embedding 维度检查跟随当前查询作用域（`domain`、`path_prefix`），不会被无关 domain 里的旧向量误导。最后一轮 path 复核优先走批量查询；若失败则丢弃结果并报告降级，而不是静默保留陈旧数据。

### 意图感知搜索

四类核心意图 —— `factual`、`exploratory`、`temporal`、`causal` —— 分别匹配 `factual_high_precision`、`exploratory_high_recall`、`temporal_time_filtered`、`causal_wide_pool` 模板。无显著信号默认 `factual_high_precision`；信号冲突或低信号混合时回退 `unknown`（`default`）。`why ... after ...` 这类时间词仅作连接词的查询仍走 causal 路径。

### 记忆维护引擎

四个引擎协同维持记忆库长期健康：

- **Forgetting Engine**：活力值按可配置的半衰期（默认 ~60 天）衰减。低于阈值的记忆成为归档候选。实际归档需要 review token —— 不会静默删除。
- **Layering Engine**：将记忆组织为 L0（原始）→ L1（关联簇）→ L2（主题摘要），带完整来源追踪。只读；摘要仅作为草稿存在直到被显式批准。
- **Compression Engine**：在不同预算使用率下预览级联压缩层级（mild/aggressive/emergency）。永远不写 —— 只展示*会*压缩什么。
- **Procedural Engine**：从对话记忆中提取步骤式操作流程，让隐式工作流变成可搜索的显式知识。

### 灵活部署

四种档位（A/B/C/D），从纯本地到远程 API。B/C/D 默认开启 RRF 融合；C/D 在安装了 `sqlite-vec` 时额外走 sqlite-vec 原生向量搜索。embedding 维度变化时，vec0 KNN 表会自动 DROP 并按新维度重建，但不同 backend/model/dimension 下已经写入的旧向量仍需要 `rebuild_index(wait=true)` 或分库验证。最完整的端到端验证仍是 `macOS + Docker`；原生 Windows 通过 `backend/mcp_wrapper.py` 也已打通。远程与 GUI 宿主组合请按目标环境再做一次复核。

### 内置可观测性仪表盘

基于 React 的四视图：**记忆浏览器**、**审查与回滚**、**维护**、**可观测性**。语言选择会被记住；常见中文浏览器语言（`zh`、`zh-TW`、`zh-HK`）首次访问会归并到 `zh-CN`，其他情况回退英文。Edge 用户会自动切到更轻量的视觉模式。

当既没有已保存的 Dashboard 鉴权，也没有运行时注入的 Dashboard 鉴权时，前端会自动打开首启向导。它可以把 `MCP_API_KEY` 保存到当前浏览器会话，并在本地 checkout 场景下把常见运行参数写入 `.env`。本地 `.env` 写入路径严格限定为项目内文件、仅 loopback、第一次写入必须有非空 key。Provider base 会做归一化（自动剥离 `/embeddings`、`/rerank`、`/chat/completions`），loopback IP 和 `localhost` 默认允许，其它 private 目标需要在 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` 里显式放行。

按页面拆开的使用说明：[中文仪表盘使用指南](docs/DASHBOARD_GUIDE_CN.md)。

---

## 系统架构

<p align="center">
  <img src="docs/images/系统架构图.png" width="900" alt="Memory Palace 系统架构" />
</p>

用户 / AI Agent → React 仪表盘或 MCP Server（9 工具 + SSE）→ FastAPI 后端 → Write Guard / 检索引擎 → Write Lane / Index Worker → SQLite。

---

## 技术栈

### 后端

| 组件 | 技术 | 版本 |
|---|---|---|
| Web 框架 | [FastAPI](https://fastapi.tiangolo.com/) | ≥ 0.109 |
| ORM | [SQLAlchemy](https://www.sqlalchemy.org/) | ≥ 2.0 |
| 数据库 | [SQLite](https://www.sqlite.org/) + aiosqlite | ≥ 0.19 |
| MCP 协议 | `mcp (FastMCP)` | ≥ 0.1 |
| HTTP 客户端 | [httpx](https://www.python-httpx.org/) | ≥ 0.26 |
| 数据校验 | [Pydantic](https://docs.pydantic.dev/) | ≥ 2.5 |
| 差异引擎 | `diff_match_patch` + `difflib` fallback | — |

### 前端

| 组件 | 技术 | 版本 |
|---|---|---|
| UI | [React](https://react.dev/) | 18 |
| 构建 | [Vite](https://vitejs.dev/) | 7.x |
| 样式 | [Tailwind CSS](https://tailwindcss.com/) | 3.x |
| 动画 | [Framer Motion](https://www.framer.com/motion/) | 12.x |
| 路由 | React Router DOM | 6.x |
| API | [Axios](https://axios-http.com/) | 1.x |

模块级职责详情参见 [TECHNICAL_OVERVIEW.md](docs/TECHNICAL_OVERVIEW.md)。

---

## 环境要求

| 组件 | 最低 | 推荐 |
|---|---|---|
| Python | 3.10+ | 3.11+ |
| Node.js | 20.19+（或 >=22.12） | 最新 LTS |
| npm | 9+ | 最新稳定版 |
| Docker（可选） | 20+ | 最新稳定版 |

---

## 快速开始

三条路径，最终落到同一套 Dashboard + MCP 接口。

### 方式一：拉取预构建 Docker 镜像（最省事）

```bash
git clone https://github.com/AGI-is-going-to-arrive/Memory-Palace.git
cd Memory-Palace

bash scripts/apply_profile.sh docker b .env.docker
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

Windows PowerShell：`.\scripts\apply_profile.ps1 -Platform docker -Profile b -Target .env.docker`，再用相同的 `docker compose` 命令。停止：`docker compose -f docker-compose.ghcr.yml down --remove-orphans`。

### 方式二：一键 Docker 部署（自动避端口冲突）

```bash
bash scripts/docker_one_click.sh --profile b              # macOS / Linux
.\scripts\docker_one_click.ps1 -Profile b                  # Windows
bash scripts/docker_one_click.sh --profile c --allow-runtime-env-injection   # C/D 需要真实地址
```

脚本会在 `MCP_API_KEY` 为空时自动生成、`3000`/`18000` 被占用时切换端口、对 `/sse` 做 readiness 检查、拒绝 NFS 这类高风险数据卷挂载。停止：`COMPOSE_PROJECT_NAME=<控制台打印的> docker compose -f docker-compose.yml down --remove-orphans`。

### 方式三：手动本地搭建

```bash
git clone https://github.com/AGI-is-going-to-arrive/Memory-Palace.git
cd Memory-Palace
bash scripts/apply_profile.sh macos b      # 生成档位 B 的 env

# 后端
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# 前端（新终端）
cd frontend && npm install && npm run dev
```

打开 <http://localhost:5173>。如果要立刻使用 Dashboard 或 `/browse` / `/review` / `/maintenance`，先在 `.env` 里加 `MCP_API_KEY=change-this`（或 `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` 用于本机回环调试）再启动后端。

### 默认访问地址

| 服务 | 本地开发 | Docker |
|---|---|---|
| 前端仪表盘 | <http://localhost:5173> | <http://127.0.0.1:3000> |
| 后端 API | <http://127.0.0.1:8000> | <http://127.0.0.1:18000> |
| SSE | <http://127.0.0.1:8010/sse> | <http://127.0.0.1:3000/sse> |

### 重要边界

- Docker 数据保存在 named volume `<compose-project>_data` 和 `<compose-project>_snapshots` 中。`docker compose down` 不会删除数据，但 `down -v` 会清除。
- NFS/CIFS/SMB 挂载会被一键脚本拒绝。如必须使用网络挂载，可绕过一键脚本手动 `docker compose up`，并设置 `MEMORY_PALACE_DOCKER_WAL_ENABLED=false` 和 `MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete`。
- 仓库自带的 `stdio` launcher（`scripts/run_memory_palace_mcp_stdio.sh`、`backend/mcp_wrapper.py`）需要一份带绝对 `DATABASE_URL` 的本地 `.env`。`/app/...`、`/data/...` 这类容器路径会被直接拒绝。
- Skill `memory-palace-reports` 的输出默认写到仓库外的绝对路径 `~/.memory-palace-reports/`。
- Docker 前端端口属于可信运维入口；要给受信范围之外的人访问，先在前面加 VPN / 反向代理鉴权。
- `Profile C/D` 必须填真实 endpoint、key、model id。`apply_profile.*` 和后端都会对占位值 fail-closed。
- 切换 embedding backend / model / dimension 后要检查 `index_status()`，必要时跑 `rebuild_index(wait=true)`。

详细步骤：[GETTING_STARTED.md](docs/GETTING_STARTED.md)。

---

## 部署档位（A / B / C / D）

| 档位 | 检索模式 | Embedding | Reranker | 适用场景 |
|---|---|---|---|---|
| **A** | `keyword` | ❌ | ❌ | 最小资源，初步验证 |
| **B** | `hybrid` | 📦 本地哈希 | ❌ | **默认起步档位**——本地开发，无需外部服务 |
| **C** | `hybrid` | 🌐 Router/API | ✅ | 推荐档位——已准备好本地模型服务 |
| **D** | `hybrid` | 🌐 Router/API | ✅ | 远程 API，生产环境 |

C 和 D 共享相同的混合检索流水线，主要差异在 endpoint（本地 vs 远程）和默认 `RETRIEVAL_RERANKER_WEIGHT`（`0.30` vs `0.35`）。建议先在 B 上跑通再考虑升级；切档不是“切过去就好”——一旦向量是在不同 backend/dimension 下写入的，就要重建索引。

### C/D 配置

所有 endpoint 都使用 OpenAI 兼容 API 格式（Ollama、LM Studio、vLLM、托管服务等）：

```bash
RETRIEVAL_EMBEDDING_BACKEND=api
RETRIEVAL_EMBEDDING_API_BASE=http://localhost:11434/v1
RETRIEVAL_EMBEDDING_API_KEY=your-api-key
RETRIEVAL_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_EMBEDDING_DIM=<provider-vector-dim>

RETRIEVAL_RERANKER_ENABLED=true
RETRIEVAL_RERANKER_API_BASE=http://localhost:11434/v1
RETRIEVAL_RERANKER_API_KEY=your-api-key
RETRIEVAL_RERANKER_MODEL=your-reranker-model-id

RETRIEVAL_RERANKER_WEIGHT=0.30  # Profile C 默认；Profile D 用 0.35
```

要点：

- `RETRIEVAL_EMBEDDING_DIM` 必须等于 provider 返回的实际向量维度。当前实现会把它作为 OpenAI-compatible `/embeddings` 请求的 `dimensions` 字段；若 provider 明确拒绝，会自动重试一次不带 `dimensions`。最终响应维度仍不匹配时直接丢弃该向量并报 `degrade_reasons`。
- 是否启用 Reranker 由 `RETRIEVAL_RERANKER_ENABLED` 控制；连接参数缺失时才依次回退到 `ROUTER_*`、`OPENAI_*`。
- 可选的 LLM 辅助 Write Guard / Gist / intent 路由对应 `WRITE_GUARD_LLM_*`、`COMPACT_GIST_LLM_*`、`INTENT_LLM_*`，都写在同一份 `.env` 里。

档位模板：`deploy/profiles/{macos,linux,windows,docker}/profile-{a,b,c,d}.env`。完整参数参考：[DEPLOYMENT_PROFILES.md](docs/DEPLOYMENT_PROFILES.md)。

---

## MCP 工具

Memory Palace 通过 MCP 协议暴露 **9 个标准化工具**：

| 类别 | 工具 | 说明 |
|---|---|---|
| **读写** | `read_memory` | 读取记忆（完整或按 `RETRIEVAL_CHUNK_SIZE` 分块）|
| | `create_memory` | 创建节点（先过 Write Guard；建议显式填 `title`）|
| | `update_memory` | 更新记忆（优先 Patch；仅真正追加到末尾时用 Append）|
| | `delete_memory` | 删除路径（返回结构化 JSON）|
| | `add_alias` | 添加别名路径 |
| **检索** | `search_memory` | 支持 `keyword` / `semantic` / `hybrid` 模式 |
| **治理** | `compact_context` | 压缩会话上下文为长期摘要（Gist + Trace）|
| | `rebuild_index` | 触发索引重建 / 睡眠整合 |
| | `index_status` | 查询索引可用性与运行时状态 |

### 系统 URI

| URI | 说明 |
|---|---|
| `system://boot` | 按 `CORE_MEMORY_URIS` 加载核心记忆 |
| `system://index` | 完整记忆索引概览 |
| `system://index-lite` | 基于 gist 的轻量摘要 |
| `system://audit` | 观测与审计摘要聚合 |
| `system://recent` / `system://recent/N` | 最近修改的记忆 |

### 启动 MCP 服务器

```bash
cd backend && ./.venv/bin/python mcp_server.py     # stdio（Windows: .\.venv\Scripts\python.exe）
cd backend && HOST=127.0.0.1 PORT=8010 python run_sse.py   # SSE（回环示例）
```

`stdio` 不经过 HTTP/SSE 鉴权中间层，但受保护的 HTTP/SSE 路由仍要 `MCP_API_KEY`。`HOST=0.0.0.0` 只在确实需要远程访问、并且自己的防火墙 / 反向代理 / 鉴权已经就位时才使用；远程 hostname / origin 也要补 `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS`。

Shell wrapper 会设置 `PYTHONIOENCODING=utf-8` 和 `PYTHONUTF8=1`，避免 Windows 控制台遇到非 ASCII 记忆内容时出现编码错误。

完整工具语义：[TOOLS.md](docs/TOOLS.md)。

---

## 多客户端集成

MCP 工具层负责 **确定性执行**；Skills 策略层负责 **策略与时机**。

<p align="center">
  <img src="docs/images/多客户端 MCP + Skills 编排图.png" width="900" alt="多客户端 MCP + Skills 编排图" />
</p>

### 推荐默认流程

```
1. 🚀 启动    → read_memory("system://boot")
2. 🔍 召回    → search_memory(include_session=true)
3. ✍️ 写入    → 优先 update_memory 的 Patch；新建用带 title 的 create_memory
4. 📦 压缩    → compact_context(force=false)
5. 🔧 恢复    → rebuild_index(wait=true) + index_status()
```

### 支持的客户端

| 客户端 | 集成方式 |
|---|---|
| Claude Code | 新机器优先 `--scope user`；workspace 安装仅在需要仓库级入口时再补 |
| Gemini CLI | 新机器优先 `--scope user`；workspace 可选 |
| Codex CLI / OpenCode | `sync` 解决 repo-local skill 自动发现；要稳定绑到当前仓库 backend 时补 `--scope user --with-mcp` |
| Cursor / Windsurf / VSCode-host / Antigravity | repo-local `AGENTS.md` + 渲染出的 MCP 配置片段 |

### 安装 Skills

```bash
python scripts/sync_memory_palace_skill.py
python scripts/install_skill.py --targets claude,codex,gemini,opencode --scope user --with-mcp --force

# IDE 宿主：直接渲染 MCP 配置片段
python scripts/render_ide_host_config.py --host cursor       # 或：windsurf | vscode-host | antigravity
```

可选本地复核：

```bash
python scripts/evaluate_memory_palace_skill.py
cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py
```

`FAIL` 需要处理；`SKIP`/`PARTIAL`/`MANUAL` 通常代表宿主或环境边界。CI 或并行 review 里需要隔离输出时，设置 `MEMORY_PALACE_SKILL_REPORT_PATH` / `MEMORY_PALACE_MCP_E2E_REPORT_PATH`。

新机器上更稳的默认方案是 `user` 级安装 — Codex 和 OpenCode 只在 user scope 下绑定 MCP。canonical 真源：`<repo-root>/docs/skills/memory-palace/`。安装后会在 `.claude/`、`.codex/`、`.opencode/` 下生成本地镜像。完整指南：[MEMORY_PALACE_SKILLS.md](docs/skills/MEMORY_PALACE_SKILLS.md)、[IDE_HOSTS.md](docs/skills/IDE_HOSTS.md)。

---

## 评测结果

这是一份发布摘要，具体数字会随硬件、provider 和模型不同而变化。完整方法与复现：[EVALUATION.md](docs/EVALUATION.md)。同口径旧版 vs 当前版本对照：[release_summary_vs_old_project_2026-03-06.md](docs/changelog/release_summary_vs_old_project_2026-03-06.md)。

A/B/C/D 真实运行 · `profile_abcd_real_metrics.json` · 每数据集 8 样本 · 10 个干扰文档 · Seed = 20260219

| 档位 | 数据集 | HR@10 | MRR | NDCG@10 | p95（ms） |
|---|---|---:|---:|---:|---:|
| A | SQuAD v2 / NFCorpus | 0.000 / 0.250 | 0.000 / 0.250 | 0.000 / 0.250 | 1.78 / 1.74 |
| B | SQuAD v2 / NFCorpus | 0.625 / 0.750 | 0.302 / 0.478 | 0.383 / 0.542 | 4.92 / 5.02 |
| **C** | SQuAD v2 / NFCorpus | **1.000** / 0.750 | **1.000** / 0.567 | **1.000** / 0.611 | 665 / 454 |
| **D** | SQuAD v2 / NFCorpus | **1.000** / 0.750 | **1.000** / 0.650 | **1.000** / 0.673 | 2078 / 2365 |

C/D 在记录的运行中通过已配置的 embedding 和 reranker 模型在 SQuAD v2 上达到完美召回，额外延迟来自模型推理和网络。A/B 大样本门控（100 样本）和完整逐数据集表格在 [EVALUATION.md](docs/EVALUATION.md) 中。

<p align="center">
  <img src="docs/images/benchmark_comparison.png" width="900" alt="旧版 vs 当前版本检索质量与延迟对比图" />
</p>

质量门控：Write Guard 精确率 1.000（≥0.90）/召回率 1.000（≥0.85）；意图分类准确率 1.000（≥0.80）；Gist ROUGE-L 0.759（≥0.40）。数据源：`write_guard_quality_metrics.json`、`intent_accuracy_metrics.json`、`compact_context_gist_quality_metrics.json`。

用户侧最小复核：`bash scripts/pre_publish_check.sh` + `curl -fsS http://127.0.0.1:8000/health`。`backend/tests/benchmark/` 下的 benchmark runners 属于维护材料。

---

## 仪表盘截图

下面是进入 Dashboard 之后的典型状态。没配置鉴权时，页面外壳仍会打开，但受保护请求会显示授权提示或 `401`。Edge 自动切到更轻量的视觉模式。

<details>
<summary>🪄 首启配置向导</summary>
<img src="docs/images/setup-assistant-zh.png" width="900" alt="首启配置向导" />
</details>

<details>
<summary>📂 记忆 · 📋 审查 · 🔧 维护 · 📊 可观测性</summary>
<img src="docs/images/memory-zh.png" width="900" alt="记忆浏览器" />
<img src="docs/images/review-zh.png" width="900" alt="审查页面" />
<img src="docs/images/maintenance-zh.png" width="900" alt="维护页面" />
<img src="docs/images/observability-zh.png" width="900" alt="可观测性页面" />
</details>

---

## 记忆写入与审查工作流

<p align="center">
  <img src="docs/images/记忆写入与审查时序图.png" width="900" alt="记忆写入与审查时序图" />
</p>

**写入路径**：`create_memory` / `update_memory` → Write Lane 队列 → Write Guard（`ADD` / `UPDATE` / `NOOP` / `DELETE`）→ 快照 + 版本记录 → 异步 Index Worker。

**检索路径**：`preprocess_query` → `classify_intent` → 策略模板 → `keyword`/`semantic`/`hybrid` 检索 → `results` + `degrade_reasons`。

---

## 文档导航

| 文档 | 说明 |
|---|---|
| [快速开始](docs/GETTING_STARTED.md) | 从零到运行的完整指南 |
| [技术概述](docs/TECHNICAL_OVERVIEW.md) | 架构设计与模块职责 |
| [部署档位](docs/DEPLOYMENT_PROFILES.md) | A/B/C/D 配置与调参 |
| [MCP 工具](docs/TOOLS.md) | 9 个工具的完整语义与返回格式 |
| [评测报告](docs/EVALUATION.md) | 检索质量、写入门控、意图分类 |
| [Skills 指南](docs/skills/MEMORY_PALACE_SKILLS.md) | 多客户端集成策略 |
| [安全与隐私](docs/SECURITY_AND_PRIVACY.md) | API Key 鉴权与安全策略 |
| [故障排查](docs/TROUBLESHOOTING.md) | 常见问题与解决方案 |

---

## 安全与隐私

- 仅 `.env.example` 进入仓库；真实 `.env` 始终被 gitignore。
- 文档中所有 API Key 均为占位符。
- HTTP/SSE 鉴权默认 fail-closed：未配置或未提供有效 `MCP_API_KEY` 时返回 `401`；`stdio` 不受影响。
- Docker 一键部署在服务端代理转发鉴权头，浏览器不会直接拿到真实 key。
- 本地绕过需显式 `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`（仅限 loopback）。
- Setup Assistant 的本地 `.env` 写入更严格：仅项目内文件、直连 loopback、第一次保存要求 key 非空；后端已配置 `MCP_API_KEY` 后即使 loopback 写入也必须带有效 key。
- 通过向导写入的 provider base 会先归一化和校验：常见后缀（`/embeddings`、`/rerank`、`/chat/completions`）自动剥离；格式不对或指到 link-local 的地址直接拦下；loopback IP 和 `localhost` 默认允许；其它 private 目标需要 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS`。

详情：[SECURITY_AND_PRIVACY.md](docs/SECURITY_AND_PRIVACY.md)。

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=AGI-is-going-to-arrive/Memory-Palace&type=Date)](https://star-history.com/#AGI-is-going-to-arrive/Memory-Palace&Date)

---

## 开源协议

[MIT](LICENSE) — Copyright (c) 2026 agi

---

## 致谢与灵感来源

- 最初的灵感：<https://linux.do/t/topic/1616409>
- 最早参考项目：[`Dataojitori/nocturne_memory`](https://github.com/Dataojitori/nocturne_memory)
- Memory Palace 是在这条思路上做的完整重构版本，补齐了新的公开文档、部署路径与验证链。
