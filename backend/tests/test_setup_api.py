import importlib
import os
import tempfile
import errno
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import setup as setup_api
from db.sqlite_client import (
    DEFAULT_EMBEDDING_BACKEND,
    DEFAULT_EMBEDDING_DIM,
    SQLiteClient,
)


@pytest.fixture(autouse=True)
def _clear_pre_dotenv_env_keys_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMORY_PALACE_PRE_DOTENV_ENV_KEYS", raising=False)


def _build_client(*, client=("127.0.0.1", 50000)) -> TestClient:
    app = FastAPI()
    app.include_router(setup_api.router)
    return TestClient(app, client=client, base_url="http://127.0.0.1")


def _reload_setup_api() -> None:
    importlib.reload(setup_api)


def _reset_setup_api_state() -> None:
    reset_target_env = Path(tempfile.gettempdir()) / "memory-palace-setup-reset.env"
    reset_target_env.unlink(missing_ok=True)
    os.environ["MEMORY_PALACE_SETUP_ENV_FILE"] = str(reset_target_env)
    os.environ.pop("MEMORY_PALACE_PRE_DOTENV_ENV_KEYS", None)
    for key in setup_api._SETUP_MANAGED_ENV_KEYS:
        os.environ.pop(key, None)
    _reload_setup_api()
    os.environ.pop("MEMORY_PALACE_SETUP_ENV_FILE", None)
    os.environ.pop("MEMORY_PALACE_PRE_DOTENV_ENV_KEYS", None)
    for key in setup_api._SETUP_MANAGED_ENV_KEYS:
        os.environ.pop(key, None)


def test_setup_status_allows_loopback_without_api_key(monkeypatch, tmp_path: Path) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text("MCP_API_KEY=\n", encoding="utf-8")
    target_env = tmp_path / ".env"

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.get("/setup/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["apply_supported"] is True
    assert payload["write_supported"] is True
    assert payload["write_reason"] == "local_env_file"
    assert payload["target_label"] == ".env"
    assert payload["summary"]["dashboard_auth_configured"] is False


def test_setup_status_defaults_to_runtime_hash_backend_when_env_missing(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "\n".join(
            [
                "MCP_API_KEY=",
                "RETRIEVAL_EMBEDDING_BACKEND=none",
                "RETRIEVAL_RERANKER_ENABLED=false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.delenv("RETRIEVAL_EMBEDDING_BACKEND", raising=False)
    monkeypatch.delenv("RETRIEVAL_EMBEDDING_DIM", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.get("/setup/status")

    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["embedding_backend"] == DEFAULT_EMBEDDING_BACKEND
    assert summary["embedding_dim"] == DEFAULT_EMBEDDING_DIM
    assert summary["embedding_configured"] is True

    runtime_client = SQLiteClient(f"sqlite+aiosqlite:///{tmp_path / 'setup-defaults.db'}")
    assert runtime_client._embedding_backend == summary["embedding_backend"]
    assert runtime_client._embedding_dim == summary["embedding_dim"]


def test_setup_status_marks_remote_embedding_incomplete_without_dimension(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "\n".join(
            [
                "MCP_API_KEY=",
                "RETRIEVAL_EMBEDDING_BACKEND=openai",
                "RETRIEVAL_EMBEDDING_API_BASE=https://api.openai.com/v1",
                "RETRIEVAL_EMBEDDING_MODEL=text-embedding-3-large",
                "RETRIEVAL_RERANKER_ENABLED=false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"
    target_env.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.get("/setup/status")

    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["embedding_backend"] == "openai"
    assert summary["embedding_dim"] is None
    assert summary["embedding_configured"] is False


def test_setup_status_rejects_non_loopback_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)

    with _build_client(client=("203.0.113.10", 50000)) as client:
        response = client.get("/setup/status")

    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["error"] == "setup_access_denied"
    assert detail["reason"] == "local_loopback_or_api_key_required"


def test_setup_status_rejects_loopback_peer_when_host_header_is_not_loopback(
    monkeypatch,
) -> None:
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)

    with _build_client(client=("127.0.0.1", 50000)) as client:
        response = client.get(
            "/setup/status",
            headers={"Host": "memory-palace.example"},
        )

    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["error"] == "setup_access_denied"
    assert detail["reason"] == "local_loopback_or_api_key_required"


def test_setup_status_allows_ipv6_loopback_without_api_key(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text("MCP_API_KEY=\n", encoding="utf-8")
    target_env = tmp_path / ".env"

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client(client=("::1", 50000)) as client:
        response = client.get(
            "/setup/status",
            headers={"Host": "[::1]:8000"},
        )

    assert response.status_code == 200
    assert response.json()["apply_supported"] is True


def test_setup_status_accepts_authenticated_remote_request(monkeypatch, tmp_path: Path) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text("MCP_API_KEY=\n", encoding="utf-8")
    target_env = tmp_path / ".env"

    monkeypatch.setenv("MCP_API_KEY", "setup-secret")
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client(client=("203.0.113.10", 50000)) as client:
        response = client.get(
            "/setup/status",
            headers={"X-MCP-API-Key": "setup-secret"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["apply_supported"] is True
    assert payload["write_supported"] is False
    assert payload["write_reason"] == "local_loopback_required_for_write"


def test_write_env_file_retries_atomic_replace_after_transient_permission_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target_env = tmp_path / ".env"
    target_env.write_text("EXISTING=1\n", encoding="utf-8")
    replace_calls: list[tuple[str, str]] = []
    original_replace = setup_api.os.replace

    def _flaky_replace(src: str, dst: str) -> None:
        replace_calls.append((src, dst))
        if len(replace_calls) == 1:
            raise PermissionError(errno.EACCES, "locked", dst)
        original_replace(src, dst)

    monkeypatch.setattr(setup_api.os, "replace", _flaky_replace)

    setup_api._write_env_file(
        target_env,
        {"UPDATED": "2"},
    )

    written = target_env.read_text(encoding="utf-8")
    assert "EXISTING=1" in written
    assert "UPDATED=2" in written
    assert len(replace_calls) == 2


def test_setup_status_loopback_requires_api_key_for_write_when_configured(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text("MCP_API_KEY=\n", encoding="utf-8")
    target_env = tmp_path / ".env"

    monkeypatch.setenv("MCP_API_KEY", "setup-secret")
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.get("/setup/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["apply_supported"] is True
    assert payload["write_supported"] is False
    assert payload["write_reason"] == "local_api_key_required_for_write"


def test_setup_status_rejects_target_env_outside_project_root(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text("MCP_API_KEY=\n", encoding="utf-8")
    target_env = tmp_path.parent / ".env.outside"

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.get("/setup/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["apply_supported"] is False
    assert payload["apply_reason"] == "target_env_outside_project"
    assert payload["write_supported"] is False
    assert payload["write_reason"] == "target_env_outside_project"


def test_setup_status_does_not_create_target_parent_during_support_probe(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text("MCP_API_KEY=\n", encoding="utf-8")
    target_env = tmp_path / "nested" / ".env.local"

    monkeypatch.setenv("MCP_API_KEY", "setup-secret")
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    assert target_env.parent.exists() is False

    with _build_client(client=("203.0.113.10", 50000)) as client:
        response = client.get(
            "/setup/status",
            headers={"X-MCP-API-Key": "setup-secret"},
        )

    assert response.status_code == 200
    assert response.json()["apply_supported"] is True
    assert target_env.parent.exists() is False


def test_setup_import_preserves_explicit_process_override(monkeypatch, tmp_path: Path) -> None:
    target_env = tmp_path / ".env"
    target_env.write_text(
        "RETRIEVAL_EMBEDDING_BACKEND=hash\nRETRIEVAL_EMBEDDING_DIM=64\n",
        encoding="utf-8",
    )

    try:
        with monkeypatch.context() as scoped:
            scoped.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))
            scoped.setenv(
                "MEMORY_PALACE_PRE_DOTENV_ENV_KEYS",
                '["RETRIEVAL_EMBEDDING_BACKEND","RETRIEVAL_EMBEDDING_DIM"]',
            )
            scoped.setenv("RETRIEVAL_EMBEDDING_BACKEND", "router")
            scoped.setenv("RETRIEVAL_EMBEDDING_DIM", "1024")
            _reload_setup_api()

            assert setup_api._read_optional_env("RETRIEVAL_EMBEDDING_BACKEND") == "router"
            assert setup_api._read_optional_env("RETRIEVAL_EMBEDDING_DIM") == "1024"
    finally:
        _reset_setup_api_state()


def test_setup_status_refresh_preserves_explicit_process_override(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text("MCP_API_KEY=\n", encoding="utf-8")
    target_env = tmp_path / ".env"
    target_env.write_text(
        "RETRIEVAL_EMBEDDING_BACKEND=hash\nRETRIEVAL_EMBEDDING_DIM=64\n",
        encoding="utf-8",
    )

    try:
        with monkeypatch.context() as scoped:
            scoped.delenv("MCP_API_KEY", raising=False)
            scoped.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
            scoped.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))
            scoped.setenv(
                "MEMORY_PALACE_PRE_DOTENV_ENV_KEYS",
                '["RETRIEVAL_EMBEDDING_BACKEND","RETRIEVAL_EMBEDDING_DIM"]',
            )
            scoped.setenv("RETRIEVAL_EMBEDDING_BACKEND", "router")
            scoped.setenv("RETRIEVAL_EMBEDDING_DIM", "1024")
            _reload_setup_api()
            scoped.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)

            with _build_client() as client:
                response = client.get("/setup/status")

            assert response.status_code == 200
            summary = response.json()["summary"]
            assert summary["embedding_backend"] == "router"
            assert summary["embedding_dim"] == 1024
            assert setup_api._read_optional_env("RETRIEVAL_EMBEDDING_BACKEND") == "router"
            assert setup_api._read_optional_env("RETRIEVAL_EMBEDDING_DIM") == "1024"
    finally:
        _reset_setup_api_state()


def test_setup_config_refresh_preserves_explicit_process_override(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "MCP_API_KEY=\nRETRIEVAL_EMBEDDING_BACKEND=router\nRETRIEVAL_EMBEDDING_DIM=1024\n",
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"
    target_env.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")

    try:
        with monkeypatch.context() as scoped:
            scoped.delenv("MCP_API_KEY", raising=False)
            scoped.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
            scoped.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))
            scoped.setenv(
                "MEMORY_PALACE_PRE_DOTENV_ENV_KEYS",
                '["RETRIEVAL_EMBEDDING_BACKEND","RETRIEVAL_EMBEDDING_DIM"]',
            )
            scoped.setenv("RETRIEVAL_EMBEDDING_BACKEND", "router")
            scoped.setenv("RETRIEVAL_EMBEDDING_DIM", "1024")
            _reload_setup_api()
            scoped.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)

            with _build_client() as client:
                response = client.post(
                    "/setup/config",
                    json={
                        "dashboard_api_key": "local-secret",
                        "allow_insecure_local": False,
                        "embedding_backend": "hash",
                    },
                )

            assert response.status_code == 200
            body = response.json()
            written = target_env.read_text(encoding="utf-8")
            assert "RETRIEVAL_EMBEDDING_BACKEND=hash" in written
            assert "RETRIEVAL_EMBEDDING_DIM=64" in written
            assert body["summary"]["embedding_backend"] == "router"
            assert body["summary"]["embedding_dim"] == 1024
            assert setup_api._read_optional_env("RETRIEVAL_EMBEDDING_BACKEND") == "router"
            assert setup_api._read_optional_env("RETRIEVAL_EMBEDDING_DIM") == "1024"
    finally:
        _reset_setup_api_state()


def test_setup_config_refreshes_startup_dotenv_values_after_local_save(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "MCP_API_KEY=router-secret\nRETRIEVAL_EMBEDDING_BACKEND=hash\nRETRIEVAL_EMBEDDING_DIM=64\n",
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"
    target_env.write_text(
        "MCP_API_KEY=router-secret\nRETRIEVAL_EMBEDDING_BACKEND=hash\nRETRIEVAL_EMBEDDING_DIM=64\n",
        encoding="utf-8",
    )

    try:
        with monkeypatch.context() as scoped:
            scoped.setenv("MCP_API_KEY", "router-secret")
            scoped.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
            scoped.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))
            # Simulate main.py having already loaded the same .env into process env.
            scoped.setenv("MEMORY_PALACE_PRE_DOTENV_ENV_KEYS", "[]")
            scoped.setenv("RETRIEVAL_EMBEDDING_BACKEND", "router")
            scoped.setenv("RETRIEVAL_EMBEDDING_DIM", "2048")
            _reload_setup_api()
            scoped.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
            scoped.setenv("MCP_API_KEY", "router-secret")
            scoped.setenv("RETRIEVAL_EMBEDDING_BACKEND", "router")
            scoped.setenv("RETRIEVAL_EMBEDDING_DIM", "2048")

            with _build_client() as client:
                response = client.post(
                    "/setup/config",
                    headers={"X-MCP-API-Key": "router-secret"},
                    json={
                        "dashboard_api_key": "   ",
                        "allow_insecure_local": False,
                        "embedding_backend": "router",
                        "embedding_dim": 1024,
                        "reranker_enabled": True,
                        "router_api_base": "http://127.0.0.1:8001/v1",
                        "router_embedding_model": "local-router-embed",
                        "router_reranker_model": "local-router-rerank",
                    },
                )

            assert response.status_code == 200
            body = response.json()
            assert body["summary"]["embedding_backend"] == "router"
            assert body["summary"]["embedding_dim"] == 1024
            assert setup_api._read_optional_env("RETRIEVAL_EMBEDDING_BACKEND") == "router"
            assert setup_api._read_optional_env("RETRIEVAL_EMBEDDING_DIM") == "1024"
    finally:
        _reset_setup_api_state()


def test_setup_config_first_local_save_limits_persistence_to_local_auth_fields(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "\n".join(
            [
                "MCP_API_KEY=",
                "MCP_API_KEY_ALLOW_INSECURE_LOCAL=false",
                "RETRIEVAL_EMBEDDING_BACKEND=hash",
                "RETRIEVAL_RERANKER_ENABLED=false",
                "WRITE_GUARD_LLM_ENABLED=false",
                "INTENT_LLM_ENABLED=false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.delenv("RETRIEVAL_EMBEDDING_BACKEND", raising=False)
    monkeypatch.delenv("RETRIEVAL_EMBEDDING_DIM", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    payload = {
        "dashboard_api_key": "local-secret",
        "allow_insecure_local": True,
        "embedding_backend": "api",
        "embedding_dim": "1024",
        "embedding_api_base": "http://127.0.0.1:9100/v1",
        "embedding_model": "local-embedding-model",
        "reranker_enabled": True,
        "reranker_api_base": "http://127.0.0.1:9200/v1",
        "reranker_model": "local-reranker-model",
        "write_guard_llm_enabled": True,
        "write_guard_llm_api_base": "http://127.0.0.1:9300/v1",
        "write_guard_llm_model": "local-guard-model",
        "intent_llm_enabled": True,
        "intent_llm_api_base": "http://127.0.0.1:9400/v1",
        "intent_llm_model": "local-intent-model",
    }

    with _build_client() as client:
        response = client.post("/setup/config", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["summary"]["dashboard_auth_configured"] is True
    assert body["summary"]["embedding_backend"] == "hash"
    assert body["summary"]["reranker_enabled"] is False
    assert body["summary"]["write_guard_enabled"] is False
    assert body["summary"]["intent_llm_enabled"] is False
    assert body["immediate_env_refresh"] == [
        "MCP_API_KEY",
        "MCP_API_KEY_ALLOW_INSECURE_LOCAL",
    ]
    assert body["saved_keys"] == [
        "MCP_API_KEY",
        "MCP_API_KEY_ALLOW_INSECURE_LOCAL",
    ]

    written = target_env.read_text(encoding="utf-8")
    assert "MCP_API_KEY=local-secret" in written
    assert "MCP_API_KEY_ALLOW_INSECURE_LOCAL=true" in written
    assert "RETRIEVAL_EMBEDDING_BACKEND=hash" in written
    assert "RETRIEVAL_RERANKER_ENABLED=false" in written
    assert "WRITE_GUARD_LLM_ENABLED=false" in written
    assert "INTENT_LLM_ENABLED=false" in written
    assert "RETRIEVAL_EMBEDDING_API_BASE=http://127.0.0.1:9100/v1" not in written
    assert "RETRIEVAL_RERANKER_API_BASE=http://127.0.0.1:9200/v1" not in written
    assert "WRITE_GUARD_LLM_API_BASE=http://127.0.0.1:9300/v1" not in written
    assert "INTENT_LLM_API_BASE=http://127.0.0.1:9400/v1" not in written
    assert written.count("MCP_API_KEY=") == 1

    assert setup_api._get_configured_mcp_api_key() == "local-secret"
    assert setup_api._env_bool("MCP_API_KEY_ALLOW_INSECURE_LOCAL", False) is True


def test_setup_config_preserves_existing_secret_when_blank(monkeypatch, tmp_path: Path) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "MCP_API_KEY=\nRETRIEVAL_EMBEDDING_BACKEND=hash\n",
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"
    target_env.write_text(
        "MCP_API_KEY=existing-secret\nRETRIEVAL_EMBEDDING_BACKEND=hash\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("MCP_API_KEY", "existing-secret")
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.post(
            "/setup/config",
            headers={"X-MCP-API-Key": "existing-secret"},
            json={
                "dashboard_api_key": "   ",
                "allow_insecure_local": False,
                "embedding_backend": "hash",
            },
        )

    assert response.status_code == 200
    written = target_env.read_text(encoding="utf-8")
    assert "MCP_API_KEY=existing-secret" in written
    assert written.count("MCP_API_KEY=") == 1


def test_setup_status_refreshes_setup_managed_env_from_target_file_after_restart(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text("MCP_API_KEY=\n", encoding="utf-8")
    target_env = tmp_path / ".env"
    target_env.write_text(
        "\n".join(
            [
                "MCP_API_KEY=",
                "MCP_API_KEY_ALLOW_INSECURE_LOCAL=false",
                "RETRIEVAL_EMBEDDING_BACKEND=hash",
                "RETRIEVAL_EMBEDDING_DIM=64",
                "RETRIEVAL_RERANKER_ENABLED=false",
                "ROUTER_API_BASE=",
                "ROUTER_API_KEY=",
                "ROUTER_CHAT_MODEL=",
                "ROUTER_EMBEDDING_MODEL=",
                "ROUTER_RERANKER_MODEL=",
                "WRITE_GUARD_LLM_ENABLED=false",
                "WRITE_GUARD_LLM_API_BASE=",
                "WRITE_GUARD_LLM_API_KEY=",
                "WRITE_GUARD_LLM_MODEL=",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("RETRIEVAL_EMBEDDING_BACKEND", "router")
    monkeypatch.setenv("RETRIEVAL_EMBEDDING_DIM", "1024")
    monkeypatch.setenv("ROUTER_API_BASE", "https://stale-router.example/v1")
    monkeypatch.setenv("ROUTER_EMBEDDING_MODEL", "stale-router-model")
    monkeypatch.setenv("WRITE_GUARD_LLM_ENABLED", "true")
    monkeypatch.setenv("WRITE_GUARD_LLM_API_BASE", "https://stale-guard.example/v1")
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.get("/setup/status")

    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["embedding_backend"] == "hash"
    assert summary["embedding_dim"] == 64
    assert summary["router_configured"] is False
    assert summary["write_guard_enabled"] is False
    assert setup_api._read_optional_env("RETRIEVAL_EMBEDDING_BACKEND") == "hash"
    assert setup_api._read_optional_env("RETRIEVAL_EMBEDDING_DIM") == "64"
    assert os.getenv("ROUTER_API_BASE") is None
    assert os.getenv("ROUTER_EMBEDDING_MODEL") is None
    assert os.getenv("WRITE_GUARD_LLM_API_BASE") is None
    assert os.getenv("WRITE_GUARD_LLM_ENABLED") == "false"


def test_setup_config_rejects_router_profile_without_required_remote_fields(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "\n".join(
            [
                "MCP_API_KEY=",
                "RETRIEVAL_EMBEDDING_BACKEND=hash",
                "RETRIEVAL_RERANKER_ENABLED=false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.post(
            "/setup/config",
            json={
                "dashboard_api_key": "router-secret",
                "allow_insecure_local": False,
                "embedding_backend": "router",
                "reranker_enabled": True,
            },
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "setup_validation_failed"
    assert "embedding_dim" in detail["missing_fields"]
    assert "router_api_base" in detail["missing_fields"]
    assert "router_embedding_model" in detail["missing_fields"]
    assert "router_reranker_model" in detail["missing_fields"]


def test_setup_config_clears_hidden_router_and_llm_fields_when_switching_back_to_hash(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "\n".join(
            [
                "MCP_API_KEY=",
                "RETRIEVAL_EMBEDDING_BACKEND=router",
                "RETRIEVAL_EMBEDDING_DIM=1024",
                "RETRIEVAL_RERANKER_ENABLED=true",
                "ROUTER_API_BASE=https://router.example/v1",
                "ROUTER_API_KEY=router-secret",
                "ROUTER_CHAT_MODEL=router-chat",
                "ROUTER_EMBEDDING_MODEL=router-embed",
                "ROUTER_RERANKER_MODEL=router-rerank",
                "WRITE_GUARD_LLM_ENABLED=true",
                "WRITE_GUARD_LLM_API_BASE=https://guard.example/v1",
                "WRITE_GUARD_LLM_API_KEY=guard-secret",
                "WRITE_GUARD_LLM_MODEL=guard-model",
                "INTENT_LLM_ENABLED=true",
                "INTENT_LLM_API_BASE=https://intent.example/v1",
                "INTENT_LLM_API_KEY=intent-secret",
                "INTENT_LLM_MODEL=intent-model",
                "",
            ]
        ),
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"
    target_env.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.post(
            "/setup/config",
            json={
                "dashboard_api_key": "local-secret",
                "allow_insecure_local": False,
                "embedding_backend": "hash",
                "reranker_enabled": False,
                "write_guard_llm_enabled": False,
                "intent_llm_enabled": False,
            },
        )

    assert response.status_code == 200
    written = target_env.read_text(encoding="utf-8")
    assert "RETRIEVAL_EMBEDDING_BACKEND=hash" in written
    assert "RETRIEVAL_EMBEDDING_DIM=64" in written
    assert "RETRIEVAL_RERANKER_ENABLED=false" in written
    assert "ROUTER_API_BASE=" in written
    assert "ROUTER_API_KEY=" in written
    assert "ROUTER_CHAT_MODEL=" in written
    assert "ROUTER_EMBEDDING_MODEL=" in written
    assert "ROUTER_RERANKER_MODEL=" in written
    assert "WRITE_GUARD_LLM_ENABLED=false" in written
    assert "WRITE_GUARD_LLM_API_BASE=" in written
    assert "WRITE_GUARD_LLM_API_KEY=" in written
    assert "WRITE_GUARD_LLM_MODEL=" in written
    assert "INTENT_LLM_ENABLED=false" in written
    assert "INTENT_LLM_API_BASE=" in written
    assert "INTENT_LLM_API_KEY=" in written
    assert "INTENT_LLM_MODEL=" in written


def test_setup_config_persists_profile_b_with_hybrid_search_mode(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "\n".join(
            [
                "MCP_API_KEY=",
                "SEARCH_DEFAULT_MODE=keyword",
                "RETRIEVAL_EMBEDDING_BACKEND=none",
                "RETRIEVAL_RERANKER_ENABLED=false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"
    target_env.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.delenv("SEARCH_DEFAULT_MODE", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.post(
            "/setup/config",
            json={
                "dashboard_api_key": "local-secret",
                "allow_insecure_local": False,
                "embedding_backend": "hash",
                "reranker_enabled": False,
                "write_guard_llm_enabled": False,
                "intent_llm_enabled": False,
            },
        )

    assert response.status_code == 200
    written = target_env.read_text(encoding="utf-8")
    assert "SEARCH_DEFAULT_MODE=hybrid" in written
    assert "RETRIEVAL_EMBEDDING_BACKEND=hash" in written
    assert "RETRIEVAL_EMBEDDING_DIM=64" in written
    assert "RETRIEVAL_RERANKER_ENABLED=false" in written
    assert setup_api._read_optional_env("SEARCH_DEFAULT_MODE") == "hybrid"


def test_setup_config_accepts_openai_backend_and_persists_embedding_dim(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "\n".join(
            [
                "MCP_API_KEY=",
                "MCP_API_KEY_ALLOW_INSECURE_LOCAL=false",
                "RETRIEVAL_EMBEDDING_BACKEND=hash",
                "RETRIEVAL_EMBEDDING_DIM=64",
                "RETRIEVAL_RERANKER_ENABLED=false",
                "WRITE_GUARD_LLM_ENABLED=false",
                "INTENT_LLM_ENABLED=false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"
    target_env.write_text(
        env_example.read_text(encoding="utf-8").replace(
            "MCP_API_KEY=",
            "MCP_API_KEY=openai-secret",
            1,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("MCP_API_KEY", "openai-secret")
    monkeypatch.delenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    payload = {
        "dashboard_api_key": "openai-secret",
        "allow_insecure_local": False,
        "embedding_backend": "openai",
        "embedding_api_base": "https://api.openai.com/v1",
        "embedding_api_key": "sk-test",
        "embedding_model": "text-embedding-3-large",
        "embedding_dim": 3072,
    }

    with _build_client() as client:
        response = client.post(
            "/setup/config",
            headers={"X-MCP-API-Key": "openai-secret"},
            json=payload,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["summary"]["embedding_backend"] == "openai"
    written = target_env.read_text(encoding="utf-8")
    assert "RETRIEVAL_EMBEDDING_BACKEND=openai" in written
    assert "RETRIEVAL_EMBEDDING_DIM=3072" in written


def test_setup_config_write_failure_does_not_leak_raw_os_error(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "\n".join(
            [
                "MCP_API_KEY=",
                "MCP_API_KEY_ALLOW_INSECURE_LOCAL=false",
                "RETRIEVAL_EMBEDDING_BACKEND=hash",
                "RETRIEVAL_EMBEDDING_DIM=64",
                "RETRIEVAL_RERANKER_ENABLED=false",
                "WRITE_GUARD_LLM_ENABLED=false",
                "INTENT_LLM_ENABLED=false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"

    def _raise_write_failure(*args, **kwargs):
        _ = args, kwargs
        raise OSError(errno.EACCES, "secret path /tmp/private")

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setattr(setup_api, "_write_env_file", _raise_write_failure)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.post(
            "/setup/config",
            json={
                "dashboard_api_key": "write-secret",
                "allow_insecure_local": False,
                "embedding_backend": "hash",
            },
        )

    assert response.status_code == 500
    assert "secret path" not in response.text
    assert "/tmp/private" not in response.text
    assert response.json()["detail"] == {
        "error": "setup_write_failed",
        "reason": "internal_error",
    }


def test_setup_config_rejects_openai_backend_without_embedding_dim_when_no_remote_dim_exists(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "\n".join(
            [
                "MCP_API_KEY=",
                "MCP_API_KEY_ALLOW_INSECURE_LOCAL=false",
                "RETRIEVAL_EMBEDDING_BACKEND=hash",
                "RETRIEVAL_EMBEDDING_DIM=64",
                "RETRIEVAL_RERANKER_ENABLED=false",
                "WRITE_GUARD_LLM_ENABLED=false",
                "INTENT_LLM_ENABLED=false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.delenv("RETRIEVAL_EMBEDDING_BACKEND", raising=False)
    monkeypatch.delenv("RETRIEVAL_EMBEDDING_DIM", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    payload = {
        "dashboard_api_key": "openai-secret",
        "allow_insecure_local": False,
        "embedding_backend": "openai",
        "embedding_api_base": "https://api.openai.com/v1",
        "embedding_api_key": "sk-test",
        "embedding_model": "text-embedding-3-large",
    }

    with _build_client() as client:
        response = client.post("/setup/config", json=payload)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "setup_validation_failed"
    assert "embedding_dim" in detail["missing_fields"]
    assert not target_env.exists()


def test_setup_config_requires_explicit_embedding_dim_when_switching_remote_backend(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "\n".join(
            [
                "MCP_API_KEY=",
                "MCP_API_KEY_ALLOW_INSECURE_LOCAL=false",
                "RETRIEVAL_EMBEDDING_BACKEND=router",
                "RETRIEVAL_EMBEDDING_DIM=2048",
                "RETRIEVAL_RERANKER_ENABLED=false",
                "WRITE_GUARD_LLM_ENABLED=false",
                "INTENT_LLM_ENABLED=false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"
    target_env.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    payload = {
        "dashboard_api_key": "openai-secret",
        "allow_insecure_local": False,
        "embedding_backend": "openai",
        "embedding_api_base": "https://api.openai.com/v1",
        "embedding_api_key": "sk-test",
        "embedding_model": "text-embedding-3-large",
    }

    with _build_client() as client:
        response = client.post("/setup/config", json=payload)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "setup_validation_failed"
    assert "embedding_dim" in detail["missing_fields"]
    written = target_env.read_text(encoding="utf-8")
    assert "RETRIEVAL_EMBEDDING_BACKEND=router" in written
    assert "RETRIEVAL_EMBEDDING_DIM=2048" in written


def test_setup_config_rejects_invalid_existing_remote_embedding_dim_without_explicit_override(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "\n".join(
            [
                "MCP_API_KEY=",
                "MCP_API_KEY_ALLOW_INSECURE_LOCAL=false",
                "RETRIEVAL_EMBEDDING_BACKEND=router",
                "RETRIEVAL_EMBEDDING_DIM=invalid",
                "RETRIEVAL_RERANKER_ENABLED=false",
                "WRITE_GUARD_LLM_ENABLED=false",
                "INTENT_LLM_ENABLED=false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"
    target_env.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    payload = {
        "dashboard_api_key": "openai-secret",
        "allow_insecure_local": False,
        "embedding_backend": "openai",
        "embedding_api_base": "https://api.openai.com/v1",
        "embedding_api_key": "sk-test",
        "embedding_model": "text-embedding-3-large",
    }

    with _build_client() as client:
        response = client.post("/setup/config", json=payload)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "setup_validation_failed"
    assert "embedding_dim" in detail["missing_fields"]


def test_setup_config_accepts_real_local_router_endpoint_with_real_models(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "MCP_API_KEY=\nRETRIEVAL_EMBEDDING_BACKEND=hash\nRETRIEVAL_EMBEDDING_DIM=64\n",
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"
    target_env.write_text(
        "MCP_API_KEY=router-secret\nRETRIEVAL_EMBEDDING_BACKEND=hash\nRETRIEVAL_EMBEDDING_DIM=64\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("MCP_API_KEY", "router-secret")
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.post(
            "/setup/config",
            headers={"X-MCP-API-Key": "router-secret"},
            json={
                "dashboard_api_key": "   ",
                "allow_insecure_local": False,
                "embedding_backend": "router",
                "embedding_dim": 1024,
                "reranker_enabled": True,
                "router_api_base": "http://127.0.0.1:8001/v1",
                "router_embedding_model": "local-router-embed",
                "router_reranker_model": "local-router-rerank",
            },
        )

    assert response.status_code == 200
    written = target_env.read_text(encoding="utf-8")
    assert "ROUTER_API_BASE=http://127.0.0.1:8001/v1" in written
    assert "ROUTER_EMBEDDING_MODEL=local-router-embed" in written
    assert "ROUTER_RERANKER_MODEL=local-router-rerank" in written


def test_setup_config_rejects_link_local_provider_url_targets(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "MCP_API_KEY=\nRETRIEVAL_EMBEDDING_BACKEND=hash\nRETRIEVAL_EMBEDDING_DIM=64\n",
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.post(
            "/setup/config",
            json={
                "dashboard_api_key": "local-secret",
                "allow_insecure_local": False,
                "embedding_backend": "api",
                "embedding_api_base": "http://169.254.169.254/v1",
                "embedding_model": "local-embedding-model",
                "embedding_dim": 1024,
            },
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "setup_validation_failed"
    assert detail["reason"] == "invalid_api_base_url"
    assert detail["field"] == "embedding_api_base"
    assert not target_env.exists()


def test_setup_config_normalizes_provider_suffixes_before_writing(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "MCP_API_KEY=\nRETRIEVAL_EMBEDDING_BACKEND=hash\nRETRIEVAL_EMBEDDING_DIM=64\n",
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"
    target_env.write_text(
        "MCP_API_KEY=local-secret\nRETRIEVAL_EMBEDDING_BACKEND=hash\nRETRIEVAL_EMBEDDING_DIM=64\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("MCP_API_KEY", "local-secret")
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.post(
            "/setup/config",
            headers={"X-MCP-API-Key": "local-secret"},
            json={
                "dashboard_api_key": "   ",
                "allow_insecure_local": False,
                "embedding_backend": "api",
                "embedding_api_base": "http://127.0.0.1:9100/v1/embeddings/",
                "embedding_model": "local-embedding-model",
                "embedding_dim": 1024,
                "reranker_enabled": True,
                "reranker_api_base": "http://127.0.0.1:9200/v1/rerank",
                "reranker_model": "local-reranker-model",
            },
        )

    assert response.status_code == 200
    written = target_env.read_text(encoding="utf-8")
    assert "RETRIEVAL_EMBEDDING_API_BASE=http://127.0.0.1:9100/v1" in written
    assert "RETRIEVAL_RERANKER_API_BASE=http://127.0.0.1:9200/v1" in written


def test_setup_config_rejects_private_literal_provider_base_without_allowlist(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "MCP_API_KEY=\nRETRIEVAL_EMBEDDING_BACKEND=hash\nRETRIEVAL_EMBEDDING_DIM=64\n",
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.post(
            "/setup/config",
            json={
                "dashboard_api_key": "local-secret",
                "allow_insecure_local": False,
                "embedding_backend": "api",
                "embedding_api_base": "http://10.0.0.8:11435/v1",
                "embedding_model": "local-embedding-model",
                "embedding_dim": 1024,
            },
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "setup_validation_failed"
    assert detail["reason"] == "invalid_api_base_url"
    assert detail["field"] == "embedding_api_base"
    assert not target_env.exists()


def test_setup_config_allows_private_literal_provider_base_with_allowlist(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "MCP_API_KEY=\nRETRIEVAL_EMBEDDING_BACKEND=hash\nRETRIEVAL_EMBEDDING_DIM=64\n",
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"
    target_env.write_text(
        "MCP_API_KEY=local-secret\nRETRIEVAL_EMBEDDING_BACKEND=hash\nRETRIEVAL_EMBEDDING_DIM=64\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("MCP_API_KEY", "local-secret")
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setenv("MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS", "10.0.0.0/8")
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.post(
            "/setup/config",
            headers={"X-MCP-API-Key": "local-secret"},
            json={
                "dashboard_api_key": "   ",
                "allow_insecure_local": False,
                "embedding_backend": "api",
                "embedding_api_base": "http://10.0.0.8:11435/v1",
                "embedding_model": "local-embedding-model",
                "embedding_dim": 1024,
            },
        )

    assert response.status_code == 200
    written = target_env.read_text(encoding="utf-8")
    assert "RETRIEVAL_EMBEDDING_API_BASE=http://10.0.0.8:11435/v1" in written


def test_setup_config_rejects_example_router_model_ids(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "MCP_API_KEY=\nRETRIEVAL_EMBEDDING_BACKEND=hash\nRETRIEVAL_EMBEDDING_DIM=64\n",
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.post(
            "/setup/config",
            json={
                "dashboard_api_key": "router-secret",
                "allow_insecure_local": False,
                "embedding_backend": "router",
                "embedding_dim": 1024,
                "reranker_enabled": True,
                "router_api_base": "http://127.0.0.1:8001/v1",
                "router_embedding_model": "router-embedding-model",
                "router_reranker_model": "router-reranker-model",
            },
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "setup_validation_failed"
    assert "router_embedding_model" in detail["placeholder_fields"]
    assert "router_reranker_model" in detail["placeholder_fields"]


def test_setup_config_rejects_invalid_openai_embedding_dim_without_backend_literal_errors(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "MCP_API_KEY=\nRETRIEVAL_EMBEDDING_BACKEND=hash\nRETRIEVAL_EMBEDDING_DIM=64\n",
        encoding="utf-8",
    )
    target_env = tmp_path / ".env"

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.post(
            "/setup/config",
            json={
                "dashboard_api_key": "openai-secret",
                "allow_insecure_local": False,
                "embedding_backend": "openai",
                "embedding_api_base": "https://api.openai.com/v1",
                "embedding_model": "text-embedding-3-large",
                "embedding_dim": 0,
            },
        )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert [tuple(item["loc"]) for item in detail] == [("body", "embedding_dim")]


def test_setup_config_rejects_when_running_in_docker(monkeypatch, tmp_path: Path) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text("MCP_API_KEY=\n", encoding="utf-8")
    target_env = tmp_path / ".env"

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.setenv("MEMORY_PALACE_RUNNING_IN_DOCKER", "true")
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.post(
            "/setup/config",
            json={
                "dashboard_api_key": "local-secret",
                "allow_insecure_local": False,
                "embedding_backend": "hash",
            },
        )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "setup_apply_unsupported"
    assert detail["reason"] == "docker_runtime_not_persisted"


def test_setup_config_rejects_remote_write_even_with_valid_api_key(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text("MCP_API_KEY=\n", encoding="utf-8")
    target_env = tmp_path / ".env"

    monkeypatch.setenv("MCP_API_KEY", "setup-secret")
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client(client=("203.0.113.10", 50000)) as client:
        response = client.post(
            "/setup/config",
            headers={"X-MCP-API-Key": "setup-secret"},
            json={
                "dashboard_api_key": "remote-secret",
                "allow_insecure_local": False,
                "embedding_backend": "hash",
            },
        )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["error"] == "setup_access_denied"
    assert detail["reason"] == "local_loopback_required_for_write"


def test_setup_config_rejects_loopback_write_without_api_key_when_configured(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text("MCP_API_KEY=\nRETRIEVAL_EMBEDDING_BACKEND=hash\n", encoding="utf-8")
    target_env = tmp_path / ".env"

    monkeypatch.setenv("MCP_API_KEY", "setup-secret")
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.post(
            "/setup/config",
            json={
                "dashboard_api_key": "local-secret",
                "allow_insecure_local": False,
                "embedding_backend": "hash",
            },
        )

    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["error"] == "setup_access_denied"
    assert detail["reason"] == "invalid_or_missing_api_key"
    assert not target_env.exists()


def test_setup_config_requires_dashboard_api_key_for_first_local_save(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text("MCP_API_KEY=\nRETRIEVAL_EMBEDDING_BACKEND=hash\n", encoding="utf-8")
    target_env = tmp_path / ".env"

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client() as client:
        response = client.post(
            "/setup/config",
            json={
                "dashboard_api_key": "   ",
                "allow_insecure_local": False,
                "embedding_backend": "hash",
            },
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "setup_validation_failed"
    assert "dashboard_api_key" in detail["missing_fields"]
    assert not target_env.exists()


def test_setup_config_rejects_loopback_peer_when_host_header_is_not_loopback(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text("MCP_API_KEY=\n", encoding="utf-8")
    target_env = tmp_path / ".env"

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client(client=("127.0.0.1", 50000)) as client:
        response = client.post(
            "/setup/config",
            headers={"Host": "memory-palace.example"},
            json={
                "dashboard_api_key": "proxy-bypass",
                "allow_insecure_local": False,
                "embedding_backend": "hash",
            },
        )

    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["error"] == "setup_access_denied"
    assert detail["reason"] == "local_loopback_or_api_key_required"
    assert not target_env.exists()


def test_setup_config_allows_ipv6_loopback_write_without_api_key(
    monkeypatch, tmp_path: Path
) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text("MCP_API_KEY=\nRETRIEVAL_EMBEDDING_BACKEND=hash\n", encoding="utf-8")
    target_env = tmp_path / ".env"

    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setattr(setup_api, "_ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("MEMORY_PALACE_SETUP_ENV_FILE", str(target_env))

    with _build_client(client=("::1", 50000)) as client:
        response = client.post(
            "/setup/config",
            headers={"Host": "[::1]:8000"},
            json={
                "dashboard_api_key": "ipv6-secret",
                "allow_insecure_local": False,
                "embedding_backend": "hash",
            },
        )

    assert response.status_code == 200
    assert "MCP_API_KEY=ipv6-secret" in target_env.read_text(encoding="utf-8")
