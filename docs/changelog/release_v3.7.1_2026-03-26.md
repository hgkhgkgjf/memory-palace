# Memory Palace v3.7.1 发布说明（2026-03-26）

记录本仓库已真实修改并真实复验的内容。

---

## 1. 一句话结论

`v3.7.1` 是一轮“收口 + 运维边界修正”的发布：路径删除更接近原子，回滚 metadata 不再误伤 alias，Windows 脚本边界更稳，repo-local skill evaluator 更像环境检查而不是误报仓库失败。

---

## 2. 实际修改

- `delete_memory` 把当前 path 状态读取、删除前 snapshot 取值以及 path 删除放进同一条 SQLite 写事务。多个本地进程共用同一个 SQLite 文件时，别的进程更不容易在“删的是什么”和“实际删掉了什么”之间插队。
- `rollback_to_memory(..., restore_path_metadata=True)` 只恢复当前选中 path 的 metadata。alias 自己的 `priority` / `disclosure` 不会再被主路径的 snapshot metadata 覆盖。
- provider-chain 的 embedding cache 更会复用 fallback/provider 的缓存结果。对 fail-open 远端链路来说，前一次 provider 失败后，后续请求不再总是把所有 fallback provider 重新打一遍。
- Review session 列表会跳过非法的 legacy session 目录名，而不是让这些旧目录直接把 session 列表打挂。
- `add_alias` 在 MCP 入口层统一执行 `priority` 严格校验，bool / float 这类值不会再从这条公开工具路径漏过去。
- `apply_profile.sh` 能正确处理从 PowerShell / WSL / Git Bash 传进来的 Windows 绝对目标路径（包括分隔符已经被 shell 吞坏的常见形态），不会再往仓库根目录里落坏文件名。
- `docker_one_click.ps1` 用 UTF-8 without BOM 回写生成的 Docker env 文件。原生 Windows PowerShell 不会再沿这条路径把 Docker Compose 要读的 env 文件写成 UTF-16。
- `evaluate_memory_palace_skill.py` 能更正确地解析常见 dotenv 风格的 `DATABASE_URL`，包括带引号、`export DATABASE_URL=...` 和尾部注释。它会把 user-scope 绑定漂移、Gemini 登录/鉴权提示这类机器环境问题记成 `PARTIAL`，并把 `gemini_live` 保持为显式 opt-in。

---

## 3. 验证范围

- 后端测试：`797 passed, 20 skipped`
- 前端测试：`119 passed`
- 前端生产构建：通过
- live stdio MCP e2e：通过
- repo-local skill sync check：通过
- repo-local skill evaluator：
  - 当前机器上已重新确认退出码为成功
  - user-scope 漂移、Gemini 登录、宿主 runtime 缺失这类环境问题保留为 `PARTIAL` / `MANUAL`
- 原生 macOS 本机验证：
  - repo-local backend + standalone SSE + Vite 路径已复验
  - Memory / Review / Maintenance / Observability 四页已在真实浏览器中复验
  - 中英文切换与持久化已复验
- 原生 Windows 本机 smoke：
  - 已在发布标签上完成后续真实宿主复验
  - 宿主机启动与主功能路径已复验
- Docker 路径验证：
  - Profile B one-click 路径已复验
  - Profile C / D 的 runtime injection 检索链路已结合真实 embedding / reranker / LLM 服务复验
  - Dashboard 根页面、backend health、带鉴权的 browse、`/sse` 可达

---

## 4. 对用户最直接的影响

- 共用本地 SQLite 时，路径删除更不容易撞上竞态
- 回滚单一路径时，不会再把 alias 自己的 metadata 一起抹平
- Windows 的 shell / PowerShell 运维脚本边界更稳了
- repo-local skill 验证更不容易因为机器本地登录或 user-scope 漂移而误报仓库失败

发布摘要建议：

> `v3.7.1` 收紧了本地 delete-path 原子性，保住了 alias 自身的 rollback metadata，修稳了 Windows 运维脚本边界，并完成了原生 macOS / Windows 宿主上的主链路复验。
