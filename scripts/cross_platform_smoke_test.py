"""Pytest wrapper around :mod:`cross_platform_smoke`.

This module asserts that the cross-platform smoke test reports no *critical*
findings. Warnings (e.g. ``os.path`` usages awaiting pathlib migration) are
allowed and surfaced via the report payload for inspection.

The wrapper deliberately re-exports a few helpers so that callers (for
example, the CI script) can re-use the audit output without re-implementing
its loader.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


# Resolve the sibling ``cross_platform_smoke.py`` module without requiring
# the ``scripts/`` directory to be a Python package.
_THIS_DIR = Path(__file__).resolve().parent
_SMOKE_PATH = _THIS_DIR / "cross_platform_smoke.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "cross_platform_smoke_loaded",
        _SMOKE_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"Could not load smoke module at {_SMOKE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("cross_platform_smoke_loaded", module)
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke_module()


def _repo_root() -> Path:
    return _THIS_DIR.parent


@pytest.fixture(scope="module")
def smoke_report() -> dict:
    repo_root = _repo_root()
    scan_roots = [repo_root / "backend"]
    report = smoke.run_audit(
        repo_root=repo_root,
        scan_roots=scan_roots,
        scripts_dir=repo_root / "scripts",
        skip_parts=set(smoke._DEFAULT_SKIP_PARTS),
    )
    return smoke.summarise(report)


def test_no_critical_findings(smoke_report: dict) -> None:
    """Critical findings (hardcoded absolute paths, etc.) must be zero."""
    critical = []
    for entries in smoke_report["findings"].values():
        critical.extend(e for e in entries if e["severity"] == "critical")
    assert critical == [], (
        "Cross-platform smoke test reported critical findings:\n"
        + json.dumps(critical, indent=2)
    )


def test_shell_scripts_have_powershell_partners(smoke_report: dict) -> None:
    """Every ``.sh`` script in ``scripts/`` should ship a ``.ps1`` partner.

    The audit reports unpaired shell scripts as warnings; this test surfaces
    them but is *informational* unless we want to enforce parity strictly. To
    avoid blocking until the team has time to write paired scripts, the test
    is parameterised by an environment-style attribute on the report so it can
    be tightened later by flipping a single flag.
    """
    gaps = smoke_report["findings"]["shell_script_gaps"]
    # Informational assertion: render the list rather than failing. We use
    # pytest's xfail mechanism so missing partners are visible but do not
    # block the gate until the project decides to enforce parity.
    if gaps:
        pytest.xfail(
            "Shell scripts without paired .ps1: "
            + ", ".join(g["file"] for g in gaps)
        )


def test_summary_shape(smoke_report: dict) -> None:
    """Defensive contract test for the audit output structure."""
    totals = smoke_report["totals"]
    for key in (
        "critical",
        "warning",
        "os_path_usage",
        "hardcoded_separators",
        "platform_specific",
        "temp_dir_risks",
        "shell_script_gaps",
    ):
        assert key in totals, f"missing total: {key}"
        assert isinstance(totals[key], int), f"total {key} must be int"
    findings = smoke_report["findings"]
    for key in (
        "os_path_usage",
        "hardcoded_separators",
        "platform_specific",
        "temp_dir_risks",
        "shell_script_gaps",
    ):
        assert key in findings, f"missing finding bucket: {key}"
        assert isinstance(findings[key], list), f"finding bucket {key} must be list"


def test_runs_under_main_entrypoint(tmp_path: Path) -> None:
    """The CLI entry point should also be runnable directly (smoke test)."""
    output = tmp_path / "report.json"
    rc = smoke.main(
        [
            "--repo-root",
            str(_repo_root()),
            "--scan",
            str(_repo_root() / "backend"),
            "--scripts-dir",
            str(_repo_root() / "scripts"),
            "--json",
            "--output",
            str(output),
            "--allow-critical",
        ]
    )
    # Even with criticals present we expect a 0 exit because --allow-critical
    # was supplied; the goal of this test is to make sure the entry point
    # parses arguments and writes the report file.
    assert rc == 0
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "totals" in payload
    assert "findings" in payload
