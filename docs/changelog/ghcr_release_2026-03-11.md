# GHCR 预构建镜像发布说明（2026-03-11）

这份说明只记录**已经落地、已经验证**的 GHCR 发布能力，不写“理论上可以”的内容。

---

## 1. 一句话结论

现在可以直接从 GitHub Container Registry 拉取 Memory Palace 的预构建镜像，用 `docker compose` 启动默认的 **Profile B**，从而绕开本地镜像构建环境问题。

---

## 2. 这次新增了什么

- 新增 GHCR 镜像发布 workflow
- 新增 `docker-compose.ghcr.yml`
- 默认卷名改为按 compose project 隔离
- 一键脚本在端口冲突场景下会打印真实可访问地址
- 文档已经把“用户路径”和“维护者路径”拆开：
  - 用户路径：`docker-compose.ghcr.yml`
  - 维护 / 本地 build 路径：`docker_one_click.sh/.ps1`

---

## 3. 现在最推荐谁用这条路径

最适合这类用户：

- 本地 Docker 能用，但本地镜像 `build` 总是失败
- 只想先把 Dashboard / API / SSE 跑起来
- 不想先排本地 Node / Python / buildx / Dockerfile 环境问题

如果你就是想“先能用起来”，优先走 GHCR 路径。

---

## 4. 当前已验证范围

本次公开口径只承诺这些：

- 默认 **Profile B**
- Dashboard 可访问
- Backend API 可访问
- SSE 服务可访问
- Docker 卷默认按 compose project 隔离
- Docker 下首启配置向导会进入 guidance mode，不会伪装成能持久化容器 `.env`

这次没有把以下内容写成“GHCR 路径已完全验证”：

- `Profile C / D` 在真实外部模型服务下的用户路径
- 原生 Windows / native `pwsh` 全链路终验
- `skills / MCP / IDE host` 自动安装

---

## 5. 最重要的边界

### 5.1 这条路径解决什么

它解决的是：

- **服务启动**
- 也就是 `Dashboard / API / SSE`

### 5.2 这条路径不自动解决什么

它不会自动帮你完成：

- `Claude / Codex / Gemini / OpenCode` 的本机 skill 安装
- IDE host 的 repo-local `AGENTS.md + MCP snippet` 接入
- 你机器上的 client config 改写

也就是说：

- Docker 负责跑服务
- 客户端接入仍然是宿主机侧配置问题

---

## 6. 用户最短路径

```bash
git clone https://github.com/AGI-is-going-to-arrive/Memory-Palace.git
cd Memory-Palace

bash scripts/apply_profile.sh docker b .env.docker

docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

默认访问地址：

- Dashboard：`http://localhost:3000`
- Backend API：`http://localhost:18000`
- SSE：`http://localhost:3000/sse`

> 注意：这条 GHCR compose 路径**不会自动换端口**。如果本机 `3000` / `18000` 被占用，请先设置 `MEMORY_PALACE_FRONTEND_PORT` / `MEMORY_PALACE_BACKEND_PORT`。

---

## 7. 如果还想接客户端怎么办

分两种情况：

### 方式 A：只想手工连 MCP

如果你的客户端支持远程 SSE MCP，可以手工配置到：

- `http://localhost:3000/sse`

并带上对应的 API key / 鉴权头。

### 方式 B：想复用仓库现成的 skill + MCP 自动化安装链路

继续使用当前仓库 checkout，然后看：

- `docs/skills/GETTING_STARTED.md`
- `docs/skills/SKILLS_QUICKSTART.md`

这条路径仍然是 **repo-local 安装路径**，不是 Docker 自动安装路径。

---

## 8. 相关文档

- `docs/GETTING_STARTED.md`
- `docs/DEPLOYMENT_PROFILES.md`
- `docs/SECURITY_AND_PRIVACY.md`
- `docs/skills/README.md`
- `docs/skills/GETTING_STARTED.md`
