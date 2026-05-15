# Memory Palace — MCP 工具参考手册

> **Memory Palace** 通过 [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) 为 AI Agent 提供持久化记忆能力。
> 本文档是所有 9 个 MCP 工具的完整参考，适合首次接入的新手用户阅读。

---

## 目录

- [快速参考表](#快速参考表)
- [核心概念](#核心概念)
- [工具详细说明](#工具详细说明)
  - [read_memory — 读取记忆](#read_memory)
  - [create_memory — 创建记忆](#create_memory)
  - [update_memory — 更新记忆](#update_memory)
  - [delete_memory — 删除记忆](#delete_memory)
  - [add_alias — 添加别名](#add_alias)
  - [search_memory — 检索记忆](#search_memory)
  - [compact_context — 会话压缩](#compact_context)
  - [rebuild_index — 索引重建](#rebuild_index)
  - [index_status — 索引状态查询](#index_status)
- [返回值通用字段](#返回值通用字段)
- [降级 (Degradation) 机制](#降级机制)
- [推荐工作流 (Skills 策略)](#推荐工作流)
- [检索配置 (Profile C/D)](#检索配置)

---

## 快速参考表

| 工具 | 类别 | 一句话说明 |
|---|---|---|
| `read_memory` | 📖 读取 | 按 URI 读取记忆内容，支持整段 / 分片 / 范围读取 |
| `create_memory` | ✏️ 写入 | 在指定父 URI 下创建新的记忆节点 |
| `update_memory` | ✏️ 写入 | 更新已有记忆的内容、优先级或 disclosure |
| `delete_memory` | ✏️ 写入 | 按 URI 删除记忆路径 |
| `add_alias` | ✏️ 写入 | 为同一条记忆创建另一个 URI 入口（别名） |
| `search_memory` | 🔍 检索 | 通过关键词 / 语义 / 混合模式搜索记忆 |
| `compact_context` | 🧹 治理 | 将当前会话上下文压缩为持久化摘要 |
| `rebuild_index` | 🔧 维护 | 触发检索索引重建或 sleep-time 整合任务 |
| `index_status` | 🔧 维护 | 查询索引可用性、队列深度与运行时状态 |

---

## 核心概念

### URI 地址体系

Memory Palace 使用 `domain://path` 格式来寻址每一条记忆：

```
core://agent              ← 核心域下的 "agent" 路径
writer://chapter_1/scene  ← 写作域下的层级路径
system://boot             ← 系统内置 URI（只读）
```

这里的 URI 指的是 **Memory Palace 记忆地址**，不是操作系统文件路径。像 `C:/notes.txt`、`C:\notes.txt` 这类 Windows 文件路径现在会被明确拒绝；如果你要访问记忆，请写成 `core://...`，不要把本机磁盘路径传进 MCP 工具。

字面 `%20` 这类百分号序列本身也可以是合法路径文本。说人话就是：如果某条路径真的就叫
`foo%20bar`，它会继续按字面路径存在；但对已经存在的记忆来说，公开工具也会兼容
`core://foo%20bar`、`core://chapter_1%2Fscene_2` 这类编码空格 / 编码斜杠写法去查找。
像 `C%3A/...` 这种解码后会变成 Windows 文件路径的输入，则会继续直接拒绝。

**常用域（Domain）：**

- `core` — 核心记忆（人格、偏好、关键事实）
- `writer` — 写作域（故事、章节）
- `system` — 系统保留（`boot` / `index` / `index-lite` / `audit` / `recent`），不可写入

> 💡 优先级 (`priority`) 是一个整数，**数字越小优先级越高**（0 最高）。它决定了检索排序和冲突解决时的先后顺序。当前公开工具契约要求这里传的是真正的整数值；`true/false`、`1.9` 这类值会直接拒绝。

### Write Guard（写入守卫）

`create_memory` 和 `update_memory` 在执行前会自动调用 **Write Guard**，用于：

- 检测是否已有重复内容（避免冗余写入）
- 建议合并到已有记忆（返回 `UPDATE` / `NOOP` 动作）

Write Guard 的决策方法可能包括 `keyword`、`embedding`、`llm`、`write_guard_llm`、`unknown`、`none`、`exception`，取决于当前配置和服务可用性。

---

## 工具详细说明

<a id="read_memory"></a>

### 📖 `read_memory`

**功能：** 按 URI 读取记忆内容。

**函数签名：**
<!-- 源码位置: backend/mcp_server.py -->
```python
read_memory(
    uri: str,                       # 必填，记忆 URI
    chunk_id: Optional[int] = None, # 可选，分片索引（0 起始）
    range: Optional[str] = None,    # 可选，字符范围（如 "0:500"）
    max_chars: Optional[int] = None, # 可选，返回字符数上限
    include_ancestors: Optional[bool] = False # 可选，是否附带父链记忆（仅非 system URI）
)
```

**系统 URI（特殊地址）：**

| URI | 用途 | 何时使用 |
|---|---|---|
| `system://boot` | 加载核心记忆 + 最近记忆 | 每次**会话启动**时调用 |
| `system://index` | 查看所有记忆的完整索引 | 需要**概览全部记忆**时 |
| `system://index-lite` | 查看 gist 轻量索引摘要 | 需要**低成本快速概览**时 |
| `system://audit` | 查看聚合观测/审计摘要 | 需要**排障与运行态巡检**时 |
| `system://recent` | 最近修改的 10 条记忆 | 快速查看**最新变更** |
| `system://recent/N` | 最近修改的 N 条记忆 | 自定义数量（最多 100） |

**返回值格式：**

- **默认模式**（不传 `chunk_id` / `range` / `max_chars`）：返回格式化的纯文本
- **分片模式**（传入任一可选参数）：返回 JSON 字符串，包含 `selection` 元信息

**使用示例：**

```python
# 会话启动时加载核心记忆
read_memory("system://boot")

# 读取某条具体记忆
read_memory("core://agent/my_user")

# 分片读取大段内容（第 0 片）
read_memory("core://agent", chunk_id=0)

# 按字符范围读取
read_memory("core://agent", range="0:500")
```

> 📌 公开工具在查已有记忆时，会先按原始 path 查，再按解码变体补一次兼容查找。也就是说，编码空格 / 编码斜杠仍然能命中已有路径，但字面百分号路径不会被自动改写。

> ⚠️ `chunk_id` 和 `range` **不能同时使用**。

---

<a id="create_memory"></a>

### ✏️ `create_memory`

**功能：** 在父 URI 下创建一条新记忆。

**函数签名：**
<!-- 源码位置: backend/mcp_server.py -->
```python
create_memory(
    parent_uri: str,              # 必填，父 URI（如 "core://agent"）
    content: str,                 # 必填，记忆正文
    priority: int,                # 必填，检索优先级（数字越小越优先）
    title: Optional[str] = None,  # 可选，路径名（仅限 a-z/0-9/_/-）
    disclosure: str = ""          # 可选，触发条件描述
)
```

**关键行为：**

1. 创建前自动执行 **Write Guard** 检查
2. 若 Guard 判定为 `NOOP` / `UPDATE` / `DELETE`，创建会被阻止，返回建议目标 `guard_target_uri` / `guard_target_id`
3. 若创建是因为 Write Guard 临时异常或降级而被 fail-closed，响应里还会额外带 `retryable=true` 与 `retry_hint`
4. `title` 只允许字母、数字、下划线和连字符（不允许空格和特殊字符）
5. 若省略 `title`，系统自动分配数字 ID
6. `content` 现在还会在 MCP 入口层做长度校验；超过 `100000` 字符会直接拒绝，不再继续进 DB / Write Guard 链路
7. `parent_uri` 也遵循和读/删工具相同的 URI 契约：已有父路径如果是空格或斜杠，编码空格 / 编码斜杠写法仍可用；字面百分号路径则保持字面含义

**使用示例：**

```python
# 创建一条核心记忆
create_memory(
    "core://",
    "用户喜欢简洁的代码风格",
    priority=2,
    title="coding_style",
    disclosure="当我写代码或 review 代码时"
)

# 在已有路径下创建子记忆
create_memory(
    "core://agent",
    "每次对话开始时先问候用户",
    priority=1,
    title="greeting_rule",
    disclosure="每次会话启动时"
)
```

---

<a id="update_memory"></a>

### ✏️ `update_memory`

**功能：** 更新已有记忆的内容或元数据。

**函数签名：**
<!-- 源码位置: backend/mcp_server.py -->
```python
update_memory(
    uri: str,                          # 必填，目标 URI
    old_string: Optional[str] = None,  # Patch 模式：待替换的原文
    new_string: Optional[str] = None,  # Patch 模式：替换后的新文本
    append: Optional[str] = None,      # Append 模式：追加到末尾的文本
    priority: Optional[int] = None,    # 可选，新优先级
    disclosure: Optional[str] = None   # 可选，新触发条件
)
```

**两种编辑模式（互斥）：**

| 模式 | 参数 | 说明 |
|---|---|---|
| **Patch 模式** | `old_string` + `new_string` | 精确查找 `old_string` 并替换为 `new_string`。`old_string` 必须唯一命中 |
| **Append 模式** | `append` | 将文本追加到现有内容末尾 |

> ⚠️ **没有全量替换模式。** 必须通过 `old_string` / `new_string` 明确指定修改内容，防止意外覆盖。
>
> ⚠️ **更新前请先 `read_memory`**，确保你了解将被修改的内容。
>
> ⚠️ `old_string` / `new_string` / `append` 现在也会在 MCP 入口层做长度校验；任一字段超过 `100000` 字符会直接拒绝，不再继续进 DB / Write Guard 链路。
>
> 📌 如果内容更新触发了 `guard_action=UPDATE`，并且返回了有效的 `guard_target_id`，`update_memory` 仍会继续按**当前 URI 原地更新**执行；这里的 `guard_target_uri` / `guard_target_id` 更像“有相似目标，值得你再看一眼”的提示，不是自动把这次更新改写到别的 URI。
>
> 📌 如果 `guard_action=UPDATE` 但没有返回有效的 `guard_target_id`，工具仍会按 fail-closed 拦下这次更新。

**使用示例：**

```python
# Patch 模式：精确替换一段文字
update_memory(
    "core://agent/my_user",
    old_string="旧的偏好描述",
    new_string="新的偏好描述"
)

# Append 模式：追加内容
update_memory("core://agent", append="\n## 新章节\n这是追加的内容")

# 仅修改元数据（不触发 Write Guard）
update_memory("core://agent/my_user", priority=5)
```

---

<a id="delete_memory"></a>

### ✏️ `delete_memory`

**功能：** 删除指定 URI 路径。

**函数签名：**
<!-- 源码位置: backend/mcp_server.py -->
```python
delete_memory(
    uri: str  # 必填，要删除的 URI
)
```

**注意事项：**

- 删除的是 **URI 路径**，而非底层记忆正文的版本链
- 如果一条记忆有多个别名路径，删除其中一个不影响其他别名
- 删除前建议先 `read_memory` 确认内容
- 当前返回值是 **结构化 JSON 字符串**，常见字段包括 `ok`、`deleted`、`uri`、`message`
- 这里也沿用同样的 URI 兼容规则：编码空格 / 编码斜杠仍可命中已有路径，但字面百分号路径仍按字面解释

**使用示例：**

```python
delete_memory("core://agent/old_note")
```

---

<a id="add_alias"></a>

### ✏️ `add_alias`

**功能：** 为同一条记忆添加别名 URI，提升可达性。

**函数签名：**
<!-- 源码位置: backend/mcp_server.py -->
```python
add_alias(
    new_uri: str,                       # 必填，新的别名 URI
    target_uri: str,                    # 必填，已有记忆的 URI
    priority: int = 0,                  # 可选，此别名的检索优先级
    disclosure: Optional[str] = None    # 可选，此别名的触发条件
)
```

**说明：** 别名可以跨域——例如将 `writer://` 域的记忆链接到 `core://` 域。

**当前边界：**

- `new_uri` / `target_uri` 都会先走和其它写工具一致的 URI 校验；控制字符、不可见格式字符、surrogate 都会直接拒绝
- 如果 alias 已经写进数据库，但后续 snapshot 记录失败，当前实现会把这条 alias path 一起补偿回滚，避免出现“工具报错但 alias 已经半成功落库”的状态

**使用示例：**

```python
add_alias(
    "core://timeline/2024/05/20",
    "core://agent/my_user/first_meeting",
    priority=1,
    disclosure="当我想回忆我们是如何认识的"
)
```

---

<a id="search_memory"></a>

### 🔍 `search_memory`

**功能：** 通过关键词、语义或混合模式检索记忆。

**函数签名：**
<!-- 源码位置: backend/mcp_server.py -->
```python
search_memory(
    query: str,                                  # 必填，搜索关键词（当前上限 8000 字符）
    mode: Optional[str] = None,                  # 可选，"keyword" / "semantic" / "hybrid"
    max_results: Optional[int] = None,           # 可选，返回结果数上限
    candidate_multiplier: Optional[int] = None,  # 可选，候选池倍率
    include_session: Optional[bool] = None,      # 可选，是否包含本会话记忆
    filters: Optional[Dict] = None,              # 可选，过滤条件
    scope_hint: Optional[str] = None,            # 可选，查询侧作用域提示（domain/path_prefix/URI 前缀）
    verbose: Optional[bool] = True               # 可选，是否返回完整调试元数据
)
```

> 📌 `candidate_multiplier` 只是第一轮扩候选池的提示值，不是无限放大开关。当前实现仍有硬上限；公开返回里会带 `candidate_multiplier_applied`，而 backend metadata 里仍会保留 `candidate_limit_applied` 说明这次真正打到的硬上限。

**检索模式：**

| 模式 | 说明 |
|---|---|
| `keyword` | 安全 FTS/BM25 优先；不安全查询会自动回退到转义后的 LIKE 路径（默认模式） |
| `semantic` | 基于 Embedding 向量语义搜索（需启用可用的 embedding 链路，如 `hash` / `api` / `router` / `openai`） |
| `hybrid` | 关键词 + 语义混合检索；若已启用 Reranker，会在后面继续重排 |

> `RRF_ENABLED=false` 是当前默认值。显式开启后，RRF 只融合 `RRF_CHANNELS=fts5,vector` 这类 allowlist 通道，默认 `RRF_K=60`；`RRF_LOG_CHANNEL_CONTRIBUTIONS=false` 表示默认不额外记录通道贡献日志。`ENTITY_RERANK_WEIGHT=0.0` 也是默认关闭；entity 信号只在融合结果之后做 boost，不是 RRF 的第三条 channel。

**过滤条件 (`filters`)：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `domain` | `str` | 限定域，如 `"core"` |
| `path_prefix` | `str` | 限定路径前缀，如 `"agent/my_user"` |
| `max_priority` | `int` | 只返回 priority ≤ 此值的记忆 |
| `updated_after` | `str` | ISO 时间过滤，如 `"2026-01-31T12:00:00Z"` |

**响应字段说明：**

| 字段 | 说明 |
|---|---|
| `query_effective` | 实际生效的查询文本 |
| `query_preprocess` | 查询预处理信息 |
| `intent` | 意图分类：`factual` / `exploratory` / `temporal` / `causal` / `unknown` |
| `mode_applied` | 实际使用的检索模式 |
| `results` | 搜索结果列表；当前返回顺序会和对外暴露的 `results[].score` 保持一致 |
| `results[].score` | 当前对外可见的排序分数；`results` 默认按这个字段降序返回 |
| `degrade_reasons` | 降级原因（如有） |
| `session_first_metrics` | session-first 合并与路径复核统计；例如 `stale_result_dropped`、`session_queue_refreshed`、`revalidate_lookup_failed` |

**实用说明：**

- 默认 `verbose=true`，会带上 `query_preprocess`、`intent_profile`、`session_first_metrics`、`backend_metadata` 这类调试信息
- 如果你只关心结果、分数和降级原因，可以传 `verbose=false`，这样返回更短，更适合 MCP 上下文窗口
- 如果最终路径状态复核本身查库失败，当前实现会直接丢掉那条结果，并在 `degrade_reasons` 里追加 `path_revalidation_lookup_failed`；不会再把一条“当前状态不确定”的旧结果继续当成正常命中返回
- `candidate_multiplier` 仍然只是“你希望放大多少”的提示值；公开返回先看 `candidate_multiplier_applied`，backend metadata 再看 `candidate_limit_applied`；尤其是 `fast` 交互档下，第一轮 multiplier 现在硬上限固定为 `4`，后续意图策略也不会再把它悄悄抬高
- `query` 现在会先走一层 FTS 安全检查：像 `AND` / `OR` / `NOT` / `NEAR` 这类保留词，或 wildcard 很重的查询，不再直接改变 FTS 语义；当前实现会按这次请求回退到安全路径，而不是把普通用户输入打成一条全局故障

**使用示例：**

```python
# 简单关键词搜索
search_memory("coding style")

# 混合搜索 + 域过滤
search_memory(
    "chapter arc",
    mode="hybrid",
    max_results=8,
    include_session=True,
    filters={"domain": "writer", "path_prefix": "chapter_1"}
)
```

---

<a id="compact_context"></a>

### 🧹 `compact_context`

**功能：** 将当前会话上下文压缩为持久化记忆摘要。

**函数签名：**
<!-- 源码位置: backend/mcp_server.py -->
```python
compact_context(
    reason: str = "manual",  # 可选，压缩原因标签
    force: bool = False,     # 可选，强制压缩（不判断阈值）
    max_lines: int = 12      # 可选，摘要最大行数（最小 3）
)
```

**摘要产物：**

- **Gist**：简短摘要，用于快速回忆
- **Trace**：原始要点留痕，保留关键上下文

**Gist 生成链路（按优先级自动降级）：**

1. `llm_gist` — 调用 LLM 生成摘要（需在 `.env` 中配置 OpenAI-compatible API）
2. `extractive_bullets` — 提取式要点
3. `sentence_fallback` — 句子级降级

**实用说明：**

- 按当前验证链路，repo-local stdio 和 Docker `/sse` 都能把 `llm_gist` 真正落到持久化结果里
- 如果远程 chat 路径超时或不可用，`compact_context` 会继续按后续 fallback 降级，不会假装 LLM 已经成功
- 正常的 backend / SSE / repo-local stdio 退出路径上，系统现在还会对 pending auto-flush summary 做一次 best-effort drain；如果写入被 write_guard 拦住，或退出前这一步失败，它会跳过而不是强行写脏数据
- 同一条 session 的 flush 现在还会额外走一层基于数据库文件的 session 级进程锁；如果另一个本地进程已经在压缩这条 session，当前调用会直接返回 `already_in_progress`

**响应字段：**

| 字段 | 说明 |
|---|---|
| `gist_method` | 当前 Gist 生成策略 |
| `quality` | Gist 质量分（0–1） |
| `source_hash` | Trace 源内容哈希（用于一致性校验） |
| `index_queued` / `index_dropped` / `index_deduped` | 索引入队统计 |
| `degrade_reasons` | 降级原因（如有） |

**使用示例：**

```python
# 让系统自动判断是否需要压缩
compact_context(force=False)

# 强制压缩并限制摘要行数
compact_context(reason="long_session", force=True, max_lines=8)
```

---

<a id="rebuild_index"></a>

### 🔧 `rebuild_index`

**功能：** 触发检索索引重建或 sleep-time 整合任务。

**函数签名：**
<!-- 源码位置: backend/mcp_server.py -->
```python
rebuild_index(
    memory_id: Optional[int] = None,     # 可选，目标记忆 ID（省略则重建全量）
    reason: str = "manual",              # 可选，审计标签
    wait: bool = False,                  # 可选，是否等待任务完成再返回
    timeout_seconds: int = 30,           # 可选，等待超时秒数（wait=True 时生效）
    sleep_consolidation: bool = False    # 可选，触发 sleep-time 整合任务
)
```

**两种模式：**

| 模式 | 条件 | 行为 |
|---|---|---|
| **索引重建** | `sleep_consolidation=False`（默认） | 执行 `rebuild_index` / `reindex_memory` 队列任务 |
| **Sleep-time 整合** | `sleep_consolidation=True` | 离线扫描碎片和重复记忆，生成清理预览 |

**Sleep-time 整合详情：**

- 扫描孤儿候选并生成去重预览
- 对碎片化路径生成 rollup 预览
- 默认是 **preview-only**（不执行实际删除/写入）：
  - 设置 `RUNTIME_SLEEP_DEDUP_APPLY=1` 才执行重复清理
  - 设置 `RUNTIME_SLEEP_FRAGMENT_ROLLUP_APPLY=1` 才写入 rollup gist
- ⚠️ `memory_id` 和 `sleep_consolidation=True` **不能同时使用**

**队列满载保护：**

- HTTP 维护接口返回 `503` + `index_job_enqueue_failed`
- MCP 返回 `ok=false` + `error=queue_full`

**使用示例：**

```python
# 全量重建并等待完成
rebuild_index(wait=True)

# 重建单条记忆的索引
rebuild_index(memory_id=42, wait=True)

# 触发 sleep-time 整合（仅预览）
rebuild_index(sleep_consolidation=True, wait=True)
```

---

<a id="index_status"></a>

### 🔧 `index_status`

**功能：** 查询检索索引可用性、统计信息和运行时状态。

**函数签名：**
<!-- 源码位置: backend/mcp_server.py -->
```python
index_status()  # 无参数
```

**返回信息包含：**

| 字段 | 说明 |
|---|---|
| `index_available` | 索引是否可用 |
| `degraded` | 是否降级 |
| `runtime.index_worker` | 队列深度、活跃任务、成功/失败/取消统计 |
| `runtime.sleep_consolidation` | Sleep 整合调度状态（`enabled` / `scheduled` / `reason`） |
| `runtime.write_lanes` | 写入通道状态 |

**使用示例：**

```python
# 检查索引健康状态
index_status()
```

---

## 返回值通用字段

### Write Guard 字段

`create_memory` 和 `update_memory` 的返回值中包含以下 Write Guard 信息：

| 字段 | 可能值 | 说明 |
|---|---|---|
| `guard_action` | `ADD` / `UPDATE` / `NOOP` / `DELETE` / `BYPASS` | Guard 的决策动作 |
| `guard_reason` | 字符串 | 决策原因 |
| `guard_method` | `keyword` / `embedding` / `llm` / `write_guard_llm` / `unknown` / `none` / `exception` | 检测方法 |
| `guard_target_uri` / `guard_target_id` | 字符串 / 整数 | Guard 建议你复查或切换到的目标；它们是提示，不是自动重定向写入 |

### 索引入队统计字段

`create_memory`、`update_memory`、`compact_context` 的返回值还包含：

| 字段 | 说明 |
|---|---|
| `index_queued` | 实际入队任务数 |
| `index_dropped` | 未成功入队的任务数（如队列已满） |
| `index_deduped` | 去重后未重复入队的任务数 |

> ⚠️ 当 `index_dropped > 0` 时，表示有索引任务未能入队。客户端应将其视为降级信号，结合 `degrade_reasons` 进行告警或补偿。

### Write-Lane 超时

对 `create_memory`、`update_memory`、`delete_memory`、`add_alias`、`compact_context` 这类写工具：

- 如果 write lane 已经塞满，响应里现在会带 `reason=write_lane_timeout`
- 同一个响应里还会带 `retryable=true` 和 `retry_hint`
- 对应的 HTTP API 则会把同样的问题返回成结构化 `503`

---

## 降级机制

检索链路中，当远程 Embedding / Reranker 服务不可用或返回异常时，系统会**自动降级**并在响应中返回 `degrade_reasons` 字段。  
写入链路中，若出现 `write_guard_exception`，系统会 fail-closed 拒绝写入并记录审计，不属于“继续写入的自动降级”。

**常见降级原因：**

| 原因 | 说明 |
|---|---|
| `embedding_fallback_hash` | Embedding API 不可用，回退到本地 hash |
| `embedding_request_failed` | Embedding 请求失败 |
| `embedding_dim_mismatch_requires_reindex` | 当前查询作用域内的向量维度与当前配置不一致，需要重建索引 |
| `vector_dim_mixed_requires_reindex` / `vector_dim_mismatch_requires_reindex` | 当前查询作用域内混入了多种向量维度，或该作用域整体维度与当前配置不一致，需要重建索引 |
| `reranker_request_failed` | Reranker 请求失败 |
| `path_revalidation_lookup_failed` | 最终路径状态复核本身失败；相关结果已被直接丢弃，不再 fail-open 暴露旧 URI |
| `write_guard_exception` | Write Guard 执行异常，写入已被拒绝（fail-closed） |
| `query_preprocess_failed` | 查询预处理失败 |
| `index_enqueue_dropped` | 索引任务入队失败 |

> `embedding_request_failed` / `reranker_request_failed` 现在仍会保留基础标记，但也可能继续附带更细的后缀，例如 `:timeout`、`:http_status:503`，或 embedding 链路上的 `:api:timeout`。排障时先看主标记，再看后缀。
>
> 💡 **建议：** 客户端策略中应把 `degrade_reasons` 字段作为告警信号。当检测到降级时，可调用 `rebuild_index(wait=True)` + `index_status()` 尝试恢复。向量维度相关告警现在会跟着**当前查询作用域**走，所以别的无关 domain 不应该再触发一条假的重建提示。

---

## 推荐工作流

以下工作流是通用的 MCP 使用顺序。具体哪些客户端已经验证、哪些仍有边界，请以 `docs/skills/SKILLS_QUICKSTART.md` 的公开口径为准：

### 标准会话流程

```
┌──────────────┐
│  1. 会话启动   │  read_memory("system://boot")
│              │  → 加载核心记忆 + 最近更新
└──────┬───────┘
       ▼
┌──────────────┐
│  2. 话题回忆   │  search_memory(query, include_session=True) / read_memory(uri)
│              │  → URI 不确定时先搜索；目标 URI 已知时直接读取
└──────┬───────┘
       ▼
┌──────────────┐
│  3. 写入前检查 │  read_memory(uri) / search_memory → 确认无重复 → create_memory / update_memory
│              │  → 目标已知就直接先读；目标不确定时先搜，避免创建冗余记忆
└──────┬───────┘
       ▼
┌──────────────┐
│  4. 长会话压缩 │  compact_context(force=False)
│              │  → 系统自动判断是否需要压缩
└──────┬───────┘
       ▼
┌──────────────┐
│  5. 降级恢复   │  rebuild_index(wait=True) → index_status()
│              │  → 检测到降级时重建索引并确认状态
└──────────────┘
```

详细 Skills 编排策略见：[skills/MEMORY_PALACE_SKILLS.md](skills/MEMORY_PALACE_SKILLS.md)

---

## 检索配置

Memory Palace 支持多种检索 Profile。Profile C 和 D 使用混合检索路线（`keyword + semantic + reranker`），需要额外配置。

### 必需环境变量

在 `.env` 中配置 OpenAI-compatible API 参数：
<!-- 参考: .env.example 第 57-77 行 -->

```bash
# ── Embedding 配置 ──
RETRIEVAL_EMBEDDING_BACKEND=none      # 可选: none / hash / router / api / openai
RETRIEVAL_EMBEDDING_API_BASE=         # API 地址
RETRIEVAL_EMBEDDING_API_KEY=          # API 密钥
RETRIEVAL_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_EMBEDDING_DIM=<provider-vector-dim>  # 由用户填写的真实向量维度

# ── Reranker 配置 ──
RETRIEVAL_RERANKER_ENABLED=false      # 是否启用 Reranker
RETRIEVAL_RERANKER_API_BASE=          # API 地址
RETRIEVAL_RERANKER_API_KEY=           # API 密钥
RETRIEVAL_RERANKER_MODEL=your-reranker-model-id

# ── 权重调参 ──
RETRIEVAL_RERANKER_WEIGHT=0.40        # Reranker 权重（首要调参项）
RETRIEVAL_HYBRID_KEYWORD_WEIGHT=0.7   # 关键词权重
RETRIEVAL_HYBRID_SEMANTIC_WEIGHT=0.3  # 语义权重
```

> 💡 **首要调参项**是 `RETRIEVAL_RERANKER_WEIGHT`。这里写的是 generic `.env.example` 默认值 `0.40`；如果你用的是 shipped `Profile C/D` 模板，还要以模板里显式写死的档位值为准。即使 Embedding / Reranker 是本地部署的，也必须配置 OpenAI-compatible API 参数。
>
> 配置语义说明：`RETRIEVAL_EMBEDDING_BACKEND` 仅控制 Embedding 路径；Reranker 没有 `RETRIEVAL_RERANKER_BACKEND` 开关。Reranker 参数优先使用 `RETRIEVAL_RERANKER_*`，缺失时才回退 `ROUTER_*`（最后回退 `OPENAI_*` 的 base/key）。
>
> `RETRIEVAL_EMBEDDING_DIM` 现在也会作为 OpenAI-compatible `/embeddings` 请求里的 `dimensions` 一起发送；如果 provider 明确不支持这个字段，运行时会自动重试一次不带 `dimensions` 的旧请求。无论是否发生这次重试，`RETRIEVAL_EMBEDDING_DIM` 仍应和最终实际返回的向量维度保持一致。
>
> 这里的 model id 只是占位示例，不是项目硬依赖。Memory Palace 不绑定某个固定 provider 或模型家族；请直接填写你自己的 OpenAI-compatible 服务里实际可用的 model id。
>
> 进阶配置（例如 `INTENT_LLM_*`、`RETRIEVAL_MMR_*`、`CORS_ALLOW_*`、运行时观测/睡眠整合开关）请以 `.env.example` 为准；本节只保留最常用主配置。
>
> 预置 Profile 配置文件位于 `deploy/profiles/` 目录下（macOS / Windows / Docker）。

---

*本文档基于 `backend/mcp_server.py` 源码生成，所有参数签名和行为描述均可追溯至代码实现。*
