import importlib.util
import json
import os
import sys
from pathlib import Path


def _load_skill_eval_module():
    project_root = Path(__file__).resolve().parents[2]
    script_path = project_root / "scripts" / "evaluate_memory_palace_skill.py"
    spec = importlib.util.spec_from_file_location("evaluate_memory_palace_skill", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_install_skill_module():
    project_root = Path(__file__).resolve().parents[2]
    script_path = project_root / "scripts" / "install_skill.py"
    spec = importlib.util.spec_from_file_location("install_skill", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_sync_skill_module():
    project_root = Path(__file__).resolve().parents[2]
    script_path = project_root / "scripts" / "sync_memory_palace_skill.py"
    spec = importlib.util.spec_from_file_location("sync_memory_palace_skill", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _canonical_skill_text(body: str = "Canonical skill body.\n") -> str:
    return (
        "---\n"
        "name: memory-palace\n"
        "description: Canonical memory palace skill.\n"
        "---\n"
        f"{body}"
    )


def test_check_gate_syntax_skips_when_workspace_gate_missing(monkeypatch, tmp_path):
    module = _load_skill_eval_module()
    repo_root = tmp_path / "Memory-Palace"
    repo_root.mkdir()
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)

    result = module.check_gate_syntax()

    assert result.status == "SKIP"
    assert "run_post_change_checks.sh" in result.summary
    assert "公开仓校验范围" in result.summary
    assert "跳过" in result.summary


def test_check_gate_syntax_accepts_parent_workspace_gate(monkeypatch, tmp_path):
    module = _load_skill_eval_module()
    repo_root = tmp_path / "Memory-Palace"
    repo_root.mkdir()
    workspace_gate = tmp_path / "new" / "run_post_change_checks.sh"
    workspace_gate.parent.mkdir()
    workspace_gate.write_text("#!/usr/bin/env bash\nset -euo pipefail\necho ok\n", encoding="utf-8")

    monkeypatch.setattr(module, "REPO_ROOT", repo_root)

    result = module.check_gate_syntax()

    assert result.status == "PASS"
    assert "语法通过" in result.summary


def test_check_sync_script_uses_current_python_interpreter(monkeypatch):
    module = _load_skill_eval_module()
    recorded = {}

    def fake_run_command(cmd, *, cwd, input_text=None, timeout=120):
        recorded["cmd"] = cmd
        recorded["cwd"] = cwd

        class _Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return _Result()

    monkeypatch.setattr(module, "run_command", fake_run_command)

    result = module.check_sync_script()

    assert result.status == "PASS"
    assert recorded["cmd"][0] == sys.executable
    assert recorded["cmd"][1:] == ["-B", str(module.PROJECT_ROOT / "scripts" / "sync_memory_palace_skill.py"), "--check"]


def test_python_command_prefers_repo_backend_python_on_windows(monkeypatch, tmp_path):
    module = _load_skill_eval_module()
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir(parents=True)
    preferred_python = backend_dir / ".venv" / "Scripts" / "python.exe"
    preferred_python.parent.mkdir(parents=True)
    preferred_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "BACKEND_DIR", backend_dir)
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module.sys, "executable", r"C:\Python313\python.exe")

    assert module._python_command() == str(preferred_python)


def test_sanitize_report_text_redacts_env_and_paths() -> None:
    module = _load_skill_eval_module()
    raw = (
        'env={"DATABASE_URL":"sqlite+aiosqlite:////Users/test/demo.db",'
        '"MCP_API_KEY":"super-secret-token"}\n'
        'command=/Users/test/project/backend/mcp_server.py\n'
        'session_id=mcp_ctx_client_ServerSession-123'
    )

    sanitized = module._sanitize_report_text(raw)

    assert "super-secret-token" not in sanitized
    assert "/Users/test/project" not in sanitized
    assert "sqlite+aiosqlite" not in sanitized
    assert "mcp_ctx_client_ServerSession-123" not in sanitized
    assert "<redacted>" in sanitized


def test_write_private_report_uses_private_permissions(monkeypatch, tmp_path):
    module = _load_skill_eval_module()
    report_path = tmp_path / "reports" / "skill-report.md"

    module._write_private_report(report_path, "secret")

    assert report_path.read_text(encoding="utf-8") == "secret"
    if os.name != "nt":
        assert report_path.stat().st_mode & 0o777 == 0o600


def test_smoke_gemini_live_suite_is_opt_in_by_default(monkeypatch):
    monkeypatch.delenv("MEMORY_PALACE_ENABLE_GEMINI_LIVE", raising=False)
    monkeypatch.delenv("MEMORY_PALACE_SKIP_GEMINI_LIVE", raising=False)
    module = _load_skill_eval_module()

    result = module.smoke_gemini_live_suite()

    assert result.status == "SKIP"
    assert "MEMORY_PALACE_ENABLE_GEMINI_LIVE=1" in result.summary


def test_smoke_gemini_treats_auth_prompt_as_partial(monkeypatch):
    module = _load_skill_eval_module()

    monkeypatch.setattr(module, "_cli_executable", lambda name: "gemini" if name == "gemini" else None)
    monkeypatch.setattr(
        module,
        "run_command_capture",
        lambda *_args, **_kwargs: module.CommandCapture(
            returncode=0,
            stdout="memory-palace [Enabled]",
            stderr="",
            timed_out=False,
        ),
    )
    monkeypatch.setattr(
        module,
        "run_gemini_prompt",
        lambda *_args, **_kwargs: module.CommandCapture(
            returncode=1,
            stdout="",
            stderr="Opening authentication page in your browser. Do you want to continue? [Y/n]:",
            timed_out=False,
        ),
    )

    result = module.smoke_gemini()

    assert result.status == "PARTIAL"
    assert "登录/鉴权" in result.summary


def test_install_skill_reports_invalid_json_with_actionable_message(tmp_path):
    module = _load_install_skill_module()
    broken = tmp_path / "settings.json"
    broken.write_text('{"mcpServers": ', encoding="utf-8")

    try:
        module.read_json_file(broken)
        raise AssertionError("expected SystemExit for invalid JSON")
    except SystemExit as exc:
        message = str(exc)

    assert str(broken) in message
    assert "Invalid JSON" in message
    assert "line" in message
    assert "column" in message


def test_install_skill_write_json_file_creates_backup_before_overwrite(tmp_path):
    module = _load_install_skill_module()
    config_path = tmp_path / "settings.json"
    original_payload = {"mcpServers": {"old": {"command": "bash"}}}
    config_path.write_text(json.dumps(original_payload), encoding="utf-8")

    module.write_json_file(
        config_path,
        {"mcpServers": {"memory-palace": {"command": "bash"}}},
        dry_run=False,
    )

    backup_path = config_path.with_name("settings.json.bak")
    assert backup_path.is_file()
    assert json.loads(backup_path.read_text(encoding="utf-8")) == original_payload


def test_install_skill_write_text_file_creates_backup_before_overwrite(tmp_path):
    module = _load_install_skill_module()
    config_path = tmp_path / "config.toml"
    config_path.write_text('[mcp_servers.old]\ncommand = "bash"\n', encoding="utf-8")

    module.write_text_file(
        config_path,
        '[mcp_servers.memory-palace]\ncommand = "bash"\n',
        dry_run=False,
    )

    backup_path = config_path.with_name("config.toml.bak")
    assert backup_path.is_file()
    assert '[mcp_servers.old]' in backup_path.read_text(encoding="utf-8")


def test_sync_skill_overwrites_required_files_without_deleting_extra_files(
    monkeypatch, tmp_path
):
    module = _load_sync_skill_module()

    repo_root = tmp_path / "Memory-Palace"
    canonical_dir = repo_root / "docs" / "skills" / "memory-palace"
    (canonical_dir / "references").mkdir(parents=True, exist_ok=True)
    (canonical_dir / "agents").mkdir(parents=True, exist_ok=True)
    (canonical_dir / "variants" / "gemini").mkdir(parents=True, exist_ok=True)
    (canonical_dir / "SKILL.md").write_text(
        _canonical_skill_text("canonical-skill\n"), encoding="utf-8"
    )
    (canonical_dir / "references" / "mcp-workflow.md").write_text(
        "canonical-workflow\n", encoding="utf-8"
    )
    (canonical_dir / "references" / "trigger-samples.md").write_text(
        "canonical-trigger\n", encoding="utf-8"
    )
    (canonical_dir / "agents" / "openai.yaml").write_text(
        "canonical-openai\n", encoding="utf-8"
    )
    (canonical_dir / "variants" / "gemini" / "SKILL.md").write_text(
        _canonical_skill_text("canonical-gemini\n"), encoding="utf-8"
    )

    mirror_dir = repo_root / ".codex" / "skills" / "memory-palace"
    mirror_dir.mkdir(parents=True, exist_ok=True)
    (mirror_dir / "SKILL.md").write_text(
        _canonical_skill_text("old-skill\n"), encoding="utf-8"
    )
    (mirror_dir / "legacy-note.md").write_text("keep-me\n", encoding="utf-8")

    gemini_dir = repo_root / ".gemini" / "skills" / "memory-palace"
    gemini_dir.mkdir(parents=True, exist_ok=True)
    (gemini_dir / "SKILL.md").write_text(
        _canonical_skill_text("old-gemini\n"), encoding="utf-8"
    )
    (gemini_dir / "legacy-note.md").write_text("keep-me\n", encoding="utf-8")

    monkeypatch.setattr(module, "REPO_ROOT", repo_root)
    monkeypatch.setattr(module, "CANONICAL_DIR", canonical_dir)
    monkeypatch.setattr(module, "GEMINI_VARIANT_FILE", canonical_dir / "variants" / "gemini" / "SKILL.md")
    monkeypatch.setattr(module, "BUNDLE_MIRROR_DIRS", [mirror_dir])
    monkeypatch.setattr(module, "GEMINI_WORKSPACE_DIR", gemini_dir)

    assert module.run_sync() == 0
    assert (mirror_dir / "SKILL.md").read_text(encoding="utf-8") == _canonical_skill_text(
        "canonical-skill\n"
    )
    assert (mirror_dir / "legacy-note.md").read_text(encoding="utf-8") == "keep-me\n"
    assert (gemini_dir / "SKILL.md").read_text(encoding="utf-8") == _canonical_skill_text(
        "canonical-gemini\n"
    )
    assert (gemini_dir / "legacy-note.md").read_text(encoding="utf-8") == "keep-me\n"


def test_sync_skill_check_ignores_legacy_extra_files_when_required_files_match(
    monkeypatch, tmp_path
):
    module = _load_sync_skill_module()

    repo_root = tmp_path / "Memory-Palace"
    canonical_dir = repo_root / "docs" / "skills" / "memory-palace"
    (canonical_dir / "references").mkdir(parents=True, exist_ok=True)
    (canonical_dir / "agents").mkdir(parents=True, exist_ok=True)
    (canonical_dir / "variants" / "gemini").mkdir(parents=True, exist_ok=True)
    for relative_path, content in {
        Path("SKILL.md"): _canonical_skill_text("canonical-skill\n"),
        Path("references/mcp-workflow.md"): "canonical-workflow\n",
        Path("references/trigger-samples.md"): "canonical-trigger\n",
        Path("agents/openai.yaml"): "canonical-openai\n",
        Path("variants/gemini/SKILL.md"): _canonical_skill_text("canonical-gemini\n"),
    }.items():
        path = canonical_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    mirror_dir = repo_root / ".claude" / "skills" / "memory-palace"
    mirror_dir.mkdir(parents=True, exist_ok=True)
    for relative_path, content in {
        Path("SKILL.md"): _canonical_skill_text("canonical-skill\n"),
        Path("references/mcp-workflow.md"): "canonical-workflow\n",
        Path("references/trigger-samples.md"): "canonical-trigger\n",
        Path("agents/openai.yaml"): "canonical-openai\n",
        Path("legacy-note.md"): "keep-me\n",
    }.items():
        path = mirror_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    gemini_dir = repo_root / ".gemini" / "skills" / "memory-palace"
    gemini_dir.mkdir(parents=True, exist_ok=True)
    (gemini_dir / "SKILL.md").write_text(
        _canonical_skill_text("canonical-gemini\n"), encoding="utf-8"
    )
    (gemini_dir / "legacy-note.md").write_text("keep-me\n", encoding="utf-8")

    monkeypatch.setattr(module, "REPO_ROOT", repo_root)
    monkeypatch.setattr(module, "CANONICAL_DIR", canonical_dir)
    monkeypatch.setattr(module, "GEMINI_VARIANT_FILE", canonical_dir / "variants" / "gemini" / "SKILL.md")
    monkeypatch.setattr(module, "BUNDLE_MIRROR_DIRS", [mirror_dir])
    monkeypatch.setattr(module, "GEMINI_WORKSPACE_DIR", gemini_dir)

    assert module.run_check() == 0


def test_sync_skill_check_accepts_clean_clone_without_workspace_mirrors(
    monkeypatch, tmp_path
):
    module = _load_sync_skill_module()

    repo_root = tmp_path / "Memory-Palace"
    canonical_dir = repo_root / "docs" / "skills" / "memory-palace"
    (canonical_dir / "references").mkdir(parents=True, exist_ok=True)
    (canonical_dir / "agents").mkdir(parents=True, exist_ok=True)
    (canonical_dir / "variants" / "gemini").mkdir(parents=True, exist_ok=True)
    for relative_path, content in {
        Path("SKILL.md"): _canonical_skill_text("canonical-skill\n"),
        Path("references/mcp-workflow.md"): "canonical-workflow\n",
        Path("references/trigger-samples.md"): "canonical-trigger\n",
        Path("agents/openai.yaml"): "canonical-openai\n",
        Path("variants/gemini/SKILL.md"): _canonical_skill_text("canonical-gemini\n"),
    }.items():
        path = canonical_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(module, "REPO_ROOT", repo_root)
    monkeypatch.setattr(module, "CANONICAL_DIR", canonical_dir)
    monkeypatch.setattr(module, "GEMINI_VARIANT_FILE", canonical_dir / "variants" / "gemini" / "SKILL.md")
    monkeypatch.setattr(module, "BUNDLE_MIRROR_DIRS", [repo_root / ".codex" / "skills" / "memory-palace"])
    monkeypatch.setattr(module, "GEMINI_WORKSPACE_DIR", repo_root / ".gemini" / "skills" / "memory-palace")

    assert module.run_check() == 0
