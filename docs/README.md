# Memory Palace 文档中心

> **Memory Palace** 是一套为 AI 编程助手设计的长期记忆系统，通过 MCP（Model Context Protocol）为 Codex / Claude Code / Gemini CLI / OpenCode 提供统一的记忆读写、检索、审查与维护路径；对 `Cursor / Windsurf / VSCode-host / Antigravity` 这类 IDE 宿主，当前推荐先看 `docs/skills/IDE_HOSTS.md`。
>
> 许可证：MIT
>
> 如果你想让 AI 直接带你一步一步安装，优先从独立仓库 [`memory-palace-setup`](https://github.com/AGI-is-going-to-arrive/memory-palace-setup) 开始。当前统一口径是：**优先走 skills + MCP，不要默认只配 MCP-only**。
>
> A/B/C/D 是不同的配置档位，不是“无感热切换按钮”。只要你切了 embedding backend / model / dimension，就要准备检查索引是否仍然匹配；当前运行时如果发现维度不一致，会明确要求重建索引，而不是假装切档已经成功。
>
> 前端会先恢复浏览器里已保存的语言；没有保存值时，中文浏览器语言映射到 `zh-CN`，其它语言默认 English。右上角语言按钮可在英文和中文之间切换，切换后会持久化。

![系统架构图](images/系统架构图.png)

---

## 📖 新手入口

| 文档 | 说明 |
|---|---|
| [`memory-palace-setup`](https://github.com/AGI-is-going-to-arrive/memory-palace-setup) | 给 AI 看的独立安装向导 skill。装好后直接说：`使用 $memory-palace-setup 帮我一步步安装配置 Memory Palace，优先走 skills + MCP。` |
| [GETTING_STARTED.md](GETTING_STARTED.md) | 5 分钟跑通本地开发、GHCR 拉镜像和 Docker，附 MCP 客户端配置示例 |
| [DASHBOARD_GUIDE_CN.md](DASHBOARD_GUIDE_CN.md) | 按页面解释 Dashboard 每个按钮、字段和典型操作流程 |
| [skills/GETTING_STARTED.md](skills/GETTING_STARTED.md) | 第一次把 CLI 客户端的 skill + MCP 真正接到当前仓库 |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 启动失败、端口冲突、鉴权失败、搜索降级等常见问题排查 |
| [SECURITY_AND_PRIVACY.md](SECURITY_AND_PRIVACY.md) | API Key 安全配置、隐私保护、分享前自检 |

## 🔧 核心文档

| 文档 | 说明 |
|---|---|
| [TECHNICAL_OVERVIEW.md](TECHNICAL_OVERVIEW.md) | 后端、前端、MCP、Docker 的实现结构与技术栈一览 |
| [TOOLS.md](TOOLS.md) | 9 个 MCP 工具的输入输出、返回约定与降级语义 |
| [DEPLOYMENT_PROFILES.md](DEPLOYMENT_PROFILES.md) | A/B/C/D 四档位配置模板、参数调优与部署方式 |
| [GHCR_QUICKSTART.md](GHCR_QUICKSTART.md) | GHCR 预构建镜像的最短用户使用路径 |
| [GHCR_ACCEPTANCE_CHECKLIST.md](GHCR_ACCEPTANCE_CHECKLIST.md) | GHCR 拉镜像后的最小用户验收清单 |
| [skills/SKILLS_QUICKSTART.md](skills/SKILLS_QUICKSTART.md) | 一页看懂 CLI 客户端怎么触发 skills、怎么配 MCP、怎么验收 |
| [changelog/post_release_hardening_2026-04-21.md](changelog/post_release_hardening_2026-04-21.md) | 修复后收口：MCP 契约收紧、检索回退语义、snapshot 恢复 |
| [changelog/release_v3.7.1_2026-03-26.md](changelog/release_v3.7.1_2026-03-26.md) | `v3.7.1` 的真实修复项与验证范围 |
| [changelog/ghcr_release_2026-03-11.md](changelog/ghcr_release_2026-03-11.md) | GHCR 预构建镜像发布说明 |

## 🧩 Skills 与客户端

| 文档 | 说明 |
|---|---|
| [skills/MEMORY_PALACE_SKILLS.md](skills/MEMORY_PALACE_SKILLS.md) | canonical `memory-palace` skill 设计、安装与多 CLI 编排策略 |
| [skills/CLI_COMPATIBILITY_GUIDE.md](skills/CLI_COMPATIBILITY_GUIDE.md) | 各 CLI 的推荐安装路径、检查方式与已知边界 |
| [skills/IDE_HOSTS.md](skills/IDE_HOSTS.md) | Cursor / Windsurf / VSCode-host / Antigravity 这类 IDE 宿主的接入方式 |

> 如果你只是想先把服务跑起来，优先看 `GETTING_STARTED.md` 里的 **GHCR 预构建镜像** 路径。
>
> 如果你还想把 `Claude / Codex / Gemini / OpenCode / IDE host` 接到当前仓库，再继续看 `docs/skills/`。Docker 只负责跑服务，不会自动改本机客户端的 skill / MCP 配置。

## 📊 测评与质量

| 文档 | 说明 |
|---|---|
| [EVALUATION.md](EVALUATION.md) | 公开基准方法、A/B/C/D 关键指标摘要与复现命令 |
</content>
