"""RRF (Reciprocal Rank Fusion) offline calibration harness.

This script seeds a temporary SQLite database with a diverse 50+ memory corpus
spanning multiple domains, runs a ground-truth query set through both the
existing weighted-fusion baseline (``search_advanced`` with ``mode=hybrid``)
and an RRF-fused variant assembled from the FTS5 / vector channels, and
reports the following metrics for each candidate ``k`` value:

- MRR@8 (Mean Reciprocal Rank, top 8)
- Recall@8
- NDCG@8 (binary relevance, log-2 discount)
- p95 latency in milliseconds

Why offline? The constraint Round 1, Track B / C5 says RRF MUST be OFF by
default and a configurable ``k`` MUST be chosen *based on data*. This harness
produces the dataset that motivates the production default. It writes its
findings to ``backend/tests/benchmark/rrf_calibration_results.json`` so
reviewers can re-run with a single command and inspect the recommendation.

Run standalone::

    python backend/tests/benchmark/rrf_calibration.py
    # or under pytest:
    python -m pytest backend/tests/benchmark/rrf_calibration.py -q

The pytest entry point ``test_rrf_calibration_runs`` is a measurement
harness, not a regression gate.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import subprocess
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

BENCHMARK_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = BENCHMARK_DIR.parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_CALIBRATION_ENV_DEFAULTS = {
    "RETRIEVAL_EMBEDDING_BACKEND": "hash",
    "RETRIEVAL_EMBEDDING_DIM": "64",
}
_DB_SYMBOLS: Optional[Dict[str, Any]] = None


def _load_db_symbols() -> Dict[str, Any]:
    """Import DB/search dependencies only when the harness actually runs."""

    global _DB_SYMBOLS
    if _DB_SYMBOLS is None:
        from db.search import FTS5Channel, RRFConfig, RRFFusion, VectorChannel
        from db.search.rrf_fusion import DEFAULT_RRF_K, RRF_K_MAX, RRF_K_MIN
        from db.sqlite_client import SQLiteClient

        _DB_SYMBOLS = {
            "DEFAULT_RRF_K": DEFAULT_RRF_K,
            "FTS5Channel": FTS5Channel,
            "RRFConfig": RRFConfig,
            "RRFFusion": RRFFusion,
            "RRF_K_MAX": RRF_K_MAX,
            "RRF_K_MIN": RRF_K_MIN,
            "SQLiteClient": SQLiteClient,
            "VectorChannel": VectorChannel,
        }
    return _DB_SYMBOLS


# ---------------------------------------------------------------------------
# Test corpus
# ---------------------------------------------------------------------------

RESULTS_JSON_PATH = BENCHMARK_DIR / "rrf_calibration_results.json"
MAX_RESULTS_DEFAULT = 8
CANDIDATE_MULTIPLIER_DEFAULT = 4
K_VALUES_TO_TEST: Tuple[int, ...] = (5, 10, 20, 40, 60)


@dataclass(frozen=True)
class _GoldQuery:
    """One evaluation query with the single expected URI."""

    id: str
    query: str
    expected_uri: str


# Domain coverage: notes (project mgmt), ops (runbook), security (audit),
# search (retrieval internals), infra (platform), maintenance (cleanup),
# ml (training), frontend (UI), deploy (release), qa (testing).
_GOLD_QUERIES: Tuple[_GoldQuery, ...] = (
    _GoldQuery("rrf-001", "alpha release risk summary", "notes://project_alpha/risk_summary"),
    _GoldQuery("rrf-002", "infra migration approval owner", "notes://infra/migration_approvals"),
    _GoldQuery("rrf-003", "sprint retro unresolved blockers", "notes://sprint_retro/unresolved_blockers"),
    _GoldQuery("rrf-004", "vector index rebuild procedure", "notes://ops/index_rebuild"),
    _GoldQuery("rrf-005", "cleanup review token flow", "notes://maintenance/cleanup_review"),
    _GoldQuery("rrf-006", "reranker fallback degradation reasons", "notes://search/reranker_fallback"),
    _GoldQuery("rrf-007", "wal mode write busy timeout tuning", "notes://ops/wal_mode_tuning"),
    _GoldQuery("rrf-008", "embedding provider chain fallback config", "notes://search/embedding_provider_chain"),
    _GoldQuery("rrf-009", "snapshot recovery missing file", "notes://maintenance/snapshot_recovery"),
    _GoldQuery("rrf-010", "secret scanning baseline rule", "notes://security/secret_scan_baseline"),
    _GoldQuery("rrf-011", "csrf token rotation policy", "notes://security/csrf_rotation"),
    _GoldQuery("rrf-012", "training corpus dedupe pipeline", "notes://ml/dedupe_pipeline"),
    _GoldQuery("rrf-013", "model rollout canary stages", "notes://ml/rollout_canary"),
    _GoldQuery("rrf-014", "frontend toolbar shortcut layout", "notes://frontend/toolbar_shortcuts"),
    _GoldQuery("rrf-015", "deploy serialize docker publish", "notes://deploy/serialize_docker_publish"),
    _GoldQuery("rrf-016", "qa flaky test quarantine list", "notes://qa/flaky_quarantine"),
    _GoldQuery("rrf-017", "mcp contract golden regeneration", "notes://qa/mcp_contract_golden"),
    _GoldQuery("rrf-018", "infra storage migration cutover plan", "notes://infra/storage_cutover"),
    _GoldQuery("rrf-019", "maintenance api key rotation gate", "notes://maintenance/api_key_rotation"),
    _GoldQuery("rrf-020", "sqlite vec native top k readiness", "notes://search/sqlite_vec_readiness"),
)


_SEED_MEMORIES: Tuple[Dict[str, Any], ...] = (
    # ---- workspace roots (10) ----
    {"parent_path": "", "title": "project_alpha", "domain": "notes",
     "content": "Project Alpha workspace root."},
    {"parent_path": "", "title": "infra", "domain": "notes",
     "content": "Infrastructure notes namespace."},
    {"parent_path": "", "title": "sprint_retro", "domain": "notes",
     "content": "Sprint retrospective notes namespace."},
    {"parent_path": "", "title": "ops", "domain": "notes",
     "content": "Operations runbooks namespace."},
    {"parent_path": "", "title": "maintenance", "domain": "notes",
     "content": "Maintenance procedures namespace."},
    {"parent_path": "", "title": "search", "domain": "notes",
     "content": "Search subsystem notes namespace."},
    {"parent_path": "", "title": "security", "domain": "notes",
     "content": "Security audit and compliance notes."},
    {"parent_path": "", "title": "ml", "domain": "notes",
     "content": "Machine learning experiments and rollouts."},
    {"parent_path": "", "title": "frontend", "domain": "notes",
     "content": "Frontend UI design and component notes."},
    {"parent_path": "", "title": "deploy", "domain": "notes",
     "content": "Deployment workflows and release notes."},
    {"parent_path": "", "title": "qa", "domain": "notes",
     "content": "Quality assurance test playbooks."},

    # ---- gold-mapped pages (20) ----
    {"parent_path": "project_alpha", "title": "risk_summary", "domain": "notes",
     "content": "Alpha release risk summary. Outstanding risks include "
                "infrastructure capacity and reviewer bandwidth. Mitigation "
                "owners tracked in the alpha rollout document."},
    {"parent_path": "infra", "title": "migration_approvals", "domain": "notes",
     "content": "Infrastructure migration approval log. The approval owner is "
                "the platform tech lead; sign-off recorded for the storage "
                "migration plan and the network cutover plan."},
    {"parent_path": "sprint_retro", "title": "unresolved_blockers", "domain": "notes",
     "content": "Sprint retrospective unresolved blockers. Two cross-team "
                "dependencies remain open; owners are listed with target dates."},
    {"parent_path": "ops", "title": "index_rebuild", "domain": "notes",
     "content": "Vector index rebuild procedure. Stop write lane, snapshot the "
                "database, rebuild the embedding index, then resume traffic."},
    {"parent_path": "maintenance", "title": "cleanup_review", "domain": "notes",
     "content": "Cleanup review token flow. Prepare returns a review token "
                "with a state hash; confirm consumes the token and the write "
                "lane applies the deletion only after a hash match."},
    {"parent_path": "search", "title": "reranker_fallback", "domain": "notes",
     "content": "Reranker fallback degradation reasons. When the external "
                "reranker fails, search_advanced records reranker_request_failed "
                "in degrade_reasons and proceeds with base scores."},
    {"parent_path": "ops", "title": "wal_mode_tuning", "domain": "notes",
     "content": "WAL mode and write busy timeout tuning playbook. Raise "
                "RUNTIME_WRITE_BUSY_TIMEOUT_MS to 5000 when multiple "
                "processes share the SQLite file; pair with WAL journaling."},
    {"parent_path": "search", "title": "embedding_provider_chain", "domain": "notes",
     "content": "Embedding provider chain fallback configuration. The fail-open "
                "and fail-closed switches govern how the router degrades to the "
                "hash backend when remote embeddings are unavailable."},
    {"parent_path": "maintenance", "title": "snapshot_recovery", "domain": "notes",
     "content": "Snapshot recovery checklist when the snapshot file is missing. "
                "Re-run the manifest, verify hashes, and replay journal entries "
                "to restore consistency."},
    {"parent_path": "security", "title": "secret_scan_baseline", "domain": "notes",
     "content": "Secret scanning baseline rule set. Detect git history leaks "
                "for API keys, AWS access tokens, and database URLs; raise "
                "review on every push to protected branches."},
    {"parent_path": "security", "title": "csrf_rotation", "domain": "notes",
     "content": "CSRF token rotation policy. Tokens expire after thirty "
                "minutes of idle; refresh on every authenticated POST and "
                "invalidate on logout or password change."},
    {"parent_path": "ml", "title": "dedupe_pipeline", "domain": "notes",
     "content": "Training corpus dedupe pipeline. Hash chunked documents, "
                "MinHash near-duplicates, drop pairs above the Jaccard "
                "threshold before serialising the training corpus."},
    {"parent_path": "ml", "title": "rollout_canary", "domain": "notes",
     "content": "Model rollout canary stages. Promote shadow at 1%, A/B at "
                "10%, full rollout at 100% with rollback hooks on each stage."},
    {"parent_path": "frontend", "title": "toolbar_shortcuts", "domain": "notes",
     "content": "Frontend toolbar shortcut layout. Bind cmd-K to quick search, "
                "cmd-/ to help, cmd-, to settings; group destructive actions "
                "under a confirm modal."},
    {"parent_path": "deploy", "title": "serialize_docker_publish", "domain": "notes",
     "content": "Deploy workflow to serialize docker publish runs. Use a "
                "concurrency group keyed on registry tag to avoid racey "
                "manifest uploads that corrupt the multi-arch tag."},
    {"parent_path": "qa", "title": "flaky_quarantine", "domain": "notes",
     "content": "QA flaky test quarantine list. Tests marked here are skipped "
                "on protected branches; each entry requires an owner and a "
                "remediation target date."},
    {"parent_path": "qa", "title": "mcp_contract_golden", "domain": "notes",
     "content": "MCP contract golden regeneration steps. Run the regenerate "
                "script when a tool signature changes intentionally; commit "
                "both the code change and the refreshed golden JSON together."},
    {"parent_path": "infra", "title": "storage_cutover", "domain": "notes",
     "content": "Infrastructure storage migration cutover plan. Drain the "
                "write lane, swap connection strings, replay missed writes, "
                "and verify checksums before reopening traffic."},
    {"parent_path": "maintenance", "title": "api_key_rotation", "domain": "notes",
     "content": "Maintenance API key rotation gate. Operators must rotate "
                "MCP_API_KEY and reissue session cookies whenever a key is "
                "suspected to have leaked."},
    {"parent_path": "search", "title": "sqlite_vec_readiness", "domain": "notes",
     "content": "Sqlite vec native top k readiness checklist. Confirm the "
                "extension loads, that the vec_knn table exists, and that the "
                "dimension matches RETRIEVAL_EMBEDDING_DIM."},

    # ---- distractor pages spread across the same domains (>= 19) ----
    {"parent_path": "project_alpha", "title": "stakeholder_map", "domain": "notes",
     "content": "Project Alpha stakeholder map and escalation contacts."},
    {"parent_path": "project_alpha", "title": "kickoff_minutes", "domain": "notes",
     "content": "Alpha kickoff meeting minutes. Scope decisions and the "
                "delivery owner per workstream."},
    {"parent_path": "infra", "title": "network_topology", "domain": "notes",
     "content": "Infrastructure network topology overview, including the "
                "subnet split between API and worker fleets."},
    {"parent_path": "infra", "title": "dns_runbook", "domain": "notes",
     "content": "DNS runbook for failover and zone delegation changes."},
    {"parent_path": "ops", "title": "oncall_rotation", "domain": "notes",
     "content": "Operations on-call rotation. Primary and secondary handlers "
                "with paging escalation paths."},
    {"parent_path": "ops", "title": "log_routing", "domain": "notes",
     "content": "Operations log routing topology. Application logs flow to "
                "OpenSearch; audit logs flow to immutable object storage."},
    {"parent_path": "maintenance", "title": "vacuum_schedule", "domain": "notes",
     "content": "Maintenance vacuum and analyze schedule for the SQLite "
                "database. Weekly during low traffic; verify free pages."},
    {"parent_path": "search", "title": "mmr_diversification", "domain": "notes",
     "content": "Search MMR diversification overview. Lambda controls the "
                "balance between relevance and diversity in the rerank step."},
    {"parent_path": "search", "title": "fts_tokenizer_notes", "domain": "notes",
     "content": "FTS5 tokenizer notes. Unicode61 with prefix indexing is the "
                "default; consider trigram for code search."},
    {"parent_path": "security", "title": "threat_model", "domain": "notes",
     "content": "Security threat model snapshot. Trust boundaries between the "
                "frontend, the MCP server, and the SQLite write lane."},
    {"parent_path": "security", "title": "audit_log_format", "domain": "notes",
     "content": "Audit log format and retention. Every privileged operation "
                "produces a structured event with actor and resource."},
    {"parent_path": "ml", "title": "eval_dashboard", "domain": "notes",
     "content": "ML evaluation dashboard sketch. Track recall, precision, "
                "and latency per model version."},
    {"parent_path": "ml", "title": "data_card", "domain": "notes",
     "content": "Training data card describing sources, licences, and "
                "preprocessing steps for the production model."},
    {"parent_path": "frontend", "title": "color_tokens", "domain": "notes",
     "content": "Frontend color tokens for the redesign. OKLCH variables "
                "map to semantic surfaces."},
    {"parent_path": "frontend", "title": "responsive_breakpoints", "domain": "notes",
     "content": "Frontend responsive breakpoints for tablet and desktop."},
    {"parent_path": "deploy", "title": "release_checklist", "domain": "notes",
     "content": "Generic deploy release checklist. Smoke tests, schema "
                "migration verification, and rollback dry run."},
    {"parent_path": "deploy", "title": "feature_flag_inventory", "domain": "notes",
     "content": "Deploy feature flag inventory. Each flag has an owner, a "
                "default, and a retire-by date."},
    {"parent_path": "qa", "title": "load_test_baseline", "domain": "notes",
     "content": "QA load test baseline numbers per endpoint."},
    {"parent_path": "qa", "title": "regression_corpus", "domain": "notes",
     "content": "QA regression corpus index of frozen golden transcripts."},
)


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(float(v) for v in values)
    pos = pct * (len(ordered) - 1)
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = pos - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _ndcg_at_k(rank_index: int, k: int) -> float:
    """Binary-relevance NDCG@k for a single relevant document.

    With one relevant doc the ideal DCG is always ``1 / log2(2) == 1`` and
    the discounted gain is ``1 / log2(rank+2)`` (using 0-based rank).
    """

    if rank_index < 0 or rank_index >= k:
        return 0.0
    return 1.0 / math.log2(rank_index + 2)


@dataclass
class _PerQueryResult:
    gold: _GoldQuery
    uris: List[str]
    elapsed_ms: float
    degraded: bool = False
    fusion_metadata: Optional[Dict[str, Any]] = None


def _evaluate(
    rows: Sequence[_PerQueryResult],
    *,
    k: int,
) -> Dict[str, Any]:
    """Aggregate per-query results into MRR / Recall / NDCG / latency."""

    reciprocal_ranks: List[float] = []
    hits = 0
    ndcg_values: List[float] = []
    latencies_ms: List[float] = []
    degrade_count = 0

    for row in rows:
        latencies_ms.append(float(row.elapsed_ms))
        if row.degraded:
            degrade_count += 1

        rank_index = -1
        for idx, uri in enumerate(row.uris[:k]):
            if uri == row.gold.expected_uri:
                rank_index = idx
                break

        if rank_index >= 0:
            hits += 1
            reciprocal_ranks.append(1.0 / float(rank_index + 1))
            ndcg_values.append(_ndcg_at_k(rank_index, k))
        else:
            reciprocal_ranks.append(0.0)
            ndcg_values.append(0.0)

    total = len(rows) or 1
    return {
        "mrr_at_8": round(sum(reciprocal_ranks) / total, 6),
        "recall_at_8": round(hits / total, 6),
        "ndcg_at_8": round(sum(ndcg_values) / total, 6),
        "p95_ms": round(_percentile(latencies_ms, 0.95), 3),
        "avg_ms": round(sum(latencies_ms) / total, 3),
        "queries_evaluated": total,
        "queries_with_hit": hits,
        "degraded_query_count": degrade_count,
    }


# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _temporary_calibration_env_defaults():
    """Apply deterministic embedding defaults only while calibration runs."""

    original = {
        key: os.environ.get(key) for key in _CALIBRATION_ENV_DEFAULTS
    }
    try:
        for key, value in _CALIBRATION_ENV_DEFAULTS.items():
            os.environ.setdefault(key, value)
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


async def _seed_corpus(client: SQLiteClient) -> None:
    for entry in _SEED_MEMORIES:
        await client.create_memory(
            parent_path=str(entry["parent_path"]),
            content=str(entry["content"]),
            priority=1,
            title=str(entry["title"]),
            domain=str(entry["domain"]),
        )


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------


async def _run_weighted_baseline(
    client: SQLiteClient,
    *,
    mode: str,
) -> List[_PerQueryResult]:
    """Run the gold set through ``search_advanced`` for a given mode."""

    rows: List[_PerQueryResult] = []
    for gold in _GOLD_QUERIES:
        start = time.perf_counter()
        payload = await client.search_advanced(
            query=gold.query,
            mode=mode,
            max_results=MAX_RESULTS_DEFAULT,
            candidate_multiplier=CANDIDATE_MULTIPLIER_DEFAULT,
            filters={},
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        uris = [
            str(r.get("uri"))
            for r in (payload.get("results") or [])
            if isinstance(r, Mapping) and r.get("uri")
        ]
        rows.append(
            _PerQueryResult(
                gold=gold,
                uris=uris,
                elapsed_ms=elapsed_ms,
                degraded=bool(payload.get("degraded")),
            )
        )
    return rows


async def _run_rrf_variant(
    client: SQLiteClient,
    *,
    k: int,
    channels: Tuple[str, ...] = ("fts5", "vector"),
) -> List[_PerQueryResult]:
    """Assemble FTS5 + vector channels and apply RRF with the supplied k."""

    symbols = _load_db_symbols()
    FTS5Channel = symbols["FTS5Channel"]
    RRFConfig = symbols["RRFConfig"]
    RRFFusion = symbols["RRFFusion"]
    VectorChannel = symbols["VectorChannel"]

    fts_channel = FTS5Channel(client, candidate_multiplier=CANDIDATE_MULTIPLIER_DEFAULT)
    vec_channel = VectorChannel(client, candidate_multiplier=CANDIDATE_MULTIPLIER_DEFAULT)
    fusion = RRFFusion(RRFConfig(enabled=True, k=k, channels=channels))

    candidate_pool = MAX_RESULTS_DEFAULT * CANDIDATE_MULTIPLIER_DEFAULT

    rows: List[_PerQueryResult] = []
    for gold in _GOLD_QUERIES:
        start = time.perf_counter()
        degraded = False
        fts_results = await fts_channel.search(gold.query, candidate_pool)
        vec_results = await vec_channel.search(gold.query, candidate_pool)
        if not fts_results and not vec_results:
            degraded = True
        elif not vec_results:
            degraded = True  # vector channel could not contribute
        elif not fts_results:
            degraded = True
        per_channel = {
            "fts5": fts_results,
            "vector": vec_results,
        }
        merged = fusion.fuse(per_channel, max_results=MAX_RESULTS_DEFAULT)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        rows.append(
            _PerQueryResult(
                gold=gold,
                uris=[r.uri for r in merged],
                elapsed_ms=elapsed_ms,
                degraded=degraded,
                fusion_metadata=(
                    merged[0].metadata.get("rrf") if merged else None
                ),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------


def _choose_optimal_k(
    rrf_metrics: Mapping[int, Mapping[str, Any]],
    *,
    fallback: Optional[int] = None,
) -> Tuple[int, str]:
    """Pick the ``k`` value that maximises a quality composite.

    Composite = ``0.6 * MRR + 0.3 * Recall + 0.1 * NDCG``. Ties are broken by
    the lower-latency option.
    """

    fallback_k = int(
        fallback if fallback is not None else _load_db_symbols()["DEFAULT_RRF_K"]
    )
    best_score = -math.inf
    best_k = fallback_k
    best_reason = "fallback default"
    for k, metrics in rrf_metrics.items():
        mrr = float(metrics.get("mrr_at_8") or 0.0)
        recall = float(metrics.get("recall_at_8") or 0.0)
        ndcg = float(metrics.get("ndcg_at_8") or 0.0)
        latency = float(metrics.get("p95_ms") or 0.0)
        composite = 0.6 * mrr + 0.3 * recall + 0.1 * ndcg
        # Prefer higher composite; on ties prefer lower latency.
        candidate_tuple = (composite, -latency)
        best_tuple = (best_score, -float(rrf_metrics[best_k].get("p95_ms") or 0.0))
        if candidate_tuple > best_tuple:
            best_score = composite
            best_k = k
            best_reason = (
                f"composite=0.6*MRR+0.3*Recall+0.1*NDCG={composite:.4f}; "
                f"p95={latency:.3f}ms"
            )
    return best_k, best_reason


def _adaptive_formula(rrf_metrics: Mapping[int, Mapping[str, Any]]) -> Dict[str, Any]:
    """Surface the adaptive k formula used by the runtime config."""

    symbols = _load_db_symbols()
    rrf_k_min = int(symbols["RRF_K_MIN"])
    rrf_k_max = int(symbols["RRF_K_MAX"])
    # ``max_channel_depth`` is approximated by ``max_results * candidate_multiplier``.
    depth_hint = MAX_RESULTS_DEFAULT * CANDIDATE_MULTIPLIER_DEFAULT
    suggested = max(rrf_k_min, min(rrf_k_max, 2 * depth_hint))
    return {
        "formula": "k = clamp(2 * max_channel_depth, 10, 60)",
        "max_channel_depth_proxy": depth_hint,
        "suggested_k": suggested,
        "notes": (
            "max_channel_depth is approximated by max_results * candidate_multiplier "
            "for this calibration run. Production code can plug in the live channel "
            "depth at query time (e.g. observed candidate pool size)."
        ),
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def run_calibration(database_path: Path) -> Dict[str, Any]:
    with _temporary_calibration_env_defaults():
        SQLiteClient = _load_db_symbols()["SQLiteClient"]
        client = SQLiteClient(_sqlite_url(database_path))
        try:
            await client.init_db()
            await _seed_corpus(client)

            # Baselines first so we have a reference.
            baseline_keyword = _evaluate(
                await _run_weighted_baseline(client, mode="keyword"),
                k=MAX_RESULTS_DEFAULT,
            )
            baseline_semantic = _evaluate(
                await _run_weighted_baseline(client, mode="semantic"),
                k=MAX_RESULTS_DEFAULT,
            )
            baseline_hybrid = _evaluate(
                await _run_weighted_baseline(client, mode="hybrid"),
                k=MAX_RESULTS_DEFAULT,
            )

            rrf_results: Dict[str, Any] = {}
            per_k_metrics: Dict[int, Dict[str, Any]] = {}
            for k in K_VALUES_TO_TEST:
                metrics = _evaluate(
                    await _run_rrf_variant(client, k=k),
                    k=MAX_RESULTS_DEFAULT,
                )
                rrf_results[str(k)] = metrics
                per_k_metrics[k] = metrics

            optimal_k, reason = _choose_optimal_k(per_k_metrics)
            return {
                "calibrated_at": "2026-05-15",
                "corpus_size": len(_SEED_MEMORIES),
                "query_set_size": len(_GOLD_QUERIES),
                "k_values_tested": list(K_VALUES_TO_TEST),
                "results": rrf_results,
                "baseline_comparison": {
                    "weighted_fusion_keyword": baseline_keyword,
                    "weighted_fusion_semantic": baseline_semantic,
                    "weighted_fusion_hybrid": baseline_hybrid,
                },
                "recommendation": {
                    "optimal_k": int(optimal_k),
                    "reason": reason,
                    "feature_flag_default": False,
                    "notes": (
                        "RRF stays OFF by default (C5). Operators enable it via "
                        "RRF_ENABLED=true after replicating this calibration."
                    ),
                },
                "adaptive_formula": _adaptive_formula(per_k_metrics),
                "environment": {
                    "max_results": MAX_RESULTS_DEFAULT,
                    "candidate_multiplier": CANDIDATE_MULTIPLIER_DEFAULT,
                    "embedding_backend": os.environ.get("RETRIEVAL_EMBEDDING_BACKEND"),
                    "embedding_dim": os.environ.get("RETRIEVAL_EMBEDDING_DIM"),
                    "channels": ["fts5", "vector"],
                    "entity_channel_excluded": True,
                    "entity_channel_note": (
                        "C6: entity channel is reserved for future rerank boost "
                        "and is NOT part of the equal-weight RRF fusion."
                    ),
                },
            }
        finally:
            await client.close()


def write_results(results: Mapping[str, Any]) -> None:
    """Persist calibration results as JSON."""

    RESULTS_JSON_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# CLI + pytest entry points
# ---------------------------------------------------------------------------


def main(output_path: Optional[Path] = None) -> Dict[str, Any]:
    target = output_path or RESULTS_JSON_PATH
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "rrf_calibration.db"
        payload = _run_async(run_calibration(db_path))
    payload["results_path"] = str(target.relative_to(target.parents[2])) \
        if target.is_absolute() else str(target)
    RESULTS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload


def test_rrf_calibration_runs(tmp_path: Path) -> None:
    """Smoke-test the calibration harness end-to-end."""

    db_path = tmp_path / "rrf_calibration.db"
    original_env = {
        key: os.environ.get(key) for key in _CALIBRATION_ENV_DEFAULTS
    }
    payload = _run_async(run_calibration(db_path))

    assert set(payload["k_values_tested"]) == set(K_VALUES_TO_TEST)
    assert payload["corpus_size"] >= 50
    assert payload["query_set_size"] >= 6
    for k in K_VALUES_TO_TEST:
        bucket = payload["results"][str(k)]
        for metric in ("mrr_at_8", "recall_at_8", "ndcg_at_8", "p95_ms"):
            assert metric in bucket, f"missing {metric} for k={k}"
            assert float(bucket[metric]) >= 0.0
    assert payload["recommendation"]["feature_flag_default"] is False
    # C6: entity channel MUST stay out of fusion.
    assert payload["environment"]["entity_channel_excluded"] is True
    for key, value in original_env.items():
        assert os.environ.get(key) == value


def test_import_does_not_mutate_embedding_environment() -> None:
    """Importing the harness must not set env defaults or run calibration."""

    script = f"""
import importlib.util
import json
import os
import pathlib
import sys

for key in {list(_CALIBRATION_ENV_DEFAULTS)!r}:
    os.environ.pop(key, None)

path = pathlib.Path({str(Path(__file__).resolve())!r})
spec = importlib.util.spec_from_file_location("rrf_calibration_import_probe", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
print(json.dumps({{key: os.environ.get(key) for key in {list(_CALIBRATION_ENV_DEFAULTS)!r}}}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout.splitlines()[-1]) == {
        key: None for key in _CALIBRATION_ENV_DEFAULTS
    }


if __name__ == "__main__":  # pragma: no cover -- manual harness
    out = main()
    print(json.dumps(out["recommendation"], indent=2))


__all__ = [
    "RESULTS_JSON_PATH",
    "MAX_RESULTS_DEFAULT",
    "CANDIDATE_MULTIPLIER_DEFAULT",
    "K_VALUES_TO_TEST",
    "run_calibration",
    "write_results",
    "main",
]
