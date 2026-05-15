# Memory Palace 常见问题排查

本文档帮助你快速定位和解决 Memory Palace 使用过程中的常见问题。

---

## 1. 前端 502 或接口超时

**现象**：页面能打开，但列表为空或接口报错。

> 📌 当前版本还有一种很常见的“看起来像坏了，其实是正常门控”的情况：
>
> - 页面右上角出现 `设置 API 密钥`（英文模式下会显示 `Set API key`）
> - `Memory / Review / Maintenance / Observability` 里出现空态、等待提示或 `401`
>
> 这通常不是前端挂了，而是**你还没给受保护接口授权**。
>
> 如果你用的是 **Docker 一键部署**，按推荐路径启动时，受保护请求通常已经能直接使用；但页面右上角**仍可能继续显示** `设置 API 密钥`（英文模式下会显示 `Set API key`），因为浏览器并不知道代理层自动转发的那把 key。现在如果 proxy-held auth 已经生效，首启配置向导也不该再自己误弹出来。优先先看受保护数据是不是能正常打开；只有这些请求也失败时，才需要继续检查 `apply_profile.*` / `docker_one_click.*` 生成的 Docker env 文件、代理配置或手工改动。

**排查步骤**：

1. 确认**后端已启动**：

   ```bash
   curl -fsS http://127.0.0.1:8000/health
   ```

   > 后端健康检查端点 `GET /health` 对本机 loopback 或带有效 `MCP_API_KEY` 的请求会返回 `status`、`index`、`runtime` 等详细字段；未鉴权的远端请求只返回浅健康信息（参见 `backend/main.py` 中 `health()` 函数）。如果这类详细健康检查本身已经降级，当前也会直接返回 `503`，这属于“系统未就绪”的正常信号，不是额外多出一层代理报错。

2. 确认**前端代理目标正确**：

   检查 `frontend/vite.config.js` 中 `apiProxyTarget` 的值：

   ```javascript
   // 默认目标: http://127.0.0.1:8000
   const apiProxyTarget =
     process.env.MEMORY_PALACE_API_PROXY_TARGET ||
     process.env.NOCTURNE_API_PROXY_TARGET ||
     'http://127.0.0.1:8000'
   ```

   如果后端运行在其他端口，请设置环境变量：

   ```bash
   MEMORY_PALACE_API_PROXY_TARGET=http://127.0.0.1:9000 npm run dev
   ```

3. **Docker 场景**下确认端口映射：

   - 默认后端端口：`18000`（映射到容器内 `8000`）
   - 默认前端端口：`3000`（映射到容器内 `8080`）
   - 可通过 `MEMORY_PALACE_BACKEND_PORT`、`MEMORY_PALACE_FRONTEND_PORT` 环境变量覆盖（参见 `docker-compose.yml`）

4. 检查后端日志：

   ```bash
   # 本地直接启动（uvicorn/python run_sse.py）时，优先看当前终端输出
   # Docker 部署时查看容器日志
   docker compose -f docker-compose.yml logs backend --tail=50
   ```

---

### 只有 Edge 打开 Dashboard 很卡，但 Chrome 很流畅

**现象**：

- 同一台机器、同一个本地 Dashboard，Microsoft Edge 明显更卡
- Chrome 打开同一个地址会顺很多
- 健康检查和普通 API 请求本身看起来没有明显坏掉

**这通常不代表后端突然变慢了**。更常见的原因还是 Dashboard 页面这一层的浏览器渲染路径差异。

**当前代码的实际行为**：

- 前端现在会自动识别 Microsoft Edge
- Edge 会默认切到更轻量的视觉模式
- 这套轻量模式保留同样的页面、按钮、鉴权/配置向导流程和数据请求
- 主要变化只是把动画背景、blur 和一部分卡片动效收掉，优先减少本地卡顿

**处理方式**：

1. 先在更新后的前端页面上做一次强制刷新
2. 用 Chrome 或其他浏览器对比同一个本地地址
3. 如果只有 Edge 还卡、Chrome 正常，先把它当成浏览器侧渲染问题排，而不是先按后端/API 故障处理

---

## 1.1 页面默认是英文，怎么切到中文？

**现象**：

- 页面能正常打开
- 但界面默认显示英文

**这不是前端没加载完整**。当前版本的前端默认语言就是英文。

**处理方式**：

1. 看页面右上角的语言按钮
2. 直接点一下，就可以在英文和中文之间切换
3. 浏览器会记住你的选择；下次再打开时会优先使用你上次切到的语言

如果你 first-run 一上来先被首启配置向导挡住，也不用先把它关掉：

1. 向导右上角也有语言按钮
2. 可以直接在弹窗内部切到中文
3. 切完之后页面主体和后续弹窗也会一起跟着切换

**补充说明**：

- 语言切换只影响前端显示，不会改变 MCP、API、鉴权或数据库行为
- 如果你看到的是英文界面，但功能、按钮、数据都正常，这属于预期行为，不是故障

---

## 1.2 本地 stdio MCP 一启动就断开，或错误里出现 `/app/data` / `/data`

**常见现象**：

- 客户端里看到 `connection closed: initialize response`
- 或启动日志里出现 `Read-only file system: '/app'`
- 或直接报本地 `.env` 里的 `DATABASE_URL` 指向 `/app/data/...` 或 `/data/...`

**这通常不是 MCP 协议坏了**。更常见的原因是：你把 Docker / GHCR 路径里的 `sqlite+aiosqlite:////app/data/...`，或其他 `/data/...` 这类容器内 sqlite 路径，写进了本地 `.env`。

repo-local `scripts/run_memory_palace_mcp_stdio.sh` 只服务于：

- 当前 checkout
- 当前 checkout 下的本地 `.env`
- 当前 checkout 下的本地 `backend/.venv`

它不会复用 Docker 容器里的 `/app/data`，也不会把 `/data/...` 这类容器内 sqlite 路径当成本机路径。现在如果它发现本地 `.env` 仍在用容器路径，会直接拒绝启动，而不是再假装握手成功。

补一条容易误会的小边界：现在 repo-local `bash` wrapper 和原生 Windows 的 `backend/mcp_wrapper.py` 都已经统一用同一套 `.env` 解析逻辑了；如果某个 Windows 风格宿主最后把 `backend/mcp_wrapper.py` 跑在 `Git Bash / MSYS / Cygwin` 里，wrapper 也会优先尝试 `.venv/Scripts/python.exe`。也就是说，像下面这种写法本身不是问题：

```dotenv
DATABASE_URL="sqlite+aiosqlite:////absolute/path/to/demo.db" # local db
```

真正的问题仍然只是：它是不是容器内路径。

对 shell wrapper 这条路径（`macOS / Linux / Git Bash / WSL`）来说，`run_memory_palace_mcp_stdio.sh` 现在还会在启动 Python 前先导出 `PYTHONIOENCODING=utf-8` 和 `PYTHONUTF8=1`。说人话就是：如果当前 shell 默认编码不是 UTF-8，本地 stdio 也更不容易因为编码问题翻车。

**处理方式**：

1. 打开仓库根目录 `.env`
2. 把 `DATABASE_URL` 改成你宿主机上的绝对路径，例如：

   ```dotenv
   DATABASE_URL=sqlite+aiosqlite:////absolute/path/to/memory_palace/demo.db
   ```

3. 或者重新生成本地 `.env`：

   ```bash
   bash scripts/apply_profile.sh macos b
   ```

4. 如果你本来就想复用 Docker 那边的服务和数据，不要再走本地 `stdio`，直接让客户端连接 Docker 暴露的 `/sse`

---

## 1.3 Memory 页面点删除或切节点没反应

**现象**：

- 某些受限 WebView / IDE 宿主里没有原生确认框
- 在 Memory 页面点“删除路径”或切到别的节点，看起来像点了没反应

**现在的实际行为**：

- 当前 Memory 页已经改成 fail-closed
- 说人话就是：确认框不可用时，它不会偷偷删除，也不会偷偷跳走
- 动作会直接被拦下，页面里会给出错误提示

**处理方式**：

1. 先换标准浏览器复现一次
2. 再确认当前宿主是否禁用了原生对话框
3. 如果标准浏览器正常、只有特定宿主不正常，就优先按宿主能力边界排，不要先怀疑 Memory 写入逻辑本身坏了

---

## 2. `/maintenance/*`、`/review/*` 或 `/browse/*` 返回 401

**常见原因**：请求没带鉴权头。注意 `/browse/node` 的读操作也受保护，而且这些接口默认就是 fail-closed；只有显式开启 `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` 且请求来自 loopback 时才会放行。

**排查与处理**：

- **方式一**：curl 加鉴权头：

  ```bash
  curl -fsS http://127.0.0.1:8000/maintenance/orphans \
    -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>"
  ```

- **方式二**：使用 Bearer 格式：

  ```bash
  curl -fsS http://127.0.0.1:8000/maintenance/orphans \
    -H "Authorization: Bearer <YOUR_MCP_API_KEY>"
  ```

- **前端**：注入 `window.__MEMORY_PALACE_RUNTIME__`（详见 [SECURITY_AND_PRIVACY.md](SECURITY_AND_PRIVACY.md) 第 4 节）
- **前端页面**：也可以直接点右上角的 `设置 API 密钥` / `更新 API 密钥`（英文模式下分别显示 `Set API key` / `Update API key`）
  - 当前版本会先打开首启配置向导
  - 如果你只是想先让 Dashboard 通过鉴权，优先使用“只保存 Dashboard 密钥”
  - 浏览器已经保存 Dashboard key 时，Observability 会改走带 header/bearer 的 fetch-based SSE；如果你刚更新了浏览器里保存的 Dashboard key，下一次非终态重连会重新读取当前 key / mode，不需要为了这件事整页刷新；如果是明确的 `4xx` 鉴权失败，它会停止重试，优先按 key/session 问题排查。修正 key 后，重新聚焦这个标签页会重建带当前鉴权的 `/sse` 连接
  - `.env` 写入只建议在本地 checkout + 非 Docker 运行时使用
  - 如果当前还没有任何 Dashboard 鉴权，而你第一次本地保存就同时带上了远端/provider-chain 配置，后端会先只做 auth bootstrap；远端 embedding/reranker/LLM 字段要等下一次带鉴权的保存再真正落盘

- **本地调试** 可设置 insecure local override（仅 loopback 生效）：

  ```bash
  # .env 中添加
  MCP_API_KEY_ALLOW_INSECURE_LOCAL=true
  ```

- **如果你明明改了仓库 `.env`，服务却还在使用旧 key / 错 key**：
  - 先检查当前终端有没有额外导出过 `MCP_API_KEY` 或 `MCP_API_KEY_ALLOW_INSECURE_LOCAL`
  - 当前实现里，**进程环境变量优先级高于仓库 `.env`**
  - 我们在真实本地复测里就遇到过：`run_sse.py` 读取到了外层 shell 里的 `MCP_API_KEY`，结果即使仓库 `.env` 里写的是另一把 key，`/sse` 仍然按外层环境变量鉴权，表现成 `401 invalid_or_missing_api_key`

  ```bash
  env | rg '^MCP_API_KEY=|^MCP_API_KEY_ALLOW_INSECURE_LOCAL='
  unset MCP_API_KEY MCP_API_KEY_ALLOW_INSECURE_LOCAL
  ```

  > 清掉外层环境变量后，请重新启动 `backend` / `run_sse.py` 再复测。

**根据返回的 `reason` 字段判断具体原因（参见 `backend/api/maintenance.py`）：**

| `reason` | 含义 | 处理方式 |
|---|---|---|
| `invalid_or_missing_api_key` | Key 错误或未提供 | 检查 Key 是否正确 |
| `api_key_not_configured` | 本地手动启动时 `.env` 中 `MCP_API_KEY` 为空 | 设置 Key 或启用 insecure local |
| `insecure_local_override_requires_loopback` | 启用了 insecure local 但请求非 loopback | 确保从 `127.0.0.1` 或 `localhost` 访问 |

> 💡 如果你看到的是：
>
> - `Awaiting Input`
> - `Failed to load node`
> - `Connection Lost`
> - `maintenance_auth_failed | api_key_not_configured`
>
> 优先先配 key，再判断是不是别的问题。

## 2.1 Dashboard 刚写完，reflection 还提示 `session_summary_empty`

**先说结论**：

- 按当前代码，Dashboard 通过 `/browse` 的写入已经会喂给 reflection workflow
- 所以现在再看到这个报错，不应该先把原因归到“这次写入来自 Dashboard”

**排查顺序**：

1. 先确认这次 `/browse` 写入本身已经成功
2. 确认前后端不是旧页面、旧进程，或还停在修复前版本
3. 再去看是不是别的 session/source 选择问题，而不是默认把锅甩给 Dashboard 写路径

说人话就是：`session_summary_empty` 这条老结论现在已经过时了。先排当前运行版本和当前这次写入本身，不要再把 Dashboard 写路径当成默认根因。

---

## 3. SSE 启动失败或端口占用

**现象**：

- 本地手动启动 `python run_sse.py` 报 `address already in use`
- 或 Docker 下访问 `http://127.0.0.1:3000/sse` 失败

**处理**：

1. 先确认你当前走的是哪条路径：

   - 本地 standalone `run_sse.py`：继续按下面的 `/health` 检查
   - Docker / GHCR：优先检查 `http://127.0.0.1:3000/sse` 是否可达，因为 Docker 默认不再有独立 `sse` 容器

2. 如果你走的是 standalone `run_sse.py`，先确认 SSE 进程是不是已经起来：

   ```bash
   curl -fsS http://127.0.0.1:8010/health
   ```

   如果这里都不通，优先排查进程和端口；如果这里已经返回 `{"status":"ok","service":"memory-palace-sse"}`，再继续看 `/sse` 和 `/messages` 的鉴权或 session。

   再补一个小边界：当前前端代理路径仍以 `/sse` 为标准写法；如果某个客户端误用了 `/sse/`，前端现在也会把它转发到同一条后端 SSE 路径。所以文档和客户端配置里仍然优先写 `/sse`，但看到尾部斜杠也不必单独怀疑代理挂了。

3. 更换端口（`run_sse.py` 会优先尝试 `8000`，必要时可显式切到 `8010`）：

   ```bash
   HOST=127.0.0.1 PORT=8010 python run_sse.py
   ```

   如果刚才其实是因为 `8000` 被占用而自动回退，当前启动日志也会明确打印最终 `/sse` 地址，并提醒你更新客户端配置或显式设置 `PORT`。优先先按这条提示改客户端，不要先把它误判成 SSE 链路本身坏了。

4. 或查找并释放被占用端口：

   再补一个这轮修复过的小边界：`docker_one_click.sh` 在没有 `lsof` / `nc`、只能退回 Python socket probe 时，现在会按 `0.0.0.0` 做 wildcard bind 检查，而不是只试 `127.0.0.1`。说人话就是：如果端口其实已经被本机另一块 host IP 占住了，它现在也会被当成真实冲突，不要只盯着 loopback 监听看。

   ```bash
   # macOS / Linux
   lsof -i :8000
   kill -9 <PID>
   ```

   ```powershell
   # Windows PowerShell
   netstat -ano | findstr :8000
   taskkill /PID <PID> /F
   ```

---

## 3.1 `/messages` 返回 404 或 410

**现象**：

- 你先连上了 `/sse`
- 也拿到了 `event: endpoint`
- 但后面往 `/messages/?session_id=...` 发请求时返回 `404` 或 `410`

**这通常不是鉴权错了**，而是你手里的 `session_id` 已经失效了。

当前真实行为是：

- `404`：服务端已经找不到这条 session
- `410`：session 还在映射里，但底层 SSE writer 已经关闭

说人话就是：

- 只要 SSE 流断开了，就别继续复用旧的 `session_id`
- 你需要重新连一次 `/sse`，拿一条新的 `event: endpoint`

**处理方式**：

1. 重新建立 SSE 连接：

   ```bash
   curl -i \
     -H 'Accept: text/event-stream' \
     -H 'X-MCP-API-Key: <YOUR_MCP_API_KEY>' \
     http://127.0.0.1:8010/sse
   ```

2. 从新返回的 `event: endpoint` 里取新的 `session_id`

3. 再向新的 `/messages/?session_id=...` 发请求

**补充说明**：

- 这是当前版本故意做成 fail-closed 的行为
- 目的就是避免“旧会话其实已经死了，但服务端还回你一个假 `202 Accepted`”

---

## 3.2 后端启动时报 `No module named 'diff_match_patch'`

**现象**：

- 本地启动 `uvicorn main:app` 时，日志里出现：

  ```text
  ModuleNotFoundError: No module named 'diff_match_patch'
  ```

**现在的实际行为**：

- 当前代码会优先使用 `diff_match_patch`
- 如果这个包在你的 Python 环境里缺失，`/review/diff` 会自动退回到 `difflib.HtmlDiff` 表格 diff
- 这不应该再把整个后端启动直接打死

**如果你还是看到了这个错误**，优先排查这两件事：

1. 你是不是在用项目自己的虚拟环境启动：

   ```bash
   cd backend
   source .venv/bin/activate
   python -m uvicorn main:app --reload --port 8000
   ```

2. 依赖是不是装在了别的 Python 解释器里：

   ```bash
   cd backend
   .venv/bin/python -m pip install -r requirements.txt
   ```

**补充说明**：

- `diff_match_patch` 仍然在 `backend/requirements.txt` 里，正常安装时最好带上
- 现在加的 fallback 只是为了把故障从“后端起不来”降成“review diff 降级”，不是建议长期缺着这个依赖

3. Docker 一键部署时，优先检查前端入口：

   ```bash
   curl -i -H 'Accept: text/event-stream' http://127.0.0.1:3000/sse
   ```

   正常情况下你应该能看到：

   ```text
   event: endpoint
   data: /messages/?session_id=...
   ```

4. 如果你是远程客户端接入，请再确认这三件事：

   - `run_sse.py` 启动时不要继续绑在 `HOST=127.0.0.1`
   - 请求里带了正确的 `X-MCP-API-Key` 或 `Authorization: Bearer ...`
   - 反向代理 / 防火墙没有把请求拦掉

   可以先用一条最小请求排查：

   ```bash
   curl -i \
     -H 'Accept: text/event-stream' \
     -H 'X-MCP-API-Key: <YOUR_MCP_API_KEY>' \
     http://<YOUR_HOST>:<YOUR_PORT>/sse
   ```

---

## 3.3 运行 `python mcp_server.py` 时提示 `No module named 'sqlalchemy'`

**现象**：

- 本地直接运行 `python mcp_server.py`，启动前就报：

  ```text
  ModuleNotFoundError: No module named 'sqlalchemy'
  ```

**这通常不是 Memory Palace 功能逻辑坏了**，而是当前启动这个 MCP 进程的 Python 环境里没有装后端依赖。

`sqlalchemy` 是 `backend/requirements.txt` 里的硬依赖；`mcp_server.py` 启动时会先导入数据库层，所以如果解释器不对，进程会在真正启动前直接退出。

**最常见的两种情况**：

1. 你开了一个新终端，但没有重新激活 `backend/.venv`
2. 你在 Claude Code / Codex / OpenCode 这类客户端里配置本地 MCP 时，写的是系统 `python`，不是项目自己的 `.venv` Python

**处理方式**：

1. 先确认你在项目自己的虚拟环境里安装过依赖：

   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. 如果你只是想在当前终端里直接启动 MCP：

   ```bash
   cd backend
   ./.venv/bin/python mcp_server.py
   ```

   Windows PowerShell：

   ```powershell
   cd backend
   .\.venv\Scripts\python.exe mcp_server.py
   ```

3. 如果你是在客户端里配置本地 stdio MCP，优先把 `command` 直接写成项目自己的 `.venv` Python，不要只写 `python`。

**快速自检**：

```bash
cd backend
./.venv/bin/python -c "import sqlalchemy; print(sqlalchemy.__version__)"
```

如果这条命令能正常输出版本号，再启动 `mcp_server.py` 就不会卡在这个问题上。

---

## 4. Docker 一键脚本失败

**排查步骤**：

1. 确认 Docker 可用：

   ```bash
   docker compose version
   ```

2. 确认 profile 合法（`a`、`b`、`c`、`d`）：

   ```bash
   # 查看帮助
   bash scripts/docker_one_click.sh --help
   ```

   这里再补一个容易误判的小边界：对 macOS / Linux 的 shell 路径来说，
   `docker_one_click.sh` 现在已经会先对短暂的 `docker compose up`
   失败做几次小范围退避重试。所以如果脚本最后还是退出，优先先看**最后一条
   compose 错误**；真正需要修的是那条最终错误，而不只是第一次瞬时抖动。

3. 端口冲突时指定端口：

   ```bash
   bash scripts/docker_one_click.sh --profile b --frontend-port 3100 --backend-port 18100
   ```

   如果脚本发现你指定的端口也被占用，会继续自动换到附近空闲端口。
   这时请以脚本最后打印出来的 `Frontend` / `Backend API` 地址为准，不要继续死盯你最初输入的端口。

4. 如果脚本在真正启动前就直接失败，并且错误里提到：
   - `backend /app/data`
   - `WAL`
   - `NFS` / `CIFS` / `SMB`

   这通常不是脚本误报，而是新的**启动前保护**在生效：

   - 仓库默认只把 **Docker named volume + WAL** 当成受支持路径
   - 如果你把 backend 的 `/app/data` 改成网络文件系统 bind mount，再继续开 `WAL`，SQLite 存在损坏风险
   - `docker_one_click.sh/.ps1` 现在会在 `docker compose up` 前直接拒绝这类组合

   处理方式只有两类：

   ```bash
   # 方案 A：回到仓库默认 named volume 路径（推荐）
   unset MEMORY_PALACE_DATA_VOLUME
   ```

   或：

   ```bash
   # 方案 B：如果你必须用 NFS/CIFS/SMB bind mount，就显式关闭 WAL
   export MEMORY_PALACE_DOCKER_WAL_ENABLED=false
   export MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete
   ```

   如果你绕过一键脚本，自己手动执行 `docker compose up`，这条保护不会自动替你执行；你需要自己遵守同一条规则。

5. 镜像构建失败时，检查 Dockerfile 是否完整：
   - `deploy/docker/Dockerfile.backend` — 基于 `python:3.11-slim`
   - `deploy/docker/Dockerfile.frontend` — 基于 `node:22-alpine`（构建）+ `nginxinc/nginx-unprivileged:1.27-alpine`（运行）

6. 如果 frontend 容器启动很快就退出，日志里出现：
   - `MCP_API_KEY contains unsupported control characters`

   这通常说明你写进 Docker env 文件的 `MCP_API_KEY` 里混进了不该出现的字符。最常见的还是 ASCII 控制字符，比如换行、回车、制表符；当前前端入口脚本也会直接拒绝反引号这类明显不适合出现在 key 里的字符。

   常见场景是：
   - 从密码管理器或聊天窗口复制 key 时，把结尾换行一起带进去了
   - 从表格、IM 或某些密码管理器里复制时，把中间的制表符一起带进去了
   - 从命令片段或聊天记录里复制时，把反引号也一起带进去了
   - 手工编辑 `.env.docker` 时把 key 写成了多行

   处理方式很简单：把 `MCP_API_KEY` 改成**单行**纯文本，再重新启动。这里不需要猜测代理、SSE 或浏览器缓存问题，先把 key 本身清干净。

> 💡 Windows 用户可使用 `scripts/docker_one_click.ps1`（PowerShell 版本）。

---

## 5. 搜索质量突然下降

**排查步骤**：

1. **查看 `degrade_reasons`**：`search_memory` MCP 工具返回的 `degrade_reasons` 字段会告诉你检索链路的具体降级原因。常见值包括：

   | `degrade_reasons` 值 | 含义 | 来源文件 |
   |---|---|---|
   | `embedding_fallback_hash` | Embedding API 不可达，回退到本地 hash | `backend/db/sqlite_client.py` |
   | `embedding_config_missing` | Embedding 配置缺失 | `backend/db/sqlite_client.py` |
   | `embedding_request_failed` | Embedding API 请求失败 | `backend/db/sqlite_client.py` |
   | `embedding_dim_mismatch_requires_reindex` | 当前查询作用域内的向量维度和当前配置不一致，需要重建索引 | `backend/db/sqlite_client.py` |
   | `vector_dim_mixed_requires_reindex` / `vector_dim_mismatch_requires_reindex` | 当前查询作用域内混入了多种向量维度，或该作用域整体维度和当前配置不一致，需要重建索引 | `backend/db/sqlite_client.py` |
   | `reranker_request_failed` | Reranker API 请求失败 | `backend/db/sqlite_client.py` |
   | `reranker_config_missing` | Reranker 配置缺失 | `backend/db/sqlite_client.py` |
   | `fts_query_invalid` | 当前查询不适合直接走 FTS；系统已按这次请求回退到安全路径 | `backend/db/sqlite_client.py` |
   | `path_revalidation_lookup_failed` | 最终 path 状态复核失败；相关结果已直接丢弃 | `backend/db/sqlite_client.py` |
   | `intent_llm_model_unavailable` | 已开启 intent LLM，但当前配置的模型/后端不可用 | `backend/db/sqlite_client.py` |
   | `compact_gist_llm_empty` | Compact Gist LLM 返回空结果 | `backend/mcp_server.py` |
   | `index_enqueue_dropped` | 索引任务入队被丢弃 | `backend/mcp_server.py` |

   > `write_guard_exception` 属于写入/学习链路（如 `create_memory`、`update_memory`、显式学习触发），语义为写入已 fail-closed 拒绝，并非检索质量降级。
   >
   > `fts_query_invalid` 现在更像“这次 query 走了安全回退”而不是“整个 FTS 挂了”。常见触发是保留词（如 `AND/OR/NOT/NEAR`）或 wildcard 很重的输入；先看结果有没有按 fallback 返回，再决定是否要重写查询。
   >
   > `path_revalidation_lookup_failed` 的语义也要按 fail-close 理解：相关结果已经被直接丢弃，不该把空结果误读成“库里一定没有这条记忆”。
   >
   > 现在这两类请求失败原因还会继续细分。例如你可能看到 `embedding_request_failed:timeout`、`embedding_request_failed:http_status:503`、`embedding_request_failed:connection_failure`、`embedding_request_failed:rate_limited`、`embedding_request_failed:upstream_unavailable`、`embedding_request_failed:retry_exhausted`，或者 `reranker_request_failed:http_status:503`。看法很简单：先看前半段知道是哪条链路挂了，再看后半段确认是超时、限流、上游不可用、连接失败，还是别的请求错误。现在 `compact_gist` / `write_guard` / `intent_llm` 这些请求失败链路也会沿用同一套细分口径。

2. **检查 Embedding / Reranker API 可达性**：

   ```bash
   # 配置语义：RETRIEVAL_EMBEDDING_BACKEND 只控制 embedding。
   # reranker 不存在 RETRIEVAL_RERANKER_BACKEND；如需本地强制走自有 reranker API，
   # 请显式设置 RETRIEVAL_RERANKER_ENABLED=true 与 RETRIEVAL_RERANKER_API_BASE/API_KEY/MODEL。
   # 注意：RETRIEVAL_*_API_BASE 可能已包含 /v1，避免再手动拼接 /v1
   # 如果应用里配置的是非 loopback 的 private IP 字面量 provider base，还要先补
   # MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS=<该 IP 或 CIDR>
   # 用实际调用端点做健康检查更准确：
   curl -fsS -X POST <RETRIEVAL_EMBEDDING_API_BASE>/embeddings \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer <RETRIEVAL_EMBEDDING_API_KEY>" \
     -d '{"model":"<RETRIEVAL_EMBEDDING_MODEL>","input":"ping","dimensions":<RETRIEVAL_EMBEDDING_DIM>}'
   curl -fsS -X POST <RETRIEVAL_RERANKER_API_BASE>/rerank \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer <RETRIEVAL_RERANKER_API_KEY>" \
     -d '{"model":"<RETRIEVAL_RERANKER_MODEL>","query":"ping","documents":["pong"]}'
   ```

   > 如果你的本地服务本身不要求 API key，就把 `Authorization` 这一行去掉。若 embedding provider 明确拒绝 `dimensions`，运行时会自动重试一次不带这个字段的旧请求，但最终返回的向量维度仍然要和 `RETRIEVAL_EMBEDDING_DIM` 保持一致。
   >
   > 对 one-click 的 Docker `profile c/d + --allow-runtime-env-injection` 路径来说，宿主机侧的 loopback router / chat 地址（`127.0.0.1` / `localhost` / `::1`）现在会在生成的 Docker env 里自动改成 `host.docker.internal`。如果你绕过这条 one-click 路径，自己准备最终 Docker env，还是要手动写成容器可达地址。其它 non-loopback private IP 字面量地址仍然保持显式写法，需要时也还是要补 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS`。

   > **排障顺序建议**：
   > - 先确认你当前使用的是 `router` 方案，还是分别直配 `RETRIEVAL_EMBEDDING_*`、`RETRIEVAL_RERANKER_*`、`WRITE_GUARD_LLM_* / COMPACT_GIST_LLM_*`。
   > - 如果采用直配方案，优先检查实际 `*_API_BASE` / `*_API_KEY` / `*_MODEL`。
   > - 如果采用 `router` 方案，再检查 `ROUTER_*` 配置和 router 服务本身。

3. **重建索引**（通过 MCP 工具调用）：

   ```python
   # 重建索引
   rebuild_index(wait=true)
   # 检查索引状态
   index_status()
   ```

   > 如果看到的是向量维度相关的降级原因，先重建**当前查询作用域**对应的数据就够了。现在这类检查已经会跟着 `domain` / `path_prefix` / `scope_hint` 等查询范围走，不应该再被别的无关 domain 误触发。要补一句兼容边界：如果你传的是 `scope_hint=fast` 或 `scope_hint=deep`，当前版本会先把它当成快/深档位快捷值处理，不是 path scope。

4. **查看观测摘要**（通过 HTTP API）：

   ```bash
   curl -fsS http://127.0.0.1:8000/maintenance/observability/summary \
     -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>"
   ```

5. **检查配置参数**：确认 `RETRIEVAL_RERANKER_WEIGHT` 在合理范围（`.env.example` 注释建议 `0.20 ~ 0.40`，generic 默认 `0.40`；shipped `Profile C/D` 模板仍按各自显式值）

6. **观测页里看到新增字段不要慌**：

   - `scope_hint`：通常只是告诉检索“优先看哪个范围”；只有兼容旧调用方时，`fast/deep` 会先被当成快/深档位快捷值
   - `interaction_tier`：这条查询最后走的是 `fast` 还是 `deep`
   - `intent_llm_attempted`：这条查询是否真的尝试过 intent-LLM 分支；对 `fast` 请求来说，看到 `false` 很正常
   - `reflection_workflow`：运行时快照里看到的是 prepared / executed / rolled back 计数，属于当前 summary 视图，不是每条明细事件列表
   - 本地化 `P95`：延迟卡片看的还是同一个慢尾指标，只是标签现在会跟着当前语言一起本地化
   - `sm-lite`：是当前版本新增的一组轻量运行时状态，不是报错
   - `Runtime Snapshot`：是帮助你排障的摘要，不是必须每项都有值

---

## 6. 前端构建失败

```bash
cd frontend
rm -rf node_modules       # 清理缓存
npm ci                     # 全新安装依赖
npm run test               # 运行测试
npm run build              # 构建产物
```

> **Windows 用户**：使用 `rmdir /s /q node_modules` 替代 `rm -rf`。

常见原因：

- Node.js 版本不兼容：建议使用 Node.js `20.19+`（或 `>=22.12`）
- 网络问题导致 `npm ci` 失败：可配置 NPM Mirror

---

## 7. 测试失败或想做更深验证

如果你只是想先确认安装可用，先做最小运行检查：

```bash
curl -fsS http://127.0.0.1:8000/health
```

如果你想继续确认后端/前端都可用，再运行仓库自带测试：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate           # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest tests -q

cd ../frontend
npm ci
npm run test
npm run build
```

> **Windows PowerShell 用户**：`source` 命令不可用，使用 `.\.venv\Scripts\Activate.ps1` 激活虚拟环境。

**快速定位技巧**：优先查看最近改动文件对应的测试集，再扩大全量回归：

```bash
# 只运行特定测试文件
pytest tests/test_week6_maintenance_auth.py -q

# 只运行匹配名称的测试
pytest tests -k "test_search" -q
```

---

## 8. 数据库迁移异常

**现象**：启动时报迁移锁超时，类似 `Timed out waiting for migration lock`。

**背景**：Memory Palace 使用基于文件锁的迁移机制（参见 `backend/db/migration_runner.py`），防止多个进程同时执行迁移。

**排查与处理**：

1. **检查是否有重复进程同时启动**

2. **调整锁超时**：在 `.env` 中设置（默认 `10` 秒）：

   ```bash
   DB_MIGRATION_LOCK_TIMEOUT_SEC=30
   ```

3. **手动指定锁文件路径**：

   ```bash
   DB_MIGRATION_LOCK_FILE=/tmp/memory_palace.migrate.lock
   ```

   > 如果不设置，默认锁文件为 `<数据库文件>.migrate.lock`（例如 `demo.db.migrate.lock`），保存在与数据库文件同一目录下。
   >
   > 当前版本另外还有一把启动初始化锁：`<数据库文件>.init.lock`。它用于把 `init_db()` 串行化，避免 `backend` 和 `sse` 首次并发启动时互相抢库。
   >
   > 这把 `.init.lock` 只会用于**文件型 SQLite 数据库**。像 `:memory:` 这类目标不会生成它；如果你的 `DATABASE_URL` 带 query string，锁文件也会按真实数据库文件名生成，不会把 `?cache=shared` 这类参数拼进文件名里。

4. **手动删除残留锁文件后重启**：

   ```bash
   # 找到锁文件并删除（默认在数据库文件旁）
   rm -f /path/to/demo.db.migrate.lock
   rm -f /path/to/demo.db.init.lock
   ```

**验证锚点**：当前仓库中的 `backend/tests/test_migration_runner.py` 覆盖了迁移锁与超时场景。

---

## 9. 索引重建后仍无改善

**排查步骤**：

1. **确认索引已就绪**：

   ```python
   # MCP 工具调用
   index_status()
   # 返回中应包含 index_available=true
   ```

2. **检查 Embedding 后端配置是否正确**（参见 `.env.example`）：

   | 部署档位 | `RETRIEVAL_EMBEDDING_BACKEND` 应设为 | 说明 |
   |---|---|---|
   | Profile A | `none` | 纯关键字搜索，不使用 Embedding |
   | Profile B | `hash` | 本地 hash Embedding（默认值） |
   | Profile C/D | `api` 或 `router` | 本地开发优先用 `api` 直配排障；发布验证默认回到 `router` 主链路 |

   再补几个当前 setup 流程已经对齐的小边界：

   - 现在从 `Profile B` 切到远端 backend 时，保存前会继续要求你填真实的 `RETRIEVAL_EMBEDDING_DIM`，不再默认把旧的 `64` 带过去，也不会替你猜一个 `1024`
   - 如果你在向导里来回切 `Profile B/C/D` 或 `hash / api / router / openai`，当前会把已经隐藏的旧字段一起清掉；如果结果看起来还像旧配置，更该优先怀疑后端没重启，或者读的不是你以为的 `.env`
   - `openai` 也是当前支持的 embedding backend，但它不是单独的新 Profile；排障思路还是按远端 backend 的 `base / model / dim` 是否对齐来查

3. **确认有记忆内容**：

   ```bash
   curl -fsS \
     -H "X-MCP-API-Key: ${MCP_API_KEY}" \
     "http://127.0.0.1:8000/browse/node?domain=core&path="
   ```

4. **尝试 Sleep Consolidation**（通过 MCP 工具）：

   ```python
   rebuild_index(sleep_consolidation=true, wait=true)
   ```

   > Sleep Consolidation 会触发深度索引重建（参见 `backend/runtime_state.py` 中 `SleepTimeConsolidator`）。

5. **检查 `degrade_reasons`** 中是否存在降级标识（参见本文档第 5 节降级原因表）

---

## 10. CORS 报错（跨域访问被拒绝）

**现象**：前端请求后端 API 时浏览器报 CORS 错误。

**说明**：当前默认**不是允许所有 Origin**。后端在 `CORS_ALLOW_ORIGINS` 留空时，只放行本地常用来源：

```python
http://localhost:5173
http://127.0.0.1:5173
http://localhost:3000
http://127.0.0.1:3000
```

**如果仍然报错**，通常原因是：

- 前端开发服务器的代理未正确配置（检查 `frontend/vite.config.js`）
- Docker 部署时前端 Nginx 没有正确转发到后端（检查 `deploy/docker/nginx.conf.template`）
- 你正在从一个**不在允许列表里的浏览器来源**访问后端

**处理建议**：

- 本地开发：
  - 保持 `CORS_ALLOW_ORIGINS=` 留空即可
- 生产浏览器访问：
  - 把 `CORS_ALLOW_ORIGINS` 显式写成你的前端地址列表
  - 例如：`CORS_ALLOW_ORIGINS=https://app.example.com,https://admin.example.com`
- 不建议为了省事直接写 `*`
  - 尤其是你还需要 credentials / cookie / auth 头的时候

---

## 11. Docker 更新后页面仍像旧版本

**现象**：你已经更新了 Docker 前端镜像或重启了容器，但浏览器里看到的 Dashboard 还是旧页面，或者同一个地址看起来像两套不同页面。

**说明**：当前 Docker 前端的 `deploy/docker/nginx.conf.template` 会对 `/index.html` 返回：

```nginx
Cache-Control: no-store, no-cache, must-revalidate
```

这条配置的目的，是尽量减少浏览器继续复用旧入口 HTML 的情况。也就是说，如果你仍然看到旧页面，优先怀疑的通常不是仓库默认配置本身，而是下面几类情况：

- 前端容器其实还没切到新镜像 / 新配置
- 浏览器标签页还停留在旧页面，尚未重新加载
- 你在 Docker 前端前面又接了一层自己的反向代理、CDN 或企业缓存，并且那一层改写或忽略了缓存头

**处理建议**：

- 先确认当前前端容器确实已经重建并启动完成
- 再手动刷新一次页面
- 如果问题只在某个外部入口复现，直接检查该入口返回的 `/index.html` 响应头，确认是否还保留 `Cache-Control: no-store, no-cache, must-revalidate`
- 只有在你自己额外接了代理/缓存层时，才需要继续排查这些中间层

---

## 12. 获取帮助

如果以上步骤无法解决你的问题：

1. 查看后端完整日志：本地看启动终端输出，Docker 看 `docker compose -f docker-compose.yml logs backend --tail=200`
2. 检查 `GET /health` 返回的 `status` 和 `index` 字段
3. 通过 `GET /maintenance/observability/summary` 查看系统运行概况（该接口受 `MCP_API_KEY` 保护，请携带 `X-MCP-API-Key` 或 `Authorization: Bearer`）
4. 提交 Issue 时请附上：错误信息、操作系统、Python 版本、Node.js 版本、使用的 Profile 档位
