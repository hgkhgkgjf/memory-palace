from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys

import pytest


def _load_harness():
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "evaluate_memory_palace_mcp_e2e.py"
    spec = importlib.util.spec_from_file_location("evaluate_memory_palace_mcp_e2e", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _set_windows_posix_shell_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key in ("MSYSTEM", "CYGWIN", "WSL_DISTRO_NAME", "WSL_INTEROP", "OSTYPE"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


@pytest.mark.skipif(
    os.name == "nt",
    reason="Live stdio subprocess E2E is covered on POSIX; Windows path selection is unit-tested.",
)
def test_live_mcp_stdio_e2e_suite_passes() -> None:
    harness = _load_harness()
    results, stderr_output = harness.run_suite_sync()

    failing = [item for item in results if item.status == "FAIL"]
    assert not failing, [(item.name, item.summary, item.details) for item in failing]
    assert "bound to a different event loop" not in stderr_output


def test_repo_local_stdio_command_uses_python_wrapper_on_windows(
    monkeypatch, tmp_path: Path
) -> None:
    harness = _load_harness()
    project_root = tmp_path / "Memory-Palace"
    backend_root = project_root / "backend"
    preferred_python = backend_root / ".venv" / "Scripts" / "python.exe"
    preferred_python.parent.mkdir(parents=True, exist_ok=True)
    preferred_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(harness, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(harness, "BACKEND_ROOT", backend_root)
    monkeypatch.setattr(harness.os, "name", "nt")
    monkeypatch.setattr(harness.sys, "executable", r"C:\Python313\python.exe")
    _set_windows_posix_shell_env(monkeypatch, {})

    command, args = harness._repo_local_stdio_command()

    assert command == str(preferred_python)
    assert args == [str(backend_root / "mcp_wrapper.py")]


def test_repo_local_stdio_command_fails_closed_without_backend_venv_on_windows(
    monkeypatch, tmp_path: Path
) -> None:
    harness = _load_harness()
    project_root = tmp_path / "Memory-Palace-no-venv"
    backend_root = project_root / "backend"
    backend_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(harness, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(harness, "BACKEND_ROOT", backend_root)
    monkeypatch.setattr(harness.os, "name", "nt")
    monkeypatch.setattr(harness.sys, "executable", r"C:\Python313\python.exe")
    _set_windows_posix_shell_env(monkeypatch, {})

    with pytest.raises(SystemExit, match="Missing backend virtualenv python"):
        harness._repo_local_stdio_command()


@pytest.mark.parametrize(
    ("env", "label"),
    [
        ({"MSYSTEM": "MINGW64"}, "git-bash"),
        ({"CYGWIN": "1"}, "cygwin"),
        ({"WSL_DISTRO_NAME": "Ubuntu"}, "wsl-distro"),
        ({"WSL_INTEROP": r"\\wsl$\\Ubuntu\\interop"}, "wsl-interop"),
        ({"OSTYPE": "msys"}, "msys-ostype"),
        ({"OSTYPE": "cygwin"}, "cygwin-ostype"),
    ],
)
def test_repo_local_stdio_command_keeps_bash_wrapper_for_windows_posix_shell_hosts(
    monkeypatch, tmp_path: Path, env: dict[str, str], label: str
) -> None:
    harness = _load_harness()
    project_root = tmp_path / f"Memory-Palace-{label}"
    backend_root = project_root / "backend"

    monkeypatch.setattr(harness, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(harness, "BACKEND_ROOT", backend_root)
    monkeypatch.setattr(harness.os, "name", "nt")
    _set_windows_posix_shell_env(monkeypatch, env)

    command, args = harness._repo_local_stdio_command()

    assert command == "bash"
    assert args == [str(project_root / "scripts" / "run_memory_palace_mcp_stdio.sh")]


def test_resolve_report_path_supports_relative_override_under_temp_root(
    monkeypatch, tmp_path: Path
) -> None:
    harness = _load_harness()
    monkeypatch.setenv("MEMORY_PALACE_MCP_E2E_REPORT_PATH", "tmp/custom-e2e-report.md")
    monkeypatch.setattr(harness, "REPORT_OVERRIDE_ROOT", tmp_path / "tmp-root")

    resolved = harness._resolve_report_path()

    assert resolved == tmp_path / "tmp-root" / "tmp" / "custom-e2e-report.md"


def test_build_markdown_redacts_sensitive_details() -> None:
    harness = _load_harness()
    report = harness.build_markdown(
        [
            harness.StepResult(
                name="demo",
                status="FAIL",
                summary="failed",
                details='DATABASE_URL=sqlite+aiosqlite:////Users/test/demo.db MCP_API_KEY=secret-token',
            )
        ],
        "stderr from /Users/test/project",
    )

    assert "secret-token" not in report
    assert "/Users/test/project" not in report
    assert "sqlite+aiosqlite" not in report
    assert "<redacted>" in report


def test_write_private_report_uses_private_permissions(tmp_path: Path) -> None:
    harness = _load_harness()
    report_path = tmp_path / "tmp-root" / "mcp-e2e.md"

    harness._write_private_report(report_path, "secret")

    assert report_path.read_text(encoding="utf-8") == "secret"
    if os.name != "nt":
        assert report_path.stat().st_mode & 0o777 == 0o600


def test_maybe_reexec_with_backend_python_sets_guard_env(monkeypatch, tmp_path: Path) -> None:
    harness = _load_harness()
    backend_python = tmp_path / "backend-python"
    backend_python.write_text("", encoding="utf-8")

    monkeypatch.delenv(harness._REEXEC_GUARD_ENV, raising=False)
    monkeypatch.setattr(harness, "_resolve_backend_python", lambda: backend_python)
    monkeypatch.setattr(harness.sys, "executable", str(tmp_path / "system-python"))

    captured = {}

    def _fake_execve(path, argv, env):
        captured["path"] = path
        captured["argv"] = argv
        captured["env"] = env
        raise RuntimeError("execve-called")

    monkeypatch.setattr(harness.os, "execve", _fake_execve)

    with pytest.raises(RuntimeError, match="execve-called"):
        harness._maybe_reexec_with_backend_python()

    assert captured["path"] == str(backend_python)
    assert captured["argv"][0] == str(backend_python)
    assert captured["env"][harness._REEXEC_GUARD_ENV] == "1"


def test_maybe_reexec_with_backend_python_stops_after_guard_is_set(
    monkeypatch, tmp_path: Path
) -> None:
    harness = _load_harness()
    backend_python = tmp_path / "backend-python"
    backend_python.write_text("", encoding="utf-8")

    monkeypatch.setenv(harness._REEXEC_GUARD_ENV, "1")
    monkeypatch.setattr(harness, "_resolve_backend_python", lambda: backend_python)
    monkeypatch.setattr(harness.sys, "executable", str(tmp_path / "system-python"))

    exec_calls = []
    monkeypatch.setattr(
        harness.os,
        "execve",
        lambda *args: exec_calls.append(args),
    )

    harness._maybe_reexec_with_backend_python()

    assert exec_calls == []


def test_python_wrapper_live_stdio_smoke() -> None:
    harness = _load_harness()
    backend_python = harness._resolve_backend_python()
    if backend_python is None:
        raise AssertionError("backend virtualenv python is required for python-wrapper smoke")

    results, stderr_output = harness.run_suite_sync(
        repo_local_command=(
            str(backend_python),
            [str(harness.BACKEND_ROOT / "mcp_wrapper.py")],
        )
    )

    failing = [item for item in results if item.status == "FAIL"]
    assert not failing, [(item.name, item.summary, item.details) for item in failing]
    assert "tool_inventory" in {item.name for item in results}
    assert "bound to a different event loop" not in stderr_output
