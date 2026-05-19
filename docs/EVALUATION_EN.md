# Memory Palace Benchmark Results

This document summarizes retrieval quality, latency, and semantic quality gate results for the A/B/C/D profiles, plus profile selection guidance.

---

## 1. What Exactly Do These Metrics Look At?

In plain English:

- **HR@10**: Whether the correct answer was found within the top 10 results. Higher is better.
- **MRR**: How high up the correct answer is ranked. Higher rank, higher score.
- **NDCG@10**: Not just whether it was found, but how good the overall ranking is. Higher is better.
- **Recall@10**: If a query has multiple relevant results, this measures how many were covered in the top 10. Higher is better.
- **p50 / p95**: Response time. `p50` is "how fast most requests are." `p95` is "how slow it gets when things are sluggish."
- **Degradation Rate**: Percentage of requests where the system fell back to a lower-tier mode because the external embedding/reranker was unavailable. Lower is better.

If you just want a quick look, prioritize these three:

1. **HR@10**: Can it find it?
2. **MRR**: Once found, is it ranked near the top?
3. **p95**: Is the slowest batch of requests too slow?

---

## 2. Public A/B/C/D Summary

These numbers come from 2 datasets (`SQuAD v2 Dev`, `BEIR NFCorpus`) × 8 queries each, keeping only the first relevant document per query, plus `200` distractor documents, with `candidate_multiplier=8`.

| Profile | Avg HR@10 | Avg MRR | Avg NDCG@10 | Avg Recall@10 | Avg p95(ms) |
|---|---:|---:|---:|---:|---:|
| A | 0.125 | 0.125 | 0.125 | 0.125 | 2.7 |
| B | 0.188 | 0.156 | 0.164 | 0.188 | 14.7 |
| C | 0.812 | 0.714 | 0.737 | 0.812 | 208.8 |
| D | 0.875 | 0.776 | 0.799 | 0.875 | 3004.9 |

Key points:

- `Profile B` is the **default interaction tier**: lowest latency, suitable for day-to-day CLI / IDE recall.
- `Profile C` is the **explicit deep-retrieval tier**: clearly above B in quality, still in the hundreds-of-milliseconds p95 range.
- `Profile D` is the **highest-quality tier**: adds the reranker on top of C, so quality is highest but p95 is already in the seconds range.
- These results assume the active profile's embedding dimension is already aligned. When dimensions differ, the runtime returns `embedding_dim_mismatch_requires_reindex` / `vector_dim_mismatch_requires_reindex` and requires reindex or a separate database.

---

## 3. Old vs Current Version Comparison

In control scenarios prone to interference, the current version's C / D tiers show significant improvements.

![Old vs Current Retrieval Quality and Latency Comparison](images/benchmark_comparison.png)

### Core Conclusions for High-Distractor Scenarios

| Scenario | Metric | Old C | New C | Old D | New D |
|---|---|---:|---:|---:|---:|
| `s8,d10` | `HR@10` | 0.875 | 0.875 | 0.875 | 0.875 |
| `s8,d200` | `HR@10` | 0.313 | 0.563 | 0.375 | 0.625 |
| `s100,d200` | `HR@10` | 0.280 | 0.580 | 0.295 | 0.615 |

### MRR / NDCG@10

| Scenario | Metric | Old C | New C | Old D | New D |
|---|---|---:|---:|---:|---:|
| `s8,d10` | `MRR / NDCG@10` | 0.783 / 0.805 | 0.783 / 0.805 | 0.825 / 0.837 | 0.825 / 0.837 |
| `s8,d200` | `MRR / NDCG@10` | 0.313 / 0.313 | 0.563 / 0.563 | 0.375 / 0.375 | 0.625 / 0.625 |
| `s100,d200` | `MRR / NDCG@10` | 0.247 / 0.255 | 0.512 / 0.529 | 0.268 / 0.275 | 0.560 / 0.573 |

### Latency Notes

| Scenario | Repo | C p95(ms) | D p95(ms) |
|---|---|---:|---:|
| `s8,d10` | Old | 474.5 | 2103.2 |
| `s8,d10` | New | 639.5 | 2088.2 |
| `s8,d200` | Old | 945.8 | 2507.1 |
| `s8,d200` | New | 1150.9 | 2428.8 |
| `s100,d200` | Old | 1027.8 | 2796.5 |
| `s100,d200` | New | 937.6 | 2772.0 |

### How to Read These Numbers

- `s` is sample size, `d` is the number of distractor documents; a larger `d` indicates a harder scenario.
- Low-difficulty scenario `s8,d10`: **equivalent**.
- High-interference scenarios (`s8,d200` / `s100,d200`): clear improvement in the current version.
- The main gain is **better retrieval quality**, not faster in every scenario; in `s100,d200`, which is closer to real complex retrieval, latency does not get obviously worse.

One-line summary:

> If you care about real complex retrieval rather than the simplest demo scenarios, the current version is materially stronger than the old one.

---

## 4. Quality Gates (Semantic-Related)

These gates check that core paths have not regressed; they are not "writing quality" scores.

### Write Guard

| Metric | Value | Threshold | Status |
|---|---:|---:|---|
| Precision | 1.000 | >= 0.90 | ✅ PASS |
| Recall | 1.000 | >= 0.85 | ✅ PASS |

- **Precision**: When the system says "this should be blocked / updated," how often is that judgment correct?
- **Recall**: Among the cases that really should be blocked / updated, how many did the system miss?

### Intent Classification

| Metric | Value | Threshold | Status |
|---|---:|---:|---|
| Accuracy | 1.000 | >= 0.80 | ✅ PASS |

- Classification method: `keyword_scoring_v2` (pure rules, no external model dependency)
- Covered intents: `temporal`, `causal`, `exploratory`, `factual`
- This does not measure final answer quality. It checks whether the system can first decide what kind of query it is, so the later retrieval strategy is more likely to be right.

### Gist Quality (Context Compression Summary)

| Metric | Value | Threshold | Status |
|---|---:|---:|---|
| ROUGE-L (mean) | 0.759 | >= 0.40 | ✅ PASS |

- **ROUGE-L** roughly measures how close the generated gist is to the reference summary in key-content overlap.
- It is not a final writing-quality score. It checks whether compression keeps the important meaning.

### Prompt Safety (Reflection Prompt Contract)

| Metric | Value | Threshold | Status |
|---|---:|---:|---|
| Contract pass rate | 1.000 | >= 1.000 | ✅ PASS |

- Focus: whether the system prompt explicitly treats input as untrusted, enforces strict JSON output, and strips control characters.
- This is a **safety-contract gate**, not a model-capability score.

### Reflection Lane (Concurrent Reflection Path)

| Metric | Value | Threshold | Status |
|---|---:|---:|---|
| Timeout degrade correctness | 1 | = 1 | ✅ PASS |

- Focus: when the reflection lane is saturated or times out, does it still return `reflection_lane_timeout` as expected.

### RRF / Search Quality Calibration

The repository includes two small seeded harnesses:

- `backend/tests/benchmark/search_quality_baseline.py` / `search_quality_baseline.json`
- `backend/tests/benchmark/rrf_calibration.py` / `rrf_calibration_results.json`

They provide a reproducible calibration baseline for retrieval changes such as RRF and entity boost. They are not production-quality promises. The raw code default remains `RRF_ENABLED=false`; the shipped Profile B/C/D templates explicitly set `RRF_ENABLED=true` (`RRF_K=10`). Profile A is pure keyword mode and does not use RRF.

---

## 5. How to Re-check

The full benchmark is more time-consuming and mainly useful for maintenance. If you only want to confirm the current installation status, this minimal set is recommended:

```bash
bash scripts/pre_publish_check.sh
curl -fsS http://127.0.0.1:8000/health
```

If you need deeper reproduction, the repository ships benchmark helpers and test cases under `backend/tests/benchmark/`.

---

## 6. How to Choose a Profile

| Profile | Best For | Strength | Notes |
|---|---|---|---|
| A | Low-resource environments, first-pass validation | Extremely low latency (`p95 < 3ms`) | Keyword-only matching; semantic recall is limited |
| B | Single-machine development, daily debugging, default interaction profile | Lowest latency, best fit for frequent recall | Uses local hash embedding; old B vectors are not reusable after a cross-dimension switch to C/D |
| C | Deep retrieval with local or private model services | Clearly better quality than B while latency is still manageable | Confirm embedding-dimension alignment before switching; if the old index used a different dimension, reindex or use a separate database |
| D | API-first / remote-service-first quality profile | Highest retrieval quality | Highest latency (p95 already in the seconds range); same dimension caveat as C |

> **Production recommendation**: Fix one profile + model configuration and track the same metric baseline over time. Avoid mixing numbers across different profiles.

---

## 7. How to Read This Benchmark Page

- When comparing different results, first confirm that `profile`, dataset scope, sample size, and model configuration are consistent.
- If `profile c/d` lacks usable external model services, you may see `embedding_request_failed` / `embedding_fallback_hash`; this means the external chain is not ready, not that the main workflow is unusable.
- For external communication, prefer the summary tables and chart already organized on this page; do not mix temporary re-test results from different baselines.
