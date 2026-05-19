# Memory Palace 安全与隐私指南

本文档面向部署和维护 Memory Palace 的用户，涵盖密钥管理、接口鉴权、Docker 安全，以及分享或正式发布前的安全自检。

---

## 1. 你需要保护什么

以下密钥 **只应存在于本地 `.env` 或受保护的部署环境变量中**，不应提交到 Git 仓库。完整密钥清单可参考 [`.env.example`](../.env.example)。

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

- 只提交 `.env.example`，**不要提交** `.env`（已写入 [`.gitignore`](../.gitignore)）
- 文档里只写 `<YOUR_API_KEY>` 这种占位符
- 公开截图前确认没有包含真实 key、用户名、绝对路径
- 对外日志中不打印请求头和密钥
- 定期轮换 API Key，尤其在团队成员变更后
- Docker 场景优先使用服务端代理转发鉴权头，而不是把 key 写进前端静态资源

---

## 3. 接口鉴权策略

### 受保护的接口范围

以下接口默认都受保护：

| 接口前缀 | 保护范围 |
|---|---|
| `/maintenance/*` | 所有请求 |
| `/review/*` | 所有请求 |
| `/browse/*` | 所有请求（含读操作） |
| `/api/layering/*` | 所有请求 |
| `/api/forgetting/*` | 所有请求 |
| `/search/quality-metrics` | 所有请求 |
| SSE 接口 | `/sse` 与 `/messages` |

> `/browse/node` 的 `GET` 请求也在鉴权范围内，请携带 `X-MCP-API-Key` 或 `Authorization: Bearer`。

### 鉴权方式（二选一）

**Header 方式（推荐）：**

```
X-MCP-API-Key: <MCP_API_KEY>
```

**Bearer Token 方式：**

```
Authorization: Bearer <MCP_API_KEY>
```

> 后端使用 `hmac.compare_digest` 进行恒等时间比较，防止时序攻击。

### 错误响应格式

受保护的 Dashboard API 使用 FastAPI 标准响应体。业务错误优先返回结构化 `detail` 对象：

```json
{
  "detail": {
    "error": "invalid_or_missing_api_key",
    "reason": "invalid_or_missing_api_key"
  }
}
```

客户端应同时兼容历史或框架产生的 `detail: "..."` 字符串，以及新的 `detail.error` / `detail.reason` 对象字段。`detail.error` 作为稳定错误码使用；`detail.reason` 可用于展示或记录具体原因。

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

“客户端主体”按**解析后的客户端地址**分桶；如果请求带了 API key / Bearer token，会把该 token 的稳定哈希一起并入 key。单纯重连换一个新的 `session_id`，不能把 `/messages` 的限流桶清零。

如果这条 SSE 链路跑在**受信代理后面**（例如仓库自带的 Docker 前端代理，或你自己控制的私有反向代理），限流 key 会优先读取：

- `X-Forwarded-For` 里的第一个合法 IP
- 取不到时再看 `X-Real-IP`
- 只有不在受信代理后面时，才按当前连接对端地址分桶

默认只信 loopback 代理；如果你自己的反向代理不在 loopback 上，需要显式补 `SSE_TRUSTED_PROXY_HOSTS` 或 `SSE_TRUSTED_PROXY_CIDRS`，否则转发头不会参与分桶。

`/sse` 流默认还会发心跳（每 15 秒），让长连接在代理链路上更稳定。

这层限流主要用于拦截**误配置客户端或单主体突发刷写**；它不是公网暴露场景下的完整 DDoS 防护，也不能替代外层的 VPN、反向代理限流或网络访问控制。

### 无 Key 时的默认行为

鉴权遵循 **fail-closed** 策略：

| 条件 | 行为 | HTTP 响应 |
|---|---|---|
| `MCP_API_KEY` 已设置且请求携带正确 Key | ✅ 放行 | — |
| `MCP_API_KEY` 已设置但 Key 错误或缺失 | ❌ 拒绝 | `401`，`reason: invalid_or_missing_api_key` |
| `MCP_API_KEY` 为空，`MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`，请求来自 loopback 且不含转发头 | ✅ 放行 | — |
| `MCP_API_KEY` 为空，`MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`，请求来自 loopback 但含 `Forwarded` / `X-Forwarded-*` / `X-Real-IP` 等转发头 | ❌ 拒绝 | `401`，`reason: insecure_local_override_requires_loopback` |
| `MCP_API_KEY` 为空，`MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`，请求非 loopback | ❌ 拒绝 | `401`，`reason: insecure_local_override_requires_loopback` |
| `MCP_API_KEY` 为空，未开启 insecure local | ❌ 拒绝 | `401`，`reason: api_key_not_configured` |

> Loopback 地址仅包含 `127.0.0.1`、`::1`、`localhost`；且必须为直连本机请求（无 `Forwarded` / `X-Forwarded-*` / `X-Real-IP` 等转发头）。

---

## 4. 前端密钥注入（运行时）

前端不在构建时写死密钥，而是通过运行时注入读取。这适合本地调试或你自己控制的私有部署环境：

```html
<script>
  window.__MEMORY_PALACE_RUNTIME__ = {
    maintenanceApiKey: "<YOUR_MCP_API_KEY>",
    maintenanceApiKeyMode: "header"  // 可选值: "header" | "bearer"
  };
</script>
```

> ⚠️ 不要把真实 `MCP_API_KEY` 直接写进公开页面或任何会暴露给最终用户的静态资源里，因为浏览器里可以直接读到这个全局对象。

工作原理：

1. 前端读取 `window.__MEMORY_PALACE_RUNTIME__`
2. axios 请求拦截器判断请求是否需要鉴权
3. 对 `/maintenance/*`、`/review/*`、`/browse/*`、`/setup/*`、`/api/layering/*`、`/api/forgetting/*` 以及 `/search/quality-metrics` 自动注入鉴权头
4. Observability 订阅 `/sse` 时也会复用这套鉴权：没有浏览器侧 Dashboard key 时走原生 `EventSource`；有 key 时切到可带 header/bearer 的 fetch-based SSE，不会把 key 拼到 URL 里；重连会重新读取当前浏览器鉴权并继续带上 `Last-Event-ID`；明确的 `4xx` 鉴权失败则停止重试

> 兼容性：也支持旧字段名 `window.__MCP_RUNTIME_CONFIG__`。
>
> 如果服务端 Dashboard 鉴权已经生效（尤其是标准 Docker proxy-held key 路径），前端不会只因为浏览器本地还没保存 key 就自己弹出首启向导。

### 首启配置向导的安全边界

Dashboard 首启配置向导不是“浏览器随便改服务器配置”的通用后门：

- `/setup/status` 允许两种访问方式：
  - **直连本机回环地址**（`127.0.0.1` / `::1` / `localhost`，且不带 forwarded headers，并且请求里的 host 本身也是 loopback）
  - **携带有效 `MCP_API_KEY`**
- `/setup/config` 的**写入能力只允许直连本机回环地址**；即使拿着有效 `MCP_API_KEY`，远端请求也不能直接改主机 `.env`
- 向导接口只允许写入一组白名单 env 键，不支持任意文件写入
- 只允许写本地 checkout 的 `.env`
- 第一次往本地 `.env` 保存时，`Dashboard API key` 必须非空；留空会被后端直接拒绝
- 如果当前进程运行在 Docker 内部，向导会明确返回 `setup_apply_unsupported`，停留在说明模式，不会伪装成已经持久化容器 env / 代理配置
- 向导不会把现有 secret 值回显到前端；前端只能看到”是否已配置”的摘要状态
- MCP tool 和 Dashboard API 的错误响应做了脱敏：内部 memory id、数据库路径、Python 异常堆栈等信息不会出现在返回给客户端的错误消息里。500 类错误统一返回 `"internal_error"`；400 类错误返回异常类型名或稳定业务错误码（如 `orphan_not_found`、`orphan_delete_blocked`）。原始异常只写入服务端日志
- 浏览器本地只会把 Dashboard 使用的 `MCP_API_KEY` 放在当前浏览器会话的 `sessionStorage`；embedding / reranker / LLM key 不会保存在浏览器里
- Observability 的 `/sse` 订阅也跟随这条浏览器侧 Dashboard 鉴权
- 切档时，已隐藏的旧字段会跟着本次保存一起清掉，减少把上一档残留的 router/API 字段继续带进本次提交的风险
- provider API base 字段会先做归一化和校验：`/embeddings`、`/rerank`、`/chat/completions`、`/responses` 这类常见尾缀会自动去掉；格式不对、带凭证、或指到 link-local 的地址会直接拒绝。`127.0.0.1` / `::1` / `localhost` 默认允许；其它私网地址需通过 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` 显式放行
- 运行时如果读到无效的 chat / embedding / reranker API base，也会按 fail-closed 处理：直接忽略这条配置并走降级/回退

**Docker 一键部署的默认做法不一样：**

- `apply_profile.*` 在 `docker` 平台下如果发现 `MCP_API_KEY` 为空，会自动生成一把本地 key
- 前端容器不会把这把 key 写进页面，而是由 Nginx 代理在服务端只转发到受保护的 Dashboard API 路径，以及 `/sse`、`/messages`
- 浏览器可以直接使用 Dashboard，但不会在页面源码里暴露真实 key
- 这条便利路径默认把前端端口本身视为可信入口。谁能直接访问 Docker Dashboard 端口，谁就能使用这些被代理的受保护接口，所以这一层的 `MCP_API_KEY` **并不等于** 终端用户鉴权。若要暴露给受信范围之外的使用者，请先在 `3000` 前面加上你自己的 VPN、反向代理鉴权或网络访问控制

---

## 5. Docker 安全

以下安全配置可在项目 Docker 文件中直接验证：

| 安全措施 | 实现方式 | 文件引用 |
|---|---|---|
| 非 root 运行（后端） | `groupadd --gid 10001 app && useradd --uid 10001` | `deploy/docker/Dockerfile.backend` |
| 非 root 运行（前端） | 使用 `nginxinc/nginx-unprivileged:1.27-alpine` 基础镜像 | `deploy/docker/Dockerfile.frontend` |
| 前端代理鉴权 | 由 Nginx 在服务端转发 `X-MCP-API-Key`，浏览器侧不保存真实 key；仅对受保护路径（`/api/maintenance/*`、`/api/review/*`、`/api/browse/*`、`/api/setup/*`、`/api/layering/*`、`/api/forgetting/*`、`/api/search/quality-metrics` 以及 `/sse` / `/messages`）注入该头 | `deploy/docker/nginx.conf.template` |
| 禁止提权 | `security_opt: no-new-privileges:true` | `docker-compose.yml` |
| 数据持久化 | Docker Volumes 默认按 compose project 隔离：`<compose-project>_data` → `/app/data`，`<compose-project>_snapshots` → `/app/snapshots` | `docker-compose.yml` |
| 健康检查（后端） | `python /usr/local/bin/backend-healthcheck.py`；脚本会请求 `http://127.0.0.1:8000/health` 并要求 `status == "ok"`；超时可通过 `MEMORY_PALACE_BACKEND_HEALTHCHECK_TIMEOUT_SEC` 调整 | `docker-compose.yml`、`deploy/docker/backend-healthcheck.py` |
| 健康检查（前端） | `wget -q -O - http://127.0.0.1:8080/` | `docker-compose.yml` |

---

<p align="center">
  <img src="images/security_checklist.png" width="900" alt="分享前安全自检清单" />
</p>

## 6. 分享或发布前自检清单

1. **一键自检（推荐）**：

   ```bash
   bash scripts/pre_publish_check.sh
   ```

   该脚本会检查：常见本地敏感产物 / 工具配置是否存在、是否被 git 跟踪、已跟踪文件中的密钥模式、个人绝对路径泄露、`.env.example` 的 API key 占位状态。它更像“分享前仓库卫生检查”；本地文件存在通常给 `WARN`，不是 `FAIL`。

2. **检查工作区状态** — 确认无意外暴露：

   ```bash
   git status
   ```

   应确保以下文件不在提交中（均已在 `.gitignore` 中配置）：
   - `.env`、`.env.*`（保留 `.env.example`）
   - `.venv`、`.mcp.json`、`.mcp.json.bak`、`.claude/`、`.codex/`、`.cursor/`、`.opencode/`、`.gemini/`、`.agent/`、`.tmp/`、`.playwright-cli/`
   - `.pytest_cache/`、`backend/.pytest_cache/`（本机测试缓存）
   - `*.db`（数据库文件）
   - `*.init.lock`、`*.migrate.lock`
   - `backend/backend.log`、`frontend/frontend.log`
   - `snapshots/`、`frontend/dist/`
   - 本地验证报告（默认输出到 `docs/skills/` 但不进入 Git）
   - 任意 `.DS_Store`

3. **关键字扫描** — 检查代码和文档中是否残留真实密钥：

   ```bash
   rg -n -l "sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY" .
   ```

4. **检查绝对路径** — 确保文档中不包含本机路径：

   ```bash
   grep -rn "<user-home>" --include="*.md" <repo-root>
   grep -rn "C:/absolute/path/to/" --include="*.md" <repo-root>
   ```

5. **运行验证** — 确认项目可复现构建：

   ```bash
   bash scripts/pre_publish_check.sh
   curl -fsS http://127.0.0.1:8000/health
   cd frontend && npm ci && npm run test && npm run build
   ```

---

## 7. 通常不应提交的本地文件

| 文件 / 目录 | 说明 |
|---|---|
| `.env`、`.env.*`（保留 `.env.example`） | 可能包含真实 API Key |
| `.venv`、`backend/.venv`、`frontend/.venv` | 本地虚拟环境 |
| `.mcp.json`、`.mcp.json.bak`、`.claude/`、`.codex/`、`.cursor/`、`.opencode/`、`.gemini/`、`.agent/`、`.tmp/`、`.playwright-cli/` | 本地工具 / MCP / 浏览器验证产物目录 |
| `*.db` | SQLite 数据库文件 |
| `*.init.lock`、`*.migrate.lock` | 数据库初始化 / 迁移锁文件 |
| `backend/backend.log`、`frontend/frontend.log` | 后端 / 前端运行日志 |
| `snapshots/` | 本地快照目录 |
| `__pycache__/`、`.pytest_cache/` | Python 缓存 |
| `frontend/node_modules`、`frontend/dist/` | NPM 依赖和前端构建产物 |
| `.DS_Store` | macOS 系统文件 |
| `backups/` | 本地备份目录 |

> 公开文档里建议统一使用占位符：
>
> - `<repo-root>`：仓库根目录
> - `<user-home>`：用户目录
> - `/absolute/path/to/...`：macOS / Linux 绝对路径示例
> - `C:/absolute/path/to/...`：Windows 绝对路径示例
