# Memory Palace 部署档位（Deployment Profiles）

本文档帮助你根据自己的硬件条件和使用场景，选择合适的 Memory Palace 配置档位（A / B / C / D），并完成部署。

---

## 快速导航

| 章节 | 内容 |
|---|---|
| [1. 三步上手](#1-三步上手) | 最快了解如何开始 |
| [2. 档位一览](#2-档位一览) | A/B/C/D 四种配置的区别 |
| [3. 各档位详细配置](#3-各档位详细配置) | 每种档位的 `.env` 参数说明 |
| [4. 可选 LLM 参数](#4-可选-llm-参数writeguardcompact_contextintent) | 写入守卫、上下文压缩与意图增强 |
| [5. Docker 一键部署](#5-docker-一键部署推荐) | 推荐的容器化部署方式 |
| [6. 手动启动](#6-手动启动) | 不用 Docker 的本地启动方式 |
| [7. 本地推理服务参考](#7-本地推理服务参考) | Ollama / LM Studio / vLLM / SGLang |
| [8. Vitality 参数](#8-vitality-参数) | 记忆活力衰减与清理机制 |
| [9. API 鉴权](#9-api-鉴权) | Maintenance / SSE / Browse / Review 接口安全 |
| [10. 调参与故障排查](#10-调参与故障排查) | 常见问题与调优建议 |
| [11. 辅助脚本一览](#11-辅助脚本一览) | 所有部署相关脚本 |

---

## 1. 三步上手

1. **选择档位**：根据你的硬件选择 `A`、`B`、`C` 或 `D`（不确定就先选 **B** 跑通；如果你已经有稳定模型服务且明确需要更强语义检索，再考虑上 **C/D**）
2. **生成配置**：运行 `apply_profile` 脚本生成 `.env` 文件
3. **启动服务**：使用 Docker 一键部署 **或** 手动启动后端 + 前端

> `deploy/profiles/*/profile-*.env` 是模板输入，不是建议你直接复制提交或直接运行的最终 `.env`。面向用户的稳定路径仍然是先跑 `apply_profile.sh/.ps1`，再按实际环境微调生成结果。

> **💡 建议口径**：**Profile B 仍是默认起步档位**，因为它零外部依赖；`Profile C/D` 更适合作为“模型服务已经就绪后的深检索档位”，不是无感热切换。升级前，请先确认 embedding / reranker 可达、向量维度配置正确；如果当前库里已经写过旧向量，再用 `index_status()` 检查，必要时执行 `rebuild_index(wait=true)`，或者直接用新库验证。

---

## 2. 档位一览

| 档位 | 搜索模式 | Embedding 方式 | Reranker | 适用场景 |
|:---:|---|---|---|---|
| **A** | `keyword` | 关闭（`none`） | ❌ 关闭 | 最低配要求，纯关键词检索，快速验证 |
| **B** | `hybrid` | 本地哈希（`hash`） | ❌ 关闭 | **默认起步档位**，单机开发，无需额外服务 |
| **C** | `hybrid` | API 调用（`router`） | ✅ 开启 | 模型服务已就绪后的深检索档位，本地部署 embedding/reranker 模型服务 |
| **D** | `hybrid` | API 调用（`router`） | ✅ 开启 | 质量优先的远程 API 档位，无需本地 GPU |

**关键区别**：

- **A → B**：从纯关键词升级为混合检索，使用内置哈希向量（不依赖任何外部服务）
- **B → C/D**：接入真实的 embedding + reranker 模型后，有机会获得更强的语义检索；如果旧索引仍是另一套 embedding backend / model / dim 写出来的，运行时会先降级并要求重建索引
- **C vs D**：算法路径一致；默认模板中主要差异为模型服务地址（本地 vs 远程），并且默认 `RETRIEVAL_RERANKER_WEIGHT` 也不同（C=`0.30`，D=`0.35`）

> **口径说明（避免与评测文档混淆）**：部署模板描述的是你本地真正会写进 `.env` 的默认档位；`docs/EVALUATION.md` 负责汇总公开 A/B/C/D 复核里这些档位跑出来的结果。前者用于决定怎么配，后者用于理解这些档位在那轮复核里的表现；两边都不代表你可以在一批旧向量上无感热切换。
>
> **补充说明**：C/D 模板默认走 `router` 路线；如果你的部署不使用统一 router，也可以直接配置 `RETRIEVAL_EMBEDDING_*`、`RETRIEVAL_RERANKER_*`、`WRITE_GUARD_LLM_* / COMPACT_GIST_LLM_*` 连接 OpenAI-compatible 服务。
>
> **首启向导口径也一样**：向导里的 `Profile C` / `Profile D` 只是分别预填一组更像“本地/private router”或“远程 router”的建议起点，不代表你已经完成配置。真正保存前，仍然要把 router 的必填地址 / 模型字段换成你自己的真实值；如果你不走 router，也可以直接切到 `api` / `openai` embedding backend。`openai` 是 embedding backend 选项，不是额外新增的新档位。这里填写的 API base 口径也和后端一致：请填服务 base/root（通常到 `/v1`），不要手动写成 `/embeddings`、`/rerank`、`/chat/completions` 这种具体接口路径；常见尾缀会自动去掉，但格式不对或指到 link-local 的地址会直接 fail-closed。`127.0.0.1` / `::1` 这类 loopback IP 字面量，再加上 `localhost`，仍然默认允许；如果你故意把 provider base 指到其它 private IP 字面量，还要先通过 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS` 显式放行。还有一个现在需要明说的边界：在非 Docker 的本地 checkout 上，如果当前还没有已配置的 Dashboard auth，而你第一次用向导保存的又是需要远端 provider chain 的配置，后端会先只 bootstrap `MCP_API_KEY` / `MCP_API_KEY_ALLOW_INSECURE_LOCAL`；要让 `RETRIEVAL_EMBEDDING_*`、`RETRIEVAL_RERANKER_*`、`WRITE_GUARD_LLM_*`、`INTENT_LLM_*` 真正写进 `.env`，需要在 auth 生效后再保存一次。
>
> **本地模板补一条**：仓库内的本地 `profile c/d` 模板现在也显式保留 `RUNTIME_AUTO_FLUSH_ENABLED=true`，所以通过 `apply_profile.sh/.ps1` 生成的 `.env`，默认会和 A/B 一样继续保留 auto-flush。
>
> **为什么不强制一切都走 router**：
> - `embedding`、`reranker`、`llm` 三条链路的模型、地址、密钥和故障模式不同，分开配置更便于定位和替换。
> - 当前仓库已经支持分别直配：`RETRIEVAL_EMBEDDING_*`、`RETRIEVAL_RERANKER_*`、`WRITE_GUARD_LLM_* / COMPACT_GIST_LLM_*` 均可独立工作。
> - `router` 的主要价值在生产侧：统一入口、模型编排、鉴权、限流、审计和后续 provider 切换；它适合作为**默认模板口径**，但不是唯一支持方式。
>
>
> **配置优先级说明（避免误配）**：
> - `RETRIEVAL_EMBEDDING_BACKEND` 只影响 Embedding 链路，不影响 Reranker。
> - Reranker 没有 `RETRIEVAL_RERANKER_BACKEND` 开关；是否启用仅由 `RETRIEVAL_RERANKER_ENABLED` 控制。
> - Reranker 的地址/密钥优先读取 `RETRIEVAL_RERANKER_API_BASE/API_KEY`，缺失时才回退 `ROUTER_API_BASE/ROUTER_API_KEY`，最后回退 `OPENAI_BASE_URL/OPENAI_API_BASE` 与 `OPENAI_API_KEY`。

---

## 3. 各档位详细配置

### Profile A —— 纯关键词（最低配）

零依赖，仅使用关键词匹配：

```bash
# 核心配置（参见 deploy/profiles/linux/profile-a.env）
SEARCH_DEFAULT_MODE=keyword
RETRIEVAL_EMBEDDING_BACKEND=none
RETRIEVAL_RERANKER_ENABLED=false
RUNTIME_INDEX_WORKER_ENABLED=false    # 无需索引 worker
```

### Profile B —— 混合检索 + 本地哈希（默认）

使用内置的 64 维哈希向量，提供基础语义能力：

```bash
# 核心配置（参见 deploy/profiles/linux/profile-b.env）
SEARCH_DEFAULT_MODE=hybrid
RETRIEVAL_EMBEDDING_BACKEND=hash
RETRIEVAL_EMBEDDING_MODEL=hash-v1
RETRIEVAL_EMBEDDING_DIM=64
RETRIEVAL_RERANKER_ENABLED=false
RUNTIME_INDEX_WORKER_ENABLED=true     # 开启异步索引
RUNTIME_INDEX_DEFER_ON_WRITE=true
```

### Profile C/D —— 混合检索 + 真实模型（深检索档位）

C 和 D 的算法路径相同，均使用 `router` 后端调用 OpenAI-compatible API；默认模板中 D 的 reranker 权重更高（`0.35`）。

> **先说结论**：
> - **Profile B**：默认起步，先保证你今天就能跑起来
> - **Profile C**：模型服务已就绪后的深检索档位
> - **Profile D**：质量优先的远程 API 档位
>
> **升级到 Profile C 前最少要准备什么**：
> - Embedding：`RETRIEVAL_EMBEDDING_*`
> - Reranker：`RETRIEVAL_RERANKER_*`
> - 如果你还想启用 LLM 辅助的 write guard / gist / intent routing：再填写 `WRITE_GUARD_LLM_*`、`COMPACT_GIST_LLM_*`、可选的 `INTENT_LLM_*`
>
> **如果你现在只是做检索链路 smoke**：
> - **Profile C**：最少先把 Embedding 链路配通；仓库自带的 `profile-c` 模板默认仍会把 Reranker 一起打开
> - **Profile D**：沿用同一条 Embedding + Reranker 检索链路，但默认指向远程端点，且 reranker 权重更高
> - `WRITE_GUARD_LLM_*`、`COMPACT_GIST_LLM_*`、`INTENT_LLM_*` 不是检索 smoke 的硬前提
>
> 当前仓库附带的 real-profile helper 和这里的“最少准备什么”说法，只是在强调更深检索首先新增的是 Embedding 依赖；它**不等于**仓库自带 `profile-c` 模板会默认关闭 Reranker。`backend/tests/benchmark/helpers/profile_abcd_real_runner.py` 里的 helper 目前使用的是 benchmark-only 语义：`profile_c = API embedding 且不带 reranker`，`profile_d = API embedding + reranker`。而按当前模板，`Profile C` 仍是本地/private API 优先且默认启用 Reranker，`Profile D` 则是在同一条检索链路上切到 remote API 并给更高的默认 reranker 权重。本地小样本 smoke 也已经按这组实际模板重新核对过。这不是在说你可以对同一批旧向量“智能切档”。
>
> **再强调一次**：Profile B 默认是 64 维 hash 向量；Profile C/D 则取决于你实际配置的外部 embedding 维度。只要 backend / model / dim 变了，就要把“旧索引可能需要重建”当成前置条件，而不是当成故障后的附加排障动作。

**Profile C**（本地模型服务）——适合有 GPU 或使用 Ollama/vLLM 等本地推理：

```bash
# 核心配置（参见 deploy/profiles/linux/profile-c.env）
SEARCH_DEFAULT_MODE=hybrid
RETRIEVAL_EMBEDDING_BACKEND=router

# Embedding 配置
ROUTER_API_BASE=http://127.0.0.1:PORT/v1          # ← 替换 PORT 为实际端口
ROUTER_API_KEY=replace-with-your-key
ROUTER_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_EMBEDDING_API_BASE=http://127.0.0.1:PORT/v1
RETRIEVAL_EMBEDDING_API_KEY=replace-with-your-key
RETRIEVAL_EMBEDDING_DIM=<provider-vector-dim>

# Reranker 配置
RETRIEVAL_RERANKER_ENABLED=true
RETRIEVAL_RERANKER_API_BASE=http://127.0.0.1:PORT/v1
RETRIEVAL_RERANKER_API_KEY=replace-with-your-key
RETRIEVAL_RERANKER_MODEL=your-reranker-model-id
RETRIEVAL_RERANKER_WEIGHT=0.30                     # 推荐 0.20 ~ 0.40
```

如果你不使用统一 `router`，也可以直接配置 OpenAI-compatible embedding / reranker 服务：

```bash
# 直连 OpenAI-compatible 服务
RETRIEVAL_EMBEDDING_BACKEND=api
RETRIEVAL_RERANKER_ENABLED=true
RETRIEVAL_RERANKER_API_BASE=http://127.0.0.1:PORT/v1
RETRIEVAL_RERANKER_API_KEY=replace-with-your-key
# 下面两项按你的服务实际模型名填写
RETRIEVAL_EMBEDDING_MODEL=your-embedding-model-id
RETRIEVAL_RERANKER_MODEL=your-reranker-model-id
# 注意：不存在 RETRIEVAL_RERANKER_BACKEND 配置项
```

> 如果你走的是直连 API 路径，`RETRIEVAL_EMBEDDING_DIM` 请和 provider 实际返回的向量维度保持一致。当前代码不会替你猜这个值；它只会把这个值作为 OpenAI-compatible `/embeddings` 请求里的 `dimensions` 发出去。若 provider 明确不支持 `dimensions`，运行时会自动重试一次不带这个字段的旧请求。如果最终返回的真实维度还是和你的配置不一致，运行时现在会立刻拒绝这条向量并走 fallback / degrade，不会再静默写入一条错维度索引。`RETRIEVAL_EMBEDDING_API_BASE` / `RETRIEVAL_RERANKER_API_BASE` / `WRITE_GUARD_LLM_API_BASE` 这类地址也请统一写服务 base/root；常见接口尾缀会自动归一化，但 malformed / link-local 值会直接 fail-closed。`127.0.0.1` / `::1` 这类 loopback IP 字面量，再加上 `localhost`，仍然默认允许；如果你要直连其它 private IP 字面量，还要额外补上 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS`。
>
> 如果你本地用的是 Ollama 这类 OpenAI-compatible 路径，也优先走 `/v1/embeddings`；只有在模型本身确实返回某个固定维度时，再把 `RETRIEVAL_EMBEDDING_DIM` 填成那个真实值，不要照抄别处的 `1024` 或 `4096` 示例。
>
> 如果你已经用另一套维度写过索引，再把 `.env` 切到这里的直连配置，当前运行时不会帮你自动迁移旧向量。更稳的顺序是：先备份，再 `index_status()`，出现维度不一致告警就 `rebuild_index(wait=true)`，或者直接换一份新库验证。

**Profile D**（远程 API 服务）——无需本地 GPU，使用云端模型：

```bash
# 与 C 的主要区别：API 地址指向远程，且默认 reranker 权重更高
ROUTER_API_BASE=https://router.example.com/v1
RETRIEVAL_EMBEDDING_API_BASE=https://router.example.com/v1
RETRIEVAL_RERANKER_API_BASE=https://router.example.com/v1
RETRIEVAL_RERANKER_WEIGHT=0.35                     # 远程推荐略高
```

> **🔑 C/D 第一调参项**：`RETRIEVAL_RERANKER_WEIGHT`，建议范围 `0.20 ~ 0.40`，以 `0.05` 步长微调。
>
> **补一条口径区分**：这里的 `0.30 / 0.35` 仍是 shipped `Profile C/D` 模板的显式默认值；generic `.env.example` 里的运行时 fallback 默认值现在是 `0.40`，两者不是同一个层级。
>
> **模型 ID 提醒**：上面的 `your-embedding-model-id` / `your-reranker-model-id` 只是 shell-safe 占位示例。项目本身不绑定某个固定模型家族；请直接填写你自己的 provider 实际 model id。
> 如果你使用 `profile c/d`，无论是先跑 `apply_profile.sh/.ps1`，还是继续走 `docker_one_click.sh/.ps1`，这些占位 model id / endpoint / key 都会被当成未解析配置；脚本会先直接拦下，而不是等容器启动后再暴露错误。
> 像 `http://127.0.0.1:8001/v1` 这种真实本地 / private router 地址，本身**不算**占位值。真正会卡住保存或启动的，是 `https://router.example.com/v1`、`router-embedding-model`、`router-reranker-model`、`your-embedding-model-id`、`your-reranker-model-id` 这类文档示例值。

如果你采用直连方式，先注意一个边界：

- `docker_one_click.sh/.ps1` **不会直接读取你手改的仓库 `.env` 作为 Docker 最终配置**
- 它每次都会先基于 `deploy/profiles/docker/profile-*.env` 生成一份 Docker env，再按脚本参数决定是否注入运行时覆盖
- 所以如果你只是把最终直连配置写进仓库根的 `.env`，然后直接执行 `bash scripts/docker_one_click.sh --profile c`，实际启动的仍然是档位模板，不一定是你刚写进去的那套最终值

> 按当前复验结果，本地 `profile c/d + --allow-runtime-env-injection` 会按预期顺序工作：先基于模板生成 Docker env，再把这次运行的模板占位符校验延后，写入运行时注入值，最后仍然对缺失的外部配置做 fail-closed 检查。用人话说就是：模板里的占位符不再会在你真实值落盘前提前挡住本地联调，但缺失必填注入值时仍然会直接拦下。
>
> 对 native Windows PowerShell 路径来说，`docker_one_click.ps1` 后续对这个 Docker env 文件做运行时覆写时，现在也会继续保持 UTF-8 without BOM，不会再把同一个文件改写成 PowerShell 5.1 默认的 UTF-16 形态再交给 Docker Compose。
>
> 再补一条这次实测对齐过的边界：对 one-click 的 `profile c/d + --allow-runtime-env-injection` 路径来说，当前 shell 里的 loopback provider base（`127.0.0.1` / `localhost` / `::1`）现在会在生成的 Docker env 里自动改成 `host.docker.internal`，这样容器还能继续访问宿主机上的本地 router / chat 服务。这个被改写后的 host 也会追加进这次运行的 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS`，因为后端仍会按 private-address 规则校验 provider base；其它 private IP 字面量地址仍然保持原值，也只追加精确 host，不会顺手放宽成更大的信任范围。脚本不会把还没解析掉的 `host:PORT` 占位串当成可信 host 追加。如果你绕过 one-click，自己准备最终 Docker env，还是要手动写成容器可达地址。

最小验证建议分成两种：

```bash
# 方式 A：本地联调用一键脚本（显式注入）
# 适合你已经在当前 shell 里准备好了 embedding / reranker / LLM 的 API 地址、key、model
bash scripts/docker_one_click.sh --profile c --allow-runtime-env-injection
```

```bash
# 方式 B：验证你自己准备好的“最终 Docker env 文件”
# 这时请直接显式指定 MEMORY_PALACE_DOCKER_ENV_FILE，而不是指望一键脚本去读仓库 .env
MEMORY_PALACE_DOCKER_ENV_FILE=/absolute/path/to/your-docker.env docker compose up -d --build
```

然后再复验基础接口：

```bash
curl -fsS http://127.0.0.1:18000/health
curl -fsS http://127.0.0.1:18000/browse/node -H "X-MCP-API-Key: <YOUR_MCP_API_KEY>"
```

结果判定口径：

1. 请只拿**同一套最终部署配置**做对比和验收，不要混用不同链路的结果。
2. 对 `docker_one_click` 来说，`--allow-runtime-env-injection` 属于**本地联调路径**，不是“读取仓库 `.env` 作为最终 Docker 配置”的意思。
3. 如果你要验收真正准备上线的直连 Docker 配置，请直接拿那份最终 Docker env 文件做启动 + 健康检查。
4. 若占位 endpoint/key/model id 下启动失败，属于预期 fail-closed；请替换成真实可用值后再复验。

### 模型 ID 示例

这里建议你直接按“用途 -> 真实 model id”去填：

| 用途 | 建议写法 | 说明 |
|---|---|---|
| Embedding | `your-embedding-model-id` | 填你的 provider 实际 embedding model id |
| Reranker | `your-reranker-model-id` | 填你的 provider 实际 reranker model id |
| 可选 LLM | `your-chat-model-id` | 用于 `write_guard` / `compact_context` / `intent` |

无论你走 `router` 还是直连 API，项目都只是把这些字符串原样传给你的 OpenAI-compatible 服务；不会强制要求某个固定模型品牌或家族。

---

## 4. 可选 LLM 参数（write_guard / compact_context / intent）

这些参数控制三个可选的 LLM 功能：**写入守卫**（质量过滤）、**上下文压缩**（摘要生成）和**意图增强**（实验性分类增强）。

在 `.env` 中配置：

```bash
# Write Guard LLM（写入守卫，过滤低质量记忆）
WRITE_GUARD_LLM_ENABLED=false
WRITE_GUARD_LLM_API_BASE=             # OpenAI-compatible /chat/completions 端点
WRITE_GUARD_LLM_API_KEY=
WRITE_GUARD_LLM_MODEL=your-chat-model-id

# Compact Context Gist LLM（上下文压缩，生成摘要）
COMPACT_GIST_LLM_ENABLED=false
COMPACT_GIST_LLM_API_BASE=
COMPACT_GIST_LLM_API_KEY=
COMPACT_GIST_LLM_MODEL=your-chat-model-id

# Intent LLM（实验性意图分类增强）
INTENT_LLM_ENABLED=false
INTENT_LLM_API_BASE=
INTENT_LLM_API_KEY=
INTENT_LLM_MODEL=your-chat-model-id
```

> **回退机制**：当 `COMPACT_GIST_LLM_*` 未配置时，`compact_context` 会自动回退使用 `WRITE_GUARD_LLM_*` 的配置。两条链路均使用 OpenAI-compatible chat 接口（`/chat/completions`）。
>
> **说明**：这里的 model id 只起占位示例作用。只要你的服务兼容 OpenAI-style `/embeddings`、`/chat/completions` 或 reranker 端点，就可以改成你自己的实际 model id。
>
> 如果你的 provider 使用了不同的 model id 写法，请保持同一模型家族，并改成你自己的 provider 实际 model id。
>
> **补充说明**：`INTENT_LLM_*` 为实验性能力，关闭或不可用时会直接回退关键词规则，不影响默认检索路径。
>
> **完整高级配置**：`CORS_ALLOW_*`、`RETRIEVAL_MMR_*`、`INDEX_LITE_ENABLED`、`AUDIT_VERBOSE`、运行时观测/睡眠整合上限等不在本节逐项展开，统一以 `.env.example` 为准。
>
> **开启建议（推荐直接照这个来）**：
> - `INTENT_LLM_ENABLED=false`
>   - 适合默认生产 / 默认用户部署
>   - 只有在你已经有稳定 chat 模型、并且想增强模糊查询意图分类时再试
> - `RETRIEVAL_MMR_ENABLED=false`
>   - 默认先关
>   - 只有当 hybrid 检索前几条结果重复度明显偏高时，再打开看效果
> - `CORS_ALLOW_ORIGINS=`
>   - 本地开发建议留空，直接使用内建本地白名单
>   - 生产浏览器访问请显式写允许域名，不建议直接用 `*`
> - `RETRIEVAL_SQLITE_VEC_ENABLED=false`
>   - 当前仍属于 rollout 开关
>   - 普通用户部署默认不建议开；只有在维护阶段验证扩展路径、readiness 和回退链路时再启用

---

## 5. Docker 一键部署（推荐）

### 5.0 GHCR 预构建镜像（更适合本地构建总是失败的用户）

如果你遇到的核心问题是“本地镜像 build 总是失败”，优先走 GHCR 路径：

```bash
cd <project-root>
bash scripts/apply_profile.sh docker b .env.docker

docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

```powershell
cd <project-root>
.\scripts\apply_profile.ps1 -Platform docker -Profile b -Target .env.docker

docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

`apply_profile` 会从仓库模板生成 `.env.docker`，并在覆盖已有目标前先备份。

这条路径的定位是**先把服务跑起来**：

- 它绕开本地镜像 build。
- 但它仍然默认你手里有当前仓库 checkout，因为 compose 文件和 profile 脚本就在仓库里。
- 它覆盖的是 `Dashboard / API / SSE`。
- 它**不会**自动给你安装本机上的 `skills / MCP / IDE host` 配置。
- 如果你还想用当前仓库现成的 repo-local skill + MCP 安装链路，请继续看 `docs/skills/GETTING_STARTED.md`。
- 如果你只想让某个客户端连 MCP，不走 repo-local 安装链路，也可以手工把支持远程 SSE 的客户端指到 `http://localhost:3000/sse`。这里的 `<YOUR_MCP_API_KEY>` 默认就填刚生成的 `.env.docker` 里的 `MCP_API_KEY`。
- `scripts/run_memory_palace_mcp_stdio.sh` 不是这条 Docker 路径的客户端入口：它依赖本地 `bash` 和 `backend/.venv`，只会复用宿主机上的本地 `.env` / `DATABASE_URL`，不会复用容器里的 `/app/data`。
- 如果你后面要切回本机 `stdio` 客户端，本地 `.env` 必须写宿主机可访问的绝对路径；如果仓库里只有 `.env.docker` 而没有本地 `.env`，或者 `.env` / 显式 `DATABASE_URL` 仍写成 `/app/...` 或 `/data/...` 这类容器路径，它都会明确拒绝启动，并提示改走本机路径或 Docker 暴露的 `/sse`。
- 和 `docker_one_click.sh/.ps1` 不同，这条路径**不会自动换端口**。如果 `3000` / `18000` 已被占用，请显式设置 `MEMORY_PALACE_FRONTEND_PORT` / `MEMORY_PALACE_BACKEND_PORT`。
- 如果容器里的 C / D 档位还要访问**你宿主机上的本地模型服务**，不要把容器侧地址写成 `127.0.0.1`。对容器来说，这个地址只会回到容器自己，不会指向你的宿主机。优先使用 `host.docker.internal`（或你的实际可达宿主机地址）。当前 compose 已显式补 `host.docker.internal:host-gateway`，Linux Docker 现在也能沿这条路径访问宿主机服务。

本节下面剩余内容描述的是 **本地构建 / 维护者路径**，也就是 `docker_one_click.sh/.ps1`。

### 前置要求

- 已安装 [Docker](https://docs.docker.com/get-docker/) 并启动 Docker Engine
- 支持 `docker compose`（Docker Desktop 默认包含）

### macOS / Linux

```bash
cd <project-root>
bash scripts/docker_one_click.sh --profile b
# 如需把当前 shell 的 API 地址/密钥/模型注入本次运行的 Docker env 文件（默认关闭）：
bash scripts/docker_one_click.sh --profile c --allow-runtime-env-injection
```

### Windows PowerShell

```powershell
cd <project-root>
.\scripts\docker_one_click.ps1 -Profile b
# 如需把当前 PowerShell 进程环境注入本次运行的 Docker env 文件（默认关闭）：
.\scripts\docker_one_click.ps1 -Profile c -AllowRuntimeEnvInjection
```

> `apply_profile.ps1` 现已对 **所有重复 env key** 做“保留最后值”的统一去重，不再只处理 `DATABASE_URL`。
>
> 如果你是在 Linux / WSL 里的 PowerShell 环境运行 `apply_profile.ps1`，`-Platform linux` 现在也已可用；它会使用独立的 Linux 本地模板。原生 Windows 继续使用 `-Platform windows` 即可。
>
> 如果当前机器没有安装 `pwsh`，但你已经有 Docker，可直接运行 `bash scripts/smoke_apply_profile_ps1_in_docker.sh` 做一轮 repo-local 的 `apply_profile.ps1` 实际 smoke。
>
> 原生 Windows / `pwsh` 仍建议在目标环境单独补跑一次；这些步骤面向部署补验，不建议和新手入口文档混在一起读。
>
> `docker_one_click.sh/.ps1` 默认会为每次运行生成独立的临时 Docker env 文件，并通过 `MEMORY_PALACE_DOCKER_ENV_FILE` 传给 `docker compose`；只有显式设置该环境变量时才会复用指定路径，而不是固定共享 `.env.docker`。
>
> 对 macOS / Linux 的 shell 路径来说，如果你显式把 `MEMORY_PALACE_DOCKER_ENV_FILE` 指到自定义位置，`docker_one_click.sh` 现在也会在那个文件同目录生成临时文件再替换回去，减少目标文件不在默认临时目录时出现跨文件系统替换问题的概率。那条最终提交现在也会补一层有上限的小重试，短暂锁冲突不再那么容易直接打断整次 env 更新。
>
> 如果本次 Docker env 文件里的 `MCP_API_KEY` 为空，`apply_profile.sh/.ps1` 会自动生成一把本地 key，供 Dashboard 代理和 SSE 共用。
>
> 当前 compose 会先等 `backend` 的 `/health` 通过，同时一键脚本还会补做一次前端代理 `/sse` 的可达性检查，frontend 才算真正 ready。看到容器刚启动但浏览器还没通时，优先先等几秒，不要急着误判成部署失败。
>
> 对 macOS / Linux 的 shell 路径来说，`docker_one_click.sh` 现在还会对短暂的 `docker compose up` 失败补一层有上限的退避重试，再决定是否报硬失败。说人话就是：短暂的拉镜像、daemon 抖动或启动瞬时问题会再给一次机会；如果连续失败，或者本来就不是可重试错误，脚本仍会停下并打印最后一条真实错误。
>
> 同一 checkout 下的并发一键部署会被 deployment lock 串行化，避免共享 compose project / env 文件互相覆盖。
>
> WAL 安全边界：仓库默认只把 **named volume + WAL** 当成受支持的 Docker 路径。如果你把 backend `/app/data` 改成 NFS/CIFS/SMB 或其它网络文件系统 bind mount，就必须显式切回 `MEMORY_PALACE_DOCKER_WAL_ENABLED=false` 与 `MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete`。`docker_one_click.sh/.ps1` 现在会在 `docker compose up` 前做这层 preflight，并在发现高风险组合时直接拒绝启动；如果你绕过一键脚本，自己手动跑 `docker compose up`，则需要自己执行同样的检查。
>
> 运行时环境注入只给 `profile c/d` 使用。如果你把 `--allow-runtime-env-injection` / `-AllowRuntimeEnvInjection` 传给 `profile a/b`，脚本会在改动 Docker env 之前停止，避免轻量档位被本机 provider 环境变量意外改写。对 `profile c/d`，脚本会把这次运行切到显式 API 模式，并额外强制 `RETRIEVAL_EMBEDDING_BACKEND=api`。当前这条注入链路会一起覆盖：
>
> - 显式传入的 `RETRIEVAL_EMBEDDING_*`
> - 显式传入的 `RETRIEVAL_RERANKER_ENABLED` / `RETRIEVAL_RERANKER_*`
> - 可选的 `WRITE_GUARD_LLM_*`、`COMPACT_GIST_LLM_*`、`INTENT_LLM_*`
>
> 当 `RETRIEVAL_EMBEDDING_API_*` / `RETRIEVAL_RERANKER_API_*` 没显式提供时，它会优先复用当前进程里的 `ROUTER_API_BASE/ROUTER_API_KEY` 作为 embedding / reranker API base+key 的兜底；当 `RETRIEVAL_RERANKER_MODEL` 没显式提供时，也会优先复用 `ROUTER_RERANKER_MODEL`。
>
> 当前验证快照（2026-05-15）：Docker/Linux `Profile B/C/D` 都重新跑过。`Profile B` 使用项目原本设置，backend/frontend health 通过，`/sse` 返回 endpoint event，Dashboard 的 Memory / Observability / Maintenance 页面浏览器 smoke 没有 console error；同时复验了前端代理对 `/api/layering/*`、`/api/forgetting/*`、`/api/search/quality-metrics` 的受保护路由。`Profile C/D` 使用显式运行时注入和 1024 维外部 embedding / reranker 组合，容器内会把宿主机 loopback chat base 改成 `host.docker.internal` 并加入本次 allowlist；两档的 create/search/delete smoke 都通过，查询返回 `degrade_reasons=None`，SSE 与浏览器 smoke 也通过。本轮没有把原生 Windows / 原生 Linux host runtime benchmark 表重算。
>
> 本地 build 路径现在还会使用按 checkout 固定的本地镜像名。这样做的好处很直接：只要这个 checkout 里已经成功 build 过一次，后续即使切换 `COMPOSE_PROJECT_NAME`，`--no-build` 也还是能复用之前的本地镜像；只有第一次启动或手动删掉本地镜像时，才需要重新 build。

### 部署完成后的访问地址

| 服务 | 宿主机默认端口 | 容器内部端口 | 访问方式 |
|---|:---:|:---:|---|
| Frontend（Web UI） | `3000` | `8080` | `http://localhost:3000` |
| Backend（API） | `18000` | `8000` | `http://localhost:18000` |
| SSE（前端代理） | `3000` | `8080 -> 8000` | `http://localhost:3000/sse` |
| 健康检查 | `18000` | `8000` | `http://localhost:18000/health` |

### 一键脚本做了什么

1. 调用 profile 脚本从模板生成本次运行使用的 Docker env 文件（默认是 per-run 临时文件；仅当显式设置 `MEMORY_PALACE_DOCKER_ENV_FILE` 时才复用指定路径）
2. 默认禁用运行时环境注入，避免隐式覆盖模板；只有 `profile c/d` 可以显式开启注入，`profile a/b` 会直接拒绝这个开关。对 `profile c/d`，注入模式会额外强制 `RETRIEVAL_EMBEDDING_BACKEND=api` 用于本地联调；若显式 `RETRIEVAL_*` 未提供，则优先复用 `ROUTER_API_BASE/ROUTER_API_KEY` 作为 embedding / reranker API base+key 的兜底来源，并同步透传显式的 `RETRIEVAL_EMBEDDING_DIM` 与可选的 `INTENT_LLM_*`。对这条 one-click 路径来说，当前 shell 里的 loopback router / chat 类 API base 现在还会在生成的 Docker env 里自动改成 `host.docker.internal`，并把这个 host 追加进本次 allowlist；non-loopback private provider 字面量地址则保持原值，只把精确 host 追加进这次运行的 `MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS`。
3. 自动检测端口占用，若默认端口被占用则自动递增寻找空闲端口
4. 检测并注入 Docker 持久化卷：默认按 compose project 生成隔离卷名（数据库 `<compose-project>_data`，snapshot `<compose-project>_snapshots`）；如需复用旧卷，必须显式设置 `MEMORY_PALACE_DATA_VOLUME` / `MEMORY_PALACE_SNAPSHOTS_VOLUME`
5. 若 backend `/app/data` 被改成 NFS/CIFS/SMB 等网络文件系统 bind mount，且本次配置仍会启用 WAL，则在启动前直接 fail-fast
6. 对同一 checkout 的并发部署加 deployment lock，避免多次 `docker_one_click` 互相覆盖
7. 对 macOS / Linux 的 shell 路径，若 `docker compose up` 遇到短暂失败，会做几次小范围退避重试再决定是否放弃
8. 使用 `docker compose` 构建并启动后端和前端两个容器；默认拓扑下的 SSE 由 backend 承载，再通过 frontend 代理对外暴露

### 安全说明

- **Backend 容器**：以非 root 用户运行（`UID=10001`，见 `deploy/docker/Dockerfile.backend`）
- **Frontend 容器**：使用 `nginxinc/nginx-unprivileged` 镜像（默认 `UID=101`）
- Docker Compose 配置了 `security_opt: no-new-privileges:true`

### 停止服务

```bash
cd <project-root>
COMPOSE_PROJECT_NAME=<控制台打印出的 compose project> docker compose -f docker-compose.yml down --remove-orphans
```

> 上面的 `down --remove-orphans` 不会删除当前 compose project 对应的数据卷与 snapshot 卷；只有显式执行 `down -v`，或手动删除这些 volume 时，数据库和 Review snapshots 才会一起清空。

---

## 6. 手动启动

如果不使用 Docker，可以手动启动后端和前端。

### 第一步：生成 `.env` 配置

```bash
# macOS / Linux（默认先生成 Profile B 配置；Linux 也使用 `macos` 这个模板值）
cd <project-root>
bash scripts/apply_profile.sh macos b

# 如果你的 embedding / reranker 模型服务已经准备好，再切到 Profile C
# bash scripts/apply_profile.sh macos c

# Windows PowerShell
.\scripts\apply_profile.ps1 -Platform windows -Profile b

# 如果模型服务已经准备好，再切到 Profile C
# .\scripts\apply_profile.ps1 -Platform windows -Profile c
```

> 脚本执行逻辑：复制 `.env.example` 为生成后的环境文件，然后追加 `deploy/profiles/<platform>/profile-<x>.env` 中的覆盖参数。对本地平台，默认目标仍是 `.env`；如果你跑的是 `docker` 变体且没有显式传目标文件，默认目标现在会是 `.env.docker`。对 shell 路径来说，`apply_profile.sh` 还会按当前 checkout 自动改写常见的本地 `DATABASE_URL` 占位路径，包括 `/Users/...` 和 `/home/...`。macOS / Linux 下的 `apply_profile.sh` 现在还会在覆盖已有目标文件前先备份一份 `*.bak`；如果另一份 `apply_profile.sh` 正在写同一个目标文件，后来的进程会直接提示你稍后重试，而不是互相覆盖。它生成 staged / update 临时文件时，也会放到目标文件同目录，减少跨文件系统替换时的意外。这两类相邻临时文件提交现在还会补一层有上限的小重试，短暂的文件锁或索引器占用不再那么容易把整次改写打断。
>
> 原生 Windows PowerShell 现在也补齐了同样的保护逻辑。`apply_profile.ps1` 现在也会在覆盖前先备份 `*.bak`，如果另一份 `apply_profile.ps1` 正在写同一个目标文件，也会直接拒绝第二个写入，并且 staged 临时文件同样放在目标文件所在目录，而不是默认共享临时目录。最终 replace/move 这一步现在还会对常见的 Windows 短暂锁冲突补一层有上限的小重试。如果你只是想先看最终结果，可以用 `bash scripts/apply_profile.sh --dry-run ...`，或者在 PowerShell 下用 `.\scripts\apply_profile.ps1 -Platform windows -Profile b -DryRun` 做预览；这两条路径都只打印最终结果，不会真正改目标文件。
>
> `apply_profile.sh/.ps1` 当前会在生成结束后统一去重重复 env key，避免不同解析器对“同 key 多次出现”产生不一致行为。
>
> 把 `deploy/profiles/*/*.env` 理解成 **Profile 模板输入**，不要直接手抄某个模板文件当成最终 `.env`。像 macOS 模板里的 `DATABASE_URL` 会先保留占位路径，再由 `apply_profile.*` 按当前仓库位置自动改写；如果生成结果里还残留 `<...>` 或 `__REPLACE_ME__` 这类占位段，脚本或后端也会直接 fail-closed。
>
> 如果你只是第一次手动跑通仓库，先从 Profile B 开始最稳；只有在 embedding / reranker 链路都已经可用时，再切到 Profile C。

### 第二步：启动后端

```bash
cd <project-root>/backend
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# 如果你还要继续跑 backend 测试
# pip install -r requirements-dev.txt
uvicorn main:app --host 127.0.0.1 --port 18000
```

### 第三步：启动前端

```bash
cd <project-root>/frontend
npm install
MEMORY_PALACE_API_PROXY_TARGET=http://127.0.0.1:18000 npm run dev -- --host 127.0.0.1 --port 3000
```

如果你还想让 Vite 本机开发入口一起代理同源 SSE，再补一项：

```bash
MEMORY_PALACE_SSE_PROXY_TARGET=http://127.0.0.1:8010

这条 `/sse` 代理是刻意保留的本地开发路径，主要给 Vite 同源下的 SSE / MCP 调试复用；前端现在已经有共享的 `frontend/src/lib/sse.js` 来走这条路径。没有浏览器侧鉴权时它仍走轻量原生 `EventSource`；有鉴权时会切到可带 header 的 fetch-based SSE，并在非终态断流后自动重连。若浏览器里的 Dashboard 鉴权在运行中更新，下一次非终态重连会重新读取当前浏览器里的鉴权状态，不会固定沿用首次连接时的 header/bearer 快照。
```

这样 `/sse`、`/messages` 和 `/sse/messages` 也会一起转发到你本机单独启动的 `run_sse.py`，仅用于本地 Vite 开发入口联调。

---

## 7. 本地推理服务参考

如果使用 Profile C，需要在本地运行 embedding/reranker 模型。以下是常用的本地推理服务：

| 服务 | 官方文档 | 硬件建议 |
|---|---|---|
| Ollama | [docs.ollama.com](https://docs.ollama.com/gpu) | CPU 可跑；GPU 推荐按模型大小匹配 VRAM |
| LM Studio | [lmstudio.ai](https://lmstudio.ai/docs/app/system-requirements) | 建议 16GB+ RAM |
| vLLM | [docs.vllm.ai](https://docs.vllm.ai/en/stable/getting_started/installation/gpu.html) | Linux-first；NVIDIA 计算能力 7.0+ |
| SGLang | [docs.sglang.ai](https://docs.sglang.ai/index.html) | 支持 NVIDIA / AMD / CPU / TPU |

**OpenAI-compatible 接口文档**：

- Ollama：[OpenAI Compatibility](https://docs.ollama.com/api/openai-compatibility)
- LM Studio：[OpenAI Endpoints](https://lmstudio.ai/docs/app/api/endpoints/openai)

> **重要**：Memory Palace 的 embedding/reranker 均通过 OpenAI-compatible API 调用。若你开启了 reranker（C/D 默认开启），后端服务除 `/v1/embeddings` 外还需要可用的 rerank 端点（默认调用 `/rerank`）。

---

## 8. Vitality 参数

Vitality（活力值）系统用于自动管理记忆生命周期：**访问强化 → 自然衰减 → 候选清理 → 人工确认**。

| 参数 | 默认值 | 说明 |
|---|:---:|---|
| `VITALITY_MAX_SCORE` | `3.0` | 活力分上限 |
| `VITALITY_REINFORCE_DELTA` | `0.08` | 每次被检索命中后增加的分数 |
| `VITALITY_DECAY_HALF_LIFE_DAYS` | `30` | 衰减半衰期（天），30 天后活力值衰减一半 |
| `VITALITY_DECAY_MIN_SCORE` | `0.05` | 衰减下限，不会降到此值以下 |
| `VITALITY_CLEANUP_THRESHOLD` | `0.35` | 活力分低于此值的记忆列为清理候选 |
| `VITALITY_CLEANUP_INACTIVE_DAYS` | `14` | 不活跃天数阈值，配合活力分判定清理候选 |
| `RUNTIME_VITALITY_DECAY_CHECK_INTERVAL_SECONDS` | `600` | 衰减检查间隔（秒），默认 10 分钟 |
| `RUNTIME_CLEANUP_REVIEW_TTL_SECONDS` | `900` | 清理确认窗口（秒），默认 15 分钟 |
| `RUNTIME_CLEANUP_REVIEW_MAX_PENDING` | `64` | 最大待确认清理数 |

**调参建议**：

1. 先保持默认值，观察 1~2 周后再调整
2. 如果清理候选过多 → 提高 `VITALITY_CLEANUP_THRESHOLD` 或 `VITALITY_CLEANUP_INACTIVE_DAYS`
3. 如果确认窗口太短 → 调大 `RUNTIME_CLEANUP_REVIEW_TTL_SECONDS`

---

## 9. API 鉴权

以下接口受 `MCP_API_KEY` 保护（**fail-closed**：未配置 key 时默认返回 `401`）：

- `GET/POST/DELETE /maintenance/*`
- `GET/POST/PUT/DELETE /browse/*` 与 `GET/POST/DELETE /review/*`
- SSE 接口（`/sse` 与 `/messages`；本地可独立由 `run_sse.py` 启动，Docker 默认由 `backend` 进程内挂载承载）

### 请求头格式（二选一）

```
X-MCP-API-Key: <你的 MCP_API_KEY>
Authorization: Bearer <你的 MCP_API_KEY>
```

### 本地调试放行

设置 `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true` 可在本地调试时跳过鉴权：

- 仅对 loopback 请求生效（`127.0.0.1` / `::1` / `localhost`）
- 非 loopback 请求仍返回 `401`（附带 `reason=insecure_local_override_requires_loopback`）

> **MCP stdio 模式**不经过 HTTP/SSE 鉴权中间层，因此不受此限制。

### 前端访问受保护接口

**本地手动启动前后端**时，如果你只是本地调试，可以通过运行时注入 API Key（不建议在构建变量中写死）：

```html
<script>
  window.__MEMORY_PALACE_RUNTIME__ = {
    maintenanceApiKey: "<MCP_API_KEY>",
    maintenanceApiKeyMode: "header"   // 或 "bearer"
  };
</script>
```

> 不要把真实 `MCP_API_KEY` 写进公开页面、共享静态资源或会交付给最终用户的 HTML 里。浏览器里可以直接读取这个全局对象。面向他人的部署更推荐走服务端代理转发，而不是把 key 暴露到前端页面。

> 也兼容旧字段名：`window.__MCP_RUNTIME_CONFIG__`

**Docker 一键部署**时，不需要把 key 写进浏览器页面：

- 前端容器会在代理层自动给受保护的 Dashboard API 路径、`/sse`、`/messages` 带上同一把 `MCP_API_KEY`；通用 `/api/*` 不会一律注入这把 key
- 这把 key 默认保存在本次运行使用的 Docker env 文件里
- 浏览器只看到代理后的结果，不会直接拿到真实 key
- 也请把这个前端端口视为可信管理入口。如果你要把 `3000` 暴露到受信网络之外，请先在前面加上自己的 VPN、反向代理鉴权或网络访问控制。
- 如果你确实要做分离 origin 的管理面部署，可在 Docker env 里额外设置 `FRONTEND_CSP_CONNECT_SRC`；留空时默认仍是更保守的 `connect-src 'self'`。
- 如果你部署在共享主机上，又不想把资源限制硬编码进默认 compose，可从仓库根目录的 `docker-compose.override.example.yml` 复制一份 `docker-compose.override.yml` 再按机器规格调整。

### SSE 启动示例

```bash
HOST=127.0.0.1 PORT=8010 python run_sse.py
```

> 这里的 `HOST=127.0.0.1` 是本机回环调试示例；`python run_sse.py` 会优先尝试本机 `127.0.0.1:8000`，若 `8000` 已被主后端占用，则自动回退到 `127.0.0.1:8010`。如果你绑定的是 `HOST=localhost`，探测逻辑现在会把 `127.0.0.1` 当成必需检查，把 `::1` 当成尽力检查；对不支持 IPv6 loopback 的机器，不会再因为 `::1` 失败就误判 `8000` 已占用并跳到 `8010`。发生真正需要的回退时，当前启动日志也会明确打印最终 `/sse` 地址，并提醒你更新客户端配置或显式设置 `PORT`。若要给其他机器访问，请改成 `0.0.0.0`（或你的实际监听地址），并自行补齐 `MCP_API_KEY`、网络隔离、反向代理与 TLS 等保护。若你的远程 hostname / origin 也需要通过 MCP 传输层的 host/origin 校验，请显式补上 `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS`。Docker / Compose 场景下，SSE 现在直接由 `backend` 进程承载，再通过前端代理暴露出来。

Docker 一键部署时，直接使用：

```bash
http://localhost:3000/sse
```

> 如果你按上面的 GHCR compose 示例生成了 `.env.docker`，这里的 `<YOUR_MCP_API_KEY>` 默认就读 `.env.docker` 里的 `MCP_API_KEY`；若你走的是 `docker_one_click.*`，则读取本次运行使用的 Docker env 文件中的同名值。

---

## 10. 调参与故障排查

### 常见问题

| 问题 | 原因与解决 |
|---|---|
| 检索效果差 | 确认 `SEARCH_DEFAULT_MODE` 是否为 `hybrid`；C/D 档位检查 `RETRIEVAL_RERANKER_WEIGHT` 是否合理 |
| 模型服务不可用 | 系统会自动降级，检查响应中的 `degrade_reasons` 字段定位具体原因 |
| C/D 出现 `embedding_request_failed` / `embedding_fallback_hash` | 通常是外部 embedding/reranker 链路不可达（例如本机 router 未部署模型），不是后端主流程崩溃；按下方“C/D 降级信号快速排查”处理 |
| Docker 端口冲突 | 一键脚本会自动寻找空闲端口；也可手动指定（bash：`--frontend-port` / `--backend-port`，PowerShell：`-FrontendPort` / `-BackendPort`） |
| SSE 启动失败 `address already in use` | 释放占用的端口，或通过 `PORT=<空闲端口>` 切换 |
| 升级后数据库丢失 | 后端启动时会自动从历史文件名（`agent_memory.db` / `nocturne_memory.db` / `nocturne.db`）恢复 |

### C/D 降级信号快速排查（本地联调）

```bash
# 先检查服务是否真的起来
curl -fsS http://127.0.0.1:18000/health
```

1. 如果日志或返回结果里仍有 `embedding_request_failed` / `embedding_fallback_hash`，先检查 embedding / reranker 服务本身是否可达、API key 是否有效。
2. 直接检查真实调用端点，比只看配置文件更可靠：

```bash
curl -fsS -X POST <RETRIEVAL_EMBEDDING_API_BASE>/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <RETRIEVAL_EMBEDDING_API_KEY>" \
  -d '{"model":"<RETRIEVAL_EMBEDDING_MODEL>","input":"ping","dimensions":<RETRIEVAL_EMBEDDING_DIM>}'
curl -fsS -X POST <RETRIEVAL_RERANKER_API_BASE>/rerank \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <RETRIEVAL_RERANKER_API_KEY>" \
  -d '{"model":"<RETRIEVAL_RERANKER_MODEL>","query":"ping","documents":["pong"]}'
```

> 如果你的本地服务本身不要求 API key，就把 `Authorization` 这一行去掉。若 embedding provider 明确拒绝 `dimensions`，运行时会自动重试一次不带这个字段的旧请求，但最终返回的向量维度仍然要和 `RETRIEVAL_EMBEDDING_DIM` 保持一致。

3. 如果只是当前机器排障，可以临时改成 `RETRIEVAL_EMBEDDING_BACKEND=api` 并分别直配 embedding / reranker / llm；上线前再恢复到目标环境的 `router` 配置并复验一次。

### PowerShell / Windows 验证建议

- `scripts/apply_profile.sh` 与 `scripts/apply_profile.ps1` 都会对重复 env key 做统一去重。
- 如果你用 Docker 做 `pwsh-in-docker` 等效验证，`docker_one_click.ps1` 当前会优先使用 `Get-NetTCPConnection` 做端口探测；当这个 Windows cmdlet 不可用时，会自动回退到 `ss`。如果目标环境两者都没有，请显式指定固定端口，或直接在目标 Windows 机器上复验。
- 如果你要交付 Windows 环境，建议直接在目标 Windows 机器上按同一份模板跑一次启动与 smoke。
- 主文档只保留公开可执行的步骤；目标环境专项验证建议单独记录。

### 调参提示

1. **`RETRIEVAL_RERANKER_WEIGHT`**：过高会过度依赖重排序模型，建议以 `0.05` 步长调试
2. **Docker 数据持久化**：默认同时使用按 compose project 隔离的两个卷（`<compose-project>_data` 挂载 `/app/data`，`<compose-project>_snapshots` 挂载 `/app/snapshots`），分别持久化数据库与 review snapshots（见 `docker-compose.yml`）
3. **旧版兼容**：一键脚本自动识别旧版 `NOCTURNE_*` 环境变量和历史数据卷
4. **迁移锁**：`DB_MIGRATION_LOCK_FILE`（默认 `<db_file>.migrate.lock`）和 `DB_MIGRATION_LOCK_TIMEOUT_SEC`（默认 `10` 秒）用于防止多进程并发迁移冲突

---

## 11. 辅助脚本一览

| 脚本 | 说明 |
|---|---|
| `scripts/apply_profile.sh` | 从模板生成环境文件（本地平台默认 `.env`；`docker` 且未显式传目标时默认 `.env.docker`） |
| `scripts/apply_profile.ps1` | 从模板生成环境文件（本地平台默认 `.env`；`docker` 且未显式传目标时默认 `.env.docker`） |
| `scripts/docker_one_click.sh` | Docker 一键部署（macOS / Linux） |
| `scripts/docker_one_click.ps1` | Docker 一键部署（Windows PowerShell） |

### 配置模板文件结构

```
deploy/profiles/
├── macos/
│   ├── profile-a.env
│   ├── profile-b.env
│   ├── profile-c.env
│   └── profile-d.env
├── windows/
│   ├── profile-a.env
│   ├── profile-b.env
│   ├── profile-c.env
│   └── profile-d.env
└── docker/
    ├── profile-a.env
    ├── profile-b.env
    ├── profile-c.env
    └── profile-d.env
```
