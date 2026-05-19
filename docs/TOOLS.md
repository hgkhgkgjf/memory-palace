# Memory Palace — MCP 工具参考

Memory Palace 通过 [MCP](https://modelcontextprotocol.io/) 为 AI Agent 提供持久化记忆。本文档是 9 个 MCP 工具的完整参考。

## 目录

- [快速参考](#快速参考)
- [核心概念](#核心概念)
- [工具详情](#工具详情)
  - [read_memory](#read_memory)
  - [create_memory](#create_memory)
  - [update_memory](#update_memory)
  - [delete_memory](#delete_memory)
  - [add_alias](#add_alias)
  - [search_memory](#search_memory)
  - [compact_context](#compact_context)
  - [rebuild_index](#rebuild_index)
  - [index_status](#index_status)
- [返回值通用字段](#返回值通用字段)
- [降级机制](#降级机制)
- [推荐工作流](#推荐工作流)
- [检索配置](#检索配置)

---

## 快速参考

| 工具 | 类别 | 一句话说明 |
|---|---|---|
| `read_memory` | 读取 | 按 URI 读取记忆，支持整段 / 分片 / 范围读取 |
| `create_memory` | 写入 | 在父 URI 下创建新记忆 |
| `update_memory` | 写入 | 更新记忆内容、优先级或 disclosure |
| `delete_memory` | 写入 | 按 URI 删除记忆路径 |
| `add_alias` | 写入 | 为同一条记忆创建别名 URI |
| `search_memory` | 检索 | 关键词 / 语义 / 混合检索 |
| `compact_context` | 治理 | 将会话上下文压缩为持久化摘要 |
| `rebuild_index` | 维护 | 触发索引重建或 sleep-time 整合 |
| `index_status` | 维护 | 查询索引可用性、队列与运行时状态 |

---

## 核心概念

### URI 地址

Memory Palace 使用 `domain://path` 格式：

```
core://agent              ← 核心域下的 "agent" 路径
writer://chapter_1/scene  ← 写作域下的层级路径
system://boot             ← 系统内置 URI（只读）
```

URI 是 **Memory Palace 记忆地址**，不是文件路径。`C:/notes.txt` 这类 Windows 文件路径会被拒绝。

编码空格 / 编码斜杠（`core://foo%20bar`、`core://chapter_1%2Fscene_2`）兼容已有路径查找；解码后会变成文件路径的输入（如 `C%3A/...`）仍会拒绝。

**常用域**：

- `core` — 核心记忆（人格、偏好、关键事实）
- `writer` — 写作域（故事、章节）
- `system` — 系统保留（`boot` / `index` / `index-lite` / `audit` / `recent`），不可写入

> 优先级 `priority` 是整数，**数字越小优先级越高**（0 最高）。`true/false`、`1.9` 这类值会被拒绝。

### Write Guard

`create_memory` 和 `update_memory` 写入前会自动调用 **Write Guard**：

- 检测重复内容
- 建议合并（返回 `UPDATE` / `NOOP`）

决策方法包括 `keyword`、`embedding`、`llm`、`write_guard_llm`、`unknown`、`none`、`exception`。

---

## 工具详情

<a id="read_memory"></a>

### `read_memory`

按 URI 读取记忆。

```python
read_memory(
    uri: str,                       # 必填
    chunk_id: Optional[int] = None, # 可选，分片索引（0 起始）
    range: Optional[str] = None,    # 可选，字符范围（如 "0:500"）
    max_chars: Optional[int] = None,
    include_ancestors: Optional[bool] = False
)
```

**系统 URI**：

| URI | 用途 |
|---|---|
| `system://boot` | 加载核心记忆 + 最近记忆（每次会话启动调用） |
| `system://index` | 所有记忆的完整索引 |
| `system://index-lite` | gist 轻量索引摘要 |
| `system://audit` | 聚合观测/审计摘要 |
| `system://recent` | 最近修改的 10 条记忆 |
| `system://recent/N` | 最近修改的 N 条（最多 100） |

**返回**：

- 默认模式（无可选参数）：格式化纯文本
- 分片模式（传入任一可选参数）：JSON 字符串，含 `selection` 元信息

**示例**：

```python
read_memory("system://boot")
read_memory("core://agent/my_user")
read_memory("core://agent", chunk_id=0)
read_memory("core://agent", range="0:500")
```

> `chunk_id` 和 `range` 不能同时使用。

---

<a id="create_memory"></a>

### `create_memory`

在父 URI 下创建记忆。

```python
create_memory(
    parent_uri: str,              # 必填
    content: str,                 # 必填
    priority: int,                # 必填（数字越小优先级越高）
    title: Optional[str] = None,  # 路径名（Unicode 字母、数字、下划线、连字符）
    disclosure: str = ""          # 触发条件描述
)
```

**关键行为**：

1. 创建前自动 Write Guard 检查
2. Guard 判定 `NOOP` / `UPDATE` / `DELETE` 时拒绝创建，返回 `guard_target_uri` / `guard_target_id` 作为建议
3. Write Guard 临时异常导致 fail-closed 时，响应会带 `retryable=true` 和 `retry_hint`
4. `title` 只允许 Unicode 字母、数字、下划线、连字符
5. `content` 超过 `100000` 字符会被直接拒绝

**示例**：

```python
create_memory(
    "core://",
    "用户喜欢简洁的代码风格",
    priority=2,
    title="coding_style",
    disclosure="当我写代码或 review 代码时"
)
```

---

<a id="update_memory"></a>

### `update_memory`

更新已有记忆。

```python
update_memory(
    uri: str,                          # 必填
    old_string: Optional[str] = None,  # Patch 模式
    new_string: Optional[str] = None,  # Patch 模式
    append: Optional[str] = None,      # Append 模式
    priority: Optional[int] = None,
    disclosure: Optional[str] = None
)
```

**两种编辑模式（互斥）**：

| 模式 | 参数 | 说明 |
|---|---|---|
| **Patch** | `old_string` + `new_string` | 精确查找并替换。`old_string` 必须唯一命中 |
| **Append** | `append` | 追加到现有内容末尾 |

> **没有全量替换模式**。必须通过 `old_string` / `new_string` 明确指定修改内容。
>
> 更新前先 `read_memory` 确认内容。
>
> `old_string` / `new_string` / `append` 任一超过 `100000` 字符会被拒绝。
>
> 如果读取后到写入前记忆被其它会话修改，服务端会返回 `Memory version conflict` 错误。重新 `read_memory` 再操作即可。
>
> 如果 `guard_action=UPDATE` 且返回有效 `guard_target_id`，仍按**当前 URI 原地更新**。`guard_target_uri` 是提示，不是自动重定向。

**示例**：

```python
# Patch 模式
update_memory(
    "core://agent/my_user",
    old_string="旧的偏好描述",
    new_string="新的偏好描述"
)

# Append 模式
update_memory("core://agent", append="\n## 新章节\n这是追加的内容")

# 仅修改元数据（不触发 Write Guard）
update_memory("core://agent/my_user", priority=5)
```

---

<a id="delete_memory"></a>

### `delete_memory`

按 URI 删除记忆路径。

```python
delete_memory(uri: str)
```

- 删除的是 **URI 路径**，不是底层记忆正文
- 多个别名时，删除其中一个不影响其他别名
- 返回结构化 JSON：`ok` / `deleted` / `uri` / `message`

---

<a id="add_alias"></a>

### `add_alias`

为同一条记忆添加别名 URI。

```python
add_alias(
    new_uri: str,
    target_uri: str,
    priority: int = 0,
    disclosure: Optional[str] = None
)
```

- 支持跨域别名（如将 `writer://` 域的记忆链接到 `core://`）
- 控制字符、不可见格式字符、surrogate 会被拒绝
- alias 写入后 snapshot 记录失败会自动回滚，不会留下半成功状态

**示例**：

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

### `search_memory`

```python
search_memory(
    query: str,                                  # 必填（上限 8000 字符）
    mode: Optional[str] = None,                  # "keyword" / "semantic" / "hybrid"
    max_results: Optional[int] = None,
    candidate_multiplier: Optional[int] = None,
    include_session: Optional[bool] = None,
    filters: Optional[Dict] = None,
    scope_hint: Optional[str] = None,
    verbose: Optional[bool] = True
)
```

**检索模式**：

| 模式 | 说明 |
|---|---|
| `keyword` | FTS/BM25 优先；不安全查询回退到转义后的 LIKE |
| `semantic` | Embedding 向量语义搜索（需启用 embedding 链路：`hash` / `api` / `router` / `openai`） |
| `hybrid` | 关键词 + 语义混合，启用 Reranker 时继续重排 |

**过滤条件**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `domain` | `str` | 限定域 |
| `path_prefix` | `str` | 限定路径前缀 |
| `max_priority` | `int` | 只返回 priority ≤ 此值的记忆 |
| `updated_after` | `str` | ISO 时间过滤 |

**响应字段**：

| 字段 | 说明 |
|---|---|
| `query_effective` | 实际生效的查询文本 |
| `intent` | 意图分类：`factual` / `exploratory` / `temporal` / `causal` / `unknown` |
| `mode_applied` | 实际使用的检索模式 |
| `results` | 按 `score` 降序排列 |
| `results[].score` | 排序分数 |
| `degrade_reasons` | 降级原因（如有） |

**实用说明**：

- 默认 `verbose=true` 会带上调试信息（`query_preprocess`、`intent_profile`、`session_first_metrics` 等）；只关心结果时传 `verbose=false`
- `candidate_multiplier` 只是扩候选池的提示值，有硬上限；返回里看 `candidate_multiplier_applied`
- 保留语义查询（`AND` / `OR` / `NOT` / `NEAR` 等）会自动回退到安全 fallback

**示例**：

```python
search_memory("coding style")

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

### `compact_context`

将当前会话上下文压缩为持久化摘要。

```python
compact_context(
    reason: str = "manual",
    force: bool = False,
    max_lines: int = 12       # 最小 3
)
```

**产物**：

- **Gist**：简短摘要，用于快速回忆
- **Trace**：原始要点留痕

**Gist 生成链路（按优先级自动降级）**：

1. `llm_gist` — 调用 LLM 生成摘要（需配置 OpenAI-compatible API）
2. `extractive_bullets` — 提取式要点
3. `sentence_fallback` — 句子级降级

**响应字段**：

| 字段 | 说明 |
|---|---|
| `gist_method` | 当前 Gist 生成策略 |
| `quality` | Gist 质量分（0–1） |
| `source_hash` | Trace 源内容哈希 |
| `index_queued` / `index_dropped` / `index_deduped` | 索引入队统计 |
| `degrade_reasons` | 降级原因 |

> 同一 session 的 flush 会通过文件锁串行化；并发调用时返回 `already_in_progress`。

---

<a id="rebuild_index"></a>

### `rebuild_index`

触发索引重建或 sleep-time 整合。

```python
rebuild_index(
    memory_id: Optional[int] = None,     # 省略则全量重建
    reason: str = "manual",
    wait: bool = False,
    timeout_seconds: int = 30,
    sleep_consolidation: bool = False
)
```

**两种模式**：

| 模式 | 条件 | 行为 |
|---|---|---|
| **索引重建** | `sleep_consolidation=False`（默认） | 执行 rebuild_index / reindex_memory 队列任务 |
| **Sleep-time 整合** | `sleep_consolidation=True` | 离线扫描碎片和重复，生成清理预览 |

**Sleep-time 整合**：

- 默认 preview-only（不实际删除/写入）
- 设置 `RUNTIME_SLEEP_DEDUP_APPLY=1` 才执行重复清理
- 设置 `RUNTIME_SLEEP_FRAGMENT_ROLLUP_APPLY=1` 才写入 rollup gist
- `memory_id` 和 `sleep_consolidation=True` **不能同时使用**

**队列满载**：

- HTTP 返回 `503` + `index_job_enqueue_failed`
- MCP 返回 `ok=false` + `error=queue_full`

---

<a id="index_status"></a>

### `index_status`

查询检索索引可用性与运行时状态。无参数。

**返回字段**：

| 字段 | 说明 |
|---|---|
| `index_available` | 索引是否可用 |
| `degraded` | 是否降级 |
| `runtime.index_worker` | 队列深度、活跃任务、成功/失败/取消统计 |
| `runtime.sleep_consolidation` | Sleep 整合调度状态 |
| `runtime.write_lanes` | 写入通道状态 |

---

## 返回值通用字段

### Write Guard 字段

`create_memory` 和 `update_memory` 返回：

| 字段 | 可能值 | 说明 |
|---|---|---|
| `guard_action` | `ADD` / `UPDATE` / `NOOP` / `DELETE` / `BYPASS` | 决策动作 |
| `guard_reason` | 字符串 | 决策原因 |
| `guard_method` | `keyword` / `embedding` / `llm` / `write_guard_llm` / `unknown` / `none` / `exception` | 检测方法 |
| `guard_target_uri` / `guard_target_id` | 字符串 / 整数 | 建议复查或切换的目标（提示，非自动重定向） |

### 索引入队字段

`create_memory`、`update_memory`、`compact_context` 返回：

| 字段 | 说明 |
|---|---|
| `index_queued` | 实际入队任务数 |
| `index_dropped` | 未成功入队的任务数 |
| `index_deduped` | 去重后未重复入队的任务数 |

> `index_dropped > 0` 时表示有索引任务未能入队，结合 `degrade_reasons` 处理。

### Write-Lane 超时

`create_memory` / `update_memory` / `delete_memory` / `add_alias` / `compact_context`：

- write lane 塞满时响应带 `reason=write_lane_timeout`、`retryable=true`、`retry_hint`
- HTTP API 等价于结构化 `503`

---

## 降级机制

检索链路中，远程 Embedding / Reranker 不可用时系统**自动降级**并在响应中返回 `degrade_reasons`。  
写入链路中，`write_guard_exception` 会 fail-closed 拒绝写入。

**常见降级原因**：

| 原因 | 说明 |
|---|---|
| `embedding_fallback_hash` | Embedding API 不可用，回退到本地 hash |
| `embedding_request_failed` | Embedding 请求失败 |
| `embedding_dim_mismatch_requires_reindex` | 向量维度与配置不一致，需要重建索引 |
| `vector_dim_mixed_requires_reindex` / `vector_dim_mismatch_requires_reindex` | 当前作用域混入了多种维度，需要重建索引 |
| `reranker_request_failed` | Reranker 请求失败 |
| `path_revalidation_lookup_failed` | 路径状态复核失败；结果已丢弃 |
| `write_guard_exception` | Write Guard 异常，写入已被拒绝 |
| `query_preprocess_failed` | 查询预处理失败 |
| `index_enqueue_dropped` | 索引任务入队失败 |

> `embedding_request_failed` / `reranker_request_failed` 可能带细分后缀（`:timeout`、`:http_status:503`、`:api:timeout`）。先看主标记，再看后缀。
>
> 检测到降级时，可调用 `rebuild_index(wait=True)` + `index_status()` 尝试恢复。维度告警跟着**当前查询作用域**走，无关 domain 不会触发假的重建提示。

---

## 推荐工作流

### 标准会话流程

```
1. 会话启动  →  read_memory("system://boot")
                加载核心记忆 + 最近更新

2. 话题回忆  →  search_memory(query, include_session=True)
                URI 已知时直接 read_memory(uri)

3. 写入前检查 →  read_memory(uri) / search_memory
                 确认无重复 → create_memory / update_memory

4. 长会话压缩 →  compact_context(force=False)
                 系统自动判断

5. 降级恢复   →  rebuild_index(wait=True) → index_status()
                 检测到降级时重建并确认
```

详细 Skills 编排策略：[skills/MEMORY_PALACE_SKILLS.md](skills/MEMORY_PALACE_SKILLS.md)

---

## 检索配置

Profile C/D 使用混合检索（`keyword + semantic + reranker`），需要配置 OpenAI-compatible API：

```bash
# Embedding
RETRIEVAL_EMBEDDING_BACKEND=none      # none / hash / router / api / openai
RETRIEVAL_EMBEDDING_API_BASE=
RETRIEVAL_EMBEDDING_API_KEY=
RETRIEVAL_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_EMBEDDING_DIM=<provider-vector-dim>

# Reranker
RETRIEVAL_RERANKER_ENABLED=false
RETRIEVAL_RERANKER_API_BASE=
RETRIEVAL_RERANKER_API_KEY=
RETRIEVAL_RERANKER_MODEL=your-reranker-model-id

# 权重
RETRIEVAL_RERANKER_WEIGHT=0.40
RETRIEVAL_HYBRID_KEYWORD_WEIGHT=0.7
RETRIEVAL_HYBRID_SEMANTIC_WEIGHT=0.3
```

> **首要调参项**：`RETRIEVAL_RERANKER_WEIGHT`。`.env.example` 默认 `0.40`；shipped `Profile C/D` 模板分别使用 `0.30` / `0.35`。
>
> `RETRIEVAL_EMBEDDING_BACKEND` 仅控制 Embedding；Reranker 没有 `_BACKEND` 开关。Reranker 参数优先 `RETRIEVAL_RERANKER_*`，缺失时回退 `ROUTER_*`，再回退 `OPENAI_*`。
>
> 进阶配置（`INTENT_LLM_*`、`RETRIEVAL_MMR_*`、`CORS_ALLOW_*` 等）请以 `.env.example` 为准。完整档位配置见 [DEPLOYMENT_PROFILES.md](DEPLOYMENT_PROFILES.md)。
