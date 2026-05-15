# Memory Palace 安全与隐私指南

本文档面向部署和维护 Memory Palace 的用户，涵盖密钥管理、接口鉴权、Docker 安全，以及分享或正式发布前的安全自检。

---

## 1. 你需要保护什么

以下密钥 **只应存在于本地 `.env` 或受保护的部署环境变量中**，不应提交到 Git 仓库。

> 完整密钥清单可参考 [`.env.example`](../.env.example)。

| 密钥 | 用途 | 在 `.env.example` 中对应变量 |
|---|---|---|
| `MCP_API_KEY` | 维护接口、审查接口、Browse 读写与 SSE 鉴权 | `MCP_API_KEY=` |
| `RETRIEVAL_EMBEDDING_API_KEY` | Embedding 模型 API 访问 | `RETRIEVAL_EMBEDDING_API_KEY=` |
| `RETRIEVAL_RERANKER_API_KEY` | Reranker 模型 API 访问 | `RETRIEVAL_RERANKER_API_KEY=` |
| `WRITE_GUARD_LLM_API_KEY` | Write Guard LLM 决策 | `WRITE_GUARD_LLM_API_KEY=` |
| `COMPACT_GIST_LLM_API_KEY` | Compact Context Gist LLM（为空时自动回退到 Write Guard） | `COMPACT_GIST_LLM_API_KEY=` |
| `INTENT_LLM_API_KEY` | 实验性 Intent LLM 决策 | `INTENT_LLM_API_KEY=` |
| `ROUTER_API_KEY` | Router 模式下的 Embedding API 访问；以及 Reranker 未显式配置 `RETRIEVAL_RERANKER_API_KEY` 时的回退密钥 | `ROUTER_API_KEY=` |

---

## 2. 推荐做法

- ✅ 只提交 `.env.example`，**不要提交** `.env`（已写入 [`.gitignore`](../.gitignore)）
- ✅ 文档里只写 `<YOUR_API_KEY>` 这种占位符
- ✅ 公开截图前确认没有包含真实 key、用户名、绝对路径
- ✅ 对外日志中不打印请求头和密钥
- ✅ 定期轮换 API Key，尤其在团队成员变更后
- ✅ Docker 场景优先使用服务端代理转发鉴权头，而不是把 key 写进前端静态资源

---

## 3. 接口鉴权策略

### 受保护的接口范围

以下接口默认都受保护：

| 接口前缀 | 保护范围 | 代码出处 |
|---|---|---|
| `/maintenance/*` | 所有请求 | `backend/api/maintenance.py` — `require_maintenance_api_key` 作为路由依赖 |
| `/review/*` | 所有请求 | `backend/api/review.py` — 导入并依赖同一鉴权函数 |
| `/browse/*` | 所有请求（含读操作） | `backend/api/browse.py` — 路由统一挂载 `Depends(require_maintenance_api_key)` |
| `/api/layering/*` | 所有请求 | `backend/api/layering.py` — 路由统一依赖同一鉴权函数 |
| `/api/forgetting/*` | 所有请求 | `backend/api/forgetting.py` — 路由统一依赖同一鉴权函数 |
| `/search/quality-metrics` | 所有请求 | `backend/api/search_quality.py` — 搜索质量面板接口，仍需维护 key |
| SSE 接口 | `/sse` 与 `/messages` | `backend/run_sse.py` — 可复用 ASGI 鉴权中间件与 SSE transport，既可被 standalone `run_sse.py` 使用，也可被 `backend/main.py` 挂载 |

> 📖 `/browse/node` 的 `GET` 请求也在鉴权范围内，请携带 `X-MCP-API-Key` 或 `Authorization: Bearer`。

### 鉴权方式（二选一）

**Header 方式（推荐）：**

```
X-MCP-API-Key: <MCP_API_KEY>
```

**Bearer Token 方式：**

```
Authorization: Bearer <MCP_API_KEY>
```

> 后端使用 `hmac.compare_digest` 进行恒等时间比较（参见 `backend/api/maintenance.py` 与 `backend/run_sse.py` 中的鉴权实现），防止时序攻击。

### SSE `/messages` 突发限流

`/messages` 不是无限速入口。当前实现会按**稳定客户端主体**做进程内突发限流：

| 配置项 | 默认值 | 作用 |
|---|---|---|
| `SSE_MESSAGE_RATE_LIMIT_WINDOW_SECONDS` | `10` | 统计窗口（秒） |
| `SSE_MESSAGE_RATE_LIMIT_MAX_REQUESTS` | `120` | 单个客户端主体在窗口内允许的最大 POST 次数 |
| `SSE_MESSAGE_MAX_BODY_BYTES` | `1048576` | 单个 `/messages` 请求体的硬上限（字节） |

触发限流时：

- 返回 `429 Too Many Requests`
- 响应头包含 `Retry-After`
- 当前客户端主体的后续请求需要等窗口释放
- 超过 `SSE_MESSAGE_MAX_BODY_BYTES` 时会在 JSON 解析前直接返回 `413`

这里的“客户端主体”当前优先按**解析后的客户端地址**分桶；如果请求本身带了 API key / Bearer token，还会把该 token 的稳定哈希一起并入 key。说人话就是：单纯重连换一个新的 `session_id`，已经不能直接把 `/messages` 的限流桶清零。

如果这条 SSE 链路跑在**受信代理后面**（例如仓库自带的 Docker 前端代理，或你自己控制的私有反向代理），当前限流 key 会优先读取：

- `X-Forwarded-For` 里的第一个合法 IP
- 取不到时再看 `X-Real-IP`
- 只有不在受信代理后面时，才直接按当前连接对端地址分桶

这里的“受信代理”也不是看见转发头就自动信。当前默认只信 loopback 代理；如果你自己的反向代理不在 loopback 上，需要显式补 `SSE_TRUSTED_PROXY_HOSTS` 或 `SSE_TRUSTED_PROXY_CIDRS`，否则转发头不会参与分桶。

这意味着在 Docker 默认代理路径下，`/messages` 的 burst limit 不再把所有客户端都算成同一个前端容器地址；但在你自己的部署里，只有显式 allowlist 过的代理，才会让 `X-Forwarded-For` / `X-Real-IP` 生效。

另外，`/sse` 流默认还会发心跳（当前默认 15 秒），主要目的是让长连接在代理链路上更稳定，不至于看起来像“静默挂住”。

这层限流主要用于拦截**误配置客户端或单主体突发刷写**；它不是公网暴露场景下的完整 DDoS 防护，也不能替代外层的 VPN、反向代理限流或网络访问控制。

### 无 Key 时的默认行为

鉴权遵循 **fail-closed** 策略，具体逻辑如下：

| 条件 | 行为 | HTTP 响应 |
|---|---|---|
| `MCP_API_KEY` 已设置且请求携带正确 Key | ✅ 放行 | — |
| `MCP_API_KEY` 已设置但 Key 错误或缺失 | ❌ 拒绝 | `401`，`reason: invalid_or_missing_api_key` |
| `MCP_API_KEY` 为空，`MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`，请求来自 loopback 且不包含 `Forwarded` / `X-Forwarded-*` / `X-Real-IP` 等转发头 | ✅ 放行 | — |
| `MCP_API_KEY` 为空，`MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`，请求来自 loopback 但包含 `Forwarded` / `X-Forwarded-*` / `X-Real-IP` 等转发头 | ❌ 拒绝 | `401`，`reason: insecure_local_override_requires_loopback` |
| `MCP_API_KEY` 为空，`MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`，请求非 loopback | ❌ 拒绝 | `401`，`reason: insecure_local_override_requires_loopback` |
| `MCP_API_KEY` 为空，未开启 insecure local | ❌ 拒绝 | `401`，`reason: api_key_not_configured` |

> 📌 Loopback 地址仅包含 `127.0.0.1`、`::1`、`localhost`（代码常量 `_LOOPBACK_CLIENT_HOSTS`）；且必须为直连本机请求（无 `Forwarded` / `X-Forwarded-*` / `X-Real-IP` 等转发头）。

### 当前仓库中的验证锚点

以上鉴权逻辑在当前仓库的以下测试文件中有覆盖：

- `backend/tests/test_week6_maintenance_auth.py` — 维护 API 五项鉴权场景
- `backend/tests/test_week6_sse_auth.py` — SSE 鉴权场景
- `backend/tests/test_week6_sse_auth.py::test_sse_messages_rate_limit_returns_429` — `/messages` 限流与 `Retry-After` 行为
- `backend/tests/test_week6_sse_auth.py::test_sse_messages_reject_oversized_body_with_413` — `/messages` 请求体大小上限
- `backend/tests/test_week6_sse_auth.py::test_sse_rate_limit_prefers_forwarded_client_ip_for_trusted_proxy` — 受信代理下优先使用真实客户端 IP
- `backend/tests/test_sensitive_api_auth.py` — Review 与 Browse 读写鉴权
- `backend/tests/test_review_rollback.py` — Review 操作携带鉴权测试
- `backend/tests/test_reflection_workflow_service.py` — 验证 Dashboard `/browse` 写入可供 reflection workflow 继续使用，以及 `reflection execute` 进入 write lane 后的并发边界
- `backend/tests/test_reflection_workflow_api.py` — 验证 reflection rollback 在已知 `session_id` 时会继续做一致性校验，只带 `job_id` 时会先恢复原始 `session_id`，并在 review rollback 后继续做 best-effort namespace cleanup
- `backend/tests/test_reflection_observability_summary.py` — 验证 `reflection_workflow` 统计在 summary 层是 restart-stable
- `backend/tests/test_setup_api.py` — 验证 `openai` embedding backend、远端 `RETRIEVAL_EMBEDDING_DIM` 显式必填、`/setup/status` 默认汇总与运行时默认值一致，以及 setup fail-closed 边界
- `backend/tests/test_layering_engine.py` / `backend/tests/test_forgetting_engine.py` — 验证 L2 read-only、遗忘候选与 archive 人工确认边界
- `backend/tests/test_sse_deploy_contracts.py` — 验证 Docker 前端代理只给受保护路由注入 `X-MCP-API-Key`，并覆盖 `/api/layering/*`、`/api/forgetting/*`、`/api/search/quality-metrics`
- `backend/tests/test_artifact_stripper.py` / `backend/tests/test_prompt_cache_adapter.py` — 验证 opt-in adapter 默认 no-op，只有 env flag + host capability 同时满足才生效
- `frontend/src/App.test.jsx` — 验证 proxy-held auth 已生效时首启向导不误弹
- `frontend/src/features/memory/MemoryBrowser.test.jsx` — 验证 `confirm()` 不可用时 Memory 页 fail-closed

---

## 4. 前端密钥注入（运行时）

前端不在构建时写死密钥，而是通过运行时注入读取。这个方式更适合本地调试或你自己控制的私有部署环境：

```html
<script>
  window.__MEMORY_PALACE_RUNTIME__ = {
    maintenanceApiKey: "<YOUR_MCP_API_KEY>",
    maintenanceApiKeyMode: "header"  // 可选值: "header" | "bearer"
  };
</script>
```

> ⚠️ 这适合本地调试或你自己控制的部署环境。不要把真实 `MCP_API_KEY` 直接写进公开页面或任何会暴露给最终用户的静态资源里，因为浏览器里可以直接读到这个全局对象。

**工作原理**（参见 `frontend/src/lib/api.js`）：

1. `readRuntimeMaintenanceAuth()` 读取 `window.__MEMORY_PALACE_RUNTIME__`
2. axios 请求拦截器 `isProtectedApiRequest()` 判断请求是否需要鉴权
3. 对 `/maintenance/*`、`/review/*`、`/browse/*`、`/setup/*`、`/layering/*`、`/forgetting/*` 以及 `/search/quality-metrics` 自动注入鉴权头
4. Observability 订阅 `/sse` 时也会复用这套鉴权：没有浏览器侧 Dashboard key 时继续走原生 `EventSource`；有 key 时切到可带 header/bearer 的 fetch-based SSE，这样不会把 key 拼到 URL 里；而且每次重连都会重新读取当前浏览器里的 Dashboard 鉴权，并继续带上 `Last-Event-ID`；明确的 `4xx` 鉴权失败则会停止重试。现在只要浏览器侧 Dashboard 鉴权被修改、清空，前端还会额外发出一条 maintenance-auth 变更事件；Observability 会利用这条事件，再加上重新聚焦标签页时的检查，在鉴权变更后或终态 `401` 之后重建带鉴权的连接。

> 兼容性：也支持旧字段名 `window.__MCP_RUNTIME_CONFIG__`（见 `frontend/src/lib/api.js` 中的 runtime config fallback 逻辑）。
>
> 如果服务端 Dashboard 鉴权已经生效，尤其是标准 Docker proxy-held key 路径，前端现在不会只因为浏览器本地还没保存 key 就自己弹出首启向导。

### 首启配置向导的安全边界

当前版本新增了 Dashboard 首启配置向导，但它不是“浏览器随便改服务器配置”的通用后门：

- `/setup/status` 允许两种访问方式：
  - **直连本机回环地址**（`127.0.0.1` / `::1` / `localhost`，且不带 forwarded headers，并且请求里的 host 本身也是 loopback）
  - **携带有效 `MCP_API_KEY`**
- `/setup/config` 的**写入能力只允许直连本机回环地址**；即使拿着有效 `MCP_API_KEY`，远端请求也不能直接改主机 `.env`
- 向导接口只允许写入一组白名单 env 键，不支持任意文件写入
- 现阶段只允许写本地 checkout 的 `.env`
- `/setup/status` 现在会按当前运行时真实默认值返回检索摘要；如果相关 env 全缺失，本地运行态会显示成 `hash / 64`。首启向导里自动弹出的 `Profile A` 起步表单仍然只是前端引导口径，不是说这个 HTTP 状态接口会把真实运行态伪装成 `none`
- 第一次往本地 `.env` 保存时，`Dashboard API key` 现在必须非空；留空会被后端直接拒绝，不再当成匿名自举
- 如果当前进程运行在 Docker 内部，向导会明确返回 `setup_apply_unsupported`，停留在说明模式，不会伪装成已经持久化容器 env / 代理配置
- 向导不会把现有 secret 值回显到前端；前端只能看到“是否已配置”的摘要状态
- 浏览器本地只会把 Dashboard 使用的 `MCP_API_KEY` 放在当前浏览器会话的 `sessionStorage`；embedding / reranker / LLM key 不会保存在浏览器里。若检测到旧版 `localStorage` 值，前端仍只会做一次迁移，但现在只会在确认 `localStorage` 里还是**同一份旧值**时才删除它，避免多标签页并发迁移时误删另一标签页刚写入的新值。
- Observability 的 `/sse` 订阅现在也跟随这条浏览器侧 Dashboard 鉴权：没有浏览器侧 key 时继续走原生 `EventSource`；有 key 时切到可带 header/bearer 的 fetch-based SSE。这样不会把 key 放进 URL，临时断流还能自动重连；而且每次重连都会重新读取当前浏览器里的 Dashboard 鉴权，同时继续带上 `Last-Event-ID`；明确的 `4xx` 鉴权失败则会停止重试。
- 如果服务端 Dashboard 鉴权已经生效，前端不会只因为浏览器本地还没保存 Dashboard key 就自动弹出首启配置向导；这样能减少在 proxy-held key 部署里把真实 `MCP_API_KEY` 再存进浏览器的误操作。
- 向导切档时，当前已经隐藏掉的旧字段会跟着本次保存一起清掉，减少把上一档残留的 router/API 字段继续带进本次提交的风险。
- 切到远端 embedding backend 时，setup 保存会显式写入 `RETRIEVAL_EMBEDDING_DIM`；`/setup/config` 现在也支持 `openai` embedding backend。
- provider API base 字段现在会先做归一化和校验：`/embeddings`、`/rerank`、`/chat/completions`、`/responses` 这类常见尾缀会自动去掉；格式不对、带凭证、或指到 link-local 的地址会直接拒绝。`127.0.0.1` / `::1` 这类 loopback IP 字面量，再加上 `localhost`，仍然默认允许；如果你故意指到其它 private IP 字面量，或者指到一个解析后会落到 private 非 loopback 地址的 hostname，还要通过 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` 显式放行。
- 当前运行时如果读到无效的 `chat / embedding / reranker` API base，也会按 fail-closed 处理：直接忽略这条配置并走降级/回退，不会继续拿这类地址发请求。
- Memory 页在确认弹窗不可用时也会保持同样的 fail-closed 边界：不会继续执行删除或跳转，而是直接拦下动作并给出页内提示。
- `ArtifactStripper` 与 `PromptCacheAdapter` 都是 opt-in adapter。前者需要 `ARTIFACT_STRIPPING_ENABLED` 和 host capability `can_strip_tool_artifacts=true` 同时满足；后者需要 `PROMPT_CACHE_SPLIT_ENABLED` 和 `can_set_system_context=true` 同时满足。默认情况下它们都保持 no-op，不会改变 `read_memory("system://boot")` 或 MCP 工具返回契约。

**新增测试锚点：**

- `backend/tests/test_setup_api.py` — 验证本地 loopback 访问、远程鉴权、白名单 `.env` 写入、远端 `embedding_dim` 显式必填、`/setup/status` 默认汇总与运行时默认值一致，以及 Docker fail-closed
- `backend/tests/test_reflection_workflow_api.py` — 验证 reflection rollback 在已知 `session_id` 时会继续做一致性校验，只带 `job_id` 时会先恢复原始 `session_id`，并在 review rollback 后继续做 best-effort namespace cleanup
- `frontend/src/App.test.jsx` — 验证首启自动弹出、“只保存 Dashboard 密钥”交互，以及 proxy-held auth 已生效时不误弹
- `frontend/src/features/observability/ObservabilityPage.test.jsx` — 验证 Observability 在有浏览器侧鉴权时会改走可带鉴权头的 SSE 路径，并在事件到达后刷新 summary，也会在鉴权变化后重建这条带鉴权的连接
- `frontend/src/lib/api.test.js` — 验证浏览器侧 maintenance-auth 变更通知会在保存/清除和匹配的 storage 事件上触发
- `frontend/src/lib/api.contract.test.js` — 验证 `/setup/*` 也走统一鉴权头注入
- `frontend/src/lib/sse.test.js` — 验证带鉴权头的 fetch-based SSE 会在临时断流后重连、重连时刷新当前浏览器鉴权并保留 `Last-Event-ID`，以及在终态 `4xx` 鉴权失败时停止重试
- `backend/tests/test_external_import_guard_security.py` — 验证外部导入会在读正文前先按 metadata 拦住超大单文件/超大批次，且非 UTF-8 文本会稳定返回 `file_read_failed`，不会再冒出 fd 重复关闭错误
- `frontend/src/features/memory/MemoryBrowser.test.jsx` — 验证 `confirm()` 不可用时 Memory 页 fail-closed

**Docker 一键部署的默认做法不一样：**

- `apply_profile.*` 在 `docker` 平台下如果发现 `MCP_API_KEY` 为空，会自动生成一把本地 key
- 前端容器不会把这把 key 写进页面，而是由 Nginx 代理在服务端只转发到受保护的 Dashboard API 路径，以及 `/sse`、`/messages`
- 这样浏览器可以直接使用 Dashboard，但不会在页面源码里暴露真实 key
- 但这条便利路径默认把前端端口本身视为可信入口。谁能直接访问 Docker Dashboard 端口，谁就能使用这些被代理的受保护接口，所以这一层的 `MCP_API_KEY` **并不等于** 终端用户鉴权。若要暴露给受信范围之外的使用者，请先在 `3000` 前面加上你自己的 VPN、反向代理鉴权或网络访问控制。

**前端测试覆盖：**

- `frontend/src/lib/api.contract.test.js` — 验证 runtime config 注入与鉴权头附加

---

## 5. Docker 安全

以下安全配置可在项目 Docker 文件中直接验证：

| 安全措施 | 实现方式 | 文件引用 |
|---|---|---|
| 非 root 运行（后端） | `groupadd --gid 10001 app && useradd --uid 10001` | `deploy/docker/Dockerfile.backend` |
| 非 root 运行（前端） | 使用 `nginxinc/nginx-unprivileged:1.27-alpine` 基础镜像 | `deploy/docker/Dockerfile.frontend` |
| 前端代理鉴权 | 由 Nginx 在服务端转发 `X-MCP-API-Key`，浏览器侧不保存真实 key；当前仅对受保护的 `/api/maintenance/*`、`/api/review/*`、`/api/browse/*`、`/api/setup/*`、`/api/layering/*`、`/api/forgetting/*`、精确 `/api/search/quality-metrics` 以及 `/sse` / `/messages` 路径注入该头，通用 `/api/*` 不再一律附加；生成配置前会先转义代理持有 key 里的特殊字符 | `deploy/docker/nginx.conf.template` |
| 禁止提权 | `security_opt: no-new-privileges:true` | `docker-compose.yml` |
| 数据持久化 | Docker Volumes 默认按 compose project 隔离：`<compose-project>_data` → `/app/data`，`<compose-project>_snapshots` → `/app/snapshots` | `docker-compose.yml` |
| 健康检查（后端） | `python /usr/local/bin/backend-healthcheck.py`；脚本内部会请求 `http://127.0.0.1:8000/health`，并要求返回 payload 的 `status == "ok"`；请求超时可通过 `MEMORY_PALACE_BACKEND_HEALTHCHECK_TIMEOUT_SEC` 调整。backend 镜像现在也会把这条检查接进 Docker `HEALTHCHECK` | `docker-compose.yml` 中的 `backend.healthcheck`、`deploy/docker/backend-healthcheck.py`、`deploy/docker/Dockerfile.backend` |
| 健康检查（前端） | `wget -q -O - http://127.0.0.1:8080/` | `docker-compose.yml` 中的 `frontend.healthcheck` |

---

<p align="center">
  <img src="images/security_checklist.png" width="900" alt="分享前安全自检清单" />
</p>

## 6. 分享或发布前自检清单

在分享项目、交付环境或正式发布之前，请完成以下仓库卫生与安全自检步骤：

0. **一键自检（推荐）**：

   ```bash
   bash scripts/pre_publish_check.sh
   ```

   该脚本会检查：常见本地敏感产物 / 工具配置 / 本地报告是否存在、是否被 git 跟踪、已跟踪文件中的密钥模式、个人绝对路径泄露、`.env.example` 的 API key 占位状态。当前还会额外拦截已跟踪的 `.audit` / `.playwright-mcp` 工件，并扫描 tracked 文件里的本地 endpoint / key 模式（例如 `sk-local-*`、以及带端口的 loopback / private provider 地址）。它更像“分享前仓库卫生检查”；如果只是发现本地文件存在，通常会给 `WARN`，不是直接 `FAIL`。

1. **检查工作区状态** — 确认无意外暴露：

   ```bash
   git status
   ```

   应确保以下文件不在提交中（均已在 `.gitignore` 中配置）：
   - `.env`、`.env.*`（保留 `.env.example`；如你显式复用了固定 Docker env 文件，也包括 `.env.docker`）
   - `.venv`、`.mcp.json`、`.mcp.json.bak`、`.claude/`、`.codex/`、`.cursor/`、`.opencode/`、`.gemini/`、`.agent/`、`.tmp/`、`.playwright-cli/`（通常由你本地的 sync / install / 浏览器验证脚本生成）
   - `*.db`（数据库文件）
   - `*.init.lock`、`*.migrate.lock`（数据库初始化 / 迁移锁文件）
   - `backend/backend.log`、`frontend/frontend.log`
   - `snapshots/`、`frontend/dist/`
   - `backend/tests/benchmark/.real_profile_cache/`
   - `docs/skills/TRIGGER_SMOKE_REPORT.md`、`docs/skills/MCP_LIVE_E2E_REPORT.md`
   - 任意 `.DS_Store`

2. **关键字扫描** — 检查代码和文档中是否残留真实密钥：

   ```bash
   # 搜索可能的密钥泄露（建议只看文件名，避免在终端回显真实值）
   rg -n -l "sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY" .
   ```

3. **检查绝对路径** — 确保文档中不包含本机路径：

   ```bash
   # 如需手工补查，请先把下面的占位符替换成你自己的实际路径前缀
   grep -rn "<user-home>" --include="*.md" <repo-root>
   grep -rn "C:/absolute/path/to/" --include="*.md" <repo-root>
   ```

4. **运行验证** — 确认项目可复现构建：

   ```bash
   # 最小检查
   bash scripts/pre_publish_check.sh
   curl -fsS http://127.0.0.1:8000/health

   # 前端构建检查
   cd frontend && npm ci && npm run test && npm run build
   ```

   > 如需更深一层的验证，再额外运行 `cd backend && .venv/bin/python -m pip install -r requirements-dev.txt && .venv/bin/python -m pytest tests -q`。

---

## 7. 通常不应提交的本地文件

| 文件 / 目录 | 说明 |
|---|---|
| `.env`、`.env.*`（保留 `.env.example`） | 可能包含真实 API Key |
| `.venv`、`backend/.venv`、`frontend/.venv` | 本地虚拟环境，不应进入仓库 |
| `.mcp.json`、`.mcp.json.bak`、`.claude/`、`.codex/`、`.cursor/`、`.opencode/`、`.gemini/`、`.agent/`、`.tmp/`、`.playwright-cli/` | 本地工具 / MCP / 浏览器验证产物目录（通常由你本地的 sync / install / 调试脚本生成） |
| `*.db` | SQLite 数据库文件（如 `demo.db`） |
| `*.init.lock`、`*.migrate.lock` | 数据库初始化 / 迁移时生成的锁文件 |
| `backend/backend.log` | 后端运行日志 |
| `frontend/frontend.log` | 前端运行日志 |
| `snapshots/` | 本地快照目录 |
| `backend/tests/benchmark/.real_profile_cache/` | 本地 benchmark 临时数据库 |
| `__pycache__/`、`.pytest_cache/`、`backend/.pytest_cache/` | Python 缓存 |
| `frontend/node_modules` | NPM 依赖 |
| `frontend/dist/` | 前端构建产物 |
| `.DS_Store` | macOS 系统文件 |
| `backups/` | 本地备份目录 |
| `docs/improvement/` | 阶段性计划、重测草稿、排障记录 |
| `<repo-root>/docs/skills/TRIGGER_SMOKE_REPORT.md` | 本地 skill smoke 摘要 |
| `<repo-root>/docs/skills/MCP_LIVE_E2E_REPORT.md` | 本地 MCP e2e 摘要 |
| `backend/docs/benchmark_*.md` | 本地 benchmark 分析笔记 |
| `backend/tests/benchmark_results.md` | 一次性 benchmark 汇总草稿 |
| `docs/evaluation_old_vs_new_executive_summary_2026-03-05.md` | 一次性对照摘要 |
| `docs/changelog/current_code_improvements_vs_legacy_docs.md` | 补充差异清单 |

> 💡 保留 `.env.example` 作为配置模板提交到仓库。
>
> 💡 这两份本地验证报告默认会写到上面的 `docs/skills/` 路径；如果你通过 `MEMORY_PALACE_SKILL_REPORT_PATH` / `MEMORY_PALACE_MCP_E2E_REPORT_PATH` 改过输出位置，分享前也记得检查那份自定义文件。
>
> 💡 公开文档里建议统一使用占位符：
>
> - `<repo-root>`：仓库根目录
> - `<user-home>`：用户目录
> - `/absolute/path/to/...`：macOS / Linux 绝对路径示例
> - `C:/absolute/path/to/...`：Windows 绝对路径示例
