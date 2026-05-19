import json
from pathlib import Path
from typing import Any, Dict

import pytest

import mcp_server
from api import maintenance as maintenance_api
from db.sqlite_client import SQLiteClient
from shared_utils import (
    resolve_interaction_tier as _resolve_interaction_tier_shared,
    should_try_intent_llm as _should_try_intent_llm_shared,
)


async def _noop_async(*_: Any, **__: Any) -> None:
    return None


class _FakeSearchClient:
    def __init__(self) -> None:
        self.search_query: str = ""
        self.intent_profile: Dict[str, Any] = {}
        self.received_filters: Dict[str, Any] = {}

    def preprocess_query(self, query: str) -> Dict[str, Any]:
        rewritten = " ".join(query.lower().replace("?", "").split())
        return {
            "original_query": query,
            "normalized_query": rewritten,
            "rewritten_query": rewritten,
            "tokens": rewritten.split(),
            "changed": rewritten != query,
        }

    def classify_intent(self, _query: str, rewritten_query: str) -> Dict[str, Any]:
        if "when" in rewritten_query:
            return {
                "intent": "temporal",
                "strategy_template": "temporal_time_filtered",
                "method": "keyword_heuristic",
                "confidence": 0.86,
                "signals": ["temporal_keywords"],
            }
        if "why" in rewritten_query:
            return {
                "intent": "causal",
                "strategy_template": "causal_wide_pool",
                "method": "keyword_heuristic",
                "confidence": 0.82,
                "signals": ["causal_keywords"],
            }
        return {
            "intent": "factual",
            "strategy_template": "factual_high_precision",
            "method": "keyword_heuristic",
            "confidence": 0.72,
            "signals": ["default_factual"],
        }

    async def search_advanced(
        self,
        *,
        query: str,
        mode: str,
        max_results: int,
        candidate_multiplier: int,
        filters: Dict[str, Any],
        intent_profile: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        self.search_query = query
        self.intent_profile = dict(intent_profile or {})
        self.received_filters = dict(filters)
        _ = mode
        _ = max_results
        _ = candidate_multiplier
        return {
            "mode": "hybrid",
            "degraded": False,
            "degrade_reasons": [],
            "metadata": {
                "intent": self.intent_profile.get("intent"),
                "strategy_template": self.intent_profile.get("strategy_template"),
                "candidate_multiplier_applied": candidate_multiplier,
            },
            "results": [
                {
                    "uri": "core://agent/index",
                    "memory_id": 11,
                    "snippet": "Index rebuilt last night.",
                    "priority": 1,
                    "updated_at": "2026-02-16T12:00:00Z",
                    "scores": {"final": 0.9, "text": 0.6, "vector": 0.7},
                    "metadata": {
                        "domain": "core",
                        "path": "agent/index",
                        "priority": 1,
                        "updated_at": "2026-02-16T12:00:00Z",
                    },
                }
            ],
        }


class _IntentLlmSearchClient(_FakeSearchClient):
    async def classify_intent_with_llm(
        self, _query: str, _rewritten_query: str
    ) -> Dict[str, Any]:
        return {
            "intent": "causal",
            "strategy_template": "causal_wide_pool",
            "method": "intent_llm",
            "confidence": 0.91,
            "signals": ["intent_llm:causal"],
            "intent_llm_enabled": True,
            "intent_llm_applied": True,
        }


class _AmbiguousIntentSearchClient(_FakeSearchClient):
    def classify_intent(self, _query: str, _rewritten_query: str) -> Dict[str, Any]:
        return {
            "intent": "unknown",
            "strategy_template": "default",
            "method": "keyword_scoring_v2",
            "confidence": 0.46,
            "signals": ["causal:why", "temporal:before"],
        }


class _AmbiguousIntentLlmSearchClient(_AmbiguousIntentSearchClient):
    async def classify_intent_with_llm(
        self, _query: str, _rewritten_query: str
    ) -> Dict[str, Any]:
        return {
            "intent": "causal",
            "strategy_template": "causal_wide_pool",
            "method": "intent_llm",
            "confidence": 0.91,
            "signals": ["intent_llm:causal"],
            "intent_llm_enabled": True,
            "intent_llm_applied": True,
        }


class _IntentLlmFailureSearchClient(_FakeSearchClient):
    async def classify_intent_with_llm(
        self, _query: str, _rewritten_query: str
    ) -> Dict[str, Any]:
        raise RuntimeError("intent_llm_forced_failure")


class _AmbiguousIntentLlmFailureSearchClient(_AmbiguousIntentSearchClient):
    async def classify_intent_with_llm(
        self, _query: str, _rewritten_query: str
    ) -> Dict[str, Any]:
        raise RuntimeError("intent_llm_forced_failure")


class _AmbiguousIntentLlmEmptyResponseSearchClient(_AmbiguousIntentSearchClient):
    async def classify_intent_with_llm(
        self, query: str, rewritten_query: str
    ) -> Dict[str, Any]:
        fallback = self.classify_intent(query, rewritten_query)
        return {
            **fallback,
            "intent_llm_enabled": True,
            "intent_llm_applied": False,
            "degraded": True,
            "degrade_reason": "intent_llm_response_empty",
            "degrade_reasons": ["intent_llm_response_empty"],
        }


class _AmbiguousIntentLlmInvalidJsonSearchClient(_AmbiguousIntentSearchClient):
    async def classify_intent_with_llm(
        self, query: str, rewritten_query: str
    ) -> Dict[str, Any]:
        fallback = self.classify_intent(query, rewritten_query)
        return {
            **fallback,
            "intent_llm_enabled": True,
            "intent_llm_applied": False,
            "degraded": True,
            "degrade_reason": "intent_llm_response_invalid",
            "degrade_reasons": ["intent_llm_response_invalid"],
        }


class _NoIntentClient:
    def __init__(self) -> None:
        self.search_query: str = ""
        self.intent_profile: Dict[str, Any] = {}

    def preprocess_query(self, query: str) -> Dict[str, Any]:
        return {
            "original_query": query,
            "normalized_query": query,
            "rewritten_query": query,
            "tokens": [],
            "changed": False,
        }

    async def search_advanced(
        self,
        *,
        query: str,
        mode: str,
        max_results: int,
        candidate_multiplier: int,
        filters: Dict[str, Any],
        intent_profile: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        self.search_query = query
        self.intent_profile = dict(intent_profile or {})
        _ = mode
        _ = max_results
        _ = candidate_multiplier
        _ = filters
        return {"mode": "hybrid", "degraded": False, "degrade_reasons": [], "results": []}


class _LegacySearchClient:
    def __init__(self) -> None:
        self.search_query: str = ""
        self.received_filters: Dict[str, Any] = {}

    def preprocess_query(self, query: str) -> Dict[str, Any]:
        return {
            "original_query": query,
            "normalized_query": query,
            "rewritten_query": query,
            "tokens": [],
            "changed": False,
        }

    def classify_intent(self, _query: str, _rewritten_query: str) -> Dict[str, Any]:
        return {
            "intent": "factual",
            "strategy_template": "factual_high_precision",
            "method": "keyword_heuristic",
            "confidence": 0.72,
            "signals": ["default_factual"],
        }

    async def search_advanced(
        self,
        *,
        query: str,
        mode: str,
        max_results: int,
        candidate_multiplier: int,
        filters: Dict[str, Any],
    ) -> Dict[str, Any]:
        self.search_query = query
        self.received_filters = dict(filters)
        _ = mode
        _ = max_results
        _ = candidate_multiplier
        return {"mode": "hybrid", "degraded": False, "degrade_reasons": [], "results": []}


@pytest.mark.asyncio
async def test_search_memory_uses_preprocessed_query_and_returns_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeSearchClient()
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(mcp_server, "_record_session_hit", _noop_async)
    monkeypatch.setattr(mcp_server, "_record_flush_event", _noop_async)

    raw = await mcp_server.search_memory(
        query="When did we rebuild index?",
        mode="hybrid",
        include_session=False,
    )
    payload = json.loads(raw)

    assert payload["ok"] is True
    assert payload["query"] == "When did we rebuild index?"
    assert payload["query_effective"] == "when did we rebuild index"
    assert payload["intent"] == "temporal"
    assert payload["intent_profile"]["strategy_template"] == "temporal_time_filtered"
    assert fake_client.search_query == "when did we rebuild index"
    assert fake_client.intent_profile["intent"] == "temporal"
    assert payload["intent_applied"] == "temporal"
    assert payload["strategy_template_applied"] == "temporal_time_filtered"
    assert payload["interaction_tier"] == "fast"
    assert payload["intent_llm_attempted"] is False
    assert payload["candidate_multiplier_applied"] == 4


def test_interaction_tier_helpers_are_imported_from_shared_utils() -> None:
    assert mcp_server._resolve_interaction_tier is _resolve_interaction_tier_shared
    assert maintenance_api._resolve_interaction_tier is _resolve_interaction_tier_shared
    assert mcp_server._should_try_intent_llm is _should_try_intent_llm_shared
    assert maintenance_api._should_try_intent_llm is _should_try_intent_llm_shared


@pytest.mark.parametrize(
    "raw_filters",
    [
        {"domain": " CORE "},
        {"path_prefix": "core://agent/index"},
        {
            "domain": "writer",
            "path_prefix": "chapter_1/scene_2/",
            "max_priority": "2",
            "updated_after": "2026-01-31T12:00:00Z",
        },
        {"priority": 1},
    ],
)
def test_maintenance_normalize_search_filters_matches_mcp_server_contract(
    raw_filters: Dict[str, Any],
) -> None:
    assert maintenance_api._normalize_search_filters(
        raw_filters
    ) == mcp_server._normalize_search_filters(raw_filters)


@pytest.mark.parametrize(
    "raw_filters",
    [
        {"max_priority": True},
        {"domain": "invalid"},
        {"updated_after": "not-a-date"},
        {"unknown": "value"},
    ],
)
def test_maintenance_normalize_search_filters_raises_same_as_mcp_server(
    raw_filters: Dict[str, Any],
) -> None:
    with pytest.raises(ValueError) as maintenance_exc:
        maintenance_api._normalize_search_filters(raw_filters)
    with pytest.raises(ValueError) as mcp_exc:
        mcp_server._normalize_search_filters(raw_filters)

    assert str(maintenance_exc.value) == str(mcp_exc.value)


@pytest.mark.parametrize(
    "normalize_filters",
    [
        maintenance_api._normalize_search_filters,
        mcp_server._normalize_search_filters,
    ],
    ids=["maintenance", "mcp"],
)
def test_normalize_search_filters_rejects_conflicting_domain_and_uri_path_prefix(
    normalize_filters: Any,
) -> None:
    with pytest.raises(ValueError):
        normalize_filters({"domain": "core", "path_prefix": "writer://chapter_1"})


@pytest.mark.parametrize(
    "scope_hint",
    [
        None,
        "",
        "deep",
        "core",
        "core://agent/index",
        "agent/index",
    ],
)
def test_maintenance_scope_hint_contract_matches_mcp_server(
    scope_hint: Any,
) -> None:
    assert maintenance_api._normalize_scope_hint(
        scope_hint
    ) == mcp_server._normalize_scope_hint(scope_hint)


def test_maintenance_scope_merge_contract_matches_mcp_server() -> None:
    normalized_filters = {"domain": "core", "path_prefix": "agent"}
    normalized_scope_hint = {"provided": True, "raw": "core://agent/index", "domain": "core", "path_prefix": "agent/index", "strategy": "uri_prefix"}

    assert maintenance_api._merge_scope_hint_with_filters(
        normalized_filters=normalized_filters,
        scope_hint=normalized_scope_hint,
    ) == mcp_server._merge_scope_hint_with_filters(
        normalized_filters=normalized_filters,
        scope_hint=normalized_scope_hint,
    )


@pytest.mark.asyncio
async def test_search_memory_degrades_to_unknown_when_classifier_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _NoIntentClient()
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(mcp_server, "_record_session_hit", _noop_async)
    monkeypatch.setattr(mcp_server, "_record_flush_event", _noop_async)

    raw = await mcp_server.search_memory(
        query="index diagnostics",
        mode="hybrid",
        include_session=False,
    )
    payload = json.loads(raw)

    assert payload["ok"] is True
    assert payload["intent"] == "unknown"
    assert payload["strategy_template"] == "default"
    assert "intent_classification_unavailable" in payload.get("degrade_reasons", [])
    assert fake_client.intent_profile == {}


@pytest.mark.asyncio
async def test_search_memory_supports_legacy_search_advanced_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _LegacySearchClient()
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(mcp_server, "_record_session_hit", _noop_async)
    monkeypatch.setattr(mcp_server, "_record_flush_event", _noop_async)

    raw = await mcp_server.search_memory(
        query="legacy compatibility",
        mode="hybrid",
        include_session=False,
        filters={"domain": "core"},
    )
    payload = json.loads(raw)

    assert payload["ok"] is True
    assert fake_client.search_query == "legacy compatibility"
    assert fake_client.received_filters == {"domain": "core"}


@pytest.mark.asyncio
async def test_search_memory_marks_degrade_when_intent_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _AmbiguousIntentSearchClient()
    monkeypatch.setattr(mcp_server, "INTENT_LLM_ENABLED", True)
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(mcp_server, "_record_session_hit", _noop_async)
    monkeypatch.setattr(mcp_server, "_record_flush_event", _noop_async)

    raw = await mcp_server.search_memory(
        query="before or after maybe why timeline",
        mode="hybrid",
        include_session=False,
        filters={"interaction_tier": "deep"},
    )
    payload = json.loads(raw)

    assert payload["ok"] is True
    assert payload["intent_llm_enabled"] is True
    assert payload["intent_llm_applied"] is False
    assert "intent_llm_unavailable" in payload.get("degrade_reasons", [])


@pytest.mark.asyncio
async def test_deep_tier_skips_intent_llm_when_rule_classifier_is_confident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _IntentLlmSearchClient()
    monkeypatch.setattr(mcp_server, "INTENT_LLM_ENABLED", True)
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(mcp_server, "_record_session_hit", _noop_async)
    monkeypatch.setattr(mcp_server, "_record_flush_event", _noop_async)

    raw = await mcp_server.search_memory(
        query="When did we rebuild index?",
        mode="hybrid",
        include_session=False,
        filters={"interaction_tier": "deep"},
    )
    payload = json.loads(raw)

    assert payload["ok"] is True
    assert payload["intent"] == "temporal"
    assert payload["intent_llm_enabled"] is True
    assert payload["intent_llm_attempted"] is False
    assert payload["intent_llm_applied"] is False
    assert fake_client.intent_profile["method"] == "keyword_heuristic"


@pytest.mark.asyncio
async def test_deep_tier_calls_intent_llm_for_unknown_rule_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _AmbiguousIntentLlmSearchClient()
    monkeypatch.setattr(mcp_server, "INTENT_LLM_ENABLED", True)
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(mcp_server, "_record_session_hit", _noop_async)
    monkeypatch.setattr(mcp_server, "_record_flush_event", _noop_async)

    raw = await mcp_server.search_memory(
        query="before or after maybe why timeline",
        mode="hybrid",
        include_session=False,
        filters={"interaction_tier": "deep"},
    )
    payload = json.loads(raw)

    assert payload["ok"] is True
    assert payload["intent"] == "causal"
    assert payload["intent_llm_attempted"] is True
    assert payload["intent_llm_applied"] is True
    assert fake_client.intent_profile["method"] == "intent_llm"


@pytest.mark.asyncio
async def test_search_memory_falls_back_to_rule_classifier_when_intent_llm_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _AmbiguousIntentLlmFailureSearchClient()
    monkeypatch.setattr(mcp_server, "INTENT_LLM_ENABLED", True)
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(mcp_server, "_record_session_hit", _noop_async)
    monkeypatch.setattr(mcp_server, "_record_flush_event", _noop_async)

    raw = await mcp_server.search_memory(
        query="before or after maybe why timeline",
        mode="hybrid",
        include_session=False,
        filters={"interaction_tier": "deep"},
    )
    payload = json.loads(raw)

    assert payload["ok"] is True
    assert payload["intent"] == "unknown"
    assert payload["strategy_template"] == "default"
    assert payload["intent_llm_enabled"] is True
    assert payload["intent_llm_applied"] is False
    assert payload["intent_llm_attempted"] is True
    assert "intent_classification_failed" in payload.get("degrade_reasons", [])
    assert "intent_llm_fallback_rule_applied" in payload.get("degrade_reasons", [])


@pytest.mark.asyncio
async def test_search_memory_falls_back_when_intent_llm_returns_empty_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _AmbiguousIntentLlmEmptyResponseSearchClient()
    monkeypatch.setattr(mcp_server, "INTENT_LLM_ENABLED", True)
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(mcp_server, "_record_session_hit", _noop_async)
    monkeypatch.setattr(mcp_server, "_record_flush_event", _noop_async)

    raw = await mcp_server.search_memory(
        query="before or after maybe why timeline",
        mode="hybrid",
        include_session=False,
        filters={"interaction_tier": "deep"},
    )
    payload = json.loads(raw)

    assert payload["ok"] is True
    assert payload["intent"] == "unknown"
    assert payload["strategy_template"] == "default"
    assert payload["intent_llm_enabled"] is True
    assert payload["intent_llm_applied"] is False
    assert payload["intent_llm_attempted"] is True
    assert payload["degraded"] is True
    assert "intent_llm_response_empty" in payload.get("degrade_reasons", [])
    assert payload["intent_profile"]["method"] == "keyword_scoring_v2"


@pytest.mark.asyncio
async def test_search_memory_falls_back_when_intent_llm_returns_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _AmbiguousIntentLlmInvalidJsonSearchClient()
    monkeypatch.setattr(mcp_server, "INTENT_LLM_ENABLED", True)
    monkeypatch.setattr(mcp_server, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(mcp_server, "_record_session_hit", _noop_async)
    monkeypatch.setattr(mcp_server, "_record_flush_event", _noop_async)

    raw = await mcp_server.search_memory(
        query="before or after maybe why timeline",
        mode="hybrid",
        include_session=False,
        filters={"interaction_tier": "deep"},
    )
    payload = json.loads(raw)

    assert payload["ok"] is True
    assert payload["intent"] == "unknown"
    assert payload["strategy_template"] == "default"
    assert payload["intent_llm_enabled"] is True
    assert payload["intent_llm_applied"] is False
    assert payload["intent_llm_attempted"] is True
    assert payload["degraded"] is True
    assert "intent_llm_response_invalid" in payload.get("degrade_reasons", [])
    assert payload["intent_profile"]["method"] == "keyword_scoring_v2"


@pytest.mark.asyncio
async def test_observability_search_returns_intent_and_query_effective(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeSearchClient()

    async def _ensure_started(_factory) -> None:
        return None

    monkeypatch.setattr(maintenance_api, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(maintenance_api.runtime_state, "ensure_started", _ensure_started)

    async with maintenance_api._search_events_guard:
        maintenance_api._search_events.clear()

    payload = maintenance_api.SearchConsoleRequest(
        query="Why did index rebuild fail?",
        mode="hybrid",
        include_session=False,
    )
    response = await maintenance_api.run_observability_search(payload)

    assert response["ok"] is True
    assert response["query"] == "Why did index rebuild fail?"
    assert response["query_effective"] == "why did index rebuild fail"
    assert response["intent"] == "causal"
    assert response["intent_profile"]["strategy_template"] == "causal_wide_pool"
    assert response["interaction_tier"] == "fast"
    assert response["intent_llm_attempted"] is False
    assert fake_client.search_query == "why did index rebuild fail"
    assert fake_client.intent_profile["intent"] == "causal"
    assert fake_client.received_filters == {}


@pytest.mark.asyncio
async def test_observability_search_falls_back_to_rule_classifier_when_intent_llm_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _AmbiguousIntentLlmFailureSearchClient()

    async def _ensure_started(_factory) -> None:
        return None

    monkeypatch.setattr(maintenance_api, "_INTENT_LLM_ENABLED", True)
    monkeypatch.setattr(maintenance_api, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(maintenance_api.runtime_state, "ensure_started", _ensure_started)

    payload = maintenance_api.SearchConsoleRequest(
        query="before or after maybe why timeline",
        mode="hybrid",
        include_session=False,
        filters={"interaction_tier": "deep"},
    )
    response = await maintenance_api.run_observability_search(payload)

    assert response["ok"] is True
    assert response["intent"] == "unknown"
    assert response["intent_applied"] == "unknown"
    assert response["strategy_template"] == "default"
    assert response["intent_llm_enabled"] is True
    assert response["intent_llm_applied"] is False
    assert response["intent_llm_attempted"] is True
    assert "intent_classification_failed" in response["degrade_reasons"]
    assert "intent_llm_fallback_rule_applied" in response["degrade_reasons"]


@pytest.mark.asyncio
async def test_observability_search_deep_tier_skips_intent_llm_when_rule_classifier_is_confident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _IntentLlmSearchClient()

    async def _ensure_started(_factory) -> None:
        return None

    monkeypatch.setattr(maintenance_api, "_INTENT_LLM_ENABLED", True)
    monkeypatch.setattr(maintenance_api, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(maintenance_api.runtime_state, "ensure_started", _ensure_started)

    payload = maintenance_api.SearchConsoleRequest(
        query="When did index rebuild fail?",
        mode="hybrid",
        include_session=False,
        filters={"interaction_tier": "deep"},
    )
    response = await maintenance_api.run_observability_search(payload)

    assert response["ok"] is True
    assert response["intent"] == "temporal"
    assert response["intent_llm_attempted"] is False
    assert response["intent_llm_applied"] is False


@pytest.mark.asyncio
async def test_observability_search_exposes_session_first_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeSearchClient()

    async def _ensure_started(_factory) -> None:
        return None

    async def _session_search(*_args: Any, **_kwargs: Any):
        return [
            {
                "uri": "core://agent/index",
                "memory_id": 11,
                "snippet": "session cached entry",
                "priority": 1,
                "score": 0.95,
                "keyword_score": 0.91,
                "updated_at": "2026-02-16T12:00:00Z",
            }
        ]

    monkeypatch.setattr(maintenance_api, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(maintenance_api.runtime_state, "ensure_started", _ensure_started)
    monkeypatch.setattr(
        maintenance_api.runtime_state.session_cache, "search", _session_search
    )

    payload = maintenance_api.SearchConsoleRequest(
        query="index diagnostics",
        mode="hybrid",
        include_session=True,
        session_id="obs-session-1",
    )
    response = await maintenance_api.run_observability_search(payload)

    assert response["ok"] is True
    metrics = response["session_first_metrics"]
    assert metrics["session_candidates"] == 1
    assert metrics["global_candidates"] == 1
    assert metrics["dedup_dropped"] == 1
    assert metrics["session_contributed"] == 1
    assert metrics["global_contributed"] == 0


@pytest.mark.asyncio
async def test_observability_search_requires_explicit_session_id_for_session_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeSearchClient()
    session_calls = 0

    async def _ensure_started(_factory) -> None:
        return None

    async def _session_search(*_args: Any, **_kwargs: Any):
        nonlocal session_calls
        session_calls += 1
        return []

    monkeypatch.setattr(maintenance_api, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(maintenance_api.runtime_state, "ensure_started", _ensure_started)
    monkeypatch.setattr(
        maintenance_api.runtime_state.session_cache, "search", _session_search
    )

    payload = maintenance_api.SearchConsoleRequest(
        query="index diagnostics",
        mode="hybrid",
        include_session=True,
    )
    response = await maintenance_api.run_observability_search(payload)

    assert response["ok"] is True
    assert response["counts"]["session"] == 0
    assert session_calls == 0


@pytest.mark.asyncio
async def test_observability_search_marks_degrade_when_session_cache_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeSearchClient()

    async def _ensure_started(_factory) -> None:
        return None

    async def _session_search_fail(*_args: Any, **_kwargs: Any):
        raise RuntimeError("session_cache_forced_failure")

    monkeypatch.setattr(maintenance_api, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(maintenance_api.runtime_state, "ensure_started", _ensure_started)
    monkeypatch.setattr(
        maintenance_api.runtime_state.session_cache, "search", _session_search_fail
    )

    payload = maintenance_api.SearchConsoleRequest(
        query="index diagnostics",
        mode="hybrid",
        include_session=True,
        session_id="obs-session-2",
    )
    response = await maintenance_api.run_observability_search(payload)

    assert response["ok"] is True
    assert response["degraded"] is True
    assert "session_cache_lookup_failed" in response.get("degrade_reasons", [])


@pytest.mark.asyncio
async def test_observability_search_accepts_integer_max_priority_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeSearchClient()

    async def _ensure_started(_factory) -> None:
        return None

    monkeypatch.setattr(maintenance_api, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(maintenance_api.runtime_state, "ensure_started", _ensure_started)

    async with maintenance_api._search_events_guard:
        maintenance_api._search_events.clear()

    payload = maintenance_api.SearchConsoleRequest(
        query="index diagnostics",
        mode="hybrid",
        include_session=False,
        filters={"max_priority": "2"},
    )
    response = await maintenance_api.run_observability_search(payload)

    assert response["ok"] is True
    assert fake_client.received_filters == {"max_priority": 2}


@pytest.mark.asyncio
async def test_observability_search_rejects_non_integer_max_priority_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeSearchClient()

    async def _ensure_started(_factory) -> None:
        return None

    monkeypatch.setattr(maintenance_api, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(maintenance_api.runtime_state, "ensure_started", _ensure_started)

    payload = maintenance_api.SearchConsoleRequest(
        query="index diagnostics",
        mode="hybrid",
        include_session=False,
        filters={"max_priority": "1.9"},
    )
    with pytest.raises(maintenance_api.HTTPException) as exc_info:
        await maintenance_api.run_observability_search(payload)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == {
        "error": "invalid_search_filters",
        "reason": "ValueError",
    }


@pytest.mark.asyncio
async def test_preprocess_query_preserves_uri_and_multilingual_content(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "week3-preprocess.db"
    client = SQLiteClient(f"sqlite+aiosqlite:///{db_path}")

    uri_result = client.preprocess_query("core://agent/index")
    mixed_lang_result = client.preprocess_query("昨天 index 为什么失败")

    await client.close()

    assert uri_result["rewritten_query"] == "core://agent/index"
    assert mixed_lang_result["rewritten_query"] == "昨天 index 为什么失败"


@pytest.mark.asyncio
async def test_intent_llm_can_use_fallback_chat_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "week3-intent-llm-fallback.db"
    monkeypatch.setenv("INTENT_LLM_ENABLED", "true")
    monkeypatch.setenv(
        "INTENT_LLM_API_BASE",
        "http://127.0.0.1:8999/v1/chat/completions",
    )
    monkeypatch.setenv("INTENT_LLM_MODEL", "test-mini-model")
    client = SQLiteClient(f"sqlite+aiosqlite:///{db_path}")
    captured: Dict[str, Any] = {}

    async def _fake_post_json(
        base: str,
        endpoint: str,
        payload: Dict[str, Any],
        api_key: str = "",
        error_sink: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        captured["base"] = base
        captured["endpoint"] = endpoint
        captured["payload"] = dict(payload)
        captured["api_key"] = api_key
        _ = error_sink
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "intent": "causal",
                                "confidence": 0.83,
                                "signals": ["intent_llm:causal"],
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(client, "_post_json", _fake_post_json)
    payload = await client.classify_intent_with_llm(
        "before or after maybe why timeline",
        "before or after maybe why timeline",
    )
    await client.close()

    assert payload["intent_llm_applied"] is True
    assert captured["base"] == "http://127.0.0.1:8999/v1"
    assert captured["endpoint"] == "/chat/completions"


@pytest.mark.asyncio
async def test_observability_session_cache_uses_rewritten_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeSearchClient()
    captured: Dict[str, Any] = {}

    async def _ensure_started(_factory) -> None:
        return None

    async def _session_search(*, session_id: str, query: str, limit: int):
        captured["session_id"] = session_id
        captured["query"] = query
        captured["limit"] = limit
        return []

    monkeypatch.setattr(maintenance_api, "get_sqlite_client", lambda: fake_client)
    monkeypatch.setattr(maintenance_api.runtime_state, "ensure_started", _ensure_started)
    monkeypatch.setattr(maintenance_api.runtime_state.session_cache, "search", _session_search)

    payload = maintenance_api.SearchConsoleRequest(
        query="Why did index rebuild fail?",
        mode="hybrid",
        include_session=True,
        session_id="api-observability",
    )
    response = await maintenance_api.run_observability_search(payload)

    assert response["ok"] is True
    assert captured["query"] == "why did index rebuild fail"
    assert captured["session_id"] == "api-observability"


@pytest.mark.asyncio
async def test_observability_search_keeps_fast_tier_candidate_cap_for_causal_queries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "week3-observability-fast-cap.db"
    client = SQLiteClient(f"sqlite+aiosqlite:///{db_path}")
    await client.init_db()

    async def _ensure_started(_factory) -> None:
        return None

    monkeypatch.setattr(maintenance_api, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(maintenance_api.runtime_state, "ensure_started", _ensure_started)

    try:
        payload = maintenance_api.SearchConsoleRequest(
            query="Why did index rebuild fail?",
            mode="hybrid",
            include_session=False,
        )
        response = await maintenance_api.run_observability_search(payload)
    finally:
        await client.close()

    assert response["ok"] is True
    assert response["interaction_tier"] == "fast"
    assert response["intent"] == "causal"
    assert response["candidate_multiplier"] == 4
    assert (
        response["backend_metadata"]["metadata"]["candidate_multiplier_applied"] == 4
    )


@pytest.mark.asyncio
async def test_observability_search_fast_tier_ignores_raised_env_cap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "week3-observability-fast-cap-env.db"
    client = SQLiteClient(f"sqlite+aiosqlite:///{db_path}")
    await client.init_db()

    async def _ensure_started(_factory) -> None:
        return None

    monkeypatch.setattr(maintenance_api, "_FAST_INTERACTION_CANDIDATE_MULTIPLIER", 9)
    monkeypatch.setattr(maintenance_api, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(maintenance_api.runtime_state, "ensure_started", _ensure_started)

    try:
        payload = maintenance_api.SearchConsoleRequest(
            query="Why did index rebuild fail?",
            mode="hybrid",
            include_session=False,
        )
        response = await maintenance_api.run_observability_search(payload)
    finally:
        await client.close()

    assert response["ok"] is True
    assert response["interaction_tier"] == "fast"
    assert response["candidate_multiplier"] == 4
    assert (
        response["backend_metadata"]["metadata"]["candidate_multiplier_applied"] == 4
    )
