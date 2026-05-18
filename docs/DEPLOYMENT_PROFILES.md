# Memory Palace 部署档位

根据硬件和使用场景选择 A / B / C / D 档位，然后部署。

## 目录

- [1. 快速开始](#1-快速开始)
- [2. 档位一览](#2-档位一览)
- [3. 各档位配置](#3-各档位配置)
- [4. 可选 LLM 参数](#4-可选-llm-参数)
- [5. Docker 一键部署](#5-docker-一键部署)
- [6. 手动启动](#6-手动启动)
- [7. 本地推理服务](#7-本地推理服务)
- [8. Vitality 参数](#8-vitality-参数)
- [9. API 鉴权](#9-api-鉴权)
- [10. 故障排查](#10-故障排查)
- [11. 脚本一览](#11-脚本一览)

---

## 1. 快速开始

1. **选档位**：不确定就选 **B**（零外部依赖）；模型服务已就绪再考虑 C / D。
2. **生成 `.env`**：运行 `scripts/apply_profile.sh`（或 `.ps1`）。
3. **启动服务**：Docker 一键部署 **或** 手动启动。

> `deploy/profiles/*/profile-*.env` 是模板，不要直接当成最终 `.env`。先跑 `apply_profile`，再按实际环境微调。

---

## 2. 档位一览

| 档位 | 搜索模式 | Embedding | Reranker | 适用场景 |
|:---:|---|---|:---:|---|
| **A** | `keyword` | 关闭（`none`） | 关闭 | 最低配，纯关键词检索 |
| **B** | `hybrid` | 本地哈希（`hash`） | 关闭 | **默认起步档**，零外部依赖 |
| **C** | `hybrid` | API（`router`） | 开启 | 本地/私有 embedding + reranker 服务就绪后使用 |
| **D** | `hybrid` | API（`router`） | 开启 | 远程 API，无需本地 GPU |

**说明**：

- A → B：从纯关键词升级为混合检索（内置 64 维哈希，零依赖）。
- B → C/D：接入真实 embedding + reranker，提升语义检索效果。
- C vs D：算法一致，主要差别是 endpoint（本地 vs 远程）与默认 reranker 权重（C `0.30`、D `0.35`）。

> **升档前的提醒**：如果库里已有用其它 embedding 后端写入的旧向量，先用 `index_status()` 检查；维度不一致时运行 `rebuild_index(wait=true)`，或换一份新库验证。系统不会自动迁移旧向量。

> **配置优先级**：
> - `RETRIEVAL_EMBEDDING_BACKEND` 只控制 Embedding，不影响 Reranker。
> - Reranker 没有 `_BACKEND` 开关；启用与否仅由 `RETRIEVAL_RERANKER_ENABLED` 决定。
> - Reranker 地址/密钥优先读 `RETRIEVAL_RERANKER_API_BASE/API_KEY`，缺失时回退 `ROUTER_*`，再回退 `OPENAI_*`。
> - 仓库自带的 `profile-c` 模板默认仍会把 Reranker 一起打开；如果你的服务没有 `/rerank`，先关闭 `RETRIEVAL_RERANKER_ENABLED` 或继续用 B。

---

## 3. 各档位配置

### Profile A —— 纯关键词

```bash
SEARCH_DEFAULT_MODE=keyword
RETRIEVAL_EMBEDDING_BACKEND=none
RETRIEVAL_RERANKER_ENABLED=false
RUNTIME_INDEX_WORKER_ENABLED=false
```

### Profile B —— 混合检索 + 本地哈希（默认）

```bash
SEARCH_DEFAULT_MODE=hybrid
RETRIEVAL_EMBEDDING_BACKEND=hash
RETRIEVAL_EMBEDDING_MODEL=hash-v1
RETRIEVAL_EMBEDDING_DIM=64
RETRIEVAL_RERANKER_ENABLED=false
RUNTIME_INDEX_WORKER_ENABLED=true
RUNTIME_INDEX_DEFER_ON_WRITE=true
```

### Profile C —— 本地/私有 API

```bash
SEARCH_DEFAULT_MODE=hybrid
RETRIEVAL_EMBEDDING_BACKEND=router

# Embedding
ROUTER_API_BASE=http://127.0.0.1:PORT/v1
ROUTER_API_KEY=replace-with-your-key
ROUTER_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_EMBEDDING_API_BASE=http://127.0.0.1:PORT/v1
RETRIEVAL_EMBEDDING_API_KEY=replace-with-your-key
RETRIEVAL_EMBEDDING_DIM=<provider-vector-dim>

# Reranker
RETRIEVAL_RERANKER_ENABLED=true
RETRIEVAL_RERANKER_API_BASE=http://127.0.0.1:PORT/v1
RETRIEVAL_RERANKER_API_KEY=replace-with-your-key
RETRIEVAL_RERANKER_MODEL=your-reranker-model-id
RETRIEVAL_RERANKER_WEIGHT=0.30
```

如果不用统一 `router`，可改为直连：

```bash
RETRIEVAL_EMBEDDING_BACKEND=api
RETRIEVAL_RERANKER_ENABLED=true
RETRIEVAL_RERANKER_API_BASE=http://127.0.0.1:PORT/v1
RETRIEVAL_RERANKER_API_KEY=replace-with-your-key
RETRIEVAL_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_RERANKER_MODEL=your-reranker-model-id
```

### Profile D —— 远程 API

与 C 的区别：endpoint 指向远程，默认 reranker 权重更高。

```bash
ROUTER_API_BASE=https://router.example.com/v1
RETRIEVAL_EMBEDDING_API_BASE=https://router.example.com/v1
RETRIEVAL_RERANKER_API_BASE=https://router.example.com/v1
RETRIEVAL_RERANKER_WEIGHT=0.35
```

### 关键提示

- **`RETRIEVAL_EMBEDDING_DIM`** 必须与 provider 实际返回的向量维度一致。该值会作为 `dimensions` 字段发给 OpenAI-compatible `/embeddings`；provider 不支持时运行时会自动重试一次不带该字段的请求。
- **API base 写服务根**（通常到 `/v1`），不要写成 `/embeddings`、`/rerank`、`/chat/completions` 等具体接口路径。常见尾缀会自动归一化，但格式不对或 link-local 地址会 fail-closed。
- **`127.0.0.1` / `::1` / `localhost`** 默认允许。其它 private IP 字面量需要通过 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` 显式放行。
- **占位值会被拦截**：`https://router.example.com/v1`、`your-embedding-model-id` 等示例值在保存或启动时会直接拒绝；请改成真实可用值。
- **首要调参**：`RETRIEVAL_RERANKER_WEIGHT`，建议 `0.20 ~ 0.40`，以 `0.05` 步长微调。

---

## 4. 可选 LLM 参数

控制三个可选 LLM 功能：写入守卫、上下文压缩、意图增强。

```bash
# Write Guard（过滤低质量写入）
WRITE_GUARD_LLM_ENABLED=false
WRITE_GUARD_LLM_API_BASE=
WRITE_GUARD_LLM_API_KEY=
WRITE_GUARD_LLM_MODEL=your-chat-model-id

# Compact Context Gist（生成会话摘要）
COMPACT_GIST_LLM_ENABLED=false
COMPACT_GIST_LLM_API_BASE=
COMPACT_GIST_LLM_API_KEY=
COMPACT_GIST_LLM_MODEL=your-chat-model-id

# Intent（实验性意图分类增强）
INTENT_LLM_ENABLED=false
INTENT_LLM_API_BASE=
INTENT_LLM_API_KEY=
INTENT_LLM_MODEL=your-chat-model-id
```

- `COMPACT_GIST_LLM_*` 未配置时会回退到 `WRITE_GUARD_LLM_*`。
- 两条链路都走 OpenAI-compatible `/chat/completions`。
- `INTENT_LLM` 是实验性能力，关闭时自动回退关键词规则。
- 进阶参数（`CORS_ALLOW_*`、`RETRIEVAL_MMR_*`、`INDEX_LITE_ENABLED` 等）以 `.env.example` 为准。

---

## 5. Docker 一键部署

### 选项 1：GHCR 预构建镜像（推荐——本地构建经常失败的用户）

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

- 这条路径覆盖 Dashboard / API / SSE，不自动安装本机 skills / MCP / IDE host 配置。
- **不会自动调整端口**。`3000` / `18000` 被占用时显式设置 `MEMORY_PALACE_FRONTEND_PORT` / `MEMORY_PALACE_BACKEND_PORT`。
- 容器内访问宿主机模型服务时，用 `host.docker.internal` 而不是 `127.0.0.1`。

### 选项 2：本地构建一键脚本

```bash
# macOS / Linux
cd <project-root>
bash scripts/docker_one_click.sh --profile b

# Profile C/D 需要从当前 shell 注入 API 地址 / key / model
bash scripts/docker_one_click.sh --profile c --allow-runtime-env-injection
```

```powershell
# Windows PowerShell
cd <project-root>
.\scripts\docker_one_click.ps1 -Profile b
.\scripts\docker_one_click.ps1 -Profile c -AllowRuntimeEnvInjection
```

脚本会：

1. 从 profile 模板生成本次 Docker env 文件
2. 自动检测端口、持久化卷、网络文件系统 bind mount
3. 添加 deployment lock，避免同一 checkout 下并发部署互相覆盖
4. 启动后端 + 前端，等 `/health` 通过后再加一次 `/sse` 可达性检查

**runtime env injection 仅限 `profile c/d`**。对 `profile a/b` 传该标志会直接拒绝。

### 部署后访问

| 服务 | 宿主机端口 | URL |
|---|:---:|---|
| Frontend | `3000` | `http://localhost:3000` |
| Backend | `18000` | `http://localhost:18000` |
| SSE | `3000` | `http://localhost:3000/sse` |
| 健康检查 | `18000` | `http://localhost:18000/health` |

### 安全说明

- Backend 容器以非 root 用户运行（UID `10001`）
- Frontend 使用 `nginxinc/nginx-unprivileged` 镜像
- Compose 配置了 `security_opt: no-new-privileges:true`

### 停止服务

```bash
COMPOSE_PROJECT_NAME=<控制台打印的 compose project> docker compose -f docker-compose.yml down --remove-orphans
```

> `down --remove-orphans` 不会删除数据卷；显式 `down -v` 才会清空数据库和 review snapshots。

**WAL 边界**：默认 `named volume + WAL`。如果把 `/app/data` 改成 NFS/CIFS/SMB bind mount，必须显式设置 `MEMORY_PALACE_DOCKER_WAL_ENABLED=false` 和 `MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete`。一键脚本会在启动前做这层 preflight；如果你绕过一键脚本，手动 `docker compose up`，也要自己预检。

---

## 6. 手动启动

### 第一步：生成 `.env`

```bash
# macOS / Linux（Profile B）
cd <project-root>
bash scripts/apply_profile.sh macos b

# Windows PowerShell
.\scripts\apply_profile.ps1 -Platform windows -Profile b
```

> 脚本复制 `.env.example`，再追加 `deploy/profiles/<platform>/profile-<x>.env` 中的覆盖参数。本地平台默认目标是 `.env`；`docker` 变体默认是 `.env.docker`。覆盖已有目标前会先备份 `*.bak`。

只想预览结果可用 `--dry-run`：

```bash
bash scripts/apply_profile.sh --dry-run macos b
.\scripts\apply_profile.ps1 -Platform windows -Profile b -DryRun
```

### 第二步：启动后端

```bash
cd <project-root>/backend
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 18000
```

### 第三步：启动前端

```bash
cd <project-root>/frontend
npm install
MEMORY_PALACE_API_PROXY_TARGET=http://127.0.0.1:18000 npm run dev -- --host 127.0.0.1 --port 3000
```

如需 Vite 同源代理 SSE，再加：

```bash
MEMORY_PALACE_SSE_PROXY_TARGET=http://127.0.0.1:8010
```

---

## 7. 本地推理服务

Profile C 需要本地运行 embedding / reranker 模型。常用服务：

| 服务 | 官方文档 | 硬件 |
|---|---|---|
| Ollama | [docs.ollama.com](https://docs.ollama.com/gpu) | CPU 可跑；GPU 按模型大小匹配 VRAM |
| LM Studio | [lmstudio.ai](https://lmstudio.ai/docs/app/system-requirements) | 16GB+ RAM |
| vLLM | [docs.vllm.ai](https://docs.vllm.ai/en/stable/getting_started/installation/gpu.html) | Linux-first；NVIDIA 计算能力 7.0+ |
| SGLang | [docs.sglang.ai](https://docs.sglang.ai/index.html) | NVIDIA / AMD / CPU / TPU |

OpenAI-compatible 接口：

- Ollama：[OpenAI Compatibility](https://docs.ollama.com/api/openai-compatibility)
- LM Studio：[OpenAI Endpoints](https://lmstudio.ai/docs/app/api/endpoints/openai)

> Memory Palace 通过 OpenAI-compatible API 调用 embedding 与 reranker。启用 reranker 时，服务还需要 `/rerank` 端点。

---

## 8. Vitality 参数

Vitality 系统管理记忆生命周期：**访问强化 → 自然衰减 → 候选清理 → 人工确认**。

| 参数 | 默认 | 说明 |
|---|:---:|---|
| `VITALITY_MAX_SCORE` | `3.0` | 活力分上限 |
| `VITALITY_REINFORCE_DELTA` | `0.08` | 检索命中加分 |
| `VITALITY_DECAY_HALF_LIFE_DAYS` | `30` | 衰减半衰期（天） |
| `VITALITY_DECAY_MIN_SCORE` | `0.05` | 衰减下限 |
| `VITALITY_CLEANUP_THRESHOLD` | `0.35` | 低于此值列为清理候选 |
| `VITALITY_CLEANUP_INACTIVE_DAYS` | `14` | 不活跃天数阈值 |
| `RUNTIME_VITALITY_DECAY_CHECK_INTERVAL_SECONDS` | `600` | 衰减检查间隔（秒） |
| `RUNTIME_CLEANUP_REVIEW_TTL_SECONDS` | `900` | 清理确认窗口（秒） |
| `RUNTIME_CLEANUP_REVIEW_MAX_PENDING` | `64` | 最大待确认数 |

**调参建议**：

1. 先保持默认 1-2 周，再调整
2. 清理候选过多 → 提高 `VITALITY_CLEANUP_THRESHOLD` 或 `VITALITY_CLEANUP_INACTIVE_DAYS`
3. 确认窗口太短 → 调大 `RUNTIME_CLEANUP_REVIEW_TTL_SECONDS`

---

## 9. API 鉴权

以下接口受 `MCP_API_KEY` 保护（**fail-closed**，未配置时返回 `401`）：

- `/maintenance/*`、`/browse/*`、`/review/*`
- `/api/layering/*`、`/api/forgetting/*`、`/search/quality-metrics`
- SSE 接口 `/sse` 与 `/messages`

**请求头格式（二选一）**：

```
X-MCP-API-Key: <你的 MCP_API_KEY>
Authorization: Bearer <你的 MCP_API_KEY>
```

### 本地调试放行

设置 `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` 可跳过鉴权：

- 仅对 loopback 请求生效（`127.0.0.1` / `::1` / `localhost`）
- 非 loopback 仍返回 `401`

> MCP stdio 模式不经过 HTTP/SSE 鉴权中间层，不受此限制。

### 前端访问

**本地手动启动**时，可在页面里运行时注入：

```html
<script>
  window.__MEMORY_PALACE_RUNTIME__ = {
    maintenanceApiKey: "<MCP_API_KEY>",
    maintenanceApiKeyMode: "header"   // 或 "bearer"
  };
</script>
```

> 不要把真实 key 写进公开页面。面向他人的部署应通过服务端代理转发。

**Docker 一键部署**时，前端代理自动为受保护路径转发 `MCP_API_KEY`，不需要把 key 写进页面。把前端 `3000` 端口视为可信管理入口；要暴露到公网请先加 VPN、反向代理鉴权或 ACL。

### SSE 启动示例

```bash
HOST=127.0.0.1 PORT=8010 python run_sse.py
```

> `run_sse.py` 优先尝试 `127.0.0.1:8000`，被占用时回退到 `8010`。要给其他机器访问改成 `0.0.0.0`，并自行补齐 `MCP_API_KEY`、网络隔离、反向代理与 TLS。远程 hostname / origin 还需要 `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS`。

---

## 10. 故障排查

### 常见问题

| 问题 | 解决 |
|---|---|
| 检索效果差 | 确认 `SEARCH_DEFAULT_MODE=hybrid`；C/D 档检查 `RETRIEVAL_RERANKER_WEIGHT` |
| 模型服务不可用 | 系统自动降级，看响应 `degrade_reasons` 字段 |
| `embedding_request_failed` / `embedding_fallback_hash` | 外部 embedding/reranker 链路不可达，按下方排查 |
| Docker 端口冲突 | 一键脚本自动找空闲端口；也可手动 `--frontend-port` / `--backend-port` |
| SSE `address already in use` | 释放端口或用 `PORT=<空闲端口>` |
| 升级后数据库丢失 | 后端启动时自动从历史文件名恢复（`agent_memory.db` / `nocturne_memory.db`） |

### C/D 降级排查

```bash
# 1. 检查服务是否启动
curl -fsS http://127.0.0.1:18000/health

# 2. 直接调用 embedding / reranker 端点
curl -fsS -X POST <RETRIEVAL_EMBEDDING_API_BASE>/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <RETRIEVAL_EMBEDDING_API_KEY>" \
  -d '{"model":"<RETRIEVAL_EMBEDDING_MODEL>","input":"ping","dimensions":<RETRIEVAL_EMBEDDING_DIM>}'

curl -fsS -X POST <RETRIEVAL_RERANKER_API_BASE>/rerank \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <RETRIEVAL_RERANKER_API_KEY>" \
  -d '{"model":"<RETRIEVAL_RERANKER_MODEL>","query":"ping","documents":["pong"]}'
```

排障时可临时切到 `RETRIEVAL_EMBEDDING_BACKEND=api` 并直配 embedding / reranker；上线前恢复目标环境的 `router` 配置并复验。

### 调参提示

- **`RETRIEVAL_RERANKER_WEIGHT`** 过高会过度依赖重排序模型；以 `0.05` 步长微调。
- **数据持久化**：默认两个 compose-project 范围的卷（`<project>_data` 挂 `/app/data`，`<project>_snapshots` 挂 `/app/snapshots`）。
- **迁移锁**：`DB_MIGRATION_LOCK_FILE`（默认 `<db_file>.migrate.lock`）和 `DB_MIGRATION_LOCK_TIMEOUT_SEC`（默认 `10` 秒）防止并发迁移冲突。

---

## 11. 脚本一览

| 脚本 | 说明 |
|---|---|
| `scripts/apply_profile.sh` | 从模板生成 env 文件（本地默认 `.env`；`docker` 默认 `.env.docker`） |
| `scripts/apply_profile.ps1` | Windows PowerShell 等价脚本 |
| `scripts/docker_one_click.sh` | Docker 一键部署（macOS / Linux） |
| `scripts/docker_one_click.ps1` | Docker 一键部署（Windows） |
| `scripts/backup_memory.sh` / `.ps1` | 备份数据库（默认保留最近 20 份，UTC 时间戳） |

### 模板文件结构

```
deploy/profiles/
├── macos/
├── windows/
├── linux/
└── docker/
    profile-{a,b,c,d}.env
```
