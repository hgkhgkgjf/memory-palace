# Memory Palace Skills 设计说明

`memory-palace` skill 体系的结构概览。如果你只是要把客户端接通，看 [`SKILLS_QUICKSTART.md`](SKILLS_QUICKSTART.md) 即可。

---

## 1. 单一真源

canonical bundle 在：

```text
docs/skills/memory-palace/
├── SKILL.md
├── references/
│   ├── mcp-workflow.md
│   └── trigger-samples.md
├── agents/
│   └── openai.yaml
└── variants/
    ├── antigravity/
    │   └── global_workflows/
    │       └── memory-palace.md
    └── gemini/
        ├── SKILL.md
        └── memory-palace-overrides.toml
```

分发与安装：

- `scripts/sync_memory_palace_skill.py` —— 把 canonical bundle 分发到各 CLI 镜像目录
- `scripts/install_skill.py` —— 安装到 workspace 或 user 目录，可选 `--with-mcp`
- `scripts/render_ide_host_config.py` —— 给 IDE 宿主生成 MCP 配置片段

`.claude / .codex / .gemini / .opencode` 等镜像目录都是执行同步或安装后生成的本地产物，公开仓库默认不带。

---

## 2. 与 Claude Skills 规范的对齐

- **结构对齐**：采用 `skill-name/SKILL.md` 的标准 bundle 结构
- **触发契约对齐**：`description` 同时写清 “做什么” 和 “什么时候用”
- **渐进加载对齐**：主 `SKILL.md` 保持短小，工具细节下沉到 `references/`
- **跨客户端分发对齐**：Claude / Codex / OpenCode 走 mirror；Gemini 用 variant

边界：验证层是工程化的 smoke / e2e，不是 `skill-creator` 那种 `evals.json` + 自动 description 优化 loop。

---

## 3. 目录职责

| 路径 | 职责 |
|---|---|
| `docs/skills/memory-palace/SKILL.md` | 定义何时触发、最短安全默认流程、硬约束 |
| `docs/skills/memory-palace/variants/gemini/SKILL.md` | 更短、更强触发的 Gemini variant，把 first move / NOOP / trigger sample path 写成锚点 |
| `docs/skills/memory-palace/variants/gemini/memory-palace-overrides.toml` | Gemini policy 覆盖：把 MCP tool 改成 `mcpName = "memory-palace"` 规则格式，避免旧 `__` 语法告警 |
| `docs/skills/memory-palace/references/mcp-workflow.md` | 9 个 MCP 工具的最小安全工作流 + recall / write / compact / rebuild 顺序 |
| `docs/skills/memory-palace/references/trigger-samples.md` | 稳定的 should-trigger / should-not-trigger / borderline prompt 集 |
| `docs/skills/memory-palace/variants/antigravity/global_workflows/memory-palace.md` | Antigravity 专属 workflow 投影（兼容层） |

---

## 4. 设计原则

1. `description` 是触发契约
2. `SKILL.md` 正文只保留执行步骤、硬约束、失败处理
3. 工具细节下沉到 `references/`
4. 分发与校验由仓库脚本负责，不让用户手抄 skill
5. 运行时引用优先指向 repo-visible canonical 路径（不依赖 hidden mirror 可读）
6. 不只检查 “skill 能不能被发现”，还要检查 “MCP 是否真的绑到当前项目”

---

## 5. 默认工作流

### Boot

首次真实操作前：

```python
read_memory("system://boot")
```

### Recall

URI 不确定时：

```python
search_memory(query="...", include_session=True)
```

URI 已经明确时优先直接 `read_memory(uri)`，不要先绕回 `search_memory(...)`。

### Read before write

在 `create_memory` / `update_memory` / `delete_memory` / `add_alias` 前先读目标或候选目标。

写法默认：

- 新建时给 `create_memory` 显式填 `title`
- 普通改写用 `update_memory` 的 patch
- 真的要在末尾补内容时再用 `append`

### Guard-aware write

不能忽略这些字段：

- `guard_action`
- `guard_reason`
- `guard_method`
- `guard_target_uri`
- `guard_target_id`

规则：

- `NOOP` -> 停止写；检查 `guard_target_uri / guard_target_id`，读建议目标后再决定是否需要改动
- `UPDATE` -> 先看建议目标；如果你还在 create / 写前判断阶段，通常改走 `update_memory`
- `DELETE` -> 先确认旧记忆确实该被替换

### Compact / Recover

- 长会话、噪声多 -> `compact_context(force=false)`
- 检索退化 -> `index_status()`，必要时 `rebuild_index(wait=true)`

---

## 6. Trigger 设计

`description` 必须覆盖：

- 英文：memory / remember / recall / long-term memory
- 中文：记住、回忆、长期记忆、跨会话、压缩上下文、重建索引
- 明确提到 `system://boot`、`search_memory`、`compact_context`、`rebuild_index`
- 用户在问 “该 create 还是 update”
- 用户在做维护、回滚、索引恢复相关动作

边界：

- 不用于普通 README / UI / benchmark / 通用代码实现
- 不用于与 Memory Palace MCP 无关的泛化 “技能设计” 任务

`references/trigger-samples.md` 提供 should-trigger / should-not-trigger / borderline 样例集，用于 `description` 迭代时有固定对照组。

---

## 7. 维护顺序

调整 skill 时按这个顺序：

1. 先改 trigger description
2. 再改 `SKILL.md` 正文
3. 跑 `python scripts/sync_memory_palace_skill.py --check`
4. 跑 `python scripts/evaluate_memory_palace_skill.py`
5. 跑 `cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py`
6. 跑 `bash scripts/pre_publish_check.sh`
7. 真有必要时再扩 `references/`

不要回到 “先写长文档，再让用户自己抄成 skill” 的旧模式。

---

## 8. Gemini 兼容边界

CLI 可以发现并加载 `memory-palace` skill，但运行时文件读取策略可能跳过 hidden mirror 目录（如 `.gemini/skills/...`）。因此 `SKILL.md` 引用参考文件时统一指向 `docs/skills/memory-palace/...`，不依赖 hidden mirror 可读。

更稳定的 Gemini 调用方式：

```bash
gemini -m gemini-3-flash-preview \
  -p '<your prompt>' \
  --output-format text \
  --allowed-tools activate_skill,read_file
```

这是经验路径，不是官方保证。
