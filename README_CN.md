<p align="center">
  <img src="docs/images/系统架构图.png" width="280" alt="Memory Palace Logo" />
</p>

<h1 align="center">🏛️ Memory Palace · 记忆宫殿</h1>

<p align="center">
  <strong>Memory Palace provides AI agents with persistent context and seamless cross-session continuity.</strong>
</p>

<p align="center">
  <em>"每一次对话都留下痕迹，每一道痕迹都化为记忆。"</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License" />
  <img src="https://img.shields.io/badge/python-3.10+-3776ab.svg?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-18-61dafb.svg?logo=react&logoColor=black" alt="React" />
  <img src="https://img.shields.io/badge/Vite-646cff.svg?logo=vite&logoColor=white" alt="Vite" />
  <img src="https://img.shields.io/badge/SQLite-003b57.svg?logo=sqlite&logoColor=white" alt="SQLite" />
  <img src="https://img.shields.io/badge/protocol-MCP-orange.svg" alt="MCP" />
  <img src="https://img.shields.io/badge/Docker-ready-2496ed.svg?logo=docker&logoColor=white" alt="Docker" />
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="https://agi-is-going-to-arrive.github.io/Memory-Palace/">介绍页</a> · <a href="docs/README.md">文档</a> · <a href="docs/GETTING_STARTED.md">快速开始</a> · <a href="docs/EVALUATION.md">评测报告</a>
</p>

---

## 🌟 什么是 Memory Palace？

**Memory Palace（记忆宫殿）** 是一套专为 AI Agent 打造的长期记忆操作系统。它为大语言模型提供 **持久化、可检索、可审计** 的外部记忆能力——让你的 Agent 不再"每次对话都从零开始"。

通过统一的 [MCP（模型上下文协议）](https://modelcontextprotocol.io/) 接口，Memory Palace 已提供 **Codex、Claude Code、Gemini CLI、OpenCode** 的接入方案。对 `Cursor / Windsurf / VSCode-host / Antigravity` 这类 IDE 宿主，当前推荐单独走 **`AGENTS.md + MCP 配置片段`** 路径，而不是把它们当成完整 CLI skill 客户端来配置。想走最短路径时：CLI 客户端先看 [SKILLS_QUICKSTART.md](docs/skills/SKILLS_QUICKSTART.md)，IDE 宿主先看 [IDE_HOSTS.md](docs/skills/IDE_HOSTS.md)。

如果你希望 **AI 一步一步带你安装**，优先从独立的 setup-skill 仓库开始：[`memory-palace-setup`](https://github.com/AGI-is-going-to-arrive/memory-palace-setup)。当前推荐口径是 **优先走 skills + MCP**，而不是只配 MCP。比较实用的一句提示词是：`使用 $memory-palace-setup 帮我一步步安装配置 Memory Palace，优先走 skills + MCP，不要只给 MCP-only。默认先按 Profile B 起步，但如果环境允许，请主动推荐我升级到 C/D。`

### 为什么选择 Memory Palace？

| 痛点 | Memory Palace 如何解决 |
|---|---|
| 🔄 Agent 每次对话都忘记前文 | **持久化记忆存储**——基于 SQLite，记忆跨会话保留 |
| 🔍 过往上下文难以找到 | **混合检索引擎**（关键词 + 语义 + 重排序），支持意图感知搜索 |
| 🚫 无法控制写入内容 | **Write Guard** 预检每次写入；快照机制支持完整回滚 |
| 🧩 不同工具、不同集成方式 | **统一 MCP 协议**——一套接口对接所有 AI 客户端 |
| 📊 看不到系统内部状态 | **内置仪表盘**——记忆浏览、审查、维护、可观测性四大视图 |

---

## 🆕 这次版本更新了什么？

- **多语言检索现在更少丢信号了**：本地 `hash embedding`、`MMR` 去重和 session-first cache 现在都能更一致地保留中日韩与混合 Latin 文本，并会把 `ＡＰＩ` 这类全角 Latin 归一到和 `API` 同一条检索路径里。
- **本地 C/D 的 Docker 联调不那么脆了**：对 `docker_one_click.sh/.ps1 --allow-runtime-env-injection` 来说，模板占位符校验现在会先延后到运行时注入落盘之后，再继续做 fail-closed 检查；缺失必填值时仍然会直接拦下。对这条 one-click 路径来说，像 `127.0.0.1` / `localhost` / `::1` 这样的 loopback provider base 现在也会在生成的 Docker env 里自动改成 `host.docker.internal`；同一轮里出现的其它 private provider 字面量地址，则只会把精确 host 追加进 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS`，不会顺手放大到整段网段。
- **repo-local wrapper 现在会更一致地拦住本地 sqlite 误配**：仓库自带的 Python / shell wrapper 现在会先把常见的斜杠和大小写变体归一化，拒绝相对 sqlite 路径，也会把常见的 URL 编码容器路径先解开，再判断本地 `DATABASE_URL` 是否还指着 Docker 内部的 `/app/...` 或 `/data/...`。说人话就是：像 `sqlite+aiosqlite:///demo.db`、`sqlite+aiosqlite://///app/data/...`、`sqlite+aiosqlite:////%2Fapp%2Fdata/...` 这类值，现在都不会再被误放过。
- **Docker 基础镜像现在也收得更紧了**：仓库自带的 Dockerfile 现在把基础镜像 digest 一起锁住了，后面重建时不容易再因为上游 tag 漂了而悄悄变样。
- **GHCR 发布镜像现在会先自查 backend 健康脚本了**：backend 镜像现在自带 Docker 级别的 `HEALTHCHECK`，`docker-compose.ghcr.yml` 里的 backend 也继续明确绑在 `0.0.0.0`，发布工作流还会在 push 前先检查 `/usr/local/bin/backend-healthcheck.py` 是否真的在镜像里而且可执行。
- **当前公开验证快照**：2026-05-15，backend `1382 passed, 22 skipped`，frontend `203 passed`；
  前端 typecheck/build、i18n audit、bundle budget、repo-local live MCP e2e，以及
  Docker/profile/SSE/script 重点契约通过。`Profile B` 使用项目默认设置；
  runtime env injection 只用于 `Profile C/D`。下面的 benchmark 表未重算；
  原生 Windows / 原生 Linux host runtime 仍需目标环境复核。
- **公开 MCP 契约现在更严格了**：MCP 入口会直接拒绝带控制字符 / 不可见字符 / surrogate 的 URI，也会在真正进库前拦住超长的 `search_memory` / `create_memory` / `update_memory` payload；对 percent-encoded 记忆 URI 的处理现在也更可预期：字面 `%20` 这类路径文本仍然合法，已有记忆也可以通过编码空格 / 编码斜杠这类解码变体去兼容查找，而像 `C%3A/...` 这种解码后变成 Windows 文件路径的输入会继续被当成非法记忆 URI 直接拒绝。如果 `add_alias` 已经写入数据库，但 snapshot 补记失败，也会把 alias path 一起回滚掉。
- **搜索 fail-close 这条链也更收口了**：如果最终 path 状态复核自己出错，`search_memory` 现在会直接丢掉那条结果，而不是把可能已经过期的 URI 继续当正常命中返回。像 `AND` / `OR` / `NOT` / `NEAR` 这类 FTS 控制词，或者 wildcard 很重的查询，也会改成当前请求内回退，而不是让控制语义悄悄改掉匹配结果，或把正常用户输入打成一条吵人的 `fts_query_invalid`。
- **private provider 目标现在不会再被默认信任**：像 `127.0.0.1` / `::1` 这类 loopback IP 字面量，再加上 `localhost`，仍然默认可用；其它 private IP 字面量，以及解析后会落到 private 非 loopback 地址的 hostname，现在都必须通过 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` 显式 allowlist 才能继续使用。link-local 和格式错误地址仍然会 fail-close。
- **SQLite 启动和索引补修现在更收口了**：已有的本地 SQLite 文件在启动时如果 `PRAGMA quick_check(1)` 不是 `ok`，现在会直接 fail-close；bootstrap 建索引时也不只会补缺 chunk 的记忆，还会补缺失的 FTS 行；永久删除一条记忆时，也会把这条记忆关联的 chunk/vector/FTS 索引一起清掉，不再留下残留行。
- **Dashboard 多了层级、遗忘和搜索质量面板**：Memory 页会展示 L0/L1/L2 层级视图，Maintenance 页会展示遗忘模拟和人工归档候选，Observability 页会展示 Search Quality。Search Quality 是真实鉴权接口，但在带标签质量样本持久化前仍会返回 `is_mock=true` / `status=unavailable`。
- **Review snapshot 不会再默认一直涨下去了**：每次 snapshot 成功写入后，后端现在会按 age/count 做保守的 session 级清理，同时保护当前 session，并跳过拿不到锁的旧 session。
- **reflection 后台清理现在更收口了**：同一个 session、source、reason、content 的并发 `prepare` 请求，仍然会复用同一个 prepared review；如果最后一个等待方先走掉了，后端现在也会把这条已经没人等的后台 prepare 一起取消，不再让它自己继续跑完。
- **external import guard 现在会更早、更干净地 fail-close**：`/maintenance/import/prepare` 现在会先按文件 metadata 汇总大小，再决定要不要继续读正文，所以超大单文件或超大批次会在读内容前直接被拒绝。非 UTF-8 文本现在也会稳定返回 `file_read_failed`，不再冒出底层 fd 关闭错误。
- **前端类型检查现在更容易复现，也更不容易在 CI 里漏掉了**：`frontend/package.json` 现在已经补上正式的 `npm run typecheck`，Docker publish 的校验工作流也会在发布前跑同一条检查。
- **Review 页清空最后一个 session 后不再残留旧快照列表了**：现在一旦最后一个审查 session 被清空，页面会一起把旧的 snapshot 列表和底部动作区收掉，不会再留下一组看起来还能点的旧控件。
- **Setup Assistant 和 Dashboard 的本地保存现在更严格了**：带鉴权的非 loopback 请求仍然可以查看 setup 当前状态，但本地 `.env` 写入依旧只保留给“直连回环地址 + 当前项目内 `.env*` 文件”这条路径，所以保存按钮现在会直接禁用并显示原因，不会再看起来能点、点完再失败。如果后端本身已经带着 `MCP_API_KEY` 在跑，这条 loopback 写入路径现在也必须带上同一把有效 key。第一次往本地 `.env` 保存时，现在还要求 `Dashboard API key` 不能为空，不会再把“空 key 首次落盘”当成默认自举路径。如果这次第一次保存里已经带上了远端 embedding/reranker 或 LLM provider 链字段，而当时还没有任何 Dashboard 鉴权配置，后端现在会故意先只落 Dashboard 鉴权相关字段；provider 链字段要等下一次带鉴权的保存再真正写进去。现在就算 setup 状态回来的比较晚，没碰过的检索字段也会按真实状态补齐；先输入 Dashboard key，不会再把已有的 router / reranker 配置偷偷重置回 `hash` / `false`。像 `http://127.0.0.1:8001/v1` 这种真实本地 router 地址仍然可以用，但示例 model id 仍然会被当成占位值拦下；如果你切到直连 `api` / `openai` embedding 路径，本地 `.env` 保存前还必须填一个真实的正整数维度。`/embeddings`、`/rerank`、`/chat/completions` 这类常见 API 后缀现在会自动归一化；格式不对或指到 link-local 的 provider base 会直接拦下，不会再原样写进 `.env`。`Review` / `Maintenance` 在当前运行环境缺少 `confirm` / `prompt` / `alert` 时，也会 fail-close 并改成页内提示。
- **Dashboard 加载和 SSE 链路现在更顺了**：较大的 Dashboard 路由现在会按需懒加载，前端 bundle 预算也回到了警戒线以下。SSE helper 现在会跟着带前缀的 `VITE_API_BASE_URL` 去解析 `/sse`，不再默认假设站点根路径。浏览器里已经有 Dashboard 鉴权时，Observability 会切到可带同一组鉴权头的 fetch-based SSE，而且每次重连都会重新读取当前浏览器里的 Dashboard 鉴权，再带上去；同一条链路也保留指数退避重连、页面生命周期暂停/恢复和 idle watchdog。现在只要浏览器侧 Dashboard 鉴权发生变化，就会额外发出一条 maintenance-auth 变更事件；Observability 也会在鉴权变更后，或者在终态 `401` 之后用户重新聚焦标签页时，重建带鉴权的 `/sse` 连接。没有浏览器侧鉴权时，仍然走更轻量的原生 `EventSource` 路径。
- **vitality cleanup 的多条删除现在更保守了**：带确认的多选删除现在会在后端具备 session-backed permanent delete 能力时，放进同一条 DB session 里原子执行；如果做不到这条原子路径，后端会直接拒绝多条 fallback，而不是出现“前几条删掉，后几条失败”的半成功状态。单条删除 fallback 仍然允许继续执行。
- **Maintenance 里的孤儿记忆清理现在更顺手了**：孤儿记忆卡片现在可以直接用键盘聚焦，并用 `Enter` / `Space` 展开；批量删除也会并行发出少量请求，同时继续保留逐条失败和部分成功的提示。
- **真实 benchmark 产物现在更诚实地记录降级了**：真实 A/B/C/D runner 现在会同时记录查询阶段和建索引阶段的降级信息；对 D 档位来说，`reranker` 配置缺失或响应无效都不会再被算成“干净通过”。
- **Benchmark 产物默认不再写回工作树**：benchmark helpers 默认把运行产物写到系统临时目录下的 `memory-palace-benchmark-artifacts/<run-token>/...`，也仍支持显式 `artifact_dir` / `BENCHMARK_ARTIFACT_DIR` 覆盖，方便并行复验时保持隔离。
- **本地验证报告现在更收口了**：skill / MCP smoke 报告会脱敏常见 secret、session token 和本地绝对路径，并在宿主支持时改用更私有的文件权限。
- **分享前检查现在会更主动拦住本地工件了**：`scripts/pre_publish_check.sh` 现在会直接拦截已跟踪的 `.audit` / `.playwright-mcp` 工件，也会扫描 tracked 文件里的本地 endpoint/key 模式，比如 `sk-local-*`、以及带端口的 loopback/private provider 地址；仓库自己在 compose 里用来探测前端健康的 `127.0.0.1:8080` 这条合法探针不会再被误报。
- **Observability 成功提示现在不再把英文词夹进中文里了**：重建、睡眠整合、任务重试这些成功提示现在会先走本地化 token，再拼进最终消息，所以中文界面里不会再看到生硬的 `job` / `sync` 片段。
- **共用本地 SQLite 时，路径删除更稳了**：`delete_memory` 现在会把当前 path 状态读取、删除前 snapshot 取值和 path 删除都放进同一条 SQLite 写事务，而不是拆成多个独立数据库会话。
- **回滚不再抹平 alias 自己的 metadata**：`rollback_to_memory(..., restore_path_metadata=True)` 现在只恢复当前选中 path 的 metadata，不会再把 alias 自己的 `priority` / `disclosure` 一起覆盖掉。
- **metadata-only 回滚现在会按当前 path 状态 fail-close 了**：后端在真正恢复 `priority` / `disclosure` 前，会在 write lane 里再确认一次当前 path 指向和当前 metadata。要是 path 中途没了，现在会直接返回 `404`；要是 path 指向或 metadata 已经先变了，现在会返回 `409`，不再默默覆盖较新的状态，也不会再冒一个笼统的 `500`。
- **Windows 运维脚本边界更稳了**：`apply_profile.sh` 现在能更安全地规范化从 PowerShell / WSL / Git Bash 传进来的 Windows 绝对目标路径，`docker_one_click.ps1` 现在也会用 UTF-8 without BOM 回写生成出来的 Docker env 文件。
- **provider-chain 的缓存恢复更合理了**：对 fail-open embedding provider chain 来说，前一次远端失败后，后续请求现在可以复用 fallback/provider 的缓存结果，而不是总把后面的 provider 全部重打一遍。
- **repo-local 校验现在更偏保守口径**：`evaluate_memory_palace_skill.py` 现在能更正确地解析常见 dotenv 风格的 `DATABASE_URL`，`gemini_live` 改成了显式 opt-in（`MEMORY_PALACE_ENABLE_GEMINI_LIVE=1`），user-scope 绑定漂移或 Gemini 登录/鉴权提示也会被记成环境 `PARTIAL`，而不是直接当成仓库主链路失败。
- **reflection rollback 现在既更可审计，也更兼容旧调用方式了**：这条回滚现在不再依赖 ambient session。调用方如果已经知道 `session_id`，后端仍然会拿它去和 learn job 做一致性校验；如果 rollback 只带了 learn `job_id`，后端现在会先从这条 job 里恢复出原始 `session_id` 再继续做回滚。明确传入空白或只含空格的 `session_id` 仍然会 fail-close。
- **公开 `priority` 契约现在统一了**：MCP 工具入口不再先把 `True`、`False`、`1.9` 这类值强转成整数，再交给底层更严格的 SQLite 校验。说人话就是：非整数优先级现在会在公开工具路径上更早被拦下。
- **Dashboard 鉴权现在会跟着配置好的 API base 走**：如果你把 `VITE_API_BASE_URL` 指到带前缀的路径，或者你自己的 API 域名，浏览器里保存的 Dashboard key 现在也会继续附加到 `/browse`、`/review`、`/maintenance`、`/setup` 这些受保护请求上；但它仍然**不会**被发到无关第三方绝对 URL。
- **repo-local skill mirrors 已重新对齐**：canonical `memory-palace` skill 和 `.agent/.cursor` mirrors 现在重新一致，`python scripts/sync_memory_palace_skill.py --check` 在当前仓库状态下会返回 `PASS`。
- **skills + MCP 更像产品了**：现在不只是“有工具”，而是补齐了安装、同步、smoke 和 live e2e。
- **部署更稳了**：Docker 一键脚本补了 deployment lock，运行时环境注入默认关闭，分享或正式发布前也有自检脚本兜底。
- **写入链路的恢复能力更强了**：同一 session 的 snapshot 现在改成文件锁，SQLite 短暂锁冲突会做一次小范围重试，后台索引任务也会和前台写入共用同一条写入门控。
- **审查回滚现在更保守了**：如果同一个 URI 已经在另一条 review session 里留下了更晚的内容快照，旧快照的 rollback 会直接拒绝，不再默默把较新的改动回滚掉。对 create-tree 这类回滚，后端现在也会在同一条删除事务里重新确认当前 head，并把进入 write lane 前已经挂到这次快照下面的 descendants 一起清掉，所以不容易再留下晚到子节点，也不容易误删已经被更新过的新内容。
- **Dashboard 根入口现在也有最后一层兜底页了**：React 根节点外面现在包了一层全局错误边界。要是某个组件在 render 阶段直接崩掉，页面现在会先落到一个最小恢复页，而不是把整个 SPA 直接卸掉又不给解释。
- **高干扰检索在当前基准集里表现更稳**：对照旧版本时，`s8,d200` 与 `s100,d200` 这类更容易被干扰的场景，C/D 档位显示出更好的召回。
- **前端语言切换更直接了**：前端现在会先恢复浏览器里已保存的语言；如果还没有保存值，常见中文浏览器语言会自动归并到 `zh-CN`，其他首次访问场景则回退到英文。右上角仍然可以一键中英切换，浏览器也会记住你的选择。
- **Edge 下的 Dashboard 渲染现在更保守了**：当前端检测到 Microsoft Edge 时，会自动切到更轻量的视觉模式，改用静态背景、减轻 blur，并收掉一部分卡片动效，优先减少本地卡顿，同时保留同一套 Dashboard 功能。
- **本地 operator 路径也更稳了**：repo-local stdio wrapper 现在会继续复用 `.env` 里的 `RETRIEVAL_REMOTE_TIMEOUT_SEC`，仓库自带的两条 repo-local wrapper 都会补本地 `NO_PROXY` / `no_proxy` 绕过，stdio 转发也改成了分块而不是逐字节，shell wrapper 这条路径还会先补上 UTF-8 默认编码，Observability 搜索和活力清理确认这类长请求也会给浏览器更长的等待时间。
- **一些容易卡住的小边界也补齐了**：搜索结果最后一轮会优先批量校验当前 path 状态，Windows 风格宿主如果误把 `backend/mcp_wrapper.py` 跑在 `Git Bash / MSYS / Cygwin` 下也更容易选中正确的 `.venv` 解释器，Docker 前端代理 key 里像制表符这类 ASCII 控制字符现在也会被直接拦下。
- **公开口径更保守了**：文档现在已经补上原生 Windows 的 repo-local `python-wrapper` 路径，但你自己的远程环境 / GUI 宿主环境仍建议按目标环境再复核一次。
- **客户端边界写清楚了**：`Claude/Codex/OpenCode/Gemini` 走文档里的 CLI 路径；`Cursor / Windsurf / VSCode-host / Antigravity` 走 `AGENTS.md + MCP 配置片段`；`Gemini live` 和 GUI 宿主验证仍保留边界说明。

---

## ✨ 核心特性

### 🔒 可审计写入流水线

每一次记忆写入都经过严格流水线：**Write Guard 预检 → 快照记录 → 异步索引重建**。Write Guard 核心动作为 `ADD`、`UPDATE`、`NOOP`、`DELETE`；`BYPASS` 作为上层 metadata-only 更新场景的流程标记，整体链路每一步均可追溯。

现在 Dashboard 树形编辑也遵循同一条规则：`POST /browse/node`、`PUT /browse/node`、`DELETE /browse/node` 在真正改数据前也会先写 Review snapshot，所以 Review 页面里能看到并回滚这些修改。

现在同一个 `session_id` 下的快照写入会通过每个 session 一把文件锁做串行化，`manifest.json` 和单个快照 JSON 文件都会通过原子替换方式落盘。用人话说就是：如果多个本地进程共用同一个仓库 checkout，并且刚好写到同一个 Review session，这条快照记录链更不容易丢条目，也不容易留下半写入的 JSON 文件。

每次 snapshot 成功写入后，后端现在还会按 age/count 做一层保守的 session 级 retention。说人话就是：旧的 Review session 目录默认不会一直涨下去，但当前 session 仍然会被保护，拿不到锁的旧 session 也会先跳过，不会硬删。

如果某条 Review session 的 `manifest.json` 缺失或损坏，后端现在只会在**能保住原始数据库作用域**时才重建它。说人话就是：你切到另一份 `.env`、另一个 compose project 或另一份 SQLite 文件后，不会再把旧会话误认成“当前库”的会话；如果这条会话暂时没法安全识别，它会先被隐藏，而不是被一次只读的会话列表请求顺手删掉。

如果同一个 URI 已经在另一条 Review session 里留下了**更晚的内容快照**，旧快照的 rollback 现在会直接返回 `409`。说人话就是：系统会先挡住“拿旧快照去覆盖较新内容”这种情况，而不是假装回滚成功。

正常的 backend、SSE、repo-local stdio 退出路径上，`compact_context` / auto-flush 这类 pending summary 现在还会做一次 **best-effort drain**。说人话就是：如果进程准备正常退出，系统会先尽量把还没落盘的 flush summary 补写成记忆；如果这一步失败，就跳过，不会为了“硬写进去”再冒额外风险。

同一条 session 的 `compact_context` / auto-flush flush 现在还会额外走一层基于数据库文件的 session 级进程锁。说人话就是：如果两个本地进程或 worker 同时想把同一个 session 压缩成摘要，后来的那个会直接拿到 `already_in_progress`，而不是继续和前一个抢着写。

现在 SQLite 的短暂锁冲突也会做一次小范围重试，后台索引任务写库时也会经过同一条全局 write lane。说人话就是：前台写入和异步重建在本地多进程压力下更不容易互相撞上。

Dashboard / Review / Maintenance 这几组写接口现在在 write lane 等太久时，也会返回结构化的 `503`（`write_lane_timeout`），不再只给一个很难排查的通用 `500`。MCP 写工具遇到同样情况时，也会返回可重试的结构化错误结果。

### 🔍 统一检索引擎

三种检索模式——`keyword`（关键词）、`semantic`（语义）、`hybrid`（混合）——支持自动降级。当外部 Embedding 服务不可用时，系统自动回退到关键词搜索，并在发生降级时于响应中报告 `degrade_reasons`。

Embedding 维度不匹配的检查现在会跟着**当前查询作用域**走（例如 `domain`、`path_prefix` 这类过滤条件），不会再因为别的无关 domain 里残留的旧向量把当前查询误降级。如果当前作用域里的向量确实和现配置不一致，`degrade_reasons` 会明确提示需要重建索引。

`candidate_multiplier` 现在仍然只是“第一轮扩候选池”的提示值，不是无限放大开关。当前实现会继续保留硬上限，对外返回会暴露实际生效的 `candidate_multiplier_applied`，而 backend metadata 里仍会保留 `candidate_limit_applied` 这条硬上限信息。

搜索结果最后一轮的“当前状态复核”现在也会优先走批量 path 查询。说人话就是：结果一多时，后端不再为了确认每一条 path 还在不在，就一条一条往 SQLite 来回跑。

### 🧠 意图感知搜索

搜索引擎默认按四类核心意图路由——**factual（事实型）**、**exploratory（探索型）**、**temporal（时间型）**、**causal（因果型）**——并匹配对应策略模板（`factual_high_precision`、`exploratory_high_recall`、`temporal_time_filtered`、`causal_wide_pool`）；当无显著信号时默认 `factual_high_precision`，当信号冲突或低信号混合时回退为 `unknown`（模板 `default`）。说人话就是：`why ... after ...` 这类查询，如果 `after/before` 只是描述触发事件，仍会按 **causal** 处理；只有遇到 `when`、`timeline`、`yesterday` 这类更强的时间锚点时，才继续保守回退到 `unknown`。

### ♻️ 记忆治理循环

记忆是有生命力的实体，拥有随时间衰减的 **活力值（vitality score）**。治理循环涵盖：审查与回滚、孤儿清理、活力衰减、睡眠整合（自动碎片清理）。

### 🌐 多客户端 MCP 集成

一套协议，多端接入：当前公开文档把 **CLI 客户端** 和 **IDE 宿主** 分开说明。`Claude Code / Codex / Gemini CLI / OpenCode` 走技能文档里的 CLI 路径；`Cursor / Windsurf / VSCode-host / Antigravity` 走 repo-local 规则文件加 MCP 配置片段。

### 📦 灵活部署

四种部署档位（A/B/C/D），从纯本地到云端连接，支持 Docker 部署和一键脚本。当前最完整的大链路验证仍是 `macOS + Docker`；原生 Windows 现在已有通过 `backend/mcp_wrapper.py` 的 repo-local stdio 路径，但远程场景和 GUI 宿主组合仍建议按目标环境再复核一次。

如果你走的是仓库自带的 Docker / GHCR compose 路径，compose 现在会默认在仓库的 **named volume 默认部署路径** 上强制打开 WAL，减少共享 SQLite 数据卷上的 `database is locked` 这类并发写冲突。但这个默认值**不适用于**把 `/app/data` 改成 NFS/CIFS/SMB 之类网络文件系统 bind mount 的场景；如果你这么改，必须显式切回 `MEMORY_PALACE_DOCKER_WAL_ENABLED=false` 和 `MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete`。repo-local 的 `docker_one_click.sh/.ps1` 现在会在检测到这类高风险组合时直接 fail-fast；手动 `docker compose up` 仍然属于你自己负责预检查的路径。

### 📊 内置可观测性仪表盘

基于 React 的四视图仪表盘：**记忆浏览器**、**审查与回滚**、**维护管理**、**可观测性监控**。

当前前端会先恢复已保存的语言选择；如果浏览器里还没有保存值，常见中文浏览器语言（例如 `zh`、`zh-TW`、`zh-HK` 和其他 `zh-*`）会统一归并到 `zh-CN`，其他首次访问场景则回退到英文。你仍然可以点右上角语言按钮切换中英文，浏览器会记住你的选择，常见界面文案、日期/数字格式和一部分错误提示也会跟随切换，其中也包括后端返回的结构化校验错误。

如果你用 Microsoft Edge 打开 Dashboard，前端现在会自动切到更轻量的视觉模式。说人话就是：页面还是同一套功能、鉴权/配置向导入口和数据请求链路，但会把动画背景、blur 和一部分卡片动效收一点，优先减少本地卡顿。其他浏览器仍然保持常规视觉效果。

Observability 搜索和活力清理确认这类更容易跑久一点的操作，现在前端也会给更长的等待时间。对本地数据量更大的场景来说，这样更不容易出现“后端还在处理，浏览器先报超时”的错觉。

当浏览器里既没有已保存的 Dashboard 鉴权，也没有运行时注入的 Dashboard 鉴权时，前端会自动打开首启配置向导。它可以把 Dashboard `MCP_API_KEY` 保存到当前浏览器会话里，并且在应用直接连本地 checkout 时，把常见本地运行参数写进 `.env`，不需要手动编辑文件。这条写入路径现在只会指向当前项目里的 `.env*` 文件。现在向导里也会把 `Profile A` 直接标出来，不再让它只作为空表单的隐含默认态；这条默认基线仍然就是 `keyword + none`。如果你走的是“保存到本地 `.env`”这条路径，第一次本地保存现在还要求 `Dashboard API key` 不能为空；留空时，后端会直接拒绝这次写入，而不会当成匿名自举。如果这次第一次保存里已经同时打开了远端 embedding/reranker 或 LLM provider 链，而当前还没有任何 Dashboard 鉴权配置，后端会先把这一步收敛成 auth bootstrap，只写 `MCP_API_KEY` / `MCP_API_KEY_ALLOW_INSECURE_LOCAL`；provider 链字段要等下一次带鉴权的保存再真正写进去。如果你走的是“保存到本地 `.env`”这条路径，并且同时填写了 Dashboard key，向导仍然需要浏览器会话存储来记住这把 key；如果浏览器拦住了这条存储路径，页面现在会明确提示保存失败，不再假装整套配置都已经成功。对带鉴权的非 loopback 请求，向导现在仍可显示当前 setup 状态，但本地 `.env` 写入会继续保持禁用，并明确提示原因。这条路径仍然只允许直连回环地址；如果后端已经带着 `MCP_API_KEY` 在跑，那么即使是 loopback 写入，也还要带上同一把有效 key。向导还会自动归一化 `/embeddings`、`/rerank`、`/chat/completions` 这类常见 provider API 后缀；格式不对或指到 link-local 的地址会在写入前直接拦下。像 `127.0.0.1` / `::1` 这类 loopback IP 字面量，再加上 `localhost`，仍然默认允许；如果你故意把 provider base 直连到其它 private IP 字面量，或者直连到一个解析后会落到 private 非 loopback 地址的 hostname，现在还要先通过 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` 显式放行。涉及后端运行链路的改动仍然需要重启服务。

如果你想看一份按页面拆开的使用说明，可以直接打开 [中文仪表盘使用指南](docs/DASHBOARD_GUIDE_CN.md)。

---

## 🏗️ 系统架构

<p align="center">
  <img src="docs/images/系统架构图.png" width="900" alt="Memory Palace 系统架构" />
</p>

```
┌─────────────────────────────────────────────────────────────┐
│                    用户 / AI Agent                          │
│       (Codex · Claude Code · Gemini CLI · OpenCode)         │
└──────────────┬──────────────────────┬───────────────────────┘
               │                      │
    ┌──────────▼──────────┐  ┌────────▼─────────┐
    │  🖥️ React 仪表盘     │  │  🔌 MCP Server    │
    │  (记忆 / 审查 /       │  │  (9 工具 + SSE)   │
    │   维护 / 可观测性)    │  │                   │
    └──────────┬──────────┘  └────────┬──────────┘
               │                      │
               └──────────┬───────────┘
                          │
                ┌─────────▼──────────┐
                │  ⚡ FastAPI 后端    │
                │  (异步 IO)         │
                └───┬────────────┬───┘
                    │            │
          ┌─────────▼──┐  ┌─────▼───────────┐
          │ 🛡️ Write    │  │ 🔍 搜索 &        │
          │   Guard     │  │   检索引擎       │
          └─────┬──────┘  └─────┬────────────┘
                │               │
          ┌─────▼──────┐  ┌─────▼───────────┐
          │ 📝 Write    │  │ ⚙️ Index Worker  │
          │   Lane      │  │   (异步队列)     │
          └─────┬──────┘  └─────┬────────────┘
                │               │
                └───────┬───────┘
                        │
                ┌───────▼────────┐
                │ 🗄️ SQLite 数据库│
                │ (单文件存储)    │
                └────────────────┘
```

---

## 🛠️ 技术栈

### 后端

| 组件 | 技术 | 版本 | 用途 |
|---|---|---|---|
| Web 框架 | [FastAPI](https://fastapi.tiangolo.com/) | ≥ 0.109 | 异步 REST API，自动生成 OpenAPI 文档 |
| ORM | [SQLAlchemy](https://www.sqlalchemy.org/) | ≥ 2.0 | 异步 ORM 与查询层；Schema 变更由仓库内 migration runner 负责 |
| 数据库 | [SQLite](https://www.sqlite.org/) + aiosqlite | ≥ 0.19 | 零配置嵌入式数据库，单文件、便携 |
| MCP 协议 | `mcp (FastMCP)` | ≥ 0.1 | 通过 stdio / SSE 传输暴露 9 个标准化工具 |
| HTTP 客户端 | [httpx](https://www.python-httpx.org/) | ≥ 0.26 | 异步 HTTP，用于 Embedding / Reranker API 调用 |
| 数据校验 | [Pydantic](https://docs.pydantic.dev/) | ≥ 2.5 | 请求/响应校验 |
| 差异引擎 | `diff_match_patch` + `difflib` fallback | — | 优先使用 `diff_match_patch` 生成语义化 diff；如果这个可选包缺失，就自动退回到 `difflib.HtmlDiff` 表格 diff，而不会阻塞后端启动 |

### 前端

| 组件 | 技术 | 版本 | 用途 |
|---|---|---|---|
| UI 框架 | [React](https://react.dev/) | 18 | 组件化仪表盘 UI |
| 构建工具 | [Vite](https://vitejs.dev/) | 7.x | 极速 HMR 开发和优化构建 |
| 样式 | [Tailwind CSS](https://tailwindcss.com/) | 3.x | 原子化 CSS 框架 |
| 动画 | [Framer Motion](https://www.framer.com/motion/) | 12.x | 流畅页面转场和微交互 |
| 路由 | React Router DOM | 6.x | 客户端路由，支撑四大视图 |
| API 客户端 | [Axios](https://axios-http.com/) | 1.x | 仪表盘 API 请求与鉴权头注入 |
| Markdown | react-markdown + remark-gfm | — | 预留给可选的 Markdown 渲染链路；当前仪表盘里的记忆正文仍以纯文本方式展示 |
| 图标 | [Lucide React](https://lucide.dev/) | — | 统一图标体系 |

### 各层实现详解

#### 写入流水线（`mcp_server.py` → `runtime_state.py` → `sqlite_client.py`）

1. **Write Guard（写入守卫）** — 每次 `create_memory` / `update_memory` 调用都先经过 Write Guard（`sqlite_client.py`）。在规则模式下，守卫以 **语义匹配 → 关键词匹配 → LLM（可选）** 的顺序判定核心动作 `ADD`、`UPDATE`、`NOOP`、`DELETE`；`BYPASS` 由上层流程在 metadata-only 更新场景标注。当设置 `WRITE_GUARD_LLM_ENABLED=true` 时，可选 LLM 通过 OpenAI 兼容 API 参与决策。

2. **Snapshot（快照）** — 在任何修改前，系统都会先记录当前记忆状态的快照。MCP 工具链路使用 `mcp_server.py` 中的快照 helper；Dashboard 的 `/browse/node` 写入也遵循同样的 path/content 快照语义，并按当前数据库作用域写入到 dashboard 专属 session。同一个 session 的快照写路径现在会通过每个 session 一把文件锁做串行化，`manifest.json` 和单个快照 JSON 文件也会通过原子替换方式写入，所以本地多进程共用同一个 checkout 时，不容易丢 Review 条目或留下半写入的快照文件。这样 Review 仪表盘里的差异对比和一键回滚才能正常工作。

3. **Write Lane（写入车道）** — 写入进入序列化队列（`runtime_state.py` → `WriteLanes`），可配置并发度（`RUNTIME_WRITE_GLOBAL_CONCURRENCY`）。这防止了单 SQLite 文件上的竞态条件；遇到短暂的 SQLite 锁冲突时，也会先做一次小范围重试，而不是立刻把它当成硬失败抛出去。

4. **Index Worker（索引工作者）** — 每次写入完成后，异步任务入队进行索引重建（`runtime_state.py` 中的 `IndexWorker`）。工作者仍按 FIFO 顺序处理索引更新，但真正写库的那一步现在也会经过同一条 write lane，所以后台重建和前台写入更不容易互相争抢。

#### 检索流水线（`sqlite_client.py`）

1. **查询预处理** — `preprocess_query()` 对搜索查询进行规范化和分词。
2. **意图分类** — `classify_intent()` 使用关键词评分方法（`keyword_scoring_v2`）判定意图：默认为 `factual`、`exploratory`、`temporal`、`causal` 四类；无显著关键词信号时默认 `factual`（`factual_high_precision`）；信号冲突或低信号混合时回退 `unknown`（模板 `default`）。现在对因果/时间混合查询会更稳一些：`why ... after/before ...` 如果时间词只是弱连接词，仍走 **causal**；如果同时出现 `when`、`timeline`、`yesterday` 这类更强的时间锚点，才继续保守回退。
3. **策略匹配** — 根据意图匹配策略模板（如 `factual_high_precision` 使用更严格的匹配；`temporal_time_filtered` 添加时间范围约束）。
4. **多阶段检索** — 按档位执行：
   - **档位 A**：纯关键词匹配，基于 SQLite FTS
   - **档位 B**：关键词 + 本地哈希 Embedding 混合评分
   - **仓库自带的档位 C/D 模板**：关键词 + 外部 Embedding + Reranker 链路（OpenAI 兼容，通常走 router 路径）
   - **real benchmark helper 专用语义**：`profile_c` 只跑 API Embedding，不带 Reranker；`profile_d` 才再加上 Reranker。helper 里的这组 C/D 标签是 benchmark 合约，不等于仓库自带 deploy 模板。
5. **结果组装** — 结果包含 `degrade_reasons` 字段，当任何阶段失败时调用方始终了解检索质量。

#### 记忆治理（`sqlite_client.py` → `runtime_state.py`）

- **活力衰减** — 每条记忆有活力值（最大 `3.0`，可配置）。活力按指数衰减，半衰期 `VITALITY_DECAY_HALF_LIFE_DAYS=30`。低于 `VITALITY_CLEANUP_THRESHOLD=0.35` 超过 `VITALITY_CLEANUP_INACTIVE_DAYS=14` 天的记忆被标记清理。
- **睡眠整合** — 带整合参数的 `rebuild_index` 将碎片化的小记忆合并为连贯摘要。
- **孤儿清理** — 定期扫描识别没有有效记忆引用的路径。

---

## 📁 项目结构

```
memory-palace/
├── backend/
│   ├── main.py                 # FastAPI 入口；注册 Review/Browse/Maintenance/Setup 路由
│   ├── mcp_server.py           # MCP 公开入口；9 个工具签名保持兼容
│   ├── runtime_state.py        # Write Lane 队列、Index Worker、活力衰减调度器
│   ├── run_sse.py              # SSE 传输层，带 API Key 鉴权网关
│   ├── requirements.txt        # 后端运行依赖
│   ├── requirements-dev.txt    # 后端测试依赖
│   ├── db/
│   │   ├── sqlite_client.py    # 兼容外观层：CRUD、检索、Write Guard、Gist
│   │   ├── models.py           # SQLAlchemy 模型
│   │   ├── repositories/       # 数据访问拆分模块
│   │   └── search/             # FTS5/vector/RRF/entity boost 通道
│   ├── core/                   # MemoryCore 外观、层级/遗忘/压缩/程序性记忆引擎
│   ├── api/                    # REST 路由：review、browse、maintenance、setup、layering、forgetting、search quality
│   ├── mcp/                    # 工具 re-export wrapper、system 视图、host adapter
│   ├── security/               # 输入清洗与 opt-in artifact stripping
├── frontend/
│   └── src/
│       ├── App.jsx             # 路由与页面脚手架
│       ├── features/
│       │   ├── memory/         # MemoryBrowser.jsx + LayerHierarchyPanel.jsx
│       │   ├── review/         # ReviewPage.jsx — 差异对比、回滚、整合
│       │   ├── maintenance/    # MaintenancePage.jsx + ForgettingPanel.jsx
│       │   └── observability/  # ObservabilityPage.jsx + SearchQualityPanel.jsx
│       └── lib/
│           └── api.js          # 统一 API 客户端，运行时注入鉴权信息
├── deploy/
│   ├── profiles/               # A/B/C/D 档位模板（macOS/Linux/Windows/Docker）
│   └── docker/                 # Dockerfile 和 Compose 辅助配置
├── scripts/
│   ├── apply_profile.sh        # macOS/Linux 档位应用脚本
│   ├── apply_profile.ps1       # Windows 档位应用脚本
│   ├── backup_memory.sh        # macOS/Linux SQLite 一致性备份
│   ├── backup_memory.ps1       # Windows SQLite 一致性备份
│   ├── docker_one_click.sh     # macOS/Linux 一键 Docker 部署
│   ├── docker_one_click.ps1    # Windows 一键 Docker 部署
│   └── pre_publish_check.sh    # 分享前本地产物 / 泄露扫描
├── docs/                       # 完整文档集
├── .env.example                # 配置模板（含详细注释）
├── docker-compose.yml          # Docker Compose 定义
└── LICENSE                     # MIT 许可证
```

---

## 📋 环境要求

| 组件 | 最低版本 | 推荐版本 |
|---|---|---|
| Python | 3.10+ | 3.11+ |
| Node.js | 20.19+（或 >=22.12） | 最新 LTS |
| npm | 9+ | 最新稳定版 |
| Docker（可选） | 20+ | 最新稳定版 |

---

## 🚀 快速开始

### 方式一：直接拉取预构建 Docker 镜像（最省事的用户路径）

如果你本地构建环境总是出问题，先走 GHCR 预构建镜像这条路。这条路径的目标是**先把服务跑起来**，不是在你本机重新 build 镜像。

```bash
git clone https://github.com/AGI-is-going-to-arrive/Memory-Palace.git
cd Memory-Palace

bash scripts/apply_profile.sh docker b .env.docker

docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

`apply_profile` 会从仓库模板生成 `.env.docker`，并在覆盖已有目标前先备份，所以不要先手动把 `.env.example` 复制到 `.env.docker`。

```powershell
git clone https://github.com/AGI-is-going-to-arrive/Memory-Palace.git
cd Memory-Palace

.\scripts\apply_profile.ps1 -Platform docker -Profile b -Target .env.docker

docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

默认访问地址：

| 服务 | 地址 |
|---|---|
| 前端仪表盘 | <http://127.0.0.1:3000> |
| 后端 API | <http://127.0.0.1:18000> |
| SSE | <http://127.0.0.1:3000/sse> |

先记住几个边界：

- 这条路径绕开的是**本地镜像构建**，不是“完全不需要仓库 checkout”。你仍然需要仓库里的 `docker-compose.ghcr.yml`、`.env.example` 和 profile 脚本。
- 这条路径解决的是 **Dashboard / API / SSE 服务启动**。
- 它**不会**自动把 `Claude / Codex / Gemini / OpenCode / Cursor / Antigravity` 这些客户端在你机器上的 skill / MCP 配置一起改好。
- 如果你还想用当前仓库现成的 repo-local skill + MCP 自动化安装链路，保留这个 checkout，再继续看 [docs/skills/GETTING_STARTED.md](docs/skills/GETTING_STARTED.md)。
- 如果你不走 repo-local 安装链路，也可以手工把支持远程 SSE 的 MCP 客户端指到 `http://localhost:3000/sse`，并配置同一把 API key / 鉴权头。这里的 `<YOUR_MCP_API_KEY>` 默认就读刚生成的 `.env.docker` 里的 `MCP_API_KEY`。
- 仓库自带的 compose 文件在卷名默认值上使用了嵌套 `${...:-...}`。如果你本机的 Compose 实现较旧，或仍在用经典 `docker-compose`，这条手动路径可能会在 `docker compose up` 前就解析失败。遇到这种情况，优先改走 `docker_one_click.sh/.ps1`，或先显式设置 `MEMORY_PALACE_DATA_VOLUME` / `MEMORY_PALACE_SNAPSHOTS_VOLUME` / `COMPOSE_PROJECT_NAME`。
- `scripts/run_memory_palace_mcp_stdio.sh` 不是 Docker 客户端入口。它依赖本地 `bash` 和 `backend/.venv`，只会复用宿主机上的本地 `.env` / `DATABASE_URL`，不会复用容器里的 `/app/data`。
- 如果你后面要切回本机 `stdio` 客户端，本地 `.env` 必须写宿主机可访问的绝对路径。仓库里只有 `.env.docker` 而没有本地 `.env` 时，它会明确拒绝回退到 `demo.db`；如果 `.env` 或显式 `DATABASE_URL` 仍写成 `/app/...` 或 `/data/...` 这类容器路径，它也会直接拒绝启动，并提示你改成本机路径或走 Docker 暴露的 `/sse`。
- 和 `docker_one_click.sh/.ps1` 不同，GHCR compose 路径**不会自动换端口**。如果 `3000` / `18000` 已被占用，请在启动前自己设置 `MEMORY_PALACE_FRONTEND_PORT` / `MEMORY_PALACE_BACKEND_PORT`。
- 如果容器需要访问你宿主机上的本地模型服务，优先使用 `host.docker.internal`。当前 compose 已显式补 `host.docker.internal:host-gateway`，Linux Docker 也可以沿这条路径访问宿主机服务。对 one-click 的 `profile c/d + --allow-runtime-env-injection` 路径来说，当前 shell 里的 loopback provider base 现在会自动改成 `host.docker.internal`；但如果你绕过 one-click，自己准备最终 Docker env，还是要手动写成容器可达地址。

停止服务：

```bash
docker compose -f docker-compose.ghcr.yml down --remove-orphans
```

### 方式二：手动本地搭建（推荐新手使用）

> **💡 提示**：本教程推荐你先以 **档位 B** 为目标，这样可以在**零外部模型服务**的前提下跑通全流程。
> 如果你希望日常使用时拿到更好的检索效果，**强烈建议后续升级到档位 C**；但请先按 [升级到档位 C/D](#-升级到档位-cd) 中的说明补齐 embedding / reranker / LLM 对应配置。

#### 第 1 步：克隆仓库

```bash
git clone https://github.com/AGI-is-going-to-arrive/Memory-Palace.git
cd Memory-Palace
```

#### 第 2 步：创建配置文件

选择以下 **任一** 方法：

**方法 A — 复制模板手动编辑：**

```bash
cp .env.example .env
```

> 这条路径用的是**更保守的 `.env.example` 最小模板**。它足够你先把本地服务跑起来，但**不等于已经套用了仓库里的档位 B 模板**。
>
> 如果你想直接拿到仓库预设好的档位 B 默认值（例如本地 hash Embedding），请直接使用下面的**方法 B**。如果你继续走方法 A 也没问题，就把它理解成“从最小模板手动往上补配置”即可。

然后打开 `.env`，将 `DATABASE_URL` 设置为你机器上的实际路径。共享环境或接近生产的场景更推荐使用绝对路径：

```bash
# macOS / Linux 示例：
DATABASE_URL=sqlite+aiosqlite:////absolute/path/to/demo.db

# Windows 示例：
DATABASE_URL=sqlite+aiosqlite:///C:/absolute/path/to/demo.db
```

> 不要把 Docker / GHCR 路径里的 `sqlite+aiosqlite:////app/data/...`，或任何 `/data/...` 这类容器内 sqlite 路径，直接写进本地 `.env`。`/app/...`、`/data/...` 都是容器内路径，不是你宿主机上的真实文件路径；像 `sqlite+aiosqlite:///demo.db` 这种相对 sqlite 路径，或 `sqlite+aiosqlite:////%2Fapp%2Fdata/...` 这种把容器路径做了 URL 编码的写法，本地 repo-local `stdio` wrapper 现在也会一并拒绝。本地 `stdio` 请改成宿主机绝对路径；如果你就是要复用 Docker 那边的数据和服务，请直接改连 Docker 暴露的 `/sse`。

如果你想立刻在本地使用 Dashboard，或者直接调用 `/browse` / `/review` / `/maintenance`，请先把下面二选一写进 `.env`，再启动后端：

```dotenv
# 方式 A：设置一把本地 API Key（推荐）
MCP_API_KEY=change-this-local-key

# 方式 B：仅限本机回环调试时跳过鉴权（不要用于共享环境）
MCP_API_KEY_ALLOW_INSECURE_LOCAL=true
```

**方法 B — 使用档位脚本（推荐）：**

```bash
# macOS
bash scripts/apply_profile.sh macos b

# Linux
bash scripts/apply_profile.sh linux b

# Windows PowerShell
.\scripts\apply_profile.ps1 -Platform windows -Profile b
```

脚本会根据平台从 `deploy/profiles/{macos,linux,windows,docker}/profile-b.env` 模板生成一份 **基于档位 B 的环境文件**。本地 shell 路径（`macos` / `linux`）和原生 `windows` 默认目标仍是 `.env`；如果你跑的是 `docker` 变体且没有显式传目标文件，`apply_profile.sh/.ps1` 现在会默认写到 `.env.docker`。

如果当前机器没装 `pwsh`，但已经有 Docker，也可以直接运行 `bash scripts/smoke_apply_profile_ps1_in_docker.sh`，对 `apply_profile.ps1` 做一轮 repo-local smoke。

把 `deploy/profiles/*/*.env` 理解成 **Profile 模板输入**，不要直接手抄某个模板文件当成最终 `.env`。有些模板值会先保留占位路径，再由 `apply_profile.*` 按当前仓库位置自动改写。

对于 `profile c/d`，`apply_profile.sh/.ps1` 现在也会对未替换的 endpoint / key / model 占位值直接 fail-closed。简单说：先把示例里的 `PORT`、key 和 model id 换成真实值，再继续走 Docker 启动或本地 C/D 调试。

`DATABASE_URL` 现在也走同样的保护逻辑。对本地 shell 路径，`apply_profile.sh` 会先按当前 checkout 自动改写常见占位路径，包括 `/Users/...` 和 `/home/...`；如果生成结果里还残留 `<...>` 或 `__REPLACE_ME__` 这类占位段，脚本或后端都会直接拦下，不再静默带着一条坏的 sqlite 路径继续往后跑。

后端现在也会对**当前实际启用的远端检索配置**做同样的 fail-closed 检查。如果你绕过 `apply_profile.*`，直接手工复制了 C/D 模板，并且还保留着 `host.docker.internal:PORT`、`replace-with-your-key`、`your-embedding-model-id`、`your-reranker-model-id` 这类示例值，启动会直接报错，而不是带着一份明显无效的 provider 配置继续运行。

在 macOS / Linux 上，`apply_profile.sh` 现在还会在覆盖已有目标文件前先备份一份 `*.bak`。如果另一份 `apply_profile.sh` 正在写同一个目标文件，后来的进程会直接提示你稍后重试，而不是两边互相覆盖。它生成 staged / update 临时文件时，也会放到目标文件同目录，而不是统一丢到共享 `/tmp`，这样自定义目标路径时更不容易撞上跨文件系统替换的坑。

原生 Windows PowerShell 现在也补齐了同一套操作习惯。简单说：`apply_profile.ps1` 现在也会在覆盖前先备份 `*.bak`，如果另一份 `apply_profile.ps1` 正在写同一个目标文件，也会直接拒绝第二个写入，并且 staged 临时文件同样放在目标文件所在目录，而不是默认共享临时目录。如果你只是想先看看最终会生成什么内容，可以用 `bash scripts/apply_profile.sh --dry-run ...`，或者在 PowerShell 下用 `.\scripts\apply_profile.ps1 -Platform windows -Profile b -DryRun`；这两条路径都只打印最终结果，不会真正改目标文件。如果你只是想先看 PowerShell 脚本用法，可以直接运行 `.\scripts\apply_profile.ps1 -Help`。

如果你前面已经生成过 `.env.docker`，也不要直接把那份 Docker 文件改名成 `.env`。Docker profile 里的 `/app/data/...` 这类容器路径只对容器有效；如果你自己把挂载点改成 `/data/...`，本机 `stdio` MCP 也一样不能直接拿来用，还是需要宿主机自己的绝对路径。

但要注意：

- **macOS / Windows 本地启动**时，脚本**不会**自动帮你填 `MCP_API_KEY`
- 如果你想立刻用 Dashboard、`/browse` / `/review` / `/maintenance`，或者 `/sse` / `/messages`，还需要自己再补一项：
  - `MCP_API_KEY=change-this-local-key`
  - 或 `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`（仅限你自己机器上的回环调试）
- 只有 **docker 平台**下，`apply_profile` 才会在 `MCP_API_KEY` 为空时自动生成一把本地 key

#### 第 3 步：启动后端

```bash
cd backend

# 创建并激活虚拟环境
python -m venv .venv
source .venv/bin/activate        # Windows PowerShell：.\.venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt

# 如果你后面还要跑后端测试
# pip install -r requirements-dev.txt

# 启动 API 服务器
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

正常情况下你会看到：

```
Memory API starting...
SQLite database initialized.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

> 上面这条 `uvicorn main:app --host 127.0.0.1 ...` 是推荐的**本机开发**写法。
>
> 如果你机器上的 Python 命令名是 `python3` 而不是 `python`，把上面命令里的 `python` 换成 `python3` 即可。
>
> 如果你改为直接运行 `python main.py`，当前默认也是绑定 `127.0.0.1:8000`，不会自动放开到 `0.0.0.0`。只有在你明确需要远程访问时，才手动改成 `0.0.0.0`（或你的实际绑定地址），并补齐 `MCP_API_KEY`、防火墙、反向代理或其他网络侧保护。

#### 第 4 步：启动前端

打开一个 **新的终端窗口**：

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

正常情况下你会看到：

```
  VITE v7.x.x  ready

  ➜  Local:   http://localhost:5173/
```

#### 第 5 步：验证安装

```bash
# 检查后端健康状态
curl -s http://127.0.0.1:8000/health | python -m json.tool

# 浏览记忆树
#
# 方式 A：如果你配置了 `MCP_API_KEY`
curl -s "http://127.0.0.1:8000/browse/node?domain=core&path=" \
  -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>" | python -m json.tool

# 方式 B：如果你启用了 `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`
curl -s "http://127.0.0.1:8000/browse/node?domain=core&path=" | python -m json.tool
```

在浏览器中打开 **<http://localhost:5173>** —— 你应该能看到 Memory Palace 仪表盘 🎉

> 如果本地手动启动后右上角出现 `设置 API 密钥`（英文模式下会显示 `Set API key`），这是正常现象。说明前端页面已经起来了，但受保护的数据请求（`/browse/*`、`/review/*`、`/maintenance/*`）仍然遵循 `MCP_API_KEY` / `MCP_API_KEY_ALLOW_INSECURE_LOCAL` 的鉴权规则。独立的 MCP SSE 端点（`/sse`、`/messages`）也遵循同一规则。
>
> 如果你配置了 `MCP_API_KEY`，打开页面后请点右上角 `设置 API 密钥`（英文模式下会显示 `Set API key`）打开首启向导；你可以只把同一把 key 保存到当前浏览器会话，也可以在“本地 checkout + 非 Docker 运行”的场景下，把常见运行参数一起写进 `.env`。这条本地写入路径现在只会写当前项目里的 `.env*` 文件。如果你启用了 `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`，直连本机回环地址（`127.0.0.1` / `::1` / `localhost`，且不带 forwarded headers）的请求可直接访问这些受保护数据请求，但这条“免手动输 key”的 loopback 读放宽并不会放开本地 `.env` 写入门槛。如果你是通过带鉴权的非 loopback 路径看的页面，向导仍然能显示当前状态，但本地 `.env` 写入会继续保持禁用，这是现在明确写死的安全边界。如果后端已经带着 `MCP_API_KEY` 在跑，那么即使是这条 loopback 写入路径，也还要带上同一把有效 key。
>
> 如果你选择的是“只保存 Dashboard 密钥”，这把 key 会保存在当前浏览器会话里（`sessionStorage`），直到你手动清除或这次浏览器会话结束。当前端发现旧版遗留在 `localStorage` 里的 Dashboard key 时，仍然只会迁移一次，但现在只有在确认没有被别的标签页替换掉时，才会删除那份旧值。现在就算 setup 状态回来的比较晚，没碰过的检索字段也会按真实状态补齐；先输入 Dashboard key，不会再把已有的 router / reranker 配置偷偷重置回 `hash` / `false`。浏览器侧这把 Dashboard 鉴权如果被你改掉、清掉，或被别的标签页同步进来，前端现在也会额外发出 maintenance-auth 变更事件；Observability 会利用这条事件，再加上重新聚焦标签页时的检查，在鉴权变更后或终态 `401` 之后重建带鉴权的 `/sse` 连接。向导里的“档位 C/D”预设（英文界面显示为 `Profile C/D`）现在已经按文档口径走 `router + reranker` 路线；但只靠预设本身已经不能直接保存了，真正落地前仍要把必填远端字段换成真实值。像 `http://127.0.0.1:8001/v1` 这种真实本地 router 地址仍然可以用，但示例 model id 仍然会被当成占位值拦下。对直连 `api` / `openai` embedding 路径来说，现在本地 `.env` 保存前还会继续要求一个真实的正整数维度。`/embeddings`、`/rerank`、`/chat/completions` 这类常见 API 后缀会自动归一化；格式不对或指到 link-local 的 provider base 会在保存前直接拦下。像 `127.0.0.1` / `::1` 这类 loopback IP 字面量，再加上 `localhost`，仍然默认允许；如果你本机确实要直连其它 private IP 字面量，或者指到一个解析后会落到 private 非 loopback 地址的 hostname，还要额外补上 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS`。如果你本机的 router 还没准备好，就手动把检索字段切回直连 `api` / `openai` 模式排障。
>
> 如果你选择的是“保存到本地 `.env`”，并且同时填了 Dashboard key，要记住 `.env` 写入和浏览器 key 持久化是两步。现在只要浏览器本地存储失败，向导就会直接报保存失败，不再给出误导性的成功提示。实际使用时，这通常意味着 `.env` 可能已经写进去了，但浏览器侧鉴权还没准备好；先看右上角状态，再决定是否重试。
>
> 这个向导不会假装自己能热更新 Docker 容器里的 env / 代理配置。只要涉及 embedding / reranker / write_guard / intent 这类后端侧参数，保存之后仍然需要按实际部署方式重启对应服务。

#### 第 6 步：连接 AI 客户端

启动 MCP 服务器以便 AI 客户端访问 Memory Palace：

```bash
cd backend

# stdio 模式（用于常见 stdio 客户端，如 Claude Code / Codex / OpenCode）
python mcp_server.py

# 如果你是在新终端或客户端配置里启动，下面这条更稳
./.venv/bin/python mcp_server.py   # Windows PowerShell：.\.venv\Scripts\python.exe mcp_server.py

# SSE 模式（下面这个命令是本机回环示例；远程访问请改 HOST）
HOST=127.0.0.1 PORT=8010 python run_sse.py
```

```powershell
cd backend
$env:HOST = "127.0.0.1"
$env:PORT = "8010"
python run_sse.py
```

> 说明：`stdio` 直接连接 MCP 工具进程，不经过 HTTP/SSE 鉴权中间层；未设置 `MCP_API_KEY` 时也可本地使用 MCP 工具。这里说的是 `stdio` 本身，不包括受保护的 HTTP / SSE 路由。
>
> 上面这条 `python mcp_server.py` 默认你还在使用刚才安装依赖的那个 `backend/.venv`。如果你换了一个新终端，或者是在 Claude Code / Codex / OpenCode 这类客户端里配置本地 MCP，优先直接指向项目自己的 `.venv`。否则很容易因为解释器不对，在启动前就报 `ModuleNotFoundError: No module named 'sqlalchemy'`。
>
> 如果你要把 MCP 接到客户端配置里，先按本机 shell 边界选 launcher：
>
> - 原生 Windows：优先 `backend/mcp_wrapper.py`
> - macOS / Linux / Git Bash / WSL：优先 `scripts/run_memory_palace_mcp_stdio.sh`
>
> 这两条 launcher 都会优先复用当前仓库的 `backend/.venv` 和 `.env` / `DATABASE_URL`；如果 `.env` 里已经设置了 `RETRIEVAL_REMOTE_TIMEOUT_SEC`，它们也会继续复用这个值；没设置时 repo-local 默认仍是 `8` 秒。只有在仓库里既没有本地 `.env`、也没有 `.env.docker` 时，才会回退到仓库默认 SQLite 路径。若仓库里只有 `.env.docker`，或者本地 `.env` 里的 `DATABASE_URL` 仍写成 Docker 容器内路径（例如 `sqlite+aiosqlite:////app/data/memory_palace.db`、`sqlite+aiosqlite://///app/data/memory_palace.db`、大写 `/APP/...` 变体、你自己改成 `/data/...` 的变体，或 `sqlite+aiosqlite:////%2Fapp%2Fdata/...` 这种 URL 编码变体），它都会明确拒绝启动，并提示你改走 Docker 暴露的 `/sse` 或改回宿主机绝对路径。像 `sqlite+aiosqlite:///demo.db` 这种相对 sqlite 路径，现在也不会再被放过。repo-local `stdio` wrapper 现在也不再只依赖 `python-dotenv` 才能读取 `.env`；如果本地启动仍然失败，更常见的原因已经变成 `.env` 内容或路径本身有问题，而不是少装了这个额外包。
>
> 对 shell wrapper 这条路径（`macOS / Linux / Git Bash / WSL`）来说，`run_memory_palace_mcp_stdio.sh` 现在还会在启动 Python 前先导出 `PYTHONIOENCODING=utf-8` 和 `PYTHONUTF8=1`。说人话就是：就算当前 shell 默认编码不太友好，本地 stdio 也更不容易因为编码问题变成乱码或直接报错。
>
> 现在仓库自带的两条 repo-local wrapper 都会把已有的 `NO_PROXY` / `no_proxy` 合并起来，并补上 `localhost`、`127.0.0.1`、`::1`、`host.docker.internal`。说人话就是：如果你本机还跑着 Ollama 或别的本地 OpenAI-compatible 服务，它们更不容易被宿主机代理误走。这条自动代理绕过只针对仓库自带的两条 repo-local wrapper，不等于所有后端启动方式都会默认带上同样的保护。
>
> 在原生 Windows 或其它更依赖 wrapper 的宿主路径里，repo-local stdio launcher 现在也会按块转发 stdin/stdout，而不是逐字节转发。说人话就是：遇到更大的 MCP 响应时，体感会比以前顺一些，但原来的 CRLF 清理规则不变。
>
> 再补一个边界细节：如果某个客户端 / IDE host 只是把 `DATABASE_URL` 传成了空字符串，但当前仓库 `.env` 里本来就有有效值，这两条 wrapper 仍会把这个运行时空值当成“没设置”，继续复用仓库 `.env`。但如果本地 `.env` 自己就存在，而且写成了 `DATABASE_URL=` 空值，wrapper 现在会直接 fail-closed，明确提示你先把本机配置改对再重试。
>
> 同样地，如果 `.env` 或你显式传入的 `DATABASE_URL` 在把常见斜杠和大小写变体归一化后，仍是 `/app/...` 或 `/data/...` 这类 Docker 容器路径，wrapper 现在也会直接拒绝启动。这不是 MCP 协议故障，而是本机路径配置错了；改成宿主机绝对路径，或者继续走 Docker `/sse`。
>
> 上面这个 `HOST=127.0.0.1` 是**只给本机访问**的写法；`python run_sse.py` 会优先尝试回环 `127.0.0.1:8000`，如果本机 `8000` 已被主后端占用，则自动回退到 `127.0.0.1:8010`。如果你显式绑定的是 `HOST=::1`，它会单独检查 `::1:8000`，不会因为 IPv4 的 `8000` 被占用就误回退。如果你绑定的是 `HOST=localhost`，探测逻辑现在会按当前主机实际可用的回环地址分别检查，不会再因为这台机器不支持 IPv6 localhost，就误以为 `8000` 已占用而直接回退到 `8010`。发生真正需要的回退时，当前启动日志还会明确打印最终 `/sse` 地址，并提醒你更新客户端配置或显式设置 `PORT`，所以更应该把它看成“客户端配置要跟着改”的提示，而不是静默故障。真要给远程客户端访问，请改成 `HOST=0.0.0.0`（或你的实际绑定地址）。这一步只是把监听范围放开，**不等于**跳过安全控制；API Key、防火墙、反向代理和传输安全仍然要自己补齐。如果你的远程 hostname / origin 还要通过 MCP 传输层的 host/origin 校验，也要再显式补上 `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS`，而不是把非回环监听误解成“默认放开全部来源”。

详细的客户端配置请参阅 [多客户端集成](#-多客户端集成)。

---

### 方式三：一键 Docker 部署

```bash
# macOS / Linux
bash scripts/docker_one_click.sh --profile b

# Windows PowerShell
.\scripts\docker_one_click.ps1 -Profile b

# 仅在需要时显式注入当前进程环境（默认关闭）
bash scripts/docker_one_click.sh --profile c --allow-runtime-env-injection
# 或
.\scripts\docker_one_click.ps1 -Profile c -AllowRuntimeEnvInjection
```

> Docker 一键部署会启动当前默认的双服务拓扑，并对外暴露三类入口：
>
> - Dashboard：`http://127.0.0.1:3000`
> - Backend API：`http://127.0.0.1:18000`
> - SSE：`http://127.0.0.1:3000/sse`
>
> 如果 Docker env 文件里的 `MCP_API_KEY` 为空，脚本会自动生成一把本地 key。前端会在代理层自动带上这把 key，所以按推荐的一键脚本路径启动时，**受保护请求通常已经能直接用**；但页面右上角仍可能继续显示 `设置 API 密钥`（英文模式下会显示 `Set API key`），因为浏览器页面本身并不知道代理层的真实 key。这不一定代表配置坏了；只有当受保护数据也一起报 `401` 或空态时，才需要继续排查 env / 代理配置。
>
> 客户端配置里仍然请把 `/sse` 当成规范公开入口来写。`/sse/` 现在只保留成兼容写法，也会转发到同一条后端 SSE 路径，所以新的示例和你自己的配置都继续写 `/sse` 即可。
>
> `docker_one_click.sh/.ps1` 默认本来就会给每次运行隔离一份 Docker env 文件。对 macOS / Linux 的 shell 路径来说，如果你显式把 `MEMORY_PALACE_DOCKER_ENV_FILE` 指到自己的自定义文件，`docker_one_click.sh` 现在也会在那个文件同目录生成临时文件再替换回去，减少目标文件不在默认临时目录时出现跨文件系统替换问题的概率。
>
> 也请把这个 Docker 前端端口当成可信操作员 / 管理入口。只要有人能直接访问 `http://<你的主机>:3000`，他就能使用 Dashboard 以及被代理的受保护接口，所以不要把这个端口当成“有 `MCP_API_KEY` 就等于终端用户鉴权”的公网入口；若要给受信范围之外的人访问，请先在前面加你自己的 VPN、反向代理鉴权或网络访问控制。
>
> WAL 安全边界：仓库默认仍假定 backend 数据库放在 Docker **named volume** 挂载的 `/app/data` 里。如果你有意把它替换成 NFS/CIFS/SMB 或其它网络文件系统 bind mount，就**不要继续开着 WAL**。`docker_one_click.sh/.ps1` 现在会在 `docker compose up` 前做预检查，一旦发现这类高风险组合就直接拒绝启动；如果你绕过一键脚本，自己手动跑 `docker compose up`，就需要自己遵守同一条规则。
>
> Windows 复核说明（2026 年 3 月 19 日）：这条 repo-local `docker compose -f docker-compose.yml` 路径，已经在原生 Windows 上重新做过端到端验证。`http://127.0.0.1:3000/sse` 会返回 `HTTP 200`，并给出 `/messages/?session_id=...`；`Claude` 和 `Gemini` 也都已经通过这个前端代理 SSE 入口完成过真实的 `read_memory(system://boot)` 调用。
>
> 现在 Docker 前端会先等 `backend` 的 `/health` 通过，同时一键脚本还会额外检查前端代理出来的 `/sse` 是否可达，才算真正 ready。backend 容器侧的检查也不再是“`/health` 只要回 `200` 就算好”，而是会继续确认返回 payload 里的 `status == "ok"`。容器刚起来时如果页面还没完全可用，先多等几秒，再按控制台打印出的地址重试即可。
>
> 运行时环境注入只给 `profile c/d` 使用。如果你把 `--allow-runtime-env-injection` / `-AllowRuntimeEnvInjection` 传给 `profile a/b`，脚本会在改动 Docker env 之前直接停止，因为这两个轻量档位应该保留文档里的默认设置。对 one-click 的 `profile c/d + --allow-runtime-env-injection` 路径来说，当前 shell 里传进来的 loopback provider base 会在生成的 Docker env 里自动改成 `host.docker.internal`。其它 non-loopback private provider 字面量地址仍然保持原值，但脚本会把它们的精确 host 追加进这次运行的 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS`，让 backend 继续按原来的 fail-closed 规则工作，而不是把一条本来可用的本地 private 目标误判成非法地址。
>
> 当前 Docker 前端还会对 `/index.html` 返回 `Cache-Control: no-store, no-cache, must-revalidate`，尽量减少“前端已经更新，但浏览器还拿着旧入口页面”的情况。如果你刚升级完镜像仍看到明显旧页面，先确认容器已经是新版本，再手动刷新一次页面；只有在你额外接了自己的反向代理或 CDN 时，才需要继续检查这些中间层是否改写了缓存头。
>
> Docker 默认还会分别持久化两类运行期数据：数据库卷会按 compose project 隔离为 `<compose-project>_data`（容器内 `/app/data`），snapshot 卷会隔离为 `<compose-project>_snapshots`（容器内 `/app/snapshots`）。如果你确实要复用旧的共享卷，请显式设置 `MEMORY_PALACE_DATA_VOLUME` / `MEMORY_PALACE_SNAPSHOTS_VOLUME`。如果你执行 `docker compose down -v` 或手动删除这些卷，这两部分都会一起清空。
>
> 这也会直接影响审查页：当你切到另一组数据卷或另一个 compose project 时，可见的 rollback 会话会跟着那份数据库一起切换，而不是把不同环境的会话混在一起。

| 服务 | 地址 |
|---|---|
| 前端仪表盘 | <http://127.0.0.1:3000> |
| 后端 API | <http://127.0.0.1:18000> |
| SSE | <http://127.0.0.1:3000/sse> |
| 健康检查 | <http://127.0.0.1:18000/health> |

> 注：以上为默认端口。若端口被占用，一键脚本会自动调整并在控制台输出实际地址。

停止服务：

```bash
COMPOSE_PROJECT_NAME=<控制台打印出的 compose project> docker compose -f docker-compose.yml down --remove-orphans
```

---

## ⚙️ 部署档位（A / B / C / D）

Memory Palace 提供四种部署档位以匹配你的硬件和需求：

| 档位 | 检索模式 | Embedding | Reranker | 适用场景 |
|---|---|---|---|---|
| **A** | 纯 `keyword` | ❌ 关闭 | ❌ 关闭 | 🟢 最小资源，初步验证 |
| **B** | `hybrid` 混合 | 📦 本地哈希 | ❌ 关闭 | 🟡 **默认起步档位**——本地开发，无需外部服务 |
| **C** | `hybrid` 混合 | 🌐 Router / API | ✅ 开启 | 🟠 **强烈推荐档位**——你已经准备好本地模型服务 |
| **D** | `hybrid` 混合 | 🌐 Router / API | ✅ 开启 | 🔴 远程 API，生产环境 |

> **说明**：档位 C 和 D 共享相同的混合检索流水线（`keyword + semantic + reranker`）。当前仓库附带模板的主要区别是模型服务地址（本地 vs 远程）以及默认 `RETRIEVAL_RERANKER_WEIGHT`（`0.30` vs `0.35`）。

### 🔼 升级到档位 C/D

**档位 C 是强烈推荐的目标档位**，但它不是“切过去就自动好用”的零配置方案。

- 想先无脑跑通仓库，默认还是从 **档位 B** 开始
- 想把检索质量拉起来，再升级到 **档位 C**
- 升级时至少要把 `.env` 里的 **embedding** 和 **reranker** 相关参数填好
- 如果你还想启用 LLM 辅助的 write guard / gist / intent routing，也要把对应的 `WRITE_GUARD_LLM_*`、`COMPACT_GIST_LLM_*`、可选的 `INTENT_LLM_*` 一并填好

在 `.env` 文件中配置以下参数。所有端点均支持 **OpenAI 兼容 API** 格式，包括本地部署的 Ollama 或 LM Studio：

```bash
# ── Embedding 模型 ──────────────────────────────────────────
RETRIEVAL_EMBEDDING_BACKEND=api
RETRIEVAL_EMBEDDING_API_BASE=http://localhost:11434/v1   # 例如 Ollama
RETRIEVAL_EMBEDDING_API_KEY=your-api-key
RETRIEVAL_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_EMBEDDING_DIM=1024          # 按 provider 实际返回维度填写

# ── Reranker 模型 ───────────────────────────────────────────
RETRIEVAL_RERANKER_ENABLED=true
RETRIEVAL_RERANKER_API_BASE=http://localhost:11434/v1
RETRIEVAL_RERANKER_API_KEY=your-api-key
RETRIEVAL_RERANKER_MODEL=your-reranker-model-id

# ── 调参旋钮（推荐 0.20 ~ 0.40）────────────────────────────
RETRIEVAL_RERANKER_WEIGHT=0.40
```

> 配置语义说明：
> - `RETRIEVAL_EMBEDDING_BACKEND` 只控制 Embedding 链路。
> - Reranker 没有 `RETRIEVAL_RERANKER_BACKEND` 开关，启用与否由 `RETRIEVAL_RERANKER_ENABLED` 控制。
> - Reranker 连接参数优先读取 `RETRIEVAL_RERANKER_API_BASE/API_KEY/MODEL`；缺失时才回退 `ROUTER_*`（其中 base/key 还可继续回退 `OPENAI_*`）。
> - 当前代码会把 `RETRIEVAL_EMBEDDING_DIM` 作为 OpenAI-compatible `/embeddings` 请求里的 `dimensions` 一起发出去；如果 provider 明确不支持这个字段，会自动重试一次不带 `dimensions` 的旧请求。
> - 如果最终返回的 embedding 维度还是和 `RETRIEVAL_EMBEDDING_DIM` 不一致，运行时现在会立刻拒绝这条向量并走 fallback / degrade，不会再静默写入一条错维度的索引记录。
>
> 如果你的 provider 对 Embedding / Reranker 使用的是带命名空间的 model id（例如 `Qwen/...`），请填写你自己的 provider 实际 model id，不要把示例值原样照抄到别的环境。
> 如果你本地用的是 Ollama 这类 OpenAI-compatible 入口，也优先走 `/v1/embeddings` 这条路径；只有在模型本身确实返回 1024 维向量时，再显式设置 `dimensions=1024`。
> 如果你只是想先做一轮本地 smoke test，通常先直接打真实的 `/embeddings` 和 `/rerank` 端点，比一上来先怀疑后端更快。具体 `curl` 例子可以直接看排障文档。
> 如果你后面要用 `docker_one_click.sh/.ps1` 跑 `profile c/d`，这些示例 model id 也会被当成未解析占位符；在换成真实值之前，脚本会直接在 `docker compose` 前 fail-closed。
>
> **推荐口径（重要）**：
> - **本地开发 / 调试**：优先直接分别配置 `RETRIEVAL_EMBEDDING_*`、`RETRIEVAL_RERANKER_*`、`WRITE_GUARD_LLM_*` / `COMPACT_GIST_LLM_*`。
> - **为什么这样配**：因为三条链路的可达性、模型名、性能瓶颈往往不同，分别直配更容易定位问题，也不会把“本机 router 没有某个模型”的问题误判成整个系统故障。
> - **生产 / 客户环境**：若已有统一模型网关，再回到 `router` 主链路；它更适合承接统一鉴权、限流、审计和模型切换，但不是本地调试的硬性前提。
> - **更多高级配置**：例如 `INTENT_LLM_*`、`CORS_ALLOW_*`、`RETRIEVAL_MMR_*` 与运行时观测/睡眠整合开关，统一以 `.env.example` 和 `docs/DEPLOYMENT_PROFILES.md` 为准。
> - **这些开关怎么理解**：
>   - `INTENT_LLM_ENABLED`：实验能力，默认建议保持 `false`
>   - `RETRIEVAL_MMR_ENABLED`：只有 hybrid 检索下才有意义，默认建议保持 `false`
>   - `CORS_ALLOW_ORIGINS`：本地开发建议留空；要给浏览器跨域访问时再显式写允许域名
>   - `RETRIEVAL_SQLITE_VEC_ENABLED`：当前仍是 rollout 开关，普通用户部署默认建议保持 `false`

### 可选：LLM 驱动的 Write Guard 与 Gist

```bash
# ── Write Guard LLM（写入守卫）──────────────────────────────
WRITE_GUARD_LLM_ENABLED=true
WRITE_GUARD_LLM_API_BASE=http://localhost:11434/v1
WRITE_GUARD_LLM_API_KEY=your-api-key
WRITE_GUARD_LLM_MODEL=your-chat-model-id

# ── Compact Gist LLM（留空则回退至 Write Guard 配置）───────
COMPACT_GIST_LLM_ENABLED=true
COMPACT_GIST_LLM_API_BASE=
COMPACT_GIST_LLM_API_KEY=
COMPACT_GIST_LLM_MODEL=your-chat-model-id
```

> 上面这些模型名只是占位示例，不是项目硬依赖。Memory Palace 不绑定某个固定 provider 或模型家族；请直接填写你自己的 OpenAI-compatible 服务里实际可用的 embedding / reranker / chat model id。如需调整 Intent LLM、CORS、自定义 MMR、sqlite-vec rollout 或运行时审计上限，请直接参考 `.env.example`；README 只保留最常用主配置。
>
> 如果你在本地用 `--allow-runtime-env-injection` 调试 `profile c/d`，脚本会把这次运行切到显式 API 模式；它现在会一起透传显式的 `RETRIEVAL_EMBEDDING_*`（包括 `RETRIEVAL_EMBEDDING_DIM`）、`RETRIEVAL_RERANKER_ENABLED` / `RETRIEVAL_RERANKER_*`，以及可选的 `WRITE_GUARD_LLM_*` / `COMPACT_GIST_LLM_*` / `INTENT_LLM_*`。当 `RETRIEVAL_EMBEDDING_API_*` / `RETRIEVAL_RERANKER_API_*` 没填时，会把 `ROUTER_API_BASE/ROUTER_API_KEY` 作为 embedding / reranker API base+key 的兜底来源；如果 `RETRIEVAL_RERANKER_MODEL` 还没显式填写，也会优先回退到 `ROUTER_RERANKER_MODEL`。这个选项现在会拒绝 `profile a/b`，避免本地 provider 环境变量意外改掉轻量档位默认值。对同一条 one-click 路径来说，当前 shell 里的 loopback router / chat 类 API base 会自动改成 `host.docker.internal`；其它 non-loopback private provider 字面量地址则保持显式写法，只会追加到这次生成的 Docker env allowlist 里。
>
> 对本地 Docker build 路径来说，一键脚本现在还会使用按 checkout 固定的本地镜像名。实际效果就是：只要这个 checkout 里之前已经 build 过一次，即使你换了 `COMPOSE_PROJECT_NAME`，`--no-build` 也还能继续复用这些本地镜像；只有第一次启动或你手动删掉本地镜像时，才需要重新走 `--build`。

档位模板位于：`deploy/profiles/{macos,linux,windows,docker}/profile-{a,b,c,d}.env`

完整参数参考：[DEPLOYMENT_PROFILES.md](docs/DEPLOYMENT_PROFILES.md)

---

## 🔌 MCP 工具参考

Memory Palace 通过 MCP 协议暴露 **9 个标准化工具**：

| 类别 | 工具 | 说明 |
|---|---|---|
| **读写** | `read_memory` | 读取记忆内容（完整或按 `RETRIEVAL_CHUNK_SIZE` 分块）|
| | `create_memory` | 创建新记忆节点（先通过 Write Guard 预检；建议始终显式填写 `title`）|
| | `update_memory` | 更新现有记忆（优先用 Patch；只有真的要追加到末尾时再用 Append）|
| | `delete_memory` | 删除记忆路径（返回结构化 JSON 字符串） |
| | `add_alias` | 为记忆添加别名路径 |
| **检索** | `search_memory` | 统一搜索入口，支持 `keyword` / `semantic` / `hybrid` 模式 |
| **治理** | `compact_context` | 压缩会话上下文为长期摘要（Gist + Trace）|
| | `rebuild_index` | 触发索引重建 / 睡眠整合 |
| | `index_status` | 查询索引可用性和运行时状态 |

### 系统 URI

| URI | 说明 |
|---|---|
| `system://boot` | 读取该 URI 时按 `CORE_MEMORY_URIS` 加载核心记忆 |
| `system://index` | 完整记忆索引概览 |
| `system://index-lite` | 基于 gist 的轻量索引摘要 |
| `system://audit` | 聚合后的观测 / 审计摘要 |
| `system://recent` | 最近修改的记忆 |
| `system://recent/N` | 最近 N 条记忆 |

### 启动 MCP 服务器

```bash
# stdio 模式（用于常见 stdio 客户端——Claude Code、Codex、OpenCode 等）
cd backend && python mcp_server.py

# 如果你是在新终端或客户端配置里启动，下面这条更稳
cd backend && ./.venv/bin/python mcp_server.py   # Windows PowerShell：cd backend && .\.venv\Scripts\python.exe mcp_server.py

# SSE 模式（下面这个命令是本机回环示例；远程访问请改 HOST）
cd backend && HOST=127.0.0.1 PORT=8010 python run_sse.py
```

> 上面这条 `python mcp_server.py` 默认 `backend/.venv` 已经激活；如果不是，优先改用项目自己的 `.venv` 解释器，避免启动时用错 Python。
>
> 只有在你确实需要远程客户端时，才改成 `HOST=0.0.0.0`；同时记得补齐网络侧安全措施。

完整工具语义：[TOOLS.md](docs/TOOLS.md)

---

## 🔄 多客户端集成

MCP 工具层负责 **确定性执行**；Skills 策略层负责 **策略与时机**。

<p align="center">
  <img src="docs/images/多客户端 MCP + Skills 编排图.png" width="900" alt="多客户端 MCP + Skills 编排图" />
</p>

### 推荐默认流程

```
1. 🚀 启动    → read_memory("system://boot")               # 加载核心记忆
2. 🔍 召回    → search_memory(include_session=true)         # 话题召回
3. ✍️ 写入    → 优先 update_memory 的 Patch；新建用带 title 的 create_memory    # 先读后写
4. 📦 压缩    → compact_context(force=false)                 # 会话压缩
5. 🔧 恢复    → rebuild_index(wait=true) + index_status()   # 降级恢复
```

### 支持的客户端

| 客户端 | 集成方式 |
|---|---|
| Claude Code | 新机器上更稳的默认方案是 `user` 级安装；只有你还想补当前仓库项目级入口时，再额外执行 workspace 安装 |
| Gemini CLI | 新机器上更稳的默认方案是 `user` 级安装；workspace 安装在当前仓库里仍然只是可选补充 |
| Codex CLI / OpenCode | `sync` 只解决 repo-local skill 自动发现；如果你想稳定绑到当前仓库 backend，仍建议补 `--scope user --with-mcp` |
| Cursor / Windsurf / VSCode-host / Antigravity | repo-local `AGENTS.md` + `python scripts/render_ide_host_config.py --host ...` |

### 安装 Skill

```bash
python scripts/sync_memory_palace_skill.py
python scripts/sync_memory_palace_skill.py --check
python scripts/install_skill.py --targets claude,codex,gemini,opencode --scope user --with-mcp --force
python scripts/install_skill.py --targets claude,gemini --scope workspace --with-mcp --force
python scripts/install_skill.py --targets claude,gemini --scope workspace --with-mcp --check
```

如果你要补 workspace 级 MCP，当前脚本只会为 `Claude Code` 和 `Gemini CLI` 写稳定的 repo-local 绑定；`Codex/OpenCode` 继续走 user-scope MCP 更稳。

现在 `--check` 只会把文档里支持的 repo-local launcher 形态判成通过。说人话就是：`PASS` 的意思是“当前绑定方式在支持列表里”，不是“随便写个差不多的自定义命令也算过”。

如果你接的是 IDE 宿主，不要先找 hidden skill mirrors，直接生成当前仓库的 MCP 配置片段：

```bash
python scripts/render_ide_host_config.py --host cursor
python scripts/render_ide_host_config.py --host windsurf
python scripts/render_ide_host_config.py --host vscode-host
python scripts/render_ide_host_config.py --host antigravity
```

文档里的规范名字现在统一写成 `VSCode-host`，对应命令参数用 `vscode-host`。脚本仍兼容历史写法 `--host vscode`，但新的示例统一改用 `vscode-host`。

如果宿主存在 `stdin/stdout` 或 CRLF 兼容问题，再改用 wrapper 版本：

```bash
python scripts/render_ide_host_config.py --host antigravity --launcher python-wrapper
```

如果你想在自己的机器上额外做一轮本地验证，再运行：

```bash
python scripts/evaluate_memory_palace_skill.py
cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py
```

其中 `Gemini CLI`、`Codex CLI`、`OpenCode` 在新机器上都更建议优先补一次 `user` 级 MCP 安装：

```bash
python scripts/install_skill.py --targets gemini,codex,opencode --scope user --with-mcp --force
```

上面这两条更适合作为补充验证，不需要把它们理解成新手第一次安装时的必做步骤。

canonical 真源，以及你执行 CLI 同步/安装命令后在本地会看到的路径：

- Canonical：`<repo-root>/docs/skills/memory-palace/`
- Claude Code：`<repo-root>/.claude/skills/memory-palace/`
- Codex CLI：`<repo-root>/.codex/skills/memory-palace/`
- OpenCode：`<repo-root>/.opencode/skills/memory-palace/`

这些隐藏目录都是安装后生成的本地镜像目录。刚 clone 下来时，通常只会先看到 `docs/skills/memory-palace/` 这份 canonical bundle。

对 IDE 宿主，推荐看的不是这些 hidden mirrors，而是：

- repo-local 规则入口：`<repo-root>/AGENTS.md`
- MCP 配置片段：`python scripts/render_ide_host_config.py --host <cursor|windsurf|vscode-host|antigravity>`
- `Antigravity` 兼容层：只有宿主确实需要 wrapper 时，才改用 `backend/mcp_wrapper.py`

这套 skill 已按当前真实代码口径收敛：

- 会话启动优先 `read_memory("system://boot")`
- URI 不确定时优先 `search_memory(..., include_session=true)`
- 写入遵循“先读后写”，并显式处理 `guard_action` / `guard_reason`
- 检索降级时先 `index_status()`，再视情况 `rebuild_index(wait=true)`
- `guard_action=NOOP` 时不要继续写入；先检查建议目标，再决定是否切换为 `update_memory`
- 触发样例集固定在 `<repo-root>/docs/skills/memory-palace/references/trigger-samples.md`

如果你想额外复核 skill smoke 或真实 MCP 端到端链路，运行：

```bash
python scripts/evaluate_memory_palace_skill.py
cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py
```

这两条命令会生成本地复核报告。`FAIL` 需要处理；`SKIP` / `PARTIAL` / `MANUAL` 通常表示宿主或环境边界，需要按目标环境补验。
如果要在 CI 或并行 review 里隔离输出，设置 `MEMORY_PALACE_SKILL_REPORT_PATH` / `MEMORY_PALACE_MCP_E2E_REPORT_PATH`。
相对路径会被放到 `memory-palace-reports/` 下；如果要固定落点，优先用仓库外的绝对路径。

现在这条 live MCP e2e 脚本会跟用户实际连接时一样，优先走 repo-local wrapper。它也会把 wrapper 行为和 `compact_context` 的 gist 持久化一起带上复核，而不只是检查工具清单。

完整指南见：

- [MEMORY_PALACE_SKILLS.md](docs/skills/MEMORY_PALACE_SKILLS.md)
- [IDE_HOSTS.md](docs/skills/IDE_HOSTS.md)

---

## 📊 评测结果

> 这里保留**对用户有用的摘要表**，用于说明当前版本的大致表现。
>
> 想看方法、边界和复现命令，直接看 `docs/EVALUATION.md`；想看当前 `v3.7.1` 的发布说明，直接看 `docs/changelog/release_v3.7.1_2026-03-26.md`；如果还想看同口径的旧版 vs 当前版本摘要，再补看 `docs/changelog/release_summary_vs_old_project_2026-03-06.md`。
>
> 下面这些数字是发布摘要，不代表所有硬件、provider 或网络条件下都会完全一致。

### 检索质量 — A/B/C/D 真实运行

数据源：`profile_abcd_real_metrics.json` · 每数据集样本量 = 8 · 10 个干扰文档 · Seed = 20260219 · 这类 JSON 通常是维护阶段在本地复核时生成的 benchmark 产物

> 📌 这组数字是当前发布轮次的一次摘要运行；硬件、模型服务和网络条件不同，结果也可能不同。

> 📌 这些指标怎么理解：
>
> - `HR@10`：前 10 条里有没有找到正确结果
> - `MRR`：正确结果排得靠不靠前
> - `NDCG@10`：整体排序质量好不好
> - `p95`：慢的时候大概会慢到什么程度
>
> 如果你只看一个指标，先看 `HR@10`。

| 档位 | 数据集 | HR@10 | MRR | NDCG@10 | p95（ms） | 门控 |
|---|---|---:|---:|---:|---:|---|
| A | SQuAD v2 | 0.000 | 0.000 | 0.000 | 1.78 | ✅ 通过 |
| A | NFCorpus | 0.250 | 0.250 | 0.250 | 1.74 | ✅ 通过 |
| B | SQuAD v2 | 0.625 | 0.302 | 0.383 | 4.92 | ✅ 通过 |
| B | NFCorpus | 0.750 | 0.478 | 0.542 | 5.02 | ✅ 通过 |
| **C** | **SQuAD v2** | **1.000** | **1.000** | **1.000** | 665.14 | ✅ 通过 |
| C | NFCorpus | 0.750 | 0.567 | 0.611 | 454.42 | ✅ 通过 |
| **D** | **SQuAD v2** | **1.000** | **1.000** | **1.000** | 2078.38 | ✅ 通过 |
| D | NFCorpus | 0.750 | 0.650 | 0.673 | 2364.97 | ✅ 通过 |

> 💡 在这组历史 SQuAD v2 benchmark 产物里，档位 C/D 通过外部 Embedding（bge-m3）+ Reranker（bge-reranker-v2-m3）达到完美召回。额外延迟来自模型推理和网络开销。

### 检索质量 — A/B 大样本门控

数据源：`profile_ab_metrics.json` · 样本量 = 100 · 这类 JSON 通常是维护阶段在本地复核时生成的 benchmark 产物

| 档位 | 数据集 | HR@10 | MRR | NDCG@10 | p95（ms） |
|---|---|---:|---:|---:|---:|
| A | MS MARCO | 0.333 | 0.333 | 0.333 | 2.1 |
| A | BEIR NFCorpus | 0.300 | 0.300 | 0.300 | 2.6 |
| A | SQuAD v2 | 0.150 | 0.150 | 0.150 | 3.0 |
| B | MS MARCO | 0.867 | 0.658 | 0.696 | 3.7 |
| B | BEIR NFCorpus | 1.000 | 0.828 | 0.850 | 4.7 |
| B | SQuAD v2 | 1.000 | 0.765 | 0.822 | 3.9 |

> ⚠️ 上面这组 A/B/C/D 指标主要用来帮助你理解当前基准集里的**档位差异**。
>
> 如果你还想补看**同口径旧版 vs 当前版本对照**，直接看：
>
> - `docs/EVALUATION.md` 里的 `3.5 旧版 vs 当前版本（同口径摘要）`
> - `docs/changelog/release_summary_vs_old_project_2026-03-06.md`

<p align="center">
  <img src="docs/images/benchmark_comparison.png" width="900" alt="旧版 vs 当前版本检索质量与延迟对比图" />
</p>

> 📈 这张图看的是**旧版 vs 当前版本**在同口径下的一次对照快照，不是 A/B/C/D 档位示意图，也不代表所有环境都会得到相同结果。

### 质量门控汇总

| 门控项 | 指标 | 结果 | 阈值 | 状态 |
|---|---|---:|---:|---|
| Write Guard | 精确率 | 1.000 | ≥ 0.90 | ✅ 通过 |
| Write Guard | 召回率 | 1.000 | ≥ 0.85 | ✅ 通过 |
| 意图分类 | 准确率 | 1.000 | ≥ 0.80 | ✅ 通过 |
| Gist 质量 | ROUGE-L | 0.759 | ≥ 0.40 | ✅ 通过 |
| Phase 6 门控 | 有效性 | true | — | ✅ 通过 |

> **Write Guard**：在 6 个测试用例上评估（4 TP, 0 FP, 0 FN）。数据源：`write_guard_quality_metrics.json`（通常由维护阶段的本地 benchmark 复核生成）
>
> **意图分类**：使用 `keyword_scoring_v2` 方法，6/6 正确分类，覆盖 temporal、causal、exploratory、factual 四种意图。数据源：`intent_accuracy_metrics.json`（通常由维护阶段的本地 benchmark 复核生成）
>
> **Gist ROUGE-L**：5 个测试用例的平均值（范围：0.667 – 0.923）。数据源：`compact_context_gist_quality_metrics.json`（通常由维护阶段的本地 benchmark 复核生成）
>
> 说人话就是：
>
> - **Write Guard** 看“该拦的时候拦没拦对”
> - **意图分类** 看“系统有没有先看懂这条查询是什么类型”
> - **ROUGE-L** 看“压缩后的 gist 有没有把关键意思留下来”

### 评测复核说明

当前仓库里保留了 `backend/tests/benchmark/` 相关测试与脚本，但这部分更适合作为复核材料，不是新手上来的第一步。

这里保留的数字，是维护阶段基于真实代码和真实验证得到的**摘要口径**。

如果你使用的是日常用户内容，建议这样复核当前安装状态：

```bash
bash scripts/pre_publish_check.sh
curl -fsS http://127.0.0.1:8000/health
```

如果你确实要复核 benchmark，再去看 `backend/tests/benchmark/` 下的 runners 和相关测试；普通用户日常使用先做最小健康检查就够了。

---

## 🖼️ 仪表盘截图

> 📌 下面这些图主要用来帮助你快速认识功能区。
>
> - 它们展示的是**已经进入 Dashboard 后**的典型页面状态
> - 下面这组图展示的是切到中文后的界面；如果浏览器里还没有保存语言值，常见中文浏览器语言现在会自动归并到 `zh-CN`，其他首次访问场景则回退到英文
> - 当前版本顶部统一提供鉴权 / 配置入口（中文界面下对应 `设置 API 密钥` / `更新 API 密钥` / `清除密钥`；若运行时已注入则显示 `运行时密钥已启用`，同时仍可打开 `配置向导`）
> - 如果还没配置鉴权，页面外壳仍然会打开，但受保护的数据请求会先显示授权提示、空态或 `401`，而不是直接显示完整数据
> - 如果你实际用的是 Microsoft Edge，在线页面可能会比这些截图看起来更“素”一点，因为 Edge 现在会自动切到更轻量的视觉模式来减少卡顿；页面结构和功能本身不变

<details>
<summary>🪄 首启配置向导</summary>

<img src="docs/images/setup-assistant-zh.png" width="900" alt="Memory Palace — 首启配置向导（中文模式）" />

这个向导可以把 Dashboard key 保存到当前浏览器会话里，并且在“非 Docker 的本地 checkout”场景下，把常见运行参数直接写进 `.env`。如果浏览器没法把这把会话级 key 存下来，页面现在会明确提示保存失败，不再把它显示成成功；所以请把 `.env` 写入和浏览器鉴权保存理解成两步。涉及后端运行链路的改动仍然需要重启服务。
</details>

<details>
<summary>📂 记忆 — 树形浏览器与编辑器</summary>

<img src="docs/images/memory-zh.png" width="900" alt="Memory Palace — 记忆浏览器页面（中文模式）" />

树形结构的记忆浏览器，支持内联编辑和 Gist 视图。按 域名 → 路径 层级导航。
</details>

<details>
<summary>📋 审查 — 差异对比与回滚</summary>

<img src="docs/images/review-zh.png" width="900" alt="Memory Palace — 审查页面（中文模式）" />

快照的并排差异对比，支持一键回滚和整合操作。当前版本在这页上还补了更细的错误提示和会话处理细节。审查队列会跟随**当前数据库**作用域切换，所以当你换到另一份本地 `.env`、另一个 compose project 或另一份 SQLite 文件时，不会把别的库里的 rollback 会话混进当前页面。
</details>

<details>
<summary>🔧 维护 — 活力治理</summary>

<img src="docs/images/maintenance-zh.png" width="900" alt="Memory Palace — 维护页面（中文模式）" />

监控记忆活力值、触发清理任务、管理衰减参数。当前版本还补了 domain / path_prefix 等过滤项，以及更完整的人工确认流程。
</details>

<details>
<summary>📊 可观测性 — 搜索与任务监控</summary>

<img src="docs/images/observability-zh.png" width="900" alt="Memory Palace — 可观测性页面（中文模式）" />

实时搜索查询监控、检索质量洞察和任务队列状态。当前版本还补了 `scope hint`、运行时快照里的 `reflection_workflow`、搜索诊断里的 `interaction_tier` / `intent_llm_attempted`，以及索引任务队列等信息。
</details>

> 💡 后端现在默认不再公开运行中的 `/docs`。要看当前接口行为，优先看仓库文档和 `backend/tests/` 里的已核对测试。

---

## ⏱️ 记忆写入与审查工作流

<p align="center">
  <img src="docs/images/记忆写入与审查时序图.png" width="900" alt="记忆写入与审查时序图" />
</p>

### 写入路径

1. `create_memory` / `update_memory` 进入 **Write Lane** 队列
2. 写入前 **Write Guard** 评估 → 核心动作：`ADD` / `UPDATE` / `NOOP` / `DELETE`（`BYPASS` 仅用于 metadata-only 更新流程标记）
3. **快照** 与版本变更记录生成
4. 异步 **Index Worker** 入队进行索引更新

### 检索路径

1. `preprocess_query` → `classify_intent`（factual / exploratory / temporal / causal；无显著信号默认 factual_high_precision，冲突或低信号混合时为 unknown/default）
2. 策略模板匹配（如 `factual_high_precision`、`temporal_time_filtered`）
3. 执行 `keyword` / `semantic` / `hybrid` 检索
4. 返回 `results` + `degrade_reasons`

---

## 📚 文档导航

| 文档 | 说明 |
|---|---|
| [快速开始](docs/GETTING_STARTED.md) | 从零到运行的完整指南 |
| [技术概述](docs/TECHNICAL_OVERVIEW.md) | 架构设计与模块职责 |
| [部署档位](docs/DEPLOYMENT_PROFILES.md) | A/B/C/D 详细配置与调参指南 |
| [MCP 工具](docs/TOOLS.md) | 全部 9 个工具的完整语义与返回格式 |
| [评测报告](docs/EVALUATION.md) | 检索质量、写入门控、意图分类指标 |
| [Skills 指南](docs/skills/MEMORY_PALACE_SKILLS.md) | 多客户端统一集成策略 |
| [安全与隐私](docs/SECURITY_AND_PRIVACY.md) | API Key 认证与安全策略 |
| [故障排查](docs/TROUBLESHOOTING.md) | 常见问题与解决方案 |

---

## 🔐 安全与隐私

- 仅 `.env.example` 被提交——**实际 `.env` 文件始终被 gitignore**
- 文档中所有 API Key 均使用占位符
- HTTP/SSE 鉴权默认 **失败关闭（fail-closed）**：未配置或未提供有效 `MCP_API_KEY` 时，受保护接口返回 `401`
- 上述门控仅作用于 HTTP/SSE 接口；`stdio` 模式不受影响
- Docker 一键部署默认通过服务端代理转发鉴权头，浏览器页面不会直接拿到真实 `MCP_API_KEY`
- 本地绕过需显式启用：`MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`（仅限回环地址）
- 但 Setup Assistant 的本地 `.env` 写入边界更严格：它只允许写项目内的 `.env*` 文件，而且仍然只接受直连 loopback；第一次本地保存还要求 `Dashboard API key` 非空；只要后端已经配置了 `MCP_API_KEY`，就算是 loopback 写入也必须带有效 key
- 通过向导写入的 provider API base 会先做归一化和校验：`/embeddings`、`/rerank`、`/chat/completions` 这类常见后缀会自动去掉，格式不对或指到 link-local 的地址会直接拦下；`127.0.0.1` / `::1` 这类 loopback IP 字面量，再加上 `localhost`，仍然默认允许；其它 private IP 字面量，以及解析后会落到 private 非 loopback 地址的 hostname，则要通过 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` 显式放行

详情：[SECURITY_AND_PRIVACY.md](docs/SECURITY_AND_PRIVACY.md)

---

## 🔀 迁移与兼容性

为向后兼容旧版 `nocturne_memory` 部署：

- 脚本仍支持旧版 `NOCTURNE_*` 环境变量前缀
- Docker 脚本自动检测并复用旧版数据卷
- 后端启动时通过 `_try_restore_legacy_sqlite_file()` 自动从旧版 SQLite 文件名恢复（`agent_memory.db`、`nocturne_memory.db`、`nocturne.db`）

> 兼容层不影响当前 Memory Palace 品牌和主路径。

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=AGI-is-going-to-arrive/Memory-Palace&type=Date)](https://star-history.com/#AGI-is-going-to-arrive/Memory-Palace&Date)

---

## 📄 开源协议

[MIT](LICENSE) — Copyright (c) 2026 agi

---

## 🙏 致谢与灵感来源

- 最初的灵感来源于这条社区讨论帖：<https://linux.do/t/topic/1616409>
- 最早参考的项目是 `Dataojitori/nocturne_memory`：<https://github.com/Dataojitori/nocturne_memory>
- `Memory Palace` 是在这条思路上做的完整重构版本，补齐了新的公开文档、部署路径和验证链

---

<p align="center">
  <strong>用 ❤️ 为有记忆的 AI Agent 而构建。</strong>
</p>

<p align="center">
  <sub>Memory Palace · 记忆宫殿 —— 因为最好的 AI 助手，从不遗忘。</sub>
</p>
