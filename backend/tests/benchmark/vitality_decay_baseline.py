"""Vitality decay baseline harness.

Seeds an isolated SQLite database with memories of known vitality scores and
known ages, applies one forced decay pass, and verifies the resulting scores
match the decay formula documented in ``vitality_baseline.md``:

    resistance         = 1 + min(2.0, log1p(access_count) * 0.35)
    effective_age_days = age_days / resistance
    decay_ratio        = exp(-effective_age_days / half_life_days)
    next_score         = max(min_score, current_score * decay_ratio)

The harness is intentionally read-only with respect to production code: it
only exercises ``SQLiteClient`` through its public methods and writes a
companion snapshot (``vitality_decay_baseline.json``) capturing the observed
decay curve. The snapshot serves as the regression target before downstream
changes (e.g. dynamic half-life, per-domain decay).

Run standalone:

    python -m pytest backend/tests/benchmark/vitality_decay_baseline.py
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

BENCHMARK_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = BENCHMARK_DIR.parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from db.sqlite_client import Memory, SQLiteClient  # noqa: E402

BASELINE_JSON_PATH = BENCHMARK_DIR / "vitality_decay_baseline.json"
DECAY_TOLERANCE = 1e-6


@dataclass(frozen=True)
class _DecaySeed:
    """One pre-decay memory state expressed independently of wall-clock time."""

    title: str
    initial_score: float
    age_days: float
    access_count: int


# A small grid chosen to exercise the curve:
#   * varied ages (no decay, half a half-life, two half-lives, four half-lives),
#   * a high-access memory exercising the resistance term,
#   * a high-access young memory verifying near-no-decay,
#   * a low-score memory that should clamp on the floor.
_DECAY_SEEDS: Tuple[_DecaySeed, ...] = (
    _DecaySeed(title="fresh_zero_age", initial_score=1.0, age_days=0.0, access_count=0),
    _DecaySeed(title="half_life", initial_score=1.0, age_days=30.0, access_count=0),
    _DecaySeed(title="two_half_lives", initial_score=1.5, age_days=60.0, access_count=0),
    _DecaySeed(
        title="four_half_lives", initial_score=2.0, age_days=120.0, access_count=0
    ),
    _DecaySeed(
        title="aged_with_access", initial_score=1.0, age_days=60.0, access_count=8
    ),
    _DecaySeed(
        title="young_with_access", initial_score=1.0, age_days=2.0, access_count=20
    ),
    _DecaySeed(
        title="floor_clamp", initial_score=0.06, age_days=240.0, access_count=0
    ),
)


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


def _expected_decay(
    *,
    initial_score: float,
    age_days: float,
    access_count: int,
    half_life_days: float,
    min_score: float,
) -> float:
    """Pure reference implementation of the documented formula."""

    resistance = 1.0 + min(2.0, math.log1p(max(0, int(access_count))) * 0.35)
    effective_age_days = max(0.0, float(age_days)) / resistance
    decay_ratio = math.exp(-effective_age_days / max(1.0, float(half_life_days)))
    next_score = max(float(min_score), float(initial_score) * decay_ratio)
    return next_score


async def _seed_memories(
    client: SQLiteClient,
    *,
    reference_time: datetime,
) -> Dict[str, int]:
    """Insert each seed memory and rewrite its decay-relevant columns."""

    id_by_title: Dict[str, int] = {}
    for seed in _DECAY_SEEDS:
        created = await client.create_memory(
            parent_path="",
            content=f"decay-baseline content for {seed.title}",
            priority=1,
            title=seed.title,
            domain="core",
        )
        memory_id = int(created["id"])
        id_by_title[seed.title] = memory_id

        async with client.session() as session:
            memory = await session.get(Memory, memory_id)
            assert memory is not None, f"memory {seed.title} missing after create"
            memory.vitality_score = float(seed.initial_score)
            memory.access_count = int(seed.access_count)
            memory.last_accessed_at = reference_time - timedelta(
                days=float(seed.age_days)
            )
            session.add(memory)
    return id_by_title


async def _measure_decay(db_path: Path) -> Dict[str, Any]:
    """Run one decay pass against a fully-controlled database."""

    client = SQLiteClient(_sqlite_url(db_path))
    try:
        await client.init_db()
        reference_time = datetime.now(timezone.utc).replace(tzinfo=None)
        id_by_title = await _seed_memories(client, reference_time=reference_time)

        decay_result = await client.apply_vitality_decay(
            force=True,
            reason="benchmark.vitality_decay_baseline",
            reference_time=reference_time,
        )

        per_memory: List[Dict[str, Any]] = []
        async with client.session() as session:
            for seed in _DECAY_SEEDS:
                memory = await session.get(Memory, id_by_title[seed.title])
                assert memory is not None
                observed = float(memory.vitality_score or 0.0)
                expected = _expected_decay(
                    initial_score=seed.initial_score,
                    age_days=seed.age_days,
                    access_count=seed.access_count,
                    half_life_days=float(decay_result["half_life_days"]),
                    min_score=float(client._vitality_decay_min_score),
                )
                per_memory.append(
                    {
                        "title": seed.title,
                        "initial_score": seed.initial_score,
                        "age_days": seed.age_days,
                        "access_count": seed.access_count,
                        "expected_score": round(expected, 9),
                        "observed_score": round(observed, 9),
                        "delta": round(observed - expected, 9),
                    }
                )

        stats = await client.get_vitality_stats()

        return {
            "config": {
                "half_life_days": float(decay_result["half_life_days"]),
                "min_score": float(client._vitality_decay_min_score),
                "cleanup_threshold": float(client._vitality_cleanup_threshold),
                "cleanup_inactive_days": float(
                    client._vitality_cleanup_inactive_days
                ),
                "reinforce_delta": float(client._vitality_reinforce_delta),
            },
            "decay_result": dict(decay_result),
            "per_memory": per_memory,
            "stats_after_decay": dict(stats),
            "seed_count": len(_DECAY_SEEDS),
            "tolerance": DECAY_TOLERANCE,
        }
    finally:
        await client.close()


def _write_snapshot(payload: Dict[str, Any], output_path: Path) -> Path:
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path


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
# pytest entry points
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vitality_decay_matches_documented_formula(tmp_path: Path) -> None:
    """Each seeded memory must decay to the analytically expected value."""

    db_path = tmp_path / "vitality_decay_baseline.db"
    snapshot = await _measure_decay(db_path)

    # Contract: decay was actually applied this run.
    assert snapshot["decay_result"]["applied"] is True
    assert snapshot["decay_result"]["checked_memories"] >= len(_DECAY_SEEDS)
    assert snapshot["decay_result"]["half_life_days"] >= 1.0

    # Contract: each per-row score matches the formula.
    for row in snapshot["per_memory"]:
        assert abs(float(row["delta"])) <= DECAY_TOLERANCE, (
            f"row {row['title']!r} deviates from formula by "
            f"{row['delta']!r} (expected={row['expected_score']!r}, "
            f"observed={row['observed_score']!r})"
        )

    # Contract: aggregate stats post-decay are consistent.
    stats = snapshot["stats_after_decay"]
    assert int(stats["total_memories"]) >= len(_DECAY_SEEDS)
    assert 0.0 <= float(stats["min_score"]) <= float(stats["max_score"])

    snapshot_path = _write_snapshot(snapshot, tmp_path / BASELINE_JSON_PATH.name)
    assert snapshot_path.exists()
    assert json.loads(snapshot_path.read_text(encoding="utf-8"))["seed_count"] == len(
        _DECAY_SEEDS
    )


def test_baseline_snapshot_artifact_is_writeable(tmp_path: Path) -> None:
    """Confirm the JSON artifact directory is writeable from this harness."""

    sentinel = tmp_path / ".vitality_decay_baseline_sentinel"
    sentinel.write_text("ok", encoding="utf-8")
    try:
        assert sentinel.read_text(encoding="utf-8") == "ok"
    finally:
        sentinel.unlink(missing_ok=True)


def test_reference_decay_formula_is_pure() -> None:
    """The reference helper must reproduce known anchor points exactly."""

    # zero age -> no decay.
    assert (
        _expected_decay(
            initial_score=1.0,
            age_days=0.0,
            access_count=0,
            half_life_days=30.0,
            min_score=0.05,
        )
        == pytest.approx(1.0, abs=DECAY_TOLERANCE)
    )

    # age == half_life_days with the source-coded formula
    # exp(-age/half_life) gives 1/e (~0.3679), not 0.5. The constant is
    # named "half_life_days" historically; the implementation in
    # SQLiteClient.apply_vitality_decay uses it as the time constant of
    # plain exponential decay.
    assert (
        _expected_decay(
            initial_score=1.0,
            age_days=30.0,
            access_count=0,
            half_life_days=30.0,
            min_score=0.05,
        )
        == pytest.approx(math.exp(-1.0), abs=DECAY_TOLERANCE)
    )

    # below floor -> clamp.
    assert (
        _expected_decay(
            initial_score=0.06,
            age_days=10_000.0,
            access_count=0,
            half_life_days=30.0,
            min_score=0.05,
        )
        == pytest.approx(0.05, abs=DECAY_TOLERANCE)
    )


__all__ = [
    "BASELINE_JSON_PATH",
    "DECAY_TOLERANCE",
    "_expected_decay",
]
