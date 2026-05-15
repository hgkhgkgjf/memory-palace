# Memory Palace Benchmark Results

This document summarizes the retrieval quality, latency, and semantic quality
gate test results for different profiles (A/B/C/D) of Memory Palace. This page
retains the **summary tables + review notes**; the public repository keeps
benchmark helpers and test entries under `backend/tests/benchmark/`, while
machine-specific raw benchmark logs, one-off gate drafts, periodic re-test
records, and some metric JSONs are typically for development or local use only.

> Status Note (2026-04 / 2026-05): This page keeps the 2026-02 public baseline tables,
> folds the 2026-04-17 real A/B/C/D verification into the current public-facing
> conclusion, records a narrower 2026-04-18 maintenance rerun, and also keeps a
> 2026-04-21 post-fix validation note for the later review-driven fixes. It also
> includes the 2026-05-15 Docker/Linux `Profile B/C/D` recheck. That
> 2026-04-21 round reran the full backend suite (`1136 passed, 22 skipped`),
> frontend tests (`198 passed`), frontend build, frontend typecheck,
> repo-local live MCP e2e (`PASS`), and a repo-local Profile B browser smoke;
> the same round also completed a smaller real A/B/C/D rerun on `BEIR NFCorpus`
> (`sample_size=5`, `Profile D` Phase 6 Gate still `PASS`). It did **not**
> recalculate the benchmark tables on this page. The 2026-05-15 pass covered
> Docker/Linux `Profile B/C/D` startup, protected proxy routes, SSE, browser
> smoke, and C/D create/search/delete only; it also did not recalculate these
> benchmark tables. For the current default
> interaction profile, the explicit deep-retrieval profiles, and the newest
> public-facing re-check notes, start with Sections 3, 4, and 5 on this page.

---

## 1. Data Sources

| Source | Description |
|---|---|
| Public Summary Tables on this page | Key metrics and gate results for A/B/C/D profiles intended for users |
| Public benchmark helpers and test cases under `backend/tests/benchmark/` | Used to understand the evaluation methodology; specific metric files are usually maintenance-phase or local review artifacts |
| Maintenance-phase benchmark artifacts | One-off re-test logs, gate drafts, and local run results; not distributed with the user repository by default |
| Current Release Notes | `docs/changelog/release_v3.7.1_2026-03-26_EN.md` |
| Release Comparison Summary | `docs/changelog/release_summary_vs_old_project_2026-03-06_EN.md` |

> Data Generation Time: `2026-02-19T06:55:30+00:00` (early gate baseline) /
> `2026-04-17T10:35:51+00:00` (current public verification) /
> `2026-04-18T06:31:05+00:00` (current-session maintenance rerun) /
> `2026-04-21` (post-fix validation refresh; benchmark tables unchanged) /
> `2026-05-15` (Docker/Linux Profile B/C/D recheck; benchmark tables unchanged)

> Artifact path note: the public benchmark helpers now default to writing run
> artifacts under the system temp directory at
> `memory-palace-benchmark-artifacts/<run-token>/...`; if you need a fixed
> location, pass `artifact_dir` explicitly or set `BENCHMARK_ARTIFACT_DIR`.
> This keeps parallel benchmark runs from dirtying the worktree.

---

## 1.5 What exactly do these metrics look at?

In plain English:

- **HR@10**: Whether the correct answer was found within the top 10 results.
  The higher, the better.
- **MRR**: How **high up** the correct answer is ranked. The higher the rank,
  the higher the score.
- **NDCG@10**: Not just whether it was found, but how good the **overall
  ranking** is. The higher, the better.
- **Recall@10**: If a query has multiple relevant results, this measures how
  many were **covered** in the top 10. The higher, the better.
- **p50 / p95**: Response time. `p50` can be thought of as "how fast most
  requests are," while `p95` is "how slow it gets when things are sluggish."
- **Degradation Rate**: The percentage of requests where the system fell back
  to a lower-tier mode because the external embedding/reranker was unavailable.
  The lower, the better.

If you just want a quick look, prioritize these three:

1. **HR@10**: Can it find it?
2. **MRR**: Once found, is it ranked near the top?
3. **p95**: Is the slowest batch of requests too slow?

---

## 2. Retrieval Benchmark (A/B/CD Small Sample Gate)

**Source**: the latest run-scoped benchmark artifact under
`memory-palace-benchmark-artifacts/<run-token>/profile_ab_metrics.json`
(`sample_size=100`, 3 datasets per profile x 100 queries; typically generated
by benchmark helpers in `backend/tests/benchmark/` during the maintenance
phase)

| Profile | Mode | Dataset | HR@10 | MRR | NDCG@10 | Recall@10 | p50(ms) | p95(ms) | Degradation Rate |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| A | keyword | MS MARCO | 0.333 | 0.333 | 0.333 | 0.333 | 1.2 | 2.1 | 0.0% |
| A | keyword | BEIR NFCorpus | 0.300 | 0.300 | 0.300 | 0.300 | 1.6 | 2.6 | 0.0% |
| A | keyword | SQuAD v2 Dev | 0.150 | 0.150 | 0.150 | 0.150 | 1.2 | 3.0 | 0.0% |
| B | hybrid | MS MARCO | 0.867 | 0.658 | 0.696 | 0.850 | 3.4 | 3.7 | 0.0% |
| B | hybrid | BEIR NFCorpus | 1.000 | 0.828 | 0.850 | 0.975 | 4.1 | 4.7 | 0.0% |
| B | hybrid | SQuAD v2 Dev | 1.000 | 0.765 | 0.822 | 1.000 | 3.2 | 3.9 | 0.0% |
| CD | hybrid | (Same baseline as B) | Same as B | Same as B | Same as B | Same as B | Same as B | Same as B | 0.0% |

> **Note**: The CD gate uses the same hash embedding baseline as B to verify
> the correctness of the hybrid retrieval path.

---

## 3. Retrieval Benchmark (Real A/B/C/D Run)

**Source**: the latest run-scoped real-run artifact under
`memory-palace-benchmark-artifacts/<run-token>/profile_abcd_real_metrics.json`
(`sample_size_requested=8`, 2 datasets x 8 queries; typically generated by
benchmark helpers in `backend/tests/benchmark/` during the maintenance phase)

Strategy: Each query uses `first_relevant_only=true` to keep only the first
relevant document, with `200` extra distractor documents,
`candidate_multiplier=8`, and random seed `20260219`.

| Profile | Dataset | HR@10 | MRR | NDCG@10 | p50(ms) | p95(ms) | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| A | SQuAD v2 Dev | 0.000 | 0.000 | 0.000 | 5.179 | 7.920 | ✅ PASS |
| A | BEIR NFCorpus | 0.250 | 0.250 | 0.250 | 8.218 | 13.576 | ✅ PASS |
| B | SQuAD v2 Dev | 0.125 | 0.062 | 0.079 | 33.801 | 52.227 | ✅ PASS |
| B | BEIR NFCorpus | 0.250 | 0.250 | 0.250 | 40.857 | 44.675 | ✅ PASS |
| C | SQuAD v2 Dev | 1.000 | 0.896 | 0.920 | 219.999 | 298.780 | ✅ PASS |
| C | BEIR NFCorpus | 0.625 | 0.531 | 0.554 | 212.338 | 259.681 | ✅ PASS |
| D | SQuAD v2 Dev | 1.000 | 0.896 | 0.920 | 2452.644 | 2764.629 | ✅ PASS |
| D | BEIR NFCorpus | 0.750 | 0.656 | 0.679 | 3155.158 | 3409.331 | ✅ PASS |

> **Note**:
>
> - `Profile B` remains the **default interaction profile**: lowest latency,
>   suitable for day-to-day CLI / IDE recall.
> - `Profile C` is the **explicit deep-retrieval profile**: under this real
>   benchmark helper contract it uses `hybrid + API embedding` **without
>   reranker**, and still lands clearly above B while staying in the
>   hundreds-of-milliseconds range.
> - `Profile D` remains the **highest-quality profile**: under the same helper
>   contract it adds the reranker on top of `Profile C`, so quality is highest
>   but p95 is already in the seconds range.
> - This real benchmark helper's `Profile C/D` split is a maintenance-time
>   benchmark contract, not the same thing as the shipped deployment templates.
> - The current real runner also folds both **query-time** and **index-time**
>   degradation into the public gate. Embedding-side degradation affects C/D;
>   reranker-missing or invalid-response cases are mainly D-side gate semantics
>   and no longer get written up as a clean PASS.
> - These results assume the **active profile's embedding dimension is already
>   aligned**. They do not mean you can hot-switch between B's old vectors and
>   C/D's old vectors in the same store. When dimensions differ, the current
>   runtime returns `embedding_dim_mismatch_requires_reindex` /
>   `vector_dim_mismatch_requires_reindex`, which means reindex or a separate
>   database is required.
> - All Phase 6 gates are PASS, indicating that the public profiles did not
>   hit failures or invalid requests in this run.

### 3.1 How to read the 2026-04-17 verification

- If you only want the **default recommendation**, choose `Profile B`.
- If you explicitly want **deeper retrieval / quality-first recall**, switch
  to `Profile C` or `Profile D`.
- `Profile C` and `Profile D` are not default recall tiers. They are deeper
  retrieval tiers that you opt into on purpose.
- The narrower 2026-04-18 rerun below is useful as a fresh maintenance
  snapshot, but it does **not** replace the wider 2026-04-17 public baseline
  above.

After averaging the two datasets, the public summary for this run is:

| Profile | Avg HR@10 | Avg MRR | Avg NDCG@10 | Avg Recall@10 | Avg p95(ms) |
|---|---:|---:|---:|---:|---:|
| A | 0.125 | 0.125 | 0.125 | 0.125 | 10.7 |
| B | 0.188 | 0.156 | 0.164 | 0.188 | 48.5 |
| C | 0.812 | 0.714 | 0.737 | 0.812 | 279.2 |
| D | 0.875 | 0.776 | 0.799 | 0.875 | 3087.0 |

### 3.2 Current 2026-04-18 rerun (public-facing summary)

This session also reran a narrower current check with:

- `dataset_scope=squad_v2_dev`
- `sample_size=2`
- `extra_distractors=20`
- `candidate_multiplier=8`
- `max_results=10`

| Profile | Dataset | HR@10 | MRR | NDCG@10 | p95(ms) |
|---|---|---:|---:|---:|---:|
| A | SQuAD v2 Dev | 0.000 | 0.000 | 0.000 | 2.264 |
| B | SQuAD v2 Dev | 1.000 | 0.571 | 0.667 | 6.687 |
| C | SQuAD v2 Dev | 1.000 | 1.000 | 1.000 | 666.607 |
| D | SQuAD v2 Dev | 1.000 | 1.000 | 1.000 | 1261.532 |

In plain English:

- `Profile B` still fits the default recommendation when you want the lowest
  friction day-to-day setup.
- `Profile C/D` again show the quality-first tier, but they still cost much
  more latency than `Profile B`.
- The later 2026-04-21 post-fix pass reran the full backend/frontend suites,
  frontend build, frontend typecheck, repo-local live MCP e2e, and a
  repo-local `Profile B` browser smoke; the same round also completed a
  smaller real A/B/C/D rerun on `BEIR NFCorpus` with `Profile D` Phase 6 Gate
  still `PASS`. The 2026-05-15 follow-up reran Docker/Linux `Profile B/C/D`
  startup, SSE, browser smoke, and C/D create/search/delete. Neither pass
  recalculated this benchmark table.
- Native Windows and native Linux host runtime paths were **not** rerun in
  this round, so this page does not claim a fresh host-runtime pass there.

### 3.3 2026-04-20 Same-config follow-up (default reranker weight)

This follow-up is not a new public baseline. It was only used to re-check a
same-config `Profile D` rerank-fusion regression seen during maintenance reruns.

- It uses the same small-sample real-run contract: `sample_size=8`,
  `extra_distractors=200`, `candidate_multiplier=8`.
- When the generic runtime default `RETRIEVAL_RERANKER_WEIGHT` was still
  `0.25`, `Profile D` on `BEIR NFCorpus` dipped to `MRR=0.59375` and
  `NDCG@10=0.632701`.
- After restoring the generic runtime default to `0.40`, the same-config
  follow-up returned `Profile D` on `BEIR NFCorpus` to
  `HR@10=0.750`, `MRR=0.65625`, `NDCG@10=0.678835`, with `p95≈3158ms`.
- This follow-up only says the D-side rerank-fusion default has been brought
  back in line with the current repository truth. It does **not** mean the
  shipped `Profile C/D` templates now use `0.40` as their explicit values.

## 3.5 Old vs Current Version (Same-Metric Summary)

The following figures come from a round of **same-metric old/new comparison
reviews**. Summary data is kept here; raw comparison records with local machine
paths are not retained.

![Old vs Current Version Retrieval Quality and Latency Comparison](images/benchmark_comparison.png)

> 📈 This chart corresponds to the comparison results between the **old version
> and the current version** under the same metrics.
>
> When reading the chart, you can look at:
>
> - Top-left `HR@10`: Whether it was found in the top 10
> - Bottom-right `p95 latency`: How slow it gets at the extreme
> - The footer line `cm=8 avg`: Represents the upper-bound performance of the
>   new version after further increasing the candidate pool

---

### Core Conclusions for High-Distractor Scenarios

| Scenario | Metric | Old C | New C | Old D | New D |
|---|---|---:|---:|---:|---:|
| `s8,d10` | `HR@10` | 0.875 | 0.875 | 0.875 | 0.875 |
| `s8,d200` | `HR@10` | 0.313 | 0.563 | 0.375 | 0.625 |
| `s100,d200` | `HR@10` | 0.280 | 0.580 | 0.295 | 0.615 |

### A Closer Look: MRR / NDCG@10

| Scenario | Metric | Old C | New C | Old D | New D |
|---|---|---:|---:|---:|---:|
| `s8,d10` | `MRR / NDCG@10` | 0.783 / 0.805 | 0.783 / 0.805 | 0.825 / 0.837 | 0.825 / 0.837 |
| `s8,d200` | `MRR / NDCG@10` | 0.313 / 0.313 | 0.563 / 0.563 | 0.375 / 0.375 | 0.625 / 0.625 |
| `s100,d200` | `MRR / NDCG@10` | 0.247 / 0.255 | 0.512 / 0.529 | 0.268 / 0.275 | 0.560 / 0.573 |

### How to read these numbers

- `s8,d10`: Low-difficulty scenario, **no change**
- `s8,d200`: Once distractors increase, the current version improves clearly
- `s100,d200`: With larger samples and more distractors, the current version
  is still noticeably more stable

One-line summary:

> If you care about real complex retrieval rather than the simplest demo
> scenarios, the current version is materially stronger than the old one.

### Quick parameter explanation

- `s8,d10`: `s=sample_size`, `d=extra_distractors`. You can read this as
  "8 samples + 10 distractor documents."
- `s8,d200`: Still 8 samples, but distractors increase to 200, making it much
  easier for the true result to be buried.
- `s100,d200`: 100 samples + 200 distractor documents, closer to real complex
  retrieval.
- `candidate_multiplier=4 / 8`: The first retrieval round expands the
  candidate pool before later re-ranking. A larger value usually gives
  **quality more room to improve**, but also makes **latency more likely to
  rise**.

### Latency Notes

| Scenario | Repository | C p95(ms) | D p95(ms) |
|---|---|---:|---:|
| `s8,d10` | Old | 474.5 | 2103.2 |
| `s8,d10` | Current | 639.5 | 2088.2 |
| `s8,d200` | Old | 945.8 | 2507.1 |
| `s8,d200` | Current | 1150.9 | 2428.8 |
| `s100,d200` | Old | 1027.8 | 2796.5 |
| `s100,d200` | Current | 937.6 | 2772.0 |

Plain English:

- The main gain in the current version is **better retrieval quality**
- It is not faster in every scenario
- But in `s100,d200`, which is closer to real complex retrieval, latency does
  not get obviously worse

### Current-Version Tuning Headroom (Supplement)

In the `s100,d200` scenario, if the current version's `candidate_multiplier`
is increased from `4` to `8`, the 3-run average becomes:

- C: `HR@10=0.700`, `MRR=0.607`, `NDCG@10=0.630`
- D: `HR@10=0.720`, `MRR=0.651`, `NDCG@10=0.668`

This indicates that the current version still has further tuning headroom, at
the cost of a larger candidate pool and higher latency.

---

## 4. Quality Gates (Semantic-Related)

### Write Guard

**Source**: the latest run-scoped artifact under
`memory-palace-benchmark-artifacts/<run-token>/write_guard_quality_metrics.json`
(typically generated by benchmark helpers during the maintenance phase)

| Metric | Value | Threshold | Status |
|---|---:|---:|---|
| Precision | 1.000 | >= 0.90 | ✅ PASS |
| Recall | 1.000 | >= 0.85 | ✅ PASS |

- Total test cases: **6** (`TP=4`, `FP=0`, `FN=0`)
- Decision distribution: `NOOP`x2, `UPDATE`x2, `ADD`x2
- Overall result: **overall_pass = true**

How to read it:

- **Precision**: When the system says "this should be blocked / updated," how
  often is that judgment correct? Higher is better.
- **Recall**: Among the cases that really should be blocked / updated, how many
  did the system miss? Higher is better.
- The goal here is not writing quality. It checks whether **Write Guard causes
  false positives or misses**.

### Intent Classification

**Source**: the latest run-scoped artifact under
`memory-palace-benchmark-artifacts/<run-token>/intent_accuracy_metrics.json`
(typically generated by benchmark helpers during the maintenance phase)

| Metric | Value | Threshold | Status |
|---|---:|---:|---|
| Accuracy | 1.000 | >= 0.80 | ✅ PASS |

- Total test cases: **6**
- Classification method: `keyword_scoring_v2` (pure rules, no external model
  dependency)
- Covered intents: `temporal`x2, `causal`x2, `exploratory`x1, `factual`x1
- Strategy template mapping:
  - `temporal` -> `temporal_time_filtered`
  - `causal` -> `causal_wide_pool`
  - `exploratory` -> `exploratory_high_recall`
  - `factual` -> `factual_high_precision`

How to read it:

- This does not measure whether the final answer is good. It checks whether the
  system can first decide whether a query is better treated as a **factual,
  exploratory, temporal, or causal** query.
- If the intent is right, the later retrieval strategy is much more likely to
  be right as well.

### Gist Quality (Context Compression Summary)

**Source**: the latest run-scoped artifact under
`memory-palace-benchmark-artifacts/<run-token>/compact_context_gist_quality_metrics.json`
(typically generated by benchmark helpers during the maintenance phase)

| Metric | Value | Threshold | Status |
|---|---:|---:|---|
| ROUGE-L (mean) | 0.759 | >= 0.40 | ✅ PASS |

- Total test cases: **5**
- ROUGE-L distribution by case:

| Case | ROUGE-L |
|---|---:|
| gist-001 | 0.824 |
| gist-002 | 0.923 |
| gist-003 | 0.667 |
| gist-004 | 0.667 |
| gist-005 | 0.714 |

How to read it:

- **ROUGE-L** can be read simply as how close the generated gist is to the
  reference summary in terms of key-content overlap.
- It is not a final writing-quality score. It checks whether compression
  **keeps the important meaning**.

### Prompt Safety (Reflection Prompt Contract)

**Source**: the latest run-scoped artifact under
`memory-palace-benchmark-artifacts/<run-token>/prompt_safety_contract_metrics.json`
(typically generated by benchmark helpers during the maintenance phase)

| Metric | Value | Threshold | Status |
|---|---:|---:|---|
| Contract pass rate | 1.000 | >= 1.000 | ✅ PASS |

- Artifact contract: the current JSON payload also carries
  `schema_version: "v1"`.
- Focus: whether the system prompt explicitly treats input as untrusted,
  enforces strict JSON output, and strips control characters from the base
  prompt payload.
- This is a **safety-contract gate**, not a model-capability score. The point
  is to keep the write guard / gist / intent reflection prompt frame from
  regressing.

### Reflection Lane (Concurrent Reflection Path)

**Source**: the latest run-scoped artifact under
`memory-palace-benchmark-artifacts/<run-token>/reflection_lane_metrics.json`
(typically generated by benchmark helpers during the maintenance phase)

| Metric | Value | Threshold | Status |
|---|---:|---:|---|
| Timeout degrade correctness | 1 | = 1 | ✅ PASS |

- Artifact contract: the current JSON payload also carries
  `schema_version: "v1"`.
- Focus: when the reflection lane is saturated or times out, does it still
  return `reflection_lane_timeout` as expected and leave runtime metrics
  behind.
- The key observable fields include `tasks_total`, `tasks_failed`,
  `wait_ms_p95`, and `duration_ms_p95`.

### RRF / Search Quality Calibration

The repository also includes two small seeded harnesses:

- `backend/tests/benchmark/search_quality_baseline.py` / `search_quality_baseline.json`
- `backend/tests/benchmark/rrf_calibration.py` / `rrf_calibration_results.json`

Their role is to provide a reproducible calibration baseline for retrieval changes such as RRF and entity boost. They are not production-quality promises. The current `rrf_calibration_results.json` recommendation still keeps **RRF disabled by default**: `feature_flag_default=false`; production config must explicitly set `RRF_ENABLED=true` to enable it. The Search Quality Dashboard does not yet persist these seeded harness results as live metrics either; its API keeps returning `is_mock=true` / `status=unavailable` until labelled quality samples are actually stored.

---

## 5. How to Re-check the Current Public Baseline

The current repository keeps benchmark-related scripts and data under
`backend/tests/benchmark/`, but the full benchmark is more time-consuming and
mainly useful for maintenance / review.

If you only want to confirm the current installation status, this minimal check
set is recommended:

```bash
bash scripts/pre_publish_check.sh
curl -fsS http://127.0.0.1:8000/health
```

If you need deeper reproduction, the current repository already includes the
benchmark helpers and test cases under `backend/tests/benchmark/`; only
one-off maintenance artifacts and temporary gate scripts are not part of the
main public docs entry.

If you inspect the raw maintenance JSONs directly, the current benchmark
artifacts also carry `schema_version: "v1"` so downstream checks can tell which
artifact contract they are reading.

If you want to reproduce the narrower 2026-04-18 maintenance rerun used in this
session, this is the command shape:

```bash
cd backend
.venv/bin/python tests/benchmark/run_profile_abcd_real.py \
  --sample-size 2 \
  --datasets squad_v2_dev \
  --extra-distractors 20 \
  --max-results 10 \
  --candidate-multiplier 8
```

---

### 5.1 What Was Actually Rechecked In This Session

- Full non-benchmark backend suite: `1136 passed / 22 skipped`
- Full frontend suite: `198 passed`
- Frontend `typecheck` / `build`: passed
- Repo-local `Profile B` real-browser smoke: passed
- Repo-local live MCP e2e: passed
- `BEIR NFCorpus` small real A/B/C/D rerun: passed (`sample_size=5`, `extra_distractors=20`, `candidate_multiplier=8`, `Profile D` gate = `PASS`)
- Docker/Linux `Profile B`: rerun with the project's existing settings; backend/frontend were healthy, `/sse` returned an endpoint event, and browser smoke on Memory / Observability / Maintenance had no console errors; the new protected proxy routes `/api/layering/*`, `/api/forgetting/*`, and `/api/search/quality-metrics` returned normally
- Docker/Linux `Profile C/D`: rerun with explicit runtime injection and a 1024-dimension external embedding / reranker setup; create/search/delete smoke passed for both profiles, search returned `degrade_reasons=None`, and SSE plus browser smoke passed
- Docker / profile / SSE contract tests: `backend/tests/test_profile_script_regressions.py`, `backend/tests/test_docker_one_click_contracts.py`, and `backend/tests/test_sse_deploy_contracts.py` passed together with `67 passed, 10 skipped`
- Real A/B/C/D benchmark: rerun earlier in this session; not recalculated in the final closeout pass
- Search Quality Dashboard panel: the backend endpoint is a real authenticated API, but because labelled quality samples are not persisted yet, it explicitly returns `is_mock=true` / `status=unavailable`; do not treat the panel's example MRR/Recall values as benchmark results
- `skills+MCP` / `single-MCP`: the public skill-smoke note still follows the earlier dedicated host-validation round: `claude` / `codex` / `gemini` passed, `cursor` / `agent` / `antigravity` remain `PARTIAL`, and `gemini_live` stays `SKIP`. `OpenCode` hit one timeout in the full multi-CLI sweep but passed on the immediate standalone rerun, so this is better understood as host-side fluctuation rather than a stable all-host `PASS` claim. This 2026-04-21 doc refresh did not rerun that host-bound skill-smoke set.

This is intentionally still not described as “everything is green everywhere.”

---

## 6. How to Interpret the Results and Choose a Profile

| Profile | Best For | Strength | Notes |
|---|---|---|---|
| A | Low-resource environments, first-pass validation | Extremely low latency (`p95 < 3ms`) | Keyword-only matching; semantic recall is limited |
| B | Single-machine development, daily debugging, default interaction profile | Lowest latency, best fit for frequent recall | Uses local hash embedding; do not expect old B vectors to be transparently reusable after a cross-dimension switch to C/D |
| C | Deep retrieval with local or private model services | Clearly better quality than B while latency is still manageable | Before switching to C, confirm the embedding dimension is aligned; if the old index was written with a different dimension, reindex or use a separate database |
| D | API-first / remote-service-first quality profile | Highest retrieval quality | Highest latency (current p95 is already in the seconds range), and it should not share old vectors from a different embedding dimension without reindexing |

> **Production recommendation**: Fix one profile + model configuration and
> track the same metric baseline over time. Avoid mixing numbers across
> different profiles.

---

## 7. How to Read This Benchmark Page

- When comparing different results, first confirm that `profile`, dataset
  scope, sample size, and model configuration are consistent.
- If `profile c/d` lacks usable external model services, you may see
  `embedding_request_failed` / `embedding_fallback_hash`; this means the
  external chain is not ready, not that the main workflow is unusable.
- If your deployment directly configures `RETRIEVAL_EMBEDDING_*` and
  `RETRIEVAL_RERANKER_*` separately, you should still compare only within the
  same final configuration.
- For external communication, prefer the summary tables and chart already
  organized on this page; do not mix temporary re-test results from different
  baselines.
