#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

profile="b"
no_build=0
frontend_port="${MEMORY_PALACE_FRONTEND_PORT:-${NOCTURNE_FRONTEND_PORT:-3000}}"
backend_port="${MEMORY_PALACE_BACKEND_PORT:-${NOCTURNE_BACKEND_PORT:-18000}}"
auto_port=1
allow_runtime_env_injection=0
port_probe_fallback_warned=0
FRONTEND_PORT_LOCK=""
BACKEND_PORT_LOCK=""
DEPLOYMENT_LOCK=""
TEMP_DOCKER_ENV_FILE=""
TEMP_DOCKER_ENV_FILE_AUTO=0
compose_project_name=""

normalize_project_root_for_compose_name() {
  local raw_path="$1"
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -am "${raw_path}"
    return 0
  fi
  if command -v wslpath >/dev/null 2>&1; then
    case "${raw_path}" in
      /mnt/[a-zA-Z]/*|/[a-zA-Z]/*)
        wslpath -m "${raw_path}"
        return 0
        ;;
    esac
  fi
  printf '%s\n' "${raw_path//\\//}"
}

compose_project_path_checksum() {
  local normalized_path="$1"
  if command -v python3 >/dev/null 2>&1; then
    PROJECT_ROOT_HASH_INPUT="${normalized_path}" python3 - <<'PY'
import hashlib
import os

print(hashlib.sha256(os.environ["PROJECT_ROOT_HASH_INPUT"].encode("utf-8")).hexdigest()[:8])
PY
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    PROJECT_ROOT_HASH_INPUT="${normalized_path}" python - <<'PY'
import hashlib
import os

print(hashlib.sha256(os.environ["PROJECT_ROOT_HASH_INPUT"].encode("utf-8")).hexdigest()[:8])
PY
    return 0
  fi
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "${normalized_path}" | sha256sum | awk '{print substr($1, 1, 8)}'
    return 0
  fi
  if command -v shasum >/dev/null 2>&1; then
    printf '%s' "${normalized_path}" | shasum -a 256 | awk '{print substr($1, 1, 8)}'
    return 0
  fi
  if command -v openssl >/dev/null 2>&1; then
    printf '%s' "${normalized_path}" | openssl dgst -sha256 | awk '{print substr($NF, 1, 8)}'
    return 0
  fi
  echo "Unable to derive default compose project name: need python, sha256sum, shasum, or openssl." >&2
  return 1
}

default_compose_project_name() {
  local project_slug normalized_project_root path_checksum
  project_slug="$(
    basename "${PROJECT_ROOT}" \
      | tr '[:upper:]' '[:lower:]' \
      | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//'
  )"
  if [[ -z "${project_slug}" ]]; then
    project_slug="memory-palace"
  fi
  normalized_project_root="$(normalize_project_root_for_compose_name "${PROJECT_ROOT}")"
  path_checksum="$(compose_project_path_checksum "${normalized_project_root}")" || return 1
  echo "${project_slug}-${path_checksum}"
}

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/docker_one_click.sh [--profile a|b|c|d] [--frontend-port <port>] [--backend-port <port>] [--no-auto-port] [--no-build] [--allow-runtime-env-injection]
USAGE
}

is_positive_int() {
  [[ "$1" =~ ^[0-9]+$ ]] && [[ "$1" -ge 1 ]] && [[ "$1" -le 65535 ]]
}

try_acquire_path_lock() {
  local target_path="$1"
  local lock_dir="${target_path}.lockdir"
  local owner_file="${lock_dir}/owner_pid"
  local owner_pid=""

  mkdir -p "$(dirname "${target_path}")" >/dev/null 2>&1 || true

  if mkdir "${lock_dir}" 2>/dev/null; then
    printf '%s\n' "${BASHPID:-$$}" > "${owner_file}" 2>/dev/null || true
    echo "${lock_dir}"
    return 0
  fi

  if [[ -f "${owner_file}" ]]; then
    owner_pid="$(cat "${owner_file}" 2>/dev/null || true)"
  fi
  if [[ -n "${owner_pid}" ]] && ! kill -0 "${owner_pid}" 2>/dev/null; then
    rm -rf "${lock_dir}" >/dev/null 2>&1 || true
    if mkdir "${lock_dir}" 2>/dev/null; then
      printf '%s\n' "${BASHPID:-$$}" > "${owner_file}" 2>/dev/null || true
      echo "${lock_dir}"
      return 0
    fi
  fi

  return 1
}

release_path_lock() {
  local lock_dir="$1"
  if [[ -n "${lock_dir}" ]]; then
    rm -rf "${lock_dir}" >/dev/null 2>&1 || true
  fi
}

port_in_use() {
  local port="$1"
  if command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
    local python_candidate=""
    local probe_status=0
    if command -v python3 >/dev/null 2>&1; then
      python_candidate="python3"
    else
      python_candidate="python"
    fi
    if "${python_candidate}" - "${port}" <<'PY' >/dev/null 2>&1
import errno
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    # docker-compose.yml publishes admin ports on loopback only. Probe the same
    # address so a service bound only to another host IP does not block setup.
    sock.bind(("127.0.0.1", port))
except OSError as exc:
    if exc.errno == errno.EADDRINUSE:
        raise SystemExit(0)
    raise SystemExit(2)
finally:
    sock.close()

raise SystemExit(1)
PY
    then
      probe_status=0
    else
      probe_status=$?
    fi
    case "${probe_status}" in
      0) return 0 ;;
      1) return 1 ;;
    esac
  fi
  if command -v nc >/dev/null 2>&1; then
    nc -z 127.0.0.1 "${port}" >/dev/null 2>&1
    return $?
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP@127.0.0.1:"${port}" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi
  if [[ "${port_probe_fallback_warned}" -eq 0 ]]; then
    echo "[port-probe] neither lsof/nc nor a usable python socket probe is available; fail-closed port probing is enabled." >&2
    port_probe_fallback_warned=1
  fi
  return 0
}

find_free_port() {
  local start_port="$1"
  local max_scan="${2:-200}"
  local exclude_port="${3:-}"
  local current="$start_port"
  local i
  local lock_dir=""

  for ((i = 0; i <= max_scan; i++)); do
    if [[ "${current}" -gt 65535 ]]; then
      break
    fi
    if [[ -n "${exclude_port}" && "${current}" -eq "${exclude_port}" ]]; then
      current=$((current + 1))
      continue
    fi
    if ! port_in_use "${current}"; then
      lock_dir="$(try_acquire_path_lock "${TMPDIR:-/tmp}/memory-palace-port-locks/port-${current}" || true)"
      if [[ -n "${lock_dir}" ]]; then
        if ! port_in_use "${current}"; then
          printf '%s %s\n' "${current}" "${lock_dir}"
          return 0
        fi
        release_path_lock "${lock_dir}"
      fi
    fi
    current=$((current + 1))
  done

  echo "" >&2
  return 1
}

resolve_stable_env_file_path() {
  local raw_path="$1"
  local original_path="${1:-}"
  local reconstructed_path=""

  if [[ -z "${raw_path}" ]]; then
    printf '%s\n' "${raw_path}"
    return 0
  fi

  raw_path="$(normalize_cli_path "${raw_path}")"
  if is_mangled_windows_absolute_path "${raw_path}"; then
    if reconstructed_path="$(reconstruct_mangled_windows_path "${raw_path}")"; then
      raw_path="${reconstructed_path}"
    else
      echo "Refusing mangled Windows absolute env file path: ${original_path}" >&2
      echo "bash received it without directory separators before docker_one_click.sh could normalize it." >&2
      echo "Re-run with C:/... or a repo-relative POSIX path instead." >&2
      return 1
    fi
  fi

  case "${raw_path}" in
    /*|[a-zA-Z]:[\\/]*|\\\\*|//*)
      printf '%s\n' "${raw_path}"
      return 0
      ;;
  esac

  if command -v python3 >/dev/null 2>&1; then
    RAW_ENV_FILE_PATH="${raw_path}" python3 - <<'PY'
import os

print(os.path.abspath(os.environ["RAW_ENV_FILE_PATH"]))
PY
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    RAW_ENV_FILE_PATH="${raw_path}" python - <<'PY'
import os

print(os.path.abspath(os.environ["RAW_ENV_FILE_PATH"]))
PY
    return 0
  fi

  printf '%s/%s\n' "$(pwd -P)" "${raw_path}"
}

normalize_cli_path() {
  local raw_path="${1:-}"
  if [[ -z "${raw_path}" ]]; then
    printf '%s\n' "${raw_path}"
    return 0
  fi

  if [[ "${raw_path}" =~ ^[A-Za-z]:[\\/].* ]]; then
    if command -v cygpath >/dev/null 2>&1; then
      cygpath -u "${raw_path}"
      return 0
    fi
    if command -v wslpath >/dev/null 2>&1; then
      wslpath -u "${raw_path}"
      return 0
    fi
  fi

  printf '%s\n' "${raw_path//\\//}"
}

is_mangled_windows_absolute_path() {
  local raw_path="${1:-}"
  [[ "${raw_path}" =~ ^[A-Za-z]:[^/\\].* ]] && [[ ! "${raw_path}" =~ ^[A-Za-z]:[\\/].* ]]
}

reconstruct_mangled_windows_path() {
  local raw_path="${1:-}"
  local normalized="${raw_path//\\//}"
  if [[ ! "${normalized}" =~ ^([A-Za-z]):([^/].*)$ ]]; then
    return 1
  fi

  local drive="${BASH_REMATCH[1]}"
  local remainder="${BASH_REMATCH[2]}"
  local drive_root=""
  if command -v cygpath >/dev/null 2>&1; then
    drive_root="$(cygpath -u "${drive}:/" 2>/dev/null || true)"
  fi
  if [[ -z "${drive_root}" ]] && command -v wslpath >/dev/null 2>&1; then
    drive_root="$(wslpath -u "${drive}:/" 2>/dev/null || true)"
  fi
  if [[ -z "${drive_root}" || ! -d "${drive_root}" ]]; then
    return 1
  fi

  local current="${drive_root%/}"
  local remainder_value="${remainder}"
  local best_match=""
  local child=""
  local name=""
  shopt -s nullglob dotglob
  while [[ -n "${remainder_value}" && -d "${current}" ]]; do
    best_match=""
    for child in "${current}"/* "${current}"/.[!.]* "${current}"/..?*; do
      [[ -e "${child}" ]] || continue
      name="$(basename "${child}")"
      if [[ "${remainder_value}" == "${name}"* ]]; then
        if [[ -z "${best_match}" || ${#name} -gt ${#best_match} ]]; then
          best_match="${name}"
        fi
      fi
    done
    if [[ -z "${best_match}" ]]; then
      break
    fi
    current="${current}/${best_match}"
    remainder_value="${remainder_value#${best_match}}"
  done
  shopt -u nullglob dotglob

  if [[ -z "${remainder_value}" ]]; then
    printf '%s\n' "${current}"
    return 0
  fi
  if [[ -d "${current}" ]]; then
    printf '%s\n' "${current}/${remainder_value}"
    return 0
  fi
  return 1
}

mktemp_adjacent_file() {
  local target_path="$1"
  local label="${2:-tmp}"
  local target_dir target_name
  target_dir="$(dirname "${target_path}")"
  target_name="$(basename "${target_path}")"
  mkdir -p "${target_dir}" >/dev/null 2>&1 || true
  mktemp "${target_dir}/.${target_name}.${label}.XXXXXX"
}

append_no_proxy_entry() {
  local current_value="$1"
  local raw_entry="$2"
  local entry="${raw_entry#"${raw_entry%%[![:space:]]*}"}"
  local existing=""

  entry="${entry%"${entry##*[![:space:]]}"}"
  if [[ -z "${entry}" ]]; then
    printf '%s\n' "${current_value}"
    return 0
  fi

  IFS=',' read -r -a existing_entries <<< "${current_value}"
  for existing in "${existing_entries[@]}"; do
    existing="${existing#"${existing%%[![:space:]]*}"}"
    existing="${existing%"${existing##*[![:space:]]}"}"
    if [[ "${existing}" == "${entry}" ]]; then
      printf '%s\n' "${current_value}"
      return 0
    fi
  done

  if [[ -z "${current_value}" ]]; then
    printf '%s\n' "${entry}"
  else
    printf '%s,%s\n' "${current_value}" "${entry}"
  fi
}

extract_hostname_from_url() {
  local raw_url="${1:-}"
  local host_port=""

  if [[ -z "${raw_url}" ]]; then
    return 1
  fi

  host_port="${raw_url#*://}"
  host_port="${host_port%%/*}"
  host_port="${host_port##*@}"
  if [[ -z "${host_port}" ]]; then
    return 1
  fi

  if [[ "${host_port}" == \[*\]* ]]; then
    printf '%s\n' "${host_port#\[}" | sed 's/\]$//; s/\]:.*$//'
    return 0
  fi

  if [[ "${host_port}" == *:* ]] && [[ "${host_port##*:}" =~ ^[0-9]+$ ]]; then
    host_port="${host_port%:*}"
  fi

  if [[ "${host_port}" == *:* ]]; then
    return 1
  fi

  if [[ -z "${host_port}" ]]; then
    return 1
  fi

  printf '%s\n' "${host_port}"
}

rewrite_loopback_api_base_for_docker() {
  local raw_url="${1:-}"
  local provider_host provider_host_lower prefix rest authority path_suffix host_port userinfo suffix

  if [[ -z "${raw_url}" ]]; then
    return 1
  fi

  provider_host="$(extract_hostname_from_url "${raw_url}" || true)"
  provider_host_lower="$(printf '%s' "${provider_host}" | tr '[:upper:]' '[:lower:]')"
  case "${provider_host_lower}" in
    127.0.0.1|0.0.0.0|localhost|::1) ;;
    *)
      printf '%s\n' "${raw_url}"
      return 1
      ;;
  esac

  if [[ "${raw_url}" != *"://"* ]]; then
    printf '%s\n' "${raw_url}"
    return 1
  fi

  prefix="${raw_url%%://*}://"
  rest="${raw_url#*://}"
  authority="${rest%%/*}"
  path_suffix=""
  if [[ "${rest}" == */* ]]; then
    path_suffix="/${rest#*/}"
  fi

  host_port="${authority}"
  userinfo=""
  if [[ "${host_port}" == *@* ]]; then
    userinfo="${host_port%@*}@"
    host_port="${host_port##*@}"
  fi

  suffix=""
  if [[ "${provider_host_lower}" == "::1" ]]; then
    case "${host_port}" in
      "[::1]") suffix="" ;;
      "[::1]:"*) suffix="${host_port#"[::1]"}" ;;
      *)
        printf '%s\n' "${raw_url}"
        return 1
        ;;
    esac
  elif [[ "${host_port}" == "${provider_host}" ]]; then
    suffix=""
  elif [[ "${host_port}" == "${provider_host}:"* ]]; then
    suffix="${host_port#"${provider_host}"}"
  else
    printf '%s\n' "${raw_url}"
    return 1
  fi

  printf '%s%s%s%s%s\n' "${prefix}" "${userinfo}" "host.docker.internal" "${suffix}" "${path_suffix}"
  return 0
}

append_env_csv_value_in_file() {
  local env_file="$1"
  local key="$2"
  local raw_value="$3"
  local current_value updated_value

  current_value="$(get_env_value_from_file "${env_file}" "${key}")"
  updated_value="$(append_no_proxy_entry "${current_value}" "${raw_value}")"
  if [[ "${updated_value}" == "${current_value}" ]]; then
    return 1
  fi

  upsert_env_value_in_file "${env_file}" "${key}" "${updated_value}"
  return 0
}

rewrite_env_api_base_for_docker() {
  local env_file="$1"
  local key="$2"
  local current_value rewritten_value=""

  current_value="$(get_env_value_from_file "${env_file}" "${key}")"
  if [[ -z "${current_value}" ]]; then
    return 0
  fi

  rewritten_value="$(rewrite_loopback_api_base_for_docker "${current_value}")" || true
  if [[ -z "${rewritten_value}" || "${rewritten_value}" == "${current_value}" ]]; then
    return 0
  fi

  upsert_env_value_in_file "${env_file}" "${key}" "${rewritten_value}"
  echo "[override] ${key} mapped loopback host to host.docker.internal for docker runtime injection."
}

append_provider_allowlist_host_from_api_base() {
  local env_file="$1"
  local api_base="$2"
  local source_key="$3"
  local provider_host=""

  provider_host="$(extract_hostname_from_url "${api_base}" || true)"
  if [[ -z "${provider_host}" ]]; then
    return 0
  fi
  local provider_host_lower=""
  provider_host_lower="$(printf '%s' "${provider_host}" | tr '[:upper:]' '[:lower:]')"
  case "${provider_host_lower}" in
    127.0.0.1|0.0.0.0|::1|localhost)
      return 0
      ;;
  esac

  if append_env_csv_value_in_file \
    "${env_file}" \
    "MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS" \
    "${provider_host}"; then
    echo "[override] MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS appended ${provider_host} from ${source_key}."
  fi
}

build_local_no_proxy_value() {
  local effective_no_proxy=""
  local raw_group=""
  local entry=""

  for raw_group in "${NO_PROXY:-}" "${no_proxy:-}"; do
    IFS=',' read -r -a current_entries <<< "${raw_group}"
    for entry in "${current_entries[@]}"; do
      effective_no_proxy="$(append_no_proxy_entry "${effective_no_proxy}" "${entry}")"
    done
  done

  for entry in "127.0.0.1" "localhost" "::1" "host.docker.internal"; do
    effective_no_proxy="$(append_no_proxy_entry "${effective_no_proxy}" "${entry}")"
  done

  printf '%s\n' "${effective_no_proxy}"
}

wait_for_deployment_ready() {
  local attempts="${1:-30}"
  local sleep_seconds="${2:-2}"
  local probe_frontend_port="${3:-${frontend_port}}"
  local probe_backend_port="${4:-${backend_port}}"
  local backend_url="http://127.0.0.1:${probe_backend_port}/health"
  local frontend_url="http://127.0.0.1:${probe_frontend_port}/"
  local sse_url="http://127.0.0.1:${probe_frontend_port}/sse"
  local sse_status=""
  local attempt=0
  local effective_no_proxy=""

  effective_no_proxy="$(build_local_no_proxy_value)"

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if NO_PROXY="${effective_no_proxy}" no_proxy="${effective_no_proxy}" \
      curl --noproxy "${effective_no_proxy}" -fsS "${backend_url}" >/dev/null 2>&1 && \
      NO_PROXY="${effective_no_proxy}" no_proxy="${effective_no_proxy}" \
      curl --noproxy "${effective_no_proxy}" -fsS "${frontend_url}" >/dev/null 2>&1; then
      sse_status="$(
        NO_PROXY="${effective_no_proxy}" no_proxy="${effective_no_proxy}" \
          curl --noproxy "${effective_no_proxy}" -sS -o /dev/null -w '%{http_code}' "${sse_url}" || true
      )"
      if [[ "${sse_status}" == "200" || "${sse_status}" == "401" ]]; then
        return 0
      fi
    fi
    sleep "${sleep_seconds}"
  done

  return 1
}

compose_error_is_retryable() {
  local message="${1:-}"
  local patterns=(
    "No such container"
    "dependency failed to start"
    "toomanyrequests"
    "TLS handshake timeout"
    "connection reset by peer"
    "i/o timeout"
    "context canceled"
    "EOF"
  )
  local pattern=""

  if [[ -z "${message}" ]]; then
    return 1
  fi

  for pattern in "${patterns[@]}"; do
    if [[ "${message}" == *"${pattern}"* ]]; then
      return 0
    fi
  done

  return 1
}

run_compose_with_retry() {
  local compose_args_name="$1"
  local compose_project_name="$2"
  local max_attempts="${3:-3}"
  local env_file="${4:-}"
  local compose_env_file_args_local=()
  local compose_args=()
  local attempt=0
  local sleep_seconds=0
  local output=""
  local status=0
  local detail=""

  if [[ -n "${env_file}" ]]; then
    compose_env_file_args_local=(--env-file "${env_file}")
  fi

  eval "compose_args=(\"\${${compose_args_name}[@]}\")"

  while (( attempt < max_attempts )); do
    attempt=$((attempt + 1))

    set +e
    output="$(
      COMPOSE_PROJECT_NAME="${compose_project_name}" "${compose_cmd[@]}" "${compose_env_file_args_local[@]}" "${compose_args[@]}" 2>&1
    )"
    status=$?
    set -e

    if [[ ${status} -eq 0 ]]; then
      if [[ -n "${output}" ]]; then
        printf '%s\n' "${output}"
      fi
      return 0
    fi

    detail="docker compose command failed: ${compose_args[*]}"
    if [[ -n "${output}" ]]; then
      detail+=$'\n'"${output}"
    fi
    printf '%s\n' "${detail}" >&2

    if (( attempt >= max_attempts )) || ! compose_error_is_retryable "${detail}"; then
      return "${status}"
    fi

    sleep_seconds=$((2 * attempt))
    echo "[compose-retry] transient compose up failure (${attempt}/${max_attempts}), retrying in ${sleep_seconds}s." >&2
    sleep "${sleep_seconds}"
    if ! COMPOSE_PROJECT_NAME="${compose_project_name}" "${compose_cmd[@]}" "${compose_env_file_args_local[@]}" -f docker-compose.yml down --remove-orphans >/dev/null 2>&1; then
      :
    fi
  done

  return 1
}

compose_project_has_any_container() {
  local service="$1"
  docker ps -a \
    --filter "label=com.docker.compose.project=${compose_project_name}" \
    --filter "label=com.docker.compose.service=${service}" \
    --format '{{.Names}}' \
    | head -n 1 \
    | grep -q .
}

resolve_published_port_from_compose() {
  local service="$1"
  local target_port="$2"
  local fallback_port="$3"
  local attempts="${4:-10}"
  local attempt=1
  local container_name=""
  local port_output=""
  local ports_output=""
  local ports_regex=""

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    ports_output="$(
      docker ps \
        --filter "label=com.docker.compose.project=${compose_project_name}" \
        --filter "label=com.docker.compose.service=${service}" \
        --format '{{.Ports}}' \
        | head -n 1
    )"
    ports_output="${ports_output//$'\r'/}"
    ports_regex=":([0-9]+)->${target_port}/tcp"
    if [[ "${ports_output}" =~ ${ports_regex} ]]; then
      echo "${BASH_REMATCH[1]}"
      return 0
    fi

    container_name="$(
      docker ps \
        --filter "label=com.docker.compose.project=${compose_project_name}" \
        --filter "label=com.docker.compose.service=${service}" \
        --format '{{.Names}}' \
        | head -n 1
    )"
    if [[ -n "${container_name}" ]]; then
      port_output="$(docker port "${container_name}" "${target_port}" 2>/dev/null | head -n 1 || true)"
      port_output="${port_output//$'\r'/}"
      if [[ "${port_output}" =~ :([0-9]+)$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return 0
      fi
    fi

    if port_output="$(
      COMPOSE_PROJECT_NAME="${compose_project_name}" \
        "${compose_cmd[@]}" "${compose_env_file_args[@]}" -f docker-compose.yml port "${service}" "${target_port}" 2>/dev/null \
        | head -n 1
    )"; then
      port_output="${port_output//$'\r'/}"
      if [[ "${port_output}" =~ :([0-9]+)$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return 0
      fi
    fi

    if [[ "${attempt}" -lt "${attempts}" ]]; then
      sleep 1
    fi
  done

  echo "${fallback_port}"
}

cleanup_runtime_state() {
  release_path_lock "${FRONTEND_PORT_LOCK}"
  release_path_lock "${BACKEND_PORT_LOCK}"
  release_path_lock "${DEPLOYMENT_LOCK}"
  if [[ "${TEMP_DOCKER_ENV_FILE_AUTO}" -eq 1 && -n "${TEMP_DOCKER_ENV_FILE}" ]]; then
    rm -f "${TEMP_DOCKER_ENV_FILE}" >/dev/null 2>&1 || true
  fi
}

trap cleanup_runtime_state EXIT

resolve_data_volume() {
  local explicit_volume="${MEMORY_PALACE_DATA_VOLUME:-${NOCTURNE_DATA_VOLUME:-}}"
  if [[ -n "${explicit_volume}" ]]; then
    echo "${explicit_volume}"
    return 0
  fi

  local project_name="${compose_project_name:-${COMPOSE_PROJECT_NAME:-$(default_compose_project_name)}}"
  local default_volume="${project_name}_data"
  if docker volume inspect "${default_volume}" >/dev/null 2>&1; then
    echo "${default_volume}"
    return 0
  fi

  local legacy_candidates=(
    "memory_palace_data"
    "nocturne_data"
    "nocturne_memory_data"
  )
  local candidate
  for candidate in "${legacy_candidates[@]}"; do
    if ! docker volume inspect "${candidate}" >/dev/null 2>&1; then
      continue
    fi

    echo "[compat] found legacy shared docker volume '${candidate}', but defaulting to isolated volume '${default_volume}'. Set MEMORY_PALACE_DATA_VOLUME=${candidate} to reuse old data intentionally." >&2
    break
  done

  echo "${default_volume}"
}

resolve_snapshots_volume() {
  local explicit_volume="${MEMORY_PALACE_SNAPSHOTS_VOLUME:-${NOCTURNE_SNAPSHOTS_VOLUME:-}}"
  if [[ -n "${explicit_volume}" ]]; then
    echo "${explicit_volume}"
    return 0
  fi

  local project_name="${compose_project_name:-${COMPOSE_PROJECT_NAME:-$(default_compose_project_name)}}"
  local default_volume="${project_name}_snapshots"
  if docker volume inspect "${default_volume}" >/dev/null 2>&1; then
    echo "${default_volume}"
    return 0
  fi

  local legacy_candidates=(
    "memory_palace_snapshots"
    "nocturne_snapshots"
  )
  local candidate
  for candidate in "${legacy_candidates[@]}"; do
    if ! docker volume inspect "${candidate}" >/dev/null 2>&1; then
      continue
    fi

    echo "[compat] found legacy shared docker volume '${candidate}', but defaulting to isolated volume '${default_volume}'. Set MEMORY_PALACE_SNAPSHOTS_VOLUME=${candidate} to reuse old snapshots intentionally." >&2
    break
  done

  echo "${default_volume}"
}

get_env_value_from_file() {
  local env_file="$1"
  local key="$2"
  local raw
  env_file="$(resolve_stable_env_file_path "${env_file}")"
  raw="$(awk -F= -v target="${key}" '$1==target {print substr($0, index($0, "=") + 1)}' "${env_file}" | tail -n 1)"
  echo "${raw%$'\r'}"
}

commit_adjacent_temp_file_with_retry() {
  local source_path="$1"
  local target_path="$2"
  local attempt output status

  for attempt in 1 2 3; do
    if output="$(mv -f "${source_path}" "${target_path}" 2>&1)"; then
      return 0
    fi
    status=$?
    if (( attempt >= 3 )); then
      break
    fi
    sleep "0.$((attempt * 5))"
  done

  if [[ -n "${output:-}" ]]; then
    printf '%s\n' "${output}" >&2
  fi
  return "${status:-1}"
}

upsert_env_value_in_file() {
  local env_file="$1"
  local key="$2"
  local value="$3"
  local tmp_file
  env_file="$(resolve_stable_env_file_path "${env_file}")"
  tmp_file="$(mktemp_adjacent_file "${env_file}" "upsert")"
  awk -v target="${key}" -v replacement="${value}" '
    BEGIN { updated=0 }
    $0 ~ ("^" target "=") {
      if (updated == 0) {
        print target "=" replacement
        updated=1
      }
      next
    }
    { print }
    END {
      if (updated == 0) {
        print target "=" replacement
      }
    }
  ' "${env_file}" > "${tmp_file}"
  commit_adjacent_temp_file_with_retry "${tmp_file}" "${env_file}"
}

apply_profile_runtime_overrides() {
  local env_file="$1"
  local selected_profile="${2:-}"
  local override_keys=(
    "ROUTER_API_BASE"
    "ROUTER_API_KEY"
    "ROUTER_CHAT_MODEL"
    "ROUTER_EMBEDDING_MODEL"
    "ROUTER_RERANKER_MODEL"
    "RETRIEVAL_EMBEDDING_BACKEND"
    "RETRIEVAL_EMBEDDING_API_BASE"
    "RETRIEVAL_EMBEDDING_API_KEY"
    "RETRIEVAL_EMBEDDING_DIM"
    "RETRIEVAL_EMBEDDING_MODEL"
    "RETRIEVAL_RERANKER_ENABLED"
    "RETRIEVAL_RERANKER_API_BASE"
    "RETRIEVAL_RERANKER_API_KEY"
    "RETRIEVAL_RERANKER_MODEL"
    "WRITE_GUARD_LLM_ENABLED"
    "WRITE_GUARD_LLM_API_BASE"
    "WRITE_GUARD_LLM_API_KEY"
    "WRITE_GUARD_LLM_MODEL"
    "COMPACT_GIST_LLM_ENABLED"
    "COMPACT_GIST_LLM_API_BASE"
    "COMPACT_GIST_LLM_API_KEY"
    "COMPACT_GIST_LLM_MODEL"
    "INTENT_LLM_ENABLED"
    "INTENT_LLM_API_BASE"
    "INTENT_LLM_API_KEY"
    "INTENT_LLM_MODEL"
    "MEMORY_PALACE_ALLOWED_PRIVATE_PROVIDER_TARGETS"
    "MCP_API_KEY"
    "MCP_API_KEY_ALLOW_INSECURE_LOCAL"
  )
  local key
  for key in "${override_keys[@]}"; do
    local override_value="${!key:-}"
    if [[ -n "${override_value}" ]]; then
      upsert_env_value_in_file "${env_file}" "${key}" "${override_value}"
      echo "[override] ${key} applied to ${env_file}"
    fi
  done

  if [[ "${selected_profile}" == "c" || "${selected_profile}" == "d" ]]; then
    upsert_env_value_in_file "${env_file}" "RETRIEVAL_EMBEDDING_BACKEND" "api"
    echo "[override] RETRIEVAL_EMBEDDING_BACKEND=api forced for local profile ${selected_profile} runtime injection."

    if [[ -z "${RETRIEVAL_EMBEDDING_API_BASE:-}" && -n "${ROUTER_API_BASE:-}" ]]; then
      upsert_env_value_in_file "${env_file}" "RETRIEVAL_EMBEDDING_API_BASE" "${ROUTER_API_BASE}"
      echo "[override] RETRIEVAL_EMBEDDING_API_BASE copied from ROUTER_API_BASE for local profile ${selected_profile} runtime injection."
    fi
    if [[ -z "${RETRIEVAL_EMBEDDING_API_KEY:-}" && -n "${ROUTER_API_KEY:-}" ]]; then
      upsert_env_value_in_file "${env_file}" "RETRIEVAL_EMBEDDING_API_KEY" "${ROUTER_API_KEY}"
      echo "[override] RETRIEVAL_EMBEDDING_API_KEY copied from ROUTER_API_KEY for local profile ${selected_profile} runtime injection."
    fi
    if [[ -z "${RETRIEVAL_EMBEDDING_MODEL:-}" && -n "${ROUTER_EMBEDDING_MODEL:-}" ]]; then
      upsert_env_value_in_file "${env_file}" "RETRIEVAL_EMBEDDING_MODEL" "${ROUTER_EMBEDDING_MODEL}"
      echo "[override] RETRIEVAL_EMBEDDING_MODEL copied from ROUTER_EMBEDDING_MODEL for local profile ${selected_profile} runtime injection."
    fi
    if [[ -z "${RETRIEVAL_RERANKER_API_BASE:-}" && -n "${ROUTER_API_BASE:-}" ]]; then
      upsert_env_value_in_file "${env_file}" "RETRIEVAL_RERANKER_API_BASE" "${ROUTER_API_BASE}"
      echo "[override] RETRIEVAL_RERANKER_API_BASE copied from ROUTER_API_BASE for local profile ${selected_profile} runtime injection."
    fi
    if [[ -z "${RETRIEVAL_RERANKER_API_KEY:-}" && -n "${ROUTER_API_KEY:-}" ]]; then
      upsert_env_value_in_file "${env_file}" "RETRIEVAL_RERANKER_API_KEY" "${ROUTER_API_KEY}"
      echo "[override] RETRIEVAL_RERANKER_API_KEY copied from ROUTER_API_KEY for local profile ${selected_profile} runtime injection."
    fi
    if [[ -z "${RETRIEVAL_RERANKER_MODEL:-}" && -n "${ROUTER_RERANKER_MODEL:-}" ]]; then
      upsert_env_value_in_file "${env_file}" "RETRIEVAL_RERANKER_MODEL" "${ROUTER_RERANKER_MODEL}"
      echo "[override] RETRIEVAL_RERANKER_MODEL copied from ROUTER_RERANKER_MODEL for local profile ${selected_profile} runtime injection."
    fi

    rewrite_env_api_base_for_docker "${env_file}" "ROUTER_API_BASE"
    rewrite_env_api_base_for_docker "${env_file}" "RETRIEVAL_EMBEDDING_API_BASE"
    rewrite_env_api_base_for_docker "${env_file}" "RETRIEVAL_RERANKER_API_BASE"
    rewrite_env_api_base_for_docker "${env_file}" "WRITE_GUARD_LLM_API_BASE"
    rewrite_env_api_base_for_docker "${env_file}" "COMPACT_GIST_LLM_API_BASE"
    rewrite_env_api_base_for_docker "${env_file}" "INTENT_LLM_API_BASE"

    append_provider_allowlist_host_from_api_base \
      "${env_file}" \
      "$(get_env_value_from_file "${env_file}" "RETRIEVAL_EMBEDDING_API_BASE")" \
      "RETRIEVAL_EMBEDDING_API_BASE"
    append_provider_allowlist_host_from_api_base \
      "${env_file}" \
      "$(get_env_value_from_file "${env_file}" "RETRIEVAL_RERANKER_API_BASE")" \
      "RETRIEVAL_RERANKER_API_BASE"
    append_provider_allowlist_host_from_api_base \
      "${env_file}" \
      "$(get_env_value_from_file "${env_file}" "WRITE_GUARD_LLM_API_BASE")" \
      "WRITE_GUARD_LLM_API_BASE"
    append_provider_allowlist_host_from_api_base \
      "${env_file}" \
      "$(get_env_value_from_file "${env_file}" "COMPACT_GIST_LLM_API_BASE")" \
      "COMPACT_GIST_LLM_API_BASE"
    append_provider_allowlist_host_from_api_base \
      "${env_file}" \
      "$(get_env_value_from_file "${env_file}" "INTENT_LLM_API_BASE")" \
      "INTENT_LLM_API_BASE"
    append_provider_allowlist_host_from_api_base \
      "${env_file}" \
      "$(get_env_value_from_file "${env_file}" "ROUTER_API_BASE")" \
      "ROUTER_API_BASE"
  fi
}

is_truthy() {
  case "${1:-}" in
    1|true|yes|on|enabled|TRUE|YES|ON|ENABLED)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

value_has_unresolved_placeholder() {
  local value="$1"
  [[ "${value}" == *"replace-with-your-key"* ]] \
    || [[ "${value}" == *"replace-with-your-embedding-dim"* ]] \
    || [[ "${value}" == *"<provider-vector-dim>"* ]] \
    || [[ "${value}" == *"<your-router-host>"* ]] \
    || [[ "${value}" == *"host.docker.internal:PORT"* ]] \
    || [[ "${value}" == *"your-embedding-model-id"* ]] \
    || [[ "${value}" == *"your-reranker-model-id"* ]] \
    || [[ "${value}" =~ :PORT(/|$) ]]
}

assert_profile_external_settings_ready() {
  local env_file="$1"
  local selected_profile="$2"
  local found=0

  if [[ "${selected_profile}" != "c" && "${selected_profile}" != "d" ]]; then
    return 0
  fi

  local embedding_backend
  embedding_backend="$(get_env_value_from_file "${env_file}" "RETRIEVAL_EMBEDDING_BACKEND" | tr '[:upper:]' '[:lower:]')"
  local reranker_enabled_raw
  reranker_enabled_raw="$(get_env_value_from_file "${env_file}" "RETRIEVAL_RERANKER_ENABLED" | tr '[:upper:]' '[:lower:]')"

  local required_keys=()
  case "${embedding_backend}" in
    router)
      required_keys+=("ROUTER_API_BASE" "ROUTER_API_KEY" "RETRIEVAL_EMBEDDING_MODEL" "RETRIEVAL_EMBEDDING_DIM")
      ;;
    api|openai)
      required_keys+=("RETRIEVAL_EMBEDDING_API_BASE" "RETRIEVAL_EMBEDDING_API_KEY" "RETRIEVAL_EMBEDDING_MODEL" "RETRIEVAL_EMBEDDING_DIM")
      ;;
    hash|none|"")
      ;;
    *)
      required_keys+=("RETRIEVAL_EMBEDDING_API_BASE" "RETRIEVAL_EMBEDDING_API_KEY" "RETRIEVAL_EMBEDDING_MODEL" "RETRIEVAL_EMBEDDING_DIM")
      ;;
  esac
  if is_truthy "${reranker_enabled_raw}"; then
    required_keys+=("RETRIEVAL_RERANKER_API_BASE" "RETRIEVAL_RERANKER_API_KEY" "RETRIEVAL_RERANKER_MODEL")
  fi

  local key
  for key in "${required_keys[@]}"; do
    local value
    value="$(get_env_value_from_file "${env_file}" "${key}")"
    if [[ -z "${value}" ]]; then
      echo "[profile-check] Missing required value for ${key} (${selected_profile})" >&2
      found=1
      continue
    fi
    if value_has_unresolved_placeholder "${value}"; then
      echo "[profile-check] Unresolved placeholder for ${key}: ${value}" >&2
      found=1
    fi
  done

  if [[ "${found}" -eq 1 ]]; then
    echo "[profile-check] Profile ${selected_profile} has unresolved external settings in ${env_file}." >&2
    return 1
  fi
  return 0
}

get_env_override_or_file_value() {
  local env_file="$1"
  local key="$2"
  local default_value="${3:-}"
  local env_override="${!key:-}"
  if [[ -n "${env_override}" ]]; then
    printf '%s\n' "${env_override}"
    return 0
  fi
  local file_value
  file_value="$(get_env_value_from_file "${env_file}" "${key}")"
  if [[ -n "${file_value}" ]]; then
    printf '%s\n' "${file_value}"
    return 0
  fi
  printf '%s\n' "${default_value}"
}

docker_env_requests_wal() {
  local env_file="$1"
  local wal_enabled_raw
  local journal_mode_raw
  wal_enabled_raw="$(get_env_override_or_file_value "${env_file}" "MEMORY_PALACE_DOCKER_WAL_ENABLED" "true")"
  if ! is_truthy "${wal_enabled_raw}"; then
    return 1
  fi
  journal_mode_raw="$(get_env_override_or_file_value "${env_file}" "MEMORY_PALACE_DOCKER_JOURNAL_MODE" "wal")"
  journal_mode_raw="$(printf '%s' "${journal_mode_raw}" | tr '[:upper:]' '[:lower:]')"
  [[ "${journal_mode_raw}" == "wal" ]]
}

trim_wrapping_quotes() {
  local value="${1:-}"
  if [[ "${#value}" -ge 2 ]]; then
    if [[ "${value:0:1}" == "\"" && "${value: -1}" == "\"" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
      value="${value:1:${#value}-2}"
    fi
  fi
  printf '%s\n' "${value}"
}

target_affects_runtime_database() {
  local target="${1:-}"
  if [[ "${target}" == "/" ]]; then
    return 0
  fi
  target="${target%/}"
  if [[ -z "${target}" ]]; then
    return 1
  fi
  [[ "/app/data" == "${target}" || "/app/data" == "${target}/"* ]]
}

normalize_bind_source_path() {
  local source_path="${1:-}"
  source_path="$(trim_wrapping_quotes "${source_path}")"
  if [[ -z "${source_path}" ]]; then
    printf '%s\n' ""
    return 0
  fi
  if [[ "${source_path}" == "~"* ]]; then
    source_path="${HOME}${source_path:1}"
  fi
  case "${source_path}" in
    //*)
      printf '%s\n' "${source_path}"
      return 0
      ;;
    /*)
      printf '%s\n' "${source_path}"
      return 0
      ;;
  esac
  printf '%s\n' "${PROJECT_ROOT}/${source_path}"
}

resolve_existing_probe_path() {
  local candidate="${1:-}"
  if [[ -z "${candidate}" ]]; then
    return 1
  fi
  while [[ ! -e "${candidate}" ]]; do
    local parent
    parent="$(dirname "${candidate}")"
    if [[ -z "${parent}" || "${parent}" == "${candidate}" ]]; then
      return 1
    fi
    candidate="${parent}"
  done
  printf '%s\n' "${candidate}"
}

detect_filesystem_type() {
  local probe_path="${1:-}"
  local fs_type=""
  if fs_type="$(stat -f %T "${probe_path}" 2>/dev/null)" && [[ -n "${fs_type}" ]]; then
    printf '%s\n' "${fs_type}"
    return 0
  fi
  if fs_type="$(stat -f -c %T "${probe_path}" 2>/dev/null)" && [[ -n "${fs_type}" ]]; then
    printf '%s\n' "${fs_type}"
    return 0
  fi
  if fs_type="$(df -T "${probe_path}" 2>/dev/null | awk 'NR==2 {print $2}')" && [[ -n "${fs_type}" ]]; then
    printf '%s\n' "${fs_type}"
    return 0
  fi
  return 1
}

filesystem_type_is_network_risky() {
  local fs_type="${1:-}"
  fs_type="$(printf '%s' "${fs_type}" | tr '[:upper:]' '[:lower:]')"
  case "${fs_type}" in
    nfs|nfs4|cifs|smbfs|sshfs|fuse.sshfs|webdav|davfs|ceph|glusterfs)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_probable_network_bind_source() {
  local source_path="${1:-}"
  case "${source_path}" in
    //*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

collect_backend_bind_mounts_from_compose_config() {
  local env_file="$1"
  local config_output
  if ! config_output="$(
    COMPOSE_PROJECT_NAME="${compose_project_name:-${COMPOSE_PROJECT_NAME:-}}" \
      "${compose_cmd[@]}" "${compose_env_file_args[@]}" -f docker-compose.yml config 2>/dev/null
  )"; then
    echo "[wal-guard] Failed to render docker compose config while validating bind mounts." >&2
    return 1
  fi
  printf '%s\n' "${config_output}" | awk '
    function strip_quotes(value) {
      if (length(value) >= 2) {
        first = substr(value, 1, 1)
        last = substr(value, length(value), 1)
        if ((first == "\"" && last == "\"") || (first == "'"'"'" && last == "'"'"'")) {
          return substr(value, 2, length(value) - 2)
        }
      }
      return value
    }
    function parse_bind_shorthand(value, marker_index) {
      value = strip_quotes(value)
      marker_index = index(value, ":/app/data")
      if (marker_index > 1) {
        current_type = "bind"
        current_source = substr(value, 1, marker_index - 1)
        current_target = "/app/data"
      }
    }
    function extract_inline_type(value, normalized, marker_index) {
      normalized = strip_quotes(value)
      marker_index = index(normalized, "type:")
      if (marker_index == 0) {
        return ""
      }
      normalized = substr(normalized, marker_index + length("type:"))
      sub(/^[[:space:]]+/, "", normalized)
      if (normalized == "") {
        return ""
      }
      sub(/[[:space:]].*$/, "", normalized)
      return normalized
    }
    function flush_record() {
      if (current_type == "bind" && current_source != "" && current_target != "") {
        print current_source "\t" current_target
      }
      current_type = ""
      current_source = ""
      current_target = ""
    }
    /^services:$/ { in_services = 1; next }
    in_services && /^  backend:$/ { in_backend = 1; next }
    in_backend && /^  [^[:space:]][^:]*:$/ && $0 != "  backend:" {
      flush_record()
      in_backend = 0
      in_volumes = 0
    }
    in_backend && /^    volumes:$/ { in_volumes = 1; next }
    in_backend && in_volumes && /^    [^[:space:]-][^:]*:/ {
      flush_record()
      in_volumes = 0
    }
    in_backend && in_volumes {
      if ($0 ~ /^      - /) {
        flush_record()
        value = $0
        sub(/^      - /, "", value)
        inline_type = extract_inline_type(value)
        if (inline_type != "") {
          current_type = inline_type
        } else {
          parse_bind_shorthand(value)
        }
        next
      }
      if ($0 ~ /^        type: /) {
        sub(/^        type: /, "", $0)
        current_type = $0
        next
      }
      if ($0 ~ /^        source: /) {
        sub(/^        source: /, "", $0)
        current_source = $0
        next
      }
      if ($0 ~ /^        target: /) {
        sub(/^        target: /, "", $0)
        current_target = $0
        next
      }
    }
    END { flush_record() }
  '
}

assert_no_risky_wal_bind_mounts() {
  local env_file="$1"
  if ! docker_env_requests_wal "${env_file}"; then
    return 0
  fi
  local bind_mounts
  bind_mounts="$(collect_backend_bind_mounts_from_compose_config "${env_file}")" || return 1
  if [[ -z "${bind_mounts}" ]]; then
    return 0
  fi

  local line source_path target_path normalized_source probe_path fs_type
  while IFS=$'\t' read -r source_path target_path; do
    [[ -n "${source_path}" && -n "${target_path}" ]] || continue
    target_path="$(trim_wrapping_quotes "${target_path}")"
    if ! target_affects_runtime_database "${target_path}"; then
      continue
    fi

    normalized_source="$(normalize_bind_source_path "${source_path}")"
    if is_probable_network_bind_source "${normalized_source}"; then
      echo "[wal-guard] Refusing to start Docker deployment: backend /app/data is bind-mounted from network path '${normalized_source}' while WAL is enabled." >&2
      echo "[wal-guard] Use the default Docker named volume, or set MEMORY_PALACE_DOCKER_WAL_ENABLED=false and MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete." >&2
      return 1
    fi

    probe_path="$(resolve_existing_probe_path "${normalized_source}" || true)"
    if [[ -z "${probe_path}" ]]; then
      continue
    fi
    fs_type="$(detect_filesystem_type "${probe_path}" || true)"
    if filesystem_type_is_network_risky "${fs_type}"; then
      echo "[wal-guard] Refusing to start Docker deployment: backend /app/data bind source '${normalized_source}' resolves to risky filesystem '${fs_type}' with WAL enabled." >&2
      echo "[wal-guard] Use the default Docker named volume, or set MEMORY_PALACE_DOCKER_WAL_ENABLED=false and MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete." >&2
      return 1
    fi
  done <<< "${bind_mounts}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Missing value for --profile" >&2
        exit 2
      fi
      profile="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
      ;;
    --frontend-port)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Missing value for --frontend-port" >&2
        exit 2
      fi
      frontend_port="$1"
      ;;
    --backend-port)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Missing value for --backend-port" >&2
        exit 2
      fi
      backend_port="$1"
      ;;
    --no-auto-port)
      auto_port=0
      ;;
    --no-build)
      no_build=1
      ;;
    --allow-runtime-env-injection)
      allow_runtime_env_injection=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
  shift
done

case "${profile}" in
  a|b|c|d) ;;
  *)
    echo "Unsupported profile: ${profile}. Expected one of: a | b | c | d" >&2
    exit 2
    ;;
esac

if ! is_positive_int "${frontend_port}"; then
  echo "Invalid --frontend-port: ${frontend_port}" >&2
  exit 2
fi

if ! is_positive_int "${backend_port}"; then
  echo "Invalid --backend-port: ${backend_port}" >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not installed or not in PATH" >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  compose_cmd=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  compose_cmd=(docker-compose)
else
  echo "Neither 'docker compose' nor 'docker-compose' is available" >&2
  exit 1
fi

DEPLOYMENT_LOCK="$(
  try_acquire_path_lock "${TMPDIR:-/tmp}/memory-palace-deploy-locks/$(default_compose_project_name)" || true
)"
if [[ -z "${DEPLOYMENT_LOCK}" ]]; then
  echo "[deploy-lock] another docker_one_click deployment is already running for this checkout; wait for it to finish before retrying." >&2
  exit 1
fi

env_file="${MEMORY_PALACE_DOCKER_ENV_FILE:-}"
if [[ -z "${env_file}" ]]; then
  env_file="$(mktemp "${TMPDIR:-/tmp}/memory-palace-docker-env-${profile}-XXXXXX")"
  TEMP_DOCKER_ENV_FILE="${env_file}"
  TEMP_DOCKER_ENV_FILE_AUTO=1
fi
env_file="$(resolve_stable_env_file_path "${env_file}")"
chmod 600 "${env_file}" >/dev/null 2>&1 || true
export MEMORY_PALACE_DOCKER_ENV_FILE="${env_file}"
echo "[env-file] using ${env_file}"
if [[ "${allow_runtime_env_injection}" -eq 1 && "${profile}" != "c" && "${profile}" != "d" ]]; then
  echo "[override] --allow-runtime-env-injection is only supported for profile c/d; profile ${profile} keeps its documented defaults." >&2
  exit 1
fi
if [[ "${allow_runtime_env_injection}" -eq 1 && ( "${profile}" == "c" || "${profile}" == "d" ) ]]; then
  MEMORY_PALACE_ALLOW_UNRESOLVED_PROFILE_PLACEHOLDERS=1 \
    bash "${SCRIPT_DIR}/apply_profile.sh" docker "${profile}" "${env_file}"
else
  bash "${SCRIPT_DIR}/apply_profile.sh" docker "${profile}" "${env_file}"
fi
if [[ "${allow_runtime_env_injection}" -eq 1 ]]; then
  apply_profile_runtime_overrides "${env_file}" "${profile}"
else
  echo "[override] runtime env injection disabled by default; pass --allow-runtime-env-injection to opt in."
fi
assert_profile_external_settings_ready "${env_file}" "${profile}"

cd "${PROJECT_ROOT}"

if [[ ${auto_port} -eq 1 ]]; then
  if ! frontend_reservation="$(find_free_port "${frontend_port}")"; then
    echo "Failed to auto-resolve free frontend port near ${frontend_port}. Try --no-auto-port with explicit values." >&2
    exit 1
  fi
  read -r resolved_frontend_port FRONTEND_PORT_LOCK <<< "${frontend_reservation}"
  if ! backend_reservation="$(find_free_port "${backend_port}" 200 "${resolved_frontend_port}")"; then
    echo "Failed to auto-resolve free backend port near ${backend_port}. Try --no-auto-port with explicit values." >&2
    exit 1
  fi
  read -r resolved_backend_port BACKEND_PORT_LOCK <<< "${backend_reservation}"

  if [[ "${resolved_frontend_port}" != "${frontend_port}" ]]; then
    echo "[port-adjust] frontend ${frontend_port} is occupied, switched to ${resolved_frontend_port}"
  fi
  if [[ "${resolved_backend_port}" != "${backend_port}" ]]; then
    echo "[port-adjust] backend ${backend_port} is occupied, switched to ${resolved_backend_port}"
  fi

  frontend_port="${resolved_frontend_port}"
  backend_port="${resolved_backend_port}"
fi

data_volume="$(resolve_data_volume)"
snapshots_volume="$(resolve_snapshots_volume)"
upsert_env_value_in_file "${env_file}" "MEMORY_PALACE_FRONTEND_PORT" "${frontend_port}"
upsert_env_value_in_file "${env_file}" "MEMORY_PALACE_BACKEND_PORT" "${backend_port}"
upsert_env_value_in_file "${env_file}" "MEMORY_PALACE_DATA_VOLUME" "${data_volume}"
upsert_env_value_in_file "${env_file}" "MEMORY_PALACE_SNAPSHOTS_VOLUME" "${snapshots_volume}"
upsert_env_value_in_file "${env_file}" "NOCTURNE_FRONTEND_PORT" "${frontend_port}"
upsert_env_value_in_file "${env_file}" "NOCTURNE_BACKEND_PORT" "${backend_port}"
upsert_env_value_in_file "${env_file}" "NOCTURNE_DATA_VOLUME" "${data_volume}"
upsert_env_value_in_file "${env_file}" "NOCTURNE_SNAPSHOTS_VOLUME" "${snapshots_volume}"
planned_frontend_port="$(get_env_value_from_file "${env_file}" "MEMORY_PALACE_FRONTEND_PORT")"
planned_backend_port="$(get_env_value_from_file "${env_file}" "MEMORY_PALACE_BACKEND_PORT")"
if [[ -z "${planned_frontend_port}" ]]; then
  planned_frontend_port="${frontend_port}"
fi
if [[ -z "${planned_backend_port}" ]]; then
  planned_backend_port="${backend_port}"
fi
compose_project_name="${COMPOSE_PROJECT_NAME:-$(default_compose_project_name)}"
local_image_namespace="${MEMORY_PALACE_LOCAL_IMAGE_NAMESPACE:-$(default_compose_project_name)}"
backend_image="${MEMORY_PALACE_BACKEND_IMAGE:-${local_image_namespace}-backend:latest}"
frontend_image="${MEMORY_PALACE_FRONTEND_IMAGE:-${local_image_namespace}-frontend:latest}"
export MEMORY_PALACE_BACKEND_IMAGE="${backend_image}"
export MEMORY_PALACE_FRONTEND_IMAGE="${frontend_image}"
compose_env_file_args=()
if [[ -n "${env_file}" ]]; then
  compose_env_file_args=(--env-file "${env_file}")
fi

assert_no_risky_wal_bind_mounts "${env_file}"

export MEMORY_PALACE_FRONTEND_PORT="${frontend_port}"
export MEMORY_PALACE_BACKEND_PORT="${backend_port}"
export MEMORY_PALACE_DATA_VOLUME="${data_volume}"
export MEMORY_PALACE_SNAPSHOTS_VOLUME="${snapshots_volume}"
export NOCTURNE_FRONTEND_PORT="${frontend_port}"
export NOCTURNE_BACKEND_PORT="${backend_port}"
export NOCTURNE_DATA_VOLUME="${data_volume}"
export NOCTURNE_SNAPSHOTS_VOLUME="${snapshots_volume}"

# Force recreate to avoid stale network attachment causing frontend->backend 502.
if ! COMPOSE_PROJECT_NAME="${compose_project_name}" "${compose_cmd[@]}" "${compose_env_file_args[@]}" -f docker-compose.yml down --remove-orphans >/dev/null 2>&1; then
  echo "[compose-down] pre-cleanup failed; aborting to match fail-closed deployment behavior." >&2
  exit 1
fi

if [[ ${no_build} -eq 1 ]]; then
  compose_up_args=(-f docker-compose.yml up -d --no-build --wait --wait-timeout 120 --force-recreate --remove-orphans)
  if ! run_compose_with_retry compose_up_args "${compose_project_name}" 3 "${env_file}"; then
    if ! compose_project_has_any_container backend \
      && ! compose_project_has_any_container frontend; then
      echo "[compose-up] docker compose failed before creating any service container; skipping readiness probe." >&2
      exit 1
    fi
    echo "[compose-up] docker compose returned non-zero; probing backend/frontend readiness via proxied /sse..." >&2
    probe_frontend_port="$(resolve_published_port_from_compose frontend 8080 "${planned_frontend_port}")"
    probe_backend_port="$(resolve_published_port_from_compose backend 8000 "${planned_backend_port}")"
    if ! wait_for_deployment_ready 30 2 "${probe_frontend_port}" "${probe_backend_port}"; then
      exit 1
    fi
    echo "[compose-up] services became ready after compose reported failure; continuing." >&2
  fi
else
  compose_up_args=(-f docker-compose.yml up -d --build --wait --wait-timeout 120 --force-recreate --remove-orphans)
  if ! run_compose_with_retry compose_up_args "${compose_project_name}" 3 "${env_file}"; then
    if ! compose_project_has_any_container backend \
      && ! compose_project_has_any_container frontend; then
      echo "[compose-up] docker compose failed before creating any service container; skipping readiness probe." >&2
      exit 1
    fi
    echo "[compose-up] docker compose returned non-zero; probing backend/frontend readiness via proxied /sse..." >&2
    probe_frontend_port="$(resolve_published_port_from_compose frontend 8080 "${planned_frontend_port}")"
    probe_backend_port="$(resolve_published_port_from_compose backend 8000 "${planned_backend_port}")"
    if ! wait_for_deployment_ready 30 2 "${probe_frontend_port}" "${probe_backend_port}"; then
      exit 1
    fi
    echo "[compose-up] services became ready after compose reported failure; continuing." >&2
  fi
fi

reported_frontend_port="$(resolve_published_port_from_compose frontend 8080 "${planned_frontend_port}")"
reported_backend_port="$(resolve_published_port_from_compose backend 8000 "${planned_backend_port}")"

echo ""
echo "Memory Palace is starting with docker profile ${profile}."
echo "Frontend: http://localhost:${reported_frontend_port}"
echo "Backend API: http://localhost:${reported_backend_port}"
echo "SSE Endpoint: http://localhost:${reported_frontend_port}/sse"
echo "Health: http://localhost:${reported_backend_port}/health"
echo "Compose project: ${compose_project_name}"
