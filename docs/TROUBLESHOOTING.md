# 常见问题排查

按问题分类。前面是高频问题，后面是配置和深度问题。

---

## 1. 前端打不开或接口超时

**症状**：页面能打开但列表为空，或接口返回 502 / 错误。

如果页面右上角显示 `设置 API 密钥`（英文 `Set API key`），或者 `Memory / Review / Maintenance / Observability` 显示空态、`401`，通常不是前端坏了，而是**受保护接口还没鉴权**。Docker 一键部署时，按钮可能仍然显示（浏览器不知道代理层有 key），但受保护数据应该已经能正常打开。

排查步骤：

1. 确认后端已启动：
   ```bash
   curl -fsS http://127.0.0.1:8000/health
   ```

2. 检查前端代理目标。`frontend/vite.config.js` 默认指向 `http://127.0.0.1:8000`。如果后端在其他端口：
   ```bash
   MEMORY_PALACE_API_PROXY_TARGET=http://127.0.0.1:9000 npm run dev
   ```

3. Docker 场景检查端口：
   - 后端默认 `18000`（映射容器内 `8000`）
   - 前端默认 `3000`（映射容器内 `8080`）
   - 可用 `MEMORY_PALACE_BACKEND_PORT` / `MEMORY_PALACE_FRONTEND_PORT` 覆盖

4. 查看后端日志：
   ```bash
   # 本地启动看终端输出
   # Docker 部署
   docker compose -f docker-compose.yml logs backend --tail=50
   ```

### Edge 卡顿但 Chrome 流畅

前端会自动识别 Microsoft Edge 并切换到轻量视觉模式（保留全部功能，只减少动画和模糊效果）。如果只有 Edge 卡，先按浏览器渲染问题处理，不要先怀疑后端。

---

## 2. 切换中英文

页面右上角有语言按钮，点一下切换。浏览器会记住选择。

首启配置向导也带语言按钮，不需要先关闭弹窗。

---

## 3. 本地 stdio MCP 启动后立即断开

常见错误：
- `connection closed: initialize response`
- `Read-only file system: '/app'`
- `.env` 里 `DATABASE_URL` 指向 `/app/data/...` 或 `/data/...`

原因是把 Docker 容器内路径写到了本地 `.env`。`scripts/run_memory_palace_mcp_stdio.sh` 只服务本机，不会复用 Docker 容器里的 `/app/data`。

这条 shell wrapper 会在启动 Python 前导出 `PYTHONIOENCODING=utf-8` 和 `PYTHONUTF8=1`，非 UTF-8 locale 下也更不容易乱码。

解决：

1. 把 `.env` 里 `DATABASE_URL` 改成宿主机绝对路径：
   ```dotenv
   DATABASE_URL=sqlite+aiosqlite:////absolute/path/to/memory_palace/demo.db
   ```

2. 或重新生成 `.env`：
   ```bash
   bash scripts/apply_profile.sh macos b
   ```

3. 如果就是想复用 Docker 那边的数据，不要走本地 stdio，让客户端连 Docker 暴露的 `/sse`。

---

## 4. Memory 页面删除或切节点没反应

某些 WebView / IDE 宿主没有原生确认框时，Memory 页面会 fail-closed：动作直接被拦下，不会偷偷删除或跳走。

换标准浏览器复现一次，或确认宿主是否禁用了原生对话框。

---

## 5. 受保护接口返回 401

`/maintenance/*`、`/review/*`、`/browse/*` 都受 `MCP_API_KEY` 保护，默认 fail-closed。

解决方式（任选一种）：

```bash
# curl 加自定义 header
curl -fsS http://127.0.0.1:8000/maintenance/orphans \
  -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>"

# 或 Bearer
curl -fsS http://127.0.0.1:8000/maintenance/orphans \
  -H "Authorization: Bearer <YOUR_MCP_API_KEY>"
```

前端：点右上角的 `设置 API 密钥` / `更新 API 密钥`，或在浏览器里注入 `window.__MEMORY_PALACE_RUNTIME__`（详见 [SECURITY_AND_PRIVACY.md](SECURITY_AND_PRIVACY.md)）。

本地调试时可在 `.env` 设置：
```env
MCP_API_KEY_ALLOW_INSECURE_LOCAL=true
```
仅对 loopback 直连请求生效。

**如果改了 `.env` 但服务还在用旧 key**：检查当前 shell 是否 export 过 `MCP_API_KEY`。进程环境变量优先级高于 `.env`：

```bash
env | rg '^MCP_API_KEY=|^MCP_API_KEY_ALLOW_INSECURE_LOCAL='
unset MCP_API_KEY MCP_API_KEY_ALLOW_INSECURE_LOCAL
# 然后重启 backend / run_sse.py
```

返回的 `reason` 字段含义：

| `reason` | 含义 | 处理 |
|---|---|---|
| `invalid_or_missing_api_key` | Key 错或未提供 | 检查 key |
| `api_key_not_configured` | `.env` 里 `MCP_API_KEY` 为空 | 设置 key 或开启 insecure local |
| `insecure_local_override_requires_loopback` | 开了 insecure local 但请求非 loopback | 确保从 `127.0.0.1` 访问 |

---

## 6. SSE 启动失败或端口占用

`python run_sse.py` 报 `address already in use`，或访问 `http://127.0.0.1:3000/sse` 失败。

1. 确认你走的是哪条路径：
   - 本地 standalone：用下面的 `/health` 检查
   - Docker：检查 `http://127.0.0.1:3000/sse`（Docker 默认不再有独立 sse 容器）

2. 检查 SSE 进程：
   ```bash
   curl -fsS http://127.0.0.1:8010/health
   ```
   返回 `{"status":"ok","service":"memory-palace-sse"}` 即正常。

3. 换端口启动：
   ```bash
   HOST=127.0.0.1 PORT=8010 python run_sse.py
   ```
   `run_sse.py` 优先尝试 `8000`，被占用时自动回退 `8010`。日志会打印最终 `/sse` 地址，按提示更新客户端配置。

4. 查找并释放占用端口：
   ```bash
   # macOS / Linux
   lsof -i :8000
   kill -9 <PID>

   # Windows PowerShell
   netstat -ano | findstr :8000
   taskkill /PID <PID> /F
   ```

### `/messages` 返回 404 或 410

`session_id` 已失效。`404` 表示服务端找不到 session，`410` 表示 SSE writer 已关闭。

只要 SSE 流断开，就别复用旧的 `session_id`。重新连一次 `/sse`：

```bash
curl -i \
  -H 'Accept: text/event-stream' \
  -H 'X-MCP-API-Key: <YOUR_MCP_API_KEY>' \
  http://127.0.0.1:8010/sse
```

从新返回的 `event: endpoint` 里取新的 `session_id`，再发请求到新的 `/messages/?session_id=...`。

---

## 7. 启动报 `No module named '...'`

最常见的是 `sqlalchemy` 或 `diff_match_patch`。

`sqlalchemy` 是后端硬依赖。错误通常因为你没用 `backend/.venv`，或客户端配的是系统 `python` 而不是项目的 `.venv` Python。

`diff_match_patch` 现在已经做了 fallback：缺失时 `/review/diff` 会回退到 `difflib.HtmlDiff`，不会让整个后端启动失败。

解决：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate           # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

如果是配置客户端 MCP，把 `command` 直接写成项目的 `.venv` Python：
- macOS / Linux：`./.venv/bin/python mcp_server.py`
- Windows：`.\.venv\Scripts\python.exe mcp_server.py`

快速自检：

```bash
cd backend
./.venv/bin/python -c "import sqlalchemy; print(sqlalchemy.__version__)"
```

---

## 8. Docker 一键脚本失败

1. 确认 Docker 可用：
   ```bash
   docker compose version
   ```

2. 查看脚本帮助：
   ```bash
   bash scripts/docker_one_click.sh --help
   ```

3. 端口冲突时指定端口：
   ```bash
   bash scripts/docker_one_click.sh --profile b --frontend-port 3100 --backend-port 18100
   ```
   即使你指定的端口也被占用，脚本会继续找空闲端口。以脚本最后打印的地址为准。

4. 错误提到 `backend /app/data`、`WAL`、`NFS/CIFS/SMB`：这是启动前安全保护。仓库默认只支持 Docker named volume + WAL 组合；如果你绕过一键脚本，手动 `docker compose up`，也要按同样规则先检查。处理方式：

   ```bash
   # 方案 A：回到默认 named volume（推荐）
   unset MEMORY_PALACE_DATA_VOLUME

   # 方案 B：必须用网络文件系统时，关闭 WAL
   export MEMORY_PALACE_DOCKER_WAL_ENABLED=false
   export MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete
   ```

5. 前端容器启动后立刻退出，日志显示 `MCP_API_KEY contains unsupported control characters`：你的 key 里混进了不该出现的字符（换行、回车、tab、反引号）。把 `MCP_API_KEY` 改成**单行**纯文本再重启。

Windows 用户使用 PowerShell 版：`scripts/docker_one_click.ps1`。

---

## 9. 搜索质量下降

`search_memory` 返回的 `degrade_reasons` 字段告诉你检索链路具体降级原因。常见值：

| `degrade_reasons` | 含义 |
|---|---|
| `embedding_fallback_hash` | Embedding API 不可达，回退到本地 hash |
| `embedding_config_missing` | Embedding 配置缺失 |
| `embedding_request_failed` | Embedding API 请求失败 |
| `embedding_dim_mismatch_requires_reindex` | 向量维度和当前配置不一致，需要重建索引 |
| `vector_dim_mixed_requires_reindex` | 查询范围内混入多种向量维度 |
| `reranker_request_failed` | Reranker API 请求失败 |
| `reranker_config_missing` | Reranker 配置缺失 |
| `fts_query_invalid` | 当前查询不适合 FTS，已走安全回退 |
| `path_revalidation_lookup_failed` | path 复核失败，相关结果被丢弃 |
| `intent_llm_model_unavailable` | Intent LLM 不可用 |
| `compact_gist_llm_empty` | Compact Gist LLM 返回空 |
| `index_enqueue_dropped` | 索引任务入队被丢弃 |

请求失败的细分后缀：`:timeout`、`:http_status:503`、`:connection_failure`、`:rate_limited`、`:upstream_unavailable`、`:retry_exhausted`。

检查 Embedding / Reranker API 可达性：

```bash
curl -fsS -X POST <RETRIEVAL_EMBEDDING_API_BASE>/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <RETRIEVAL_EMBEDDING_API_KEY>" \
  -d '{"model":"<RETRIEVAL_EMBEDDING_MODEL>","input":"ping","dimensions":<RETRIEVAL_EMBEDDING_DIM>}'

curl -fsS -X POST <RETRIEVAL_RERANKER_API_BASE>/rerank \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <RETRIEVAL_RERANKER_API_KEY>" \
  -d '{"model":"<RETRIEVAL_RERANKER_MODEL>","query":"ping","documents":["pong"]}'
```

注意：
- `RETRIEVAL_*_API_BASE` 可能已包含 `/v1`，不要重复拼接
- 本地服务不要求 key 时去掉 `Authorization` 头
- 非 loopback 的 private IP 字面量需要先加入 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS`

重建索引：

```python
rebuild_index(wait=true)
index_status()
```

查看观测摘要：

```bash
curl -fsS http://127.0.0.1:8000/maintenance/observability/summary \
  -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>"
```

---

## 10. 前端构建失败

```bash
cd frontend
rm -rf node_modules                  # Windows: rmdir /s /q node_modules
npm ci
npm run build
```

常见原因：
- Node.js 版本不兼容：建议 20.19+ 或 22.12+
- 网络问题：配置 NPM Mirror

---

## 11. 数据库迁移异常

启动报 `Timed out waiting for migration lock`。

1. 检查是否有重复进程同时启动

2. 调整锁超时（`.env` 默认 10 秒）：
   ```env
   DB_MIGRATION_LOCK_TIMEOUT_SEC=30
   ```

3. 手动指定锁文件路径：
   ```env
   DB_MIGRATION_LOCK_FILE=/tmp/memory_palace.migrate.lock
   ```

   默认锁文件 `<数据库文件>.migrate.lock` 保存在数据库文件同目录。另有 `<数据库文件>.init.lock` 用于串行化 `init_db()`，避免 `backend` 和 `sse` 并发启动抢库。`:memory:` 数据库不会生成这些锁。

4. 删除残留锁文件后重启：
   ```bash
   rm -f /path/to/demo.db.migrate.lock
   rm -f /path/to/demo.db.init.lock
   ```

---

## 12. 索引重建后仍无改善

1. 确认索引就绪：
   ```python
   index_status()  # 应包含 index_available=true
   ```

2. 检查 Embedding 后端配置（详见 `.env.example`）：

   | 档位 | `RETRIEVAL_EMBEDDING_BACKEND` |
   |---|---|
   | Profile A | `none` |
   | Profile B | `hash` |
   | Profile C/D | `api` 或 `router` |

3. 确认有记忆内容：
   ```bash
   curl -fsS \
     -H "X-MCP-API-Key: ${MCP_API_KEY}" \
     "http://127.0.0.1:8000/browse/node?domain=core&path="
   ```

4. 尝试 Sleep Consolidation 深度重建：
   ```python
   rebuild_index(sleep_consolidation=true, wait=true)
   ```

5. 检查 `degrade_reasons`（见第 9 节）

---

## 13. CORS 报错

前端请求后端 API 时浏览器报 CORS 错误。

默认行为：`CORS_ALLOW_ORIGINS` 留空时只放行本地来源：

```
http://localhost:5173
http://127.0.0.1:5173
http://localhost:3000
http://127.0.0.1:3000
```

常见原因：
- 前端 dev server 代理未配置（检查 `frontend/vite.config.js`）
- Docker 部署时 Nginx 没有正确转发（检查 `deploy/docker/nginx.conf.template`）
- 你的浏览器来源不在允许列表里

生产环境写明确的来源列表：

```env
CORS_ALLOW_ORIGINS=https://app.example.com,https://admin.example.com
```

不建议直接写 `*`，尤其是还需要 credentials / cookie 的时候。

---

## 14. Docker 更新后页面仍是旧版

Docker 前端 `nginx.conf.template` 对 `/index.html` 返回 `Cache-Control: no-store, no-cache, must-revalidate`。如果仍看到旧页面：

1. 确认前端容器已重建并启动完成
2. 浏览器手动刷新
3. 如果只在某个外部入口复现，检查那一层是否改写了缓存头

---

## 15. 获取帮助

如果上述步骤无法解决：

1. 看后端完整日志：本地看终端，Docker 看 `docker compose -f docker-compose.yml logs backend --tail=200`
2. 检查 `GET /health` 返回的 `status` 和 `index`
3. 调用 `GET /maintenance/observability/summary`（带 `X-MCP-API-Key`）看运行概况
4. 提交 Issue 时附上：错误信息、操作系统、Python 版本、Node.js 版本、使用的 Profile
