# Memory Palace Skills Docs

本目录描述 Memory Palace 的 skills / MCP 编排方案。

如果你只通过 `docker compose` 或 GHCR 镜像跑 `Dashboard / API / SSE`，这里不一定是第一站；要接 `Claude / Codex / Gemini / OpenCode / IDE host` 才继续读。Docker 跑服务，不会自动改本机的 skill / MCP / IDE host 配置。

如果你想让 AI 全程带着你装，先安装独立的 [`memory-palace-setup`](https://github.com/AGI-is-going-to-arrive/memory-palace-setup)，然后说：

```text
使用 $memory-palace-setup 帮我一步步安装配置 Memory Palace，优先走 skills + MCP。
```

如果只想把客户端手工接到 Docker 暴露的 `/sse`，看：

- `docs/GHCR_QUICKSTART.md`
- `docs/GETTING_STARTED.md` 里的 `6.2 SSE 模式` 和 `6.3 客户端配置示例`

---

## 文档导航

| 文件 | 用途 |
|---|---|
| [`SKILLS_QUICKSTART.md`](SKILLS_QUICKSTART.md) | 最短安装路径与触发自检 |
| [`CLI_COMPATIBILITY_GUIDE.md`](CLI_COMPATIBILITY_GUIDE.md) | 各 CLI 的完整选项与边界（Claude / Gemini / Codex / OpenCode） |
| [`IDE_HOSTS.md`](IDE_HOSTS.md) | Cursor / Windsurf / VSCode-host / Antigravity 的 `AGENTS.md + MCP snippet` 接法 |
| [`MEMORY_PALACE_SKILLS.md`](MEMORY_PALACE_SKILLS.md) | Skill 体系设计、目录职责、维护顺序 |
| [`GETTING_STARTED.md`](GETTING_STARTED.md) | 入口文档（内容已合并到 `SKILLS_QUICKSTART.md`） |

英文版本：`SKILLS_QUICKSTART_EN.md` 等同名加 `_EN` 后缀。

---

## canonical bundle

真正的 canonical bundle 在：

```text
docs/skills/memory-palace/
├── SKILL.md
├── references/
├── variants/
└── agents/openai.yaml
```

公开文档负责告诉用户怎么用，canonical bundle 负责定义这套 skill 到底是什么。`AGENTS.md` 作为 repo-local 规则入口随仓提供，便于 Antigravity 等支持 `AGENTS.md` 的客户端读取约束；旧环境仍可兼容 `GEMINI.md`。

`Cursor / Windsurf / VSCode-host / Antigravity` 不再以 hidden skill mirrors 为默认接入方式，统一通过 `AGENTS.md + python scripts/render_ide_host_config.py --host ...` 接入。

---

## 本地验证报告

- `TRIGGER_SMOKE_REPORT.md` —— 运行 `python scripts/evaluate_memory_palace_skill.py` 后生成
- `MCP_LIVE_E2E_REPORT.md` —— 运行 `cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py` 后生成

这两份是本地复核产物，不是主入口文档。公开仓库默认看不到（被 `.gitignore` 排除）。准备转发前请自己检查内容是否含本机路径或客户端配置痕迹。

如果在并行 review 或 CI 里不想覆盖默认文件，设置 `MEMORY_PALACE_SKILL_REPORT_PATH` / `MEMORY_PALACE_MCP_E2E_REPORT_PATH`。相对路径会落到系统临时目录的 `memory-palace-reports/` 下；要完全控制位置传仓库外的绝对路径。
