"""Search quality baseline harness.

Measures MRR@8, Recall@8, p95 latency, and average latency across the
``search_advanced`` retrieval modes (keyword / semantic / hybrid) on a tiny
seeded in-memory corpus. Results are written back into the companion
``search_quality_baseline.json`` artefact so future runs (e.g. after enabling
RRF or entity rerank) can be compared against the same data.

Run standalone:

    python -m pytest backend/tests/benchmark/search_quality_baseline.py

The pytest entry point ``test_capture_search_quality_baseline`` is a measurement
harness, not a regression gate: it only asserts the contract of the produced
metrics structure. A separate test, ``test_baseline_artifact_contract``,
guarantees the JSON skeleton stays well-formed even on hosts where the heavy
embedding/vector backends are unavailable.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple


BENCHMARK_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = BENCHMARK_DIR.parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from db.sqlite_client import SQLiteClient  # noqa: E402  (sys.path bootstrap)


BASELINE_JSON_PATH = BENCHMARK_DIR / "search_quality_baseline.json"
MAX_RESULTS_DEFAULT = 8
CANDIDATE_MULTIPLIER_DEFAULT = 4
SEARCH_MODES: Tuple[str, ...] = ("keyword", "semantic", "hybrid")


@dataclass(frozen=True)
class _GoldQuery:
    """One evaluation query with a single expected URI."""

    id: str
    query: str
    expected_uri: str


# Deterministic, hand-crafted gold set. Each query targets exactly one of the
# memories seeded by ``_seed_corpus`` below, so MRR/Recall are well-defined.
_GOLD_QUERIES: Tuple[_GoldQuery, ...] = (
    _GoldQuery(
        id="sq-001",
        query="alpha release risk summary",
        expected_uri="notes://project_alpha/risk_summary",
    ),
    _GoldQuery(
        id="sq-002",
        query="infra migration approval owner",
        expected_uri="notes://infra/migration_approvals",
    ),
    _GoldQuery(
        id="sq-003",
        query="sprint retro unresolved blockers",
        expected_uri="notes://sprint_retro/unresolved_blockers",
    ),
    _GoldQuery(
        id="sq-004",
        query="vector index rebuild procedure",
        expected_uri="notes://ops/index_rebuild",
    ),
    _GoldQuery(
        id="sq-005",
        query="cleanup review token flow",
        expected_uri="notes://maintenance/cleanup_review",
    ),
    _GoldQuery(
        id="sq-006",
        query="reranker fallback degradation reasons",
        expected_uri="notes://search/reranker_fallback",
    ),
)


_SEED_MEMORIES: Tuple[Dict[str, Any], ...] = (
    {
        "parent_path": "",
        "title": "project_alpha",
        "domain": "notes",
        "content": "Project Alpha workspace root.",
    },
    {
        "parent_path": "project_alpha",
        "title": "risk_summary",
        "domain": "notes",
        "content": (
            "Alpha release risk summary. Outstanding risks include "
            "infrastructure capacity and reviewer bandwidth. Mitigation owners "
            "tracked in the alpha rollout document."
        ),
    },
    {
        "parent_path": "",
        "title": "infra",
        "domain": "notes",
        "content": "Infrastructure notes namespace.",
    },
    {
        "parent_path": "infra",
        "title": "migration_approvals",
        "domain": "notes",
        "content": (
            "Infrastructure migration approval log. The approval owner is the "
            "platform tech lead; sign-off recorded for the storage migration "
            "plan and the network cutover plan."
        ),
    },
    {
        "parent_path": "",
        "title": "sprint_retro",
        "domain": "notes",
        "content": "Sprint retrospective notes namespace.",
    },
    {
        "parent_path": "sprint_retro",
        "title": "unresolved_blockers",
        "domain": "notes",
        "content": (
            "Sprint retrospective unresolved blockers. Two cross-team "
            "dependencies remain open; owners are listed with target dates."
        ),
    },
    {
        "parent_path": "",
        "title": "ops",
        "domain": "notes",
        "content": "Operations runbooks namespace.",
    },
    {
        "parent_path": "ops",
        "title": "index_rebuild",
        "domain": "notes",
        "content": (
            "Vector index rebuild procedure. Stop write lane, snapshot the "
            "database, rebuild the embedding index, then resume traffic."
        ),
    },
    {
        "parent_path": "",
        "title": "maintenance",
        "domain": "notes",
        "content": "Maintenance procedures namespace.",
    },
    {
        "parent_path": "maintenance",
        "title": "cleanup_review",
        "domain": "notes",
        "content": (
            "Cleanup review token flow. Prepare returns a review token with a "
            "state hash; confirm consumes the token and the write lane applies "
            "the deletion only after a hash match."
        ),
    },
    {
        "parent_path": "",
        "title": "search",
        "domain": "notes",
        "content": "Search subsystem notes namespace.",
    },
    {
        "parent_path": "search",
        "title": "reranker_fallback",
        "domain": "notes",
        "content": (
            "Reranker fallback degradation reasons. When the external reranker "
            "fails, search_advanced records reranker_request_failed in "
            "degrade_reasons and proceeds with base scores."
        ),
    },
)


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


async def _seed_corpus(client: SQLiteClient) -> None:
    """Create the deterministic memory corpus used for measurement."""

    for entry in _SEED_MEMORIES:
        await client.create_memory(
            parent_path=str(entry["parent_path"]),
            content=str(entry["content"]),
            priority=1,
            title=str(entry["title"]),
            domain=str(entry["domain"]),
        )


def _extract_uris(payload: Mapping[str, Any]) -> List[str]:
    """Return the ordered list of URIs from a ``search_advanced`` payload."""

    results = payload.get("results") if isinstance(payload, Mapping) else None
    if not isinstance(results, list):
        return []
    uris: List[str] = []
    for row in results:
        if isinstance(row, Mapping):
            uri = str(row.get("uri") or "")
            if uri:
                uris.append(uri)
    return uris


def _evaluate_mode(
    payloads: Sequence[Tuple[_GoldQuery, Mapping[str, Any], float]],
    *,
    k: int,
) -> Dict[str, Any]:
    """Aggregate per-query results into MRR@k / Recall@k / latency stats."""

    reciprocal_ranks: List[float] = []
    hits = 0
    latencies_ms: List[float] = []
    degrade_count = 0

    for gold, payload, elapsed_ms in payloads:
        latencies_ms.append(float(elapsed_ms))
        if bool(payload.get("degraded")):
            degrade_count += 1

        uris = _extract_uris(payload)
        rank_index = -1
        for idx, uri in enumerate(uris[:k]):
            if uri == gold.expected_uri:
                rank_index = idx
                break

        if rank_index >= 0:
            hits += 1
            reciprocal_ranks.append(1.0 / float(rank_index + 1))
        else:
            reciprocal_ranks.append(0.0)

    total = len(payloads)
    mrr = (sum(reciprocal_ranks) / total) if total else 0.0
    recall = (hits / total) if total else 0.0
    avg_ms = (sum(latencies_ms) / total) if total else 0.0
    p95_ms = _percentile(latencies_ms, 0.95)

    return {
        "mrr_at_8": round(mrr, 6),
        "recall_at_8": round(recall, 6),
        "p95_ms": round(p95_ms, 3),
        "avg_ms": round(avg_ms, 3),
        "queries_evaluated": total,
        "queries_with_hit": hits,
        "degraded_query_count": degrade_count,
    }


def _percentile(values: Sequence[float], pct: float) -> float:
    """Linear-interpolation percentile compatible with statistics.quantiles."""

    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(float(v) for v in values)
    # Inclusive position 0..1 mapped to ordered list.
    pos = pct * (len(ordered) - 1)
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = pos - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


async def _run_mode(
    client: SQLiteClient,
    mode: str,
) -> List[Tuple[_GoldQuery, Mapping[str, Any], float]]:
    """Execute every gold query once in the requested mode."""

    rows: List[Tuple[_GoldQuery, Mapping[str, Any], float]] = []
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
        rows.append((gold, payload, elapsed_ms))
    return rows


async def measure_search_quality(database_path: Path) -> Dict[str, Any]:
    """Seed a temporary SQLite DB and measure every mode end-to-end."""

    client = SQLiteClient(_sqlite_url(database_path))
    try:
        await client.init_db()
        await _seed_corpus(client)

        baseline_metrics: Dict[str, Any] = {}
        for mode in SEARCH_MODES:
            payloads = await _run_mode(client, mode)
            baseline_metrics[mode] = _evaluate_mode(
                payloads, k=MAX_RESULTS_DEFAULT
            )
        return baseline_metrics
    finally:
        await client.close()


def write_baseline_metrics(
    metrics: Mapping[str, Mapping[str, Any]],
    *,
    baseline_path: Path | None = None,
) -> Path:
    """Merge measured metrics into a baseline JSON file in place."""

    target = baseline_path or BASELINE_JSON_PATH
    payload = json.loads(target.read_text(encoding="utf-8"))
    baseline = payload.setdefault("baseline_metrics", {})
    for mode, mode_metrics in metrics.items():
        existing = baseline.setdefault(mode, {})
        merged = dict(existing)
        merged.update(dict(mode_metrics))
        baseline[mode] = merged
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def _run_async(coro):
    """Compatibility wrapper for pytest-asyncio not being required."""

    try:
        return asyncio.run(coro)
    except RuntimeError:
        # Running inside an existing event loop (e.g. nested pytest plugin).
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# pytest entry points
# ---------------------------------------------------------------------------


def test_baseline_artifact_contract() -> None:
    """The JSON skeleton must stay well-formed even without measurement."""

    payload = json.loads(BASELINE_JSON_PATH.read_text(encoding="utf-8"))

    assert payload.get("version")
    environment = payload.get("environment") or {}
    assert environment.get("search_modes") == list(SEARCH_MODES)
    assert int(environment.get("max_results_default")) == MAX_RESULTS_DEFAULT
    assert (
        int(environment.get("candidate_multiplier_default"))
        == CANDIDATE_MULTIPLIER_DEFAULT
    )

    baseline = payload.get("baseline_metrics") or {}
    for mode in SEARCH_MODES:
        assert mode in baseline, f"missing baseline_metrics.{mode}"
        bucket = baseline[mode]
        for key in ("mrr_at_8", "recall_at_8", "p95_ms"):
            assert key in bucket, f"missing baseline_metrics.{mode}.{key}"


def test_capture_search_quality_baseline(tmp_path: Path) -> None:
    """Measure live metrics and persist them to a temporary baseline copy."""

    db_path = tmp_path / "search_quality_baseline.db"
    baseline_path = tmp_path / BASELINE_JSON_PATH.name
    baseline_path.write_text(
        BASELINE_JSON_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    metrics = _run_async(measure_search_quality(db_path))

    assert set(metrics.keys()) == set(SEARCH_MODES)
    for mode, bucket in metrics.items():
        assert bucket["queries_evaluated"] == len(_GOLD_QUERIES)
        assert 0.0 <= float(bucket["mrr_at_8"]) <= 1.0
        assert 0.0 <= float(bucket["recall_at_8"]) <= 1.0
        assert float(bucket["p95_ms"]) >= 0.0
        assert float(bucket["avg_ms"]) >= 0.0
        # Recall@8 is an upper bound on MRR@8 for k>=1 with one relevant doc.
        assert float(bucket["mrr_at_8"]) <= float(bucket["recall_at_8"]) + 1e-9

    written_path = write_baseline_metrics(metrics, baseline_path=baseline_path)
    assert written_path == baseline_path

    # Reload the file and confirm the merge landed.
    refreshed = json.loads(baseline_path.read_text(encoding="utf-8"))
    for mode in SEARCH_MODES:
        bucket = refreshed["baseline_metrics"][mode]
        assert bucket["mrr_at_8"] is not None
        assert bucket["recall_at_8"] is not None
        assert bucket["p95_ms"] is not None


__all__ = [
    "BASELINE_JSON_PATH",
    "MAX_RESULTS_DEFAULT",
    "CANDIDATE_MULTIPLIER_DEFAULT",
    "SEARCH_MODES",
    "measure_search_quality",
    "write_baseline_metrics",
]
