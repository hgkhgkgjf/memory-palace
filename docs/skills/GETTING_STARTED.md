# Memory Palace Skills 快速上手

> 如果你只想把当前仓库这条 skill + MCP 链路接通，按这份做就够了。
>
> 如果你只是通过 GHCR / Docker 跑 `Dashboard / API / SSE`，这份不是第一入口；只有要把本机客户端接到当前 checkout 时才继续读。
>
> 如果你希望 **AI 直接一步一步带你安装**，更推荐先从独立仓库 [`memory-palace-setup`](https://github.com/AGI-is-going-to-arrive/memory-palace-setup) 开始。当前统一口径是：**优先走 skills + MCP，不要默认走 MCP-only**。装好后直接说：`使用 $memory-palace-setup 帮我一步步安装配置 Memory Palace，优先走 skills + MCP。默认先按 Profile B 起步，但如果环境允许，请主动推荐我升级到 C/D。`
>
> 这份长文档用于手工 repo-local 接通、逐步校验和排障。如果只是想先跑通，优先看 `memory-palace-setup` 或 `SKILLS_QUICKSTART.md`。
>
> repo-local MCP launcher 规则只有两条：原生 Windows 使用 `backend/mcp_wrapper.py`；
> macOS / Linux / `Git Bash` / `WSL` / MSYS / Cygwin 使用 `scripts/run_memory_palace_mcp_stdio.sh`。
> `install_skill.py`、`render_ide_host_config.py` 和 repo-local 自检都按这条规则生成配置。
>
> repo-local wrapper 只服务于“当前 checkout + 本地 `.env` + 本地 `backend/.venv`”，不会复用 Docker 容器里的 `/app/data`。如果只有 `.env.docker`，或本地 `DATABASE_URL` 仍指向 `/app/...` / `/data/...` 容器路径，它会拒绝启动，并提示改成本机绝对路径或 Docker `/sse`。
>
> **再补一条范围说明**：这份主要写给 `Claude Code / Gemini CLI / Codex / OpenCode` 这类 CLI 客户端。`Cursor / Windsurf / VSCode-host / Antigravity` 这类 IDE 宿主，请直接看 `IDE_HOSTS.md`。

## 🎯 先记住一句话

`memory-palace` 分成两层：

- **skill 自动发现**
  - 负责“什么时候该进入 Memory Palace 工作流”
- **MCP 真正绑到当前仓库**
  - 负责“真正去调用这个仓库里的 Memory Palace backend”

所以“能用”必须同时满足：

1. skill 被发现
2. MCP 指向当前仓库

少任何一层，都不算真的配好。

再补一句 Docker 用户最容易误会的：

- `docker compose` 能把服务端跑起来
- 但不会自动把你机器上的 skill / MCP / IDE host 配置也一起改好
- 当前这份文档描述的是 **repo-local 安装路径**
- 如果你不走这条 repo-local 路径，而是只想让某个客户端手工接 Docker 里的 MCP，请把它视为另一条“手工远程 SSE MCP”路径

这条“手工远程 SSE MCP”路径当前已经有公开入口：

- `docs/GHCR_QUICKSTART.md`
- `docs/GETTING_STARTED.md` 里的 `6.2 SSE 模式`
- `docs/GETTING_STARTED.md` 里的 `6.3 客户端配置示例`

补一句最重要的边界：

- 当前仓库已经给出了**通用的 SSE MCP 配置骨架**
- 但不同客户端自己的字段名、GUI 入口、header 配置方式并不完全一样
- 所以如果你走这条手工路径，Memory Palace 文档负责告诉你：
  - 服务地址
  - 鉴权要求
  - 通用 JSON 骨架
- 客户端最终要填在哪个面板、字段名叫什么，仍以客户端自己的 MCP 文档为准

---

## 1. 单一真源在哪里

当前 canonical skill 在：

```text
docs/skills/memory-palace/
```

这里维护的是：

- `SKILL.md`
- `references/`
- `variants/`
- `agents/openai.yaml`

你运行同步 / 安装命令后，`.claude/.codex/.gemini/.opencode/...` 这些镜像目录才会出现在本地。刚 clone 下来、还没执行命令前看不到它们，属于正常现象。

如果你接的是 IDE 宿主，不要把 hidden mirrors 当成默认主路径。那条路径现在单独收到了：

- `IDE_HOSTS.md`
- `python scripts/render_ide_host_config.py --host ...`

---

## 2. 第一步：先同步 repo-local mirrors

```bash
python scripts/sync_memory_palace_skill.py
python scripts/sync_memory_palace_skill.py --check
```

这一步只解决 **skill 自动发现**，还没解决 MCP。

补一条这次已经按当前脚本口径收紧过的行为：

- 如果你是刚 clone 下来的仓库、还没安装任何 workspace mirrors，`--check` 现在会直接说明“当前还没安装 mirrors”，并返回成功；它不再把“尚未安装”误报成 drift/fail。
- 真正会让 `--check` 失败的，是“你已经装过了，但当前内容和 canonical 对不上”。

---

## 3. 第二步：先走更稳的 user-scope，再按需补 workspace 入口

`install_skill.py` 现在除了装 skill，还支持：

- `--with-mcp`
  - 同步安装 MCP 配置
- `--check`
  - 检查当前安装结果是否与 canonical 和当前仓库绑定一致

再补一条很实用的边界：

- 如果你省略 `--targets`，当前默认只会安装 CLI 目标：`claude,codex,opencode`
- `gemini` 仍然推荐，但要你在命令里显式加上
- `cursor/agent/antigravity` 这类 IDE 宿主兼容投影，已经不在默认 target 集合里

补一条很实用的细节：

- 如果脚本准备改写现有配置文件（例如 `.mcp.json`、`.gemini/settings.json`、`~/.gemini/policies/memory-palace-overrides.toml`、`~/.codex/config.toml`），现在会先在同目录生成一个 `*.bak` 备份
  - 例如：`.mcp.json.bak`、`settings.json.bak`、`memory-palace-overrides.toml.bak`、`config.toml.bak`
- 如果目标 JSON 本身已经坏掉，脚本会直接报出具体文件路径和行列号，不再吐一整屏 Python traceback
- 如果 Windows 上的配置文件或 skill 目录刚好被短暂占用，`install_skill.py` 现在还会对那类最终 `replace` / promote / rollback 步骤补一层有上限的小重试，不再那么容易把安装停在半切换状态

### 推荐命令

新机器上更稳的默认方案，还是先从 `user-scope` 开始：

```bash
python scripts/install_skill.py \
  --targets claude,codex,gemini,opencode \
  --scope user \
  --with-mcp \
  --force
```

如果你还想让**当前仓库**额外落一个项目级入口，再补一次 workspace 安装：

```bash
python scripts/install_skill.py \
  --targets claude,gemini \
  --scope workspace \
  --with-mcp \
  --force
```

检查：

```bash
python scripts/install_skill.py \
  --targets claude,gemini \
  --scope workspace \
  --with-mcp \
  --check
```

如果你要补 workspace 级 MCP，`install_skill.py` 当前只会为 `Claude Code` 和 `Gemini CLI` 写稳定的 repo-local 绑定；`Codex/OpenCode` 继续走 user-scope MCP 更稳。

如果这条 `workspace --check` 通过，可以直接这样理解：

- `Claude`：`SKILL OK` + `MCP OK`
- `Gemini`：`SKILL OK` + `MCP OK`
- `Codex/OpenCode`：如果你也放进同一条 workspace 检查里，skill 会是 `OK`，但 MCP 只会给 `NOTE`，因为 workspace scope 本来就不定义稳定的 repo-local MCP 配置面

如果你看到的是：

- `workspace --check` 通过
- 但 `user --check` 失败

先别急着怀疑仓库本身坏了。更常见的情况是你自己 home 目录里还留着旧版 skill / MCP 配置。直接对同一组 target 重跑一次 `--scope user --with-mcp --force` 即可；脚本现在会先在原目录留 `*.bak`，再覆盖当前文件。

这一步会做两件事：

1. 继续保持 repo-local skill mirrors
2. 给当前仓库补两个直连入口：
   - `Claude Code` → `.mcp.json`
   - `Gemini CLI` → `.gemini/settings.json`
   - `Gemini CLI` → `.gemini/policies/memory-palace-overrides.toml`

这两个入口会按平台调用 repo-local wrapper：

```text
native Windows  -> backend/mcp_wrapper.py
macOS / Linux / Git Bash / WSL -> scripts/run_memory_palace_mcp_stdio.sh
```

这里说的“native Windows”现在是按实际宿主环境判断，不是只看你机器是不是 Windows。也就是说：如果你人在 Windows 机器上，但当前命令是从 `Git Bash` / `WSL` / MSYS / Cygwin 发出来的，安装脚本仍会把它当成 POSIX shell 宿主，继续写 `bash` wrapper。

它的作用很简单：

- 用项目自己的 `backend/.venv`
- 优先复用当前仓库 `.env` 里的 `DATABASE_URL`
- 如果宿主或客户端把 `DATABASE_URL` 显式传成空字符串，也会按“没设置”处理，继续回退到当前仓库 `.env` 的有效值
- 如果仓库里只有 `.env.docker` 而没有本地 `.env`，就停止并提示改走 Docker `/sse`
- 如果 `.env` / 显式 `DATABASE_URL` 在把常见斜杠和大小写变体归一化后，仍写成 `/app/...` 或 `/data/...` 这类容器路径，也会停止并提示改成本机绝对路径或 Docker `/sse`
- 对 shell wrapper 这条路径，还会合并已有的 `NO_PROXY` / `no_proxy` 并补上 `localhost`、`127.0.0.1`、`::1`、`host.docker.internal`，减少本机 Ollama / 本机 OpenAI-compatible 服务被宿主机代理误走

这两条 wrapper 的边界保持一致，所以你在 Dashboard / HTTP API 里看到的库，和 MCP 客户端实际读写的库，默认就是同一份。

也就是说：`Claude / Codex / Gemini / OpenCode` 这些 repo-local `stdio` 入口最终都会走**当前平台对应的 wrapper**。你改这个仓库 `.env`，等于一起改了这些客户端默认连到的库。

注意：

- `Codex/OpenCode` 在 workspace scope 下仍以 **repo-local skill 自动发现** 为主
- 它们的 MCP 仍建议走 **user-scope 注册**

---

## 4. 第三步：补上 Codex / OpenCode 的 user-scope MCP

如果你想让你自己的 `Codex/OpenCode` 明确连到这个仓库，执行：

```bash
python scripts/install_skill.py \
  --targets claude,codex,gemini,opencode \
  --scope user \
  --with-mcp \
  --force
```

检查：

```bash
python scripts/install_skill.py \
  --targets claude,codex,gemini,opencode \
  --scope user \
  --with-mcp \
  --check
```

这一步会把 MCP 注册到这些地方：

- `Claude Code` → `~/.claude.json` 当前仓库 project block
- `Codex CLI` → `~/.codex/config.toml`
- `Gemini CLI` → `~/.gemini/settings.json`
- `Gemini CLI` → `~/.gemini/policies/memory-palace-overrides.toml`
- `OpenCode` → `~/.config/opencode/opencode.json`

这些 user-scope MCP 配置本质上也还是调用同一个 wrapper，所以默认行为和 workspace 入口一致：

- 先读当前仓库 `.env`
- 再决定实际 `DATABASE_URL`
- 没有本地 `.env` 且仓库里只有 `.env.docker` 时，不会偷偷改用 `demo.db`
- 如果 `.env` / 显式 `DATABASE_URL` 在把常见斜杠和大小写变体归一化后，仍是 `/app/...` 或 `/data/...` 容器路径，也会直接拒绝启动

如果你想换到另一份数据库，优先改这个仓库自己的 `.env`，不要手工在不同客户端里各写一套不同的数据库路径。

---

## 5. 四个 CLI 客户端现在怎么理解

下面这些结论默认你已经跑完了上面的 `sync/install` 命令。

### Claude Code

- repo-local skill：有
- workspace MCP：有

结论：

- **更稳的默认方案还是先跑 `--scope user --with-mcp`**
- 如果你还想给当前仓库补一个项目级入口，再额外执行 workspace 安装

### Gemini CLI

- repo-local skill：有
- workspace MCP：有
- policy 覆盖文件：有

结论：

- **更稳的默认方案仍是先跑 `--scope user --with-mcp`**
- 如果你还想给当前仓库补一个 workspace 入口，再额外执行 workspace 安装
- 如果你看到 `Policy file warning in memory-palace-overrides.toml`，优先重跑一遍 `--scope user --with-mcp --force`
- 写给别人看时仍建议保守：普通 `gemini` smoke 这轮已通过；`gemini_live` 仍是显式可选并默认 `SKIP`

### Codex CLI

- repo-local skill：有
- user-scope MCP：推荐

结论：

- **不要理解成天然开箱即用**
- 准确说法是：
  - skill 可 repo-local 自动发现
  - MCP 仍以 user-scope 注册为主
- 对 `Codex` 更稳的公开口径是：skill 仍可 repo-local 自动发现，MCP 仍以 user-scope 注册为主；这次 session 的 `codex` smoke 已通过，但公开文档仍建议保留“目标机再做一次 user-scope 复核”的说法，不要直接写成所有机器都已完全通过

### OpenCode

- repo-local skill：有
- user-scope MCP：推荐

结论：

- **不要理解成天然开箱即用**
- 准确说法是：
  - skill 可 repo-local 自动发现
  - MCP 仍以 user-scope 注册为主

如果你接的是 `Cursor / Windsurf / VSCode-host / Antigravity`，这里先停下，不要继续套用 CLI 的 hidden mirror 逻辑。直接改看：

- `IDE_HOSTS.md`
- `python scripts/render_ide_host_config.py --host ...`

---

## 6. 最简单的验证方法

### 安装链检查

```bash
python scripts/install_skill.py \
  --targets claude,gemini \
  --scope workspace \
  --with-mcp \
  --check

python scripts/install_skill.py \
  --targets claude,codex,gemini,opencode \
  --scope user \
  --with-mcp \
  --check
```

### 触发 smoke

```bash
python scripts/evaluate_memory_palace_skill.py
```

这条命令会在本地生成 smoke 摘要：

```text
docs/skills/TRIGGER_SMOKE_REPORT.md
```

如果你是刚 clone 下来的 GitHub 仓库，这个文件默认可能还不存在；先跑完命令再看，属于正常现象。它属于本地验证产物，分享前建议自己检查是否包含本机路径、客户端配置路径或其他环境痕迹。`evaluate_memory_palace_skill.py` 现在只要任一检查是 `FAIL` 就会返回非零退出码；`SKIP` / `PARTIAL` / `MANUAL` 不会单独让进程失败。如果 `codex exec` 在 smoke 超时前没有产出结构化输出，`codex` 那一项会记成 `PARTIAL`，而不是把整轮卡住。
如果你在并行 review 或 CI 里不想覆盖默认文件，也可以先设置 `MEMORY_PALACE_SKILL_REPORT_PATH`。如果你写的是相对路径，脚本现在会自动把报告落到系统临时目录下的 `memory-palace-reports/`；如果你想完全自己控制落点，优先传仓库外的绝对路径。
如果当前机器根本没有 `Antigravity` 宿主 runtime，就把 `antigravity` 那一项看成“目标宿主上的手工补验还没做”，不要先理解成仓库主链路失败。

这条检查会串行调用多种 CLI；如果你的机器上已经装了 `claude`、`codex`、`opencode`、`gemini`，完整跑完通常要几分钟，不建议看到几十秒无输出就直接当成“挂死”。
`gemini_live` 现在改为**显式可选**：只有当你主动设置 `MEMORY_PALACE_ENABLE_GEMINI_LIVE=1` 时，脚本才会对 Gemini 当前配置解析出的真实数据库做一轮 `create/update/guard` 验证，并可能留下 `notes://gemini_suite_*` 这类测试记忆；如果你还想强制跳过，也可以继续设置 `MEMORY_PALACE_SKIP_GEMINI_LIVE=1`。
即使手动开启这轮 live 验证，只要撞上共享真实数据库、有另一条 Gemini live 会话先改了同一条记忆，或者回答漏掉了当前的 known-URI fast path（目标 URI 已明确时，本来就该直接 `read_memory(...)`，不该再绕回 `search_memory(...)`），它也可能停在 `PARTIAL`；先把它理解成 live 宿主侧或 smoke 契约侧的验证边界，不要直接等同于主链路 skill/MCP 已坏。
如果这条报告里只有 `mcp_bindings` 失败，优先先重跑一次统一的 `user-scope` 安装，再重新执行 smoke：

```bash
python scripts/install_skill.py --targets claude,codex,gemini,opencode --scope user --with-mcp --force
python scripts/evaluate_memory_palace_skill.py
```

如果你看到的是：

- `mcp_bindings = PARTIAL`
- `claude/codex/gemini/opencode` 这些 user-scope 入口都已经是 `PASS`

通常说明只是**可选的 workspace 入口还没安装**，或者 `cursor/agent/antigravity` 这类 IDE 宿主兼容投影还没补到当前仓库；不要先把它理解成主链路 MCP 绑定已经坏了。

### 真实 MCP 调用链

```bash
cd backend
python ../scripts/evaluate_memory_palace_mcp_e2e.py
```

这条命令会在本地生成真实 MCP e2e 摘要：

```text
docs/skills/MCP_LIVE_E2E_REPORT.md
```

同样地，这份报告默认也是“运行后才会出现”的本地产物；公开 GitHub 仓库里暂时没有，不代表接法有问题。
如果你在并行 review 或 CI 里不想覆盖默认文件，也可以先设置 `MEMORY_PALACE_MCP_E2E_REPORT_PATH`。如果你写的是相对路径，脚本现在会自动把报告落到系统临时目录下的 `memory-palace-reports/`；如果你想完全自己控制落点，优先传仓库外的绝对路径。
它默认使用隔离临时库，不会碰你的正式库；但失败时仍可能把 stderr、日志或临时目录路径写进报告。准备转发给别人前，先自己看一遍内容。
这条脚本会跟用户实际连接时一样走 repo-local wrapper，并覆盖 wrapper 行为和 `compact_context` gist 持久化。最终结果以本机生成的报告为准；原生 Windows / 原生 Linux host runtime 仍需在目标环境复核。

这两份报告主要用来复核当前环境的结果，不是主入口文档。

---

## 7. 正向 / 反向 prompt

正向 prompt：

```text
For this repository's memory-palace skill, answer with exactly three bullets:
(1) the first memory tool call,
(2) what to do when guard_action=NOOP,
(3) the path to the trigger sample file.
```

期望命中：

- `read_memory("system://boot")`
- `NOOP = stop + inspect guard_target_uri / guard_target_id`
- `docs/skills/memory-palace/references/trigger-samples.md`

当前 smoke 还会再补一条后续检查：如果 prompt 里已经直接给出具体 URI，答案就应该直接对那个 URI 走 `read_memory(...)`，不要先绕回 `search_memory(...)`。

反向 prompt：

```text
请帮我改一下 README 开头的文案，不需要碰 Memory Palace。
```

如果这条也硬触发 `memory-palace`，说明 `description` 太宽，或者客户端触发策略有问题。

---

## 8. 最容易踩的坑

### 只同步了 skill mirrors

现象：

- 看起来 skill 在
- 但 MCP 没绑到当前仓库

### 只补了 MCP，没补 skill

现象：

- 工具能用
- 但客户端不会自动进入 Memory Palace 工作流

### 把 Codex / OpenCode 误写成“天然开箱即用”

现象：

- repo-local skill 的确会被发现
- 但没有 user-scope MCP 时，仍可能不会连到当前仓库 backend

### 直接依赖隐藏路径

现象：

- skill 已加载
- 但读取 `.gemini/skills/...` 或 `.codex/skills/...` 时被本机策略拦掉

所以统一优先引用 repo-visible 路径：

```text
docs/skills/memory-palace/references/mcp-workflow.md
docs/skills/memory-palace/references/trigger-samples.md
```

---

## 9. 下一份该看什么

- 想看四端口径：`CLI_COMPATIBILITY_GUIDE.md`
- 想本地复核 skill 触发结果：先跑 `python scripts/evaluate_memory_palace_skill.py`
- 想本地复核真实 MCP e2e：先跑 `cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py`
