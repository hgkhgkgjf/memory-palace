from pathlib import Path
import os
import shutil
import subprocess

import pytest
import run_sse
from starlette.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _frontend_entrypoint_shell() -> list[str]:
    candidates = [
        shutil.which("sh"),
        r"C:\Program Files\Git\bin\sh.exe",
        r"C:\Program Files\Git\usr\bin\sh.exe",
        shutil.which("bash"),
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.is_file():
            continue
        return [str(path)]

    pytest.skip("No POSIX shell is available to execute frontend-entrypoint.sh")


def _run_frontend_entrypoint(script_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_frontend_entrypoint_shell(), str(script_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


def test_sse_main_falls_back_to_8010_when_loopback_8000_is_busy(monkeypatch) -> None:
    call_order = []

    def _fake_create_sse_app(**kwargs):
        call_order.append(("create_sse_app", kwargs))
        return {"app": "fake"}

    def _fake_run_uvicorn_sse_app(app, *, host, port, transport):
        call_order.append(("uvicorn", host, port, app, transport))

    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setattr(run_sse, "create_sse_app", _fake_create_sse_app)
    monkeypatch.setattr(run_sse, "_create_sse_transport", lambda: "transport")
    monkeypatch.setattr(run_sse, "_run_uvicorn_sse_app", _fake_run_uvicorn_sse_app)
    monkeypatch.setattr(run_sse, "_is_loopback_port_available", lambda port: port != 8000)

    run_sse.main()

    assert call_order[0] == (
        "create_sse_app",
        {"initialize_runtime_on_startup": True, "transport": "transport"},
    )
    assert call_order[1][0] == "uvicorn"
    assert call_order[1][1] == "127.0.0.1"
    assert call_order[1][2] == 8010


def test_sse_app_lifespan_initializes_runtime_when_enabled(monkeypatch) -> None:
    call_order = []

    async def _fake_initialize_runtime(*, ensure_runtime_started: bool = True) -> None:
        call_order.append(("startup", ensure_runtime_started))

    async def _fake_drain_pending_flush_summaries(*, reason: str) -> None:
        call_order.append(("drain", reason))

    async def _fake_shutdown() -> None:
        call_order.append(("shutdown", "runtime"))

    async def _fake_close_sqlite_client() -> None:
        call_order.append(("shutdown", "db"))

    monkeypatch.setattr(run_sse, "initialize_backend_runtime", _fake_initialize_runtime)
    monkeypatch.setattr(run_sse, "drain_pending_flush_summaries", _fake_drain_pending_flush_summaries)
    monkeypatch.setattr(run_sse.runtime_state, "shutdown", _fake_shutdown)
    monkeypatch.setattr(run_sse, "close_sqlite_client", _fake_close_sqlite_client)

    app = run_sse.create_sse_app(initialize_runtime_on_startup=True)

    with TestClient(app):
        assert call_order[0] == ("startup", True)

    assert ("drain", "runtime.shutdown") in call_order
    assert ("shutdown", "runtime") in call_order
    assert ("shutdown", "db") in call_order


def test_compose_pins_sse_internal_port_to_proxy_contract() -> None:
    compose_text = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    backend_block = compose_text.split("\n  backend:\n", 1)[1].split("\n  frontend:\n", 1)[0]
    frontend_block = compose_text.split("\n  frontend:\n", 1)[1]

    assert "\n  sse:\n" not in compose_text
    assert "HOST: 0.0.0.0" in backend_block
    assert "RUNTIME_WRITE_WAL_ENABLED: ${MEMORY_PALACE_DOCKER_WAL_ENABLED:-true}" in backend_block
    assert "backend:\n        condition: service_healthy" in frontend_block


def test_pull_based_ghcr_compose_matches_backend_frontend_proxy_topology() -> None:
    compose_text = (PROJECT_ROOT / "docker-compose.ghcr.yml").read_text(encoding="utf-8")
    backend_block = compose_text.split("\n  backend:\n", 1)[1].split("\n  frontend:\n", 1)[0]
    frontend_block = compose_text.split("\n  frontend:\n", 1)[1]

    assert "\n  sse:\n" not in compose_text
    assert 'python", "/usr/local/bin/backend-healthcheck.py' in backend_block
    assert "RUNTIME_WRITE_WAL_ENABLED: ${MEMORY_PALACE_DOCKER_WAL_ENABLED:-true}" in backend_block
    assert "backend:\n        condition: service_healthy" in frontend_block


def test_frontend_nginx_template_targets_repo_managed_sse_port() -> None:
    template_text = (
        PROJECT_ROOT / "deploy" / "docker" / "nginx.conf.template"
    ).read_text(encoding="utf-8")
    sse_block = template_text.split("location = /sse {", 1)[1].split(
        "location = /sse/ {", 1
    )[0]
    messages_block = template_text.split("location ^~ /messages {", 1)[1].split(
        "location ^~ /sse/messages {", 1
    )[0]
    sse_messages_block = template_text.split(
        "location ^~ /sse/messages {", 1
    )[1].split("location = /index.html {", 1)[0]

    assert "proxy_pass http://backend:8000/sse/;" in template_text
    assert "connect-src ${FRONTEND_CSP_CONNECT_SRC_NGINX_ESCAPED};" in template_text
    assert "location ^~ /messages {" in template_text
    assert "location ^~ /sse/messages {" in template_text
    assert "location = /sse/ {" in template_text
    assert "return 307 /sse;" in template_text
    assert 'proxy_set_header Connection "";' in sse_block
    assert 'proxy_set_header Connection "";' in messages_block
    assert 'proxy_set_header Connection "";' in sse_messages_block


def test_frontend_nginx_template_only_injects_api_key_for_protected_api_routes() -> None:
    template_text = (
        PROJECT_ROOT / "deploy" / "docker" / "nginx.conf.template"
    ).read_text(encoding="utf-8")

    for path in (
        "location ^~ /api/maintenance/ {",
        "location ^~ /api/review/ {",
        "location ^~ /api/browse/ {",
        "location ^~ /api/setup/ {",
        "location ^~ /api/layering/ {",
        "location ^~ /api/forgetting/ {",
        "location = /api/search/quality-metrics {",
    ):
        assert path in template_text

    assert "proxy_pass http://backend:8000/api/layering/;" in template_text
    assert "proxy_pass http://backend:8000/api/forgetting/;" in template_text
    assert "proxy_pass http://backend:8000/search/quality-metrics;" in template_text

    public_api_block = template_text.split("location /api/ {", 1)[1].split("}", 1)[0]
    assert "proxy_pass http://backend:8000/;" in public_api_block
    assert "X-MCP-API-Key" not in public_api_block


def test_backend_entrypoint_requires_gosu_before_privilege_drop() -> None:
    script_text = (
        PROJECT_ROOT / "deploy" / "docker" / "backend-entrypoint.sh"
    ).read_text(encoding="utf-8")

    assert "command -v gosu >/dev/null 2>&1" in script_text
    assert "backend-entrypoint: gosu is required when running as root" in script_text


def test_frontend_static_nginx_reference_is_removed() -> None:
    assert not (PROJECT_ROOT / "deploy" / "docker" / "nginx.conf").exists()


def test_frontend_entrypoint_escapes_dollar_signs_in_api_key() -> None:
    script_text = (
        PROJECT_ROOT / "deploy" / "docker" / "frontend-entrypoint.sh"
    ).read_text(encoding="utf-8")

    assert "sed 's/[\\\\\\\"$]/\\\\&/g'" in script_text
    assert "FRONTEND_CSP_CONNECT_SRC" in script_text
    assert "carriage_return=\"$(printf '\\r')\"" in script_text
    assert "backtick=\"$(printf '\\140')\"" in script_text
    assert "tr -d '[:cntrl:]'" in script_text
    assert "MCP_API_KEY contains unsupported control characters." in script_text
    assert "FRONTEND_CSP_CONNECT_SRC contains unsupported characters." in script_text
    assert "FRONTEND_CSP_CONNECT_SRC_NGINX_ESCAPED" in script_text


def test_frontend_entrypoint_rejects_tab_in_api_key() -> None:
    script_path = PROJECT_ROOT / "deploy" / "docker" / "frontend-entrypoint.sh"
    env = os.environ.copy()
    env["MCP_API_KEY"] = "local\tkey"

    result = _run_frontend_entrypoint(script_path, env)

    assert result.returncode == 1
    assert "unsupported control characters" in result.stderr


def test_frontend_entrypoint_rejects_backtick_in_api_key() -> None:
    script_path = PROJECT_ROOT / "deploy" / "docker" / "frontend-entrypoint.sh"
    env = os.environ.copy()
    env["MCP_API_KEY"] = "local`key"

    result = _run_frontend_entrypoint(script_path, env)

    assert result.returncode == 1
    assert "unsupported control characters" in result.stderr


def test_frontend_entrypoint_accepts_default_connect_src_and_renders_template(
    tmp_path: Path,
) -> None:
    script_source = (
        PROJECT_ROOT / "deploy" / "docker" / "frontend-entrypoint.sh"
    ).read_text(encoding="utf-8")
    template_path = tmp_path / "default.conf.template"
    target_path = tmp_path / "default.conf"
    template_path.write_text(
        'add_header Content-Security-Policy "connect-src ${FRONTEND_CSP_CONNECT_SRC_NGINX_ESCAPED};";\n',
        encoding="utf-8",
    )

    script_path = tmp_path / "frontend-entrypoint.sh"
    script_path.write_text(
        script_source
        .replace(
            'template_path="/etc/nginx/templates/default.conf.template"',
            f'template_path="{template_path}"',
        )
        .replace(
            'target_path="/etc/nginx/conf.d/default.conf"',
            f'target_path="{target_path}"',
        )
        .replace("nginx -t", ":")
        .replace("exec nginx -g 'daemon off;'", "exit 0"),
        encoding="utf-8",
    )
    script_path.chmod(0o755)

    env = os.environ.copy()
    env["MCP_API_KEY"] = "local-key"

    result = _run_frontend_entrypoint(script_path, env)

    assert result.returncode == 0, result.stderr
    assert "connect-src 'self';" in target_path.read_text(encoding="utf-8")


def test_frontend_entrypoint_rejects_semicolon_in_connect_src() -> None:
    script_path = PROJECT_ROOT / "deploy" / "docker" / "frontend-entrypoint.sh"
    env = os.environ.copy()
    env["MCP_API_KEY"] = "local-key"
    env["FRONTEND_CSP_CONNECT_SRC"] = "'self'; script-src https://evil.example"

    result = _run_frontend_entrypoint(script_path, env)

    assert result.returncode == 1
    assert "FRONTEND_CSP_CONNECT_SRC contains unsupported characters." in result.stderr
