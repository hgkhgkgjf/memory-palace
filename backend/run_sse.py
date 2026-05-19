import os
import sys
import hmac
import hashlib
import asyncio
import errno
import logging
import socket
import threading
import time
import uvicorn
from collections import deque
from contextlib import asynccontextmanager
from ipaddress import ip_address, ip_network
from typing import Any, Deque, Dict, Optional, Tuple
from urllib.parse import quote
from uuid import UUID, uuid4

import anyio
from anyio import ClosedResourceError
import mcp.types as types
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import ValidationError
from sse_starlette import EventSourceResponse
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import Response
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send
from shared_utils import env_int as _shared_env_int, is_loopback_hostname as _is_loopback_hostname

# Ensure we can import from backend dir
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from db import close_sqlite_client
from mcp_server import (
    drain_pending_flush_summaries,
    mcp,
)
from mcp.server.sse import SseServerTransport
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from runtime_state import runtime_state
from runtime_bootstrap import initialize_backend_runtime

logger = logging.getLogger(__name__)

_MCP_API_KEY_ENV = "MCP_API_KEY"
_MCP_API_KEY_HEADER = "X-MCP-API-Key"
_MCP_API_KEY_ALLOW_INSECURE_LOCAL_ENV = "MCP_API_KEY_ALLOW_INSECURE_LOCAL"
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on", "enabled"}
_LOOPBACK_CLIENT_HOSTS = {"127.0.0.1", "::1", "localhost"}
_DEFAULT_SSE_PORT = 8000
_LOOPBACK_FALLBACK_SSE_PORT = 8010
_FORWARDED_HEADER_NAMES = {
    "forwarded",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-forwarded-port",
    "x-real-ip",
    "x-client-ip",
    "true-client-ip",
    "cf-connecting-ip",
}
_SSE_HTTP_PATHS = {"/sse", "/sse/", "/messages", "/messages/", "/sse/messages", "/sse/messages/"}
_PUBLIC_HTTP_PATHS = {"/health", "/health/"}
_SSE_TRUSTED_PROXY_HOSTS_ENV = "SSE_TRUSTED_PROXY_HOSTS"
_SSE_TRUSTED_PROXY_CIDRS_ENV = "SSE_TRUSTED_PROXY_CIDRS"


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    return _shared_env_int(name, default, minimum=minimum, clamp_default=True)


def _env_csv(name: str) -> tuple[str, ...]:
    raw = str(os.getenv(name) or "")
    values: list[str] = []
    for part in raw.split(","):
        candidate = str(part or "").strip()
        if candidate:
            values.append(candidate)
    return tuple(values)


def _loopback_probe_targets(
    host: str | None = None,
) -> tuple[tuple[str, int, bool], ...]:
    normalized_host = str(host or "").strip().lower()
    if normalized_host == "127.0.0.1":
        return (
            ("127.0.0.1", socket.AF_INET, True),
            ("::1", socket.AF_INET6, False),
        )
    if normalized_host == "::1":
        return (
            ("127.0.0.1", socket.AF_INET, False),
            ("::1", socket.AF_INET6, True),
        )
    if normalized_host == "localhost":
        return (
            ("127.0.0.1", socket.AF_INET, True),
            ("::1", socket.AF_INET6, False),
        )
    return (
        ("127.0.0.1", socket.AF_INET, True),
        ("::1", socket.AF_INET6, True),
    )


def _is_loopback_port_available(port: int, host: str | None = None) -> bool:
    attempted_required_probe = False
    for probe_host, family, required in _loopback_probe_targets(host or os.getenv("HOST")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe:
                if required:
                    attempted_required_probe = True
                if family == socket.AF_INET6 and hasattr(socket, "IPV6_V6ONLY"):
                    try:
                        probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                    except OSError:
                        pass
                probe.bind((probe_host, port))
        except OSError as exc:
            if exc.errno in {
                errno.EADDRNOTAVAIL,
                errno.EAFNOSUPPORT,
                errno.EPROTONOSUPPORT,
            }:
                if required:
                    return False
                continue
            if required:
                return False
    return attempted_required_probe


def _is_requested_loopback_port_available(host: str, port: int) -> bool:
    checker = _is_loopback_port_available
    try:
        return checker(port, host)
    except TypeError:
        return checker(port)


def _format_http_host_for_display(host: str) -> str:
    normalized = str(host or "").strip() or "127.0.0.1"
    if ":" in normalized and not normalized.startswith("[") and not normalized.endswith("]"):
        return f"[{normalized}]"
    return normalized


def _resolve_sse_port(host: str) -> int:
    raw_port = str(os.getenv("PORT") or "").strip()
    if raw_port:
        return _env_int("PORT", _DEFAULT_SSE_PORT, minimum=1)

    normalized_host = str(host or "").strip().lower()
    if (
        normalized_host in {"127.0.0.1", "localhost", "::1"}
        and not _is_requested_loopback_port_available(normalized_host or host, _DEFAULT_SSE_PORT)
    ):
        display_host = _format_http_host_for_display(normalized_host or host)
        if not _is_requested_loopback_port_available(
            normalized_host or host, _LOOPBACK_FALLBACK_SSE_PORT
        ):
            raise RuntimeError(
                "Loopback SSE ports "
                f"{_DEFAULT_SSE_PORT} and {_LOOPBACK_FALLBACK_SSE_PORT} are unavailable; "
                "set PORT explicitly."
            )
        print(
            f"Loopback port {_DEFAULT_SSE_PORT} is already in use; "
            f"falling back to {_LOOPBACK_FALLBACK_SSE_PORT}. "
            f"Update MCP client config to "
            f"http://{display_host}:{_LOOPBACK_FALLBACK_SSE_PORT}/sse "
            f"or set PORT explicitly.",
            file=sys.stderr,
        )
        return _LOOPBACK_FALLBACK_SSE_PORT

    return _DEFAULT_SSE_PORT


def _get_configured_mcp_api_key() -> str:
    return str(os.getenv(_MCP_API_KEY_ENV) or "").strip()


def _allow_insecure_local_without_api_key() -> bool:
    value = str(os.getenv(_MCP_API_KEY_ALLOW_INSECURE_LOCAL_ENV) or "").strip().lower()
    return value in _TRUTHY_ENV_VALUES


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not isinstance(authorization, str):
        return None
    value = authorization.strip()
    if not value:
        return None
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token if token else None


def _extract_scope_client_host(scope: Scope) -> str:
    client = scope.get("client")
    host = ""
    if isinstance(client, tuple) and client:
        host = str(client[0] or "").strip().lower()
    elif client is not None:
        host = str(getattr(client, "host", "") or "").strip().lower()
    return host


def _trusted_proxy_hosts() -> set[str]:
    configured_hosts = {
        str(item or "").strip().lower()
        for item in _env_csv(_SSE_TRUSTED_PROXY_HOSTS_ENV)
        if str(item or "").strip()
    }
    return set(_LOOPBACK_CLIENT_HOSTS) | configured_hosts


def _trusted_proxy_networks() -> tuple[Any, ...]:
    networks = []
    for item in _env_csv(_SSE_TRUSTED_PROXY_CIDRS_ENV):
        try:
            networks.append(ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _is_trusted_proxy_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    if not normalized:
        return False
    if normalized in _trusted_proxy_hosts():
        return True
    try:
        address = ip_address(normalized)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    return any(address in network for network in _trusted_proxy_networks())


def _extract_forwarded_client_host(scope: Scope) -> Optional[str]:
    headers = Headers(raw=list(scope.get("headers") or []))
    forwarded_for = headers.get("x-forwarded-for")
    if isinstance(forwarded_for, str) and forwarded_for.strip():
        for item in forwarded_for.split(","):
            candidate = str(item or "").strip().lower()
            if not candidate:
                continue
            try:
                ip_address(candidate)
                return candidate
            except ValueError:
                continue

    real_ip = headers.get("x-real-ip")
    if isinstance(real_ip, str):
        candidate = real_ip.strip().lower()
        if candidate:
            try:
                ip_address(candidate)
                return candidate
            except ValueError:
                return None
    return None


def _resolve_rate_limit_client_host(scope: Scope) -> str:
    direct_host = _extract_scope_client_host(scope)
    if _is_trusted_proxy_host(direct_host):
        forwarded_host = _extract_forwarded_client_host(scope)
        if forwarded_host:
            return forwarded_host
    return direct_host or "unknown"


def _extract_rate_limit_auth_token(scope: Scope) -> str:
    headers = Headers(raw=list(scope.get("headers") or []))
    provided = (
        str(headers.get(_MCP_API_KEY_HEADER) or "").strip()
        or _extract_bearer_token(headers.get("authorization"))
        or ""
    )
    return provided


def _build_rate_limit_principal_key(scope: Scope) -> str:
    host = _resolve_rate_limit_client_host(scope)
    token = _extract_rate_limit_auth_token(scope)
    if not token:
        return host
    token_hash = hashlib.sha256(token.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{host}:{token_hash}"


def _is_loopback_scope(scope: Scope) -> bool:
    host = _extract_scope_client_host(scope)
    if host not in _LOOPBACK_CLIENT_HOSTS:
        return False

    headers = Headers(scope=scope)
    for header_name in _FORWARDED_HEADER_NAMES:
        header_value = headers.get(header_name)
        if isinstance(header_value, str) and header_value.strip():
            return False
    return True


def _extract_host_from_scope(scope: Scope) -> Optional[str]:
    headers = Headers(scope=scope)
    host_header = headers.get("host")
    if isinstance(host_header, str) and host_header.strip():
        return host_header
    server = scope.get("server")
    if isinstance(server, tuple) and server:
        return str(server[0] or "").strip()
    return None


def _is_direct_loopback_scope(scope: Scope) -> bool:
    if not _is_loopback_scope(scope):
        return False
    return _is_loopback_hostname(_extract_host_from_scope(scope))


async def _read_request_body_with_limit(
    request: Request, *, max_bytes: int
) -> tuple[Optional[bytes], bool]:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                return None, True
        except (TypeError, ValueError):
            pass

    body = bytearray()
    async for chunk in request.stream():
        if not chunk:
            continue
        body.extend(chunk)
        if len(body) > max_bytes:
            return None, True
    return bytes(body), False


def _should_suppress_stream_shutdown_runtime_error(scope: Scope, exc: RuntimeError) -> bool:
    if scope.get("type") != "http":
        return False
    path = _resolve_request_path(scope)
    if path not in _SSE_HTTP_PATHS:
        return False
    message = str(exc)
    return (
        "Expected ASGI message 'http.response.body'" in message
        and "'http.response.start'" in message
    )


def _should_suppress_request_validation_value_error(scope: Scope, exc: ValueError) -> bool:
    if scope.get("type") != "http":
        return False
    path = _resolve_request_path(scope)
    if path not in _SSE_HTTP_PATHS:
        return False
    return str(exc).strip() == "Request validation failed"


def _should_suppress_closed_resource_error(scope: Scope) -> bool:
    if scope.get("type") != "http":
        return False
    path = _resolve_request_path(scope)
    return path in {"/sse", "/sse/"}


def _resolve_request_path(scope: Scope) -> str:
    root_path = str(scope.get("root_path") or "").rstrip("/")
    path = str(scope.get("path") or "")
    if not path:
        path = "/"
    elif not path.startswith("/"):
        path = f"/{path}"

    if not root_path:
        return path
    if path == "/":
        return f"{root_path}/"
    return f"{root_path}{path}"


async def _finalize_suppressed_stream_response_if_needed(
    *,
    send: Send,
    response_started: bool,
    response_completed: bool,
) -> None:
    if not response_started or response_completed:
        return
    try:
        await send({"type": "http.response.body", "body": b"", "more_body": False})
    except (ClosedResourceError, RuntimeError, ValueError):
        return


async def _call_app_with_sse_shutdown_suppression(
    app: ASGIApp, scope: Scope, receive: Receive, send: Send
) -> None:
    try:
        await app(scope, receive, send)
    except ClosedResourceError:
        if _should_suppress_closed_resource_error(scope):
            return
        raise
    except RuntimeError as exc:
        if _should_suppress_stream_shutdown_runtime_error(scope, exc):
            return
        raise
    except ValueError as exc:
        if _should_suppress_request_validation_value_error(scope, exc):
            return
        raise


class MemoryPalaceSseServerTransport(SseServerTransport):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._message_rate_limit_window_seconds = float(
            _env_int("SSE_MESSAGE_RATE_LIMIT_WINDOW_SECONDS", 10, minimum=1)
        )
        self._message_rate_limit_max_requests = _env_int(
            "SSE_MESSAGE_RATE_LIMIT_MAX_REQUESTS", 120, minimum=10
        )
        self._message_rate_limit_max_keys = _env_int(
            "SSE_MESSAGE_RATE_LIMIT_MAX_KEYS", 1024, minimum=1
        )
        self._heartbeat_ping_seconds = _env_int(
            "SSE_HEARTBEAT_PING_SECONDS", 15, minimum=5
        )
        self._message_max_body_bytes = _env_int(
            "SSE_MESSAGE_MAX_BODY_BYTES", 1024 * 1024, minimum=1024
        )
        self._message_rate_limit_buckets: Dict[str, Deque[float]] = {}
        self._message_rate_limit_last_seen: Dict[str, float] = {}
        self._message_rate_limit_guard = threading.Lock()
        self._runtime_loop: Optional[asyncio.AbstractEventLoop] = None
        self._shutdown_streams_requested = False

    @staticmethod
    def _session_rate_limit_key(scope: Scope, session_id: UUID) -> str:
        _ = session_id
        return _build_rate_limit_principal_key(scope)

    async def _check_message_rate_limit(
        self, *, scope: Scope, session_id: UUID
    ) -> Optional[int]:
        key = self._session_rate_limit_key(scope, session_id)
        now = time.monotonic()
        with self._message_rate_limit_guard:
            bucket = self._message_rate_limit_buckets.get(key)
            if bucket is None:
                self._evict_oldest_rate_limit_key_if_needed()
                bucket = deque()
                self._message_rate_limit_buckets[key] = bucket

            cutoff = now - self._message_rate_limit_window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= self._message_rate_limit_max_requests:
                retry_after = max(
                    1,
                    int((bucket[0] + self._message_rate_limit_window_seconds) - now),
                )
                return retry_after

            bucket.append(now)
            self._message_rate_limit_last_seen[key] = now
            return None

    async def _clear_message_rate_limit_state(
        self, *, scope: Scope, session_id: UUID
    ) -> None:
        _ = scope, session_id
        return None

    def _evict_oldest_rate_limit_key_if_needed(self) -> None:
        if len(self._message_rate_limit_buckets) < self._message_rate_limit_max_keys:
            return
        oldest_key = min(
            self._message_rate_limit_buckets.keys(),
            key=lambda item: self._message_rate_limit_last_seen.get(item, float("-inf")),
        )
        self._message_rate_limit_buckets.pop(oldest_key, None)
        self._message_rate_limit_last_seen.pop(oldest_key, None)

    @asynccontextmanager
    async def connect_sse(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            raise ValueError("connect_sse can only handle HTTP requests")
        try:
            self._runtime_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._runtime_loop = None

        request = Request(scope, receive)
        error_response = await self._security.validate_request(request, is_post=False)
        if error_response:
            await error_response(scope, receive, send)
            raise ValueError("Request validation failed")

        # Keep all internal channels zero-buffered so slow SSE clients apply
        # backpressure instead of building an unbounded user-space queue.
        read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

        session_id = uuid4()
        self._read_stream_writers[session_id] = read_stream_writer

        root_path = scope.get("root_path", "")
        full_message_path_for_client = root_path.rstrip("/") + self._endpoint
        client_post_uri_data = (
            f"{quote(full_message_path_for_client)}?session_id={session_id.hex}"
        )

        sse_stream_writer, sse_stream_reader = anyio.create_memory_object_stream(0)

        async def sse_writer():
            async with sse_stream_writer, write_stream_reader:
                event_index = 0

                def next_event_id() -> str:
                    nonlocal event_index
                    event_id = f"{session_id.hex}:{event_index}"
                    event_index += 1
                    return event_id

                await sse_stream_writer.send(
                    {
                        "id": next_event_id(),
                        "event": "endpoint",
                        "data": client_post_uri_data,
                    }
                )
                async for session_message in write_stream_reader:
                    await sse_stream_writer.send(
                        {
                            "id": next_event_id(),
                            "event": "message",
                            "data": session_message.message.model_dump_json(
                                by_alias=True, exclude_none=True
                            ),
                        }
                    )

        async with anyio.create_task_group() as tg:

            async def response_wrapper(
                scope: Scope, receive: Receive, send: Send
            ) -> None:
                response_started = False
                response_completed = False

                async def tracked_send(message: Dict[str, Any]) -> None:
                    nonlocal response_started, response_completed
                    message_type = str(message.get("type") or "")
                    if message_type == "http.response.start":
                        response_started = True
                    elif message_type == "http.response.body" and not bool(
                        message.get("more_body", False)
                    ):
                        response_completed = True
                    await send(message)

                try:
                    try:
                        await EventSourceResponse(
                            content=sse_stream_reader,
                            data_sender_callable=sse_writer,
                            ping=self._heartbeat_ping_seconds,
                        )(scope, receive, tracked_send)
                    except ClosedResourceError:
                        if not _should_suppress_closed_resource_error(scope):
                            raise
                        await _finalize_suppressed_stream_response_if_needed(
                            send=send,
                            response_started=response_started,
                            response_completed=response_completed,
                        )
                    except RuntimeError as exc:
                        if not _should_suppress_stream_shutdown_runtime_error(scope, exc):
                            raise
                        await _finalize_suppressed_stream_response_if_needed(
                            send=send,
                            response_started=response_started,
                            response_completed=response_completed,
                        )
                    except ValueError as exc:
                        if not _should_suppress_request_validation_value_error(scope, exc):
                            raise
                        await _finalize_suppressed_stream_response_if_needed(
                            send=send,
                            response_started=response_started,
                            response_completed=response_completed,
                        )
                    except asyncio.CancelledError:
                        await _finalize_suppressed_stream_response_if_needed(
                            send=send,
                            response_started=response_started,
                            response_completed=response_completed,
                        )
                        return
                finally:
                    self._read_stream_writers.pop(session_id, None)
                    await self._clear_message_rate_limit_state(
                        scope=scope, session_id=session_id
                    )
                    try:
                        await read_stream_writer.aclose()
                    except ClosedResourceError:
                        pass
                    except Exception:
                        logger.debug("SSE read stream writer close failed", exc_info=True)
                    try:
                        await write_stream_reader.aclose()
                    except ClosedResourceError:
                        pass
                    except Exception:
                        logger.debug("SSE write stream reader close failed", exc_info=True)

            tg.start_soon(response_wrapper, scope, receive, send)
            yield (read_stream, write_stream)

    async def close_active_streams(self) -> None:
        writers = list(self._read_stream_writers.values())
        self._read_stream_writers = {}
        for writer in writers:
            try:
                await writer.aclose()
            except Exception:
                continue

        with self._message_rate_limit_guard:
            self._message_rate_limit_buckets.clear()
            self._message_rate_limit_last_seen.clear()

    def request_shutdown_stream_close(self) -> None:
        if self._shutdown_streams_requested:
            return
        self._shutdown_streams_requested = True
        loop = self._runtime_loop
        if loop is None or loop.is_closed():
            return

        def _schedule_close() -> None:
            asyncio.create_task(self.close_active_streams())

        loop.call_soon_threadsafe(_schedule_close)

    async def handle_post_message(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        request = Request(scope, receive)

        error_response = await self._security.validate_request(request, is_post=True)
        if error_response:
            return await error_response(scope, receive, send)

        session_id_param = request.query_params.get("session_id")
        if session_id_param is None:
            response = Response("session_id is required", status_code=400)
            return await response(scope, receive, send)

        try:
            session_id = UUID(hex=session_id_param)
        except ValueError:
            response = Response("Invalid session ID", status_code=400)
            return await response(scope, receive, send)

        writer = self._read_stream_writers.get(session_id)
        if not writer:
            response = Response("Could not find session", status_code=404)
            return await response(scope, receive, send)

        retry_after = await self._check_message_rate_limit(
            scope=scope, session_id=session_id
        )
        if retry_after is not None:
            response = Response(
                "Too many requests for this session",
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
            return await response(scope, receive, send)

        body, body_too_large = await _read_request_body_with_limit(
            request, max_bytes=self._message_max_body_bytes
        )
        if body_too_large:
            response = Response(
                f"Message body too large (max {self._message_max_body_bytes} bytes)",
                status_code=413,
            )
            return await response(scope, receive, send)

        try:
            message = types.JSONRPCMessage.model_validate_json(body)
        except ValidationError as err:
            response = Response("Could not parse message", status_code=400)
            await response(scope, receive, send)
            return

        metadata = ServerMessageMetadata(request_context=request)
        session_message = SessionMessage(message, metadata=metadata)
        try:
            await writer.send(session_message)
        except ClosedResourceError:
            self._read_stream_writers.pop(session_id, None)
            response = Response("Session is closed", status_code=410)
            return await response(scope, receive, send)

        response = Response("Accepted", status_code=202)
        await response(scope, receive, send)


def apply_mcp_api_key_middleware(app: ASGIApp) -> ASGIApp:
    async def _auth_middleware(scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await app(scope, receive, send)
            return

        path = _resolve_request_path(scope)
        if path in _PUBLIC_HTTP_PATHS:
            await _call_app_with_sse_shutdown_suppression(app, scope, receive, send)
            return

        configured = _get_configured_mcp_api_key()
        headers = Headers(scope=scope)
        if not configured:
            if _allow_insecure_local_without_api_key() and _is_direct_loopback_scope(scope):
                await _call_app_with_sse_shutdown_suppression(app, scope, receive, send)
                return
            reason = (
                "insecure_local_override_requires_loopback"
                if _allow_insecure_local_without_api_key()
                else "api_key_not_configured"
            )
            response = JSONResponse(
                status_code=401,
                content={
                    "error": "mcp_sse_auth_failed",
                    "reason": reason,
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        provided = (
            str(headers.get(_MCP_API_KEY_HEADER, "")).strip()
            or _extract_bearer_token(headers.get("Authorization"))
        )
        if not provided or not hmac.compare_digest(provided, configured):
            response = JSONResponse(
                status_code=401,
                content={
                    "error": "mcp_sse_auth_failed",
                    "reason": "invalid_or_missing_api_key",
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await _call_app_with_sse_shutdown_suppression(app, scope, receive, send)

    return _auth_middleware


def _build_message_alias_path() -> str:
    return f"{mcp.settings.sse_path.rstrip('/')}{mcp.settings.message_path}"


def _create_sse_transport() -> MemoryPalaceSseServerTransport:
    return MemoryPalaceSseServerTransport(
        mcp._normalize_path(mcp.settings.mount_path, mcp.settings.message_path),
        security_settings=mcp.settings.transport_security,
    )

def _build_sse_handlers(
    transport: MemoryPalaceSseServerTransport,
) -> Tuple[Any, Any]:
    class _SseEndpoint:
        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            async with transport.connect_sse(scope, receive, send) as streams:
                await mcp._mcp_server.run(
                    streams[0],
                    streams[1],
                    mcp._mcp_server.create_initialization_options(),
                )

    sse_endpoint = _SseEndpoint()

    async def health_endpoint(_request: Request) -> Response:
        return JSONResponse({"status": "ok", "service": "memory-palace-sse"})

    return sse_endpoint, health_endpoint


def create_embedded_sse_apps() -> Tuple[ASGIApp, ASGIApp]:
    transport = _create_sse_transport()
    sse_endpoint, _health_endpoint = _build_sse_handlers(transport)
    stream_app = Starlette(
        debug=mcp.settings.debug,
        routes=[Route("/", endpoint=sse_endpoint, methods=["GET"])],
    )
    return (
        apply_mcp_api_key_middleware(stream_app),
        apply_mcp_api_key_middleware(transport.handle_post_message),
    )


def create_sse_app(
    *,
    include_health: bool = True,
    manage_runtime_lifecycle: bool = True,
    initialize_runtime_on_startup: bool = False,
    transport: Optional[MemoryPalaceSseServerTransport] = None,
) -> ASGIApp:
    transport = transport or _create_sse_transport()
    sse_endpoint, health_endpoint = _build_sse_handlers(transport)

    routes = []
    if include_health:
        routes.append(Route("/health", endpoint=health_endpoint, methods=["GET"]))
    routes.extend(
        [
            Mount(_build_message_alias_path(), app=transport.handle_post_message),
            Route(mcp.settings.sse_path, endpoint=sse_endpoint, methods=["GET"]),
            Mount(mcp.settings.message_path, app=transport.handle_post_message),
            *mcp._custom_starlette_routes,
        ]
    )

    lifespan = None
    if manage_runtime_lifecycle:
        @asynccontextmanager
        async def lifespan(_app: Starlette):
            if initialize_runtime_on_startup:
                await initialize_backend_runtime()
            yield
            try:
                await drain_pending_flush_summaries(reason="runtime.shutdown")
            finally:
                await runtime_state.shutdown()
                await close_sqlite_client()

    app = Starlette(debug=mcp.settings.debug, routes=routes, lifespan=lifespan)
    return apply_mcp_api_key_middleware(app)


class _SignalAwareSseServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config, *, transport: MemoryPalaceSseServerTransport):
        super().__init__(config)
        self._transport = transport

    def handle_exit(self, sig: int, frame: Optional[object]) -> None:
        self._transport.request_shutdown_stream_close()
        super().handle_exit(sig, frame)


def _run_uvicorn_sse_app(
    app: ASGIApp,
    *,
    host: str,
    port: int,
    transport: MemoryPalaceSseServerTransport,
) -> None:
    config = uvicorn.Config(app, host=host, port=port)
    server = _SignalAwareSseServer(config, transport=transport)
    try:
        server.run()
    except KeyboardInterrupt:
        return


def main():
    """
    Run the Memory Palace MCP server using SSE (Server-Sent Events) transport.
    This is required for clients that don't support stdio (like some web-based tools).
    """
    print("Initializing Memory Palace SSE Server...")
    transport = _create_sse_transport()
    app = create_sse_app(
        initialize_runtime_on_startup=True,
        transport=transport,
    )

    host = str(os.getenv("HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = _resolve_sse_port(host)
    display_host = _format_http_host_for_display(host)

    print(f"Starting SSE Server on http://{display_host}:{port}")
    print(f"SSE Endpoint: http://{display_host}:{port}/sse")

    _run_uvicorn_sse_app(app, host=host, port=port, transport=transport)

if __name__ == "__main__":
    main()
