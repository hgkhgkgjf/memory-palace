import socket
from datetime import datetime

import pytest

import mcp_server
from shared_utils import (
    PRIVATE_PROVIDER_TARGETS_ENV,
    allowed_private_provider_targets,
    env_bool,
    env_int,
    is_loopback_hostname,
    normalize_http_api_base,
    parse_iso_datetime,
    utc_iso_now,
)


def test_env_bool_uses_shared_truthy_values(monkeypatch) -> None:
    monkeypatch.setenv("MP_SHARED_BOOL", "enabled")
    assert env_bool("MP_SHARED_BOOL", False) is True
    monkeypatch.setenv("MP_SHARED_BOOL", "off")
    assert env_bool("MP_SHARED_BOOL", True) is False


def test_env_int_keeps_runtime_style_default_fallback(monkeypatch) -> None:
    monkeypatch.delenv("MP_SHARED_INT", raising=False)
    assert env_int("MP_SHARED_INT", 3, minimum=5) == 3
    monkeypatch.setenv("MP_SHARED_INT", "2")
    assert env_int("MP_SHARED_INT", 3, minimum=5) == 5


def test_env_int_supports_sse_style_clamped_default(monkeypatch) -> None:
    monkeypatch.delenv("MP_SHARED_INT", raising=False)
    assert env_int("MP_SHARED_INT", 3, minimum=5, clamp_default=True) == 5
    monkeypatch.setenv("MP_SHARED_INT", "invalid")
    assert env_int("MP_SHARED_INT", 3, minimum=5, clamp_default=True) == 5


def test_is_loopback_hostname_handles_ipv6_and_host_ports() -> None:
    assert is_loopback_hostname("[::1]:8000") is True
    assert is_loopback_hostname("127.0.0.1:5173") is True
    assert is_loopback_hostname("memory-palace.example") is False


def test_normalize_http_api_base_trims_known_suffix_without_losing_host() -> None:
    assert (
        normalize_http_api_base(
            "https://Example.com/v1/embeddings/",
            trim_suffixes=("/embeddings",),
        )
        == "https://Example.com/v1"
    )


def test_normalize_http_api_base_rejects_non_http_scheme() -> None:
    with pytest.raises(ValueError, match="http or https"):
        normalize_http_api_base("file:///tmp/provider.sock")


def test_normalize_http_api_base_rejects_embedded_credentials() -> None:
    with pytest.raises(ValueError, match="embedded credentials"):
        normalize_http_api_base("https://user:pass@example.com/v1")


def test_normalize_http_api_base_rejects_link_local_metadata_addresses() -> None:
    with pytest.raises(ValueError, match="link-local"):
        normalize_http_api_base("http://169.254.169.254/v1")


def test_allowed_private_provider_targets_keeps_loopback_defaults(monkeypatch) -> None:
    monkeypatch.delenv(PRIVATE_PROVIDER_TARGETS_ENV, raising=False)
    assert {"127.0.0.1", "::1", "localhost"} <= allowed_private_provider_targets()


def test_normalize_http_api_base_allows_loopback_hosts_by_default() -> None:
    assert normalize_http_api_base("http://127.0.0.1:9999/v1") == "http://127.0.0.1:9999/v1"


def test_normalize_http_api_base_rejects_private_ip_literals_without_allowlist(monkeypatch) -> None:
    monkeypatch.delenv(PRIVATE_PROVIDER_TARGETS_ENV, raising=False)
    with pytest.raises(ValueError, match="private IP literal"):
        normalize_http_api_base("http://10.0.0.8:11435/v1")


def test_normalize_http_api_base_allows_private_ip_literals_when_allowlisted(
    monkeypatch,
) -> None:
    monkeypatch.setenv(PRIVATE_PROVIDER_TARGETS_ENV, "10.0.0.0/8,fc00::/7")
    assert normalize_http_api_base("http://10.0.0.8:11435/v1") == "http://10.0.0.8:11435/v1"
    assert normalize_http_api_base("http://[fc00::1]/v1") == "http://[fc00::1]/v1"


def test_normalize_http_api_base_rejects_private_hostnames_without_allowlist(
    monkeypatch,
) -> None:
    monkeypatch.delenv(PRIVATE_PROVIDER_TARGETS_ENV, raising=False)
    monkeypatch.setattr(
        "shared_utils.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 11435))
        ],
    )
    with pytest.raises(ValueError, match="private-address hostname"):
        normalize_http_api_base("http://router.internal:11435/v1")


def test_normalize_http_api_base_allows_private_hostnames_when_allowlisted(
    monkeypatch,
) -> None:
    monkeypatch.setenv(PRIVATE_PROVIDER_TARGETS_ENV, "router.internal")
    monkeypatch.setattr(
        "shared_utils.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 11435))
        ],
    )
    assert (
        normalize_http_api_base("http://router.internal:11435/v1")
        == "http://router.internal:11435/v1"
    )


def test_normalize_http_api_base_rejects_partially_allowlisted_private_hostname(
    monkeypatch,
) -> None:
    monkeypatch.setenv(PRIVATE_PROVIDER_TARGETS_ENV, "10.0.0.0/8")
    monkeypatch.setattr(
        "shared_utils.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 11435)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.9", 11435)),
        ],
    )
    with pytest.raises(ValueError, match="private-address hostname"):
        normalize_http_api_base("http://router.internal:11435/v1")


def test_utc_iso_now_returns_utc_z_suffix() -> None:
    assert utc_iso_now().endswith("Z")


def test_parse_iso_datetime_normalizes_timezone_offsets_to_utc_naive() -> None:
    parsed = parse_iso_datetime(
        "2026-03-21T16:30:00+08:00",
        normalize_to_utc_naive=True,
    )

    assert parsed == datetime(2026, 3, 21, 8, 30, 0)
    assert parsed.tzinfo is None


def test_parse_iso_datetime_raises_friendly_error_when_strict() -> None:
    with pytest.raises(ValueError, match="Invalid datetime 'not-a-datetime'"):
        parse_iso_datetime("not-a-datetime", strict=True)


def test_mcp_server_parse_iso_datetime_reuses_shared_normalization() -> None:
    assert mcp_server._parse_iso_datetime("2026-03-21T16:30:00+08:00") == datetime(
        2026, 3, 21, 8, 30, 0
    )
