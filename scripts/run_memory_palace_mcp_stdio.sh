#!/usr/bin/env bash
set -euo pipefail

resolve_script_path() {
  local source_path="${1:-}"
  if [[ -z "${source_path}" ]]; then
    return 1
  fi

  while [[ -h "${source_path}" ]]; do
    local source_dir
    source_dir="$(cd -P -- "$(dirname -- "${source_path}")" && pwd)"
    local linked_path
    linked_path="$(readlink "${source_path}")"
    if [[ "${linked_path}" != /* ]]; then
      source_path="${source_dir}/${linked_path}"
    else
      source_path="${linked_path}"
    fi
  done

  local resolved_dir
  resolved_dir="$(cd -P -- "$(dirname -- "${source_path}")" && pwd)"
  printf '%s\n' "${resolved_dir}/$(basename -- "${source_path}")"
}

SCRIPT_PATH="$(resolve_script_path "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd -P -- "$(dirname -- "${SCRIPT_PATH}")" && pwd)"
PROJECT_ROOT="$(cd -P -- "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"
POSIX_VENV_PYTHON="${BACKEND_DIR}/.venv/bin/python"
WINDOWS_VENV_PYTHON="${BACKEND_DIR}/.venv/Scripts/python.exe"
ENV_FILE="${PROJECT_ROOT}/.env"
DOCKER_ENV_FILE="${PROJECT_ROOT}/.env.docker"
DEFAULT_DB_PATH="${PROJECT_ROOT}/demo.db"
DOCKER_INTERNAL_SQLITE_ROOTS=("/app" "/data")

is_windows_host_shell() {
  case "${OSTYPE:-}" in
    msys*|cygwin*|win32*)
      return 0
      ;;
  esac

  [[ "${OS:-}" == "Windows_NT" ]]
}

prefer_windows_venv_layout() {
  is_windows_host_shell
}

normalize_path_slashes() {
  local value="${1:-}"
  printf '%s' "${value//\\//}"
}

uppercase_windows_drive() {
  local value
  value="$(normalize_path_slashes "${1:-}")"
  if [[ "${value}" =~ ^([a-zA-Z]):/?(.*)$ ]]; then
    local drive rest
    drive="$(printf '%s' "${BASH_REMATCH[1]}" | tr '[:lower:]' '[:upper:]')"
    rest="${BASH_REMATCH[2]}"
    if [[ -n "${rest}" ]]; then
      printf '%s:/%s' "${drive}" "${rest}"
    else
      printf '%s:/' "${drive}"
    fi
    return 0
  fi
  printf '%s' "${value}"
}

resolve_windows_host_path() {
  local value="${1:-}"
  local converted=""

  value="$(normalize_path_slashes "${value}")"
  if [[ -z "${value}" ]]; then
    printf '%s' "${value}"
    return 0
  fi

  if command -v cygpath >/dev/null 2>&1; then
    converted="$(cygpath -am "${value}" 2>/dev/null || true)"
    converted="$(uppercase_windows_drive "${converted}")"
    if [[ "${converted}" =~ ^[A-Z]:/.*$ ]]; then
      printf '%s' "${converted}"
      return 0
    fi
  fi

  if command -v wslpath >/dev/null 2>&1; then
    converted="$(wslpath -w "${value}" 2>/dev/null || true)"
    converted="$(uppercase_windows_drive "${converted}")"
    if [[ "${converted}" =~ ^[A-Z]:/.*$ ]]; then
      printf '%s' "${converted}"
      return 0
    fi
  fi

  if [[ "${value}" =~ ^/mnt/([a-zA-Z])/(.*)$ ]]; then
    printf '%s:/%s' "$(printf '%s' "${BASH_REMATCH[1]}" | tr '[:lower:]' '[:upper:]')" "${BASH_REMATCH[2]}"
    return 0
  fi

  if [[ "${value}" =~ ^/([a-zA-Z])/(.*)$ ]]; then
    printf '%s:/%s' "$(printf '%s' "${BASH_REMATCH[1]}" | tr '[:lower:]' '[:upper:]')" "${BASH_REMATCH[2]}"
    return 0
  fi

  printf '%s' "$(uppercase_windows_drive "${value}")"
}

prefer_windows_path_semantics() {
  if [[ "${VENV_PYTHON:-}" == *.exe ]]; then
    return 0
  fi

  prefer_windows_venv_layout
}

read_env_value() {
  local file_path="$1"
  local key="$2"
  if [[ ! -f "${file_path}" ]]; then
    return 0
  fi
  awk -v key="${key}" '
    function ltrim(s) { sub(/^[[:space:]]+/, "", s); return s }
    function rtrim(s) { sub(/[[:space:]]+$/, "", s); return s }
    function trim(s) { return rtrim(ltrim(s)) }
    {
      line = $0
      sub(/\r$/, "", line)
      if (line ~ /^[[:space:]]*#/ || index(line, "=") == 0) {
        next
      }
      eq = index(line, "=")
      current_key = trim(substr(line, 1, eq - 1))
      if (current_key != key) {
        next
      }
      value = trim(substr(line, eq + 1))
      if (length(value) >= 2) {
        first = substr(value, 1, 1)
        last = substr(value, length(value), 1)
        if ((first == "\"" || first == "'\''") && last == first) {
          last_value = substr(value, 2, length(value) - 2)
          next
        }
      }
      sub(/[[:space:]]+#.*$/, "", value)
      value = trim(value)
      if (length(value) >= 2) {
        first = substr(value, 1, 1)
        last = substr(value, length(value), 1)
        if ((first == "\"" || first == "'\''") && last == first) {
          value = substr(value, 2, length(value) - 2)
        }
      }
      last_value = value
    }
    END { printf "%s", last_value }
  ' "${file_path}"
}

env_file_has_key() {
  local file_path="$1"
  local key="$2"
  if [[ ! -f "${file_path}" ]]; then
    return 1
  fi
  awk -v key="${key}" '
    function ltrim(s) { sub(/^[[:space:]]+/, "", s); return s }
    function rtrim(s) { sub(/[[:space:]]+$/, "", s); return s }
    function trim(s) { return rtrim(ltrim(s)) }
    {
      line = $0
      sub(/\r$/, "", line)
      if (line ~ /^[[:space:]]*#/ || index(line, "=") == 0) {
        next
      }
      eq = index(line, "=")
      current_key = trim(substr(line, 1, eq - 1))
      if (current_key == key) {
        found = 1
      }
    }
    END { exit found ? 0 : 1 }
  ' "${file_path}"
}

normalize_env_value() {
  local value="${1:-}"
  value="${value//$'\r'/}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  if [[ "${#value}" -ge 2 ]]; then
    if [[ "${value:0:1}" == "\"" && "${value: -1}" == "\"" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
      value="${value:1:${#value}-2}"
    fi
  fi
  printf '%s' "${value}"
}

read_windows_host_env_value() {
  local key="${1:-}"
  if [[ -z "${key}" ]]; then
    printf '%s' ""
    return 0
  fi
  if ! command -v cmd.exe >/dev/null 2>&1; then
    printf '%s' ""
    return 0
  fi

  local value=""
  value="$(cmd.exe /d /c "echo %${key}%" 2>/dev/null | tr -d '\r' | tail -n 1 || true)"
  value="$(normalize_env_value "${value}")"
  if [[ "${value}" == "%${key}%" ]]; then
    value=""
  fi
  printf '%s' "${value}"
}

resolve_passthrough_env_value() {
  local key="${1:-}"
  local value=""
  if [[ -n "${key}" ]]; then
    value="$(normalize_env_value "${!key-}")"
  fi
  if [[ -n "${value}" ]]; then
    printf '%s' "${value}"
    return 0
  fi
  read_windows_host_env_value "${key}"
}

_LOCAL_NO_PROXY_HOSTS=("localhost" "127.0.0.1" "::1" "host.docker.internal")

csv_list_contains_case_insensitive() {
  local csv="${1:-}"
  local needle
  needle="$(normalize_env_value "${2:-}")"
  if [[ -z "${needle}" ]]; then
    return 0
  fi

  local needle_lower
  needle_lower="$(printf '%s' "${needle}" | tr '[:upper:]' '[:lower:]')"
  local entry
  local -a entries=()
  if [[ -n "${csv}" ]]; then
    IFS=',' read -r -a entries <<< "${csv}"
  fi
  for entry in "${entries[@]-}"; do
    entry="$(normalize_env_value "${entry}")"
    if [[ -z "${entry}" ]]; then
      continue
    fi
    if [[ "$(printf '%s' "${entry}" | tr '[:upper:]' '[:lower:]')" == "${needle_lower}" ]]; then
      return 0
    fi
  done
  return 1
}

append_csv_item_if_missing() {
  local csv="${1:-}"
  local item
  item="$(normalize_env_value "${2:-}")"
  if [[ -z "${item}" ]]; then
    printf '%s' "${csv}"
    return 0
  fi
  if csv_list_contains_case_insensitive "${csv}" "${item}"; then
    printf '%s' "${csv}"
    return 0
  fi
  if [[ -n "${csv}" ]]; then
    printf '%s,%s' "${csv}" "${item}"
  else
    printf '%s' "${item}"
  fi
}

ensure_local_no_proxy_defaults() {
  local merged=""
  local existing_value
  local existing_entry
  local existing_entries=()
  for existing_value in \
    "$(resolve_passthrough_env_value "NO_PROXY")" \
    "$(resolve_passthrough_env_value "no_proxy")"; do
    existing_value="$(normalize_env_value "${existing_value}")"
    if [[ -z "${existing_value}" ]]; then
      continue
    fi
    IFS=',' read -r -a existing_entries <<< "${existing_value}"
    for existing_entry in "${existing_entries[@]}"; do
      merged="$(append_csv_item_if_missing "${merged}" "${existing_entry}")"
    done
  done

  local host
  for host in "${_LOCAL_NO_PROXY_HOSTS[@]}"; do
    merged="$(append_csv_item_if_missing "${merged}" "${host}")"
  done

  export NO_PROXY="${merged}"
  export no_proxy="${merged}"
}

restore_proxy_env_values() {
  local proxy_var
  local proxy_value
  for proxy_var in HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy; do
    proxy_value="$(resolve_passthrough_env_value "${proxy_var}")"
    if [[ -n "${proxy_value}" ]]; then
      export "${proxy_var}=${proxy_value}"
    fi
  done
}

format_sqlite_absolute_url() {
  local absolute_path="${1:-}"
  absolute_path="$(normalize_path_slashes "${absolute_path%$'\r'}")"
  if prefer_windows_path_semantics; then
    absolute_path="$(resolve_windows_host_path "${absolute_path}")"
  fi
  absolute_path="$(uppercase_windows_drive "${absolute_path}")"
  if [[ "${absolute_path}" =~ ^[A-Za-z]:/.*$ ]]; then
    printf 'sqlite+aiosqlite:///%s' "${absolute_path}"
    return 0
  fi
  while [[ "${absolute_path}" == /* ]]; do
    absolute_path="${absolute_path#/}"
  done
  printf 'sqlite+aiosqlite:////%s' "${absolute_path}"
}

normalize_sqlite_database_url_path() {
  local info
  info="$(sqlite_database_url_path_info "${1:-}")"
  printf '%s' "${info%%|*}" | tr '[:upper:]' '[:lower:]'
}

sqlite_database_url_path_info() {
  local value previous pass path scheme_prefix
  value="$(normalize_env_value "${1:-}")"
  previous=""
  for pass in 1 2 3; do
    [[ "${value}" == *%* ]] || break
    [[ "${value}" != "${previous}" ]] || break
    previous="${value}"
    value="${value//\\/\\\\}"
    value="$(printf '%b' "${value//%/\\x}")"
  done
  value="$(normalize_path_slashes "${value}")"
  if [[ "$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]')" != sqlite+aiosqlite:* ]]; then
    printf '%s' "|0"
    return 0
  fi

  scheme_prefix="sqlite+aiosqlite:"
  path="${value:${#scheme_prefix}}"
  if [[ "${path}" =~ ^///[A-Za-z]:/.*$ ]]; then
    printf '%s|1' "${path:3}"
  elif [[ "${path}" =~ ^[A-Za-z]:/.*$ ]]; then
    printf '%s|1' "${path}"
  elif [[ "${path}" == ////* ]]; then
    while [[ "${path}" == /* ]]; do
      path="${path#/}"
    done
    printf '/%s|1' "${path}"
  elif [[ "${path}" == ///* ]]; then
    printf '%s|0' "${path:3}"
  elif [[ "${path}" == /* && "${path}" != //* ]]; then
    printf '%s|1' "${path}"
  else
    while [[ "${path}" == /* ]]; do
      path="${path#/}"
    done
    printf '%s|0' "${path}"
  fi
}

is_docker_internal_database_url() {
  local normalized_path
  local info
  info="$(sqlite_database_url_path_info "${1:-}")"
  if [[ "${info##*|}" != "1" ]]; then
    return 1
  fi
  normalized_path="$(printf '%s' "${info%%|*}" | tr '[:upper:]' '[:lower:]')"
  local root
  for root in "${DOCKER_INTERNAL_SQLITE_ROOTS[@]}"; do
    [[ "${normalized_path}" == "${root}" || "${normalized_path}" == "${root}/"* ]] && return 0
  done
  return 1
}

database_url_is_relative() {
  local info
  info="$(sqlite_database_url_path_info "${1:-}")"
  [[ -n "${info%%|*}" && "${info##*|}" == "0" ]]
}

database_url_has_parent_reference() {
  local normalized_path
  normalized_path="$(normalize_sqlite_database_url_path "${1:-}")"
  [[ -n "${normalized_path}" ]] || return 1
  local segment
  IFS='/' read -r -a segments <<< "${normalized_path}"
  for segment in "${segments[@]-}"; do
    [[ "${segment}" == ".." ]] && return 0
  done
  return 1
}

VENV_PYTHON=""
if prefer_windows_venv_layout; then
  if [[ -x "${WINDOWS_VENV_PYTHON}" ]]; then
    VENV_PYTHON="${WINDOWS_VENV_PYTHON}"
  elif [[ -x "${POSIX_VENV_PYTHON}" ]]; then
    VENV_PYTHON="${POSIX_VENV_PYTHON}"
  fi
elif [[ -x "${POSIX_VENV_PYTHON}" ]]; then
  VENV_PYTHON="${POSIX_VENV_PYTHON}"
elif [[ -x "${WINDOWS_VENV_PYTHON}" ]]; then
  VENV_PYTHON="${WINDOWS_VENV_PYTHON}"
fi

if [[ -z "${VENV_PYTHON}" ]]; then
  echo "Missing backend virtualenv python: ${POSIX_VENV_PYTHON} or ${WINDOWS_VENV_PYTHON}" >&2
  exit 1
fi

cd "${BACKEND_DIR}"

runtime_database_url="$(normalize_env_value "${DATABASE_URL:-}")"
effective_database_url="${runtime_database_url}"
if [[ -z "${runtime_database_url}" && -f "${ENV_FILE}" ]]; then
  effective_database_url="$(normalize_env_value "$(read_env_value "${ENV_FILE}" "DATABASE_URL")")"
  if [[ -z "${effective_database_url}" ]] && env_file_has_key "${ENV_FILE}" "DATABASE_URL"; then
    echo "Refusing to start repo-local stdio MCP with empty DATABASE_URL in ${ENV_FILE}." >&2
    echo "Set DATABASE_URL to a host absolute SQLite URL, or remove the empty line to use the no-.env demo fallback." >&2
    exit 1
  fi
  if [[ -n "${effective_database_url}" ]]; then
    export DATABASE_URL="${effective_database_url}"
  fi
fi

if database_url_has_parent_reference "${effective_database_url}"; then
  echo "Refusing to start repo-local stdio MCP with parent-directory DATABASE_URL: ${effective_database_url}" >&2
  echo "The DATABASE_URL path must be a normalized host absolute path and must not contain '..' segments." >&2
  exit 1
fi

if database_url_is_relative "${effective_database_url}"; then
  echo "Refusing to start repo-local stdio MCP with relative DATABASE_URL: ${effective_database_url}" >&2
  echo "The DATABASE_URL path must be a normalized host absolute path." >&2
  exit 1
fi

if is_docker_internal_database_url "${effective_database_url}"; then
  echo "Refusing to start repo-local stdio MCP with Docker-internal DATABASE_URL: ${effective_database_url}" >&2
  echo "The current .env points to a container-only sqlite path (for example /app/... or /data/...)." >&2
  echo "For local stdio, regenerate .env with 'bash scripts/apply_profile.sh macos b' or set DATABASE_URL to a host absolute path." >&2
  echo "If you want the containerized database/service, connect your client to the Docker /sse endpoint instead." >&2
  exit 1
fi

# Reuse the repo's configured DATABASE_URL when .env exists so MCP clients and
# the Dashboard/API keep talking to the same SQLite file. Fall back to demo.db
# only for a minimal no-.env local boot.
if [[ -z "$(normalize_env_value "${DATABASE_URL:-}")" && ! -f "${ENV_FILE}" ]]; then
  if [[ -f "${DOCKER_ENV_FILE}" ]]; then
    echo "Refusing to fall back to demo.db while ${DOCKER_ENV_FILE} exists." >&2
    echo "The repo-local stdio wrapper does not reuse Docker's /app/data database path." >&2
    echo "Create a local .env for the SQLite file you want, or connect your client to the Docker /sse endpoint instead." >&2
    exit 1
  fi
  export DATABASE_URL="$(format_sqlite_absolute_url "${DEFAULT_DB_PATH}")"
fi

runtime_remote_timeout="$(normalize_env_value "${RETRIEVAL_REMOTE_TIMEOUT_SEC:-}")"
if [[ -z "${runtime_remote_timeout}" && -f "${ENV_FILE}" ]]; then
  runtime_remote_timeout="$(normalize_env_value "$(read_env_value "${ENV_FILE}" "RETRIEVAL_REMOTE_TIMEOUT_SEC")")"
fi
if [[ -n "${runtime_remote_timeout}" ]]; then
  export RETRIEVAL_REMOTE_TIMEOUT_SEC="${runtime_remote_timeout}"
else
  export RETRIEVAL_REMOTE_TIMEOUT_SEC="8"
fi

# Keep common host-local model endpoints off inherited shell proxies so repo-local
# stdio remains compatible with local Ollama / OpenAI-compatible services.
ensure_local_no_proxy_defaults
restore_proxy_env_values

export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"
export PYTHONUTF8="${PYTHONUTF8:-1}"

exec_backend_entrypoint() {
  local backend_entrypoint="$1"
  shift

  if [[ "${backend_entrypoint}" == *.exe ]]; then
    exec "${backend_entrypoint}" "$@"
  fi

  local header=""
  header="$(LC_ALL=C head -c 2 "${backend_entrypoint}" 2>/dev/null || true)"
  if [[ "${header}" == '#!' ]]; then
    exec bash <(tr -d '\r' < "${backend_entrypoint}") "$@"
  fi

  exec "${backend_entrypoint}" "$@"
}

exec_backend_entrypoint "${VENV_PYTHON}" mcp_server.py
