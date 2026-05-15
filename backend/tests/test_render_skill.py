"""Golden tests for ``scripts/render_skill.py``.

The renderer must produce a byte-for-byte match against the per-host
fixtures under ``backend/tests/fixtures/skill_golden/<host>.SKILL.md``. Any
intentional change to the template or per-host patches MUST regenerate the
fixtures in the same commit; otherwise the test fails with a unified-diff
hint so the reviewer can audit the drift before merging.

Round 3 Track B (Step B1): six hosts are pinned — claude, codex, cursor,
opencode, agent, gemini. Five share the canonical SKILL.md; gemini uses
the shorter ``variants/gemini`` template.
"""

from __future__ import annotations

import difflib
import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "render_skill.py"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "skill_golden"


# ---------------------------------------------------------------------------
# Module loader: we import the script by path so tests are hermetic and do not
# require the script directory to be on sys.path.
# ---------------------------------------------------------------------------


def _load_renderer():
    spec = importlib.util.spec_from_file_location("render_skill", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


renderer = _load_renderer()


# ---------------------------------------------------------------------------
# Golden tests — one parametrized case per supported host.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("host", renderer.SUPPORTED_HOSTS)
def test_render_for_host_matches_golden_fixture(host: str) -> None:
    fixture_path = FIXTURE_DIR / f"{host}.SKILL.md"
    assert fixture_path.is_file(), (
        f"Missing golden fixture for host={host!r}. "
        f"Regenerate via `python scripts/render_skill.py --host {host} "
        f"--output {fixture_path.relative_to(REPO_ROOT)}` after auditing the diff."
    )

    expected = fixture_path.read_text(encoding="utf-8")
    actual = renderer.render_for_host(host)

    if actual != expected:
        diff = "\n".join(
            difflib.unified_diff(
                expected.splitlines(),
                actual.splitlines(),
                fromfile=f"fixtures/skill_golden/{host}.SKILL.md",
                tofile=f"render_for_host({host!r})",
                lineterm="",
            )
        )
        pytest.fail(
            "Skill golden diff is non-zero for host="
            f"{host!r}.\n{diff or '(no line diff; whitespace/encoding mismatch)'}"
        )


def test_supported_hosts_count_is_six() -> None:
    # Lock the host roster so adding/removing one fails this test alongside
    # the per-host parametrization above.
    assert len(renderer.SUPPORTED_HOSTS) == 6
    assert set(renderer.SUPPORTED_HOSTS) == {
        "claude",
        "codex",
        "cursor",
        "opencode",
        "agent",
        "gemini",
    }


# ---------------------------------------------------------------------------
# Negative / API tests.
# ---------------------------------------------------------------------------


def test_render_for_host_rejects_unknown_host() -> None:
    with pytest.raises(ValueError) as excinfo:
        renderer.render_for_host("notarealhost")
    assert "Unknown host" in str(excinfo.value)


def test_render_template_substitutes_known_variables() -> None:
    template = "ns={{ MCP_NS }} ref={{ TRIGGER_REF }}"
    out = renderer.render_template(
        template,
        {
            "MCP_NS": "mcp__memory-palace__",
            "TRIGGER_REF": "docs/skills/memory-palace/references/trigger-samples.md",
        },
    )
    assert "ns=mcp__memory-palace__" in out
    assert "trigger-samples.md" in out


def test_render_template_raises_on_unknown_variable() -> None:
    with pytest.raises(KeyError) as excinfo:
        renderer.render_template("hello {{ NOPE }}", {})
    assert "NOPE" in str(excinfo.value)


def test_render_for_host_writes_atomically(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "SKILL.md"
    written = renderer.render_to_path("claude", target)
    assert written == target
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == renderer.render_for_host("claude")
    # The atomic helper must clean up its temp swap file.
    assert not (tmp_path / "nested" / "SKILL.md.tmp").exists()


def test_render_all_writes_six_files(tmp_path: Path, monkeypatch) -> None:
    # Redirect every host's output to a tmp_path mirror so the test does not
    # rewrite the repository workspace mirrors as a side effect.
    redirected = {}
    for host, patch in renderer.HOST_PATCHES.items():
        new_output = tmp_path / host / "SKILL.md"
        redirected[host] = renderer.HostPatch(
            source=patch.source,
            output=new_output,
            variables=patch.variables,
        )
    monkeypatch.setattr(renderer, "HOST_PATCHES", redirected)

    written = renderer.render_all()
    assert set(written.keys()) == set(renderer.SUPPORTED_HOSTS)
    for host, path in written.items():
        assert path.is_file(), f"Missing rendered output for {host!r}"
        body = path.read_text(encoding="utf-8")
        assert body.startswith("---\n"), f"{host!r}: rendered output lost frontmatter"


def test_cli_main_reports_unknown_host(capsys) -> None:
    rc = renderer.main(["--host", "nonsense"])
    assert rc != 0
    err = capsys.readouterr().err
    # argparse rejects the bad choice before our code runs.
    assert "invalid choice" in err or "unknown" in err.lower()


def test_cli_main_renders_to_stdout(capsys) -> None:
    rc = renderer.main(["--host", "gemini"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "name: memory-palace" in out
    # Gemini variant is shorter so it must NOT contain the allowed-tools key.
    assert "allowed-tools" not in out


def test_cli_main_renders_to_file(tmp_path: Path) -> None:
    target = tmp_path / "out.md"
    rc = renderer.main(["--host", "claude", "--output", str(target)])
    assert rc == 0
    assert target.read_text(encoding="utf-8").startswith("---\n")
