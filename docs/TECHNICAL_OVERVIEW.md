# Memory Palace 技术总览

本文档面向需要了解系统架构或做二次开发的技术用户。

## 1. 技术栈

| 层 | 技术 | 版本 | 作用 |
|---|---|---|---|
| Backend | FastAPI + SQLAlchemy + SQLite | FastAPI ≥0.109 · SQLAlchemy ≥2.0 · aiosqlite ≥0.19 | 记忆读写、检索、审查、维护 |
| MCP | `mcp.server.fastmcp` | mcp ≥0.1 | 为 Codex / Claude Code / Gemini CLI / OpenCode 暴露统一工具面；IDE 宿主（Cursor / Windsurf / VSCode / Antigravity）通过 repo-local `AGENTS.md` + MCP 配置接入 |
| Frontend | React + Vite + TailwindCSS + Framer Motion | React ≥18.2 · Vite ≥7.3 · TailwindCSS ≥3.3 · Framer Motion ≥12.34 | 可视化 Dashboard |
| Runtime | 内置队列与 worker | — | 写入串行化、索引重建、vitality 衰减、sleep consolidation |
| Deployment | Docker Compose + profile 脚本 | Docker ≥20 · Compose ≥2.0 | A/B/C/D 档位部署 |

核心依赖详见 `backend/requirements.txt` 和 `frontend/package.json`。

> 仓库 compose 文件在卷名默认值上使用了嵌套 `${...:-...}`。较旧 Compose 实现解析失败时，可改走 `docker_one_click.sh/.ps1`，或显式设置 `MEMORY_PALACE_DATA_VOLUME`、`MEMORY_PALACE_SNAPSHOTS_VOLUME`、`COMPOSE_PROJECT_NAME`。

---

## 2. 后端结构

```
backend/
├── main.py               # FastAPI 入口，生命周期管理
├── mcp_server.py         # MCP 公开入口（9 个工具）
├── runtime_state.py      # 写入 lane、索引 worker、vitality 衰减
├── run_sse.py            # SSE 传输层（API Key 鉴权）
├── api/
│   ├── browse.py         # 记忆浏览与写入（/browse）
│   ├── review.py         # 审查、回滚、集成（/review）
│   ├── maintenance.py    # 维护、观测、vitality 清理（/maintenance）
│   ├── layering.py       # L2 层级摘要（/api/layering）
│   ├── forgetting.py     # 遗忘模拟、archive（/api/forgetting）
│   ├── search_quality.py # 搜索质量面板（/search）
│   └── setup.py          # 首启配置与本地 .env 写入（/setup）
├── db/
│   ├── sqlite_client.py  # 核心 CRUD、检索与治理
│   ├── search/           # FTS5 / vector / RRF / entity boost 检索通道
│   ├── snapshot.py       # 快照管理（按 session 隔离、原子写入、保守 retention/GC）
│   ├── migration_runner.py / migration_gate.py  # 自动迁移 + 备份护栏
│   └── migrations/       # SQL 迁移脚本
├── core/
│   ├── layering_engine.py     # L2 只读层级摘要
│   ├── forgetting_engine.py   # 衰减模拟与人工 archive
│   ├── compression_engine.py  # 预览式压缩候选
│   └── procedural_engine.py   # 程序性记忆草稿（需人工审批）
├── mcp/                  # 工具薄 wrapper、system://* 视图、host adapter
└── security/             # MCP 输入清洗、artifact stripping
```

> 部署、profile 应用、分享前自检等脚本位于仓库根目录的 `scripts/`，不在 `backend/` 下。

### 核心模块

- **`main.py`** — FastAPI 入口。负责数据库初始化、legacy DB 兼容恢复、CORS 配置、路由注册和健康检查。`/health` 对本机 loopback 或带有效 `MCP_API_KEY` 的请求返回详细 runtime 数据；未鉴权远端请求只返回浅健康结果。降级状态下返回 HTTP `503`。

- **`mcp_server.py`** — MCP 公开入口。提供 URI 解析（`domain://path`）、快照管理、Write Guard 决策、会话缓存、异步索引入队、系统 URI 资源（`system://boot`、`system://index` 等）。公开支持的入口是 `stdio` 和 SSE。MCP 入口层做严格契约校验：控制字符 / 不可见字符 / surrogate URI、超长 payload 都会被拦下。

- **`runtime_state.py`** — 管理写入 lane（串行化写操作）、索引 worker、vitality 衰减、cleanup review 审批和 sleep consolidation 调度。session-first 检索缓存采用"单 session 限长 + 总 session 数上限"的进程内边界。

- **`run_sse.py`** — SSE 传输层。负责 API Key 鉴权、`/sse` 与 `/messages` 会话管理、15 秒心跳。客户端断开后清理 session，旧 `session_id` 请求返回 `404/410`。

- **`setup.py`** — 首启配置与本地 `.env` 写入入口。区分"进程显式覆盖"和"启动时从 `.env` 读取"。第一次保存要求 Dashboard key 非空；provider API base 做归一化与校验。无 Dashboard auth 时首次保存会先 bootstrap `MCP_API_KEY`，retrieval/provider 字段需要后续带鉴权再保存。

- **`db/sqlite_client.py`** — SQLite 操作层。包含 CRUD、keyword/semantic/hybrid 检索、Write Guard 逻辑（语义匹配 + 关键词匹配 + LLM 决策三级判定）、gist 生成与缓存、vitality 评分与衰减、embedding 获取、reranker 集成。数据库初始化使用 `.init.lock` 做进程级串行化。

- **`db/migration_runner.py` / `migration_gate.py`** — 发现和执行 SQL migration，记录版本与 checksum。checksum 归一化处理 `CRLF/LF` 和 UTF-8 BOM。`MigrationGate` 在 destructive migration 前做 dry-run、备份和导出护栏。

- **`core/` engines** — `MemoryCore` 是兼容外观，只做委托。`layering_engine` 提供 L2 只读摘要；`forgetting_engine` 做衰减模拟和带 review token 的 archive，不自动删除；`compression_engine` 是预览式候选；`procedural_engine` 默认产出 `review_state="draft"`，需人工审批。派生数据带 `source_memory_ids`、`source_hashes`、`derivation_method`、`confidence`、`review_state` 等 provenance 字段。

---

## 3. HTTP API 入口

- `/browse` — 看记忆、写记忆（最常用）
- `/review` — 看 diff、回滚、确认集成
- `/maintenance` — 清理、重建索引、看运行状态
- `/api/layering` — L2 层级摘要
- `/api/forgetting` — 遗忘候选与人工 archive
- `/search/quality-metrics` — 搜索质量面板

### `/browse`

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/browse/node` | 浏览记忆树（含子节点、面包屑、gist、别名） |
| `POST` | `/browse/node` | 创建记忆节点（含 Write Guard） |
| `PUT` | `/browse/node` | 更新记忆节点（含 Write Guard） |
| `DELETE` | `/browse/node` | 删除记忆路径 |

- 写入会先记录 Review snapshot；session 名带数据库作用域（如 `dashboard-<scope>`）
- 单次 `content` 限制：`BROWSE_CONTENT_MAX_CHARS`（默认 1 MiB）
- 路径长度限制：`BROWSE_PATH_MAX_CHARS`（默认 512）
- write lane 塞满时返回结构化 `503`（`write_lane_timeout`）

### `/review`

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/review/sessions` | 列出审查会话 |
| `GET` | `/review/sessions/{session_id}/snapshots` | 查看会话快照列表 |
| `GET` | `/review/sessions/{session_id}/snapshots/{resource_id}` | 查看快照详情 |
| `GET` | `/review/sessions/{session_id}/diff/{resource_id}` | 查看版本 diff |
| `POST` | `/review/sessions/{session_id}/rollback/{resource_id}` | 执行回滚 |
| `DELETE` | `/review/sessions/{session_id}/snapshots/{resource_id}` | 确认集成（删除快照） |
| `DELETE` | `/review/sessions/{session_id}` | 清除整个 session 快照 |
| `GET` | `/review/deprecated` | 列出 deprecated 记忆 |
| `DELETE` | `/review/memories/{memory_id}` | 永久删除已审查记忆 |
| `POST` | `/review/diff` | 通用文本 diff 计算 |

边界说明：

- snapshot 文件位于 `snapshots/`，但会话列表和快照读取按当前数据库作用域过滤
- 同 `session_id` 的快照写路径串行化，`manifest.json` 与快照 JSON 文件通过原子替换落盘
- 保守 retention/GC：按 age/count 清理旧 session、保护当前 session、拿不到锁的旧 session 先跳过
- 内容快照已有更新时回滚会返回 `409`，避免覆盖较新改动
- metadata-only rollback 在写入前 fail-close 校验 path 状态

### `/maintenance`

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/maintenance/orphans` | 查看孤儿记忆 |
| `DELETE` | `/maintenance/orphans/{memory_id}` | 永久删除孤儿记忆 |
| `POST` | `/maintenance/import/prepare` | 准备外部导入 |
| `POST` | `/maintenance/import/execute` | 执行外部导入 |
| `POST` | `/maintenance/import/jobs/{job_id}/rollback` | 回滚导入 |
| `POST` | `/maintenance/learn/trigger` | 触发显式学习任务 |
| `POST` | `/maintenance/learn/reflection` | 触发 reflection workflow（`prepare/execute`） |
| `POST` | `/maintenance/vitality/decay` | 触发 vitality 衰减 |
| `POST` | `/maintenance/vitality/candidates/query` | 查询清理候选记忆 |
| `POST` | `/maintenance/vitality/cleanup/prepare` | 准备清理审批 |
| `POST` | `/maintenance/vitality/cleanup/confirm` | 确认并执行清理 |
| `GET` | `/maintenance/index/worker` | 索引 worker 状态 |
| `POST` | `/maintenance/index/rebuild` | 全量索引重建 |
| `POST` | `/maintenance/index/reindex/{memory_id}` | 单条索引重建 |
| `POST` | `/maintenance/index/sleep-consolidation` | 触发 sleep consolidation |
| `POST` | `/maintenance/observability/search` | 观测搜索 |
| `GET` | `/maintenance/observability/summary` | 观测概览 |

分 5 类：

1. **导入 / 学习任务**：`import/*`、`learn/*`
2. **孤儿记忆清理**：`orphans*`
3. **活力治理**：`vitality/*`
4. **索引任务**：`index/*`
5. **运行态观测**：`observability/*`

### `/api/layering`

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/layering/summaries` | 列出 L2 摘要（可按 `scope` / `review_state` 过滤） |
| `GET` | `/api/layering/summaries/{summary_id}` | 查看单条摘要与来源 drill-down |
| `POST` | `/api/layering/summaries/generate` | 基于 L1 memory ids 生成 draft 预览（`persisted=false`） |

### `/api/forgetting`

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/forgetting/simulate` | 纯读的活力衰减模拟 |
| `GET` | `/api/forgetting/candidates` | 返回低于阈值的候选队列 |
| `POST` | `/api/forgetting/archive/prepare` | 准备 archive review（生成 token 和确认短语） |
| `POST` | `/api/forgetting/archive/confirm` | 消费 token 后执行 archive |
| `POST` | `/api/forgetting/archive` | 单条 archive 低层接口 |

遗忘引擎不会自动删除记忆。当前写路径是带人工确认的 archive：原始 memory 标 deprecated，归档副本写入 `archived_memories`。

### `/search/quality-metrics`

Docker 前端代理路径是 `/api/search/quality-metrics`。当前明确返回 `is_mock=true`、`status=unavailable`、`reason=labelled_search_quality_samples_not_persisted`。Dashboard 面板里的 MRR / Recall 示例值仅用于 UI 占位，不要当成生产检索质量。

> 后端默认不公开 `/docs`；接口说明优先看本文档、[TOOLS.md](TOOLS.md) 和 `backend/tests/` 里的接口测试。

---

## 4. MCP 工具

| 工具 | 类型 | 说明 |
|---|---|---|
| `read_memory` | 读取 | 支持整段与分片，含系统 URI |
| `create_memory` | 写入 | 创建记忆（Write Guard，进入 write lane） |
| `update_memory` | 写入 | 优先 `old_string/new_string` 精确替换；`append` 仅用于尾追加 |
| `delete_memory` | 写入 | 删除记忆路径 |
| `add_alias` | 写入 | 为同一记忆添加别名（可跨域） |
| `search_memory` | 检索 | 统一检索入口（keyword/semantic/hybrid），支持意图分类与策略模板 |
| `compact_context` | 治理 | 将会话上下文压缩为长期记忆摘要 |
| `rebuild_index` | 维护 | 全量或单条索引重建，支持 sleep consolidation |
| `index_status` | 维护 | 查询索引可用性与运行时状态 |

详细参数与降级语义：[TOOLS.md](TOOLS.md)

---

## 5. 前端结构

```
frontend/src/
├── App.jsx                    # 路由与页面骨架
├── main.jsx                   # React 入口
├── RootErrorBoundary.jsx      # 根级 render 崩溃兜底
├── i18n.js                    # react-i18next 初始化
├── lib/
│   ├── api.js                 # 统一 API 客户端 + 运行时鉴权注入
│   ├── sse.js                 # 轻量 SSE helper
│   └── format.js              # 跟随语言的日期 / 数字格式化
├── locales/{en,zh-CN}.js
├── features/
│   ├── memory/                # 树形浏览、L0/L1/L2 层级视图
│   ├── review/                # diff / rollback / integrate
│   ├── maintenance/           # vitality 清理、遗忘候选
│   └── observability/         # 检索统计、搜索质量面板
└── components/                # DiffViewer / GlassCard / SnapshotList 等
```

### Dashboard 四大模块

| 模块 | 路由 | 功能 |
|---|---|---|
| Memory Browser | `/memory` | 按域树形浏览、内联编辑、gist 摘要、别名管理、L0/L1/L2 层级视图 |
| Review | `/review` | 查看 snapshot diff、rollback、integrate、清理 deprecated |
| Maintenance | `/maintenance` | vitality 评分、孤儿清理、索引重建、清理审批、遗忘模拟与 archive |
| Observability | `/observability` | 检索日志、任务记录、索引 worker、系统状态、搜索质量面板 |

**前端行为说明**：

- 首次访问无保存语言时，中文浏览器（`zh`、`zh-TW`、`zh-HK`、`zh-*`）归并到 `zh-CN`，其他回退英文
- 语言切换保存在 `localStorage` 的 `memory-palace.locale`
- React 根节点包 `RootErrorBoundary`：组件 render 崩溃时显示最小兜底页（跟随当前语言）
- 浏览器侧 Dashboard 鉴权保存在 `sessionStorage`；legacy `localStorage` 值会做一次迁移
- Docker 一键部署时，前端代理自动转发 `MCP_API_KEY`；浏览器页面不知道代理层的真实 key
- Setup Assistant 切换 Profile / backend 时清掉旧字段，避免残留；切到远端 backend 时只在显式填写 `RETRIEVAL_EMBEDDING_DIM` 后才保存
- vitality cleanup 多选删除在后端支持时原子执行；不支持时直接拒绝多删，避免半成功
- Memory 页"离开未保存编辑"和"删除路径"走 fail-closed 确认逻辑

---

## 6. 前端鉴权注入

前端不从 `VITE_*` 构建变量读取维护密钥，采用运行时注入：

```html
<script>
  window.__MEMORY_PALACE_RUNTIME__ = {
    maintenanceApiKey: "<YOUR_MCP_API_KEY>",
    maintenanceApiKeyMode: "header"   // 或 "bearer"
  };
</script>
```

- `maintenanceApiKeyMode`：`header`（`X-MCP-API-Key`）或 `bearer`（`Authorization: Bearer`）
- 也兼容旧字段名 `window.__MCP_RUNTIME_CONFIG__`
- 优先级：Setup Assistant 刚保存的 key > 运行时注入 key > 浏览器会话保存的 key
- 切换 mode 时拦截器会先删旧 header 再补新 header，避免同时带两套鉴权头

**Docker 一键部署**走第三种方式：不把 key 注入页面，而是在前端代理层自动转发。

---

## 7. 数据与任务流

### 写入路径

1. `create_memory` / `update_memory` 进入 **write lane**（串行化；遇 SQLite 锁冲突会先做有上限重试）
2. 写前执行 **Write Guard** 判定（`ADD` / `UPDATE` / `NOOP` / `DELETE`；`BYPASS` 是上层 metadata-only 流程标记）
   - 三级判定链：语义匹配 → 关键词匹配 → LLM 决策（可选）
3. 生成 **snapshot** 与版本变更（按 `path` 和 `memory` 两维度分别记录；同 session 通过文件锁串行化）
4. 入队 **索引任务**（队列满返回 `index_dropped` / `queue_full`）

### 检索路径

1. **`preprocess_query`** 预处理（标准化空白、分词、保留 URI）
2. **`classify_intent`** 按 4 种核心意图路由：
   - `factual` → `factual_high_precision`（高精度匹配）
   - `exploratory` → `exploratory_high_recall`（高召回探索）
   - `temporal` → `temporal_time_filtered`（时间过滤）
   - `causal` → `causal_wide_pool`（因果推理）
   - `unknown` → `default`（信号冲突或低信号时保守回退）
3. 执行 **keyword / semantic / hybrid** 检索
4. 可选 **reranker** 重排序
5. 支持 `scope_hint`、`domain`、`path_prefix`、`max_priority`
6. 返回 `results` 与 `degrade_reasons`

> 意图分类使用关键词评分实现，无需外部模型调用。
>
> 向量维度检查跟着当前查询的 scope 走，无关 domain 不会触发假的重建提示。
>
> `scope_hint=fast|deep` 会先按 interaction tier 快捷值处理；新调用方建议直接传 `interaction_tier`。

**可选配置**：

- `INTENT_LLM_ENABLED` 默认关闭；开启后优先 LLM 意图分类，失败回退关键词规则
- `RETRIEVAL_MMR_ENABLED` 默认关闭；仅 `hybrid` 检索下做去重 / 多样性重排
- `RRF_ENABLED` 默认关闭；开启后只在 `fts5` / `vector` 通道做 RRF，默认 `RRF_K=60`
- `ENTITY_RERANK_WEIGHT` 默认 `0.0`；entity 信号是 fusion 后的 boost，不是第三条 RRF channel
- `RETRIEVAL_SQLITE_VEC_ENABLED` 默认关闭，legacy 向量路径仍是默认实现

![记忆写入与审查时序图](images/记忆写入与审查时序图.png)

---

## 8. 部署口径

| 场景 | 宿主机端口 | 容器内部端口 |
|---|---|---|
| 本地开发 | Backend `8000` · Frontend `5173` | — |
| Docker 默认 | Backend `18000` · Frontend `3000` · SSE `3000/sse` | Backend `8000`（同时承载 REST + SSE） · Frontend `8080` |

端口环境变量：

- Backend：`MEMORY_PALACE_BACKEND_PORT`（默认 `18000`，回退 `NOCTURNE_BACKEND_PORT`）
- Frontend：`MEMORY_PALACE_FRONTEND_PORT`（默认 `3000`，回退 `NOCTURNE_FRONTEND_PORT`）

> 把 SSE 监听地址改成 `0.0.0.0` 只表示远程客户端可以连，**不表示**可以跳过 `MCP_API_KEY`、反向代理、防火墙或 TLS 等安全控制。

### 相关文件

- **Compose**：`docker-compose.yml`、`docker-compose.ghcr.yml`
- **镜像**：`deploy/docker/Dockerfile.backend`（`python:3.11-slim`）、`deploy/docker/Dockerfile.frontend`（构建 `node:22-alpine`，运行 `nginxinc/nginx-unprivileged:1.27-alpine`）
- **健康检查**：`deploy/docker/backend-healthcheck.py`（要求 `/health` 返回 `status == "ok"`，默认 5 秒超时）
- **Nginx 模板**：`deploy/docker/nginx.conf.template`（只对受保护路径和 `/sse` / `/messages` 注入 `X-MCP-API-Key`，对 `/index.html` 返回 `no-store/no-cache/must-revalidate`）
- **入口脚本**：`deploy/docker/backend-entrypoint.sh`、`deploy/docker/frontend-entrypoint.sh`
- **备份**：`scripts/backup_memory.sh` / `.ps1`（默认保留最近 20 份，UTC 时间戳）
- **分享前检查**：`scripts/pre_publish_check.sh`（拦截 tracked `.audit` / `.playwright-mcp` 工件，扫描 tracked 文件里的本地 endpoint / key 模式）

详细验证结果见 [EVALUATION.md](EVALUATION.md)。

---

## 9. 安全默认值

- `/maintenance/*`、`/review/*`、`/api/layering/*`、`/api/forgetting/*`、`/search/quality-metrics` 所有端点需 API Key 鉴权
- `/browse` 读写均通过端点级 `Depends(require_maintenance_api_key)` 门控
- 公开 HTTP 端点：`/` 与 `/health`（`/health` 浅健康结果对外公开，详细 runtime/index 仅对 loopback 或带 key 的请求开放）
- `MCP_API_KEY` 为空时默认 **fail-closed**
- `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` 仅对 loopback 请求生效，且仅限直连 loopback 无 forwarding headers
- `/setup/config` 本地 `.env` 写入路径同样 fail-closed：只写当前项目 `.env*`、只允许直连 loopback、第一次保存要求 Dashboard key 非空
- Setup/provider API base 先做归一化和校验，运行时读到无效 base 时按 fail-closed 走降级
- Docker 容器默认非 root：
  - Backend：`app` 用户（UID `10001`）
  - Frontend：`nginx-unprivileged` 镜像

详细策略：[SECURITY_AND_PRIVACY.md](SECURITY_AND_PRIVACY.md)
