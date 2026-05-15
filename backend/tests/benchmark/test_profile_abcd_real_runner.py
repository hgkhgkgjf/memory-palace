import argparse
import sys
from pathlib import Path

import pytest
import requests

BENCHMARK_DIR = Path(__file__).resolve().parent
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))
BACKEND_ROOT = BENCHMARK_DIR.parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from db.sqlite_client import SQLiteClient

from helpers.common import (  # noqa: E402
    BENCHMARK_ARTIFACT_DIR,
    BENCHMARK_ARTIFACTS_ROOT,
)
from helpers.profile_abcd_real_runner import (  # noqa: E402
    DatasetBundle,
    QueryCase,
    REAL_PROFILE_CD_MARKDOWN_ARTIFACT,
    REAL_PROFILE_JSON_ARTIFACT,
    REAL_PROFILE_MARKDOWN_ARTIFACT,
    REAL_PROFILE_WORKDIR,
    PROFILE_CONFIGS,
    _build_comparison_rows,
    _evaluate_dataset,
    _preflight_profile_remote_dependencies,
    _run_profile,
    build_phase6_gate,
    compute_percentile,
    compute_retrieval_metrics,
    render_profile_cd_real_markdown,
    resolve_real_profile_workdir,
)
import run_profile_abcd_real  # noqa: E402


def test_default_benchmark_artifacts_use_run_scoped_directory() -> None:
    assert BENCHMARK_ARTIFACT_DIR.parent == BENCHMARK_ARTIFACTS_ROOT
    assert BENCHMARK_ARTIFACT_DIR != BENCHMARK_DIR
    assert BENCHMARK_DIR not in BENCHMARK_ARTIFACT_DIR.parents
    assert REAL_PROFILE_JSON_ARTIFACT.parent == BENCHMARK_ARTIFACT_DIR
    assert REAL_PROFILE_MARKDOWN_ARTIFACT.parent == BENCHMARK_ARTIFACT_DIR
    assert REAL_PROFILE_CD_MARKDOWN_ARTIFACT.parent == BENCHMARK_ARTIFACT_DIR


def test_compute_retrieval_metrics_binary_relevance_contract() -> None:
    metrics = compute_retrieval_metrics(
        retrieved_doc_ids=["d2", "d1", "d3", "d4"],
        relevant_doc_ids={"d1", "d4"},
        k=10,
    )
    assert metrics["hr_at_5"] == pytest.approx(1.0)
    assert metrics["hr_at_10"] == pytest.approx(1.0)
    assert metrics["mrr"] == pytest.approx(0.5)
    assert metrics["recall_at_10"] == pytest.approx(1.0)
    assert metrics["ndcg_at_10"] == pytest.approx(0.6509209, abs=1e-6)


def test_compute_percentile_linear_interpolation() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    assert compute_percentile(values, 0.50) == pytest.approx(2.5)
    assert compute_percentile(values, 0.95) == pytest.approx(3.85)
    assert compute_percentile([9.0], 0.95) == pytest.approx(9.0)


def test_build_phase6_gate_marks_invalid_when_profile_d_has_invalid_reasons() -> None:
    gate = build_phase6_gate(
        [
            {
                "dataset": "squad_v2_dev",
                "dataset_label": "SQuAD v2 Dev",
                "degradation": {"invalid_reasons": []},
            },
            {
                "dataset": "beir_nfcorpus",
                "dataset_label": "BEIR NFCorpus",
                "degradation": {"invalid_reasons": ["embedding_request_failed"]},
            },
        ]
    )
    assert gate["valid"] is False
    assert gate["invalid_reasons"] == ["embedding_request_failed"]
    assert gate["rows"][0]["valid"] is True
    assert gate["rows"][1]["valid"] is False


def test_build_phase6_gate_api_tolerant_allows_small_invalid_rate() -> None:
    gate = build_phase6_gate(
        [
            {
                "dataset": "beir_nfcorpus",
                "dataset_label": "BEIR NFCorpus",
                "degradation": {
                    "queries": 500,
                    "invalid_reasons": ["reranker_request_failed"],
                    "invalid_count": 2,
                    "invalid_rate": 0.004,
                    "request_failed_count": 2,
                    "request_failed_rate": 0.004,
                    "invalid_reason_counts": {"reranker_request_failed": 2},
                    "request_failed_reason_counts": {"reranker_request_failed": 2},
                },
            }
        ],
        mode="api_tolerant",
        invalid_rate_threshold=0.05,
    )
    assert gate["mode"] == "api_tolerant"
    assert gate["valid"] is True
    assert gate["invalid_count"] == 2
    assert gate["request_failed_count"] == 2
    assert gate["request_failed_reason_counts"] == {"reranker_request_failed": 2}
    assert gate["rows"][0]["valid"] is True


def test_build_phase6_gate_api_tolerant_marks_invalid_when_rate_exceeds_threshold() -> None:
    gate = build_phase6_gate(
        [
            {
                "dataset": "beir_nfcorpus",
                "dataset_label": "BEIR NFCorpus",
                "degradation": {
                    "queries": 500,
                    "invalid_reasons": ["reranker_request_failed"],
                    "invalid_count": 30,
                    "invalid_rate": 0.06,
                    "request_failed_count": 30,
                    "request_failed_rate": 0.06,
                },
            }
        ],
        mode="api_tolerant",
        invalid_rate_threshold=0.05,
    )
    assert gate["valid"] is False
    assert gate["rows"][0]["valid"] is False


def test_build_phase6_gate_api_tolerant_rejects_non_request_failed_invalid_reason() -> None:
    gate = build_phase6_gate(
        [
            {
                "dataset": "beir_nfcorpus",
                "dataset_label": "BEIR NFCorpus",
                "degradation": {
                    "queries": 500,
                    "invalid_reasons": ["embedding_fallback_hash"],
                    "invalid_count": 1,
                    "invalid_rate": 0.002,
                    "request_failed_count": 0,
                    "request_failed_rate": 0.0,
                },
            }
        ],
        mode="api_tolerant",
        invalid_rate_threshold=0.05,
    )
    assert gate["valid"] is False
    assert gate["rows"][0]["valid"] is False


def test_build_comparison_rows_respects_api_tolerant_gate_truth() -> None:
    rows = _build_comparison_rows(
        {
            "profile_a": {
                "rows": [
                    {
                        "dataset": "beir_nfcorpus",
                        "dataset_label": "BEIR NFCorpus",
                        "quality": {"hr_at_10": 0.2, "ndcg_at_10": 0.2},
                        "latency_ms": {"p95": 2.0},
                    }
                ]
            },
            "profile_b": {
                "rows": [
                    {
                        "dataset": "beir_nfcorpus",
                        "dataset_label": "BEIR NFCorpus",
                        "quality": {"hr_at_10": 0.23, "ndcg_at_10": 0.21},
                        "latency_ms": {"p95": 20.0},
                    }
                ]
            },
            "profile_c": {
                "rows": [
                    {
                        "dataset": "beir_nfcorpus",
                        "dataset_label": "BEIR NFCorpus",
                        "quality": {"hr_at_10": 0.5, "ndcg_at_10": 0.44},
                        "latency_ms": {"p95": 330.0},
                    }
                ]
            },
            "profile_d": {
                "rows": [
                    {
                        "dataset": "beir_nfcorpus",
                        "dataset_label": "BEIR NFCorpus",
                        "quality": {"hr_at_10": 0.6, "ndcg_at_10": 0.47},
                        "latency_ms": {"p95": 3300.0},
                        "degradation": {"invalid_reasons": ["reranker_request_failed"]},
                    }
                ]
            },
        },
        gate_rows_by_dataset={
            "beir_nfcorpus": {
                "valid": True,
                "invalid_reasons": ["reranker_request_failed"],
            }
        },
    )
    assert rows[0]["valid"] is True


def test_resolve_real_profile_workdir_respects_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expected = tmp_path / "custom-real-cache"
    monkeypatch.setenv("BENCHMARK_REAL_PROFILE_WORKDIR", str(expected))
    assert resolve_real_profile_workdir() == expected


def test_resolve_real_profile_workdir_prefers_explicit_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(
        "BENCHMARK_REAL_PROFILE_WORKDIR",
        str(tmp_path / "env-cache"),
    )
    explicit = tmp_path / "explicit-cache"
    assert resolve_real_profile_workdir(explicit) == explicit


def test_resolve_real_profile_workdir_allocates_unique_run_dir_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BENCHMARK_REAL_PROFILE_WORKDIR", raising=False)

    first = resolve_real_profile_workdir()
    second = resolve_real_profile_workdir()

    assert first != second
    assert first.parent == REAL_PROFILE_WORKDIR
    assert second.parent == REAL_PROFILE_WORKDIR
    assert first.name.startswith("run-")
    assert second.name.startswith("run-")


class _FakeProbeResponse:
    def __init__(self, *, status_code: int, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeProbeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.closed = False

    def post(self, url, *, json, headers, timeout):
        self.calls.append(
            {
                "url": url,
                "json": dict(json),
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_profile_c_preflight_fails_fast_when_embedding_provider_returns_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "http://10.0.0.8:11435/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_KEY", "embed-secret")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "embed-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "1024")
    monkeypatch.setenv("MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS", "10.0.0.8/32")

    fake_session = _FakeProbeSession(
        [
            _FakeProbeResponse(
                status_code=502,
                payload={"error": {"message": "upstream unavailable"}},
                text='{"error":{"message":"upstream unavailable"}}',
            )
        ]
    )
    monkeypatch.setattr(
        sys.modules[_run_profile.__module__],
        "_build_remote_probe_session",
        lambda: fake_session,
    )

    client = SQLiteClient("sqlite+aiosqlite:///:memory:")
    config = next(item for item in PROFILE_CONFIGS if item.key == "profile_c")
    try:
        with pytest.raises(RuntimeError, match="profile_c embedding preflight failed"):
            _preflight_profile_remote_dependencies(
                config=config,
                client=client,
                timeout_sec=1.0,
            )
    finally:
        await client.close()

    assert fake_session.closed is True
    assert fake_session.calls[0]["url"] == "http://10.0.0.8:11435/v1/embeddings"
    assert fake_session.calls[0]["headers"]["Authorization"] == "Bearer embed-secret"
    assert "X-API-Key" not in fake_session.calls[0]["headers"]


@pytest.mark.asyncio
async def test_profile_c_preflight_wraps_request_errors_into_clear_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "http://10.0.0.8:11435/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_KEY", "embed-secret")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "embed-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "1024")
    monkeypatch.setenv("MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS", "10.0.0.8/32")

    fake_session = _FakeProbeSession([requests.ReadTimeout("timed out")])
    monkeypatch.setattr(
        sys.modules[_run_profile.__module__],
        "_build_remote_probe_session",
        lambda: fake_session,
    )

    client = SQLiteClient("sqlite+aiosqlite:///:memory:")
    config = next(item for item in PROFILE_CONFIGS if item.key == "profile_c")
    try:
        with pytest.raises(RuntimeError, match="request_error:ReadTimeout"):
            _preflight_profile_remote_dependencies(
                config=config,
                client=client,
                timeout_sec=1.0,
            )
    finally:
        await client.close()

    assert fake_session.closed is True


@pytest.mark.asyncio
async def test_profile_c_preflight_retries_without_dimensions_when_provider_rejects_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "http://10.0.0.8:11435/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_KEY", "embed-secret")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "embed-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "1024")
    monkeypatch.setenv("MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS", "10.0.0.8/32")

    fake_session = _FakeProbeSession(
        [
            _FakeProbeResponse(
                status_code=400,
                payload={"error": {"message": "dimensions not supported"}},
                text='{"error":{"message":"dimensions not supported"}}',
            ),
            _FakeProbeResponse(
                status_code=200,
                payload={"data": [{"embedding": [0.1] * 1024}]},
            ),
        ]
    )
    monkeypatch.setattr(
        sys.modules[_run_profile.__module__],
        "_build_remote_probe_session",
        lambda: fake_session,
    )

    client = SQLiteClient("sqlite+aiosqlite:///:memory:")
    config = next(item for item in PROFILE_CONFIGS if item.key == "profile_c")
    try:
        _preflight_profile_remote_dependencies(
            config=config,
            client=client,
            timeout_sec=1.0,
        )
    finally:
        await client.close()

    assert len(fake_session.calls) == 2
    assert "dimensions" in fake_session.calls[0]["json"]
    assert "dimensions" not in fake_session.calls[1]["json"]
    assert fake_session.calls[0]["headers"]["Authorization"] == "Bearer embed-secret"
    assert "X-API-Key" not in fake_session.calls[0]["headers"]


@pytest.mark.asyncio
async def test_profile_d_preflight_reranker_uses_bearer_header_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "api")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_BASE", "http://10.0.0.8:11435/v1")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_API_KEY", "embed-secret")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_MODEL", "embed-model")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "1024")
    monkeypatch.setenv("RETRIEVAL_RERANKER_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_RERANKER_API_BASE", "http://10.0.0.9:8080/v1")
    monkeypatch.setenv("RETRIEVAL_RERANKER_API_KEY", "rerank-secret")
    monkeypatch.setenv("RETRIEVAL_RERANKER_MODEL", "rerank-model")
    monkeypatch.setenv(
        "MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS",
        "10.0.0.8/32,10.0.0.9/32",
    )

    fake_session = _FakeProbeSession(
        [
            _FakeProbeResponse(
                status_code=200,
                payload={"data": [{"embedding": [0.1] * 1024}]},
            ),
            _FakeProbeResponse(
                status_code=200,
                payload={
                    "results": [
                        {"index": 0, "relevance_score": 0.9},
                        {"index": 1, "relevance_score": 0.1},
                    ]
                },
            ),
        ]
    )
    monkeypatch.setattr(
        sys.modules[_run_profile.__module__],
        "_build_remote_probe_session",
        lambda: fake_session,
    )

    client = SQLiteClient("sqlite+aiosqlite:///:memory:")
    config = next(item for item in PROFILE_CONFIGS if item.key == "profile_d")
    try:
        _preflight_profile_remote_dependencies(
            config=config,
            client=client,
            timeout_sec=1.0,
        )
    finally:
        await client.close()

    assert fake_session.calls[1]["url"] == "http://10.0.0.9:8080/v1/rerank"
    assert fake_session.calls[1]["headers"]["Authorization"] == "Bearer rerank-secret"
    assert "X-API-Key" not in fake_session.calls[1]["headers"]


class _ProbeSearchClient:
    def __init__(self, result_rows):
        self._result_rows = list(result_rows)
        self.calls = []

    async def search_advanced(
        self,
        *,
        query: str,
        mode: str,
        max_results: int,
        candidate_multiplier: int,
        filters,
    ):
        self.calls.append(
            {
                "query": query,
                "mode": mode,
                "max_results": max_results,
                "candidate_multiplier": candidate_multiplier,
                "filters": dict(filters),
            }
        )
        return {
            "results": list(self._result_rows),
            "degraded": False,
            "degrade_reasons": [],
        }


@pytest.mark.asyncio
async def test_evaluate_dataset_passes_depth_params_and_keeps_top10_metrics() -> None:
    result_rows = [{"memory_id": memory_id} for memory_id in range(1, 13)]
    client = _ProbeSearchClient(result_rows)
    bundle = DatasetBundle(
        key="squad_v2_dev",
        label="SQuAD v2 Dev",
        domain="bench_squad_v2_dev",
        queries=[QueryCase(query_id="q-1", query="alpha", relevant_doc_ids={"doc_12"})],
        docs=[("doc_1", "doc one")],
        sample_bucket_size=100,
        query_count_raw=1,
    )
    memory_to_doc = {memory_id: f"doc_{memory_id}" for memory_id in range(1, 13)}

    row = await _evaluate_dataset(
        client=client,  # type: ignore[arg-type]
        bundle=bundle,
        profile_mode="hybrid",
        memory_to_doc=memory_to_doc,
        max_results=12,
        candidate_multiplier=9,
    )

    assert client.calls == [
        {
            "query": "alpha",
            "mode": "hybrid",
            "max_results": 12,
            "candidate_multiplier": 9,
            "filters": {"domain": "bench_squad_v2_dev"},
        }
    ]
    # Relevant doc is rank 12 in returned list; Top10 metrics must remain 0.
    assert row["quality"]["hr_at_10"] == pytest.approx(0.0)
    assert row["quality"]["mrr"] == pytest.approx(0.0)
    assert row["quality"]["ndcg_at_10"] == pytest.approx(0.0)
    assert row["quality"]["recall_at_10"] == pytest.approx(0.0)
    assert row["retrieval_depth"] == {
        "max_results": 12,
        "candidate_multiplier": 9,
        "metric_top_k": 10,
    }


class _PopulateStubClient:
    def __init__(self, *_args, **_kwargs) -> None:
        self._next_id = 1

    async def init_db(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def create_memory(self, **_kwargs):
        memory_id = self._next_id
        self._next_id += 1
        return {
            "id": memory_id,
            "index_report": {
                "degraded": True,
                "degrade_reasons": ["embedding_fallback_hash"],
                "invalid_reasons": ["embedding_fallback_hash"],
                "effective_backend": "hash",
            },
        }

    async def search_advanced(self, **_kwargs):
        return {
            "results": [{"memory_id": 1}],
            "degraded": False,
            "degrade_reasons": [],
        }


class _PreflightStubClient:
    instances = []

    def __init__(self, *_args, **_kwargs) -> None:
        self.init_db_called = False
        self.close_called = False
        self.create_memory_calls = 0
        self._remote_http_timeout_sec = 8.0
        self._embedding_backend = "api"
        self._embedding_api_base = "http://embed.local/v1"
        self._embedding_api_key = "embed-key"
        self._embedding_model = "embed-model"
        self._embedding_dim = 1024
        self._reranker_enabled = False
        self._reranker_api_base = ""
        self._reranker_api_key = ""
        self._reranker_model = ""
        type(self).instances.append(self)

    def _resolve_embedding_api_base(self, _backend: str) -> str:
        return self._embedding_api_base

    def _resolve_embedding_model(self, _backend: str) -> str:
        return self._embedding_model

    @staticmethod
    def _build_embedding_payload(model: str, content: str, *, dimensions: int):
        payload = {"model": model, "input": content}
        if int(dimensions) > 0:
            payload["dimensions"] = int(dimensions)
        return payload

    @staticmethod
    def _join_api_url(base: str, endpoint: str) -> str:
        return f"{base.rstrip('/')}{endpoint}"

    @staticmethod
    def _build_embedding_retry_payload_without_dimensions(**_kwargs):
        return None

    def _extract_embedding_from_response(self, payload):
        if not isinstance(payload, dict):
            return None
        rows = payload.get("data")
        if not isinstance(rows, list) or not rows:
            return None
        row = rows[0]
        if not isinstance(row, dict):
            return None
        embedding = row.get("embedding")
        return embedding if isinstance(embedding, list) else None

    def _validate_embedding_dimension(
        self,
        embedding,
        degrade_reasons=None,
        backend=None,
    ):
        del degrade_reasons, backend
        if isinstance(embedding, list) and len(embedding) == self._embedding_dim:
            return embedding
        return None

    async def init_db(self) -> None:
        self.init_db_called = True

    async def close(self) -> None:
        self.close_called = True

    async def create_memory(self, **_kwargs):
        self.create_memory_calls += 1
        raise AssertionError("provider preflight should fail before create_memory")


@pytest.mark.asyncio
async def test_run_profile_surfaces_index_time_degradation_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = DatasetBundle(
        key="squad_v2_dev",
        label="SQuAD v2 Dev",
        domain="bench_squad_v2_dev",
        queries=[QueryCase(query_id="q-1", query="alpha", relevant_doc_ids={"doc-1"})],
        docs=[("doc-1", "doc one")],
        sample_bucket_size=100,
        query_count_raw=1,
    )
    config = next(item for item in PROFILE_CONFIGS if item.key == "profile_c")

    monkeypatch.setattr(sys.modules[_run_profile.__module__], "SQLiteClient", _PopulateStubClient)

    profile_payload, _mapping, _indexing = await _run_profile(
        config=config,
        bundles=[bundle],
        db_path=tmp_path / "profile-c.db",
        max_results=10,
        candidate_multiplier=8,
        existing_mapping=None,
        existing_indexing=None,
        populate=True,
    )

    row = profile_payload["rows"][0]
    assert row["indexing"]["degraded"] is True
    assert row["indexing"]["degrade_reasons"] == ["embedding_fallback_hash"]
    assert row["indexing"]["effective_backend"] == "hash"


@pytest.mark.asyncio
async def test_run_profile_fails_fast_when_embedding_preflight_returns_502(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = DatasetBundle(
        key="squad_v2_dev",
        label="SQuAD v2 Dev",
        domain="bench_squad_v2_dev",
        queries=[QueryCase(query_id="q-1", query="alpha", relevant_doc_ids={"doc-1"})],
        docs=[("doc-1", "doc one")],
        sample_bucket_size=100,
        query_count_raw=1,
    )
    config = next(item for item in PROFILE_CONFIGS if item.key == "profile_c")
    _PreflightStubClient.instances = []
    fake_session = _FakeProbeSession(
        [_FakeProbeResponse(status_code=502, text="bad gateway")]
    )

    monkeypatch.setattr(sys.modules[_run_profile.__module__], "SQLiteClient", _PreflightStubClient)
    monkeypatch.setattr(
        sys.modules[_run_profile.__module__],
        "_build_remote_probe_session",
        lambda: fake_session,
    )

    with pytest.raises(RuntimeError, match="profile_c embedding preflight failed.*status=502"):
        await _run_profile(
            config=config,
            bundles=[bundle],
            db_path=tmp_path / "profile-c.db",
            max_results=10,
            candidate_multiplier=8,
            existing_mapping=None,
            existing_indexing=None,
            populate=True,
            provider_preflight_timeout=1.5,
        )

    assert len(fake_session.calls) == 1
    assert fake_session.calls[0]["url"] == "http://embed.local/v1/embeddings"
    assert fake_session.calls[0]["json"]["model"] == "embed-model"
    assert fake_session.calls[0]["json"]["input"]
    assert fake_session.calls[0]["timeout"] == pytest.approx(1.5)
    assert _PreflightStubClient.instances[0].init_db_called is False
    assert _PreflightStubClient.instances[0].create_memory_calls == 0
    assert _PreflightStubClient.instances[0].close_called is True


def test_run_profile_cli_parse_args_exposes_provider_preflight_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_profile_abcd_real.py",
            "--provider-preflight-timeout",
            "1.5",
            "--skip-provider-preflight",
        ],
    )

    args = run_profile_abcd_real.parse_args()

    assert args.provider_preflight_timeout == pytest.approx(1.5)
    assert args.skip_provider_preflight is True


def test_run_profile_cli_main_returns_clear_error_on_preflight_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(run_profile_abcd_real, "parse_args", lambda: argparse.Namespace())

    async def _fake_run(_args) -> None:
        raise RuntimeError("profile_c embedding preflight failed | status=502")

    monkeypatch.setattr(run_profile_abcd_real, "_run", _fake_run)

    assert run_profile_abcd_real.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert (
        captured.err.strip()
        == "[benchmark] failed: profile_c embedding preflight failed | status=502"
    )


def test_render_profile_cd_real_markdown_surfaces_observed_degradation_truthfully() -> None:
    markdown = render_profile_cd_real_markdown(
        {
            "generated_at_utc": "2026-04-17T09:44:27+00:00",
            "profiles": {
                "profile_c": {
                    "rows": [
                        {
                            "dataset": "squad_v2_dev",
                            "dataset_label": "SQuAD v2 Dev",
                            "query_count": 1,
                            "corpus_doc_count": 1,
                            "quality": {
                                "hr_at_10": 1.0,
                                "mrr": 1.0,
                                "ndcg_at_10": 1.0,
                                "recall_at_10": 1.0,
                            },
                            "latency_ms": {"p95": 10.0},
                            "degradation": {
                                "degrade_rate": 0.0,
                                "invalid_reasons": [],
                            },
                            "indexing": {
                                "degraded": True,
                                "degrade_reasons": ["embedding_fallback_hash"],
                                "invalid_reasons": ["embedding_fallback_hash"],
                                "effective_backend": "hash",
                            },
                        }
                    ]
                },
                "profile_d": {
                    "rows": [
                        {
                            "dataset": "squad_v2_dev",
                            "dataset_label": "SQuAD v2 Dev",
                            "query_count": 1,
                            "corpus_doc_count": 1,
                            "quality": {
                                "hr_at_10": 1.0,
                                "mrr": 1.0,
                                "ndcg_at_10": 1.0,
                                "recall_at_10": 1.0,
                            },
                            "latency_ms": {"p95": 20.0},
                            "degradation": {
                                "degrade_rate": 0.0,
                                "invalid_reasons": [],
                            },
                            "indexing": {
                                "degraded": True,
                                "degrade_reasons": ["embedding_fallback_hash"],
                                "invalid_reasons": ["embedding_fallback_hash"],
                                "effective_backend": "hash",
                            },
                        }
                    ]
                },
            },
            "phase6": {
                "gate": {
                    "valid": False,
                    "mode": "strict",
                    "invalid_rate_threshold": 0.0,
                    "invalid_reasons": ["embedding_fallback_hash"],
                    "invalid_count": 1,
                    "query_count": 1,
                    "invalid_rate": 1.0,
                    "request_failed_count": 0,
                    "request_failed_rate": 0.0,
                    "rows": [
                        {
                            "dataset_label": "SQuAD v2 Dev",
                            "valid": False,
                            "invalid_reasons": ["embedding_fallback_hash"],
                            "invalid_count": 1,
                            "invalid_rate": 1.0,
                            "request_failed_count": 0,
                            "request_failed_rate": 0.0,
                        }
                    ],
                }
            },
        }
    )

    assert "observed degradation" in markdown.lower()
    assert "index-time degradation" in markdown.lower()
    assert "> mode: real API embedding/reranker execution" not in markdown
