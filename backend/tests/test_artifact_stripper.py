"""Tests for ``backend.security.artifact_stripper.ArtifactStripper``.

The stripper is opt-in (Round 3 Track A constraint C4). These tests
exercise both the default pass-through behavior and the activated
strip path, and assert the contract:

* Default ``strip(content, caps)`` returns ``content`` byte-for-byte
  unless BOTH env flag and host capability are active.
* When active, the stripper removes only the three documented
  injection wrappers, leaving everything else untouched.
"""

from __future__ import annotations

import pytest

from security.artifact_stripper import (
    ARTIFACT_PATTERNS,
    ARTIFACT_STRIPPING_ENV,
    REQUIRED_HOST_FLAG,
    ArtifactStripper,
)


# ---------------------------------------------------------------------
# Default / opt-out behavior
# ---------------------------------------------------------------------


def test_default_env_unset_returns_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ARTIFACT_STRIPPING_ENV, raising=False)
    stripper = ArtifactStripper()

    payload = "<relevant-memories>injected</relevant-memories>plain"
    result = stripper.strip(payload, {REQUIRED_HOST_FLAG: True})

    assert result == payload


def test_env_false_returns_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ARTIFACT_STRIPPING_ENV, "false")
    stripper = ArtifactStripper()

    payload = "<relevant-memories>injected</relevant-memories>plain"
    result = stripper.strip(payload, {REQUIRED_HOST_FLAG: True})

    assert result == payload


def test_host_flag_missing_returns_unchanged() -> None:
    stripper = ArtifactStripper(env_enabled=True)

    payload = "<relevant-memories>injected</relevant-memories>plain"
    result = stripper.strip(payload, {})

    assert result == payload


def test_host_caps_none_returns_unchanged() -> None:
    stripper = ArtifactStripper(env_enabled=True)

    payload = "<relevant-memories>injected</relevant-memories>plain"
    result = stripper.strip(payload, None)

    assert result == payload


def test_host_flag_false_returns_unchanged() -> None:
    stripper = ArtifactStripper(env_enabled=True)

    payload = "<relevant-memories>injected</relevant-memories>plain"
    result = stripper.strip(payload, {REQUIRED_HOST_FLAG: False})

    assert result == payload


# ---------------------------------------------------------------------
# Active stripping behavior
# ---------------------------------------------------------------------


def test_strip_relevant_memories_wrapper() -> None:
    stripper = ArtifactStripper(env_enabled=True)

    payload = "before<relevant-memories>secret memory</relevant-memories>after"
    result = stripper.strip(payload, {REQUIRED_HOST_FLAG: True})

    assert result == "beforeafter"


def test_strip_memory_context_wrapper() -> None:
    stripper = ArtifactStripper(env_enabled=True)

    payload = "before<memory-context>injected</memory-context>after"
    result = stripper.strip(payload, {REQUIRED_HOST_FLAG: True})

    assert result == "beforeafter"


def test_strip_html_comment_fence() -> None:
    stripper = ArtifactStripper(env_enabled=True)

    payload = (
        "before<!-- memory-palace-injected -->body lines\n"
        "more body<!-- /memory-palace-injected -->after"
    )
    result = stripper.strip(payload, {REQUIRED_HOST_FLAG: True})

    assert result == "beforeafter"


def test_strip_multiline_wrapper() -> None:
    stripper = ArtifactStripper(env_enabled=True)

    payload = (
        "preamble\n"
        "<relevant-memories>\n"
        "line one\n"
        "line two\n"
        "</relevant-memories>\n"
        "trailer\n"
    )
    result = stripper.strip(payload, {REQUIRED_HOST_FLAG: True})

    assert "<relevant-memories>" not in result
    assert "</relevant-memories>" not in result
    assert "line one" not in result
    assert "line two" not in result
    assert "preamble" in result
    assert "trailer" in result


def test_strip_multiple_wrappers_in_one_pass() -> None:
    stripper = ArtifactStripper(env_enabled=True)

    payload = (
        "a"
        "<relevant-memories>one</relevant-memories>"
        "b"
        "<memory-context>two</memory-context>"
        "c"
        "<!-- memory-palace-injected -->three<!-- /memory-palace-injected -->"
        "d"
    )
    result = stripper.strip(payload, {REQUIRED_HOST_FLAG: True})

    assert result == "abcd"


def test_strip_is_case_insensitive_on_tags() -> None:
    stripper = ArtifactStripper(env_enabled=True)

    payload = "before<Relevant-Memories>x</RELEVANT-MEMORIES>after"
    result = stripper.strip(payload, {REQUIRED_HOST_FLAG: True})

    assert result == "beforeafter"


def test_strip_leaves_unrelated_xml_tags_intact() -> None:
    stripper = ArtifactStripper(env_enabled=True)

    payload = "<note>keep me</note><relevant-memories>drop</relevant-memories>"
    result = stripper.strip(payload, {REQUIRED_HOST_FLAG: True})

    assert "<note>keep me</note>" in result
    assert "relevant-memories" not in result


def test_strip_leaves_partial_tags_intact() -> None:
    """Bare opening tags without closing tags must NOT be stripped — the
    patterns require a balanced pair."""
    stripper = ArtifactStripper(env_enabled=True)

    payload = "before<relevant-memories>orphan opener\nno closer here"
    result = stripper.strip(payload, {REQUIRED_HOST_FLAG: True})

    assert result == payload


# ---------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------


def test_empty_string_returns_empty() -> None:
    stripper = ArtifactStripper(env_enabled=True)

    assert stripper.strip("", {REQUIRED_HOST_FLAG: True}) == ""


def test_non_string_input_returns_unchanged() -> None:
    stripper = ArtifactStripper(env_enabled=True)

    assert stripper.strip(None, {REQUIRED_HOST_FLAG: True}) is None  # type: ignore[arg-type]
    assert stripper.strip(123, {REQUIRED_HOST_FLAG: True}) == 123  # type: ignore[arg-type]


def test_no_wrappers_present_returns_unchanged() -> None:
    stripper = ArtifactStripper(env_enabled=True)

    payload = "plain content without any injection wrappers."
    result = stripper.strip(payload, {REQUIRED_HOST_FLAG: True})

    assert result == payload


def test_pattern_set_has_expected_size() -> None:
    """Locks the documented pattern count. Adding a new pattern requires
    intentional contract change + RFC update."""
    assert len(ARTIFACT_PATTERNS) == 3


# ---------------------------------------------------------------------
# Truthy coercion for the env flag
# ---------------------------------------------------------------------


@pytest.mark.parametrize("flag_value", ["1", "true", "TRUE", "yes", "on", "Y"])
def test_env_truthy_values_activate(
    monkeypatch: pytest.MonkeyPatch, flag_value: str
) -> None:
    monkeypatch.setenv(ARTIFACT_STRIPPING_ENV, flag_value)
    stripper = ArtifactStripper()

    payload = "<relevant-memories>x</relevant-memories>tail"
    result = stripper.strip(payload, {REQUIRED_HOST_FLAG: True})

    assert result == "tail"


@pytest.mark.parametrize("flag_value", ["0", "false", "", "no", "off", "garbage"])
def test_env_non_truthy_values_do_not_activate(
    monkeypatch: pytest.MonkeyPatch, flag_value: str
) -> None:
    monkeypatch.setenv(ARTIFACT_STRIPPING_ENV, flag_value)
    stripper = ArtifactStripper()

    payload = "<relevant-memories>x</relevant-memories>tail"
    result = stripper.strip(payload, {REQUIRED_HOST_FLAG: True})

    assert result == payload


def test_c4_contract_byte_exact_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """C4 backstop: with the env unset, every input is passed through
    byte-for-byte regardless of the host capability declaration."""
    monkeypatch.delenv(ARTIFACT_STRIPPING_ENV, raising=False)
    stripper = ArtifactStripper()

    payload = (
        "boot text\n"
        "<relevant-memories>noise</relevant-memories>\n"
        "<memory-context>more noise</memory-context>\n"
    )
    for caps in (
        None,
        {},
        {REQUIRED_HOST_FLAG: True},
        {REQUIRED_HOST_FLAG: False},
        {"can_set_system_context": True},
    ):
        assert stripper.strip(payload, caps) == payload, caps
