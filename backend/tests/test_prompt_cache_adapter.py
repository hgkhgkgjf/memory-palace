"""Tests for ``backend.mcp.adapters.cache_adapter.PromptCacheAdapter``.

The adapter is opt-in (Round 3 Track A constraint C4). These tests
exercise both the default pass-through behavior and the activated
split path, and assert the contract:

* ``read_memory("system://boot")``-style text is returned byte-for-byte
  unless BOTH env flag and host capability are active.
* When active, splitting only happens at the documented boundary
  marker; pathological inputs fall back to pass-through.
"""

from __future__ import annotations

import pytest

from mcp.adapters.cache_adapter import (
    BOUNDARY_MARKER,
    PROMPT_CACHE_SPLIT_ENV,
    REQUIRED_HOST_FLAG,
    PromptCacheAdapter,
)


SAMPLE_BOOT_TEXT = (
    "# Core Memories\n"
    "# Loaded: 1/1 memories\n"
    "\n"
    "## Contents:\n"
    "\n"
    "For full memory index, use: system://index\n"
    "For recent memories, use: system://recent\n"
    "<memory body bytes go here>\n"
    "\n"
    "---\n"
    "\n"
    f"{BOUNDARY_MARKER}\n"
    "# Generated: 2026-05-15T00:00\n"
    "# Showing: 0 most recent entries (requested: 5)\n"
    "\n"
    "(No memories found.)\n"
)


# ---------------------------------------------------------------------
# Default / opt-out behavior
# ---------------------------------------------------------------------


def test_default_env_unset_returns_unsplit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PROMPT_CACHE_SPLIT_ENV, raising=False)
    adapter = PromptCacheAdapter()

    result = adapter.split_boot_text(
        SAMPLE_BOOT_TEXT,
        {REQUIRED_HOST_FLAG: True},
    )

    assert result == {"unsplit": SAMPLE_BOOT_TEXT}
    assert "system_context" not in result
    assert "dynamic_context" not in result


def test_env_false_returns_unsplit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PROMPT_CACHE_SPLIT_ENV, "false")
    adapter = PromptCacheAdapter()

    result = adapter.split_boot_text(
        SAMPLE_BOOT_TEXT,
        {REQUIRED_HOST_FLAG: True},
    )

    assert result == {"unsplit": SAMPLE_BOOT_TEXT}


def test_host_flag_missing_returns_unsplit() -> None:
    adapter = PromptCacheAdapter(env_enabled=True)

    # Host caps present but flag missing.
    result = adapter.split_boot_text(SAMPLE_BOOT_TEXT, {})

    assert result == {"unsplit": SAMPLE_BOOT_TEXT}


def test_host_caps_none_returns_unsplit() -> None:
    adapter = PromptCacheAdapter(env_enabled=True)

    result = adapter.split_boot_text(SAMPLE_BOOT_TEXT, None)

    assert result == {"unsplit": SAMPLE_BOOT_TEXT}


def test_host_flag_false_returns_unsplit() -> None:
    adapter = PromptCacheAdapter(env_enabled=True)

    result = adapter.split_boot_text(
        SAMPLE_BOOT_TEXT,
        {REQUIRED_HOST_FLAG: False},
    )

    assert result == {"unsplit": SAMPLE_BOOT_TEXT}


# ---------------------------------------------------------------------
# Active path: env + host capability both true
# ---------------------------------------------------------------------


def test_active_split_separates_stable_and_dynamic() -> None:
    adapter = PromptCacheAdapter(env_enabled=True)

    result = adapter.split_boot_text(
        SAMPLE_BOOT_TEXT,
        {REQUIRED_HOST_FLAG: True},
    )

    assert "system_context" in result
    assert "dynamic_context" in result
    assert "unsplit" in result

    # The marker (and recent-memories body) must live entirely on the
    # dynamic side; the stable side must NOT contain the marker.
    assert BOUNDARY_MARKER not in result["system_context"]
    assert BOUNDARY_MARKER in result["dynamic_context"]

    # Stable side carries the core-memory header.
    assert "# Core Memories" in result["system_context"]
    assert "# Loaded: 1/1 memories" in result["system_context"]

    # Pass-through key still echoes the full text.
    assert result["unsplit"] == SAMPLE_BOOT_TEXT


def test_active_split_preserves_full_text_in_unsplit() -> None:
    """Even when activated, the ``unsplit`` value must match the input."""
    adapter = PromptCacheAdapter(env_enabled=True)

    result = adapter.split_boot_text(
        SAMPLE_BOOT_TEXT,
        {REQUIRED_HOST_FLAG: True},
    )

    assert result["unsplit"] == SAMPLE_BOOT_TEXT


def test_active_split_unsplit_remains_authoritative() -> None:
    """The contract only guarantees byte-exactness on ``unsplit``. The
    stable/dynamic halves may collapse blank-line padding by design
    (``rstrip`` on the stable side). Callers that need the byte-exact
    text MUST use ``result["unsplit"]``; the split halves are for
    prompt-cache surface routing, not for lossless reconstruction."""
    adapter = PromptCacheAdapter(env_enabled=True)

    result = adapter.split_boot_text(
        SAMPLE_BOOT_TEXT,
        {REQUIRED_HOST_FLAG: True},
    )

    # unsplit is the byte-exact authority
    assert result["unsplit"] == SAMPLE_BOOT_TEXT

    # The split halves together cover all non-padding bytes of the input;
    # the stable side ends cleanly (no dangling newline) and the dynamic
    # side begins at the marker line.
    assert result["system_context"].endswith("---") or not result[
        "system_context"
    ].endswith("\n")
    assert result["dynamic_context"].lstrip().startswith(BOUNDARY_MARKER)


# ---------------------------------------------------------------------
# Pathological / fallback inputs
# ---------------------------------------------------------------------


def test_active_but_marker_absent_returns_unsplit() -> None:
    adapter = PromptCacheAdapter(env_enabled=True)

    payload = "# Core Memories\n# Loaded: 0/0 memories\n(No core memories loaded yet.)\n"
    result = adapter.split_boot_text(payload, {REQUIRED_HOST_FLAG: True})

    assert result == {"unsplit": payload}


def test_empty_input_returns_unsplit_when_active() -> None:
    adapter = PromptCacheAdapter(env_enabled=True)

    result = adapter.split_boot_text("", {REQUIRED_HOST_FLAG: True})

    assert result == {"unsplit": ""}


def test_non_string_input_handled_defensively() -> None:
    adapter = PromptCacheAdapter(env_enabled=True)

    # ``None`` simulates a caller that did not get a string back.
    result = adapter.split_boot_text(None, {REQUIRED_HOST_FLAG: True})  # type: ignore[arg-type]

    assert result == {"unsplit": ""}


def test_marker_only_text_falls_back_to_unsplit() -> None:
    adapter = PromptCacheAdapter(env_enabled=True)

    payload = f"{BOUNDARY_MARKER}\n(no stable prefix)\n"
    result = adapter.split_boot_text(payload, {REQUIRED_HOST_FLAG: True})

    assert result == {"unsplit": payload}


# ---------------------------------------------------------------------
# Truthy coercion for the env flag
# ---------------------------------------------------------------------


@pytest.mark.parametrize("flag_value", ["1", "true", "TRUE", "yes", "on", "Y"])
def test_env_truthy_values_activate(
    monkeypatch: pytest.MonkeyPatch, flag_value: str
) -> None:
    monkeypatch.setenv(PROMPT_CACHE_SPLIT_ENV, flag_value)
    adapter = PromptCacheAdapter()

    result = adapter.split_boot_text(
        SAMPLE_BOOT_TEXT,
        {REQUIRED_HOST_FLAG: True},
    )

    assert "system_context" in result


@pytest.mark.parametrize("flag_value", ["0", "false", "", "no", "off", "garbage"])
def test_env_non_truthy_values_do_not_activate(
    monkeypatch: pytest.MonkeyPatch, flag_value: str
) -> None:
    monkeypatch.setenv(PROMPT_CACHE_SPLIT_ENV, flag_value)
    adapter = PromptCacheAdapter()

    result = adapter.split_boot_text(
        SAMPLE_BOOT_TEXT,
        {REQUIRED_HOST_FLAG: True},
    )

    assert result == {"unsplit": SAMPLE_BOOT_TEXT}


def test_c4_contract_byte_exact_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """C4 backstop: with the env unset, every input is passed through
    byte-for-byte regardless of the host capability declaration."""
    monkeypatch.delenv(PROMPT_CACHE_SPLIT_ENV, raising=False)
    adapter = PromptCacheAdapter()

    for caps in (
        None,
        {},
        {REQUIRED_HOST_FLAG: True},
        {REQUIRED_HOST_FLAG: False},
        {"can_strip_tool_artifacts": True},
    ):
        result = adapter.split_boot_text(SAMPLE_BOOT_TEXT, caps)
        assert result == {"unsplit": SAMPLE_BOOT_TEXT}, caps
