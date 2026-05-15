from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy.engine import make_url


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _write_text(path: Path, content: str, *, newline: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline=newline) as handle:
        handle.write(content)


def _write_shell_script(path: Path, content: str) -> None:
    _write_text(
        path,
        content.replace("\r\n", "\n").replace("\r", ""),
        newline="\n",
    )
    path.chmod(0o755)


def _copy_script(source: Path, destination: Path) -> None:
    _write_shell_script(destination, source.read_text(encoding="utf-8"))


def _run_command(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )


def _popen_command(args: list[str], *, cwd: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _normalize_shell_path(path_text: str) -> Path:
    normalized = path_text.replace("\\", "/")
    if match := re.fullmatch(r"/mnt/([a-zA-Z])/(.*)", normalized):
        drive, remainder = match.groups()
        return Path(f"{drive.upper()}:/{remainder}")
    if match := re.fullmatch(r"/([a-zA-Z]):/(.*)", normalized):
        drive, remainder = match.groups()
        return Path(f"{drive.upper()}:/{remainder}")
    if match := re.fullmatch(r"/([a-zA-Z])/(.*)", normalized):
        drive, remainder = match.groups()
        return Path(f"{drive.upper()}:/{remainder}")
    return Path(normalized)


def _normalize_sqlite_database_path(database_path: str) -> Path:
    return _normalize_shell_path(database_path)


def _assert_sqlite_url_points_to_path(database_url: str, expected_path: Path) -> None:
    assert database_url.startswith("sqlite+aiosqlite:///")
    actual_database = make_url(database_url).database
    assert isinstance(actual_database, str)
    assert _normalize_sqlite_database_path(actual_database) == expected_path


def _assert_env_file_permissions(file_path: Path) -> None:
    mode = stat.S_IMODE(file_path.stat().st_mode)
    if os.name == "nt":
        assert mode & 0o111 == 0
        return
    assert mode == 0o600


def test_apply_profile_shell_keeps_database_url_valid_when_repo_path_has_spaces(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo with spaces"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "macos" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////Users/<your-user>/memory_palace/agent_memory.db",
                "SEARCH_DEFAULT_MODE=hybrid",
                "RETRIEVAL_EMBEDDING_BACKEND=hash",
                "RETRIEVAL_RERANKER_ENABLED=false",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_command(
        ["bash", "scripts/apply_profile.sh", "macos", "b", ".env.generated"],
        cwd=project_root,
    )

    assert result.returncode == 0, result.stderr
    generated_env = project_root / ".env.generated"
    database_url = dotenv_values(generated_env).get("DATABASE_URL")
    assert isinstance(database_url, str)
    _assert_sqlite_url_points_to_path(database_url, project_root / "demo.db")


def test_apply_profile_shell_rewrites_database_url_when_placeholder_has_spacing_and_comment(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "macos" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL = sqlite+aiosqlite:////Users/<your-user>/memory_palace/agent_memory.db  # local template placeholder",
                "SEARCH_DEFAULT_MODE=hybrid",
                "RETRIEVAL_EMBEDDING_BACKEND=hash",
                "RETRIEVAL_RERANKER_ENABLED=false",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_command(
        ["bash", "scripts/apply_profile.sh", "macos", "b", ".env.generated"],
        cwd=project_root,
    )

    assert result.returncode == 0, result.stderr
    generated_env = project_root / ".env.generated"
    generated_text = generated_env.read_text(encoding="utf-8")
    database_url = dotenv_values(generated_env).get("DATABASE_URL")
    assert isinstance(database_url, str)
    _assert_sqlite_url_points_to_path(database_url, project_root / "demo.db")
    assert "<your-user>" not in generated_text
    assert "DATABASE_URL =" not in generated_text


def test_apply_profile_shell_rewrites_database_url_when_user_placeholder_name_changes(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "macos" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////Users/<local-user>/memory_palace/agent_memory.db",
                "SEARCH_DEFAULT_MODE=hybrid",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_command(
        ["bash", "scripts/apply_profile.sh", "macos", "b", ".env.generated"],
        cwd=project_root,
    )

    assert result.returncode == 0, result.stderr
    database_url = dotenv_values(project_root / ".env.generated").get("DATABASE_URL")
    assert isinstance(database_url, str)
    _assert_sqlite_url_points_to_path(database_url, project_root / "demo.db")


def test_apply_profile_shell_linux_keeps_local_template_selection_but_writes_host_path(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "linux" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////home/<your-user>/memory_palace/agent_memory.db",
                "SEARCH_DEFAULT_MODE=hybrid",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_command(
        ["bash", "scripts/apply_profile.sh", "linux", "b", ".env.generated"],
        cwd=project_root,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    database_url = dotenv_values(project_root / ".env.generated").get("DATABASE_URL")
    assert isinstance(database_url, str)
    _assert_sqlite_url_points_to_path(database_url, project_root / "demo.db")


def test_apply_profile_shell_linux_rewrites_home_style_database_url_placeholder(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "linux" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////home/tester/memory_palace/agent_memory.db",
                "SEARCH_DEFAULT_MODE=hybrid",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_command(
        ["bash", "scripts/apply_profile.sh", "linux", "b", ".env.generated"],
        cwd=project_root,
    )

    assert result.returncode == 0, result.stderr
    database_url = dotenv_values(project_root / ".env.generated").get("DATABASE_URL")
    assert isinstance(database_url, str)
    _assert_sqlite_url_points_to_path(database_url, project_root / "demo.db")


def test_apply_profile_shell_rejects_unresolved_profile_c_placeholders(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "macos" / "profile-c.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////Users/<your-user>/memory_palace/agent_memory.db",
                "ROUTER_API_BASE=http://127.0.0.1:PORT/v1",
                "ROUTER_API_KEY=replace-with-your-key",
                "ROUTER_EMBEDDING_MODEL=your-embedding-model-id",
                "RETRIEVAL_EMBEDDING_DIM=replace-with-your-embedding-dim",
                "RETRIEVAL_RERANKER_MODEL=your-reranker-model-id",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "scripts/apply_profile.sh", "macos", "c", ".env.generated"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "unresolved placeholders" in result.stderr
    assert "ROUTER_API_BASE=http://127.0.0.1:PORT/v1" in result.stderr
    assert "ROUTER_API_KEY=replace-with-your-key" in result.stderr
    assert "RETRIEVAL_EMBEDDING_DIM=replace-with-your-embedding-dim" in result.stderr


def test_apply_profile_shell_rejects_unresolved_profile_c_placeholders_with_spacing_and_comment(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "macos" / "profile-c.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////Users/<your-user>/memory_palace/agent_memory.db",
                "ROUTER_API_BASE = http://127.0.0.1:PORT/v1  # unresolved router endpoint",
                "ROUTER_API_KEY = replace-with-your-key  # unresolved key",
                "ROUTER_EMBEDDING_MODEL = your-embedding-model-id",
                "RETRIEVAL_EMBEDDING_DIM = replace-with-your-embedding-dim  # unresolved dim",
                "RETRIEVAL_RERANKER_MODEL = your-reranker-model-id  # unresolved model",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "scripts/apply_profile.sh", "macos", "c", ".env.generated"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "unresolved placeholders" in result.stderr
    assert "ROUTER_API_BASE = http://127.0.0.1:PORT/v1  # unresolved router endpoint" in result.stderr
    assert "ROUTER_API_KEY = replace-with-your-key  # unresolved key" in result.stderr
    assert "RETRIEVAL_EMBEDDING_DIM = replace-with-your-embedding-dim  # unresolved dim" in result.stderr


def test_apply_profile_shell_can_defer_profile_placeholder_validation_to_caller(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "docker" / "profile-c.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////app/data/memory_palace.db",
                "ROUTER_API_BASE=http://host.docker.internal:PORT/v1",
                "ROUTER_API_KEY=replace-with-your-key",
                "ROUTER_EMBEDDING_MODEL=your-embedding-model-id",
                "RETRIEVAL_EMBEDDING_DIM=replace-with-your-embedding-dim",
                "RETRIEVAL_RERANKER_MODEL=your-reranker-model-id",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "scripts/apply_profile.sh", "docker", "c", ".env.docker"],
        cwd=project_root,
        env={
            **os.environ,
            "MEMORY_PALACE_ALLOW_UNRESOLVED_PROFILE_PLACEHOLDERS": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "deferred profile placeholder validation to caller" in result.stdout
    values = dotenv_values(project_root / ".env.docker")
    assert values.get("ROUTER_API_BASE") == "http://host.docker.internal:PORT/v1"


def test_apply_profile_shell_accepts_windows_absolute_target_path_on_native_windows(
    tmp_path: Path,
) -> None:
    if os.name != "nt":
        pytest.skip("native Windows host required")

    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "docker" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////app/data/memory_palace.db",
                "SEARCH_DEFAULT_MODE=hybrid",
                "RETRIEVAL_EMBEDDING_BACKEND=hash",
                "RETRIEVAL_RERANKER_ENABLED=false",
                "",
            ]
        ),
        encoding="utf-8",
    )

    target_path = project_root / "generated" / "profile-b.env"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    result = _run_command(
        ["bash", "scripts/apply_profile.sh", "docker", "b", str(target_path.resolve())],
        cwd=project_root,
    )

    assert result.returncode == 0, result.stderr
    assert target_path.is_file()
    generated = dotenv_values(target_path)
    assert generated.get("SEARCH_DEFAULT_MODE") == "hybrid"
    assert generated.get("RETRIEVAL_EMBEDDING_BACKEND") == "hash"
    assert generated.get("MCP_API_KEY")


def test_apply_profile_shell_docker_profile_syncs_compose_wal_overrides(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "docker" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////app/data/memory_palace.db",
                "RUNTIME_WRITE_WAL_ENABLED=false",
                "RUNTIME_WRITE_JOURNAL_MODE=delete",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "scripts/apply_profile.sh", "docker", "b", ".env.docker"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    values = dotenv_values(project_root / ".env.docker")
    assert values.get("MEMORY_PALACE_DOCKER_WAL_ENABLED") == "false"
    assert values.get("MEMORY_PALACE_DOCKER_JOURNAL_MODE") == "delete"


def test_apply_profile_shell_defaults_docker_target_to_env_docker(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "docker" / "profile-a.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "DATABASE_URL=sqlite+aiosqlite:////app/data/memory_palace.db\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "scripts/apply_profile.sh", "docker", "a"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (project_root / ".env.docker").exists()
    assert not (project_root / ".env").exists()


def test_docker_one_click_shell_auto_allowlists_private_runtime_provider_hosts(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    docker_script_path = project_root / "scripts" / "docker_one_click.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "docker_one_click.sh", docker_script_path)

    fake_apply_profile = project_root / "scripts" / "apply_profile.sh"
    _write_shell_script(
        fake_apply_profile,
        """#!/usr/bin/env bash
set -euo pipefail
target_path="$3"
cat > "${target_path}" <<'EOF'
DATABASE_URL=sqlite+aiosqlite:////app/data/memory_palace.db
SEARCH_DEFAULT_MODE=hybrid
RETRIEVAL_EMBEDDING_BACKEND=router
RETRIEVAL_RERANKER_ENABLED=false
EOF
""",
    )

    fake_docker = project_root / "bin" / "docker"
    _write_shell_script(
        fake_docker,
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "compose" && "${2:-}" == "version" ]]; then
  exit 0
fi
if [[ "${1:-}" == "volume" && "${2:-}" == "inspect" ]]; then
  exit 1
fi
if [[ "${1:-}" == "ps" ]]; then
  format=""
  service="backend"
  prev=""
  for arg in "$@"; do
    if [[ "${prev}" == "--filter" && "${arg}" == *"com.docker.compose.service=frontend"* ]]; then
      service="frontend"
    fi
    if [[ "${prev}" == "--format" ]]; then
      format="${arg}"
    fi
    prev="${arg}"
  done
  case "${format}" in
    "{{.Ports}}")
      if [[ "${service}" == "frontend" ]]; then
        echo "0.0.0.0:3312->8080/tcp"
      else
        echo "0.0.0.0:18112->8000/tcp"
      fi
      ;;
    "{{.Names}}")
      if [[ "${service}" == "frontend" ]]; then
        echo "fake-frontend-1"
      else
        echo "fake-backend-1"
      fi
      ;;
  esac
  exit 0
fi
if [[ "${1:-}" == "port" ]]; then
  if [[ "${3:-}" == "8080" ]]; then
    echo "0.0.0.0:3312"
  else
    echo "0.0.0.0:18112"
  fi
  exit 0
fi
if [[ "${1:-}" == "compose" ]]; then
  args_text=" $* "
  if [[ "${args_text}" == *" port frontend 8080 "* ]]; then
    echo "0.0.0.0:3312"
  elif [[ "${args_text}" == *" port backend 8000 "* ]]; then
    echo "0.0.0.0:18112"
  fi
  exit 0
fi
exit 0
""",
    )

    (project_root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    target_env = project_root / ".env.docker"

    result = _run_command(
        [
            "bash",
            "scripts/docker_one_click.sh",
            "--profile",
            "c",
            "--frontend-port",
            "3312",
            "--backend-port",
            "18112",
            "--allow-runtime-env-injection",
            "--no-build",
        ],
        cwd=project_root,
        env={
            **os.environ,
            "PATH": f"{project_root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
            "COMPOSE_PROJECT_NAME": "mp-test-runtime-allowlist",
            "MEMORY_PALACE_DOCKER_ENV_FILE": str(target_env),
            "ROUTER_API_BASE": "http://127.0.0.1:8318/v1",
            "ROUTER_API_KEY": "router-key",
            "ROUTER_CHAT_MODEL": "gpt-5.4-mini",
            "RETRIEVAL_EMBEDDING_API_BASE": "http://10.88.1.144:11435/v1",
            "RETRIEVAL_EMBEDDING_API_KEY": "embed-key",
            "RETRIEVAL_EMBEDDING_MODEL": "qwen3-embedding:8b-q8_0-ctx8192",
            "RETRIEVAL_EMBEDDING_DIM": "1024",
            "RETRIEVAL_RERANKER_ENABLED": "true",
            "RETRIEVAL_RERANKER_API_BASE": "http://10.88.1.144:8080/v1",
            "RETRIEVAL_RERANKER_API_KEY": "rerank-key",
            "RETRIEVAL_RERANKER_MODEL": "Qwen3-Reranker-8B",
            "WRITE_GUARD_LLM_API_BASE": "http://10.88.1.144:8318/v1/chat/completions",
            "WRITE_GUARD_LLM_API_KEY": "llm-key",
            "WRITE_GUARD_LLM_MODEL": "gpt-5.4-mini",
            "INTENT_LLM_API_BASE": "http://localhost:8317/v1/chat/completions",
            "INTENT_LLM_API_KEY": "intent-key",
            "INTENT_LLM_MODEL": "gpt-5.4-mini",
        },
    )

    assert result.returncode == 0, result.stderr
    values = dotenv_values(target_env)
    assert values.get("ROUTER_API_BASE") == "http://host.docker.internal:8318/v1"
    assert values.get("RETRIEVAL_EMBEDDING_BACKEND") == "api"
    assert values.get("RETRIEVAL_EMBEDDING_API_BASE") == "http://10.88.1.144:11435/v1"
    assert values.get("RETRIEVAL_RERANKER_API_BASE") == "http://10.88.1.144:8080/v1"
    assert (
        values.get("INTENT_LLM_API_BASE")
        == "http://host.docker.internal:8317/v1/chat/completions"
    )
    assert (
        values.get("MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS")
        == "10.88.1.144,host.docker.internal"
    )
    assert "MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS appended 10.88.1.144" in result.stdout
    assert (
        "MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS appended host.docker.internal"
        in result.stdout
    )
    assert "ROUTER_API_BASE mapped loopback host to host.docker.internal" in result.stdout
    assert "INTENT_LLM_API_BASE mapped loopback host to host.docker.internal" in result.stdout


def test_docker_one_click_shell_rejects_runtime_injection_for_profile_b(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    shutil.copytree(PROJECT_ROOT / "scripts", project_root / "scripts")
    shutil.copy2(PROJECT_ROOT / ".env.example", project_root / ".env.example")
    _write_shell_script(
        project_root / "bin" / "docker",
        """#!/usr/bin/env bash
if [[ "${1:-}" == "compose" && "${2:-}" == "version" ]]; then
  echo "Docker Compose version v2.0.0"
  exit 0
fi
exit 0
""",
    )
    (project_root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    target_env = project_root / ".env.docker"

    result = _run_command(
        [
            "bash",
            "scripts/docker_one_click.sh",
            "--profile",
            "b",
            "--allow-runtime-env-injection",
            "--no-build",
        ],
        cwd=project_root,
        env={
            **os.environ,
            "PATH": f"{project_root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
            "COMPOSE_PROJECT_NAME": "mp-test-profile-b-injection",
            "MEMORY_PALACE_DOCKER_ENV_FILE": str(target_env),
            "ROUTER_API_BASE": "http://127.0.0.1:8318/v1",
        },
    )

    assert result.returncode == 1
    assert "--allow-runtime-env-injection is only supported for profile c/d" in result.stderr
    assert not target_env.exists()


def test_docker_one_click_shell_avoids_bash4_case_conversion() -> None:
    script_text = (PROJECT_ROOT / "scripts" / "docker_one_click.sh").read_text(
        encoding="utf-8"
    )

    assert ",," not in script_text


def test_apply_profile_shell_injects_runtime_auto_flush_default_when_profile_omits_it(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "macos" / "profile-c.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////Users/<your-user>/memory_palace/agent_memory.db",
                "SEARCH_DEFAULT_MODE=hybrid",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "scripts/apply_profile.sh", "macos", "c", ".env.generated"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    values = dotenv_values(project_root / ".env.generated")
    assert values.get("RUNTIME_AUTO_FLUSH_ENABLED") == "true"


def test_apply_profile_shell_tightens_generated_env_permissions(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "macos" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////Users/<your-user>/memory_palace/agent_memory.db",
                "SEARCH_DEFAULT_MODE=hybrid",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_command(
        ["bash", "scripts/apply_profile.sh", "macos", "b", ".env.generated"],
        cwd=project_root,
    )

    assert result.returncode == 0, result.stderr
    generated_env = project_root / ".env.generated"
    _assert_env_file_permissions(generated_env)


def test_apply_profile_shell_backs_up_existing_target_before_overwrite(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    existing_target = project_root / ".env.generated"
    existing_target.write_text("EXISTING_KEY=keep-me\n", encoding="utf-8")

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "macos" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////Users/<your-user>/memory_palace/agent_memory.db",
                "SEARCH_DEFAULT_MODE=hybrid",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "scripts/apply_profile.sh", "macos", "b", ".env.generated"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    backup_path = project_root / ".env.generated.bak"
    assert backup_path.read_text(encoding="utf-8") == "EXISTING_KEY=keep-me\n"
    assert "EXISTING_KEY=keep-me" not in existing_target.read_text(encoding="utf-8")
    assert "[backup] Existing .env.generated saved to .env.generated.bak" in result.stdout


def test_apply_profile_shell_normalizes_windows_absolute_target_path(
    tmp_path: Path,
) -> None:
    if os.name != "nt":
        pytest.skip("Windows absolute target path normalization is only relevant on native Windows hosts")

    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "docker" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////app/data/memory_palace.db",
                "SEARCH_DEFAULT_MODE=hybrid",
                "",
            ]
        ),
        encoding="utf-8",
    )

    expected_target = project_root / ".tmp" / "windows-target.generated.env"
    expected_target.parent.mkdir(parents=True, exist_ok=True)

    result = _run_command(
        [
            "bash",
            "scripts/apply_profile.sh",
            "docker",
            "b",
            expected_target.resolve().as_posix(),
        ],
        cwd=project_root,
    )

    assert result.returncode == 0, result.stderr
    assert expected_target.is_file()
    assert dotenv_values(expected_target).get("SEARCH_DEFAULT_MODE") == "hybrid"
    stray_matches = [
        item.name
        for item in project_root.iterdir()
        if item.is_file()
        and item != expected_target
        and "windows-target.generated.env" in item.name
    ]
    assert stray_matches == []


def test_apply_profile_shell_rejects_concurrent_writer_for_same_target(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "macos" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////Users/<your-user>/memory_palace/agent_memory.db",
                "SEARCH_DEFAULT_MODE=hybrid",
                "",
            ]
        ),
        encoding="utf-8",
    )

    lock_holder = _popen_command(
        [
            "bash",
            "-c",
            "mkdir -p .env.generated.lockdir && printf '%s\\n' $$ > .env.generated.lockdir/owner_pid && sleep 5",
        ],
        cwd=project_root,
    )
    time.sleep(0.5)

    try:
        result = _run_command(
            ["bash", "scripts/apply_profile.sh", "macos", "b", ".env.generated"],
            cwd=project_root,
        )
    finally:
        lock_holder.terminate()
        try:
            lock_holder.wait(timeout=5)
        except subprocess.TimeoutExpired:
            lock_holder.kill()
            lock_holder.wait(timeout=5)

    assert result.returncode == 1
    assert "another apply_profile.sh process is already writing .env.generated" in result.stderr


def test_apply_profile_shell_uses_target_adjacent_temp_files_and_locking_contract() -> None:
    script_text = (PROJECT_ROOT / "scripts" / "apply_profile.sh").read_text(
        encoding="utf-8"
    )

    assert "try_acquire_path_lock" in script_text
    assert "commit_adjacent_temp_file_with_retry()" in script_text
    assert 'mktemp_adjacent_file "${file_path}" "write"' in script_text
    assert 'mktemp_adjacent_file "${target_file}" "staged"' in script_text
    assert 'commit_adjacent_temp_file_with_retry "${tmp_file}" "${file_path}"' in script_text
    assert 'commit_adjacent_temp_file_with_retry "${staged_file}" "${target_file}"' in script_text
    assert "another apply_profile.sh process is already writing" in script_text


def test_apply_profile_shell_dry_run_prints_generated_env_without_touching_target(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.sh"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.sh", script_path)

    existing_target = project_root / ".env.generated"
    original_text = "EXISTING_KEY=keep-me\n"
    existing_target.write_text(original_text, encoding="utf-8")

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "macos" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////Users/<your-user>/memory_palace/agent_memory.db",
                "SEARCH_DEFAULT_MODE=hybrid",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "scripts/apply_profile.sh", "--dry-run", "macos", "b", ".env.generated"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "SEARCH_DEFAULT_MODE=hybrid" in result.stdout
    assert existing_target.read_text(encoding="utf-8") == original_text
    assert not (project_root / ".env.generated.bak").exists()
    assert "Generated .env.generated from" not in result.stdout


def test_apply_profile_powershell_dry_run_prints_generated_env_without_touching_target(
    tmp_path: Path,
) -> None:
    if shutil.which("pwsh") is None:
        pytest.skip("pwsh not available")

    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.ps1"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.ps1", script_path)

    existing_target = project_root / ".env.generated"
    original_text = "EXISTING_KEY=keep-me\n"
    existing_target.write_text(original_text, encoding="utf-8")

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "macos" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////Users/<your-user>/memory_palace/agent_memory.db",
                "SEARCH_DEFAULT_MODE=hybrid",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_command(
        [
            "pwsh",
            "-NoLogo",
            "-NoProfile",
            "-File",
            "scripts/apply_profile.ps1",
            "-Platform",
            "macos",
            "-Profile",
            "b",
            "-Target",
            ".env.generated",
            "-DryRun",
        ],
        cwd=project_root,
    )

    assert result.returncode == 0, result.stderr
    assert "SEARCH_DEFAULT_MODE=hybrid" in result.stdout
    assert existing_target.read_text(encoding="utf-8") == original_text
    assert "Generated .env.generated from" not in result.stdout


def test_apply_profile_powershell_defaults_docker_target_to_env_docker(
    tmp_path: Path,
) -> None:
    if shutil.which("pwsh") is None:
        pytest.skip("pwsh not available")

    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.ps1"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.ps1", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "docker" / "profile-a.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "DATABASE_URL=sqlite+aiosqlite:////app/data/memory_palace.db\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "pwsh",
            "-NoLogo",
            "-NoProfile",
            "-File",
            "scripts/apply_profile.ps1",
            "-Platform",
            "docker",
            "-Profile",
            "a",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (project_root / ".env.docker").exists()
    assert not (project_root / ".env").exists()


def test_apply_profile_powershell_linux_uses_dedicated_template_and_rewrites_host_database_url(
    tmp_path: Path,
) -> None:
    if shutil.which("pwsh") is None:
        pytest.skip("pwsh not available")

    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.ps1"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.ps1", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "linux" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////home/tester/memory_palace/agent_memory.db",
                "SEARCH_DEFAULT_MODE=hybrid",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "pwsh",
            "-NoLogo",
            "-NoProfile",
            "-File",
            "scripts/apply_profile.ps1",
            "-Platform",
            "linux",
            "-Profile",
            "b",
            "-Target",
            ".env.generated",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    generated_env = project_root / ".env.generated"
    database_url = dotenv_values(generated_env).get("DATABASE_URL")
    assert isinstance(database_url, str)
    _assert_sqlite_url_points_to_path(database_url, project_root / "demo.db")
    assert result.stderr == ""


def test_apply_profile_powershell_backs_up_existing_target_before_overwrite(
    tmp_path: Path,
) -> None:
    if shutil.which("pwsh") is None:
        pytest.skip("pwsh not available")

    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.ps1"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.ps1", script_path)

    existing_target = project_root / ".env.generated"
    existing_target.write_text("EXISTING_KEY=keep-me\n", encoding="utf-8")

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "macos" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////Users/<your-user>/memory_palace/agent_memory.db",
                "SEARCH_DEFAULT_MODE=hybrid",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "pwsh",
            "-NoLogo",
            "-NoProfile",
            "-File",
            "scripts/apply_profile.ps1",
            "-Platform",
            "macos",
            "-Profile",
            "b",
            "-Target",
            ".env.generated",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    backup_path = project_root / ".env.generated.bak"
    assert backup_path.read_text(encoding="utf-8") == "EXISTING_KEY=keep-me\n"
    assert "EXISTING_KEY=keep-me" not in existing_target.read_text(encoding="utf-8")
    assert "[backup] Existing .env.generated saved to .env.generated.bak" in result.stdout


def test_apply_profile_powershell_rejects_concurrent_writer_for_same_target(
    tmp_path: Path,
) -> None:
    if shutil.which("pwsh") is None:
        pytest.skip("pwsh not available")

    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.ps1"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.ps1", script_path)

    (project_root / ".env.example").write_text("MCP_API_KEY=\n", encoding="utf-8")
    profile_path = project_root / "deploy" / "profiles" / "macos" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite+aiosqlite:////Users/<your-user>/memory_palace/agent_memory.db",
                "SEARCH_DEFAULT_MODE=hybrid",
                "",
            ]
        ),
        encoding="utf-8",
    )

    lock_holder = _popen_command(
        [
            "pwsh",
            "-NoLogo",
            "-NoProfile",
            "-Command",
            (
                "$lockPath='.env.generated.lock'; "
                "$stream=[System.IO.File]::Open("
                "$lockPath,"
                "[System.IO.FileMode]::OpenOrCreate,"
                "[System.IO.FileAccess]::ReadWrite,"
                "[System.IO.FileShare]::None"
                "); "
                "Start-Sleep -Seconds 5; "
                "$stream.Dispose()"
            ),
        ],
        cwd=project_root,
    )
    time.sleep(0.5)

    try:
            result = _run_command(
                [
                    "pwsh",
                    "-NoLogo",
                "-NoProfile",
                "-File",
                "scripts/apply_profile.ps1",
                "-Platform",
                "macos",
                "-Profile",
                "b",
                "-Target",
                ".env.generated",
            ],
                cwd=project_root,
            )
    finally:
        lock_holder.terminate()
        try:
            lock_holder.wait(timeout=5)
        except subprocess.TimeoutExpired:
            lock_holder.kill()
            lock_holder.wait(timeout=5)

    assert result.returncode != 0
    stderr_text = re.sub(r"\x1b\[[0-9;]*m", "", result.stderr)
    assert "another apply_profile.ps1 process is already" in stderr_text
    assert "writing .env.generated; wait for it to finish before retrying." in stderr_text


def test_apply_profile_powershell_rejects_unresolved_database_url_placeholders(
    tmp_path: Path,
) -> None:
    if shutil.which("pwsh") is None:
        pytest.skip("pwsh not available")

    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "apply_profile.ps1"
    _copy_script(PROJECT_ROOT / "scripts" / "apply_profile.ps1", script_path)

    (project_root / ".env.example").write_text(
        "DATABASE_URL=sqlite+aiosqlite:////<still-placeholder>/memory_palace/demo.db\n",
        encoding="utf-8",
    )
    profile_path = project_root / "deploy" / "profiles" / "macos" / "profile-b.env"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text("SEARCH_DEFAULT_MODE=hybrid\n", encoding="utf-8")

    result = _run_command(
        [
            "pwsh",
            "-NoLogo",
            "-NoProfile",
            "-File",
            "scripts/apply_profile.ps1",
            "-Platform",
            "macos",
            "-Profile",
            "b",
            "-Target",
            ".env.generated",
        ],
        cwd=project_root,
    )

    assert result.returncode != 0
    assert "DATABASE_URL still contains unresolved placeholders" in result.stderr


def test_repo_local_stdio_wrapper_resolves_real_project_root_through_symlink(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "run_memory_palace_mcp_stdio.sh"
    backend_python = project_root / "backend" / ".venv" / "bin" / "python"

    _copy_script(PROJECT_ROOT / "scripts" / "run_memory_palace_mcp_stdio.sh", script_path)
    backend_python.parent.mkdir(parents=True, exist_ok=True)
    _write_shell_script(
        backend_python,
        "#!/usr/bin/env bash\nprintf '%s' \"$PWD\"\n",
    )

    link_dir = tmp_path / "symlink launch"
    link_dir.mkdir(parents=True, exist_ok=True)
    link_path = link_dir / "memory-palace-stdio"
    link_path.symlink_to(script_path)

    result = _run_command(
        ["bash", "./memory-palace-stdio"],
        cwd=link_dir,
        env={key: value for key, value in os.environ.items() if key != "DATABASE_URL"},
    )

    assert result.returncode == 0, result.stderr
    assert _normalize_shell_path(result.stdout) == project_root / "backend"


def test_repo_local_stdio_wrapper_prefers_env_file_remote_timeout_when_runtime_env_absent(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "run_memory_palace_mcp_stdio.sh"
    backend_python = project_root / "backend" / ".venv" / "bin" / "python"

    _copy_script(PROJECT_ROOT / "scripts" / "run_memory_palace_mcp_stdio.sh", script_path)
    backend_python.parent.mkdir(parents=True, exist_ok=True)
    _write_shell_script(
        backend_python,
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "if [[ \"${1:-}\" == \"-\" ]]; then",
                "  exec python3 \"$@\"",
                "fi",
                "printf '%s' \"${RETRIEVAL_REMOTE_TIMEOUT_SEC:-missing}\"",
                "",
            ]
        ),
    )

    (project_root / ".env").write_text(
        "RETRIEVAL_REMOTE_TIMEOUT_SEC=30\n",
        encoding="utf-8",
    )

    result = _run_command(
        ["bash", "scripts/run_memory_palace_mcp_stdio.sh"],
        cwd=project_root,
        env={key: value for key, value in os.environ.items() if key != "RETRIEVAL_REMOTE_TIMEOUT_SEC"},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "30"


def test_repo_local_stdio_wrapper_rejects_empty_database_url_in_env_file(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "run_memory_palace_mcp_stdio.sh"
    backend_python = project_root / "backend" / ".venv" / "bin" / "python"

    _copy_script(PROJECT_ROOT / "scripts" / "run_memory_palace_mcp_stdio.sh", script_path)
    backend_python.parent.mkdir(parents=True, exist_ok=True)
    _write_shell_script(
        backend_python,
        "#!/usr/bin/env bash\nprintf 'should-not-run'\n",
    )
    (project_root / ".env").write_text("DATABASE_URL=\n", encoding="utf-8")

    result = _run_command(
        ["bash", "scripts/run_memory_palace_mcp_stdio.sh"],
        cwd=project_root,
        env={key: value for key, value in os.environ.items() if key != "DATABASE_URL"},
    )

    assert result.returncode == 1
    assert "empty DATABASE_URL" in result.stderr
    assert result.stdout == ""


def test_repo_local_stdio_wrapper_reads_env_without_python_dotenv(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "run_memory_palace_mcp_stdio.sh"
    backend_python = project_root / "backend" / ".venv" / "bin" / "python"

    _copy_script(PROJECT_ROOT / "scripts" / "run_memory_palace_mcp_stdio.sh", script_path)
    backend_python.parent.mkdir(parents=True, exist_ok=True)
    _write_shell_script(
        backend_python,
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "if [[ \"${1:-}\" == \"-\" ]]; then",
                "  exec python3 -S \"$@\"",
                "fi",
                "printf '%s' \"${RETRIEVAL_REMOTE_TIMEOUT_SEC:-missing}\"",
                "",
            ]
        ),
    )

    (project_root / ".env").write_text(
        "RETRIEVAL_REMOTE_TIMEOUT_SEC=37\n",
        encoding="utf-8",
    )

    result = _run_command(
        ["bash", "scripts/run_memory_palace_mcp_stdio.sh"],
        cwd=project_root,
        env={key: value for key, value in os.environ.items() if key != "RETRIEVAL_REMOTE_TIMEOUT_SEC"},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "37"


def test_repo_local_stdio_wrapper_normalizes_double_slash_default_database_path(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "run_memory_palace_mcp_stdio.sh"
    backend_python = project_root / "backend" / ".venv" / "bin" / "python"

    _copy_script(PROJECT_ROOT / "scripts" / "run_memory_palace_mcp_stdio.sh", script_path)
    _write_text(
        script_path,
        script_path.read_text(encoding="utf-8").replace(
            'DEFAULT_DB_PATH="${PROJECT_ROOT}/demo.db"',
            'DEFAULT_DB_PATH="//tmp/memory-palace/demo.db"',
        ),
        newline="\n",
    )
    backend_python.parent.mkdir(parents=True, exist_ok=True)
    _write_shell_script(
        backend_python,
        "#!/usr/bin/env bash\nprintf '%s' \"${DATABASE_URL:-missing}\"\n",
    )

    result = _run_command(
        ["bash", "scripts/run_memory_palace_mcp_stdio.sh"],
        cwd=project_root,
        env={key: value for key, value in os.environ.items() if key != "DATABASE_URL"},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "sqlite+aiosqlite:////tmp/memory-palace/demo.db"


def test_repo_local_stdio_wrapper_exports_utf8_python_defaults(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "run_memory_palace_mcp_stdio.sh"
    backend_python = project_root / "backend" / ".venv" / "bin" / "python"

    _copy_script(PROJECT_ROOT / "scripts" / "run_memory_palace_mcp_stdio.sh", script_path)
    backend_python.parent.mkdir(parents=True, exist_ok=True)
    _write_shell_script(
        backend_python,
        "#!/usr/bin/env bash\nprintf '%s|%s' \"${PYTHONIOENCODING:-missing}\" \"${PYTHONUTF8:-missing}\"\n",
    )

    result = _run_command(
        ["bash", "scripts/run_memory_palace_mcp_stdio.sh"],
        cwd=project_root,
        env={
            key: value
            for key, value in os.environ.items()
            if key not in {"DATABASE_URL", "PYTHONIOENCODING", "PYTHONUTF8"}
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "utf-8|1"


def test_repo_local_stdio_wrapper_merges_local_hosts_into_no_proxy(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    script_path = project_root / "scripts" / "run_memory_palace_mcp_stdio.sh"
    backend_python = project_root / "backend" / ".venv" / "bin" / "python"

    _copy_script(PROJECT_ROOT / "scripts" / "run_memory_palace_mcp_stdio.sh", script_path)
    backend_python.parent.mkdir(parents=True, exist_ok=True)
    _write_shell_script(
        backend_python,
        (
            "#!/usr/bin/env bash\n"
            "printf '%s|%s|%s' "
            "\"${NO_PROXY:-missing}\" "
            "\"${no_proxy:-missing}\" "
            "\"${HTTP_PROXY:-missing}\"\n"
        ),
    )

    result = _run_command(
        ["bash", "scripts/run_memory_palace_mcp_stdio.sh"],
        cwd=project_root,
        env={
            key: value
            for key, value in os.environ.items()
            if key
            not in {
                "DATABASE_URL",
                "NO_PROXY",
                "no_proxy",
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            }
        }
        | {
            "NO_PROXY": "upper.internal",
            "no_proxy": "corp.internal",
            "HTTP_PROXY": "http://proxy.example:8080",
        },
    )

    assert result.returncode == 0, result.stderr
    no_proxy_upper, no_proxy_lower, http_proxy = result.stdout.split("|")
    assert http_proxy == "http://proxy.example:8080"
    assert no_proxy_upper == no_proxy_lower
    visible_entries = set(no_proxy_upper.split(","))
    # Native Windows -> WSL/Git Bash launches can collapse NO_PROXY/no_proxy into one
    # inherited key before the shell script runs, so keep the contract at "preserve at
    # least one inherited no_proxy value" plus the repo-local hosts we append.
    assert {"upper.internal", "corp.internal"} & visible_entries
    assert "localhost" in no_proxy_upper.split(",")
    assert "127.0.0.1" in no_proxy_upper.split(",")
    assert "::1" in no_proxy_upper.split(",")
    assert "host.docker.internal" in no_proxy_upper.split(",")
    assert no_proxy_upper.split(",").count("localhost") == 1


def test_apply_profile_powershell_declares_utf8_no_bom_and_placeholder_guard() -> None:
    script_text = (
        PROJECT_ROOT / "scripts" / "apply_profile.ps1"
    ).read_text(encoding="utf-8")

    assert ".SYNOPSIS" in script_text
    assert "[switch]$DryRun" in script_text
    assert "[Alias('Help', 'h', '?')]" in script_text
    assert "[switch]$ShowHelp" in script_text
    assert "Usage: ./scripts/apply_profile.ps1" in script_text
    assert "[ValidateSet('macos', 'linux', 'windows', 'docker')]" in script_text
    assert "$Platform = $Platform.ToLowerInvariant()" in script_text
    assert "[System.Text.UTF8Encoding]::new($false)" in script_text
    assert "function Write-LinesUtf8" in script_text
    assert "function New-AdjacentTempFile" in script_text
    assert "function Acquire-TargetFileLock" in script_text
    assert "function Release-TargetFileLock" in script_text
    assert "function Test-RetryableFileCommitException" in script_text
    assert "function Invoke-FileCommitWithRetry" in script_text
    assert "function Finalize-GeneratedEnvFile" in script_text
    assert "function Assert-ResolvedDatabaseUrlPlaceholder" in script_text
    assert "function Assert-ResolvedProfilePlaceholders" in script_text
    assert "function Sync-DockerWalOverrides" in script_text
    assert "function Ensure-DefaultEnvValue" in script_text
    assert '$Platform -in @(\'macos\', \'linux\')' in script_text
    assert "MEMORY_PALACE_DOCKER_WAL_ENABLED" in script_text
    assert "MEMORY_PALACE_DOCKER_JOURNAL_MODE" in script_text
    assert '$workingTarget = $Target' in script_text
    assert 'if ($DryRun.IsPresent) {' in script_text
    assert '$workingTarget = [System.IO.Path]::GetTempFileName()' in script_text
    assert "$targetLock = Acquire-TargetFileLock -TargetPath $Target" in script_text
    assert "$workingTarget = New-AdjacentTempFile -TargetPath $Target -Label 'staged'" in script_text
    assert "Finalize-GeneratedEnvFile -TempPath $workingTarget -DestinationPath $Target" in script_text
    assert "$win32Code = $Exception.HResult -band 0xFFFF" in script_text
    assert "$win32Code -in @(5, 32, 33)" in script_text
    assert "Start-Sleep -Milliseconds ($BaseDelayMilliseconds * $attempt)" in script_text
    assert "Release-TargetFileLock -LockInfo $targetLock" in script_text
    assert 'throw "[apply-profile-lock] another apply_profile.ps1 process is already writing $TargetPath; wait for it to finish before retrying."' in script_text
    assert 'Assert-ResolvedDatabaseUrlPlaceholder -FilePath $workingTarget -DisplayPath $Target' in script_text
    assert "[System.IO.File]::ReadAllText($workingTarget, $utf8NoBom)" in script_text
    assert "Remove-Item -Path $workingTarget -Force -ErrorAction SilentlyContinue" in script_text
    assert "Ensure-DefaultEnvValue -FilePath $workingTarget -Key 'RUNTIME_AUTO_FLUSH_ENABLED' -Value 'true'" in script_text
    assert "$line -match '^\\s*(ROUTER_API_BASE|RETRIEVAL_EMBEDDING_API_BASE|RETRIEVAL_RERANKER_API_BASE)\\s*=\\s*.*:PORT/'" in script_text
    assert "$line -match '=\\s*replace-with-your-key(\\s+#.*)?\\s*$'" in script_text
    assert "$line -match '=\\s*your-embedding-model-id(\\s+#.*)?\\s*$'" in script_text
    assert "$line -match '=\\s*replace-with-your-embedding-dim(\\s+#.*)?\\s*$'" in script_text
    assert "$line -match '=\\s*<provider-vector-dim>(\\s+#.*)?\\s*$'" in script_text
    assert "$line -match '=\\s*your-reranker-model-id(\\s+#.*)?\\s*$'" in script_text
    assert "$placeholderPattern = '^\\s*DATABASE_URL\\s*=\\s*sqlite\\+aiosqlite:////(Users|home)/[^/]+/memory_palace/agent_memory\\.db(\\s+#.*)?\\s*$'" in script_text
    assert "$placeholderPattern = '^\\s*DATABASE_URL\\s*=\\s*sqlite\\+aiosqlite:///C:/memory_palace/agent_memory\\.db(\\s+#.*)?\\s*$'" in script_text


def test_apply_profile_powershell_uses_target_adjacent_temp_files_and_locking_contract() -> None:
    script_text = (
        PROJECT_ROOT / "scripts" / "apply_profile.ps1"
    ).read_text(encoding="utf-8")

    assert "function New-AdjacentTempFile" in script_text
    assert "function Acquire-TargetFileLock" in script_text
    assert "function Release-TargetFileLock" in script_text
    assert "function Invoke-FileCommitWithRetry" in script_text
    assert "function Finalize-GeneratedEnvFile" in script_text
    assert "[apply-profile-lock] another apply_profile.ps1 process is already writing" in script_text
    assert "$targetLock = Acquire-TargetFileLock -TargetPath $Target" in script_text
    assert "$workingTarget = New-AdjacentTempFile -TargetPath $Target -Label 'staged'" in script_text
    assert "Finalize-GeneratedEnvFile -TempPath $workingTarget -DestinationPath $Target" in script_text
    assert "Invoke-FileCommitWithRetry -TargetPath $DestinationPath -Operation {" in script_text
    assert "[System.IO.File]::Replace($TempPath, $DestinationPath, $backupPath, $true)" in script_text
    assert "[System.IO.File]::Move($TempPath, $DestinationPath)" in script_text
    assert '$dryRunOutput = [System.IO.File]::ReadAllText($workingTarget, $utf8NoBom)' in script_text
    assert '[Console]::Out.Write($dryRunOutput)' in script_text


def test_docker_profiles_align_wal_defaults_with_compose_runtime_env() -> None:
    compose_text = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert (
        "RUNTIME_WRITE_WAL_ENABLED: ${MEMORY_PALACE_DOCKER_WAL_ENABLED:-true}"
        in compose_text
    )
    assert (
        "RUNTIME_WRITE_JOURNAL_MODE: ${MEMORY_PALACE_DOCKER_JOURNAL_MODE:-wal}"
        in compose_text
    )

    for profile_name in ("profile-a.env", "profile-b.env", "profile-c.env", "profile-d.env"):
        profile_text = (
            PROJECT_ROOT / "deploy" / "profiles" / "docker" / profile_name
        ).read_text(encoding="utf-8")
        assert "MEMORY_PALACE_DOCKER_WAL_ENABLED=true" in profile_text
        assert "MEMORY_PALACE_DOCKER_JOURNAL_MODE=wal" in profile_text
        assert "RUNTIME_WRITE_WAL_ENABLED=true" in profile_text
        assert "RUNTIME_WRITE_JOURNAL_MODE=wal" in profile_text


def test_profile_cd_templates_keep_auto_flush_enabled_for_local_platforms() -> None:
    for platform_name in ("macos", "windows"):
        for profile_name in ("profile-c.env", "profile-d.env"):
            profile_text = (
                PROJECT_ROOT / "deploy" / "profiles" / platform_name / profile_name
            ).read_text(encoding="utf-8")
            assert "RUNTIME_AUTO_FLUSH_ENABLED=true" in profile_text


def test_profile_cd_templates_require_user_supplied_embedding_dim_placeholder() -> None:
    for platform_name in ("macos", "linux", "windows", "docker"):
        for profile_name in ("profile-c.env", "profile-d.env"):
            profile_text = (
                PROJECT_ROOT / "deploy" / "profiles" / platform_name / profile_name
            ).read_text(encoding="utf-8")
            assert "RETRIEVAL_EMBEDDING_DIM=replace-with-your-embedding-dim" in profile_text
