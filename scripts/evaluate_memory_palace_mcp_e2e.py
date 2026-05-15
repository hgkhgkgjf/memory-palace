#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "docs" / "skills" / "MCP_LIVE_E2E_REPORT.md"
REPORT_OVERRIDE_ROOT = Path(tempfile.gettempdir()) / "memory-palace-reports"
_REEXEC_GUARD_ENV = "MEMORY_PALACE_MCP_E2E_REEXEC_GUARD"
_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(/Users/[^\s\"']+|/home/[^\s\"']+|/tmp/[^\s\"']+|/var/tmp/[^\s\"']+|/private/var/[^\s\"']+|[A-Za-z]:[\\/][^\s\"']+)"
)
_SESSION_TOKEN_PATTERN = re.compile(r"\b(?:mcp_ctx_[\w-]+|session-[\w-]+)\b")


def _resolve_report_path() -> Path:
    raw_value = os.getenv("MEMORY_PALACE_MCP_E2E_REPORT_PATH", "").strip()
    if not raw_value:
        return DEFAULT_REPORT_PATH
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        safe_parts = [part for part in path.parts if part not in {"", ".", ".."}]
        path = (
            REPORT_OVERRIDE_ROOT.joinpath(*safe_parts)
            if safe_parts
            else REPORT_OVERRIDE_ROOT / DEFAULT_REPORT_PATH.name
        )
    return path


def _backend_python_candidates() -> tuple[Path, ...]:
    windows_python = BACKEND_ROOT / ".venv" / "Scripts" / "python.exe"
    posix_python = BACKEND_ROOT / ".venv" / "bin" / "python"
    if os.name == "nt":
        return (windows_python, posix_python)
    return (posix_python, windows_python)


def _resolve_backend_python() -> Path | None:
    for candidate in _backend_python_candidates():
        if candidate.is_file():
            return candidate
    return None


def _require_backend_python() -> Path:
    backend_python = _resolve_backend_python()
    if backend_python is not None:
        return backend_python
    windows_python = BACKEND_ROOT / ".venv" / "Scripts" / "python.exe"
    posix_python = BACKEND_ROOT / ".venv" / "bin" / "python"
    raise SystemExit(
        "Missing backend virtualenv python: "
        f"{windows_python} or {posix_python}"
    )


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


def _repo_local_stdio_command() -> tuple[str, list[str]]:
    if os.name == "nt" and not _is_windows_posix_shell_host():
        return str(_require_backend_python()), [
            str(BACKEND_ROOT / "mcp_wrapper.py")
        ]
    return "bash", [str(PROJECT_ROOT / "scripts" / "run_memory_palace_mcp_stdio.sh")]


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
    sanitized = re.sub(r"\bDATABASE_URL=[^\s]+", "DATABASE_URL=<redacted>", sanitized)
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
    report_path.write_text(_sanitize_report_text(content), encoding="utf-8")
    try:
        os.chmod(report_path, 0o600)
    except OSError:
        pass
    if REPORT_OVERRIDE_ROOT in report_path.parents:
        try:
            os.chmod(report_path.parent, 0o700)
        except OSError:
            pass


def _maybe_reexec_with_backend_python() -> None:
    backend_python = _resolve_backend_python()
    if backend_python is None:
        return
    if str(os.getenv(_REEXEC_GUARD_ENV) or "").strip():
        return
    if Path(sys.executable).resolve() == backend_python.resolve():
        return
    reexec_env = dict(os.environ)
    reexec_env[_REEXEC_GUARD_ENV] = "1"
    os.execve(
        str(backend_python),
        [str(backend_python), str(Path(__file__).resolve()), *sys.argv[1:]],
        reexec_env,
    )


try:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
except ModuleNotFoundError as exc:
    if exc.name == "mcp":
        _maybe_reexec_with_backend_python()
    raise
EXPECTED_TOOLS = {
    "read_memory",
    "create_memory",
    "update_memory",
    "delete_memory",
    "add_alias",
    "search_memory",
    "compact_context",
    "rebuild_index",
    "index_status",
}


@dataclass
class StepResult:
    name: str
    status: str
    summary: str
    details: str = ""


def _text_of(call_result: Any) -> str:
    return "\n".join(getattr(item, "text", str(item)) for item in call_result.content)


def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return text


def _result(status: str, name: str, summary: str, details: str = "") -> StepResult:
    return StepResult(name=name, status=status, summary=summary, details=details)


async def run_suite(
    repo_local_command: tuple[str, list[str]] | None = None,
) -> tuple[list[StepResult], str]:
    temp_root = Path(tempfile.mkdtemp(prefix="memory-palace-live-mcp-"))
    db_path = temp_root / "memory_palace_live.db"
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
            "VALID_DOMAINS": "core,notes,system",
            "CORE_MEMORY_URIS": "core://pref_concise",
            "SEARCH_DEFAULT_MODE": "keyword",
            "RETRIEVAL_EMBEDDING_BACKEND": "none",
            "RETRIEVAL_RERANKER_ENABLED": "false",
            "WRITE_GUARD_LLM_ENABLED": "false",
            "INTENT_LLM_ENABLED": "false",
            "COMPACT_GIST_LLM_ENABLED": "false",
        }
    )

    if repo_local_command is None:
        command, args = _repo_local_stdio_command()
    else:
        command, args = repo_local_command
    server = StdioServerParameters(
        command=command,
        args=args,
        cwd=str(PROJECT_ROOT),
        env=env,
    )

    results: list[StepResult] = []
    stderr_path = temp_root / "mcp_server.stderr.log"
    with stderr_path.open("w+", encoding="utf-8") as errlog:
        async with stdio_client(server, errlog=errlog) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                tools = await session.list_tools()
                discovered = {tool.name for tool in tools.tools}
                if discovered == EXPECTED_TOOLS:
                    results.append(_result("PASS", "tool_inventory", "stdio MCP 暴露 9 个工具"))
                else:
                    results.append(
                        _result(
                            "FAIL",
                            "tool_inventory",
                            "工具集合不匹配",
                            f"expected={sorted(EXPECTED_TOOLS)} actual={sorted(discovered)}",
                        )
                    )

                boot_initial = _text_of(await session.call_tool("read_memory", {"uri": "system://boot"}))
                if "Core Memories" in boot_initial and "Loaded: 0/1" in boot_initial:
                    results.append(_result("PASS", "boot_empty", "首次 boot 在空库中按设计返回空核心记忆"))
                else:
                    results.append(_result("FAIL", "boot_empty", "首次 boot 返回异常", boot_initial))

                create_raw = _maybe_json(
                    _text_of(
                        await session.call_tool(
                            "create_memory",
                            {
                                "parent_uri": "core://",
                                "content": "user likes concise answers",
                                "priority": 1,
                                "title": "pref_concise",
                                "disclosure": "when answering",
                            },
                        )
                    )
                )
                if isinstance(create_raw, dict) and create_raw.get("created") and create_raw.get("guard_action") == "ADD":
                    results.append(_result("PASS", "create_memory", "create_memory 成功并返回 guard_action=ADD"))
                else:
                    results.append(_result("FAIL", "create_memory", "create_memory 未按设计成功", json.dumps(create_raw, ensure_ascii=False)))

                duplicate_raw = _maybe_json(
                    _text_of(
                        await session.call_tool(
                            "create_memory",
                            {
                                "parent_uri": "core://",
                                "content": "user likes concise answers",
                                "priority": 1,
                                "title": "pref_concise_dup",
                                "disclosure": "when answering",
                            },
                        )
                    )
                )
                if (
                    isinstance(duplicate_raw, dict)
                    and duplicate_raw.get("created") is False
                    and duplicate_raw.get("guard_action") in {"NOOP", "UPDATE"}
                    and duplicate_raw.get("guard_target_uri") == "core://pref_concise"
                ):
                    results.append(
                        _result(
                            "PASS",
                            "write_guard_block",
                            f"重复写入被 {duplicate_raw.get('guard_action')} 正确拦截",
                        )
                    )
                else:
                    results.append(_result("FAIL", "write_guard_block", "重复写入未被按设计拦截", json.dumps(duplicate_raw, ensure_ascii=False)))

                search_raw = _maybe_json(_text_of(await session.call_tool("search_memory", {"query": "concise answers"})))
                if (
                    isinstance(search_raw, dict)
                    and search_raw.get("ok") is True
                    and search_raw.get("degraded") is False
                    and any(item.get("uri") == "core://pref_concise" for item in search_raw.get("results", []))
                ):
                    results.append(_result("PASS", "search_memory", "search_memory 返回预期记忆且未降级"))
                else:
                    results.append(_result("FAIL", "search_memory", "search_memory 结果异常", json.dumps(search_raw, ensure_ascii=False)))

                read_core = _text_of(await session.call_tool("read_memory", {"uri": "core://pref_concise"}))
                if "user likes concise answers" in read_core:
                    results.append(_result("PASS", "read_memory", "read_memory 能读取刚创建的记忆"))
                else:
                    results.append(_result("FAIL", "read_memory", "read_memory 未返回预期内容", read_core))

                update_raw = _maybe_json(
                    _text_of(
                        await session.call_tool(
                            "update_memory",
                            {"uri": "core://pref_concise", "old_string": "concise", "new_string": "short"},
                        )
                    )
                )
                if isinstance(update_raw, dict) and update_raw.get("updated") and update_raw.get("guard_action") == "ADD":
                    results.append(_result("PASS", "update_memory", "update_memory patch 模式成功"))
                else:
                    results.append(_result("FAIL", "update_memory", "update_memory 结果异常", json.dumps(update_raw, ensure_ascii=False)))

                alias_raw = _text_of(await session.call_tool("add_alias", {"new_uri": "notes://pref_alias", "target_uri": "core://pref_concise"}))
                alias_read = _text_of(await session.call_tool("read_memory", {"uri": "notes://pref_alias"}))
                if "Success: Alias" in alias_raw and "MEMORY: notes://pref_alias" in alias_read:
                    results.append(_result("PASS", "add_alias", "add_alias 成功，alias 可读"))
                else:
                    results.append(_result("FAIL", "add_alias", "add_alias 行为异常", alias_raw + "\n\n" + alias_read))

                delete_alias = _maybe_json(
                    _text_of(await session.call_tool("delete_memory", {"uri": "notes://pref_alias"}))
                )
                read_after_delete = _text_of(await session.call_tool("read_memory", {"uri": "core://pref_concise"}))
                if (
                    isinstance(delete_alias, dict)
                    and delete_alias.get("ok") is True
                    and delete_alias.get("deleted") is True
                    and delete_alias.get("uri") == "notes://pref_alias"
                    and "Success: Memory 'notes://pref_alias' deleted." in str(delete_alias.get("message", ""))
                    and "user likes short answers" in read_after_delete
                ):
                    results.append(_result("PASS", "delete_alias", "删除 alias 后原始 core 路径仍保留"))
                else:
                    results.append(
                        _result(
                            "FAIL",
                            "delete_alias",
                            "delete_memory/alias 行为不符合设计",
                            json.dumps(delete_alias, ensure_ascii=False) + "\n\n" + read_after_delete,
                        )
                    )

                compact_raw = _maybe_json(_text_of(await session.call_tool("compact_context", {"reason": "force test", "force": True, "max_lines": 6})))
                if isinstance(compact_raw, dict) and compact_raw.get("ok") is True:
                    results.append(_result("PASS", "compact_context", "compact_context 可正常返回"))
                else:
                    results.append(_result("FAIL", "compact_context", "compact_context 返回异常", json.dumps(compact_raw, ensure_ascii=False)))

                index_raw = _maybe_json(_text_of(await session.call_tool("index_status", {})))
                if isinstance(index_raw, dict) and index_raw.get("ok") is True and "runtime" in index_raw:
                    results.append(_result("PASS", "index_status", "index_status 返回 runtime 状态"))
                else:
                    results.append(_result("FAIL", "index_status", "index_status 返回异常", json.dumps(index_raw, ensure_ascii=False)))

                rebuild_raw = _maybe_json(_text_of(await session.call_tool("rebuild_index", {"wait": True, "reason": "live_e2e"})))
                job = rebuild_raw.get("wait_result", {}).get("job", {}) if isinstance(rebuild_raw, dict) else {}
                if isinstance(rebuild_raw, dict) and rebuild_raw.get("ok") is True and job.get("status") == "succeeded":
                    results.append(_result("PASS", "rebuild_index", "rebuild_index(wait=true) 任务成功"))
                else:
                    results.append(_result("FAIL", "rebuild_index", "rebuild_index 返回异常", json.dumps(rebuild_raw, ensure_ascii=False)))

                boot_after = _text_of(await session.call_tool("read_memory", {"uri": "system://boot"}))
                if "Loaded: 1/1" in boot_after and "user likes short answers" in boot_after:
                    results.append(_result("PASS", "boot_after_write", "boot 在写入后能加载 core memory"))
                else:
                    results.append(_result("FAIL", "boot_after_write", "boot 在写入后未按设计加载 core memory", boot_after))

        errlog.seek(0)
        stderr_output = errlog.read()
    if "bound to a different event loop" in stderr_output or "Task exception was never retrieved" in stderr_output:
        results.append(_result("FAIL", "runtime_worker", "runtime index worker 仍存在跨 event loop 异常", stderr_output))
    else:
        results.append(_result("PASS", "runtime_worker", "未发现跨 event loop worker 异常"))

    return results, stderr_output


def build_markdown(results: list[StepResult], stderr_output: str) -> str:
    lines = [
        "# Memory Palace Live MCP E2E Report",
        "",
        "## Summary",
        "",
        "| Check | Status | Summary |",
        "|---|---|---|",
    ]
    for item in results:
        lines.append(f"| `{item.name}` | `{item.status}` | {item.summary} |")

    lines.extend(["", "## Details", ""])
    for item in results:
        lines.append(f"### {item.name}")
        lines.append("")
        lines.append(f"- Status: `{item.status}`")
        lines.append(f"- Summary: {item.summary}")
        if item.details:
            lines.extend(["", "```text", _sanitize_report_text(item.details.strip()), "```"])
        lines.append("")

    if stderr_output.strip():
        lines.extend(
            [
                "## MCP Server stderr",
                "",
                "```text",
                _sanitize_report_text(stderr_output.strip()),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def run_suite_sync(
    repo_local_command: tuple[str, list[str]] | None = None,
) -> tuple[list[StepResult], str]:
    return asyncio.run(run_suite(repo_local_command=repo_local_command))


def main() -> int:
    results, stderr_output = run_suite_sync()
    report_path = _resolve_report_path()
    _write_private_report(report_path, build_markdown(results, stderr_output) + "\n")
    failed = [item for item in results if item.status == "FAIL"]
    print(report_path)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
