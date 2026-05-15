import importlib.util
import json
import sys
import errno
from pathlib import Path

import pytest


def _load_install_skill_module():
    project_root = Path(__file__).resolve().parents[2]
    script_path = project_root / "scripts" / "install_skill.py"
    spec = importlib.util.spec_from_file_location("install_skill", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_read_json_file_reports_invalid_json_path(tmp_path: Path) -> None:
    module = _load_install_skill_module()
    config_path = tmp_path / "settings.json"
    config_path.write_text("{ invalid json", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        module.read_json_file(config_path)

    message = str(excinfo.value)
    assert "Invalid JSON" in message
    assert str(config_path) in message
    assert "Fix or remove the file and retry" in message


def test_read_json_file_rejects_non_object_roots(tmp_path: Path) -> None:
    module = _load_install_skill_module()
    config_path = tmp_path / "settings.json"
    config_path.write_text("[]", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        module.read_json_file(config_path)

    assert "expected an object" in str(excinfo.value)


def test_write_json_file_creates_backup_before_overwrite(tmp_path: Path) -> None:
    module = _load_install_skill_module()
    config_path = tmp_path / "settings.json"
    config_path.write_text(json.dumps({"old": True}), encoding="utf-8")

    module.write_json_file(config_path, {"new": True}, dry_run=False)

    backup_path = tmp_path / "settings.json.bak"
    assert backup_path.is_file()
    assert json.loads(backup_path.read_text(encoding="utf-8")) == {"old": True}
    assert json.loads(config_path.read_text(encoding="utf-8")) == {"new": True}


def test_write_json_file_retries_transient_permission_error_during_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_install_skill_module()
    config_path = tmp_path / "settings.json"
    config_path.write_text(json.dumps({"old": True}), encoding="utf-8")

    original_replace = module.os.replace
    attempts = {"count": 0}

    def flaky_replace(src, dst):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise PermissionError(errno.EACCES, "file is temporarily locked")
        return original_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", flaky_replace)

    module.write_json_file(config_path, {"new": True}, dry_run=False)

    assert attempts["count"] == 2
    assert json.loads(config_path.read_text(encoding="utf-8")) == {"new": True}


def test_strip_codex_memory_palace_block_keeps_similarly_named_servers() -> None:
    module = _load_install_skill_module()
    original = "\n".join(
        [
            "[mcp_servers.memory-palace-extra]",
            'command = "keep"',
            "",
            "[mcp_servers.memory-palace]",
            'command = "remove"',
            "",
            "[mcp_servers.memory-palace.env]",
            'PYTHONUTF8 = "1"',
            "",
            "[mcp_servers.other]",
            'command = "other"',
        ]
    )

    stripped = module._strip_codex_memory_palace_block(original)

    assert "[mcp_servers.memory-palace-extra]" in stripped
    assert 'command = "keep"' in stripped
    assert "[mcp_servers.memory-palace]" not in stripped
    assert "[mcp_servers.memory-palace.env]" not in stripped
    assert "[mcp_servers.other]" in stripped


def test_install_target_antigravity_copies_workspace_workflow(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    workflow_source = (
        project_root
        / "docs"
        / "skills"
        / "memory-palace"
        / "variants"
        / "antigravity"
        / "global_workflows"
        / "memory-palace.md"
    )
    workflow_source.parent.mkdir(parents=True, exist_ok=True)
    workflow_source.write_text("workflow\n", encoding="utf-8")

    monkeypatch.setattr(module, "project_root", lambda: project_root)
    monkeypatch.setattr(module, "workspace_root", lambda: project_root)

    module.install_target(
        "antigravity",
        source=project_root / "docs" / "skills" / "memory-palace",
        base_dir=project_root,
        mode="copy",
        force=False,
        dry_run=False,
    )

    destination = project_root / ".agent" / "workflows" / "memory-palace.md"
    assert destination.read_text(encoding="utf-8") == "workflow\n"


def test_check_skill_target_antigravity_accepts_matching_user_workflow(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    home_dir = tmp_path / "home"
    workflow_source = (
        project_root
        / "docs"
        / "skills"
        / "memory-palace"
        / "variants"
        / "antigravity"
        / "global_workflows"
        / "memory-palace.md"
    )
    workflow_source.parent.mkdir(parents=True, exist_ok=True)
    workflow_source.write_text("workflow\n", encoding="utf-8")
    destination = home_dir / ".gemini" / "antigravity" / "global_workflows" / "memory-palace.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("workflow\n", encoding="utf-8")

    monkeypatch.setattr(module, "project_root", lambda: project_root)

    ok, message = module.check_skill_target(
        "antigravity",
        base_dir=home_dir,
        source=project_root / "docs" / "skills" / "memory-palace",
        scope="user",
    )

    assert ok is True
    assert str(destination) == message


def test_install_target_antigravity_copies_workflow_and_removes_legacy_file(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_dir = tmp_path / "project"
    workflow_source = (
        project_dir
        / "docs"
        / "skills"
        / "memory-palace"
        / "variants"
        / "antigravity"
        / "global_workflows"
        / "memory-palace.md"
    )
    workflow_source.parent.mkdir(parents=True, exist_ok=True)
    workflow_source.write_text(
        "Use AGENTS.md first, then GEMINI.md.\n"
        "docs/skills/memory-palace/references/mcp-workflow.md\n"
        "docs/skills/memory-palace/references/trigger-samples.md\n",
        encoding="utf-8",
    )
    base_dir = tmp_path / "home"
    destination = base_dir / ".gemini" / "antigravity" / "global_workflows" / "memory-palace.md"
    legacy = destination.with_name("acg-memory-palace.md")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("legacy", encoding="utf-8")

    monkeypatch.setattr(module, "project_root", lambda: project_dir)
    monkeypatch.setattr(module, "workspace_root", lambda: project_dir / "workspace")

    module.install_target(
        "antigravity",
        source=project_dir / "docs" / "skills" / "memory-palace",
        base_dir=base_dir,
        mode="copy",
        force=False,
        dry_run=False,
    )

    assert destination.read_text(encoding="utf-8") == workflow_source.read_text(encoding="utf-8")
    assert not legacy.exists()


def test_install_target_antigravity_replaces_legacy_workflow(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    workflow_source = (
        project_root
        / "docs"
        / "skills"
        / "memory-palace"
        / "variants"
        / "antigravity"
        / "global_workflows"
        / "memory-palace.md"
    )
    workflow_source.parent.mkdir(parents=True, exist_ok=True)
    workflow_source.write_text(
        "Prefer AGENTS.md and keep GEMINI.md as legacy fallback.\n",
        encoding="utf-8",
    )

    destination_base = tmp_path / "home"
    legacy_path = (
        destination_base
        / ".gemini"
        / "antigravity"
        / "global_workflows"
        / "acg-memory-palace.md"
    )
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text("old workflow", encoding="utf-8")

    monkeypatch.setattr(module, "project_root", lambda: project_root)

    module.install_target(
        "antigravity",
        source=project_root / "docs" / "skills" / "memory-palace",
        base_dir=destination_base,
        mode="copy",
        force=True,
        dry_run=False,
    )

    installed_path = (
        destination_base
        / ".gemini"
        / "antigravity"
        / "global_workflows"
        / "memory-palace.md"
    )
    assert installed_path.is_file()
    assert installed_path.read_text(encoding="utf-8") == workflow_source.read_text(
        encoding="utf-8"
    )
    assert not legacy_path.exists()


def test_install_target_antigravity_workspace_scope_uses_agent_workflows_dir(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    workflow_source = (
        project_root
        / "docs"
        / "skills"
        / "memory-palace"
        / "variants"
        / "antigravity"
        / "global_workflows"
        / "memory-palace.md"
    )
    workflow_source.parent.mkdir(parents=True, exist_ok=True)
    workflow_source.write_text("Prefer AGENTS.md.\n", encoding="utf-8")
    workspace_dir = tmp_path / "workspace"

    monkeypatch.setattr(module, "project_root", lambda: project_root)
    monkeypatch.setattr(module, "workspace_root", lambda: workspace_dir)

    module.install_target(
        "antigravity",
        source=project_root / "docs" / "skills" / "memory-palace",
        base_dir=workspace_dir,
        mode="copy",
        force=False,
        dry_run=False,
    )

    installed_path = workspace_dir / ".agent" / "workflows" / "memory-palace.md"
    assert installed_path.is_file()
    assert installed_path.read_text(encoding="utf-8") == workflow_source.read_text(
        encoding="utf-8"
    )


def test_python_command_prefers_repo_backend_venv(monkeypatch, tmp_path: Path) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    venv_python = project_root / "backend" / ".venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "project_root", lambda: project_root)
    monkeypatch.setattr(module.os, "name", "nt")

    assert module._python_command() == str(venv_python)


def test_parse_args_defaults_to_cli_targets_only(monkeypatch) -> None:
    module = _load_install_skill_module()
    monkeypatch.setattr(module.sys, "argv", ["install_skill.py"])

    args = module.parse_args()

    assert module.resolve_targets(args.targets) == ["claude", "codex", "opencode"]


def test_resolve_targets_rejects_ide_host_targets_with_render_guidance() -> None:
    module = _load_install_skill_module()

    with pytest.raises(SystemExit) as excinfo:
        module.resolve_targets("claude,windsurf,vscode")

    message = str(excinfo.value)
    assert message.startswith("Unsupported install_skill IDE host target(s):")
    assert "render_ide_host_config.py" in message
    assert "--host windsurf" in message
    assert "--host vscode-host" in message
    assert "install_skill.py" in message
    assert "vscode," not in message
    assert message.count("--host windsurf") == 1
    assert message.count("--host vscode-host") == 1


@pytest.mark.parametrize(
    ("raw_target", "canonical_host"),
    [
        ("windsurf", "windsurf"),
        ("vscode-host", "vscode-host"),
        ("vscode", "vscode-host"),
        ("Windsurf", "windsurf"),
        ("VSCODE", "vscode-host"),
    ],
)
def test_resolve_targets_rejects_ide_host_aliases_with_canonical_render_guidance(
    raw_target: str, canonical_host: str
) -> None:
    module = _load_install_skill_module()

    with pytest.raises(SystemExit) as excinfo:
        module.resolve_targets(raw_target)

    message = str(excinfo.value)
    assert message.startswith("Unsupported install_skill IDE host target(s):")
    assert "render_ide_host_config.py" in message
    assert f"--host {canonical_host}" in message
    assert "IDE host" in message


def test_resolve_targets_deduplicates_canonical_ide_hosts_in_error_message() -> None:
    module = _load_install_skill_module()

    with pytest.raises(SystemExit) as excinfo:
        module.resolve_targets("claude,vscode,vscode-host,windsurf,claude")

    message = str(excinfo.value)
    assert "vscode-host, windsurf" in message
    assert message.count("vscode-host") == 2
    assert message.count("windsurf") == 2


def test_resolve_targets_all_still_yields_to_explicit_ide_host_guidance() -> None:
    module = _load_install_skill_module()

    assert module.resolve_targets("all") == list(module.TARGET_MAP)

    with pytest.raises(SystemExit) as excinfo:
        module.resolve_targets("all,windsurf")

    message = str(excinfo.value)
    assert message.startswith("Unsupported install_skill IDE host target(s):")
    assert "--host windsurf" in message


def test_install_skill_round_trip_workspace_then_check(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    source = project_root / "docs" / "skills" / "memory-palace"
    workspace = tmp_path / "workspace"

    for relative_path, content in {
        Path("SKILL.md"): "---\nname: memory-palace\ndescription: test skill\n---\nbody\n",
        Path("agents/openai.yaml"): "name: memory-palace\n",
        Path("references/mcp-workflow.md"): "workflow\n",
        Path("references/trigger-samples.md"): "triggers\n",
        Path("variants/gemini/SKILL.md"): "---\nname: memory-palace\ndescription: gemini variant\n---\nbody\n",
        Path("variants/gemini/memory-palace-overrides.toml"): "rule = true\n",
    }.items():
        path = source / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    (project_root / "scripts").mkdir(parents=True, exist_ok=True)
    (project_root / "scripts" / "run_memory_palace_mcp_stdio.sh").write_text(
        "#!/usr/bin/env bash\n",
        encoding="utf-8",
    )
    (project_root / "backend").mkdir(parents=True, exist_ok=True)
    (project_root / "backend" / "mcp_wrapper.py").write_text(
        "print('wrapper')\n",
        encoding="utf-8",
    )
    (project_root / "AGENTS.md").write_text("rules\n", encoding="utf-8")

    monkeypatch.setattr(module, "project_root", lambda: project_root)
    monkeypatch.setattr(module, "workspace_root", lambda: workspace)

    install_rc = module.main(
        ["--targets", "claude,gemini", "--scope", "workspace", "--with-mcp"]
    )
    check_rc = module.main(
        ["--targets", "claude,gemini", "--scope", "workspace", "--with-mcp", "--check"]
    )

    assert install_rc == 0
    assert check_rc == 0


def test_codex_server_block_uses_python_wrapper_on_windows(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    venv_python = project_root / "backend" / ".venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "project_root", lambda: project_root)
    monkeypatch.setattr(module.os, "name", "nt")

    rendered = module._codex_server_block_text()

    expected_command = str(venv_python).replace("\\", "\\\\")
    assert f'command = "{expected_command}"' in rendered
    assert str(project_root / "backend" / "mcp_wrapper.py").replace("\\", "\\\\") in rendered


def test_codex_server_block_uses_shell_wrapper_for_git_bash_windows_host(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"

    monkeypatch.setattr(module, "project_root", lambda: project_root)
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setenv("MSYSTEM", "MINGW64")
    monkeypatch.setenv("SHELL", "/usr/bin/bash")

    rendered = module._codex_server_block_text()

    assert 'command = "bash"' in rendered
    assert (project_root / "scripts" / "run_memory_palace_mcp_stdio.sh").as_posix() in rendered
    assert "mcp_wrapper.py" not in rendered


def test_check_mcp_binding_codex_falls_back_without_tomllib(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    home_dir = tmp_path / "home"
    config_path = home_dir / ".codex" / "config.toml"
    venv_python = project_root / "backend" / ".venv" / "bin" / "python"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "project_root", lambda: project_root)
    monkeypatch.setattr(module.Path, "home", lambda: home_dir)
    monkeypatch.setattr(module, "tomllib", None)

    config_path.write_text(module._codex_server_block_text(), encoding="utf-8")

    ok, message = module.check_mcp_binding("codex", scope="user")

    assert ok is True
    assert message == str(config_path)


def test_check_mcp_binding_codex_user_scope_rejects_relative_python_wrapper_arg(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    home_dir = tmp_path / "home"
    config_path = home_dir / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "\n".join(
            [
                "[mcp_servers.memory-palace]",
                'command = "python"',
                'args = ["backend/mcp_wrapper.py"]',
                "startup_timeout_sec = 30.0",
                "",
                "[mcp_servers.memory-palace.env]",
                'PYTHONIOENCODING = "utf-8"',
                'PYTHONUTF8 = "1"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "project_root", lambda: project_root)
    monkeypatch.setattr(module.Path, "home", lambda: home_dir)

    ok, message = module.check_mcp_binding("codex", scope="user")

    assert ok is False
    assert message == str(config_path)


def test_wrapper_binding_ok_accepts_python_wrapper_paths(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    venv_python = project_root / "backend" / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "project_root", lambda: project_root)

    assert module._wrapper_binding_ok(
        [str(venv_python), str(project_root / "backend" / "mcp_wrapper.py")],
        allow_relative=False,
    )
    assert module._wrapper_binding_ok(
        [str(venv_python), "backend/mcp_wrapper.py"],
        allow_relative=True,
    )


def test_wrapper_binding_ok_accepts_documented_manual_fallbacks(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    venv_python = project_root / "backend" / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "project_root", lambda: project_root)
    monkeypatch.setattr(module.shutil, "which", lambda command: str(venv_python) if command == "python" else None)

    assert module._wrapper_binding_ok(
        ["python", str(project_root / "backend" / "mcp_wrapper.py")],
        allow_relative=False,
    )


def test_wrapper_binding_ok_rejects_python_wrapper_when_python_resolves_outside_repo_venv(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    venv_python = project_root / "backend" / ".venv" / "bin" / "python"
    other_python = tmp_path / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    other_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")
    other_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "project_root", lambda: project_root)
    monkeypatch.setattr(module.shutil, "which", lambda command: str(other_python) if command == "python" else None)

    assert not module._wrapper_binding_ok(
        ["python", str(project_root / "backend" / "mcp_wrapper.py")],
        allow_relative=False,
    )
    assert module._wrapper_binding_ok(
        [
            "/bin/zsh",
            "-lc",
            f"cd {project_root} && bash scripts/run_memory_palace_mcp_stdio.sh",
        ],
        allow_relative=False,
    )


def test_wrapper_binding_ok_rejects_loose_manual_fallbacks(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    venv_python = project_root / "backend" / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "project_root", lambda: project_root)

    assert not module._wrapper_binding_ok(
        ["python3", str(project_root / "backend" / "mcp_wrapper.py")],
        allow_relative=False,
    )
    assert not module._wrapper_binding_ok(
        [
            "/bin/zsh",
            "-lc",
            f"cd {project_root} && bash scripts/run_memory_palace_mcp_stdio.sh && echo leaked",
        ],
        allow_relative=False,
    )


def test_wrapper_binding_ok_rejects_non_wrapper_commands(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    venv_python = project_root / "backend" / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "project_root", lambda: project_root)

    assert not module._wrapper_binding_ok(
        ["echo", str(project_root / "backend" / "mcp_wrapper.py")],
        allow_relative=False,
    )


def test_python_command_requires_repo_backend_venv(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"

    monkeypatch.setattr(module, "project_root", lambda: project_root)

    with pytest.raises(SystemExit) as excinfo:
        module._python_command()

    assert "Missing repo backend virtualenv python" in str(excinfo.value)


def test_check_mcp_binding_codex_reports_invalid_toml_with_path(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    home_dir = tmp_path / "home"
    config_path = home_dir / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("[mcp_servers.memory-palace\n", encoding="utf-8")

    monkeypatch.setattr(module, "project_root", lambda: project_root)
    monkeypatch.setattr(module.Path, "home", lambda: home_dir)

    with pytest.raises(SystemExit) as excinfo:
        module.check_mcp_binding("codex", scope="user")

    assert "Invalid TOML in" in str(excinfo.value)
    assert str(config_path) in str(excinfo.value)


def test_install_target_force_keeps_existing_skill_when_copying_new_tree_fails(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    source = project_root / "docs" / "skills" / "memory-palace"
    destination_base = tmp_path / "home"
    destination_dir = destination_base / ".claude" / "skills" / "memory-palace"

    for relative_path, content in {
        Path("SKILL.md"): "new skill\n",
        Path("agents/openai.yaml"): "new agent\n",
        Path("references/mcp-workflow.md"): "new workflow\n",
        Path("references/trigger-samples.md"): "new triggers\n",
    }.items():
        path = source / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    for relative_path, content in {
        Path("SKILL.md"): "old skill\n",
        Path("agents/openai.yaml"): "old agent\n",
        Path("references/mcp-workflow.md"): "old workflow\n",
        Path("references/trigger-samples.md"): "old triggers\n",
    }.items():
        path = destination_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    original_copy2 = module.shutil.copy2
    copy_count = {"value": 0}

    def flaky_copy2(src, dst, *args, **kwargs):
        copy_count["value"] += 1
        if copy_count["value"] == 2:
            raise OSError("simulated copy failure")
        return original_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(module.shutil, "copy2", flaky_copy2)

    with pytest.raises(OSError, match="simulated copy failure"):
        module.install_target(
            "claude",
            source=source,
            base_dir=destination_base,
            mode="copy",
            force=True,
            dry_run=False,
        )

    assert (destination_dir / "SKILL.md").read_text(encoding="utf-8") == "old skill\n"
    assert (destination_dir / "agents" / "openai.yaml").read_text(encoding="utf-8") == "old agent\n"
    assert not list((destination_base / ".claude" / "skills").glob(".memory-palace.staging.*"))
    assert not list((destination_base / ".claude" / "skills").glob(".memory-palace.backup.*"))


def test_install_target_retries_transient_permission_error_when_promoting_staging_tree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_install_skill_module()
    project_root = tmp_path / "Memory-Palace"
    source = project_root / "docs" / "skills" / "memory-palace"
    destination_base = tmp_path / "home"
    destination_dir = destination_base / ".claude" / "skills" / "memory-palace"

    for relative_path, content in {
        Path("SKILL.md"): "skill\n",
        Path("agents/openai.yaml"): "agent\n",
        Path("references/mcp-workflow.md"): "workflow\n",
        Path("references/trigger-samples.md"): "triggers\n",
    }.items():
        path = source / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    original_replace = module.os.replace
    attempts = {"count": 0}

    def flaky_replace(src, dst):
        if Path(dst) == destination_dir:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise PermissionError(errno.EACCES, "destination is temporarily locked")
        return original_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", flaky_replace)

    module.install_target(
        "claude",
        source=source,
        base_dir=destination_base,
        mode="copy",
        force=False,
        dry_run=False,
    )

    assert attempts["count"] == 2
    assert (destination_dir / "SKILL.md").read_text(encoding="utf-8") == "skill\n"
