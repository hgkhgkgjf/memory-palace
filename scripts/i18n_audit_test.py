"""Pytest wrapper around :mod:`i18n_audit`.

This wrapper asserts that the frontend ships locale parity between
``en.js`` and ``zh-CN.js`` and that every translation key referenced by
production code (i.e. excluding test fixtures) is defined in both locales.

It also surfaces the inventory of stale keys as an *informational* xfail so
the team can prune the translation files when convenient without blocking
the gate.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


_THIS_DIR = Path(__file__).resolve().parent
_AUDIT_PATH = _THIS_DIR / "i18n_audit.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location(
        "i18n_audit_loaded",
        _AUDIT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"Could not load i18n_audit module at {_AUDIT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("i18n_audit_loaded", module)
    spec.loader.exec_module(module)
    return module


audit = _load_audit_module()


def _repo_root() -> Path:
    return _THIS_DIR.parent


@pytest.fixture(scope="module")
def audit_summary() -> dict:
    repo_root = _repo_root()
    result = audit.run_audit(
        en_path=repo_root / "frontend/src/locales/en.js",
        zh_path=repo_root / "frontend/src/locales/zh-CN.js",
        source_roots=[repo_root / "frontend/src"],
        include_tests=False,
    )
    summary = audit.summarise(result)
    summary["occurrences_count"] = len(result.occurrences)
    return summary


def test_no_keys_missing_in_en(audit_summary: dict) -> None:
    missing = audit_summary["missing_in_en"]
    assert missing == [], (
        "Translation keys used in code but missing from en.js:\n"
        + json.dumps(missing, indent=2)
    )


def test_no_keys_missing_in_zh(audit_summary: dict) -> None:
    missing = audit_summary["missing_in_zh"]
    assert missing == [], (
        "Translation keys used in code but missing from zh-CN.js:\n"
        + json.dumps(missing, indent=2)
    )


def test_locale_trees_are_parallel(audit_summary: dict) -> None:
    only_en = audit_summary["only_in_en"]
    only_zh = audit_summary["only_in_zh"]
    assert only_en == [], (
        "Keys defined in en.js but missing from zh-CN.js:\n"
        + json.dumps(only_en, indent=2)
    )
    assert only_zh == [], (
        "Keys defined in zh-CN.js but missing from en.js:\n"
        + json.dumps(only_zh, indent=2)
    )


def test_stale_keys_are_tracked(audit_summary: dict) -> None:
    """Informational: stale keys exist but do not block the gate today."""
    stale = audit_summary["stale_keys"]
    if stale:
        pytest.xfail(f"{len(stale)} stale translation keys (informational)")


def test_summary_shape(audit_summary: dict) -> None:
    totals = audit_summary["totals"]
    for key in (
        "en_keys",
        "zh_keys",
        "used_keys",
        "missing_in_en",
        "missing_in_zh",
        "stale_keys",
        "only_in_en",
        "only_in_zh",
    ):
        assert key in totals, f"missing total: {key}"
        assert isinstance(totals[key], int), f"total {key} must be int"


def test_runs_under_main_entrypoint(tmp_path: Path) -> None:
    output = tmp_path / "i18n_report.json"
    rc = audit.main(
        [
            "--repo-root",
            str(_repo_root()),
            "--json",
            "--output",
            str(output),
            "--allow-missing",
        ]
    )
    assert rc == 0
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "totals" in payload
    assert "missing_in_en" in payload
    assert "missing_in_zh" in payload
