#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import errno
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import time
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


SKILL_NAME = "memory-palace"
TARGET_MAP = {
    "claude": ".claude/skills",
    "codex": ".codex/skills",
    "gemini": ".gemini/skills",
    "cursor": ".cursor/skills",
    "opencode": ".opencode/skills",
    "agent": ".agent/skills",
    "antigravity": None,
}
UNSUPPORTED_IDE_HOST_TARGETS = {
    "windsurf": "windsurf",
    "vscode-host": "vscode-host",
    "vscode": "vscode-host",
}
UTF8_ENV = {
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
}
SKILL_RELATIVE_FILES = [
    Path("SKILL.md"),
    Path("agents/openai.yaml"),
    Path("references/mcp-workflow.md"),
    Path("references/trigger-samples.md"),
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Install the canonical Memory Palace skill into workspace-local or user-local "
            "CLI skill directories, and optionally register MCP bindings that point to this repo. "
            "For IDE-like hosts such as Cursor/Windsurf/VSCode-host/Antigravity, prefer "
            "scripts/render_ide_host_config.py plus repo-local AGENTS.md instead of hidden skill mirrors."
        ),
    )
    parser.add_argument(
        "--targets",
        default="claude,codex,opencode",
        help=(
            "Comma-separated targets. Available: claude,codex,gemini,cursor,opencode,agent,"
            "antigravity,all. Cursor/agent/antigravity remain compatibility-only projections; "
            "IDE hosts should prefer scripts/render_ide_host_config.py plus repo-local AGENTS.md. "
            "Default keeps CLI targets only and excludes gemini because user-scope install is more "
            "reliable there."
        ),
    )
    parser.add_argument(
        "--scope",
        choices=("workspace", "user"),
        default="workspace",
        help="Install into the current workspace root or into the user's home directory.",
    )
    parser.add_argument(
        "--mode",
        choices=("copy", "symlink"),
        default="copy",
        help="Copy files by default; use symlink when you want repo edits to reflect immediately.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing installed skill directory if present.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without changing the filesystem.",
    )
    parser.add_argument(
        "--with-mcp",
        action="store_true",
        help=(
            "Also install or update MCP configuration for the selected targets when this script knows "
            "a stable configuration surface for the chosen scope."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Check whether the selected skill installs already match the canonical source. "
            "When used with --with-mcp, also verify MCP bindings."
        ),
    )
    return parser.parse_args(argv)


def resolve_targets(raw: str) -> list[str]:
    requested = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if not requested:
        raise SystemExit("No targets specified.")
    unsupported_ide_hosts = [
        item for item in requested if item in UNSUPPORTED_IDE_HOST_TARGETS
    ]
    if unsupported_ide_hosts:
        canonical_hosts: list[str] = []
        seen_hosts: set[str] = set()
        for item in unsupported_ide_hosts:
            canonical = UNSUPPORTED_IDE_HOST_TARGETS[item]
            if canonical not in seen_hosts:
                canonical_hosts.append(canonical)
                seen_hosts.add(canonical)
        host_list = ", ".join(canonical_hosts)
        commands = ", ".join(
            f"python scripts/render_ide_host_config.py --host {host}"
            for host in canonical_hosts
        )
        raise SystemExit(
            "Unsupported install_skill IDE host target(s): "
            f"{host_list}. install_skill.py does not install IDE host projections; "
            f"IDE hosts use repo-local rules plus MCP snippets, so run {commands} instead."
        )
    if "all" in requested:
        return list(TARGET_MAP)
    invalid = [item for item in requested if item not in TARGET_MAP]
    if invalid:
        raise SystemExit(f"Unknown targets: {', '.join(invalid)}")
    ordered: list[str] = []
    seen: set[str] = set()
    for item in requested:
        if item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[1]


def project_root() -> Path:
    return workspace_root()


def shell_wrapper_relative() -> Path:
    return Path("scripts/run_memory_palace_mcp_stdio.sh")


def shell_wrapper_absolute() -> Path:
    return project_root() / "scripts" / "run_memory_palace_mcp_stdio.sh"


def python_wrapper_relative() -> Path:
    return Path("backend/mcp_wrapper.py")


def python_wrapper_absolute() -> Path:
    return project_root() / "backend" / "mcp_wrapper.py"


def backend_venv_python_absolute() -> Path:
    if os.name == "nt":
        return project_root() / "backend" / ".venv" / "Scripts" / "python.exe"
    return project_root() / "backend" / ".venv" / "bin" / "python"


def _require_backend_venv_python() -> Path:
    preferred = backend_venv_python_absolute()
    if preferred.is_file():
        return preferred
    raise SystemExit(
        "Missing repo backend virtualenv python for python-wrapper MCP config: "
        f"{preferred}. Create backend/.venv before installing or rendering python-wrapper bindings."
    )


def source_dir() -> Path:
    source = project_root() / "docs" / "skills" / SKILL_NAME
    required = [source / relative_path for relative_path in SKILL_RELATIVE_FILES]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"Canonical skill source incomplete: {', '.join(missing)}")
    return source


def gemini_variant_file(source: Path) -> Path:
    variant = source / "variants" / "gemini" / "SKILL.md"
    if not variant.is_file():
        raise SystemExit(f"Gemini variant missing: {variant}")
    return variant


def gemini_policy_variant_file(source: Path) -> Path:
    variant = source / "variants" / "gemini" / "memory-palace-overrides.toml"
    if not variant.is_file():
        raise SystemExit(f"Gemini policy variant missing: {variant}")
    return variant


def gemini_policy_destination(base_dir: Path) -> Path:
    return base_dir / ".gemini" / "policies" / "memory-palace-overrides.toml"


def antigravity_workflow_file(project_dir: Path) -> Path:
    variant = (
        project_dir
        / "docs"
        / "skills"
        / SKILL_NAME
        / "variants"
        / "antigravity"
        / "global_workflows"
        / "memory-palace.md"
    )
    if not variant.is_file():
        raise SystemExit(f"Antigravity workflow variant missing: {variant}")
    return variant


def antigravity_destination(base_dir: Path, scope: str) -> Path:
    if scope == "workspace":
        return base_dir / ".agent" / "workflows" / "memory-palace.md"
    return base_dir / ".gemini" / "antigravity" / "global_workflows" / "memory-palace.md"


def ensure_wrapper_script() -> None:
    missing: list[str] = []
    for wrapper in (shell_wrapper_absolute(), python_wrapper_absolute()):
        if not wrapper.is_file():
            missing.append(str(wrapper))
    if missing:
        raise SystemExit(f"Missing MCP wrapper script: {', '.join(missing)}")


def read_json_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"Invalid JSON in {path}: {exc.msg} (line {exc.lineno}, column {exc.colno}). "
            "Fix or remove the file and retry."
        ) from exc
    if not isinstance(payload, dict):
        raise SystemExit(
            f"Invalid JSON root in {path}: expected an object, got {type(payload).__name__}."
        )
    return payload


def backup_file(path: Path, *, dry_run: bool) -> None:
    if not path.is_file():
        return
    backup_path = path.with_name(f"{path.name}.bak")
    print(f"[backup] {path} -> {backup_path}")
    if dry_run:
        return
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_path)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.tmp.",
        dir=str(path.parent),
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        _replace_with_retry(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _is_retryable_replace_error(exc: OSError) -> bool:
    if getattr(exc, "winerror", None) in {5, 32, 33}:
        return True
    return exc.errno in {
        errno.EACCES,
        errno.EBUSY,
        errno.EPERM,
    }


def _replace_with_retry(
    source: Path,
    destination: Path,
    *,
    retries: int = 3,
    retry_delay_sec: float = 0.05,
) -> None:
    last_error: OSError | None = None
    for attempt in range(retries):
        try:
            os.replace(source, destination)
            return
        except OSError as exc:
            last_error = exc
            if not _is_retryable_replace_error(exc) or attempt >= retries - 1:
                raise
            time.sleep(retry_delay_sec * (attempt + 1))
    if last_error is not None:
        raise last_error


def write_json_file(path: Path, payload: dict, *, dry_run: bool) -> None:
    print(f"[json] write -> {path}")
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_file(path, dry_run=dry_run)
    _atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def write_text_file(path: Path, content: str, *, dry_run: bool) -> None:
    print(f"[text] write -> {path}")
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_file(path, dry_run=dry_run)
    _atomic_write_text(path, content)


def _remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    shutil.rmtree(path)


def _build_regular_skill_tree(
    *,
    target_name: str,
    source: Path,
    destination_dir: Path,
    mode: str,
) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)

    if mode == "symlink":
        if target_name == "gemini":
            skill_target = destination_dir / "SKILL.md"
            skill_target.parent.mkdir(parents=True, exist_ok=True)
            skill_target.symlink_to(gemini_variant_file(source))
            return
        for relative_path in SKILL_RELATIVE_FILES:
            link_path = destination_dir / relative_path
            link_path.parent.mkdir(parents=True, exist_ok=True)
            link_path.symlink_to(source / relative_path)
        return

    if target_name == "gemini":
        shutil.copy2(gemini_variant_file(source), destination_dir / "SKILL.md")
        return

    for relative_path in SKILL_RELATIVE_FILES:
        source_file = source / relative_path
        target_file = destination_dir / relative_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)


def _install_regular_skill_target_atomically(
    *,
    target_name: str,
    source: Path,
    destination_root: Path,
    destination_dir: Path,
    mode: str,
    force: bool,
) -> None:
    destination_root.mkdir(parents=True, exist_ok=True)
    if destination_dir.exists() or destination_dir.is_symlink():
        if not force:
            raise SystemExit(
                f"Target already exists: {destination_dir} (use --force to replace it)"
            )

    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{SKILL_NAME}.staging.", dir=str(destination_root))
    )
    backup_root: Path | None = None
    backup_path: Path | None = None

    try:
        _build_regular_skill_tree(
            target_name=target_name,
            source=source,
            destination_dir=staging_dir,
            mode=mode,
        )

        if destination_dir.exists() or destination_dir.is_symlink():
            backup_root = Path(
                tempfile.mkdtemp(prefix=f".{SKILL_NAME}.backup.", dir=str(destination_root))
            )
            backup_path = backup_root / destination_dir.name
            _replace_with_retry(destination_dir, backup_path)

        _replace_with_retry(staging_dir, destination_dir)
        staging_dir = destination_dir

        if backup_root is not None:
            shutil.rmtree(backup_root)
            backup_root = None

    except Exception:
        if backup_path is not None and backup_path.exists() and not destination_dir.exists():
            _replace_with_retry(backup_path, destination_dir)
        raise
    finally:
        if backup_root is not None and backup_root.exists():
            shutil.rmtree(backup_root)
        if staging_dir.exists() and staging_dir != destination_dir:
            _remove_path(staging_dir)


def _normalized(value: object) -> str:
    return str(value).replace("\\", "/")


def _is_windows_posix_shell_host() -> bool:
    if os.name != "nt":
        return False

    for key in ("MSYSTEM", "CYGWIN", "WSL_DISTRO_NAME", "WSL_INTEROP"):
        if str(os.getenv(key) or "").strip():
            return True

    ostype = str(os.getenv("OSTYPE") or "").strip().lower()
    if any(marker in ostype for marker in ("msys", "cygwin")):
        return True

    return False


def _default_mcp_launcher() -> str:
    if os.name == "nt" and not _is_windows_posix_shell_host():
        return "python-wrapper"
    return "bash"


def _python_command() -> str:
    return str(_require_backend_venv_python())


def _render_launcher_path(path: Path, *, launcher: str) -> str:
    if launcher == "bash" and os.name == "nt":
        return path.as_posix()
    return str(path)


def _same_path(a: object, b: object) -> bool:
    return _normalized(a).lower() == _normalized(b).lower()


def _command_name(command: object) -> str:
    return Path(str(command or "")).name.lower()


def _looks_like_python_command(command: object) -> bool:
    normalized = str(command or "").strip().lower()
    return normalized in {"py", "python"}


def _strip_matching_quotes(value: object) -> str:
    normalized = str(value or "").strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        return normalized[1:-1]
    return normalized


def _shell_fallback_binding_ok(
    command: str,
    args: list[str],
    *,
    shell_candidates: set[str],
) -> bool:
    if _command_name(command) not in {"bash", "sh", "zsh"}:
        return False
    if len(args) < 2 or args[0] not in {"-lc", "-c"}:
        return False

    inline_script = str(args[1] or "").strip()
    if not inline_script:
        return False

    segments = [segment.strip() for segment in inline_script.split("&&") if segment.strip()]
    if len(segments) != 2:
        return False

    try:
        cd_tokens = shlex.split(segments[0])
    except ValueError:
        return False
    if len(cd_tokens) != 2 or cd_tokens[0] != "cd" or not _same_path(cd_tokens[1], project_root()):
        return False

    launch_segment = segments[1]
    if launch_segment.startswith("exec "):
        launch_segment = launch_segment[5:].strip()
    try:
        launch_tokens = shlex.split(launch_segment)
    except ValueError:
        return False
    if len(launch_tokens) != 2 or _command_name(launch_tokens[0]) not in {"bash", "sh", "zsh"}:
        return False

    wrapper = _normalized(_strip_matching_quotes(launch_tokens[1]))
    if wrapper in shell_candidates:
        return True

    if not Path(wrapper).is_absolute():
        resolved_wrapper = project_root() / wrapper
        if _same_path(resolved_wrapper.resolve(), shell_wrapper_absolute().resolve()):
            return True
    return False


def _wrapper_binding_ok(command_parts: list[str], *, allow_relative: bool) -> bool:
    normalized_parts = [_normalized(part) for part in command_parts if str(part).strip()]
    if not normalized_parts:
        return False

    command = normalized_parts[0]
    args = normalized_parts[1:]
    if not args:
        return False

    shell_candidates = {_normalized(shell_wrapper_absolute())}
    python_wrapper_candidates = {_normalized(python_wrapper_absolute())}
    if allow_relative:
        shell_candidates.add(_normalized(shell_wrapper_relative()))
        python_wrapper_candidates.add(_normalized(python_wrapper_relative()))

    shell_command = _command_name(command)
    if shell_command in {"bash", "sh"} and args[0] in shell_candidates:
        return True
    if _shell_fallback_binding_ok(
        command,
        args,
        shell_candidates=shell_candidates | {_normalized(shell_wrapper_relative())},
    ):
        return True

    try:
        expected_python = _normalized(_require_backend_venv_python())
    except SystemExit:
        expected_python = ""
    if expected_python and _same_path(command, expected_python) and args[0] in python_wrapper_candidates:
        return True
    if _looks_like_python_command(command) and args[0] in python_wrapper_candidates:
        resolved_python = _normalized(shutil.which(command) or "")
        return bool(expected_python and resolved_python and _same_path(resolved_python, expected_python))
    return False


def _command_and_args(*, relative: bool) -> tuple[str, list[str]]:
    launcher = _default_mcp_launcher()
    if launcher == "python-wrapper":
        wrapper = python_wrapper_relative() if relative else python_wrapper_absolute()
        return _python_command(), [str(wrapper)]
    wrapper = shell_wrapper_relative() if relative else shell_wrapper_absolute()
    return "bash", [_render_launcher_path(wrapper, launcher=launcher)]


def _claude_server_block(*, relative: bool) -> dict:
    command, args = _command_and_args(relative=relative)
    return {
        "type": "stdio",
        "command": command,
        "args": args,
        "env": dict(UTF8_ENV),
    }


def _gemini_server_block(*, relative: bool) -> dict:
    command, args = _command_and_args(relative=relative)
    return {
        "command": command,
        "args": args,
        "description": "Memory Palace MCP for the current repository",
        "timeout": 20000,
        "env": dict(UTF8_ENV),
    }


def _opencode_server_block() -> dict:
    command, args = _command_and_args(relative=False)
    return {
        "command": [command, *args],
        "enabled": True,
        "type": "local",
    }


def _codex_server_block_text() -> str:
    command, args = _command_and_args(relative=False)
    rendered_args = ", ".join(json.dumps(str(arg)) for arg in args)
    return "\n".join(
        [
            "[mcp_servers.memory-palace]",
            f"command = {json.dumps(command)}",
            f"args = [{rendered_args}]",
            "startup_timeout_sec = 30.0",
            "",
            "[mcp_servers.memory-palace.env]",
            'PYTHONIOENCODING = "utf-8"',
            'PYTHONUTF8 = "1"',
            "",
        ]
    )


def _strip_codex_memory_palace_block(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    skipping = False
    target_headers = {
        "[mcp_servers.memory-palace]",
        "[mcp_servers.memory-palace.env]",
    }
    for line in lines:
        stripped = line.strip()
        if stripped in target_headers:
            skipping = True
            continue
        if skipping and stripped.startswith("["):
            skipping = False
        if not skipping:
            kept.append(line)
    return "\n".join(kept).rstrip()


def _parse_codex_memory_palace_block(text: str) -> dict:
    block_match = re.search(
        r"(?ms)^\[mcp_servers\.memory-palace\]\s*(.*?)^(?:\[|\Z)",
        text,
    )
    if not block_match:
        return {}

    block = block_match.group(1)
    command_match = re.search(r'(?m)^command\s*=\s*(".*?")\s*$', block)
    args_match = re.search(r'(?m)^args\s*=\s*(\[.*\])\s*$', block)
    if not command_match:
        return {}

    try:
        command = ast.literal_eval(command_match.group(1))
        args = ast.literal_eval(args_match.group(1)) if args_match else []
    except (SyntaxError, ValueError):
        return {}

    if not isinstance(command, str):
        return {}
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        return {}

    return {
        "command": command,
        "args": args,
    }


def _read_codex_toml(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    except getattr(tomllib, "TOMLDecodeError", ValueError) as exc:
        message = getattr(exc, "msg", str(exc))
        line = getattr(exc, "lineno", None)
        column = getattr(exc, "colno", None)
        location = ""
        if line is not None and column is not None:
            location = f" (line {line}, column {column})"
        raise SystemExit(
            f"Invalid TOML in {path}: {message}{location}. Fix or remove the file and retry."
        ) from exc
    if not isinstance(payload, dict):
        raise SystemExit(
            f"Invalid TOML root in {path}: expected a table, got {type(payload).__name__}."
        )
    return payload


def _workspace_mcp_supported(target_name: str) -> bool:
    return target_name in {"claude", "gemini"}


def _user_mcp_supported(target_name: str) -> bool:
    return target_name in {"claude", "codex", "gemini", "opencode"}


def install_gemini_policy(
    *,
    source: Path,
    base_dir: Path,
    mode: str,
    dry_run: bool,
) -> None:
    variant = gemini_policy_variant_file(source)
    destination = gemini_policy_destination(base_dir)
    action = "symlink" if mode == "symlink" else "copy"
    print(f"[gemini] {action} policy -> {destination}")

    if dry_run:
        return

    destination.parent.mkdir(parents=True, exist_ok=True)

    if mode == "symlink":
        if destination.exists() or destination.is_symlink():
            if destination.is_dir() and not destination.is_symlink():
                raise SystemExit(f"Gemini policy destination is a directory: {destination}")
            backup_file(destination, dry_run=dry_run)
            destination.unlink()
        destination.symlink_to(variant)
        return

    write_text_file(destination, variant.read_text(encoding="utf-8"), dry_run=dry_run)


def install_target(
    target_name: str,
    *,
    source: Path,
    base_dir: Path,
    mode: str,
    force: bool,
    dry_run: bool,
) -> None:
    if target_name == "antigravity":
        destination_file = antigravity_destination(
            base_dir, "workspace" if base_dir == workspace_root() else "user"
        )
        print(f"[{target_name}] workflow -> {destination_file}")
        if dry_run:
            return
        workflow_source = antigravity_workflow_file(project_root())
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        legacy_file = destination_file.with_name("acg-memory-palace.md")
        if legacy_file.exists() or legacy_file.is_symlink():
            if legacy_file.is_symlink() or legacy_file.is_file():
                legacy_file.unlink()
            else:
                shutil.rmtree(legacy_file)
        if destination_file.exists() or destination_file.is_symlink():
            if not force:
                raise SystemExit(
                    f"Target already exists: {destination_file} (use --force to replace it)"
                )
            if destination_file.is_symlink() or destination_file.is_file():
                destination_file.unlink()
            else:
                shutil.rmtree(destination_file)
        shutil.copy2(workflow_source, destination_file)
        return

    destination_root = base_dir / TARGET_MAP[target_name]
    destination_dir = destination_root / SKILL_NAME
    action = "symlink" if mode == "symlink" else "copy"
    print(f"[{target_name}] {action} -> {destination_dir}")

    if dry_run:
        if target_name == "gemini":
            install_gemini_policy(source=source, base_dir=base_dir, mode=mode, dry_run=dry_run)
        return

    _install_regular_skill_target_atomically(
        target_name=target_name,
        source=source,
        destination_root=destination_root,
        destination_dir=destination_dir,
        mode=mode,
        force=force,
    )

    if target_name == "gemini":
        install_gemini_policy(source=source, base_dir=base_dir, mode=mode, dry_run=dry_run)


def install_mcp_binding(target_name: str, *, scope: str, dry_run: bool) -> None:
    ensure_wrapper_script()
    if scope == "workspace":
        if not _workspace_mcp_supported(target_name):
            print(
                f"[{target_name}] MCP note -> no stable workspace-local MCP config surface; use --scope user --with-mcp"
            )
            return
        if target_name == "claude":
            config_path = workspace_root() / ".mcp.json"
            payload = read_json_file(config_path)
            payload.setdefault("mcpServers", {})["memory-palace"] = _claude_server_block(relative=True)
            write_json_file(config_path, payload, dry_run=dry_run)
            return
        if target_name == "gemini":
            config_path = workspace_root() / ".gemini" / "settings.json"
            payload = read_json_file(config_path)
            payload.setdefault("mcpServers", {})["memory-palace"] = _gemini_server_block(relative=True)
            write_json_file(config_path, payload, dry_run=dry_run)
            return
        return

    if not _user_mcp_supported(target_name):
        print(f"[{target_name}] MCP note -> no user-scope MCP config managed for this target")
        return

    if target_name == "claude":
        config_path = Path.home() / ".claude.json"
        payload = read_json_file(config_path)
        projects = payload.setdefault("projects", {})
        project_block = projects.setdefault(str(workspace_root()), {})
        project_block.setdefault("mcpServers", {})["memory-palace"] = _claude_server_block(relative=False)
        write_json_file(config_path, payload, dry_run=dry_run)
        return

    if target_name == "codex":
        config_path = Path.home() / ".codex" / "config.toml"
        existing = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
        trimmed = _strip_codex_memory_palace_block(existing)
        rendered = _codex_server_block_text().rstrip()
        next_text = f"{trimmed}\n\n{rendered}\n" if trimmed else f"{rendered}\n"
        write_text_file(config_path, next_text, dry_run=dry_run)
        return

    if target_name == "gemini":
        config_path = Path.home() / ".gemini" / "settings.json"
        payload = read_json_file(config_path)
        payload.setdefault("mcpServers", {})["memory-palace"] = _gemini_server_block(relative=False)
        write_json_file(config_path, payload, dry_run=dry_run)
        return

    if target_name == "opencode":
        config_path = Path.home() / ".config" / "opencode" / "opencode.json"
        payload = read_json_file(config_path)
        if not payload:
            payload["$schema"] = "https://opencode.ai/config.json"
        payload.setdefault("mcp", {})["memory-palace"] = _opencode_server_block()
        write_json_file(config_path, payload, dry_run=dry_run)


def _check_regular_skill_target(target_name: str, *, base_dir: Path, source: Path) -> tuple[bool, str]:
    destination_root = base_dir / TARGET_MAP[target_name]
    destination_dir = destination_root / SKILL_NAME
    if not destination_dir.is_dir():
        return False, f"missing skill dir: {destination_dir}"
    for relative_path in SKILL_RELATIVE_FILES:
        expected = source / relative_path
        actual = destination_dir / relative_path
        if not actual.is_file():
            return False, f"missing file: {actual}"
        if actual.read_bytes() != expected.read_bytes():
            return False, f"mismatch: {actual}"
    return True, str(destination_dir)


def check_skill_target(target_name: str, *, base_dir: Path, source: Path, scope: str) -> tuple[bool, str]:
    if target_name == "antigravity":
        destination_file = antigravity_destination(base_dir, scope)
        expected = antigravity_workflow_file(project_root())
        if destination_file.is_file() and destination_file.read_bytes() == expected.read_bytes():
            return True, str(destination_file)
        return False, f"missing or mismatched workflow: {destination_file}"
    if target_name == "gemini":
        destination_file = base_dir / TARGET_MAP[target_name] / SKILL_NAME / "SKILL.md"
        expected = gemini_variant_file(source)
        policy_file = gemini_policy_destination(base_dir)
        expected_policy = gemini_policy_variant_file(source)
        skill_ok = destination_file.is_file() and destination_file.read_bytes() == expected.read_bytes()
        policy_ok = policy_file.is_file() and policy_file.read_bytes() == expected_policy.read_bytes()
        if skill_ok and policy_ok:
            return True, f"{destination_file}; {policy_file}"
        problems: list[str] = []
        if not skill_ok:
            problems.append(f"missing or mismatched file: {destination_file}")
        if not policy_ok:
            problems.append(f"missing or mismatched policy: {policy_file}")
        return False, "; ".join(problems)
    return _check_regular_skill_target(target_name, base_dir=base_dir, source=source)


def check_mcp_binding(target_name: str, *, scope: str) -> tuple[bool | None, str]:
    if scope == "workspace":
        if not _workspace_mcp_supported(target_name):
            return None, "workspace scope does not define a stable repo-local MCP config for this target"
        if target_name == "claude":
            config_path = workspace_root() / ".mcp.json"
            payload = read_json_file(config_path)
            server = payload.get("mcpServers", {}).get("memory-palace", {})
            command = [server.get("command", ""), *(server.get("args") or [])]
            ok = server.get("type") == "stdio" and _wrapper_binding_ok(command, allow_relative=True)
            return ok, str(config_path)
        if target_name == "gemini":
            config_path = workspace_root() / ".gemini" / "settings.json"
            payload = read_json_file(config_path)
            server = payload.get("mcpServers", {}).get("memory-palace", {})
            command = [server.get("command", ""), *(server.get("args") or [])]
            ok = _wrapper_binding_ok(command, allow_relative=True)
            return ok, str(config_path)
        return None, "not applicable"

    if not _user_mcp_supported(target_name):
        return None, "no user-scope MCP config is managed for this target"

    if target_name == "claude":
        config_path = Path.home() / ".claude.json"
        payload = read_json_file(config_path)
        project_block = payload.get("projects", {}).get(str(workspace_root()), {})
        server = project_block.get("mcpServers", {}).get("memory-palace", {})
        command = [server.get("command", ""), *(server.get("args") or [])]
        ok = server.get("type") == "stdio" and _wrapper_binding_ok(command, allow_relative=False)
        return ok, str(config_path)

    if target_name == "codex":
        config_path = Path.home() / ".codex" / "config.toml"
        if not config_path.is_file():
            return False, str(config_path)
        if tomllib is None:
            server = _parse_codex_memory_palace_block(config_path.read_text(encoding="utf-8"))
        else:
            payload = _read_codex_toml(config_path)
            server = payload.get("mcp_servers", {}).get("memory-palace", {})
        command = [server.get("command", ""), *(server.get("args") or [])]
        ok = _wrapper_binding_ok(command, allow_relative=False)
        return ok, str(config_path)

    if target_name == "gemini":
        config_path = Path.home() / ".gemini" / "settings.json"
        payload = read_json_file(config_path)
        server = payload.get("mcpServers", {}).get("memory-palace", {})
        command = [server.get("command", ""), *(server.get("args") or [])]
        ok = _wrapper_binding_ok(command, allow_relative=False)
        return ok, str(config_path)

    if target_name == "opencode":
        config_path = Path.home() / ".config" / "opencode" / "opencode.json"
        payload = read_json_file(config_path)
        server = payload.get("mcp", {}).get("memory-palace", {})
        command = list(server.get("command") or [])
        ok = bool(server.get("enabled")) and _wrapper_binding_ok(command, allow_relative=False)
        return ok, str(config_path)

    return None, "not applicable"


def _validate_frontmatter(source: Path) -> None:
    skill_file = source / "SKILL.md"
    text = skill_file.read_text(encoding="utf-8")
    frontmatter = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
    if not frontmatter:
        raise SystemExit(f"Missing YAML frontmatter in {skill_file}")
    block = frontmatter.group(1)
    name_match = re.search(r"(?m)^name:\s*(.+?)\s*$", block)
    description_match = re.search(r"(?m)^description:\s*(.+?)\s*$", block)
    if not name_match or name_match.group(1).strip().strip("\"'") != SKILL_NAME:
        raise SystemExit(f"Invalid skill name in {skill_file}")
    if not description_match or not description_match.group(1).strip():
        raise SystemExit(f"Missing description in {skill_file}")


def run_check(*, args: argparse.Namespace, targets: list[str], source: Path, base_dir: Path) -> int:
    _validate_frontmatter(source)
    ok_all = True
    print(f"Source: {source}")
    print(f"Scope: {args.scope} -> {base_dir}")
    for target_name in targets:
        ok, message = check_skill_target(
            target_name,
            base_dir=base_dir,
            source=source,
            scope=args.scope,
        )
        print(f"[{target_name}] SKILL {'OK' if ok else 'FAIL'} - {message}")
        ok_all &= ok
        if args.with_mcp:
            binding_ok, binding_message = check_mcp_binding(target_name, scope=args.scope)
            if binding_ok is None:
                print(f"[{target_name}] MCP NOTE - {binding_message}")
            else:
                print(f"[{target_name}] MCP {'OK' if binding_ok else 'FAIL'} - {binding_message}")
                ok_all &= binding_ok
    return 0 if ok_all else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    targets = resolve_targets(args.targets)
    source = source_dir()
    ensure_wrapper_script()

    if args.scope == "workspace":
        base_dir = workspace_root()
    else:
        base_dir = Path.home()

    if args.scope == "workspace" and "gemini" in targets:
        print(
            "WARN: workspace-local gemini installs can still be less reliable on some machines because "
            "Gemini may try to read hidden `.gemini/skills/...` paths. Prefer `--scope user` for Gemini "
            "if a local policy blocks hidden paths.",
            file=sys.stderr,
        )

    if args.mode == "symlink" and os.name == "nt":
        raise SystemExit("Symlink mode is not supported by default on Windows. Use --mode copy.")

    if args.check:
        return run_check(args=args, targets=targets, source=source, base_dir=base_dir)

    print(f"Source: {source}")
    print(f"Scope: {args.scope} -> {base_dir}")

    for target_name in targets:
        install_target(
            target_name,
            source=source,
            base_dir=base_dir,
            mode=args.mode,
            force=args.force,
            dry_run=args.dry_run,
        )
        if args.with_mcp:
            install_mcp_binding(target_name, scope=args.scope, dry_run=args.dry_run)

    print("Dry run complete." if args.dry_run else "Install complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
