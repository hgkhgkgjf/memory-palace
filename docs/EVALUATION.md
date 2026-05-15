# Memory Palace 评测结果

本文档汇总 Memory Palace 各档位（A/B/C/D）的检索质量、延迟与语义质量门禁测试结果。这里保留**摘要表 + 复核说明**；公开仓库会保留 `backend/tests/benchmark/` 下的 benchmark helpers 与测试入口，机器相关的原始 benchmark 日志、一次性门禁草稿、阶段性重测记录以及部分指标 JSON 默认只在开发阶段或本地使用。

> 状态说明（2026-04 / 2026-05）：本页保留 2026-02 的公开基线表格，同时把 2026-04-17 的真实 A/B/C/D 复核、2026-04-18 的当前 rerun、2026-04-21 的修复后复核一起收口到公开口径里。2026-05-15 这轮 review session 里，backend 测试 `1382 passed, 22 skipped`，frontend 测试 `203 passed`，frontend build/typecheck、i18n audit、bundle budget、repo-local live MCP e2e，以及 Docker/profile/SSE/script 的重点契约测试都通过。本轮没有重算本页 benchmark 表格。当前交互默认档位、深检索档位和新的门禁项，请优先看本页第 3 节和第 4 节。

---

## 1. 数据来源

| 来源 | 说明 |
|---|---|
| 本页公开摘要表 | 面向用户保留的 A/B/C/D 关键指标和门禁结果 |
| `backend/tests/benchmark/` 下的公开 benchmark helpers 与测试用例 | 用于理解评测口径；具体指标文件通常仍以维护阶段或本地复核产物为主 |
| 维护期 benchmark 产物 | 一次性重测日志、门禁草稿和本机运行结果；默认不随用户仓分发 |
| 当前发布说明 | `docs/changelog/release_v3.7.1_2026-03-26.md` |
| 发布对比摘要 | `docs/changelog/release_summary_vs_old_project_2026-03-06.md` |

> 数据生成时间：`2026-02-19T06:55:30+00:00`（早期门禁基线）/ `2026-04-17T10:35:51+00:00`（当前公开验证）/ `2026-04-18T06:31:05+00:00`（本 session rerun）/ `2026-04-21`（修复后复核刷新；benchmark 表未重跑）/ `2026-05-15`（Docker/Linux Profile B/C/D 复核；benchmark 表未重跑）

> 工件路径补充：当前公开 benchmark helpers 默认把运行产物写到系统临时目录下的 `memory-palace-benchmark-artifacts/<run-token>/...`；如果你要固定路径，显式传 `artifact_dir` 或设置 `BENCHMARK_ARTIFACT_DIR` 即可。这样并行 benchmark 不会把临时工件带进工作树。

---

## 1.5 这些指标到底在看什么？

先说人话：

- **HR@10**：前 10 条结果里，**有没有**把正确答案找出来。越高越好。
- **MRR**：正确答案排得**靠不靠前**。越靠前，分数越高。
- **NDCG@10**：不只看“找没找到”，还看**排序整体好不好**。越高越好。
- **Recall@10**：如果一条查询可能有多个相关结果，它看前 10 条里**覆盖了多少**。越高越好。
- **p50 / p95**：响应时间。`p50` 可以理解成“平时大多数请求有多快”，`p95` 可以理解成“慢的时候大概慢到什么程度”。
- **降级率**：系统因为外部 embedding / reranker 不可用而退回低配模式的比例。越低越好。

如果你只想快速看表，优先看这三个：

1. **HR@10**：能不能找到
2. **MRR**：找到了以后排得靠不靠前
3. **p95**：最慢那批请求慢不慢

---

## 2. 检索评测（A/B/CD 小样本门禁）

**来源**：当前最新一轮 run-scoped benchmark 产物 `memory-palace-benchmark-artifacts/<run-token>/profile_ab_metrics.json`（`sample_size=100`，每档 3 个数据集 × 100 条查询；通常由 `backend/tests/benchmark/` 下的 benchmark helpers 在维护阶段生成）

| 档位 | 模式 | 数据集 | HR@10 | MRR | NDCG@10 | Recall@10 | p50(ms) | p95(ms) | 降级率 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| A | keyword | MS MARCO | 0.333 | 0.333 | 0.333 | 0.333 | 1.2 | 2.1 | 0.0% |
| A | keyword | BEIR NFCorpus | 0.300 | 0.300 | 0.300 | 0.300 | 1.6 | 2.6 | 0.0% |
| A | keyword | SQuAD v2 Dev | 0.150 | 0.150 | 0.150 | 0.150 | 1.2 | 3.0 | 0.0% |
| B | hybrid | MS MARCO | 0.867 | 0.658 | 0.696 | 0.850 | 3.4 | 3.7 | 0.0% |
| B | hybrid | BEIR NFCorpus | 1.000 | 0.828 | 0.850 | 0.975 | 4.1 | 4.7 | 0.0% |
| B | hybrid | SQuAD v2 Dev | 1.000 | 0.765 | 0.822 | 1.000 | 3.2 | 3.9 | 0.0% |
| CD | hybrid | （与 B 同配置基线） | 同 B | 同 B | 同 B | 同 B | 同 B | 同 B | 0.0% |

> **说明**：CD 门禁使用与 B 相同的 hash embedding 基线运行，目的是验证 hybrid 检索路径的正确性。

---

## 3. 检索评测（真实 A/B/C/D 运行）

**来源**：当前最新一轮 run-scoped real-run 产物 `memory-palace-benchmark-artifacts/<run-token>/profile_abcd_real_metrics.json`（`sample_size_requested=8`，2 个数据集 × 8 条查询；通常由 `backend/tests/benchmark/` 下的 benchmark helpers 在维护阶段生成）

策略：每条查询按 `first_relevant_only=true` 仅保留首个相关文档，额外灌入 `200` 条干扰文档，`candidate_multiplier=8`，随机种子 `20260219`。

| 档位 | 数据集 | HR@10 | MRR | NDCG@10 | p50(ms) | p95(ms) | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| A | SQuAD v2 Dev | 0.000 | 0.000 | 0.000 | 5.179 | 7.920 | ✅ PASS |
| A | BEIR NFCorpus | 0.250 | 0.250 | 0.250 | 8.218 | 13.576 | ✅ PASS |
| B | SQuAD v2 Dev | 0.125 | 0.062 | 0.079 | 33.801 | 52.227 | ✅ PASS |
| B | BEIR NFCorpus | 0.250 | 0.250 | 0.250 | 40.857 | 44.675 | ✅ PASS |
| C | SQuAD v2 Dev | 1.000 | 0.896 | 0.920 | 219.999 | 298.780 | ✅ PASS |
| C | BEIR NFCorpus | 0.625 | 0.531 | 0.554 | 212.338 | 259.681 | ✅ PASS |
| D | SQuAD v2 Dev | 1.000 | 0.896 | 0.920 | 2452.644 | 2764.629 | ✅ PASS |
| D | BEIR NFCorpus | 0.750 | 0.656 | 0.679 | 3155.158 | 3409.331 | ✅ PASS |

> **说明**：
>
> - `Profile B` 仍然是**默认交互档**：延迟最低，适合 CLI / IDE 日常 recall。
> - `Profile C` 是**显式深检索档**：在这套 benchmark helper 口径里，它走的是 `hybrid + API embedding`，**不带 reranker**，质量明显高于 B，p95 仍在百毫秒级。
> - `Profile D` 仍然是**最高质量档**：在同一套 helper 口径里，它是在 `Profile C` 基础上再加 reranker，所以质量最高，但 p95 已到秒级，只适合“质量优先于时延”的场景。
> - 这套 real benchmark helper 的 `Profile C/D` 是维护期评测契约，不等于 shipped deployment templates 里的 `Profile C/D` 默认值与默认开关。
> - 这轮 C/D 指标是基于**运行时注入的、用户显式提供的 embedding 维度**得到的；公开模板现在不再发布 `4096` 这类猜测默认值。
> - 当前 real runner 还会把**查询阶段**与**建索引阶段**的降级一起记进公开门禁口径；其中 embedding 侧降级会影响 C/D，reranker 缺配置或响应无效这类无效原因则主要属于 D 的 gate 语义，不再被写成“干净 PASS”。
> - 这轮结果是在**当前档位的有效 embedding 维度已经对齐**的前提下得到的，不表示你可以把 B 的旧向量和 C/D 的旧向量拿来直接混用；如果切档后维度不一致，当前运行时会返回 `embedding_dim_mismatch_requires_reindex` / `vector_dim_mismatch_requires_reindex`，需要重建索引或分开数据库。
> - 所有 Phase 6 Gate 均为 PASS，表明当前公开档位在这轮复核里没有出现失效或请求失败。

### 3.1 这轮 2026-04-17 复核该怎么读

- 如果你只想要**默认推荐**：选 `Profile B`。
- 如果你明确知道自己在做**深检索 / 高质量优先**：显式切到 `Profile C` 或 `Profile D`。
- `Profile C` 和 `Profile D` 都不是默认 recall 档，它们是按需打开的深检索档。

按两个数据集做均值之后，这轮公开复核的摘要是：

| 档位 | Avg HR@10 | Avg MRR | Avg NDCG@10 | Avg Recall@10 | Avg p95(ms) |
|---|---:|---:|---:|---:|---:|
| A | 0.125 | 0.125 | 0.125 | 0.125 | 10.7 |
| B | 0.188 | 0.156 | 0.164 | 0.188 | 48.5 |
| C | 0.812 | 0.714 | 0.737 | 0.812 | 279.2 |
| D | 0.875 | 0.776 | 0.799 | 0.875 | 3087.0 |

### 3.2 2026-04-18 当前 rerun（本 session）

这轮 rerun 只覆盖 `squad_v2_dev`，参数是：

- `dataset_scope=squad_v2_dev`
- `sample_size=2`
- `extra_distractors=20`
- `candidate_multiplier=8`

它的作用很直接：确认当前代码和 `A/B/C/D` 四档 profile 还能按现在这套实现跑通，不拿它替代上面那组范围更大的公开基线。

| 档位 | 数据集 | HR@10 | NDCG@10 | p95(ms) |
|---|---|---:|---:|---:|
| A | SQuAD v2 Dev | 0.0 | — | 2.264 |
| B | SQuAD v2 Dev | 1.0 | 0.667 | 6.687 |
| C | SQuAD v2 Dev | 1.0 | 1.0 | 666.607 |
| D | SQuAD v2 Dev | 1.0 | 1.0 | 1261.532 |

这轮结果怎么读：

- `Profile B` 还是默认交互档，质量已经明显高于 A，延迟也还很低。
- `Profile C/D` 这轮质量都跑满了，但时延明显更高，属于按需打开的深检索档。
- `Profile A` 依旧只是低配兜底，不适合拿来代表语义检索质量。
- 后续 2026-04-21 的修复后复核重跑了完整 backend/frontend 测试、frontend build/typecheck、repo-local live MCP e2e 和 repo-local `Profile B` 真实浏览器 smoke；同一轮还补做了一次 `BEIR NFCorpus` 小样本 real A/B/C/D 复核，`Profile D` 的 Phase 6 Gate 继续 `PASS`。2026-05-15 又补跑了 Docker/Linux `Profile B/C/D` 的启动、SSE、浏览器 smoke 和 C/D create/search/delete。这里两轮都没有重算这张 benchmark 表。

### 3.3 2026-04-20 同配置 follow-up（默认 reranker 权重）

这轮 follow-up 不是新公开基线，而是针对同配置 maintenance rerun 里 `Profile D` 的 rerank 融合回退做的一次补充复核。

- 对照的是同一组 `sample_size=8`、`extra_distractors=200`、`candidate_multiplier=8` 的小样本 real-run 口径。
- 当 generic runtime 默认 `RETRIEVAL_RERANKER_WEIGHT` 还是 `0.25` 时，`Profile D` 在 `BEIR NFCorpus` 上出现过一轮回退：`MRR=0.59375`、`NDCG@10=0.632701`。
- 把 generic runtime 默认值调回 `0.40` 后，同配置 follow-up 下 `Profile D` 的 `BEIR NFCorpus` 回到 `HR@10=0.750`、`MRR=0.65625`、`NDCG@10=0.678835`，`p95≈3158ms`。
- 这条 follow-up 只说明 D 档位的 rerank 融合默认值已经按当前仓库真值收口，不代表 shipped `Profile C/D` 模板的显式权重也跟着变成 `0.40`。

## 3.5 旧版 vs 当前版本（同口径摘要）

下面这组数字来自一轮**同口径旧新对照复核**。这里保留摘要，不保留带本机路径的原始对照记录。

![旧版 vs 当前版本检索质量与延迟对比图](images/benchmark_comparison.png)

> 📈 这张图对应的是**旧版 vs 当前版本**在同口径下的对照结果。
>
> 读图时可以先看：
>
> - 左上 `HR@10`：前 10 条里有没有找到
> - 右下 `p95 latency`：慢的时候大概慢到什么程度
> - 页脚那行 `cm=8 avg`：表示新版把候选池继续放大后的上限表现

---

### 高干扰场景的核心结论

| 场景 | 指标 | 旧版 C | 新版 C | 旧版 D | 新版 D |
|---|---|---:|---:|---:|---:|
| `s8,d10` | `HR@10` | 0.875 | 0.875 | 0.875 | 0.875 |
| `s8,d200` | `HR@10` | 0.313 | 0.563 | 0.375 | 0.625 |
| `s100,d200` | `HR@10` | 0.280 | 0.580 | 0.295 | 0.615 |

### 更细一点看：MRR / NDCG@10

| 场景 | 指标 | 旧版 C | 新版 C | 旧版 D | 新版 D |
|---|---|---:|---:|---:|---:|
| `s8,d10` | `MRR / NDCG@10` | 0.783 / 0.805 | 0.783 / 0.805 | 0.825 / 0.837 | 0.825 / 0.837 |
| `s8,d200` | `MRR / NDCG@10` | 0.313 / 0.313 | 0.563 / 0.563 | 0.375 / 0.375 | 0.625 / 0.625 |
| `s100,d200` | `MRR / NDCG@10` | 0.247 / 0.255 | 0.512 / 0.529 | 0.268 / 0.275 | 0.560 / 0.573 |

### 怎么读这组数据

- `s8,d10`：低难度场景，**持平**
- `s8,d200`：干扰一多，新版提升就很明显
- `s100,d200`：样本更大、干扰更多时，新版依然明显更稳

一句话总结：

> 如果你关心的是真实复杂检索，而不是最简单的演示场景，那么当前版本相对旧版本确实更强。

### 这些参数顺手解释一下

- `s8,d10`：`s=sample_size`，`d=extra_distractors`。可以理解成“8 条样本 + 10 条干扰文档”。
- `s8,d200`：样本还是 8 条，但干扰文档拉到 200 条，更容易把真正结果淹没。
- `s100,d200`：100 条样本 + 200 条干扰文档，更接近真实复杂检索。
- `candidate_multiplier=4 / 8`：检索第一轮先放大候选池，再做后续排序。数字越大，通常**质量更有机会提升**，但**时延也更容易上去**。

### 延迟补充

| 场景 | 仓库 | C p95(ms) | D p95(ms) |
|---|---|---:|---:|
| `s8,d10` | 旧版 | 474.5 | 2103.2 |
| `s8,d10` | 新版 | 639.5 | 2088.2 |
| `s8,d200` | 旧版 | 945.8 | 2507.1 |
| `s8,d200` | 新版 | 1150.9 | 2428.8 |
| `s100,d200` | 旧版 | 1027.8 | 2796.5 |
| `s100,d200` | 新版 | 937.6 | 2772.0 |

这里也要说人话：

- 新版的主收益是**检索质量更高**
- 不是所有场景都更快
- 但在 `s100,d200` 这种更接近真实复杂检索的场景里，延迟并没有明显变坏

### 新版增强口径（补充）

在 `s100,d200` 场景下，如果把新版的 `candidate_multiplier` 从 `4` 调到 `8`，3 次重复均值为：

- C：`HR@10=0.700`、`MRR=0.607`、`NDCG@10=0.630`
- D：`HR@10=0.720`、`MRR=0.651`、`NDCG@10=0.668`

这说明新版还有进一步调优空间，但代价是更高的候选池和更高的时延。

---

## 4. 质量门禁（语义相关）

### Write Guard（写入守卫）

**来源**：当前最新一轮 run-scoped 产物 `memory-palace-benchmark-artifacts/<run-token>/write_guard_quality_metrics.json`（通常由 benchmark helpers 在维护阶段生成）

| 指标 | 值 | 阈值 | 状态 |
|---|---:|---:|---|
| Precision | 1.000 | ≥ 0.90 | ✅ PASS |
| Recall | 1.000 | ≥ 0.85 | ✅ PASS |

- 总测试用例数：**6**（TP=4, FP=0, FN=0）
- 决策类型分布：`NOOP`×2, `UPDATE`×2, `ADD`×2
- 综合判定：**overall_pass = true**

怎么理解这组指标：

- **Precision（精确率）**：系统说“该拦 / 该改”的时候，判断有多准。越高越好。
- **Recall（召回率）**：真正该拦 / 该改的情况，它漏掉了多少。越高越好。
- 这组测试的目标不是看“文笔”，而是看 **Write Guard 会不会误拦、漏拦**。

### Intent 分类（查询意图识别）

**来源**：当前最新一轮 run-scoped 产物 `memory-palace-benchmark-artifacts/<run-token>/intent_accuracy_metrics.json`（通常由 benchmark helpers 在维护阶段生成）

| 指标 | 值 | 阈值 | 状态 |
|---|---:|---:|---|
| Accuracy | 1.000 | ≥ 0.80 | ✅ PASS |

- 总测试用例数：**6**
- 分类方法：`keyword_scoring_v2`（纯规则，无外部模型依赖）
- 覆盖意图：`temporal`×2, `causal`×2, `exploratory`×1, `factual`×1
- 策略模板映射：
  - `temporal` → `temporal_time_filtered`
  - `causal` → `causal_wide_pool`
  - `exploratory` → `exploratory_high_recall`
  - `factual` → `factual_high_precision`

怎么理解：

- 这里测的不是“答得好不好”，而是系统能不能先判断出：这条查询更像**事实查询、探索查询、时间查询还是因果查询**。
- 判断对了，后面的检索策略才更容易选对。

### Gist 质量（上下文压缩摘要）

**来源**：当前最新一轮 run-scoped 产物 `memory-palace-benchmark-artifacts/<run-token>/compact_context_gist_quality_metrics.json`（通常由 benchmark helpers 在维护阶段生成）

| 指标 | 值 | 阈值 | 状态 |
|---|---:|---:|---|
| ROUGE-L（均值） | 0.759 | ≥ 0.40 | ✅ PASS |

- 总测试用例数：**5**
- 各 case ROUGE-L 分布：

| Case | ROUGE-L |
|---|---:|
| gist-001 | 0.824 |
| gist-002 | 0.923 |
| gist-003 | 0.667 |
| gist-004 | 0.667 |
| gist-005 | 0.714 |

怎么理解：

- **ROUGE-L** 可以简单理解成：生成的 gist 和参考摘要在“关键内容重合度”上有多接近。
- 它不是“最终写作质量分”，而是看压缩后**有没有把关键意思留下来**。

### Prompt Safety（反射提示安全契约）

**来源**：当前最新一轮 run-scoped 产物 `memory-palace-benchmark-artifacts/<run-token>/prompt_safety_contract_metrics.json`（通常由 benchmark helpers 在维护阶段生成）

| 指标 | 值 | 阈值 | 状态 |
|---|---:|---:|---|
| Contract pass rate | 1.000 | ≥ 1.000 | ✅ PASS |

- 工件契约：当前这份 JSON 现在还会显式带 `schema_version: "v1"`。
- 关注点：system prompt 是否明确把输入当作不可信数据、是否强制 strict JSON 输出、基础 prompt payload 是否移除了控制字符。
- 这是**安全契约门禁**，不是模型能力评分；目标是保证 write guard / gist / intent 反射链路的 prompt 框架本身不退化。

### Reflection Lane（反射并发通道）

**来源**：当前最新一轮 run-scoped 产物 `memory-palace-benchmark-artifacts/<run-token>/reflection_lane_metrics.json`（通常由 benchmark helpers 在维护阶段生成）

| Metric | Value | Threshold | Status |
|---|---:|---:|---|
| Timeout degrade correctness | 1 | = 1 | ✅ PASS |

- 工件契约：当前这份 JSON 现在还会显式带 `schema_version: "v1"`。
- 关注点：反射 lane 在并发受限且获取超时时，是否仍然按预期返回 `reflection_lane_timeout` 并留下运行时指标。
- 关键观测字段包括：`tasks_total`、`tasks_failed`、`wait_ms_p95`、`duration_ms_p95`。
- 这条公开门禁覆盖的是反射的 `prepare/execute` 并发边界；真正的 rollback 路径仍以当前结果里返回的 endpoint 为准：prepare 阶段通常先给 `/maintenance/import/jobs/.../rollback`，执行后如果已经拿到 review snapshot，则会升级为 `/review/...`，同时保留 `/maintenance/learn/jobs/.../rollback` alias。

### RRF / Search Quality calibration

当前仓库还带有两份小型 seeded harness：

- `backend/tests/benchmark/search_quality_baseline.py` / `search_quality_baseline.json`
- `backend/tests/benchmark/rrf_calibration.py` / `rrf_calibration_results.json`

它们的作用是给 RRF 和 entity boost 这类检索改动提供可复跑的校准基线，不是线上质量承诺。`rrf_calibration_results.json` 里当前记录的推荐默认仍是 **RRF 关闭**：`feature_flag_default=false`，生产配置需要显式设置 `RRF_ENABLED=true` 才会启用。Search Quality Dashboard 当前也没有把这些 seeded harness 结果当成线上指标持久化；面板接口会继续标出 `is_mock=true` / `status=unavailable`，直到项目真的写入带标签的质量样本。

---

## 5. 如何复核当前公开口径

当前仓库里保留了 `backend/tests/benchmark/` 相关脚本和数据，但完整 benchmark 更耗时，也更偏维护 / 复核用途。

如果你只是想确认当前安装状态，建议使用下面这组最小检查：

```bash
bash scripts/pre_publish_check.sh
curl -fsS http://127.0.0.1:8000/health
```

如果你需要更深入的复现，当前仓库已经附带 `backend/tests/benchmark/` 下的 benchmark helpers 与测试用例；只有一次性维护产物和临时门禁脚本不作为公开文档主入口。

如果你会直接读维护阶段产出的原始 JSON，当前 benchmark 产物现在还会额外带上 `schema_version: "v1"`，方便下游脚本先判断自己读的是哪一版工件契约。

### 5.1 本 session 已实际复核到哪里

- Backend 非 benchmark 全量：`1382 passed / 22 skipped`
- Frontend 全量：`203 passed`
- Frontend `typecheck` / `build`：通过
- Frontend i18n audit 与 bundle budget：通过
- repo-local live MCP e2e：`14/14 PASS`
- Docker / profile / SSE / script 重点契约测试：本轮复核通过
- 真实 A/B/C/D benchmark：本轮未重算，继续沿用第 3 节表格
- Search Quality Dashboard 面板：当前后端 endpoint 是真实鉴权接口，但因为尚未持久化带标签的质量样本，会明确返回 `is_mock=true` / `status=unavailable`；这里不能把面板里的示例 MRR/Recall 当成 benchmark 结果
- `skills+MCP` / `single-MCP`：skill smoke 的公开说明仍沿用更早那轮专门宿主验证的结果：`claude` / `codex` / `gemini` 为 `PASS`，`cursor` / `agent` / `antigravity` 为 `PARTIAL`，`gemini_live` 为 `SKIP`。`OpenCode` 在整轮脚本里出现过一次 timeout，但单独重跑通过；这里更适合按宿主波动理解，不把它写成稳定全绿。本次 2026-04-21 文档刷新没有重新跑这组 host-bound smoke。

这里故意不把这轮结果写成“全链路全绿”。尤其是 `skills-only`，现在还只能写 PARTIAL，不能往上拔。

---

## 6. 结果解读与档位选择建议

| 档位 | 适用场景 | 优势 | 注意事项 |
|---|---|---|---|
| A | 低配环境、先跑通验证 | 延迟极低（p95 < 3ms） | 仅关键词匹配，语义召回有限 |
| B | 单机开发、日常调试、默认交互档 | 延迟最低，适合高频 recall | 使用本地 hash embedding，和 C/D 跨维度切换时不能直接复用旧向量 |
| C | 本地/私有模型服务优先的深检索 | 质量明显高于 B，延迟仍可控 | 切到 C 前要确认 embedding 维度对齐；若和旧索引维度不同，需要重建索引或分库 |
| D | API-first / 远程服务优先的质量档 | 质量最高 | 延迟最高（当前 p95 已到秒级），同样要避免和不同维度旧索引混用 |

> **上线建议**：固定一套 profile + 模型配置，长期追踪同一指标口径，避免跨档位混合比较。

---

## 7. 如何读这页评测

- 比较不同结果时，先确认 `profile`、数据集范围、样本量和模型配置一致。
- 如果 `profile c/d` 缺少可用的外部模型服务，可能出现 `embedding_request_failed` / `embedding_fallback_hash`；这代表外部链路未就绪，不等于主流程不可用。
- 如果你采用的是分别直配 `RETRIEVAL_EMBEDDING_*` 与 `RETRIEVAL_RERANKER_*` 的部署方式，也应只拿同一套最终配置做横向比较。
- 对外沟通时，优先引用本页已经整理好的摘要表和图；不要把不同口径的临时重测结果混在一起讲。
