import os
import math
import socket
from datetime import datetime, timezone
from ipaddress import ip_address, ip_network
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit


TRUTHY_ENV_VALUES = frozenset({"1", "true", "yes", "on", "enabled"})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
DEFAULT_INTERACTION_TIERS = frozenset({"fast", "deep"})
PRIVATE_PROVIDER_TARGETS_ENV = "MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS"


def env_bool(
    name: str,
    default: bool,
    truthy_values: Optional[Iterable[str]] = None,
) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    values = TRUTHY_ENV_VALUES if truthy_values is None else frozenset(truthy_values)
    return raw.strip().lower() in values


def env_int(
    name: str,
    default: int,
    minimum: int = 0,
    *,
    clamp_default: bool = False,
) -> int:
    raw = os.getenv(name)
    fallback = max(minimum, default) if clamp_default else default
    if raw is None:
        return fallback
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return fallback
    return max(minimum, value)


def env_float(
    name: str,
    default: float,
    minimum: float = 0.0,
    *,
    clamp_default: bool = False,
) -> float:
    fallback = max(minimum, default) if clamp_default else default
    raw = os.getenv(name)
    if raw is None:
        return fallback
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(value):
        return fallback
    return max(minimum, value)


def utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso_datetime(
    value: Optional[str],
    *,
    normalize_to_utc_naive: bool = False,
    strict: bool = False,
) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        if strict:
            raise ValueError(
                f"Invalid datetime '{value}'. Use ISO-8601 like '2026-01-31T12:00:00Z'."
            ) from exc
        return None
    if normalize_to_utc_naive and parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def is_loopback_hostname(
    value: Optional[str],
    loopback_hosts: Optional[Iterable[str]] = None,
) -> bool:
    if not value:
        return False
    hostname = str(value).strip().lower()
    if not hostname:
        return False
    if hostname.startswith("["):
        closing = hostname.find("]")
        if closing != -1:
            suffix = hostname[closing + 1 :]
            if not suffix or (
                suffix.startswith(":") and suffix[1:].isdigit()
            ):
                hostname = hostname[1:closing]
    if ":" in hostname and hostname.count(":") == 1 and hostname.rsplit(":", 1)[1].isdigit():
        hostname = hostname.rsplit(":", 1)[0]
    hosts = LOOPBACK_HOSTS if loopback_hosts is None else frozenset(loopback_hosts)
    if hostname in hosts:
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def allowed_private_provider_targets(
    raw_value: Optional[str] = None,
) -> frozenset[str]:
    value = raw_value if raw_value is not None else os.getenv(PRIVATE_PROVIDER_TARGETS_ENV)
    targets = set(LOOPBACK_HOSTS)
    for item in str(value or "").split(","):
        normalized = item.strip().lower()
        if normalized:
            targets.add(normalized)
    return frozenset(targets)


def _private_provider_target_matches(
    *,
    hostname: str,
    host_ip: Any,
    targets: Iterable[str],
) -> bool:
    normalized_hostname = str(hostname or "").strip().lower()
    for raw_target in targets:
        normalized_target = str(raw_target or "").strip().lower()
        if not normalized_target:
            continue
        if normalized_target == normalized_hostname:
            return True
        try:
            network = ip_network(normalized_target, strict=False)
        except ValueError:
            continue
        if host_ip.version != network.version:
            continue
        if host_ip in network:
            return True
    return False


def normalize_http_api_base(
    value: Optional[str],
    *,
    private_target_allowlist: Optional[Iterable[str]] = None,
    trim_suffixes: Optional[Iterable[str]] = None,
) -> str:
    normalized = str(value or "").strip().rstrip("/")
    if not normalized:
        return ""

    parsed = urlsplit(normalized)
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme not in {"http", "https"}:
        raise ValueError("API base URL must use http or https.")
    if not parsed.netloc or not parsed.hostname:
        raise ValueError("API base URL must include a host.")
    if parsed.username or parsed.password:
        raise ValueError("API base URL must not include embedded credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError("API base URL must not include query parameters or fragments.")

    try:
        host_ip = ip_address(parsed.hostname)
    except ValueError:
        host_ip = None
    private_targets = allowed_private_provider_targets()
    if private_target_allowlist is not None:
        private_targets = frozenset(
            str(item or "").strip().lower()
            for item in private_target_allowlist
            if str(item or "").strip()
        ) | LOOPBACK_HOSTS
    if host_ip is not None and (
        host_ip.is_unspecified or host_ip.is_multicast or host_ip.is_link_local
    ):
        raise ValueError(
            "API base URL cannot point to an unspecified, multicast, or link-local address."
        )
    if host_ip is not None and host_ip.is_private and not host_ip.is_loopback:
        if not _private_provider_target_matches(
            hostname=str(parsed.hostname or ""),
            host_ip=host_ip,
            targets=private_targets,
        ):
            raise ValueError(
                "API base URL cannot point to a private IP literal unless it is explicitly "
                f"allowlisted via {PRIVATE_PROVIDER_TARGETS_ENV}."
            )
    if host_ip is None:
        try:
            resolved_addresses = socket.getaddrinfo(
                str(parsed.hostname or ""),
                parsed.port or 0,
                type=socket.SOCK_STREAM,
            )
        except OSError:
            resolved_addresses = []
        resolved_private_hosts = []
        for _family, _socktype, _proto, _canonname, sockaddr in resolved_addresses:
            host_value = str((sockaddr or ("",))[0] or "").strip()
            if not host_value:
                continue
            try:
                resolved_ip = ip_address(host_value)
            except ValueError:
                continue
            if (
                resolved_ip.is_unspecified
                or resolved_ip.is_multicast
                or resolved_ip.is_link_local
            ):
                raise ValueError(
                    "API base URL cannot point to an unspecified, multicast, or link-local address."
                )
            if resolved_ip.is_private and not resolved_ip.is_loopback:
                resolved_private_hosts.append(resolved_ip)
        if resolved_private_hosts and not all(
            _private_provider_target_matches(
                hostname=str(parsed.hostname or ""),
                host_ip=resolved_ip,
                targets=private_targets,
            )
            for resolved_ip in resolved_private_hosts
        ):
            raise ValueError(
                "API base URL cannot point to a private-address hostname unless it is "
                f"explicitly allowlisted via {PRIVATE_PROVIDER_TARGETS_ENV}."
            )

    path = str(parsed.path or "").rstrip("/")
    for suffix in trim_suffixes or ():
        suffix_text = str(suffix or "").strip()
        if not suffix_text:
            continue
        if path.lower().endswith(suffix_text.lower()):
            path = path[: -len(suffix_text)].rstrip("/")
            break

    return urlunsplit((scheme, parsed.netloc, path, "", ""))


def resolve_interaction_tier(
    raw_filters: Optional[Dict[str, Any]],
    *,
    requested_tier: Optional[Any] = None,
    requested_scope_hint: Optional[Any] = None,
    allowed_tiers: Optional[Iterable[str]] = None,
    default_tier: str = "fast",
) -> Tuple[str, Optional[Dict[str, Any]], Optional[Any]]:
    allowed = frozenset(
        str(item).strip().lower()
        for item in (allowed_tiers or DEFAULT_INTERACTION_TIERS)
        if str(item).strip()
    ) or DEFAULT_INTERACTION_TIERS

    normalized_default = str(default_tier or "").strip().lower() or "fast"
    if normalized_default not in allowed:
        normalized_default = "fast"

    filters_copy: Optional[Dict[str, Any]] = raw_filters
    raw_value = requested_tier
    scope_hint_value = requested_scope_hint
    if isinstance(filters_copy, dict):
        filters_copy = dict(filters_copy)
        if raw_value is None and "interaction_tier" in filters_copy:
            raw_value = filters_copy.get("interaction_tier")
        filters_copy.pop("interaction_tier", None)

    if raw_value is None:
        scope_hint_tier = str(scope_hint_value or "").strip().lower()
        if scope_hint_tier in allowed:
            raw_value = scope_hint_tier
            scope_hint_value = None

    value = str(raw_value or "").strip().lower()
    if value not in allowed:
        value = normalized_default
    return value, filters_copy, scope_hint_value


def _normalize_domain_filter(
    value: Any,
    *,
    allowed_domains: Optional[Iterable[str]] = None,
) -> Optional[str]:
    if value is None:
        return None
    domain_value = str(value).strip().lower()
    if not domain_value:
        return None
    if allowed_domains is None:
        return domain_value
    allowed_list = [
        str(item).strip().lower()
        for item in allowed_domains
        if str(item).strip()
    ]
    allowed = frozenset(allowed_list)
    if domain_value not in allowed:
        raise ValueError(
            f"Unknown domain '{domain_value}'. "
            f"Valid domains: {', '.join(allowed_list)}"
        )
    return domain_value


def _split_uri_filter(value: str) -> Tuple[str, str]:
    domain_part, path_part = str(value).split("://", 1)
    domain = str(domain_part).strip().lower()
    path_prefix = str(path_part).strip().strip("/")
    if not domain:
        raise ValueError("URI filter must include a non-empty domain.")
    return domain, path_prefix


def normalize_search_filters(
    raw_filters: Optional[Dict[str, Any]],
    *,
    allowed_domains: Optional[Iterable[str]] = None,
    allow_priority_alias: bool = False,
) -> Dict[str, Any]:
    if raw_filters is None:
        return {}
    if not isinstance(raw_filters, dict):
        raise ValueError(
            "filters must be an object with optional fields: "
            "domain/path_prefix/max_priority/updated_after."
        )

    allowed_domains_list = [
        str(item).strip().lower()
        for item in (allowed_domains or [])
        if str(item).strip()
    ]

    allowed_keys = {"domain", "path_prefix", "max_priority", "updated_after"}
    if allow_priority_alias:
        allowed_keys.add("priority")
    unknown = set(raw_filters.keys()) - allowed_keys
    if unknown:
        raise ValueError(
            f"Unknown filters: {', '.join(sorted(unknown))}. "
            f"Allowed: {', '.join(sorted(allowed_keys))}."
        )

    normalized: Dict[str, Any] = {}

    domain_value = _normalize_domain_filter(
        raw_filters.get("domain"),
        allowed_domains=allowed_domains_list,
    )
    if domain_value:
        normalized["domain"] = domain_value

    path_prefix = raw_filters.get("path_prefix")
    if path_prefix is not None:
        path_value = str(path_prefix).strip()
        if path_value:
            if "://" in path_value:
                parsed_domain, parsed_path = _split_uri_filter(path_value)
                normalized_domain = _normalize_domain_filter(
                    parsed_domain,
                    allowed_domains=allowed_domains_list,
                )
                existing_domain = str(normalized.get("domain") or "").strip().lower()
                if existing_domain and normalized_domain and existing_domain != normalized_domain:
                    raise ValueError(
                        "filters.domain conflicts with filters.path_prefix URI domain"
                    )
                if normalized_domain:
                    normalized.setdefault("domain", normalized_domain)
                normalized["path_prefix"] = parsed_path
            else:
                normalized["path_prefix"] = path_value.strip("/")

    max_priority = raw_filters.get("max_priority")
    if max_priority is None and allow_priority_alias:
        max_priority = raw_filters.get("priority")
    if max_priority is not None:
        if isinstance(max_priority, bool) or isinstance(max_priority, float):
            raise ValueError("filters.max_priority must be an integer")
        try:
            normalized["max_priority"] = int(str(max_priority).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("filters.max_priority must be an integer") from exc

    updated_after = raw_filters.get("updated_after")
    if updated_after is not None:
        parsed = parse_iso_datetime(
            str(updated_after),
            normalize_to_utc_naive=True,
            strict=True,
        )
        if parsed is not None:
            normalized["updated_after"] = parsed.isoformat()

    return normalized


def should_try_intent_llm(
    client: Any,
    rule_payload: Optional[Dict[str, Any]],
) -> bool:
    helper = getattr(client, "should_use_intent_llm", None)
    if callable(helper):
        try:
            return bool(helper(rule_payload))
        except Exception:
            pass

    if not isinstance(rule_payload, dict) or not rule_payload:
        return True

    rule_intent = str(rule_payload.get("intent") or "").strip().lower()
    try:
        rule_confidence = float(rule_payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        rule_confidence = 0.0
    return rule_intent == "unknown" or rule_confidence < 0.70
