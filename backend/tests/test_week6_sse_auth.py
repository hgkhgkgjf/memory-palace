import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from pathlib import Path
import http.client
import os
import pytest
import signal
import socket
import subprocess
import sys
import time
from uuid import uuid4

import run_sse
from run_sse import (
    apply_mcp_api_key_middleware,
    create_embedded_sse_apps,
    create_sse_app,
)
from starlette.requests import Request


_WINDOWS_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def _build_client(*, client=("testclient", 50000)) -> TestClient:
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    wrapped_app = apply_mcp_api_key_middleware(app)
    return TestClient(wrapped_app, client=client)


def _spawn_run_sse_subprocess(*, backend_dir: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    kwargs: dict[str, object] = {
        "cwd": str(backend_dir),
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = _WINDOWS_NEW_PROCESS_GROUP
    return subprocess.Popen([sys.executable, "run_sse.py"], **kwargs)


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def _request_graceful_shutdown(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
        if ctrl_break is not None:
            process.send_signal(ctrl_break)
            return
        process.terminate()
    else:
        process.send_signal(signal.SIGINT)


def test_sse_auth_rejects_when_api_key_not_configured_by_default(monkeypatch) -> None:
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", raising=False)
    with _build_client() as client:
        response = client.get("/ping")
    assert response.status_code == 401
    payload = response.json()
    assert payload.get("error") == "mcp_sse_auth_failed"
    assert payload.get("reason") == "api_key_not_configured"


@pytest.mark.parametrize("override_value", ["true", "enabled"])
def test_sse_auth_allows_when_explicit_insecure_local_override_is_enabled(
    monkeypatch, override_value: str
) -> None:
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.setenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", override_value)
    with _build_client(client=("127.0.0.1", 50000)) as client:
        response = client.get("/ping", headers={"Host": "127.0.0.1"})
    assert response.status_code == 200
    assert response.json().get("ok") is True


def test_sse_auth_rejects_insecure_local_override_for_non_loopback_client(monkeypatch) -> None:
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.setenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", "true")
    with _build_client(client=("203.0.113.10", 50000)) as client:
        response = client.get("/ping")
    assert response.status_code == 401
    payload = response.json()
    assert payload.get("error") == "mcp_sse_auth_failed"
    assert payload.get("reason") == "insecure_local_override_requires_loopback"


def test_sse_auth_rejects_insecure_local_override_when_forwarded_headers_present(monkeypatch) -> None:
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.setenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", "true")
    headers = {"X-Forwarded-For": "198.51.100.8"}
    with _build_client(client=("127.0.0.1", 50000)) as client:
        response = client.get("/ping", headers=headers)
    assert response.status_code == 401
    payload = response.json()
    assert payload.get("error") == "mcp_sse_auth_failed"
    assert payload.get("reason") == "insecure_local_override_requires_loopback"


def test_sse_auth_rejects_insecure_local_override_when_host_is_not_loopback(monkeypatch) -> None:
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.setenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", "true")
    with _build_client(client=("127.0.0.1", 50000)) as client:
        response = client.get(
            "/ping",
            headers={"Host": "memory-palace.example"},
        )
    assert response.status_code == 401
    payload = response.json()
    assert payload.get("error") == "mcp_sse_auth_failed"
    assert payload.get("reason") == "insecure_local_override_requires_loopback"


def test_sse_auth_allows_ipv6_loopback_host_header_for_insecure_local_override(
    monkeypatch,
) -> None:
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.setenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", "true")
    with _build_client(client=("::1", 50000)) as client:
        response = client.get(
            "/ping",
            headers={"Host": "[::1]:8000"},
        )
    assert response.status_code == 200
    assert response.json().get("ok") is True


def test_sse_auth_rejects_when_api_key_missing(monkeypatch) -> None:
    monkeypatch.setenv("MCP_API_KEY", "week6-sse-secret")
    with _build_client() as client:
        response = client.get("/ping")
    assert response.status_code == 401
    payload = response.json()
    assert payload.get("error") == "mcp_sse_auth_failed"
    assert payload.get("reason") == "invalid_or_missing_api_key"


def test_sse_auth_accepts_x_mcp_api_key_header(monkeypatch) -> None:
    monkeypatch.setenv("MCP_API_KEY", "week6-sse-secret")
    headers = {"X-MCP-API-Key": "week6-sse-secret"}
    with _build_client() as client:
        response = client.get("/ping", headers=headers)
    assert response.status_code == 200
    assert response.json().get("ok") is True


def test_sse_auth_accepts_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv("MCP_API_KEY", "week6-sse-secret")
    headers = {"Authorization": "Bearer week6-sse-secret"}
    with _build_client() as client:
        response = client.get("/ping", headers=headers)
    assert response.status_code == 200
    assert response.json().get("ok") is True


def test_sse_rate_limit_ignores_forwarded_client_ip_from_private_peer_by_default(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SSE_TRUSTED_PROXY_HOSTS", raising=False)
    monkeypatch.delenv("SSE_TRUSTED_PROXY_CIDRS", raising=False)
    session_id = uuid4()
    key = run_sse.MemoryPalaceSseServerTransport._session_rate_limit_key(
        {
            "type": "http",
            "path": "/messages",
            "client": ("172.18.0.10", 50000),
            "headers": [
                (b"x-forwarded-for", b"198.51.100.8, 172.18.0.10"),
                (b"x-real-ip", b"198.51.100.8"),
            ],
        },
        session_id,
    )

    assert key == "172.18.0.10"


def test_sse_rate_limit_prefers_forwarded_client_ip_for_explicit_allowlisted_proxy(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SSE_TRUSTED_PROXY_CIDRS", "172.18.0.0/16")
    session_id = uuid4()
    key = run_sse.MemoryPalaceSseServerTransport._session_rate_limit_key(
        {
            "type": "http",
            "path": "/messages",
            "client": ("172.18.0.10", 50000),
            "headers": [
                (b"x-forwarded-for", b"198.51.100.8, 172.18.0.10"),
                (b"x-real-ip", b"198.51.100.8"),
            ],
        },
        session_id,
    )

    assert key == "198.51.100.8"


def test_sse_rate_limit_ignores_forwarded_client_ip_from_untrusted_peer() -> None:
    session_id = uuid4()
    key = run_sse.MemoryPalaceSseServerTransport._session_rate_limit_key(
        {
            "type": "http",
            "path": "/messages",
            "client": ("198.51.100.99", 50000),
            "headers": [
                (b"x-forwarded-for", b"203.0.113.8"),
                (b"x-real-ip", b"203.0.113.8"),
            ],
        },
        session_id,
    )

    assert key == "198.51.100.99"

@pytest.mark.anyio
async def test_read_request_body_with_limit_rejects_stream_without_content_length() -> None:
    messages = [
        {"type": "http.request", "body": b"a" * 40, "more_body": True},
        {"type": "http.request", "body": b"b" * 40, "more_body": False},
    ]

    async def receive():
        return messages.pop(0)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/messages",
            "headers": [],
        },
        receive,
    )

    body, too_large = await run_sse._read_request_body_with_limit(
        request, max_bytes=64
    )

    assert body is None
    assert too_large is True


def test_sse_auth_preserves_streaming_response(monkeypatch) -> None:
    monkeypatch.setenv("MCP_API_KEY", "week6-sse-secret")

    app = FastAPI()

    @app.get("/stream")
    async def stream():
        async def _events():
            yield "event: endpoint\n\n"
            yield "data: ok\n\n"

        return StreamingResponse(_events(), media_type="text/event-stream")

    wrapped_app = apply_mcp_api_key_middleware(app)
    with TestClient(wrapped_app) as client:
        with client.stream("GET", "/stream", headers={"X-MCP-API-Key": "week6-sse-secret"}) as response:
            assert response.status_code == 200
            lines = list(response.iter_lines())
    assert "event: endpoint" in lines
    assert "data: ok" in lines


def test_sse_health_endpoint_is_public(monkeypatch) -> None:
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", raising=False)

    with TestClient(create_sse_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "memory-palace-sse"}


def test_sse_health_endpoint_stays_public_when_api_key_is_configured(monkeypatch) -> None:
    monkeypatch.setenv("MCP_API_KEY", "week6-sse-secret")
    monkeypatch.delenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", raising=False)

    with TestClient(create_sse_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "memory-palace-sse"}


def test_create_sse_app_initializes_runtime_in_lifespan_when_enabled(
    monkeypatch,
) -> None:
    events: list[str] = []

    async def _fake_initialize_runtime() -> None:
        events.append("startup")

    async def _fake_drain_pending_flush_summaries(*_args, **_kwargs) -> None:
        events.append("drain")

    async def _fake_shutdown() -> None:
        events.append("shutdown")

    async def _fake_close_sqlite_client() -> None:
        events.append("close")

    monkeypatch.setattr(run_sse, "initialize_backend_runtime", _fake_initialize_runtime)
    monkeypatch.setattr(
        run_sse, "drain_pending_flush_summaries", _fake_drain_pending_flush_summaries
    )
    monkeypatch.setattr(run_sse.runtime_state, "shutdown", _fake_shutdown)
    monkeypatch.setattr(run_sse, "close_sqlite_client", _fake_close_sqlite_client)

    with TestClient(create_sse_app(initialize_runtime_on_startup=True)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "memory-palace-sse"}
    assert events == ["startup", "drain", "shutdown", "close"]


@pytest.mark.parametrize(
    ("path", "headers", "expected_status", "expected_text"),
    [
        (
            "/messages",
            {
                "X-MCP-API-Key": "week6-sse-secret",
                "Content-Type": "text/plain",
                "Origin": "http://127.0.0.1:5173",
                "Host": "127.0.0.1:8000",
            },
            400,
            "Invalid Content-Type header",
        ),
        (
            "/messages",
            {
                "X-MCP-API-Key": "week6-sse-secret",
                "Content-Type": "application/json",
                "Origin": "https://evil.example",
                "Host": "127.0.0.1:8000",
            },
            403,
            "Invalid Origin header",
        ),
        (
            "/messages",
            {
                "X-MCP-API-Key": "week6-sse-secret",
                "Content-Type": "application/json",
                "Origin": "http://127.0.0.1:5173",
                "Host": "127.0.0.1:8000",
            },
            400,
            "session_id is required",
        ),
        (
            "/sse/messages/",
            {
                "X-MCP-API-Key": "week6-sse-secret",
                "Content-Type": "application/json",
                "Origin": "http://127.0.0.1:5173",
                "Host": "127.0.0.1:8000",
            },
            400,
            "session_id is required",
        ),
    ],
)
def test_embedded_sse_message_mounts_enforce_transport_security_before_session_lookup(
    monkeypatch, path: str, headers: dict[str, str], expected_status: int, expected_text: str
) -> None:
    monkeypatch.setenv("MCP_API_KEY", "week6-sse-secret")
    monkeypatch.delenv("MCP_API_KEY_ALLOW_INSECURE_LOCAL", raising=False)
    stream_app, message_app = create_embedded_sse_apps()
    app = FastAPI()
    app.mount("/sse/messages", message_app)
    app.mount("/messages", message_app)
    app.mount("/sse", stream_app)

    with TestClient(app) as client:
        response = client.post(path, headers=headers)

    assert response.status_code == expected_status
    assert response.text == expected_text


def test_sse_auth_does_not_raise_on_streaming_disconnect(tmp_path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    env = dict(**os.environ)
    env["MCP_API_KEY"] = "week6-sse-secret"
    env["DATABASE_URL"] = _sqlite_url(tmp_path / "streaming_disconnect.db")
    env["HOST"] = "127.0.0.1"
    env["PORT"] = str(port)
    server = _spawn_run_sse_subprocess(backend_dir=backend_dir, env=env)

    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            if server.poll() is not None:
                pytest.fail("uvicorn exited before the streaming test could connect")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("timed out waiting for streaming test server to start")

        request = (
            "GET /sse HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Accept: text/event-stream\r\n"
            "X-MCP-API-Key: week6-sse-secret\r\n"
            "Connection: keep-alive\r\n"
            "\r\n"
        ).encode("utf-8")

        with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
            client.sendall(request)
            chunks = []
            deadline = time.time() + 5
            while time.time() < deadline:
                chunk = client.recv(4096).decode("utf-8", errors="ignore")
                if not chunk:
                    break
                chunks.append(chunk)
                if "event: endpoint" in "".join(chunks):
                    break
            received = "".join(chunks)
            assert "200 OK" in received
            assert "id: " in received
            assert "event: endpoint" in received

        time.sleep(0.5)
    finally:
        server.terminate()
        try:
            output, _ = server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            output, _ = server.communicate(timeout=5)

    assert "AssertionError: Unexpected message" not in output


def test_sse_auth_does_not_raise_on_streaming_shutdown(tmp_path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    env = dict(**os.environ)
    env["MCP_API_KEY"] = "week6-sse-secret"
    env["DATABASE_URL"] = _sqlite_url(tmp_path / "streaming_shutdown.db")
    env["HOST"] = "127.0.0.1"
    env["PORT"] = str(port)
    server = _spawn_run_sse_subprocess(backend_dir=backend_dir, env=env)

    client = None
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            if server.poll() is not None:
                pytest.fail("uvicorn exited before the shutdown test could connect")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("timed out waiting for shutdown test server to start")

        request = (
            "GET /sse HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Accept: text/event-stream\r\n"
            "X-MCP-API-Key: week6-sse-secret\r\n"
            "\r\n"
        ).encode("utf-8")

        client = socket.create_connection(("127.0.0.1", port), timeout=5)
        client.sendall(request)
        received = ""
        deadline = time.time() + 5
        while time.time() < deadline:
            chunk = client.recv(4096).decode("utf-8", errors="ignore")
            if not chunk:
                break
            received += chunk
            if "event: endpoint" in received:
                break
        assert "200 OK" in received
        assert "id: " in received
        assert "event: endpoint" in received

        _request_graceful_shutdown(server)
        if client is not None:
            client.close()
            client = None
        output, _ = server.communicate(timeout=10)
    finally:
        if client is not None:
            client.close()
        if server.poll() is None:
            server.terminate()
            try:
                output, _ = server.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                output, _ = server.communicate(timeout=5)

    assert "Expected ASGI message 'http.response.body'" not in output
    assert "RuntimeError:" not in output


def test_sse_insecure_local_does_not_raise_on_streaming_shutdown(tmp_path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    env = dict(**os.environ)
    env.pop("MCP_API_KEY", None)
    env["MCP_API_KEY_ALLOW_INSECURE_LOCAL"] = "true"
    env["DATABASE_URL"] = _sqlite_url(tmp_path / "streaming_shutdown_insecure_local.db")
    env["HOST"] = "127.0.0.1"
    env["PORT"] = str(port)
    server = _spawn_run_sse_subprocess(backend_dir=backend_dir, env=env)

    client = None
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            if server.poll() is not None:
                pytest.fail(
                    "uvicorn exited before the insecure-local shutdown test could connect"
                )
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail(
                "timed out waiting for insecure-local shutdown test server to start"
            )

        request = (
            "GET /sse HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Accept: text/event-stream\r\n"
            "\r\n"
        ).encode("utf-8")

        client = socket.create_connection(("127.0.0.1", port), timeout=5)
        client.sendall(request)
        received = ""
        deadline = time.time() + 5
        while time.time() < deadline:
            chunk = client.recv(4096).decode("utf-8", errors="ignore")
            if not chunk:
                break
            received += chunk
            if "event: endpoint" in received:
                break
        assert "200 OK" in received
        assert "id: " in received
        assert "event: endpoint" in received

        _request_graceful_shutdown(server)
        if client is not None:
            client.close()
            client = None
        output, _ = server.communicate(timeout=10)
    finally:
        if client is not None:
            client.close()
        if server.poll() is None:
            server.terminate()
            try:
                output, _ = server.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                output, _ = server.communicate(timeout=5)

    assert "Expected ASGI message 'http.response.body'" not in output
    assert "RuntimeError:" not in output


def test_sse_auth_rejects_when_posting_to_closed_message_stream(tmp_path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    env = dict(**os.environ)
    env["MCP_API_KEY"] = "week6-sse-secret"
    env["DATABASE_URL"] = _sqlite_url(tmp_path / "closed_message_stream.db")
    env["HOST"] = "127.0.0.1"
    env["PORT"] = str(port)
    server = _spawn_run_sse_subprocess(backend_dir=backend_dir, env=env)

    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            if server.poll() is not None:
                pytest.fail("uvicorn exited before the closed-stream test could connect")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("timed out waiting for closed-stream test server to start")

        session_id = None
        request = (
            "GET /sse HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Accept: text/event-stream\r\n"
            "X-MCP-API-Key: week6-sse-secret\r\n"
            "Connection: keep-alive\r\n"
            "\r\n"
        ).encode("utf-8")
        with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
            client.sendall(request)
            received = ""
            deadline = time.time() + 5
            while time.time() < deadline:
                chunk = client.recv(4096).decode("utf-8", errors="ignore")
                if not chunk:
                    break
                received += chunk
                if "session_id=" in received:
                    session_id = received.split("session_id=", 1)[1].splitlines()[0].strip()
                    break
        assert session_id

        time.sleep(0.2)

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request(
                "POST",
                f"/messages/?session_id={session_id}",
                body='{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}',
                headers={
                    "Content-Type": "application/json",
                    "X-MCP-API-Key": "week6-sse-secret",
                },
            )
            response = connection.getresponse()
            response.read()
        finally:
            connection.close()

        assert response.status in {404, 410}

        time.sleep(0.5)
    finally:
        server.terminate()
        try:
            output, _ = server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            output, _ = server.communicate(timeout=5)

    assert "ClosedResourceError" not in output
    assert "Traceback" not in output


@pytest.mark.anyio
async def test_sse_messages_rate_limit_returns_429(monkeypatch) -> None:
    monkeypatch.setenv("SSE_MESSAGE_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("SSE_MESSAGE_RATE_LIMIT_MAX_REQUESTS", "10")

    transport = run_sse.MemoryPalaceSseServerTransport("/messages", security_settings=None)
    session_id = uuid4()
    scope = {
        "type": "http",
        "path": "/messages",
        "client": ("127.0.0.1", 50000),
    }

    for _ in range(10):
        retry_after = await transport._check_message_rate_limit(
            scope=scope,
            session_id=session_id,
        )
        assert retry_after is None

    retry_after = await transport._check_message_rate_limit(
        scope=scope,
        session_id=session_id,
    )

    assert isinstance(retry_after, int)
    assert retry_after >= 1


@pytest.mark.anyio
async def test_sse_messages_rate_limit_persists_across_session_rotation(monkeypatch) -> None:
    transport = run_sse.MemoryPalaceSseServerTransport("/messages", security_settings=None)
    transport._message_rate_limit_window_seconds = 60
    transport._message_rate_limit_max_requests = 2
    scope = {
        "type": "http",
        "path": "/messages",
        "client": ("127.0.0.1", 50000),
    }

    first_session_id = uuid4()
    second_session_id = uuid4()

    assert await transport._check_message_rate_limit(scope=scope, session_id=first_session_id) is None
    assert await transport._check_message_rate_limit(scope=scope, session_id=first_session_id) is None

    retry_after = await transport._check_message_rate_limit(
        scope=scope,
        session_id=second_session_id,
    )

    assert isinstance(retry_after, int)
    assert retry_after >= 1


def test_sse_messages_reject_oversized_body_with_413(tmp_path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    env = dict(**os.environ)
    env["MCP_API_KEY"] = "week6-sse-secret"
    env["DATABASE_URL"] = _sqlite_url(tmp_path / "oversized_message.db")
    env["HOST"] = "127.0.0.1"
    env["PORT"] = str(port)
    env["SSE_MESSAGE_MAX_BODY_BYTES"] = "1024"
    server = _spawn_run_sse_subprocess(backend_dir=backend_dir, env=env)

    sse_socket = None
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            if server.poll() is not None:
                pytest.fail("uvicorn exited before the oversized-message test could connect")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("timed out waiting for oversized-message test server to start")

        session_id = None
        request = (
            "GET /sse HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Accept: text/event-stream\r\n"
            "X-MCP-API-Key: week6-sse-secret\r\n"
            "Connection: keep-alive\r\n"
            "\r\n"
        ).encode("utf-8")
        sse_socket = socket.create_connection(("127.0.0.1", port), timeout=5)
        sse_socket.sendall(request)
        sse_socket.settimeout(5)

        received = ""
        deadline = time.time() + 5
        while time.time() < deadline:
            chunk = sse_socket.recv(4096).decode("utf-8", errors="ignore")
            if not chunk:
                break
            received += chunk
            if "session_id=" in received:
                session_id = received.split("session_id=", 1)[1].splitlines()[0].strip()
                break
        assert session_id

        oversized_body = (
            '{"jsonrpc":"2.0","id":1,"method":"'
            + ("x" * 1200)
            + '","params":{}}'
        )

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request(
                "POST",
                f"/messages/?session_id={session_id}",
                body=oversized_body,
                headers={
                    "Content-Type": "application/json",
                    "X-MCP-API-Key": "week6-sse-secret",
                },
            )
            response = connection.getresponse()
            payload = response.read().decode("utf-8", errors="ignore")
        finally:
            connection.close()

        assert response.status == 413
        assert "Message body too large" in payload

        sse_socket.settimeout(1)
        trailing = ""
        try:
            while True:
                chunk = sse_socket.recv(4096).decode("utf-8", errors="ignore")
                if not chunk:
                    break
                trailing += chunk
        except socket.timeout:
            pass

        assert "Internal Server Error" not in trailing
        time.sleep(0.2)
    finally:
        if sse_socket is not None:
            try:
                sse_socket.close()
            except OSError:
                pass
        server.terminate()
        try:
            output, _ = server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            output, _ = server.communicate(timeout=5)

    assert "Traceback" not in output


@pytest.mark.anyio
async def test_sse_rate_limit_state_persists_when_session_closes() -> None:
    transport = run_sse.MemoryPalaceSseServerTransport("/messages", security_settings=None)
    transport._message_rate_limit_max_requests = 1
    first_session_id = uuid4()
    second_session_id = uuid4()
    scope = {
        "type": "http",
        "path": "/messages",
        "client": ("127.0.0.1", 50000),
    }

    retry_after = await transport._check_message_rate_limit(
        scope=scope, session_id=first_session_id
    )

    assert retry_after is None
    assert transport._message_rate_limit_buckets

    await transport._clear_message_rate_limit_state(
        scope=scope, session_id=first_session_id
    )

    retry_after = await transport._check_message_rate_limit(
        scope=scope, session_id=second_session_id
    )

    assert isinstance(retry_after, int)
    assert retry_after >= 1


@pytest.mark.anyio
async def test_sse_transport_uses_zero_buffer_memory_streams_for_backpressure(
    monkeypatch,
) -> None:
    buffer_sizes: list[int] = []

    class _FakeSendStream:
        async def send(self, _value) -> None:
            return None

        async def aclose(self) -> None:
            return None

    class _FakeReceiveStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def aclose(self) -> None:
            return None

    def _fake_create_memory_object_stream(max_buffer_size, *args, **kwargs):
        _ = args, kwargs
        buffer_sizes.append(int(max_buffer_size))
        return _FakeSendStream(), _FakeReceiveStream()

    class _FakeSecurity:
        async def validate_request(self, request, is_post=False):
            _ = request, is_post
            return None

    class _FakeTaskGroup:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

        def start_soon(self, func, *args):
            _ = func, args
            return None

    async def _receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _send(_message):
        return None

    monkeypatch.setattr(
        run_sse.anyio,
        "create_memory_object_stream",
        _fake_create_memory_object_stream,
    )
    monkeypatch.setattr(run_sse.anyio, "create_task_group", lambda: _FakeTaskGroup())

    transport = run_sse.MemoryPalaceSseServerTransport(
        "/messages", security_settings=None
    )
    monkeypatch.setattr(transport, "_security", _FakeSecurity())

    scope = {
        "type": "http",
        "path": "/sse",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 50000),
        "method": "GET",
        "scheme": "http",
        "query_string": b"",
        "server": ("127.0.0.1", 8000),
    }

    async with transport.connect_sse(scope, _receive, _send):
        pass

    assert buffer_sizes == [0, 0, 0]


@pytest.mark.anyio
async def test_sse_cancelled_run_propagates_after_transport_cleanup(monkeypatch) -> None:
    events: list[object] = []

    class _FakeServer:
        def create_initialization_options(self) -> dict[str, str]:
            events.append("init")
            return {"mode": "test"}

        async def run(self, read_stream, write_stream, options) -> None:
            events.append(("run", read_stream, write_stream, options))
            raise asyncio.CancelledError()

    class _FakeTransport:
        @asynccontextmanager
        async def connect_sse(self, scope, receive, send):
            events.append(("enter", scope["path"]))
            try:
                yield ("read-stream", "write-stream")
            finally:
                events.append(("exit", scope["path"]))

    monkeypatch.setattr(run_sse.mcp, "_mcp_server", _FakeServer())
    sse_endpoint, _health_endpoint = run_sse._build_sse_handlers(_FakeTransport())
    scope = {
        "type": "http",
        "path": "/sse",
        "headers": [],
        "client": ("127.0.0.1", 50000),
        "method": "GET",
        "scheme": "http",
        "query_string": b"",
        "server": ("127.0.0.1", 8000),
    }

    async def _receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _send(_message: dict[str, object]) -> None:
        return None

    with pytest.raises(asyncio.CancelledError):
        await sse_endpoint(scope, _receive, _send)

    assert events == [
        ("enter", "/sse"),
        "init",
        ("run", "read-stream", "write-stream", {"mode": "test"}),
        ("exit", "/sse"),
    ]


def test_run_sse_source_does_not_use_request_private_send() -> None:
    source = Path(run_sse.__file__).read_text(encoding="utf-8")
    assert "request._send" not in source


def test_sse_main_requests_runtime_initialization_before_uvicorn(monkeypatch) -> None:
    call_order = []

    def _fake_create_sse_app(**kwargs):
        call_order.append(("create_sse_app", kwargs))
        return {"app": "fake"}

    def _fake_run_uvicorn_sse_app(app, *, host, port, transport):
        call_order.append(("uvicorn", host, port, app, transport))

    monkeypatch.setattr(run_sse, "create_sse_app", _fake_create_sse_app)
    monkeypatch.setattr(run_sse, "_create_sse_transport", lambda: "transport")
    monkeypatch.setattr(run_sse, "_run_uvicorn_sse_app", _fake_run_uvicorn_sse_app)
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "8010")

    run_sse.main()

    assert call_order[0] == (
        "create_sse_app",
        {"initialize_runtime_on_startup": True, "transport": "transport"},
    )
    assert call_order[1][0] == "uvicorn"
    assert call_order[1][1] == "127.0.0.1"
    assert call_order[1][2] == 8010


def test_sse_malformed_message_returns_400_without_internal_error_event(tmp_path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    env = dict(**os.environ)
    env["MCP_API_KEY"] = "week6-sse-secret"
    env["DATABASE_URL"] = _sqlite_url(tmp_path / "malformed_message.db")
    env["HOST"] = "127.0.0.1"
    env["PORT"] = str(port)
    server = _spawn_run_sse_subprocess(backend_dir=backend_dir, env=env)

    sse_socket = None
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            if server.poll() is not None:
                pytest.fail("uvicorn exited before the malformed-message test could connect")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("timed out waiting for malformed-message test server to start")

        session_id = None
        request = (
            "GET /sse HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Accept: text/event-stream\r\n"
            "X-MCP-API-Key: week6-sse-secret\r\n"
            "Connection: keep-alive\r\n"
            "\r\n"
        ).encode("utf-8")
        sse_socket = socket.create_connection(("127.0.0.1", port), timeout=5)
        sse_socket.sendall(request)
        sse_socket.settimeout(5)

        received = ""
        deadline = time.time() + 5
        while time.time() < deadline:
            chunk = sse_socket.recv(4096).decode("utf-8", errors="ignore")
            if not chunk:
                break
            received += chunk
            if "session_id=" in received:
                session_id = received.split("session_id=", 1)[1].splitlines()[0].strip()
                break
        assert session_id

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request(
                "POST",
                f"/messages/?session_id={session_id}",
                body='{"bad":',
                headers={
                    "Content-Type": "application/json",
                    "X-MCP-API-Key": "week6-sse-secret",
                },
            )
            response = connection.getresponse()
            payload = response.read().decode("utf-8", errors="ignore")
        finally:
            connection.close()

        assert response.status == 400
        assert "Could not parse message" in payload

        sse_socket.settimeout(1)
        trailing = ""
        try:
            while True:
                chunk = sse_socket.recv(4096).decode("utf-8", errors="ignore")
                if not chunk:
                    break
                trailing += chunk
        except socket.timeout:
            pass

        assert "Internal Server Error" not in trailing
        time.sleep(0.2)
    finally:
        if sse_socket is not None:
            try:
                sse_socket.close()
            except OSError:
                pass
        server.terminate()
        try:
            output, _ = server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            output, _ = server.communicate(timeout=5)

    assert "Received exception from stream" not in output
    assert "Traceback" not in output
