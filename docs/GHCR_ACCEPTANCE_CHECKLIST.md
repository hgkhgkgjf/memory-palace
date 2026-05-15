# GHCR 拉镜像后的用户验收清单

这份清单写给两类人：

- 你自己在发布后做一次快速复验
- 用户照着这份检查“我是不是已经真的跑起来了”

默认口径只针对 **Profile B + GHCR 预构建镜像**。

---

## 1. 前置条件

- 已安装 Docker
- 当前目录里有：
  - `docker-compose.ghcr.yml`
  - `.env.example`
  - `scripts/apply_profile.sh` / `scripts/apply_profile.ps1`

---

## 2. 启动命令

```bash
bash scripts/apply_profile.sh docker b .env.docker

docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

如果你是 Windows PowerShell，按同样思路改用：

```powershell
.\scripts\apply_profile.ps1 -Platform docker -Profile b -Target .env.docker

docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

`apply_profile` 会从仓库模板生成 `.env.docker`，并在覆盖已有目标前先备份，所以不要先手动把 `.env.example` 复制到 `.env.docker`。

---

## 3. 最小验收

### 3.1 Dashboard 能打开

浏览器访问：

- `http://localhost:3000`

通过标准：

- 页面能打开
- 右上角能看到语言切换按钮
- 页面可能显示 `设置 API 密钥`（英文模式下会显示 `Set API key`），这不一定是错误

### 3.2 后端健康检查正常

```bash
curl -fsS http://127.0.0.1:18000/health
```

通过标准：

- 返回 JSON
- 其中包含 `"status": "ok"`

### 3.3 Docker 下 setup assistant 进入指导模式

```bash
curl -fsS http://127.0.0.1:3000/api/setup/status
```

通过标准：

- 返回 `200`
- 响应里有：
  - `"running_in_docker": true`
  - `"apply_supported": false`
  - `"apply_reason": "docker_runtime_not_persisted"`

这说明：

- 前端代理正常
- 后端 setup 接口正常
- 向导不会假装自己能持久化容器 `.env`

### 3.4 SSE 入口可连

```bash
curl -i http://127.0.0.1:3000/sse
```

通过标准：

- 返回 `200` 或 `401`

解释：

- `200` 表示当前代理路径和鉴权已经放行
- `401` 也不一定是坏事，至少说明 `/sse` 路由可达，只是你当前请求没带对鉴权

---

## 4. 页面行为验收

### 4.1 中英文切换

手工检查：

- 点击右上角语言按钮
- 页面文案跟着切换
- 刷新页面后语言保持不变

### 4.2 受保护请求可用

手工检查：

- Memory / Review / Maintenance 页面不应全部报空白错误
- 如果页面只是继续显示 `设置 API 密钥`（英文模式下会显示 `Set API key`），但数据本身能正常加载，这通常是因为代理层持有 key，而浏览器本身不知道那把 key

---

## 5. 最容易误会的点

- GHCR 路径解决的是 **服务启动**
- 它**不会**自动帮你安装本机上的 `skills / MCP / IDE host`
- 如果你还想接 `Claude / Codex / Gemini / OpenCode / Cursor / Antigravity`，要继续看：
  - `docs/skills/README.md`
  - `docs/skills/GETTING_STARTED.md`

---

## 6. 停止服务

```bash
docker compose -f docker-compose.ghcr.yml down --remove-orphans
```

如果你要把数据库和 snapshots 一起清掉，再用：

```bash
docker compose -f docker-compose.ghcr.yml down -v
```

---

## 7. 如果失败，先看哪里

优先看这些文档：

- `docs/GETTING_STARTED.md`
- `docs/DEPLOYMENT_PROFILES.md`
- `docs/SECURITY_AND_PRIVACY.md`
- `docs/TROUBLESHOOTING.md`
