#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

dry_run="false"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      dry_run="true"
      shift
      ;;
    --help|-h)
      cat <<'EOF'
Usage: bash scripts/apply_profile.sh [--dry-run] [platform] [profile] [target-file]

Examples:
  bash scripts/apply_profile.sh macos b
  bash scripts/apply_profile.sh --dry-run docker c .env.docker
EOF
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

platform_input="${1:-macos}"
profile_input="${2:-b}"
target_file_input="${3:-}"

platform="$(printf '%s' "${platform_input}" | tr '[:upper:]' '[:lower:]')"
profile="$(printf '%s' "${profile_input}" | tr '[:upper:]' '[:lower:]')"

case "${platform}" in
  macos|linux|windows|docker) ;;
  *)
    echo "Unsupported platform: ${platform}. Expected one of: macos | linux | windows | docker" >&2
    exit 2
    ;;
esac

case "${profile}" in
  a|b|c|d) ;;
  *)
    echo "Unsupported profile: ${profile}. Expected one of: a | b | c | d" >&2
    exit 2
    ;;
esac

if [[ -n "${target_file_input}" ]]; then
  target_file="${target_file_input}"
elif [[ "${platform}" == "docker" ]]; then
  target_file="${PROJECT_ROOT}/.env.docker"
else
  target_file="${PROJECT_ROOT}/.env"
fi

base_env="${PROJECT_ROOT}/.env.example"
override_env="${PROJECT_ROOT}/deploy/profiles/${platform}/profile-${profile}.env"

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

target_file="$(normalize_cli_path "${target_file}")"

if [[ -n "${target_file_input}" ]] && is_mangled_windows_absolute_path "${target_file}"; then
  if reconstructed_target_file="$(reconstruct_mangled_windows_path "${target_file}")"; then
    target_file="${reconstructed_target_file}"
  else
    echo "Refusing mangled Windows absolute target path: ${target_file_input}" >&2
    echo "bash received it without directory separators before apply_profile.sh could normalize it." >&2
    echo "Re-run with C:/... or a repo-relative POSIX path instead." >&2
    exit 2
  fi
fi

is_windows_host_shell() {
  case "${OSTYPE:-}" in
    msys*|cygwin*|win32*)
      return 0
      ;;
  esac

  [[ "${OS:-}" == "Windows_NT" ]]
}

is_wsl_shell() {
  if [[ -n "${WSL_DISTRO_NAME:-}" || -n "${WSL_INTEROP:-}" ]]; then
    return 0
  fi

  grep -qi 'microsoft' /proc/version 2>/dev/null
}

supports_owner_pid_stale_lock_recovery() {
  if is_windows_host_shell || is_wsl_shell; then
    return 1
  fi
  return 0
}

normalize_path_slashes() {
  local raw_path="${1:-}"
  printf '%s\n' "${raw_path//\\//}"
}

uppercase_windows_drive() {
  local raw_path
  raw_path="$(normalize_path_slashes "${1:-}")"
  if [[ "${raw_path}" =~ ^([a-zA-Z]):/?(.*)$ ]]; then
    local drive rest
    drive="$(printf '%s' "${BASH_REMATCH[1]}" | tr '[:lower:]' '[:upper:]')"
    rest="${BASH_REMATCH[2]}"
    if [[ -n "${rest}" ]]; then
      printf '%s:/%s\n' "${drive}" "${rest}"
    else
      printf '%s:/\n' "${drive}"
    fi
    return 0
  fi
  printf '%s\n' "${raw_path}"
}

resolve_windows_host_path() {
  local raw_path="${1:-}"
  local converted=""

  raw_path="$(normalize_path_slashes "${raw_path}")"
  if [[ -z "${raw_path}" ]]; then
    printf '%s\n' "${raw_path}"
    return 0
  fi

  if command -v wslpath >/dev/null 2>&1; then
    converted="$(wslpath -w "${raw_path}" 2>/dev/null || true)"
    converted="$(uppercase_windows_drive "${converted}")"
    if [[ "${converted}" =~ ^[A-Z]:/.*$ ]]; then
      printf '%s\n' "${converted}"
      return 0
    fi
  fi

  if command -v cygpath >/dev/null 2>&1; then
    converted="$(cygpath -am "${raw_path}" 2>/dev/null || true)"
    converted="$(uppercase_windows_drive "${converted}")"
    if [[ "${converted}" =~ ^[A-Z]:/.*$ ]]; then
      printf '%s\n' "${converted}"
      return 0
    fi
  fi

  if [[ "${raw_path}" =~ ^/mnt/([a-zA-Z])/(.*)$ ]]; then
    printf '%s:/%s\n' "$(printf '%s' "${BASH_REMATCH[1]}" | tr '[:lower:]' '[:upper:]')" "${BASH_REMATCH[2]}"
    return 0
  fi

  if [[ "${raw_path}" =~ ^/([a-zA-Z])/(.*)$ ]]; then
    printf '%s:/%s\n' "$(printf '%s' "${BASH_REMATCH[1]}" | tr '[:lower:]' '[:upper:]')" "${BASH_REMATCH[2]}"
    return 0
  fi

  printf '%s\n' "$(uppercase_windows_drive "${raw_path}")"
}

TARGET_FILE_LOCK=""

write_lock_owner_metadata() {
  local owner_file="$1"
  local owner_scope_file="$2"

  printf '%s\n' "${BASHPID:-$$}" > "${owner_file}" 2>/dev/null || true
  if supports_owner_pid_stale_lock_recovery; then
    printf '%s\n' 'posix-pid' > "${owner_scope_file}" 2>/dev/null || true
  else
    printf '%s\n' 'opaque' > "${owner_scope_file}" 2>/dev/null || true
  fi
}

try_acquire_path_lock() {
  local target_path="$1"
  local lock_dir="${target_path}.lockdir"
  local owner_file="${lock_dir}/owner_pid"
  local owner_scope_file="${lock_dir}/owner_scope"
  local owner_pid=""
  local owner_scope=""

  mkdir -p "$(dirname "${target_path}")" >/dev/null 2>&1 || true

  if mkdir "${lock_dir}" 2>/dev/null; then
    write_lock_owner_metadata "${owner_file}" "${owner_scope_file}"
    echo "${lock_dir}"
    return 0
  fi

  if [[ -f "${owner_file}" ]]; then
    owner_pid="$(cat "${owner_file}" 2>/dev/null || true)"
  fi
  if [[ -f "${owner_scope_file}" ]]; then
    owner_scope="$(tr -d '\r\n' < "${owner_scope_file}" 2>/dev/null || true)"
  fi
  if supports_owner_pid_stale_lock_recovery \
    && [[ -n "${owner_pid}" ]] \
    && [[ "${owner_pid}" =~ ^[0-9]+$ ]] \
    && [[ -z "${owner_scope}" || "${owner_scope}" == "posix-pid" ]] \
    && ! kill -0 "${owner_pid}" 2>/dev/null; then
    rm -rf "${lock_dir}" >/dev/null 2>&1 || true
    if mkdir "${lock_dir}" 2>/dev/null; then
      write_lock_owner_metadata "${owner_file}" "${owner_scope_file}"
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

mktemp_adjacent_file() {
  local target_path="$1"
  local label="${2:-tmp}"
  local target_dir target_name
  target_dir="$(dirname "${target_path}")"
  target_name="$(basename "${target_path}")"
  mkdir -p "${target_dir}" >/dev/null 2>&1 || true
  mktemp "${target_dir}/.${target_name}.${label}.XXXXXX"
}

log_info() {
  if [[ "${dry_run}" == "true" ]]; then
    printf '%s\n' "$*" >&2
    return 0
  fi
  printf '%s\n' "$*"
}

backup_target_file() {
  local file_path="$1"
  local backup_path="${file_path}.bak"
  cp "${file_path}" "${backup_path}"
  chmod 600 "${backup_path}" 2>/dev/null || true
  log_info "[backup] Existing ${file_path} saved to ${backup_path}"
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

set_env_value() {
  local file_path="$1"
  local key="$2"
  local value="$3"
  local tmp_file
  tmp_file="$(mktemp_adjacent_file "${file_path}" "write")"
  awk -v key="${key}" -v value="${value}" '
    BEGIN { replaced = 0 }
    $0 ~ ("^[[:space:]]*" key "[[:space:]]*=") {
      if (!replaced) {
        print key "=" value
        replaced = 1
      }
      next
    }
    { print }
    END {
      if (!replaced) {
        print key "=" value
      }
    }
  ' "${file_path}" > "${tmp_file}"
  commit_adjacent_temp_file_with_retry "${tmp_file}" "${file_path}"
  chmod 600 "${file_path}" 2>/dev/null || true
}

generate_random_mcp_api_key() {
  local generated=""

  local python_candidate
  for python_candidate in python3 python; do
    if ! command -v "${python_candidate}" >/dev/null 2>&1; then
      continue
    fi
    generated="$("${python_candidate}" -c 'import secrets; print(secrets.token_hex(24))' 2>/dev/null || true)"
    generated="$(printf '%s' "${generated}" | tr -d '\r\n')"
    if [[ -n "${generated}" ]]; then
      printf '%s\n' "${generated}"
      return 0
    fi
  done

  if command -v py >/dev/null 2>&1; then
    for python_candidate in "-3" ""; do
      if [[ -n "${python_candidate}" ]]; then
        generated="$(py "${python_candidate}" -c 'import secrets; print(secrets.token_hex(24))' 2>/dev/null || true)"
      else
        generated="$(py -c 'import secrets; print(secrets.token_hex(24))' 2>/dev/null || true)"
      fi
      generated="$(printf '%s' "${generated}" | tr -d '\r\n')"
      if [[ -n "${generated}" ]]; then
        printf '%s\n' "${generated}"
        return 0
      fi
    done
  fi

  if command -v openssl >/dev/null 2>&1; then
    generated="$(openssl rand -hex 24 2>/dev/null | tr -d '\r\n' || true)"
    if [[ -n "${generated}" ]]; then
      printf '%s\n' "${generated}"
      return 0
    fi
  fi

  echo "Failed to generate MCP_API_KEY: no usable openssl/python3/python/py runtime is available." >&2
  return 1
}

get_env_value() {
  local file_path="$1"
  local key="$2"
  local raw_value
  raw_value="$(
    awk -v key="${key}" '
      $0 ~ ("^[[:space:]]*" key "[[:space:]]*=") {
        line = $0
        sub("^[[:space:]]*" key "[[:space:]]*=[[:space:]]*", "", line)
        value = line
      }
      END { print value }
    ' "${file_path}"
  )"
  printf '%s\n' "${raw_value%$'\r'}"
}

trim_env_value() {
  local value="${1:-}"
  value="${value%$'\r'}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s\n' "${value}"
}

read_windows_host_env_value() {
  local key="${1:-}"
  if [[ -z "${key}" ]]; then
    printf '%s\n' ""
    return 0
  fi
  if ! command -v cmd.exe >/dev/null 2>&1; then
    printf '%s\n' ""
    return 0
  fi

  local value=""
  value="$(cmd.exe /d /c "echo %${key}%" 2>/dev/null | tr -d '\r' | tail -n 1 || true)"
  value="$(trim_env_value "${value}")"
  if [[ "${value}" == "%${key}%" ]]; then
    value=""
  fi
  printf '%s\n' "${value}"
}

resolve_shell_or_host_env_value() {
  local key="${1:-}"
  local value=""
  if [[ -n "${key}" ]]; then
    value="$(trim_env_value "${!key-}")"
  fi
  if [[ -n "${value}" ]]; then
    printf '%s\n' "${value}"
    return 0
  fi
  read_windows_host_env_value "${key}"
}

validate_database_url_placeholder() {
  local file_path="$1"
  local display_path="${2:-${file_path}}"
  local database_url_line=""
  database_url_line="$(
    awk '
      /^[[:space:]]*DATABASE_URL[[:space:]]*=/ {
        line = $0
      }
      END { print line }
    ' "${file_path}"
  )"
  database_url_line="${database_url_line%$'\r'}"
  if [[ -z "${database_url_line}" ]]; then
    return 0
  fi
  if [[ "${database_url_line}" == *"__REPLACE_ME__"* || "${database_url_line}" == *"<"*">"* ]] \
    || printf '%s\n' "${database_url_line}" | grep -Eq '[Pp][Ll][Aa][Cc][Ee][Hh][Oo][Ll][Dd][Ee][Rr]'; then
    {
      echo "Generated ${display_path}, but DATABASE_URL still contains unresolved placeholders:"
      echo "  ${database_url_line}"
      echo "Replace DATABASE_URL with a real host sqlite path before using this env file."
    } >&2
    return 1
  fi
}

ensure_default_env_value() {
  local file_path="$1"
  local key="$2"
  local default_value="$3"
  local current_value
  current_value="$(trim_env_value "$(get_env_value "${file_path}" "${key}")")"
  if [[ -n "${current_value}" ]]; then
    return 0
  fi
  set_env_value "${file_path}" "${key}" "${default_value}"
}

sync_docker_wal_overrides() {
  local file_path="$1"
  local wal_enabled
  local journal_mode
  wal_enabled="$(trim_env_value "$(get_env_value "${file_path}" "RUNTIME_WRITE_WAL_ENABLED")")"
  journal_mode="$(trim_env_value "$(get_env_value "${file_path}" "RUNTIME_WRITE_JOURNAL_MODE")")"
  if [[ -n "${wal_enabled}" ]]; then
    set_env_value "${file_path}" "MEMORY_PALACE_DOCKER_WAL_ENABLED" "${wal_enabled}"
  fi
  if [[ -n "${journal_mode}" ]]; then
    set_env_value "${file_path}" "MEMORY_PALACE_DOCKER_JOURNAL_MODE" "${journal_mode}"
  fi
}

resolve_windows_db_path() {
  local db_path="${PROJECT_ROOT}/demo.db"
  local resolved_path

  resolved_path="$(resolve_windows_host_path "${db_path}")"
  if [[ "${resolved_path}" =~ ^[A-Z]:/.*$ ]]; then
    printf '%s\n' "${resolved_path}"
    return 0
  fi

  printf '%s\n' 'C:/memory_palace/demo.db'
}

dedupe_env_keys() {
  local file_path="$1"
  local key value
  while IFS= read -r key; do
    [[ -n "${key}" ]] || continue
    value="$(
      awk -v key="${key}" '
        $0 ~ ("^[[:space:]]*" key "[[:space:]]*=") {
          line = $0
          sub("^[[:space:]]*" key "[[:space:]]*=[[:space:]]*", "", line)
          value = line
        }
        END { print value }
      ' "${file_path}"
    )"
    set_env_value "${file_path}" "${key}" "${value}"
  done < <(
    awk '
      /^[[:space:]]*[A-Z0-9_]+[[:space:]]*=/ {
        line = $0
        sub(/^[[:space:]]*/, "", line)
        sub(/[[:space:]]*=.*$/, "", line)
        count[line]++
      }
      END { for (key in count) if (count[key] > 1) print key }
    ' "${file_path}" | sort
  )
}

validate_profile_placeholders() {
  local file_path="$1"
  local selected_profile="$2"
  local display_path="${3:-${file_path}}"
  if [[ "${selected_profile}" != "c" && "${selected_profile}" != "d" ]]; then
    return 0
  fi

  local -a unresolved_lines=()
  local line normalized_line
  while IFS= read -r line; do
    normalized_line="${line%$'\r'}"
    if [[ "${normalized_line}" =~ ^[[:space:]]*(ROUTER_API_BASE|RETRIEVAL_EMBEDDING_API_BASE|RETRIEVAL_RERANKER_API_BASE)[[:space:]]*=[[:space:]]*.*:PORT/ ]] \
      || [[ "${normalized_line}" =~ =[[:space:]]*(replace-with-your-key|replace-with-your-embedding-dim|your-embedding-model-id|your-reranker-model-id|<provider-vector-dim>)([[:space:]]+#.*)?[[:space:]]*$ ]] \
      || [[ "${normalized_line}" =~ =[[:space:]]*([[:alpha:]][[:alnum:]+.-]*://)?router\.example\.com([/:?#]|[[:space:]]|$) ]]; then
      unresolved_lines+=("${line}")
    fi
  done < "${file_path}"

  if [[ "${#unresolved_lines[@]}" -eq 0 ]]; then
    return 0
  fi

  {
    echo "Generated ${display_path}, but profile ${selected_profile} still contains unresolved placeholders:"
    printf '  %s\n' "${unresolved_lines[@]}"
    echo "Fill the placeholder values before using profile ${selected_profile}."
  } >&2
  return 1
}

if [[ ! -f "${base_env}" ]]; then
  echo "Missing base env template: ${base_env}" >&2
  exit 1
fi

if [[ ! -f "${override_env}" ]]; then
  echo "Missing profile template: ${override_env}" >&2
  exit 1
fi

if [[ "${dry_run}" != "true" ]]; then
  TARGET_FILE_LOCK="$(try_acquire_path_lock "${target_file}" || true)"
  if [[ -z "${TARGET_FILE_LOCK}" ]]; then
    echo "[apply-profile-lock] another apply_profile.sh process is already writing ${target_file}; wait for it to finish before retrying." >&2
    exit 1
  fi
fi

staged_file="$(mktemp_adjacent_file "${target_file}" "staged")"
cleanup_staged_file() {
  if [[ -n "${staged_file:-}" && -f "${staged_file}" ]]; then
    rm -f "${staged_file}"
  fi
  release_path_lock "${TARGET_FILE_LOCK:-}"
}
trap cleanup_staged_file EXIT

cp "${base_env}" "${staged_file}"
{
  echo
  echo "# -----------------------------------------------------------------------------"
  echo "# Appended profile overrides (${platform}/profile-${profile})"
  echo "# -----------------------------------------------------------------------------"
  cat "${override_env}"
} >> "${staged_file}"
chmod 600 "${staged_file}" 2>/dev/null || true

if [[ "${platform}" == "macos" || "${platform}" == "linux" ]]; then
  if grep -Eq '^[[:space:]]*DATABASE_URL[[:space:]]*=[[:space:]]*sqlite\+aiosqlite:////(Users|home)/[^/]+/memory_palace/agent_memory\.db([[:space:]]+#.*)?[[:space:]]*\r?$' "${staged_file}"; then
    db_path="${PROJECT_ROOT}/demo.db"
    set_env_value "${staged_file}" "DATABASE_URL" "sqlite+aiosqlite:////${db_path#/}"
    log_info "[auto-fill] DATABASE_URL set to ${db_path}"
  fi
elif [[ "${platform}" == "windows" ]]; then
  if grep -Eq '^[[:space:]]*DATABASE_URL[[:space:]]*=[[:space:]]*sqlite\+aiosqlite:///[A-Za-z]:/memory_palace/agent_memory\.db([[:space:]]+#.*)?[[:space:]]*\r?$' "${staged_file}"; then
    if db_path="$(resolve_windows_db_path)"; then
      set_env_value "${staged_file}" "DATABASE_URL" "sqlite+aiosqlite:///${db_path}"
      log_info "[auto-fill] DATABASE_URL set to ${db_path}"
    fi
  fi
fi

if [[ "${platform}" == "docker" ]]; then
  current_mcp_api_key="$(get_env_value "${staged_file}" "MCP_API_KEY")"
  if [[ -z "${current_mcp_api_key}" ]]; then
    generated_mcp_api_key="$(generate_random_mcp_api_key)"
    set_env_value "${staged_file}" "MCP_API_KEY" "${generated_mcp_api_key}"
    log_info "[auto-fill] MCP_API_KEY generated for docker profile"
  fi
  sync_docker_wal_overrides "${staged_file}"
fi

ensure_default_env_value "${staged_file}" "RUNTIME_AUTO_FLUSH_ENABLED" "true"

dedupe_env_keys "${staged_file}"
validate_database_url_placeholder "${staged_file}" "${target_file}"
allow_unresolved_profile_placeholders="$(
  resolve_shell_or_host_env_value "MEMORY_PALACE_ALLOW_UNRESOLVED_PROFILE_PLACEHOLDERS"
)"
if [[ "${allow_unresolved_profile_placeholders}" == "1" ]]; then
  log_info "[placeholder-guard] deferred profile placeholder validation to caller"
else
  validate_profile_placeholders "${staged_file}" "${profile}" "${target_file}"
fi

if [[ "${dry_run}" == "true" ]]; then
  cat "${staged_file}"
  exit 0
fi

if [[ -e "${target_file}" ]]; then
  backup_target_file "${target_file}"
fi

commit_adjacent_temp_file_with_retry "${staged_file}" "${target_file}"
chmod 600 "${target_file}" 2>/dev/null || true
staged_file=""

log_info "Generated ${target_file} from ${override_env}"
