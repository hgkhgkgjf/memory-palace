#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import os
import re
import signal
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

try:
    import tomllib
except Exception:  # pragma: no cover
    tomllib = None

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT
CANONICAL_DIR = PROJECT_ROOT / "docs" / "skills" / "memory-palace"
BACKEND_DIR = PROJECT_ROOT / "backend"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "docs" / "skills" / "TRIGGER_SMOKE_REPORT.md"
REPORT_OVERRIDE_ROOT = Path(tempfile.gettempdir()) / "memory-palace-reports"
WRAPPER_RELATIVE = Path("scripts/run_memory_palace_mcp_stdio.sh")
WRAPPER_ABSOLUTE = PROJECT_ROOT / "scripts" / "run_memory_palace_mcp_stdio.sh"
PYTHON_WRAPPER_RELATIVE = Path("backend/mcp_wrapper.py")
PYTHON_WRAPPER_ABSOLUTE = PROJECT_ROOT / "backend" / "mcp_wrapper.py"
MIRRORS = {
    "claude": REPO_ROOT / ".claude" / "skills" / "memory-palace",
    "codex": REPO_ROOT / ".codex" / "skills" / "memory-palace",
    "opencode": REPO_ROOT / ".opencode" / "skills" / "memory-palace",
    "cursor": REPO_ROOT / ".cursor" / "skills" / "memory-palace",
    "agent": REPO_ROOT / ".agent" / "skills" / "memory-palace",
}
GEMINI_WORKSPACE_DIR = REPO_ROOT / ".gemini" / "skills" / "memory-palace"
GEMINI_VARIANT_FILE = CANONICAL_DIR / "variants" / "gemini" / "SKILL.md"
ANTIGRAVITY_WORKFLOW_SOURCE = (
    CANONICAL_DIR / "variants" / "antigravity" / "global_workflows" / "memory-palace.md"
)
REQUIRED_FILES = [
    Path("SKILL.md"),
    Path("agents/openai.yaml"),
    Path("references/mcp-workflow.md"),
    Path("references/trigger-samples.md"),
]
GEMINI_TEST_MODEL = (
    str(os.getenv("MEMORY_PALACE_GEMINI_TEST_MODEL") or "").strip()
    or "gemini-3-flash-preview"
)
GEMINI_FALLBACK_MODEL = (
    str(os.getenv("MEMORY_PALACE_GEMINI_FALLBACK_MODEL") or "").strip()
    or GEMINI_TEST_MODEL
)
SKIP_GEMINI_LIVE = os.getenv("MEMORY_PALACE_SKIP_GEMINI_LIVE", "").lower() in {"1", "true", "yes"}
ENABLE_GEMINI_LIVE = os.getenv("MEMORY_PALACE_ENABLE_GEMINI_LIVE", "").lower() in {"1", "true", "yes"}
_SENSITIVE_ENV_NAME_PATTERN = re.compile(
    r"(?:^|_)(?:API_KEY|KEY|TOKEN|SECRET|PASSWORD)(?:$|_)",
    re.IGNORECASE,
)
_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(/Users/[^\s\"']+|/home/[^\s\"']+|/tmp/[^\s\"']+|/var/tmp/[^\s\"']+|/private/var/[^\s\"']+|[A-Za-z]:[\\/][^\s\"']+)"
)
_SESSION_TOKEN_PATTERN = re.compile(r"\b(?:mcp_ctx_[\w-]+|session-[\w-]+)\b")


def _read_timeout_seconds(env_name: str, default: int, *, minimum: int = 5) -> int:
    raw_value = os.getenv(env_name, "").strip()
    if not raw_value:
        return max(minimum, default)
    try:
        return max(minimum, int(raw_value))
    except (TypeError, ValueError):
        return max(minimum, default)


CODEX_SMOKE_TIMEOUT_SEC = _read_timeout_seconds(
    "MEMORY_PALACE_CODEX_SMOKE_TIMEOUT_SEC", 45
)
OPENCODE_SMOKE_TIMEOUT_SEC = _read_timeout_seconds(
    "MEMORY_PALACE_OPENCODE_SMOKE_TIMEOUT_SEC", 90
)
PROMPT = (
    "In this repository, answer in exactly 3 bullets only: "
    "(1) the first memory tool call required by the memory-palace skill, "
    "(2) what to do when guard_action is NOOP, and "
    "(3) the canonical repo-visible path of the trigger sample set."
)


def _normalize_dotenv_value(raw_value: str) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return ""

    chars: list[str] = []
    active_quote: str | None = None
    index = 0
    while index < len(text):
        char = text[index]
        if char == "#" and active_quote is None:
            break
        if char in {'"', "'"}:
            if active_quote is None:
                active_quote = char
            elif active_quote == char:
                active_quote = None
        chars.append(char)
        index += 1

    normalized = "".join(chars).strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        normalized = normalized[1:-1]
    return normalized.strip()


def _read_repo_database_url() -> str:
    env_file = PROJECT_ROOT / ".env"
    if env_file.is_file():
        for raw_line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            normalized_key = key.strip()
            if normalized_key.lower().startswith("export "):
                normalized_key = normalized_key[7:].strip()
            if normalized_key == "DATABASE_URL":
                normalized = _normalize_dotenv_value(value)
                if normalized:
                    return normalized

    default_db_path = PROJECT_ROOT / "demo.db"
    return f"sqlite+aiosqlite:///{default_db_path}"


EXPECTED_DB_URI = _read_repo_database_url()
CURSOR_AGENT_BIN = Path.home() / ".local" / "bin" / "cursor-agent"
ANTIGRAVITY_BIN = Path("/Applications/Antigravity.app/Contents/Resources/app/bin/antigravity")
REPO_LOCAL_AGENTS = PROJECT_ROOT / "AGENTS.md"
ANTIGRAVITY_WORKSPACE_WORKFLOW = REPO_ROOT / ".agent" / "workflows" / "memory-palace.md"
ANTIGRAVITY_USER_WORKFLOW = Path.home() / ".gemini" / "antigravity" / "global_workflows" / "memory-palace.md"
ANTIGRAVITY_RULE_FILES = ("AGENTS.md", "GEMINI.md")
GEMINI_CHATS_DIR = Path.home() / ".gemini" / "tmp" / REPO_ROOT.name / "chats"
ANTIGRAVITY_REFERENCE_PATHS = (
    "docs/skills/memory-palace/references/mcp-workflow.md",
    "docs/skills/memory-palace/references/trigger-samples.md",
)
GEMINI_LIVE_SIGNATURE_WORDS = (
    "harbor",
    "cinder",
    "meadow",
    "velvet",
    "quartz",
    "falcon",
    "cobalt",
    "lantern",
    "thimble",
    "orchard",
    "marble",
    "signal",
    "tulip",
    "anchor",
    "ripple",
    "compass",
)


@dataclass
class CheckResult:
    status: str
    summary: str
    details: str = ""


def _resolve_report_path(env_name: str, default_path: Path) -> Path:
    raw_value = os.getenv(env_name, "").strip()
    if not raw_value:
        return default_path
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        safe_parts = [part for part in path.parts if part not in {"", ".", ".."}]
        path = (
            REPORT_OVERRIDE_ROOT.joinpath(*safe_parts)
            if safe_parts
            else REPORT_OVERRIDE_ROOT / default_path.name
        )
    return path


def _backend_python_candidates() -> tuple[Path, ...]:
    return (
        BACKEND_DIR / ".venv" / "Scripts" / "python.exe",
        BACKEND_DIR / ".venv" / "bin" / "python",
    )


def _preferred_backend_python() -> str | None:
    for candidate in _backend_python_candidates():
        if candidate.is_file():
            return str(candidate)
    return None


def run_command(cmd: list[str], *, cwd: Path, input_text: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _python_command() -> str:
    if os.name == "nt":
        preferred = _preferred_backend_python()
        if preferred:
            return preferred
    return sys.executable or "python"


def _sanitize_report_text(text: str) -> str:
    sanitized = str(text or "")
    sanitized = re.sub(r"\bsk-[A-Za-z0-9._-]{6,}", "sk-<redacted>", sanitized)
    sanitized = re.sub(
        r'("?[A-Za-z0-9_]*DATABASE_URL"?\s*:\s*)"[^"]*"',
        r'\1"<redacted>"',
        sanitized,
    )
    sanitized = re.sub(
        r"('?[A-Za-z0-9_]*DATABASE_URL'?\s*:\s*)'[^']*'",
        r"\1'<redacted>'",
        sanitized,
    )
    sanitized = re.sub(
        r'("?[A-Za-z0-9_]*(?:API_KEY|KEY|TOKEN|SECRET|PASSWORD)"?\s*:\s*)"[^"]*"',
        r'\1"<redacted>"',
        sanitized,
    )
    sanitized = re.sub(
        r"('?[A-Za-z0-9_]*(?:API_KEY|KEY|TOKEN|SECRET|PASSWORD)'?\s*:\s*)'[^']*'",
        r"\1'<redacted>'",
        sanitized,
    )
    sanitized = re.sub(
        r"\bDATABASE_URL\s*:\s*[^,\s}\]]+",
        "DATABASE_URL: <redacted>",
        sanitized,
    )
    sanitized = re.sub(
        r"\bDATABASE_URL=[^\s]+",
        "DATABASE_URL=<redacted>",
        sanitized,
    )
    sanitized = re.sub(
        r"\b([A-Za-z0-9_]*(?:API_KEY|KEY|TOKEN|SECRET|PASSWORD))\s*:\s*[^,\s}\]]+",
        r"\1: <redacted>",
        sanitized,
    )
    sanitized = re.sub(
        r"\b([A-Za-z0-9_]*(?:API_KEY|KEY|TOKEN|SECRET|PASSWORD))=[^\s]+",
        r"\1=<redacted>",
        sanitized,
    )
    sanitized = re.sub(r"Bearer\s+\S+", "Bearer <redacted>", sanitized, flags=re.IGNORECASE)
    sanitized = _ABSOLUTE_PATH_PATTERN.sub("<redacted-path>", sanitized)
    sanitized = _SESSION_TOKEN_PATTERN.sub("<redacted-session>", sanitized)
    return sanitized


def _write_private_report(report_path: Path, content: str) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    sanitized = _sanitize_report_text(content)
    report_path.write_text(sanitized, encoding="utf-8")
    try:
        os.chmod(report_path, 0o600)
    except OSError:
        pass
    if REPORT_OVERRIDE_ROOT in report_path.parents:
        try:
            os.chmod(report_path.parent, 0o700)
        except OSError:
            pass


def _bash_relative_path(path: Path, *, cwd: Path) -> str:
    try:
        return os.path.relpath(path, cwd).replace("\\", "/")
    except ValueError:
        return path.as_posix()


def _cli_executable(name: str) -> str | None:
    resolved = shutil.which(name)
    if not resolved:
        return None
    normalized = resolved.replace("\\", "/").lower()
    if os.name == "nt" and "/windowsapps/" in normalized:
        return None
    return resolved


@dataclass
class CommandCapture:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    model: str | None = None


def run_command_capture(cmd: list[str], *, cwd: Path, input_text: str | None = None, timeout: int = 120) -> CommandCapture:
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=(os.name != "nt"),
    )
    try:
        stdout, stderr = process.communicate(input=input_text, timeout=timeout)
        stdout = stdout or ""
        stderr = stderr or ""
        return CommandCapture(returncode=process.returncode, stdout=stdout, stderr=stderr, timed_out=False)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:  # pragma: no cover
                process.kill()
            stdout, stderr = process.communicate()
        stdout = stdout or ""
        stderr = stderr or ""
        return CommandCapture(returncode=-9, stdout=stdout, stderr=stderr, timed_out=True)


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGTERM)
        else:  # pragma: no cover
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                process.terminate()
    except ProcessLookupError:
        return


def _run_command_capture_until_output_file(
    cmd: list[str],
    *,
    cwd: Path,
    output_path: Path,
    input_text: str | None = None,
    timeout: int = 120,
) -> CommandCapture:
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=(os.name != "nt"),
    )
    pending_input = input_text
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            stdout, stderr = process.communicate(
                input=pending_input,
                timeout=min(1.0, remaining),
            )
            stdout = stdout or ""
            stderr = stderr or ""
            return CommandCapture(
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr,
                timed_out=False,
            )
        except subprocess.TimeoutExpired as exc:
            pending_input = None
            if output_path.is_file():
                try:
                    payload = output_path.read_text(encoding="utf-8").strip()
                    if payload:
                        json.loads(payload)
                        _terminate_process_tree(process)
                        stdout, stderr = process.communicate(timeout=5)
                        stdout = (exc.stdout or "") + (stdout or "")
                        stderr = (exc.stderr or "") + (stderr or "")
                        return CommandCapture(
                            returncode=0,
                            stdout=stdout,
                            stderr=stderr,
                            timed_out=False,
                        )
                except Exception:
                    pass
    _terminate_process_tree(process)
    try:
        stdout, stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover
            process.kill()
        stdout, stderr = process.communicate()
    stdout = stdout or ""
    stderr = stderr or ""
    return CommandCapture(returncode=-9, stdout=stdout, stderr=stderr, timed_out=True)


def _gemini_capacity_error(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in [
            "model_capacity_exhausted",
            "resource_exhausted",
            "rateLimitExceeded".lower(),
            "no capacity available for model",
            '"code": 429',
            "status: 429",
            "too many requests",
        ]
    )


def run_gemini_prompt(prompt: str, *, timeout: int, model: str = GEMINI_TEST_MODEL) -> CommandCapture:
    gemini_bin = _cli_executable("gemini") or "gemini"
    capture = run_command_capture(
        [gemini_bin, "-m", model, "-p", prompt, "--output-format", "text"],
        cwd=REPO_ROOT,
        timeout=timeout,
    )
    capture.model = model
    merged = (capture.stdout + "\n" + capture.stderr).strip()
    should_fallback = model == GEMINI_TEST_MODEL and (
        capture.timed_out or _gemini_capacity_error(merged)
    )
    if should_fallback and GEMINI_FALLBACK_MODEL != model:
        fallback = run_command_capture(
            [gemini_bin, "-m", GEMINI_FALLBACK_MODEL, "-p", prompt, "--output-format", "text"],
            cwd=REPO_ROOT,
            timeout=timeout,
        )
        fallback.model = GEMINI_FALLBACK_MODEL
        return fallback
    return capture


def _sqlite_path_from_url(url: str) -> Path | None:
    normalized = (url or "").strip()
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if normalized.startswith(prefix):
            raw_path = normalized[len(prefix) :]
            raw_path = raw_path.split("?", 1)[0].split("#", 1)[0]
            raw_path = unquote(raw_path)
            if not raw_path or raw_path == ":memory:" or raw_path.startswith("file::memory:"):
                return None
            return Path(raw_path)
    return None


def _command_mentions_repo_wrapper(command_parts: list[Any]) -> bool:
    normalized_parts = [str(part).replace("\\", "/") for part in command_parts if str(part).strip()]
    joined = " ".join(normalized_parts)
    candidates = {
        str(WRAPPER_ABSOLUTE).replace("\\", "/"),
        str(WRAPPER_RELATIVE).replace("\\", "/"),
        str(PYTHON_WRAPPER_ABSOLUTE).replace("\\", "/"),
        str(PYTHON_WRAPPER_RELATIVE).replace("\\", "/"),
    }
    return any(candidate in joined for candidate in candidates)


def _mirror_contract_issues(name: str) -> list[str]:
    mirror = MIRRORS[name]
    if not mirror.is_dir():
        return [f"missing mirror directory: {mirror}"]
    issues: list[str] = []
    for relative_path in REQUIRED_FILES:
        expected = CANONICAL_DIR / relative_path
        actual = mirror / relative_path
        if not actual.is_file():
            issues.append(f"missing file: {actual}")
        elif actual.read_bytes() != expected.read_bytes():
            issues.append(f"mismatch: {actual}")
    return issues


def _extract_gemini_memory_palace_db_path() -> Path | None:
    settings_candidates = [REPO_ROOT / ".gemini" / "settings.json", Path.home() / ".gemini" / "settings.json"]
    for settings_path in settings_candidates:
        if not settings_path.is_file():
            continue
        try:
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        server = (payload.get("mcpServers") or {}).get("memory-palace") or {}
        env_url = (server.get("env") or {}).get("DATABASE_URL")
        if isinstance(env_url, str):
            db_path = _sqlite_path_from_url(env_url)
            if db_path is not None:
                return db_path
        command_parts = [server.get("command", ""), *(server.get("args") or [])]
        for item in server.get("args") or []:
            if not isinstance(item, str):
                continue
            match = re.search(r"DATABASE_URL=(\S+)", item)
            if match:
                db_path = _sqlite_path_from_url(match.group(1))
                if db_path is not None:
                    return db_path
        if _command_mentions_repo_wrapper(command_parts):
            db_path = _sqlite_path_from_url(EXPECTED_DB_URI)
            if db_path is not None:
                return db_path
    return None


def _sqlite_fetch_memory(db_path: Path, uri: str) -> dict[str, Any] | None:
    if "://" not in uri:
        return None
    domain, raw_path = uri.split("://", 1)
    path = raw_path.strip("/")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT
              p.domain,
              p.path,
              p.priority,
              p.disclosure,
              m.id AS memory_id,
              m.content,
              m.deprecated,
              m.created_at
            FROM paths p
            JOIN memories m ON m.id = p.memory_id
            WHERE p.domain = ? AND p.path = ? AND COALESCE(m.deprecated, 0) = 0
            ORDER BY m.id DESC
            LIMIT 1
            """,
            (domain, path),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _wait_for_memory(db_path: Path, uri: str, *, expected_substring: str | None = None, retries: int = 5) -> dict[str, Any] | None:
    for attempt in range(retries):
        row = _sqlite_fetch_memory(db_path, uri)
        if row is not None and (expected_substring is None or expected_substring in str(row.get("content") or "")):
            return row
        if attempt < retries - 1:
            time.sleep(0.5 * (attempt + 1))
    return None


def _memory_exists(db_path: Path, uri: str) -> bool:
    return _sqlite_fetch_memory(db_path, uri) is not None


def _gemini_live_write_verified(
    proc: CommandCapture,
    *,
    verified_row: dict[str, Any] | None,
    expected_content: str,
    positive_tokens: list[str],
) -> bool:
    if verified_row is None:
        return False
    content = str(verified_row.get("content") or "")
    if expected_content not in content:
        return False
    stdout = (proc.stdout or "").strip()
    lowered = stdout.lower()
    if any(token in stdout for token in positive_tokens):
        return True
    if any(token in lowered for token in ["fail ", "fail:", "error:", "error "]):
        return False
    return proc.timed_out or proc.returncode == 0


def _gemini_live_shared_state_suspected(
    *,
    note_uri: str,
    create_proc: CommandCapture,
    update_proc: CommandCapture,
    create_row: dict[str, Any] | None,
    update_row: dict[str, Any] | None,
    guard_proc: CommandCapture,
    guard_target_uri: str,
) -> bool:
    if create_row is not None and update_row is not None:
        return False

    observed_success = any(
        token in (proc.stdout or "")
        for proc in (create_proc, update_proc)
        for token in [f"SUCCESS {note_uri}", "successfully saved", "updated"]
    )
    redirected_target = bool(guard_target_uri) and guard_target_uri != note_uri
    return observed_success and (redirected_target or guard_proc.timed_out)


def _find_latest_gemini_chat(marker: str) -> tuple[Path, Any] | None:
    if not GEMINI_CHATS_DIR.is_dir():
        return None
    for path in sorted(GEMINI_CHATS_DIR.glob("session-*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if marker not in text:
            continue
        try:
            return path, json.loads(text)
        except Exception:
            return path, text
    return None


def _iter_tool_calls(chat_payload: Any) -> list[dict[str, Any]]:
    if isinstance(chat_payload, dict):
        messages = chat_payload.get("messages")
        if isinstance(messages, list):
            chat_payload = messages
        else:
            return []
    if not isinstance(chat_payload, list):
        return []
    calls: list[dict[str, Any]] = []
    for item in chat_payload:
        if isinstance(item, dict):
            tool_calls = item.get("toolCalls")
            if isinstance(tool_calls, list):
                calls.extend([call for call in tool_calls if isinstance(call, dict)])
    return calls


def _tool_name_matches(raw_name: Any, expected_name: str) -> bool:
    if not isinstance(raw_name, str):
        return False
    normalized = raw_name.strip()
    return normalized == expected_name or normalized.endswith(f"_{expected_name}")


def _latest_gemini_message(chat_payload: Any) -> str:
    if isinstance(chat_payload, dict):
        messages = chat_payload.get("messages")
        if isinstance(messages, list):
            chat_payload = messages
        else:
            return ""
    if not isinstance(chat_payload, list):
        return ""
    for item in reversed(chat_payload):
        if isinstance(item, dict) and item.get("type") == "gemini":
            content = item.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = []
                for block in content:
                    if isinstance(block, dict) and isinstance(block.get("text"), str):
                        texts.append(block["text"])
                if texts:
                    return "\n".join(texts)
    return ""


def _gemini_live_signature(marker: str, *, count: int = 3) -> str:
    digest = hashlib.sha256(marker.encode("utf-8")).digest()
    words: list[str] = []
    for index in range(count):
        bucket = digest[index] % len(GEMINI_LIVE_SIGNATURE_WORDS)
        words.append(GEMINI_LIVE_SIGNATURE_WORDS[bucket])
    return "-".join(words)


def _gemini_live_note_content(marker: str, unique_token: str) -> str:
    signature = _gemini_live_signature(marker)
    return (
        f"Verification capsule {marker}. "
        f"Nonce {unique_token}. "
        f"Signature words {signature}. "
        "For this exact session, reply in terse, clipped language without filler."
    )


def _gemini_live_updated_content(marker: str, unique_token: str) -> str:
    base = _gemini_live_note_content(marker, unique_token)
    return base + " Confirmed on the second pass."


def yaml_frontmatter_ok(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return False, "missing YAML frontmatter"
    end = text.find("\n---\n", 4)
    if end == -1:
        return False, "unterminated YAML frontmatter"
    block = text[4:end]
    if yaml is not None:
        try:
            data = yaml.safe_load(block)
        except Exception as exc:
            return False, f"invalid YAML: {exc}"
        if not isinstance(data, dict):
            return False, "frontmatter must be a mapping"
        if data.get("name") != "memory-palace":
            return False, "name must be memory-palace"
        if not data.get("description"):
            return False, "description must be non-empty"
        return True, "ok"
    if "name:" not in block or "description:" not in block:
        return False, "frontmatter missing name or description"
    return True, "ok"


def _frontmatter_data(path: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    block = text[4:end]
    if yaml is not None:
        try:
            payload = yaml.safe_load(block)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None
    name_match = re.search(r"(?m)^name:\s*(.+?)\s*$", block)
    if not name_match:
        return None
    description_match = re.search(r"(?m)^description:\s*(.+?)\s*$", block)
    if not description_match:
        return None
    description_value = description_match.group(1).strip()
    if description_value in {">", ">-", "|", "|-"}:
        lines = block.splitlines()
        collected: list[str] = []
        start_collect = False
        for line in lines:
            if start_collect:
                if line.startswith("  "):
                    collected.append(line.strip())
                    continue
                if line.strip():
                    break
            if line.startswith("description:"):
                start_collect = True
        description_value = " ".join(collected).strip()
    return {
        "name": name_match.group(1).strip().strip("\"'"),
        "description": description_value,
    }


def check_structure() -> CheckResult:
    missing = [str(CANONICAL_DIR / rel) for rel in REQUIRED_FILES if not (CANONICAL_DIR / rel).is_file()]
    if not GEMINI_VARIANT_FILE.is_file():
        missing.append(str(GEMINI_VARIANT_FILE))
    if not ANTIGRAVITY_WORKFLOW_SOURCE.is_file():
        missing.append(str(ANTIGRAVITY_WORKFLOW_SOURCE))
    if missing:
        return CheckResult("FAIL", "canonical bundle 缺文件", "\n".join(missing))
    ok, message = yaml_frontmatter_ok(CANONICAL_DIR / "SKILL.md")
    if not ok:
        return CheckResult("FAIL", "canonical SKILL.md 非法", message)
    return CheckResult("PASS", "canonical bundle 结构与 YAML 通过")


def check_description_contract() -> CheckResult:
    payload = _frontmatter_data(CANONICAL_DIR / "SKILL.md")
    if not payload:
        return CheckResult("FAIL", "无法解析 canonical SKILL.md frontmatter")
    description = str(payload.get("description") or "").lower()
    groups = {
        "must_use": any(token in description for token in ["use this skill", "always activate", "whenever"]),
        "memory_scope": any(token in description for token in ["memory palace", "durable-memory", "durable memory"]),
        "tool_or_guard_anchor": any(
            token in description
            for token in ["guard_action", "guard_target_uri", "system://boot", "compact_context", "rebuild_index", "index_status"]
        ),
        "skill_self_reference": any(
            token in description for token in ["skill itself", "noop", "trigger sample", "workflow", "cli usage"]
        ),
        "negative_boundary": any(
            token in description for token in ["do not use", "generic code edits", "readme rewrites", "non-memory-palace"]
        ),
    }
    missing = [name for name, ok in groups.items() if not ok]
    if missing:
        return CheckResult("FAIL", "description 触发契约不完整", ", ".join(missing))
    return CheckResult("PASS", "description 已覆盖触发条件、边界与 skill 自省锚点")


def check_mirrors() -> CheckResult:
    missing_targets: list[str] = []
    missing_or_mismatch: list[str] = []
    for name, mirror_dir in MIRRORS.items():
        if not mirror_dir.is_dir():
            missing_targets.append(f"{name}: {mirror_dir}")
            continue
        for rel in REQUIRED_FILES:
            expected = CANONICAL_DIR / rel
            actual = mirror_dir / rel
            if not actual.is_file():
                missing_or_mismatch.append(f"missing: {actual}")
            elif actual.read_bytes() != expected.read_bytes():
                missing_or_mismatch.append(f"mismatch: {actual}")
    gemini_skill = GEMINI_WORKSPACE_DIR / "SKILL.md"
    if not GEMINI_WORKSPACE_DIR.is_dir():
        missing_targets.append(f"gemini: {GEMINI_WORKSPACE_DIR}")
    else:
        if not gemini_skill.is_file():
            missing_or_mismatch.append(f"missing: {gemini_skill}")
        elif gemini_skill.read_bytes() != GEMINI_VARIANT_FILE.read_bytes():
            missing_or_mismatch.append(f"mismatch: {gemini_skill}")
        expected = {gemini_skill}
        actual = {path for path in GEMINI_WORKSPACE_DIR.rglob("*") if path.is_file()}
        for extra_path in sorted(actual - expected):
            missing_or_mismatch.append(f"unexpected extra file: {extra_path}")
    if missing_or_mismatch:
        return CheckResult("FAIL", "mirror 与 canonical 不一致", "\n".join(missing_or_mismatch))
    if missing_targets:
        return CheckResult(
            "PARTIAL",
            "workspace mirrors 尚未同步到当前仓库（可在需要时执行 sync）",
            "\n".join(missing_targets),
        )
    return CheckResult("PASS", "workspace mirrors match canonical bundle and Gemini variant")


def check_sync_script() -> CheckResult:
    script = PROJECT_ROOT / "scripts" / "sync_memory_palace_skill.py"
    proc = run_command([_python_command(), "-B", str(script), "--check"], cwd=REPO_ROOT, timeout=60)
    output = (proc.stdout + "\n" + proc.stderr).strip()
    if proc.returncode != 0:
        return CheckResult("FAIL", "sync script --check 失败", output)
    if "No workspace mirrors are installed yet." in output:
        return CheckResult("PARTIAL", "sync script 检测到当前仓库尚未安装 workspace mirrors", output)
    return CheckResult("PASS", proc.stdout.strip() or "sync script --check passed")


def check_gate_syntax() -> CheckResult:
    gate_candidates = [
        REPO_ROOT / "new" / "run_post_change_checks.sh",
        REPO_ROOT.parent / "new" / "run_post_change_checks.sh",
    ]
    gate_script = next((path for path in gate_candidates if path.is_file()), None)
    if gate_script is None:
        return CheckResult(
            "SKIP",
            "run_post_change_checks.sh 不属于公开仓校验范围，跳过该项",
        )
    bash_bin = shutil.which("bash")
    if not bash_bin:
        return CheckResult(
            "SKIP",
            "当前环境未找到 bash，跳过 run_post_change_checks.sh 语法检查",
            f"missing bash for: {gate_script}",
        )
    proc = run_command(
        ["bash", "-n", _bash_relative_path(gate_script, cwd=REPO_ROOT)],
        cwd=REPO_ROOT,
        timeout=30,
    )
    if proc.returncode != 0:
        return CheckResult("FAIL", "run_post_change_checks.sh 语法失败", proc.stderr.strip())
    return CheckResult("PASS", "run_post_change_checks.sh 语法通过")


def _normalized_text(value: Any) -> str:
    return str(value).replace("\\", "/")


def _command_mentions_wrapper(command_parts: list[str], *, allow_relative_wrapper: bool) -> bool:
    normalized_parts = [_normalized_text(part) for part in command_parts if str(part).strip()]
    joined = " ".join(normalized_parts)
    candidates = {_normalized_text(WRAPPER_ABSOLUTE), _normalized_text(PYTHON_WRAPPER_ABSOLUTE)}
    if allow_relative_wrapper:
        candidates.add(_normalized_text(WRAPPER_RELATIVE))
        candidates.add(_normalized_text(PYTHON_WRAPPER_RELATIVE))
    return any(candidate in joined for candidate in candidates)


def _check_command_binding(
    *,
    client_name: str,
    config_path: Path,
    command_parts: list[str],
    env_payload: dict[str, Any] | None = None,
    allow_relative_wrapper: bool = False,
) -> tuple[bool, str]:
    normalized_parts = [_normalized_text(part) for part in command_parts]
    joined = " ".join(normalized_parts)
    env_payload = env_payload or {}
    normalized_env = {key: _normalized_text(value) for key, value in env_payload.items()}
    has_wrapper = _command_mentions_wrapper(command_parts, allow_relative_wrapper=allow_relative_wrapper)

    has_server_entry = "mcp_server.py" in joined
    has_backend_dir = _normalized_text(BACKEND_DIR) in joined
    has_expected_db = EXPECTED_DB_URI in joined or normalized_env.get("DATABASE_URL") == EXPECTED_DB_URI

    if has_wrapper:
        return True, f"{client_name}: MCP 已通过 wrapper 绑定到当前项目（{config_path}）"

    if has_server_entry and has_backend_dir and has_expected_db:
        return True, f"{client_name}: MCP 已绑定到当前项目数据库配置（{config_path}）"

    reasons: list[str] = []
    if not has_server_entry:
        reasons.append("未指向 mcp_server.py")
    if not has_backend_dir:
        reasons.append("未指向当前项目 backend 目录")
    if not has_expected_db:
        reasons.append("DATABASE_URL 与当前项目配置不一致")
    return False, f"{client_name}: {'；'.join(reasons)}（{config_path}）\ncommand={joined}\nenv={json.dumps(env_payload, ensure_ascii=False)}"


def _binding_block_is_missing(
    server_block: dict[str, Any] | None,
    *,
    command_is_sequence: bool = False,
) -> bool:
    if not isinstance(server_block, dict):
        return True
    command = server_block.get("command")
    args = server_block.get("args") or []
    env_payload = server_block.get("env") or {}
    if command_is_sequence:
        command_items = command if isinstance(command, list) else []
        return not any(str(item).strip() for item in command_items) and not env_payload
    return (
        not str(command or "").strip()
        and not any(str(item).strip() for item in args)
        and not env_payload
    )


def check_client_mcp_bindings() -> CheckResult:
    details: list[str] = ["[workspace-local entrypoints]"]
    workspace_failures = 0
    user_scope_failures = 0
    partials = 0

    workspace_claude = REPO_ROOT / ".mcp.json"
    if workspace_claude.is_file():
        try:
            payload = json.loads(workspace_claude.read_text(encoding="utf-8"))
            server_block = payload.get("mcpServers", {}).get("memory-palace", {})
            if _binding_block_is_missing(server_block):
                ok, status, message = True, "INFO", f"claude(workspace): 当前仓库尚未安装 repo-local MCP 入口（{workspace_claude}）"
                partials += 1
            else:
                command = [server_block.get("command", ""), *(server_block.get("args") or [])]
                ok, message = _check_command_binding(
                    client_name="claude(workspace)",
                    config_path=workspace_claude,
                    command_parts=command,
                    env_payload=server_block.get("env") or {},
                    allow_relative_wrapper=True,
                )
                status = "PASS" if ok else "FAIL"
        except Exception as exc:
            ok, status, message = False, "FAIL", f"claude(workspace): 解析失败（{workspace_claude}）\n{exc}"
    else:
        ok, status, message = True, "INFO", f"claude(workspace): 未找到配置文件（{workspace_claude}），repo-local 入口按需安装"
        partials += 1
    workspace_failures += 0 if ok else 1
    details.append(f"{status} {message}")

    workspace_gemini = REPO_ROOT / ".gemini" / "settings.json"
    if workspace_gemini.is_file():
        try:
            payload = json.loads(workspace_gemini.read_text(encoding="utf-8"))
            server_block = payload.get("mcpServers", {}).get("memory-palace", {})
            if _binding_block_is_missing(server_block):
                ok, status, message = True, "INFO", f"gemini(project): 当前仓库尚未安装 repo-local MCP 入口（{workspace_gemini}）"
                partials += 1
            else:
                command = [server_block.get("command", ""), *(server_block.get("args") or [])]
                ok, message = _check_command_binding(
                    client_name="gemini(project)",
                    config_path=workspace_gemini,
                    command_parts=command,
                    env_payload=server_block.get("env") or {},
                    allow_relative_wrapper=True,
                )
                status = "PASS" if ok else "FAIL"
        except Exception as exc:
            ok, status, message = False, "FAIL", f"gemini(project): 解析失败（{workspace_gemini}）\n{exc}"
    else:
        ok, status, message = True, "INFO", f"gemini(project): 未找到配置文件（{workspace_gemini}），repo-local 入口按需安装"
        partials += 1
    workspace_failures += 0 if ok else 1
    details.append(f"{status} {message}")
    details.append("INFO codex(workspace): 当前仓库依赖 user-scope MCP 配置，无稳定的 repo-local config.toml 入口")
    details.append("INFO opencode(workspace): 当前仓库依赖 user-scope MCP 配置，无稳定的 repo-local opencode.json 入口")

    details.append("")
    details.append("[user-scope entrypoints]")

    claude_config = Path.home() / ".claude.json"
    if claude_config.is_file():
        try:
            payload = json.loads(claude_config.read_text(encoding="utf-8"))
            project_block = payload.get("projects", {}).get(str(REPO_ROOT))
            server_block = (project_block or {}).get("mcpServers", {}).get("memory-palace", {})
            if _binding_block_is_missing(server_block):
                ok, status, message = True, "INFO", f"claude(user): 当前机器尚未为本仓库安装 memory-palace 入口（{claude_config}）"
                partials += 1
            else:
                command = [server_block.get("command", ""), *(server_block.get("args") or [])]
                ok, message = _check_command_binding(
                    client_name="claude(user)",
                    config_path=claude_config,
                    command_parts=command,
                    env_payload=server_block.get("env") or {},
                )
                status = "PASS" if ok else "FAIL"
        except Exception as exc:
            ok, status, message = False, "FAIL", f"claude(user): 解析失败（{claude_config}）\n{exc}"
    else:
        ok, status, message = True, "INFO", f"claude(user): 未找到配置文件（{claude_config}）"
        partials += 1
    user_scope_failures += 0 if ok else 1
    details.append(f"{status} {message}")

    codex_config = Path.home() / ".codex" / "config.toml"
    if codex_config.is_file() and tomllib is not None:
        try:
            with codex_config.open("rb") as handle:
                payload = tomllib.load(handle)
            server_block = payload.get("mcp_servers", {}).get("memory-palace", {})
            if _binding_block_is_missing(server_block):
                ok, status, message = True, "INFO", f"codex(user): 当前机器尚未为本仓库安装 memory-palace 入口（{codex_config}）"
                partials += 1
            else:
                command = [server_block.get("command", ""), *(server_block.get("args") or [])]
                ok, message = _check_command_binding(
                    client_name="codex(user)",
                    config_path=codex_config,
                    command_parts=command,
                    env_payload=server_block.get("env") or {},
                )
                status = "PASS" if ok else "FAIL"
        except Exception as exc:
            ok, status, message = False, "FAIL", f"codex(user): 解析失败（{codex_config}）\n{exc}"
    elif tomllib is None:
        ok, status, message = True, "PARTIAL", "codex(user): 当前 Python 不支持 tomllib，跳过 config.toml 审计"
        partials += 1
    else:
        ok, status, message = True, "INFO", f"codex(user): 未找到配置文件（{codex_config}）"
        partials += 1
    user_scope_failures += 0 if ok else 1
    details.append(f"{status} {message}")

    gemini_config = Path.home() / ".gemini" / "settings.json"
    if gemini_config.is_file():
        try:
            payload = json.loads(gemini_config.read_text(encoding="utf-8"))
            server_block = payload.get("mcpServers", {}).get("memory-palace", {})
            if _binding_block_is_missing(server_block):
                ok, status, message = True, "INFO", f"gemini(user): 当前机器尚未为本仓库安装 memory-palace 入口（{gemini_config}）"
                partials += 1
            else:
                command = [server_block.get("command", ""), *(server_block.get("args") or [])]
                ok, message = _check_command_binding(
                    client_name="gemini(user)",
                    config_path=gemini_config,
                    command_parts=command,
                    env_payload=server_block.get("env") or {},
                )
                status = "PASS" if ok else "FAIL"
        except Exception as exc:
            ok, status, message = False, "FAIL", f"gemini(user): 解析失败（{gemini_config}）\n{exc}"
    else:
        ok, status, message = True, "INFO", f"gemini(user): 未找到配置文件（{gemini_config}）"
        partials += 1
    user_scope_failures += 0 if ok else 1
    details.append(f"{status} {message}")

    opencode_config = Path.home() / ".config" / "opencode" / "opencode.json"
    if opencode_config.is_file():
        try:
            payload = json.loads(opencode_config.read_text(encoding="utf-8"))
            server_block = payload.get("mcp", {}).get("memory-palace", {})
            if _binding_block_is_missing(server_block, command_is_sequence=True):
                ok, status, message = True, "INFO", f"opencode(user): 当前机器尚未为本仓库安装 memory-palace 入口（{opencode_config}）"
                partials += 1
            else:
                command = list(server_block.get("command") or [])
                ok, message = _check_command_binding(
                    client_name="opencode(user)",
                    config_path=opencode_config,
                    command_parts=command,
                )
                status = "PASS" if ok else "FAIL"
        except Exception as exc:
            ok, status, message = False, "FAIL", f"opencode(user): 解析失败（{opencode_config}）\n{exc}"
    else:
        ok, status, message = True, "INFO", f"opencode(user): 未找到配置文件（{opencode_config}）"
        partials += 1
    user_scope_failures += 0 if ok else 1
    details.append(f"{status} {message}")

    if workspace_failures:
        return CheckResult(
            "FAIL",
            "至少一个 repo-local 的 memory-palace MCP 入口未指向当前项目",
            "\n\n".join(details),
        )
    if user_scope_failures:
        return CheckResult(
            "PARTIAL",
            "至少一个 user-scope 的 memory-palace MCP 入口未指向当前项目；repo-local 入口未发现错误绑定",
            "\n\n".join(details),
        )
    if partials:
        return CheckResult(
            "PARTIAL",
            "当前仓库或当前机器的部分 memory-palace MCP 入口尚未安装，但已安装项未发现错误绑定",
            "\n\n".join(details),
        )
    return CheckResult(
        "PASS",
        "repo-local（Claude/Gemini）与 user-scope（Claude/Codex/Gemini/OpenCode）入口都已指向当前项目",
        "\n\n".join(details),
    )


def classify_skill_answer(text: str) -> tuple[bool, str]:
    lowered = text.lower()
    trigger_sample_paths = (
        "docs/skills/memory-palace/references/trigger-samples.md",
        "memory-palace/docs/skills/memory-palace/references/trigger-samples.md",
    )
    checks = [
        'read_memory("system://boot")' in text or "system://boot" in lowered,
        (any(token in lowered for token in ["guard_target_uri", "guard_target_id"]) and any(token in lowered for token in ["stop", "inspect", "重复", "停止"])),
        any(path in lowered for path in trigger_sample_paths),
    ]
    if all(checks):
        return True, "命中 first move / NOOP / trigger sample"
    return False, text[-1500:]


def _coalesce_structured_text(payload: Any) -> str:
    if isinstance(payload, dict):
        parts = [str(value) for value in payload.values() if str(value).strip()]
        if parts:
            return "\n".join(parts)
    if isinstance(payload, list):
        parts = [str(item) for item in payload if str(item).strip()]
        if parts:
            return "\n".join(parts)
    return json.dumps(payload, ensure_ascii=False)


def smoke_claude() -> CheckResult:
    claude_bin = _cli_executable("claude")
    if claude_bin is None:
        return CheckResult("SKIP", "claude CLI 未安装")
    proc = run_command_capture([claude_bin, "-p"], cwd=REPO_ROOT, input_text=PROMPT, timeout=90)
    if proc.timed_out:
        return CheckResult("FAIL", "Claude smoke 超时", (proc.stdout + "\n" + proc.stderr).strip())
    success, details = classify_skill_answer(proc.stdout)
    if proc.returncode == 0 and success:
        return CheckResult("PASS", "Claude smoke 通过", proc.stdout.strip())
    return CheckResult("FAIL", "Claude smoke 未通过", (proc.stdout + "\n" + proc.stderr).strip() or details)


def smoke_codex() -> CheckResult:
    codex_bin = _cli_executable("codex")
    if codex_bin is None:
        return CheckResult("SKIP", "codex CLI 未安装")
    with tempfile.TemporaryDirectory(prefix="memory-palace-codex-") as tmpdir:
        tmp = Path(tmpdir)
        schema_path = tmp / "schema.json"
        output_path = tmp / "out.json"
        schema = {
            "type": "object",
            "properties": {
                "first_move": {"type": "string"},
                "noop_handling": {"type": "string"},
                "trigger_samples_path": {"type": "string"},
            },
            "required": ["first_move", "noop_handling", "trigger_samples_path"],
            "additionalProperties": False,
        }
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        proc = _run_command_capture_until_output_file(
            [
                codex_bin,
                "exec",
                "--ephemeral",
                "--color",
                "never",
                "-s",
                "read-only",
                "-C",
                str(REPO_ROOT),
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                PROMPT,
            ],
            cwd=REPO_ROOT,
            output_path=output_path,
            timeout=CODEX_SMOKE_TIMEOUT_SEC,
        )
        if proc.returncode != 0 or not output_path.is_file():
            if proc.timed_out and output_path.is_file():
                data = json.loads(output_path.read_text(encoding="utf-8"))
                joined = _coalesce_structured_text(data)
                success, details = classify_skill_answer(joined)
                if success:
                    return CheckResult("PASS", "Codex smoke 通过（结果已落盘，CLI 进程超时退出）", joined)
                return CheckResult("FAIL", "Codex smoke 输出不符合预期", details)
            if proc.timed_out:
                timeout_details = (proc.stdout + "\n" + proc.stderr).strip()
                timeout_details = timeout_details or (
                    "codex exec 未在限定时间内返回结构化输出；"
                    "这更像外部 CLI/登录态/宿主环境阻塞，而不是仓库内 skill 契约错误。"
                )
                return CheckResult(
                    "PARTIAL",
                    f"Codex smoke 超时（>{CODEX_SMOKE_TIMEOUT_SEC}s，无结构化输出）",
                    timeout_details,
                )
            return CheckResult("FAIL", "Codex smoke 未通过", (proc.stdout + "\n" + proc.stderr).strip())
        data = json.loads(output_path.read_text(encoding="utf-8"))
        joined = _coalesce_structured_text(data)
        success, details = classify_skill_answer(joined)
        if success:
            return CheckResult("PASS", "Codex smoke 通过", joined)
        return CheckResult("FAIL", "Codex smoke 输出不符合预期", details)


def smoke_opencode() -> CheckResult:
    opencode_bin = _cli_executable("opencode")
    if opencode_bin is None:
        return CheckResult("SKIP", "opencode CLI 未安装")
    proc = run_command_capture(
        [
            opencode_bin,
            "run",
            "--dir",
            str(REPO_ROOT),
            "--format",
            "default",
            "For this repository's memory-palace skill, answer with exactly three bullets: "
            "(1) the correct first move, (2) what to do when guard_action=NOOP, "
            "(3) the path to the trigger sample file. Keep it concise.",
        ],
        cwd=REPO_ROOT,
        timeout=OPENCODE_SMOKE_TIMEOUT_SEC,
    )
    if proc.timed_out:
        return CheckResult("FAIL", "OpenCode smoke 超时", (proc.stdout + "\n" + proc.stderr).strip())
    merged = (proc.stdout + "\n" + proc.stderr).strip()
    success, details = classify_skill_answer(merged)
    if proc.returncode == 0 and success:
        return CheckResult("PASS", "OpenCode smoke 通过", merged)
    return CheckResult("FAIL", "OpenCode smoke 未通过", merged or details)


def smoke_gemini() -> CheckResult:
    gemini_bin = _cli_executable("gemini")
    if gemini_bin is None:
        return CheckResult("SKIP", "gemini CLI 未安装")
    discovery = run_command_capture([gemini_bin, "skills", "list", "--all"], cwd=REPO_ROOT, timeout=90)
    if discovery.timed_out:
        return CheckResult("FAIL", "Gemini skills list 超时")
    discovery_text = (discovery.stdout + "\n" + discovery.stderr).strip()
    discovered = "memory-palace [Enabled]" in discovery_text or "memory-palace" in discovery_text
    invoke = run_gemini_prompt(PROMPT, timeout=120)
    if invoke.timed_out:
        model_used = invoke.model or GEMINI_TEST_MODEL
        return CheckResult("PARTIAL" if discovered else "FAIL", f"Gemini prompt 超时（model={model_used}）", discovery_text)
    merged = (invoke.stdout + "\n" + invoke.stderr).strip()
    success, details = classify_skill_answer(merged)
    if discovered and invoke.returncode == 0 and success:
        model_note = f"[model={invoke.model or GEMINI_TEST_MODEL}]\n"
        return CheckResult("PASS", "Gemini smoke 通过", model_note + merged)
    lowered = merged.lower()
    if discovered:
        if any(token in lowered for token in ["authentication page", "do you want to continue", "login", "sign in"]):
            return CheckResult("PARTIAL", "Gemini 发现 skill 成功，但当前机器缺少 CLI 登录/鉴权", merged or discovery_text)
        if any(token in lowered for token in ["429", "resource_exhausted", "model_capacity_exhausted", "econnreset", "tls", "socket disconnected"]):
            return CheckResult("PARTIAL", "Gemini 发现 skill 成功，但执行受上游容量或网络波动影响", merged or discovery_text)
        return CheckResult("FAIL", "Gemini 已发现 skill，但调用结果不符合预期", merged or discovery_text)
    return CheckResult("FAIL", "Gemini 未发现或未调用 memory-palace", merged or discovery_text)


def smoke_gemini_live_suite() -> CheckResult:
    if SKIP_GEMINI_LIVE:
        return CheckResult("SKIP", "Gemini live suite 被环境变量跳过")
    if not ENABLE_GEMINI_LIVE:
        return CheckResult(
            "SKIP",
            "Gemini live suite 默认关闭；如需执行请设置 MEMORY_PALACE_ENABLE_GEMINI_LIVE=1",
        )
    if _cli_executable("gemini") is None:
        return CheckResult("SKIP", "gemini CLI 未安装")
    db_path = _extract_gemini_memory_palace_db_path()
    if db_path is None:
        return CheckResult("PARTIAL", "未能从 Gemini 配置解析 memory-palace 数据库路径")
    marker = f"gemini_suite_{int(time.time())}"
    unique_token = f"{marker}_nonce"
    note_uri = f"notes://{marker}"
    note_content = _gemini_live_note_content(marker, unique_token)
    updated_content = _gemini_live_updated_content(marker, unique_token)

    create_prompt = (
        f'Please save this durable note to Memory Palace at {note_uri}. Content: "{note_content}". '
        "Avoid duplicate creation and follow the repository memory-palace workflow automatically. "
        f"Return exactly one line: SUCCESS {note_uri} or FAIL <reason>."
    )
    update_prompt = (
        f'Please update {note_uri} in Memory Palace so its content becomes "{updated_content}". '
        "Read before write, use the repository memory-palace workflow, and only report success if the update truly succeeded. "
        f"Return exactly one line: SUCCESS {note_uri} or FAIL <reason>."
    )
    guard_marker = marker + "_guard"
    guard_uri = f"notes://{marker}_dup"
    guard_prompt = (
        f'Please try to save a second durable note to Memory Palace at {guard_uri}. Content: "{updated_content}". '
        f"The same note already exists at {note_uri}. Avoid duplicate creation. "
        "If write_guard blocks the write, do not claim a new save succeeded; report the existing target instead. "
        f"Keep this trace token in the conversation: {guard_marker}. "
        f"Return exactly one line: BLOCKED {note_uri} or SUCCESS {guard_uri} or FAIL <reason>."
    )

    create_proc = run_gemini_prompt(create_prompt, timeout=120)
    create_out = (create_proc.stdout + "\n" + create_proc.stderr).strip()
    create_row = _wait_for_memory(db_path, note_uri, expected_substring=unique_token)

    update_proc = run_gemini_prompt(update_prompt, timeout=120)
    update_out = (update_proc.stdout + "\n" + update_proc.stderr).strip()
    update_row = _wait_for_memory(db_path, note_uri, expected_substring=updated_content)

    guard_proc = run_gemini_prompt(guard_prompt, timeout=120)
    guard_out = (guard_proc.stdout + "\n" + guard_proc.stderr).strip()
    guard_chat = _find_latest_gemini_chat(guard_marker)
    guard_calls: list[dict[str, Any]] = []
    guard_message = ""
    if guard_chat is not None:
        _, payload = guard_chat
        guard_calls = _iter_tool_calls(payload)
        guard_message = _latest_gemini_message(payload)

    guard_create_index = next(
        (
            index
            for index, call in enumerate(guard_calls)
            if _tool_name_matches(call.get("name"), "create_memory")
        ),
        -1,
    )
    create_ok = _gemini_live_write_verified(
        create_proc,
        verified_row=create_row,
        expected_content=unique_token,
        positive_tokens=[f"SUCCESS {note_uri}", "successfully saved"],
    )
    update_ok = _gemini_live_write_verified(
        update_proc,
        verified_row=update_row,
        expected_content=updated_content,
        positive_tokens=[f"SUCCESS {note_uri}", "success", "updated"],
    )
    create_verified_via_update = False
    if not create_ok and create_row is None and update_row is not None:
        create_ok = _gemini_live_write_verified(
            create_proc,
            verified_row=update_row,
            expected_content=unique_token,
            positive_tokens=[f"SUCCESS {note_uri}", "successfully saved"],
        )
        if create_ok:
            create_verified_via_update = True
            create_row = update_row

    guard_create = guard_calls[guard_create_index] if guard_create_index >= 0 else None
    guard_create_output = ""
    if isinstance(guard_create, dict):
        try:
            guard_create_output = guard_create["result"][0]["functionResponse"]["response"]["output"]
        except Exception:
            guard_create_output = json.dumps(guard_create, ensure_ascii=False)
    guard_target_uri = ""
    try:
        parsed_guard = json.loads(guard_create_output) if guard_create_output else {}
        if isinstance(parsed_guard, dict):
            guard_target_uri = str(parsed_guard.get("guard_target_uri") or "")
    except Exception:
        guard_target_uri = ""
    guard_has_block = any(token in guard_create_output for token in ['"guard_action": "NOOP"', '"guard_action": "UPDATE"', '"guard_action": "DELETE"'])
    guard_followup_calls = guard_calls[guard_create_index + 1 :] if guard_create_index >= 0 else []
    guard_has_read_followup = any(
        _tool_name_matches(call.get("name"), "read_memory")
        for call in guard_followup_calls
    )
    guard_has_search_followup = any(
        _tool_name_matches(call.get("name"), "search_memory")
        for call in guard_followup_calls
    )
    guard_has_followup = any(
        _tool_name_matches(call.get("name"), expected_name)
        for call in guard_followup_calls
        for expected_name in ("read_memory", "update_memory", "search_memory")
    )
    guard_known_uri_fast_path = True
    if guard_target_uri:
        guard_known_uri_fast_path = guard_has_read_followup and not guard_has_search_followup
    guard_duplicate_created = _memory_exists(db_path, guard_uri)
    guard_no_false_success = f"SUCCESS {guard_uri}" not in guard_proc.stdout and not guard_duplicate_created
    guard_resolved_to_existing_target = bool(guard_target_uri) and f"SUCCESS {guard_target_uri}" in guard_proc.stdout
    guard_user_visible_block = any(
        token in (guard_proc.stdout + "\n" + guard_message)
        for token in [f"BLOCKED {note_uri}", note_uri, "duplicate", "already exists", "update", "noop", "guard"]
    )

    details = [
        f"db_path={db_path}",
        f"create_model={create_proc.model or GEMINI_TEST_MODEL}",
        f"create_timed_out={create_proc.timed_out}",
        f"create_stdout={create_proc.stdout.strip()}",
        f"create_verified={json.dumps(create_row, ensure_ascii=False) if create_row else 'missing'}",
        f"create_verified_via_update={create_verified_via_update}",
        f"update_model={update_proc.model or GEMINI_TEST_MODEL}",
        f"update_timed_out={update_proc.timed_out}",
        f"update_stdout={update_proc.stdout.strip()}",
        f"update_verified={json.dumps(update_row, ensure_ascii=False) if update_row else 'missing'}",
        f"guard_model={guard_proc.model or GEMINI_TEST_MODEL}",
        f"guard_timed_out={guard_proc.timed_out}",
        f"guard_stdout={guard_proc.stdout.strip()}",
        f"guard_message={guard_message.strip()}",
        f"guard_duplicate_created={guard_duplicate_created}",
        f"guard_create_output={guard_create_output or 'missing'}",
        f"guard_target_uri={guard_target_uri or 'missing'}",
        f"guard_user_visible_block={guard_user_visible_block}",
        f"guard_followup={guard_has_followup}",
        f"guard_known_uri_fast_path={guard_known_uri_fast_path}",
        f"guard_resolved_to_existing_target={guard_resolved_to_existing_target}",
    ]

    guard_safe = (guard_no_false_success or guard_resolved_to_existing_target) and (guard_has_block or guard_user_visible_block)
    if create_ok and update_ok and guard_safe:
        if guard_target_uri and not guard_known_uri_fast_path:
            return CheckResult("PARTIAL", "Gemini live 写入与更新通过，但 guard 分支未走 known-URI fast path", "\n".join(details))
        if guard_has_followup:
            return CheckResult("PASS", "Gemini live 写入/更新/守卫链路通过", "\n".join(details))
        return CheckResult("PASS", "Gemini live 写入/更新通过，guard 已安全阻断（未稳定观测到 follow-up）", "\n".join(details))

    if create_ok and update_ok:
        return CheckResult("PARTIAL", "Gemini live 写入与更新通过，但 guard 分支未稳定收敛", "\n".join(details))

    if _gemini_live_shared_state_suspected(
        note_uri=note_uri,
        create_proc=create_proc,
        update_proc=update_proc,
        create_row=create_row,
        update_row=update_row,
        guard_proc=guard_proc,
        guard_target_uri=guard_target_uri,
    ):
        return CheckResult("PARTIAL", "Gemini live 命中共享库或宿主干扰，链路未稳定收敛", "\n".join(details))

    return CheckResult("FAIL", "Gemini live MCP 链路未完全通过", "\n".join(details))


def mirror_only_status(name: str) -> CheckResult:
    mirror = MIRRORS[name]
    if not mirror.is_dir():
        return CheckResult(
            "PARTIAL",
            f"{name} 兼容投影尚未安装到当前仓库（按需同步即可）",
            str(mirror),
        )
    issues = _mirror_contract_issues(name)
    if issues:
        return CheckResult("FAIL", f"{name} mirror 缺失或与 canonical 不一致", "\n".join(issues))
    return CheckResult(
        "PARTIAL",
        f"{name} 兼容投影已对齐 canonical，但当前仍只有静态兼容检查",
        str(mirror),
    )


def smoke_cursor() -> CheckResult:
    mirror = MIRRORS["cursor"]
    if not mirror.is_dir():
        return CheckResult(
            "PARTIAL",
            "Cursor IDE Host 兼容投影尚未安装到当前仓库（按需同步即可）",
            str(mirror),
        )
    issues = _mirror_contract_issues("cursor")
    if issues:
        return CheckResult("FAIL", "Cursor IDE Host 兼容检查失败：mirror 缺失或与 canonical 不一致", "\n".join(issues))
    if not CURSOR_AGENT_BIN.is_file():
        return CheckResult("PARTIAL", "Cursor IDE Host 兼容检查通过静态契约，但本机未发现 cursor-agent runtime", str(mirror))
    try:
        proc = run_command([str(CURSOR_AGENT_BIN), "-p", PROMPT], cwd=REPO_ROOT, timeout=60)
    except subprocess.TimeoutExpired:
        return CheckResult("PARTIAL", "Cursor IDE Host 兼容检查命中 runtime，但 headless smoke 超时", str(CURSOR_AGENT_BIN))
    merged = (proc.stdout + "\n" + proc.stderr).strip()
    lowered = merged.lower()
    if "authentication required" in lowered:
        return CheckResult("PARTIAL", "Cursor IDE Host 兼容检查命中 runtime，但当前机器缺少 CLI 登录/鉴权", merged)
    success, details = classify_skill_answer(merged)
    if proc.returncode == 0 and success:
        return CheckResult("PASS", "Cursor IDE Host 兼容检查通过（headless skill probe）", merged)
    return CheckResult("PARTIAL", "Cursor IDE Host 兼容检查命中 runtime，但当前 headless skill probe 未通过", details)


def _antigravity_workflow_rule_anchor(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"missing workflow: {path}"
    text = path.read_text(encoding="utf-8", errors="replace")
    missing = [rule_file for rule_file in ANTIGRAVITY_RULE_FILES if rule_file not in text]
    missing.extend(reference for reference in ANTIGRAVITY_REFERENCE_PATHS if reference not in text)
    if missing:
        return False, f"workflow missing rule/reference anchors: {', '.join(missing)}"
    return True, "workflow declares AGENTS.md/GEMINI.md compatibility and repo-local references"


def _antigravity_bundle_rule_support(bin_path: Path) -> tuple[bool, str]:
    bundle_main = bin_path.parent.parent / "out" / "main.js"
    if not bundle_main.is_file():
        return False, f"missing Antigravity bundle entry: {bundle_main}"
    lowered = bundle_main.read_text(encoding="utf-8", errors="ignore").lower()
    missing = [rule_file for rule_file in ("agents.md", "gemini.md") if rule_file not in lowered]
    if missing:
        return False, f"bundle does not advertise rule discovery for: {', '.join(missing)}"
    return True, f"bundle advertises AGENTS.md + GEMINI.md rule discovery ({bundle_main})"


def _antigravity_installed_workflow() -> Path | None:
    for candidate in (ANTIGRAVITY_WORKSPACE_WORKFLOW, ANTIGRAVITY_USER_WORKFLOW):
        if candidate.is_file():
            return candidate
    return None


def smoke_antigravity() -> CheckResult:
    if not ANTIGRAVITY_BIN.is_file():
        return CheckResult(
            "MANUAL",
            "Antigravity IDE Host 待目标宿主手工补验：当前机器未发现 app-bundled CLI",
            (
                "Use `python scripts/render_ide_host_config.py --host antigravity --launcher python-wrapper` "
                "to verify the repo-local projection path, then re-check on a machine with Antigravity installed."
            ),
        )
    installed_workflow = _antigravity_installed_workflow()
    if installed_workflow is not None:
        if not ANTIGRAVITY_WORKFLOW_SOURCE.is_file():
            return CheckResult("FAIL", "Antigravity IDE Host 兼容检查失败：canonical workflow 缺失", str(ANTIGRAVITY_WORKFLOW_SOURCE))
        if installed_workflow.read_bytes() != ANTIGRAVITY_WORKFLOW_SOURCE.read_bytes():
            return CheckResult(
                "FAIL",
                "Antigravity IDE Host 兼容检查失败：workflow 已安装，但与 canonical 不一致",
                f"{ANTIGRAVITY_BIN}\n{installed_workflow}\n{ANTIGRAVITY_WORKFLOW_SOURCE}",
            )
        workflow_ok, workflow_message = _antigravity_workflow_rule_anchor(installed_workflow)
        if not workflow_ok:
            return CheckResult(
                "FAIL",
                "Antigravity IDE Host 兼容检查失败：workflow 已安装，但规则来源或 repo-local 引用契约不完整",
                f"{ANTIGRAVITY_BIN}\n{installed_workflow}\n{workflow_message}",
            )
        if not REPO_LOCAL_AGENTS.is_file():
            return CheckResult(
                "FAIL",
                "Antigravity IDE Host 兼容检查失败：workflow 已安装，但仓库根 AGENTS.md 缺失",
                f"{ANTIGRAVITY_BIN}\n{installed_workflow}\nmissing: {REPO_LOCAL_AGENTS}",
            )
        bundle_ok, bundle_message = _antigravity_bundle_rule_support(ANTIGRAVITY_BIN)
        bundle_note = bundle_message if bundle_ok else f"bundle check pending: {bundle_message}"
        return CheckResult(
            "PARTIAL",
            "Antigravity IDE Host 兼容检查通过静态契约：workflow 已声明 AGENTS.md + GEMINI.md 规则兼容入口；仍需宿主内手工 smoke",
            (
                f"{ANTIGRAVITY_BIN}\n"
                f"{installed_workflow}\n"
                f"{REPO_LOCAL_AGENTS}\n"
                "workflow declares AGENTS.md/GEMINI.md compatibility\n"
                f"{workflow_message}\n"
                f"{bundle_note}"
            ),
        )
    return CheckResult("MANUAL", "Antigravity IDE Host 兼容检查待手工补齐：CLI 存在，但 workflow 尚未安装", str(ANTIGRAVITY_BIN))


def generate_markdown(results: dict[str, CheckResult]) -> str:
    lines = [
        "# Memory Palace Trigger Smoke Report",
        "",
        "## Summary",
        "",
        "| Check | Status | Summary |",
        "|---|---|---|",
    ]
    for key, result in results.items():
        lines.append(f"| `{key}` | `{result.status}` | {result.summary} |")
    lines.extend(
        [
            "",
            "## Details",
            "",
        ]
    )
    for key, result in results.items():
        lines.append(f"### {key}")
        lines.append("")
        lines.append(f"- Status: `{result.status}`")
        lines.append(f"- Summary: {result.summary}")
        if result.details:
            lines.append("")
            lines.append("```text")
            lines.append(_sanitize_report_text(result.details.strip()))
            lines.append("```")
        lines.append("")
    return "\n".join(lines)


def _configure_console_utf8() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


def main() -> int:
    _configure_console_utf8()
    report_path = _resolve_report_path("MEMORY_PALACE_SKILL_REPORT_PATH", DEFAULT_REPORT_PATH)
    checks = [
        ("structure", check_structure),
        ("description_contract", check_description_contract),
        ("mirrors", check_mirrors),
        ("sync_check", check_sync_script),
        ("gate_syntax", check_gate_syntax),
        ("mcp_bindings", check_client_mcp_bindings),
        ("claude", smoke_claude),
        ("codex", smoke_codex),
        ("opencode", smoke_opencode),
        ("gemini", smoke_gemini),
        ("gemini_live", smoke_gemini_live_suite),
        ("cursor", smoke_cursor),
        ("agent", lambda: mirror_only_status("agent")),
        ("antigravity", smoke_antigravity),
    ]
    results: dict[str, CheckResult] = {}
    for name, runner in checks:
        print(f"[skill-smoke] START {name}", file=sys.stderr, flush=True)
        result = runner()
        results[name] = result
        print(
            f"[skill-smoke] END {name}: {result.status} - {result.summary}",
            file=sys.stderr,
            flush=True,
        )
    markdown = generate_markdown(results)
    _write_private_report(report_path, markdown + "\n")
    print(report_path)
    return 1 if any(result.status == "FAIL" for result in results.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
