from pathlib import Path
import shutil
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _pwsh_executable() -> str | None:
    candidates = [
        shutil.which("pwsh"),
        r"C:\Program Files\PowerShell\7\pwsh.exe",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return str(path)
    return None


def test_runtime_env_injection_covers_intent_llm_and_router_fallbacks() -> None:
    shell_text = (PROJECT_ROOT / "scripts" / "docker_one_click.sh").read_text(
        encoding="utf-8"
    )
    ps1_text = (PROJECT_ROOT / "scripts" / "docker_one_click.ps1").read_text(
        encoding="utf-8"
    )

    for literal in (
        "ROUTER_CHAT_MODEL",
        "ROUTER_RERANKER_MODEL",
        "RETRIEVAL_EMBEDDING_DIM",
        "RETRIEVAL_RERANKER_ENABLED",
        "MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS",
        "INTENT_LLM_ENABLED",
        "INTENT_LLM_API_BASE",
        "INTENT_LLM_API_KEY",
        "INTENT_LLM_MODEL",
        "WRITE_GUARD_LLM_API_BASE",
        "COMPACT_GIST_LLM_API_BASE",
        "--wait",
        "--wait-timeout",
        "RETRIEVAL_EMBEDDING_API_BASE copied from ROUTER_API_BASE",
        "RETRIEVAL_EMBEDDING_API_KEY copied from ROUTER_API_KEY",
        "RETRIEVAL_EMBEDDING_MODEL copied from ROUTER_EMBEDDING_MODEL",
        "RETRIEVAL_RERANKER_API_BASE copied from ROUTER_API_BASE",
        "RETRIEVAL_RERANKER_API_KEY copied from ROUTER_API_KEY",
        "RETRIEVAL_RERANKER_MODEL copied from ROUTER_RERANKER_MODEL",
        "append_provider_allowlist_host_from_api_base",
        "Append-ProviderAllowlistHostFromApiBase",
        "rewrite_loopback_api_base_for_docker",
        "Rewrite-LoopbackApiBaseForDocker",
        "mapped loopback host to host.docker.internal for docker runtime injection.",
    ):
        if literal == "Append-ProviderAllowlistHostFromApiBase":
            assert literal in ps1_text
            continue
        if literal == "append_provider_allowlist_host_from_api_base":
            assert literal in shell_text
            continue
        if literal == "Rewrite-LoopbackApiBaseForDocker":
            assert literal in ps1_text
            continue
        if literal == "rewrite_loopback_api_base_for_docker":
            assert literal in shell_text
            continue
        assert literal in shell_text
        assert literal in ps1_text

    assert "--no-build" in shell_text

    assert "wait_for_deployment_ready" in shell_text
    assert "Wait-DeploymentReady" in ps1_text
    assert "compose_project_has_any_container" in shell_text
    assert "Test-ComposeProjectHasAnyContainer" in ps1_text
    assert '--filter "label=com.docker.compose.project=${compose_project_name}"' in shell_text
    assert '--filter "label=com.docker.compose.service=${service}"' in shell_text
    assert "--format '{{.Ports}}'" in shell_text
    assert 'docker port "${container_name}" "${target_port}"' in shell_text
    assert '--filter "label=com.docker.compose.project=$ComposeProjectName"' in ps1_text
    assert '--filter "label=com.docker.compose.service=$Service"' in ps1_text
    assert "--format '{{.Ports}}'" in ps1_text
    assert "docker port $containerName $TargetPort" in ps1_text
    assert 'docker-compose.yml port "${service}" "${target_port}"' in shell_text
    assert "$portArgs += @('-f', 'docker-compose.yml', 'port', $Service, \"$TargetPort\")" in ps1_text
    assert 'upsert_env_value_in_file "${env_file}" "MEMORY_PALACE_FRONTEND_PORT" "${frontend_port}"' in shell_text
    assert 'upsert_env_value_in_file "${env_file}" "MEMORY_PALACE_BACKEND_PORT" "${backend_port}"' in shell_text
    assert 'planned_frontend_port="$(get_env_value_from_file "${env_file}" "MEMORY_PALACE_FRONTEND_PORT")"' in shell_text
    assert 'planned_backend_port="$(get_env_value_from_file "${env_file}" "MEMORY_PALACE_BACKEND_PORT")"' in shell_text
    assert "Set-EnvValueInFile -FilePath $envFile -Key 'MEMORY_PALACE_FRONTEND_PORT' -Value \"$FrontendPort\"" in ps1_text
    assert "Set-EnvValueInFile -FilePath $envFile -Key 'MEMORY_PALACE_BACKEND_PORT' -Value \"$BackendPort\"" in ps1_text
    assert "$plannedFrontendPort = Get-EnvValueFromFile -FilePath $envFile -Key 'MEMORY_PALACE_FRONTEND_PORT'" in ps1_text
    assert "$plannedBackendPort = Get-EnvValueFromFile -FilePath $envFile -Key 'MEMORY_PALACE_BACKEND_PORT'" in ps1_text
    assert "Get-Command -Name 'Get-NetTCPConnection'" in ps1_text
    assert "Get-Command -Name 'ss'" in ps1_text
    assert '& ss -ltnH "( sport = :$Port )"' in ps1_text
    assert "MEMORY_PALACE_ALLOW_UNRESOLVED_PROFILE_PLACEHOLDERS=1" in shell_text
    assert "MEMORY_PALACE_ALLOW_UNRESOLVED_PROFILE_PLACEHOLDERS = '1'" in ps1_text
    assert '${project_name}_data' in shell_text
    assert '${project_name}_snapshots' in shell_text
    assert "${projectName}_data" in ps1_text
    assert "${projectName}_snapshots" in ps1_text
    assert "Set MEMORY_PALACE_DATA_VOLUME=" in shell_text
    assert "Set MEMORY_PALACE_SNAPSHOTS_VOLUME=" in shell_text
    assert "Set MEMORY_PALACE_DATA_VOLUME=$legacyVolume" in ps1_text
    assert "Set MEMORY_PALACE_SNAPSHOTS_VOLUME=$legacyVolume" in ps1_text
    assert (
        "[compose-up] docker compose failed before creating any service container; "
        "skipping readiness probe." in shell_text
    )
    assert (
        "[compose-up] docker compose failed before creating any service container; "
        "skipping readiness probe." in ps1_text
    )


def test_one_click_scripts_share_compose_retry_backoff_contract() -> None:
    shell_text = (PROJECT_ROOT / "scripts" / "docker_one_click.sh").read_text(
        encoding="utf-8"
    )
    ps1_text = (PROJECT_ROOT / "scripts" / "docker_one_click.ps1").read_text(
        encoding="utf-8"
    )

    for literal in (
        "No such container",
        "dependency failed to start",
        "toomanyrequests",
        "TLS handshake timeout",
        "connection reset by peer",
        "i/o timeout",
        "context canceled",
        "EOF",
        "transient compose up failure",
    ):
        assert literal in shell_text
        assert literal in ps1_text

    assert "compose_error_is_retryable()" in shell_text
    assert "run_compose_with_retry()" in shell_text
    assert 'sleep_seconds=$((2 * attempt))' in shell_text
    assert 'sleep "${sleep_seconds}"' in shell_text
    assert (
        'run_compose_with_retry compose_up_args "${compose_project_name}" 3 "${env_file}"'
        in shell_text
    )
    assert (
        'COMPOSE_PROJECT_NAME="${compose_project_name}" "${compose_cmd[@]}" '
        '"${compose_env_file_args_local[@]}" -f docker-compose.yml down --remove-orphans'
        in shell_text
    )

    assert "function Test-ComposeRetryableError" in ps1_text
    assert "function Invoke-ComposeWithRetry" in ps1_text
    assert "Start-Sleep -Seconds $sleepSeconds" in ps1_text
    assert (
        "Invoke-ComposeWithRetry -ComposeArgs $composeUpArgs "
        "-ComposeProjectName $composeProjectName -MaxAttempts 3 -EnvFile $envFile"
        in ps1_text
    )


def test_powershell_one_click_env_io_uses_utf8_no_bom_helpers() -> None:
    ps1_text = (PROJECT_ROOT / "scripts" / "docker_one_click.ps1").read_text(
        encoding="utf-8"
    )

    assert "$utf8NoBom = [System.Text.UTF8Encoding]::new($false)" in ps1_text
    assert "function Read-LinesUtf8" in ps1_text
    assert "function Write-LinesUtf8" in ps1_text
    assert "[System.IO.File]::ReadAllLines($FilePath, $utf8NoBom)" in ps1_text
    assert "[System.IO.File]::WriteAllLines($FilePath, $Lines, $utf8NoBom)" in ps1_text
    assert "$line = Read-LinesUtf8 -FilePath $FilePath | Where-Object" in ps1_text
    assert "$lines = @(Read-LinesUtf8 -FilePath $FilePath)" in ps1_text
    assert "Write-LinesUtf8 -FilePath $FilePath -Lines $newLines" in ps1_text
    assert "Get-Content -Path $FilePath | Where-Object" not in ps1_text
    assert "Set-Content -Path $FilePath -Value $newLines" not in ps1_text


def test_powershell_one_click_validation_errors_exit_with_code_2_contract() -> None:
    ps1_text = (PROJECT_ROOT / "scripts" / "docker_one_click.ps1").read_text(
        encoding="utf-8"
    )

    assert "function Exit-ValidationError" in ps1_text
    assert "function Assert-ValidProfile" in ps1_text
    assert "function Resolve-PortValue" in ps1_text
    assert "exit 2" in ps1_text
    assert "$profileLower = Assert-ValidProfile -ProfileName $Profile" in ps1_text
    assert "$FrontendPort = Resolve-PortValue -Value $FrontendPort -Name 'FrontendPort'" in ps1_text
    assert "$BackendPort = Resolve-PortValue -Value $BackendPort -Name 'BackendPort'" in ps1_text


def test_powershell_one_click_invalid_profile_exits_with_code_2() -> None:
    pwsh_bin = _pwsh_executable()
    if not pwsh_bin:
        pytest.skip("PowerShell is not available")

    proc = subprocess.run(
        [
            pwsh_bin,
            "-NoLogo",
            "-NoProfile",
            "-File",
            str(PROJECT_ROOT / "scripts" / "docker_one_click.ps1"),
            "-Profile",
            "z",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert proc.returncode == 2
    assert "Unsupported profile" in proc.stderr


def test_powershell_one_click_invalid_frontend_port_exits_with_code_2() -> None:
    pwsh_bin = _pwsh_executable()
    if not pwsh_bin:
        pytest.skip("PowerShell is not available")

    proc = subprocess.run(
        [
            pwsh_bin,
            "-NoLogo",
            "-NoProfile",
            "-File",
            str(PROJECT_ROOT / "scripts" / "docker_one_click.ps1"),
            "-FrontendPort",
            "not-a-number",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert proc.returncode == 2
    assert "FrontendPort must be an integer" in proc.stderr


def test_one_click_scripts_resolve_custom_env_file_to_stable_absolute_paths() -> None:
    shell_text = (PROJECT_ROOT / "scripts" / "docker_one_click.sh").read_text(
        encoding="utf-8"
    )
    ps1_text = (PROJECT_ROOT / "scripts" / "docker_one_click.ps1").read_text(
        encoding="utf-8"
    )

    assert "resolve_stable_env_file_path()" in shell_text
    assert 'env_file="$(resolve_stable_env_file_path "${env_file}")"' in shell_text
    assert "pwd -P" in shell_text

    assert "function Resolve-StableEnvFilePath" in ps1_text
    assert "$envFile = Resolve-StableEnvFilePath -Path $envFile" in ps1_text
    assert "[System.IO.Path]::IsPathRooted($Path)" in ps1_text
    assert "Get-Location" in ps1_text


def test_powershell_one_click_cleans_runtime_state_on_preflight_failures() -> None:
    ps1_text = (PROJECT_ROOT / "scripts" / "docker_one_click.ps1").read_text(
        encoding="utf-8"
    )

    assert "function Restore-DockerRuntimeState" in ps1_text
    assert "$preflightComplete = $false" in ps1_text
    assert "if (-not $preflightComplete) {" in ps1_text
    assert "Restore-DockerRuntimeState" in ps1_text
    assert "[int]::TryParse($ownerPid, [ref]$ownerPidValue)" in ps1_text


def test_shell_one_click_normalizes_windows_absolute_env_paths_before_shell_io() -> None:
    shell_text = (PROJECT_ROOT / "scripts" / "docker_one_click.sh").read_text(
        encoding="utf-8"
    )

    assert "normalize_cli_path()" in shell_text
    assert "is_mangled_windows_absolute_path()" in shell_text
    assert "reconstruct_mangled_windows_path()" in shell_text
    assert 'cygpath -u "${raw_path}"' in shell_text
    assert 'wslpath -u "${raw_path}"' in shell_text
    assert 'printf \'%s\\n\' "${raw_path//\\\\//}"' in shell_text
    assert 'echo "Refusing mangled Windows absolute env file path:' in shell_text


def test_shell_one_click_env_upsert_uses_retrying_adjacent_commit_helper() -> None:
    shell_text = (PROJECT_ROOT / "scripts" / "docker_one_click.sh").read_text(
        encoding="utf-8"
    )

    assert "commit_adjacent_temp_file_with_retry()" in shell_text
    assert 'tmp_file="$(mktemp_adjacent_file "${env_file}" "upsert")"' in shell_text
    assert 'commit_adjacent_temp_file_with_retry "${tmp_file}" "${env_file}"' in shell_text


def test_one_click_readiness_probes_force_local_no_proxy_bypass() -> None:
    shell_text = (PROJECT_ROOT / "scripts" / "docker_one_click.sh").read_text(
        encoding="utf-8"
    )
    ps1_text = (PROJECT_ROOT / "scripts" / "docker_one_click.ps1").read_text(
        encoding="utf-8"
    )

    assert "build_local_no_proxy_value()" in shell_text
    assert '--noproxy "${effective_no_proxy}"' in shell_text
    assert 'NO_PROXY="${effective_no_proxy}" no_proxy="${effective_no_proxy}"' in shell_text

    assert "function Get-EffectiveNoProxyValue" in ps1_text
    assert "& curl.exe --noproxy $NoProxyValue -sS -o NUL -w '%{http_code}' $Url" in ps1_text
    assert "$env:NO_PROXY = $NoProxyValue" in ps1_text
    assert "$env:no_proxy = $NoProxyValue" in ps1_text

    for host in ("127.0.0.1", "localhost", "::1", "host.docker.internal"):
        assert host in shell_text
        assert host in ps1_text


def test_profile_external_settings_gate_checks_required_model_ids() -> None:
    shell_text = (PROJECT_ROOT / "scripts" / "docker_one_click.sh").read_text(
        encoding="utf-8"
    )
    ps1_text = (PROJECT_ROOT / "scripts" / "docker_one_click.ps1").read_text(
        encoding="utf-8"
    )

    for literal in (
        "your-embedding-model-id",
        "replace-with-your-embedding-dim",
        "<provider-vector-dim>",
        "your-reranker-model-id",
        "RETRIEVAL_EMBEDDING_MODEL",
        "RETRIEVAL_EMBEDDING_DIM",
        "RETRIEVAL_RERANKER_MODEL",
    ):
        assert literal in shell_text
        assert literal in ps1_text

    assert 'required_keys+=("ROUTER_API_BASE" "ROUTER_API_KEY" "RETRIEVAL_EMBEDDING_MODEL" "RETRIEVAL_EMBEDDING_DIM")' in shell_text
    assert 'required_keys+=("RETRIEVAL_EMBEDDING_API_BASE" "RETRIEVAL_EMBEDDING_API_KEY" "RETRIEVAL_EMBEDDING_MODEL" "RETRIEVAL_EMBEDDING_DIM")' in shell_text
    assert "$requiredKeys.Add('RETRIEVAL_EMBEDDING_DIM')" in ps1_text


def test_default_compose_project_name_uses_sha256_and_normalized_paths_in_both_scripts() -> None:
    shell_text = (PROJECT_ROOT / "scripts" / "docker_one_click.sh").read_text(
        encoding="utf-8"
    )
    ps1_text = (PROJECT_ROOT / "scripts" / "docker_one_click.ps1").read_text(
        encoding="utf-8"
    )

    assert "normalize_project_root_for_compose_name" in shell_text
    assert "cygpath -am" in shell_text
    assert "wslpath -m" in shell_text
    assert "hashlib.sha256" in shell_text
    assert "$normalizedProjectRoot = $projectRoot -replace '\\\\', '/'" in ps1_text
    assert "SHA256" in ps1_text


def test_compose_waits_for_healthy_sse_service() -> None:
    compose_text = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    backend_block = compose_text.split("\n  backend:\n", 1)[1].split("\n  frontend:\n", 1)[0]
    frontend_block = compose_text.split("\n  frontend:\n", 1)[1]

    assert "healthcheck:" in backend_block
    assert 'python", "/usr/local/bin/backend-healthcheck.py' in backend_block
    assert 'host.docker.internal:host-gateway' in backend_block
    assert "HOST: 0.0.0.0" in backend_block
    assert "# Docker defaults to WAL for the repository's named-volume deployment path." in backend_block
    assert "# If you replace these volumes with NFS/CIFS bind mounts, override both values." in backend_block
    assert "RUNTIME_WRITE_WAL_ENABLED: ${MEMORY_PALACE_DOCKER_WAL_ENABLED:-true}" in backend_block
    assert "RUNTIME_WRITE_JOURNAL_MODE: ${MEMORY_PALACE_DOCKER_JOURNAL_MODE:-wal}" in backend_block
    assert "\n  sse:\n" not in compose_text
    assert "backend:\n        condition: service_healthy" in frontend_block
    assert "CMD-SHELL" in frontend_block
    assert "unset http_proxy HTTP_PROXY https_proxy HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY" in frontend_block
    assert "wget -q -O /dev/null http://127.0.0.1:8080/" in frontend_block


def test_local_compose_uses_stable_image_names_for_no_build_reuse() -> None:
    compose_text = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    shell_text = (PROJECT_ROOT / "scripts" / "docker_one_click.sh").read_text(
        encoding="utf-8"
    )
    ps1_text = (PROJECT_ROOT / "scripts" / "docker_one_click.ps1").read_text(
        encoding="utf-8"
    )

    assert "image: ${MEMORY_PALACE_BACKEND_IMAGE:-memory-palace-backend:latest}" in compose_text
    assert "image: ${MEMORY_PALACE_FRONTEND_IMAGE:-memory-palace-frontend:latest}" in compose_text
    assert 'backend_image="${MEMORY_PALACE_BACKEND_IMAGE:-${local_image_namespace}-backend:latest}"' in shell_text
    assert 'frontend_image="${MEMORY_PALACE_FRONTEND_IMAGE:-${local_image_namespace}-frontend:latest}"' in shell_text
    assert 'export MEMORY_PALACE_BACKEND_IMAGE="${backend_image}"' in shell_text
    assert 'export MEMORY_PALACE_FRONTEND_IMAGE="${frontend_image}"' in shell_text
    assert "$backendImage = [System.Environment]::GetEnvironmentVariable('MEMORY_PALACE_BACKEND_IMAGE')" in ps1_text
    assert "$frontendImage = [System.Environment]::GetEnvironmentVariable('MEMORY_PALACE_FRONTEND_IMAGE')" in ps1_text
    assert '$env:MEMORY_PALACE_BACKEND_IMAGE = $backendImage' in ps1_text
    assert '$env:MEMORY_PALACE_FRONTEND_IMAGE = $frontendImage' in ps1_text


def test_shell_port_probe_falls_back_to_python_socket_bind() -> None:
    shell_text = (PROJECT_ROOT / "scripts" / "docker_one_click.sh").read_text(
        encoding="utf-8"
    )

    assert 'socket.socket(socket.AF_INET, socket.SOCK_STREAM)' in shell_text
    assert 'sock.bind(("127.0.0.1", port))' in shell_text
    assert 'sock.bind(("0.0.0.0", port))' not in shell_text
    assert "docker-compose.yml publishes admin ports on loopback only" in shell_text
    assert (
        "neither lsof/nc nor a usable python socket probe is available; "
        "fail-closed port probing is enabled."
    ) in shell_text


def test_shell_env_upsert_uses_env_adjacent_temp_file_for_atomic_replace() -> None:
    shell_text = (PROJECT_ROOT / "scripts" / "docker_one_click.sh").read_text(
        encoding="utf-8"
    )

    assert 'env_file="$(resolve_stable_env_file_path "${env_file}")"' in shell_text
    assert "mktemp_adjacent_file()" in shell_text
    assert 'target_dir="$(dirname "${target_path}")"' in shell_text
    assert 'target_name="$(basename "${target_path}")"' in shell_text
    assert 'tmp_file="$(mktemp_adjacent_file "${env_file}" "upsert")"' in shell_text


def test_one_click_scripts_fail_fast_on_risky_network_bind_mounts_with_wal() -> None:
    shell_text = (PROJECT_ROOT / "scripts" / "docker_one_click.sh").read_text(
        encoding="utf-8"
    )
    ps1_text = (PROJECT_ROOT / "scripts" / "docker_one_click.ps1").read_text(
        encoding="utf-8"
    )

    assert 'docker_env_requests_wal()' in shell_text
    assert 'collect_backend_bind_mounts_from_compose_config()' in shell_text
    assert 'filesystem_type_is_network_risky()' in shell_text
    assert 'assert_no_risky_wal_bind_mounts "${env_file}"' in shell_text
    assert "backend /app/data" in shell_text
    assert "MEMORY_PALACE_DOCKER_WAL_ENABLED=false and MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete" in shell_text
    assert "nfs|nfs4|cifs|smbfs|sshfs|fuse.sshfs|webdav|davfs|ceph|glusterfs" in shell_text

    assert "function Assert-BackendDataBindMountWalSafety" in ps1_text
    assert "function Get-BackendDataBindMountSourcesFromComposeConfig" in ps1_text
    assert "function Test-NetworkFilesystemSignal" in ps1_text
    assert "Assert-BackendDataBindMountWalSafety -ComposeProjectName $composeProjectName -EnvFile $envFile" in ps1_text
    assert "backend /app/data bind mount" in ps1_text
    assert "MEMORY_PALACE_DOCKER_WAL_ENABLED=false and MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete" in ps1_text
    assert "sshfs" in ps1_text
    assert "glusterfs" in ps1_text


def test_powershell_network_filesystem_signal_avoids_local_path_name_false_positives() -> None:
    ps1_text = (PROJECT_ROOT / "scripts" / "docker_one_click.ps1").read_text(
        encoding="utf-8"
    )

    assert "function Test-NetworkFilesystemSignal" in ps1_text
    assert "if ($normalizedPath -match '^(\\\\\\\\|//)') {" in ps1_text
    assert (
        "$normalizedPath -match "
        "'(^|[\\\\/])(nfs|cifs|smb|smbfs|sshfs|fuse\\.sshfs|webdav|davfs|ceph|glusterfs)([\\\\/]|$)'"
        not in ps1_text
    )
    assert "$normalizedSignal -eq 'network'" in ps1_text
    assert (
        "(?<![a-z])(nfs|nfs4|cifs|smb|smbfs|sshfs|fuse\\.sshfs|webdav|davfs|ceph|glusterfs)(?![a-z])"
        in ps1_text
    )


def test_shell_compose_bind_mount_parser_avoids_gnu_awk_only_capture_groups() -> None:
    shell_text = (PROJECT_ROOT / "scripts" / "docker_one_click.sh").read_text(
        encoding="utf-8"
    )

    assert "function extract_inline_type(" in shell_text
    assert "inline_type = extract_inline_type(value)" in shell_text
    assert "match(value, /type: ([^[:space:]]+)/, match_parts)" not in shell_text
    assert 'marker_index = index(normalized, "type:")' in shell_text
    assert 'normalized = substr(normalized, marker_index + length("type:"))' in shell_text
    assert 'sub(/[[:space:]].*$/, "", normalized)' in shell_text


def test_pull_based_ghcr_release_artifacts_exist() -> None:
    ghcr_compose = (PROJECT_ROOT / "docker-compose.ghcr.yml").read_text(
        encoding="utf-8"
    )
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "docker-publish.yml").read_text(
        encoding="utf-8"
    )

    assert "pull_policy: missing" in ghcr_compose
    assert "ghcr.io/agi-is-going-to-arrive/memory-palace-backend:latest" in ghcr_compose
    assert "ghcr.io/agi-is-going-to-arrive/memory-palace-frontend:latest" in ghcr_compose
    assert "docker/login-action" in workflow
    assert "docker/build-push-action" in workflow
    assert 'run: echo "owner_lc=${GITHUB_REPOSITORY_OWNER,,}" >> "$GITHUB_OUTPUT"' in workflow
    assert "ghcr.io/${{ steps.owner.outputs.owner_lc }}/memory-palace-${{ matrix.service }}" in workflow


def test_pull_based_ghcr_compose_matches_repo_two_service_topology() -> None:
    ghcr_compose = (PROJECT_ROOT / "docker-compose.ghcr.yml").read_text(
        encoding="utf-8"
    )
    frontend_block = ghcr_compose.split("\n  frontend:\n", 1)[1]

    assert "\n  sse:\n" not in ghcr_compose
    assert "backend:\n        condition: service_healthy" in frontend_block
    assert "sse:\n        condition: service_healthy" not in frontend_block
    assert "CMD-SHELL" in frontend_block
    assert "unset http_proxy HTTP_PROXY https_proxy HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY" in frontend_block
    assert "wget -q -O /dev/null http://127.0.0.1:8080/" in frontend_block


def test_backend_dockerfile_installs_healthcheck_script() -> None:
    dockerfile = (PROJECT_ROOT / "deploy" / "docker" / "Dockerfile.backend").read_text(
        encoding="utf-8"
    )

    assert "COPY deploy/docker/backend-healthcheck.py /usr/local/bin/backend-healthcheck.py" in dockerfile
    assert "chmod +x /usr/local/bin/backend-entrypoint.sh /usr/local/bin/backend-healthcheck.py" in dockerfile


def test_docker_publish_workflow_uses_repo_backend_venv_for_validation() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "docker-publish.yml").read_text(
        encoding="utf-8"
    )

    assert "python -m venv backend/.venv" in workflow
    assert "backend/.venv/bin/python -m pip install --upgrade pip" in workflow
    assert (
        "backend/.venv/bin/python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt"
        in workflow
    )
    assert "cd backend && .venv/bin/python -m pytest tests -q" in workflow


def test_docker_publish_workflow_builds_and_publishes_tag_refs_directly() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "docker-publish.yml").read_text(
        encoding="utf-8"
    )

    assert "concurrency:" in workflow
    assert "group: docker-publish-${{ github.sha }}" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "type=sha,prefix=sha-,format=short,enable=${{ github.ref_type != 'tag' }}" in workflow
    assert "type=ref,event=tag" in workflow
    assert "promote_tag:" not in workflow
    assert "docker buildx imagetools inspect" not in workflow
    assert "docker buildx imagetools create" not in workflow


def test_compose_volume_defaults_are_project_scoped() -> None:
    compose_text = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    ghcr_compose_text = (PROJECT_ROOT / "docker-compose.ghcr.yml").read_text(
        encoding="utf-8"
    )

    expected_data = "${MEMORY_PALACE_DATA_VOLUME:-${NOCTURNE_DATA_VOLUME:-${COMPOSE_PROJECT_NAME:-memory-palace}_data}}"
    expected_snapshots = "${MEMORY_PALACE_SNAPSHOTS_VOLUME:-${NOCTURNE_SNAPSHOTS_VOLUME:-${COMPOSE_PROJECT_NAME:-memory-palace}_snapshots}}"

    for text in (compose_text, ghcr_compose_text):
        assert expected_data in text
        assert expected_snapshots in text
        assert 'host.docker.internal:host-gateway' in text


def test_profile_d_templates_use_shell_safe_router_placeholders() -> None:
    for relative_path in (
        "deploy/profiles/macos/profile-d.env",
        "deploy/profiles/windows/profile-d.env",
        "deploy/profiles/docker/profile-d.env",
    ):
        text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "https://router.example.com/v1" in text
        assert "<your-router-host>" not in text


def test_frontend_nginx_template_disables_index_html_caching() -> None:
    template_text = (PROJECT_ROOT / "deploy" / "docker" / "nginx.conf.template").read_text(
        encoding="utf-8"
    )

    assert 'Content-Security-Policy "default-src \'self\'' in template_text
    assert "connect-src ${FRONTEND_CSP_CONNECT_SRC_NGINX_ESCAPED};" in template_text
    assert "object-src 'none'" in template_text
    assert "frame-ancestors 'none'" in template_text
    assert 'location = /index.html {' in template_text
    assert 'Cache-Control "no-store, no-cache, must-revalidate" always' in template_text
    assert "try_files /index.html =404;" in template_text


def test_optional_compose_override_example_exposes_resource_limit_knobs() -> None:
    override_text = (PROJECT_ROOT / "docker-compose.override.example.yml").read_text(
        encoding="utf-8"
    )

    assert "MEMORY_PALACE_BACKEND_MEM_LIMIT" in override_text
    assert "MEMORY_PALACE_BACKEND_CPUS" in override_text
    assert "MEMORY_PALACE_FRONTEND_MEM_LIMIT" in override_text
    assert "MEMORY_PALACE_FRONTEND_CPUS" in override_text
