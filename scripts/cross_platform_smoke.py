#!/usr/bin/env python3
"""Cross-platform compatibility smoke test for the Memory Palace backend.

This audit scans the backend (and any sibling Python sources) for portability
issues so that the project can run on Windows, macOS, and Linux without
platform-specific surprises.

It reports four categories of findings:

- ``os_path_usage``   -- ``os.path.*`` calls that should migrate to ``pathlib``.
- ``hardcoded_separators`` -- string literals containing ``/`` or ``\\`` that
  look like filesystem paths (URLs and URI schemes such as ``core://`` are
  intentionally excluded).
- ``platform_specific`` -- ``platform.system()`` / ``sys.platform`` usages that
  should be reviewed for conditional behavior.
- ``temp_dir_risks`` -- ``tempfile.mkdtemp``/``mkstemp``/``NamedTemporaryFile``
  usages that may leak temp directories when not paired with a context manager
  or explicit cleanup.

Additionally, it scans ``scripts/*.sh`` and checks whether each has a paired
``scripts/*.ps1`` so that contributors on Windows are not stranded.

Exit codes:

- ``0`` -- no critical findings (only warnings).
- ``1`` -- one or more critical findings (e.g. hardcoded absolute paths).

The script is designed to be deterministic and to work on Windows, macOS, and
Linux without external dependencies (standard library only).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Module attributes from ``os.path`` that should be flagged for pathlib
# migration. Plain ``os.path.join`` is the most common offender, but we also
# look for other helpers that have pathlib equivalents.
_OS_PATH_ATTRS = {
    "join",
    "exists",
    "isfile",
    "isdir",
    "isabs",
    "abspath",
    "basename",
    "dirname",
    "expanduser",
    "expandvars",
    "getsize",
    "getmtime",
    "getatime",
    "getctime",
    "normpath",
    "realpath",
    "relpath",
    "split",
    "splitext",
    "splitdrive",
    "samefile",
    "commonpath",
    "commonprefix",
}

# Tempfile helpers that need explicit cleanup or context-manager usage to
# avoid leaking directories/files on disk.
_TEMP_HELPERS = {
    "mkdtemp",
    "mkstemp",
    "NamedTemporaryFile",
    "TemporaryFile",
    "SpooledTemporaryFile",
}

# ``platform.system()`` / ``sys.platform`` access patterns to flag.
_PLATFORM_ATTRS = {("platform", "system"), ("sys", "platform")}

# Paths to skip when walking the backend tree. The legacy pytest-leaked dirs
# under ``backend/\private\var\folders\...`` should not be scanned.
_DEFAULT_SKIP_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "node_modules",
    ".tmp",
    ".mypy_cache",
    ".ruff_cache",
}

# Substrings that strongly suggest a literal is a URL / URI / regex / glob
# rather than a real filesystem path. We use these to suppress false positives
# in ``hardcoded_separators``.
_URI_HINTS = (
    "http://",
    "https://",
    "ws://",
    "wss://",
    "ftp://",
    "ftps://",
    "git://",
    "ssh://",
    "file://",
    "mailto:",
    "data:",
    "://",  # generic URI scheme catch-all (e.g. core://, memory://)
    "{{",   # template placeholder
    "}}",
    "\\\\",
    "\\d",
    "\\s",
    "\\w",
    "\\n",
    "\\t",
    "\\r",
    "\\.",
    "\\(",
    "\\)",
    "\\b",
)

# Patterns that look like real filesystem paths (Linux/macOS or Windows) and
# should be flagged as critical when found inside string literals.
#
# Filesystem absolute paths typically start with a well-known root prefix
# (``/Users/``, ``/home/``, ``/var/``, ``/tmp/``, ``/opt/``, ``/etc/``,
# ``/usr/``, ``/private/``, ``/mnt/``, ``/data/``, ``/root/``) or a Windows
# drive letter. Anything else that starts with ``/`` (e.g. ``/maintenance``,
# ``/api/v1``) is almost certainly a URL path / route definition and should
# not be flagged.
_UNIX_FS_ROOTS = (
    "/Users/",
    "/home/",
    "/var/",
    "/tmp/",
    "/opt/",
    "/etc/",
    "/usr/",
    "/private/",
    "/mnt/",
    "/data/",
    "/root/",
    "/sys/",
    "/proc/",
    "/dev/",
    "/lib/",
    "/bin/",
    "/sbin/",
    "/srv/",
)

_WIN_ABS_RE = re.compile(r"^[A-Za-z]:[\\/][^\s?<>|*\"]+$")


@dataclass
class Finding:
    """Single audit finding."""

    category: str
    severity: str  # "critical" or "warning"
    file: str
    line: int
    column: int
    detail: str
    snippet: str = ""

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "detail": self.detail,
            "snippet": self.snippet,
        }


@dataclass
class Report:
    os_path_usage: list[Finding] = field(default_factory=list)
    hardcoded_separators: list[Finding] = field(default_factory=list)
    platform_specific: list[Finding] = field(default_factory=list)
    temp_dir_risks: list[Finding] = field(default_factory=list)
    shell_script_gaps: list[Finding] = field(default_factory=list)

    @property
    def all_findings(self) -> list[Finding]:
        return [
            *self.os_path_usage,
            *self.hardcoded_separators,
            *self.platform_specific,
            *self.temp_dir_risks,
            *self.shell_script_gaps,
        ]

    def to_dict(self) -> dict:
        return {
            "os_path_usage": [f.to_dict() for f in self.os_path_usage],
            "hardcoded_separators": [f.to_dict() for f in self.hardcoded_separators],
            "platform_specific": [f.to_dict() for f in self.platform_specific],
            "temp_dir_risks": [f.to_dict() for f in self.temp_dir_risks],
            "shell_script_gaps": [f.to_dict() for f in self.shell_script_gaps],
        }


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def _is_skipped(path: Path, skip_parts: set[str]) -> bool:
    parts = set(path.parts)
    if parts & skip_parts:
        return True
    # The legacy leaked pytest temp dirs live under names containing the
    # literal characters ``\private\var\folders`` because they were created on
    # macOS but committed with Windows-style separators. Drop them defensively
    # so the audit cannot trip on its own backstop directory.
    for part in path.parts:
        if "\\private\\var\\folders" in part or part.startswith("\\private"):
            return True
    return False


def discover_python_files(roots: Iterable[Path], skip_parts: set[str]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file() and root.suffix == ".py":
            if not _is_skipped(root, skip_parts):
                found.append(root)
            continue
        for path in root.rglob("*.py"):
            if _is_skipped(path, skip_parts):
                continue
            found.append(path)
    return sorted(set(found))


def discover_shell_scripts(scripts_dir: Path) -> list[Path]:
    if not scripts_dir.exists():
        return []
    return sorted(scripts_dir.glob("*.sh"))


# ---------------------------------------------------------------------------
# AST walkers
# ---------------------------------------------------------------------------


class _SourceVisitor(ast.NodeVisitor):
    """Collect findings from a single parsed Python module."""

    def __init__(self, source: str, rel_path: str, is_test_file: bool = False) -> None:
        self.source = source
        self.lines = source.splitlines()
        self.rel_path = rel_path
        self.is_test_file = is_test_file
        self.os_path: list[Finding] = []
        self.platform_specific: list[Finding] = []
        self.temp_risks: list[Finding] = []
        self.hardcoded: list[Finding] = []
        # Track tempfile.mkdtemp() / etc. that are *not* wrapped in a
        # ``with`` statement or assigned to a variable that is later removed.
        # We keep this simple: any bare call result that is assigned but never
        # used inside a ``with`` is flagged as a warning.
        self._with_contexts: list[set[int]] = [set()]

    # -- helpers -----------------------------------------------------------

    def _snippet(self, node: ast.AST) -> str:
        line = getattr(node, "lineno", 0)
        if 1 <= line <= len(self.lines):
            return self.lines[line - 1].strip()
        return ""

    def _record_os_path(self, node: ast.Attribute) -> None:
        attr = node.attr
        self.os_path.append(
            Finding(
                category="os_path_usage",
                severity="warning",
                file=self.rel_path,
                line=node.lineno,
                column=node.col_offset,
                detail=f"os.path.{attr} should migrate to pathlib.Path",
                snippet=self._snippet(node),
            )
        )

    def _record_platform(self, node: ast.AST, attr: str) -> None:
        self.platform_specific.append(
            Finding(
                category="platform_specific",
                severity="warning",
                file=self.rel_path,
                line=node.lineno,
                column=node.col_offset,
                detail=f"Platform-specific access: {attr}",
                snippet=self._snippet(node),
            )
        )

    def _record_temp(self, node: ast.AST, name: str, severity: str, reason: str) -> None:
        self.temp_risks.append(
            Finding(
                category="temp_dir_risks",
                severity=severity,
                file=self.rel_path,
                line=node.lineno,
                column=node.col_offset,
                detail=f"tempfile.{name}: {reason}",
                snippet=self._snippet(node),
            )
        )

    def _record_hardcoded(self, node: ast.Constant, literal: str, severity: str, reason: str) -> None:
        self.hardcoded.append(
            Finding(
                category="hardcoded_separators",
                severity=severity,
                file=self.rel_path,
                line=node.lineno,
                column=node.col_offset,
                detail=reason,
                snippet=self._snippet(node) or repr(literal),
            )
        )

    # -- visit -------------------------------------------------------------

    def visit_With(self, node: ast.With) -> None:  # noqa: N802 (AST API)
        ids = set()
        for item in node.items:
            ctx = item.context_expr
            if isinstance(ctx, ast.Call):
                # ``with tempfile.NamedTemporaryFile() as fh:`` should mark the
                # call line as safe; we record the lineno of the call.
                ids.add(getattr(ctx, "lineno", -1))
        self._with_contexts.append(ids)
        try:
            self.generic_visit(node)
        finally:
            self._with_contexts.pop()

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        # os.path.<attr>
        value = node.value
        if (
            isinstance(value, ast.Attribute)
            and value.attr == "path"
            and isinstance(value.value, ast.Name)
            and value.value.id == "os"
            and node.attr in _OS_PATH_ATTRS
        ):
            self._record_os_path(node)
        # sys.platform / platform.system
        if isinstance(value, ast.Name):
            pair = (value.id, node.attr)
            if pair in _PLATFORM_ATTRS:
                self._record_platform(node, f"{value.id}.{node.attr}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = node.func
        # tempfile.<helper>(...) usage detection.
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id == "tempfile" and func.attr in _TEMP_HELPERS:
                # Inside a ``with`` whose call lineno matches ours -> safe.
                current_ctx = self._with_contexts[-1] if self._with_contexts else set()
                if node.lineno in current_ctx:
                    pass  # context-manager wrapped, safe
                else:
                    if func.attr == "mkdtemp":
                        # mkdtemp must be cleaned up explicitly because it is
                        # not a context manager. This is the well-known
                        # "pytest leaked temp dir" foot-gun.
                        self._record_temp(
                            node,
                            func.attr,
                            severity="warning",
                            reason=(
                                "mkdtemp result must be cleaned with "
                                "shutil.rmtree (or use TemporaryDirectory)"
                            ),
                        )
                    elif func.attr in {"NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile"}:
                        self._record_temp(
                            node,
                            func.attr,
                            severity="warning",
                            reason="Should be used as a context manager",
                        )
                    elif func.attr == "mkstemp":
                        self._record_temp(
                            node,
                            func.attr,
                            severity="warning",
                            reason="mkstemp fd must be closed and path removed",
                        )
        # platform.system() pattern
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and (func.value.id, func.attr) in _PLATFORM_ATTRS
        ):
            self._record_platform(node, f"{func.value.id}.{func.attr}()")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
        value = node.value
        if isinstance(value, str):
            self._inspect_string_literal(node, value)
        self.generic_visit(node)

    # -- string-literal inspection ----------------------------------------

    def _inspect_string_literal(self, node: ast.Constant, value: str) -> None:
        stripped = value.strip()
        if not stripped:
            return
        # Skip docstrings (parent assignment is handled at module-level)
        if len(stripped) > 200:
            return
        lower = stripped.lower()
        if any(hint in lower for hint in _URI_HINTS):
            return
        # Absolute filesystem paths -> critical (or warning inside test
        # fixtures, where ``/tmp/demo.db`` / ``/usr/bin/codex`` style strings
        # are deliberately constructed to exercise OS behavior).
        if stripped.startswith(_UNIX_FS_ROOTS) or _WIN_ABS_RE.match(stripped):
            self._record_hardcoded(
                node,
                stripped,
                severity="warning" if self.is_test_file else "critical",
                reason=(
                    "Hardcoded absolute path"
                    + (" (in test fixture)" if self.is_test_file else "")
                ),
            )
            return
        # Detect path-like strings: at least one separator with non-empty
        # components on both sides. Heuristics:
        #   - contains a backslash that looks like a path separator
        #     (e.g. ``backend\\models``)
        #   - or contains a forward slash and *all* components look like
        #     filesystem names (no spaces, no '?', no ':' beyond Win drive).
        if "\\" in stripped and "\\\\" not in stripped:
            # exclude common escape sequences and regex metacharacters
            if re.search(r"\b[A-Za-z0-9_.-]+\\[A-Za-z0-9_.-]+", stripped):
                self._record_hardcoded(
                    node,
                    stripped,
                    severity="warning",
                    reason="Hardcoded backslash path separator",
                )
                return
        if "/" in stripped and ":" not in stripped and "?" not in stripped:
            # Limit to multi-segment short literals that look like relative
            # paths and live inside Python code (not docstrings).
            if (
                len(stripped) <= 120
                and not stripped.startswith(("/", "./", "../"))
                and re.fullmatch(r"[A-Za-z0-9_.\-/]+", stripped)
                and stripped.count("/") >= 1
            ):
                # Skip obvious non-paths: words like ``a/b`` are rare but real;
                # require at least one segment longer than two chars OR a
                # known file extension.
                if re.search(r"\.[A-Za-z0-9]{1,5}\b", stripped) or any(
                    len(seg) >= 3 for seg in stripped.split("/")
                ):
                    self._record_hardcoded(
                        node,
                        stripped,
                        severity="warning",
                        reason="Relative path using forward slash; prefer pathlib",
                    )


# ---------------------------------------------------------------------------
# Python file scanning
# ---------------------------------------------------------------------------


def _is_test_path(rel: str, path: Path) -> bool:
    name = path.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    parts = set(rel.split("/"))
    return bool({"tests", "test", "__tests__"} & parts)


def scan_python_file(path: Path, repo_root: Path) -> tuple[list[Finding], list[Finding], list[Finding], list[Finding]]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [], [], [], []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return [], [], [], []
    try:
        rel = str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        rel = str(path)
    # Normalise to POSIX-style separators for stable JSON output.
    rel = rel.replace("\\", "/")
    is_test = _is_test_path(rel, path)
    visitor = _SourceVisitor(source, rel, is_test_file=is_test)
    visitor.visit(tree)
    return (
        visitor.os_path,
        visitor.hardcoded,
        visitor.platform_specific,
        visitor.temp_risks,
    )


# ---------------------------------------------------------------------------
# Shell-script pairing check
# ---------------------------------------------------------------------------


# Bash idioms that have no native PowerShell equivalent and therefore mean
# the script should ship a paired ``.ps1`` variant for Windows users.
_BASH_ONLY_RE = re.compile(
    r"""
    (\$\([^)]*\))               # $(command substitution)
    |(\[\[[^]]*\]\])            # [[ test ]]
    |(\$\{[^}]*\})              # ${param expansion}
    |(<<-?\s*['"]?[A-Za-z_]+)   # heredoc
    |\bsource\s                  # source builtin
    |\beval\s                    # eval
    """,
    re.VERBOSE,
)


def check_shell_scripts(scripts_dir: Path, repo_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for sh_path in discover_shell_scripts(scripts_dir):
        ps1 = sh_path.with_suffix(".ps1")
        try:
            rel = str(sh_path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
        except ValueError:
            rel = str(sh_path)
        if ps1.exists():
            continue
        try:
            content = sh_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        uses_bash_only = bool(_BASH_ONLY_RE.search(content))
        findings.append(
            Finding(
                category="shell_script_gaps",
                severity="warning" if uses_bash_only else "warning",
                file=rel,
                line=1,
                column=0,
                detail=(
                    "No paired .ps1 script found for Windows users"
                    + (" (uses bash-only syntax)" if uses_bash_only else "")
                ),
                snippet=ps1.name,
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_audit(
    repo_root: Path,
    scan_roots: list[Path],
    scripts_dir: Path,
    skip_parts: set[str],
) -> Report:
    report = Report()
    for path in discover_python_files(scan_roots, skip_parts):
        os_path, hardcoded, platform_specific, temp_risks = scan_python_file(path, repo_root)
        report.os_path_usage.extend(os_path)
        report.hardcoded_separators.extend(hardcoded)
        report.platform_specific.extend(platform_specific)
        report.temp_dir_risks.extend(temp_risks)
    report.shell_script_gaps.extend(check_shell_scripts(scripts_dir, repo_root))
    return report


def summarise(report: Report) -> dict:
    findings = report.all_findings
    critical = [f for f in findings if f.severity == "critical"]
    warnings = [f for f in findings if f.severity == "warning"]
    return {
        "totals": {
            "critical": len(critical),
            "warning": len(warnings),
            "os_path_usage": len(report.os_path_usage),
            "hardcoded_separators": len(report.hardcoded_separators),
            "platform_specific": len(report.platform_specific),
            "temp_dir_risks": len(report.temp_dir_risks),
            "shell_script_gaps": len(report.shell_script_gaps),
        },
        "findings": report.to_dict(),
    }


def emit_text_report(summary: dict, stream) -> None:
    totals = summary["totals"]
    findings = summary["findings"]
    stream.write("Memory Palace cross-platform smoke test\n")
    stream.write("=" * 50 + "\n")
    stream.write(
        f"critical={totals['critical']} warning={totals['warning']}\n"
    )
    stream.write(
        "  os_path_usage:        {n}\n".format(n=totals["os_path_usage"])
    )
    stream.write(
        "  hardcoded_separators: {n}\n".format(n=totals["hardcoded_separators"])
    )
    stream.write(
        "  platform_specific:    {n}\n".format(n=totals["platform_specific"])
    )
    stream.write(
        "  temp_dir_risks:       {n}\n".format(n=totals["temp_dir_risks"])
    )
    stream.write(
        "  shell_script_gaps:    {n}\n".format(n=totals["shell_script_gaps"])
    )
    stream.write("\n")
    for category, entries in findings.items():
        if not entries:
            continue
        stream.write(f"[{category}] ({len(entries)})\n")
        for entry in entries[:30]:
            stream.write(
                "  {severity:<8} {file}:{line}:{column}  {detail}\n".format(**entry)
            )
        if len(entries) > 30:
            stream.write(f"  ... ({len(entries) - 30} more)\n")
        stream.write("\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repository root (defaults to the parent of this script's directory).",
    )
    parser.add_argument(
        "--scan",
        type=Path,
        action="append",
        default=None,
        help=(
            "Additional path to scan. Defaults to <repo-root>/backend. May be "
            "passed multiple times."
        ),
    )
    parser.add_argument(
        "--scripts-dir",
        type=Path,
        default=None,
        help="Scripts directory to check for sh/ps1 pairing.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the human-readable text report.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the report to this file in addition to stdout.",
    )
    parser.add_argument(
        "--allow-critical",
        action="store_true",
        help="Always exit 0 even when critical findings are present (for triage).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    scan_roots: list[Path] = []
    if args.scan:
        scan_roots.extend(p.resolve() for p in args.scan)
    else:
        scan_roots.append((repo_root / "backend").resolve())
    scripts_dir = (args.scripts_dir or (repo_root / "scripts")).resolve()
    skip_parts = set(_DEFAULT_SKIP_PARTS)

    report = run_audit(repo_root, scan_roots, scripts_dir, skip_parts)
    summary = summarise(report)

    if args.json:
        payload = json.dumps(summary, indent=2, sort_keys=True)
        sys.stdout.write(payload + "\n")
    else:
        emit_text_report(summary, sys.stdout)

    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            if args.json or args.output.suffix.lower() == ".json":
                args.output.write_text(
                    json.dumps(summary, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            else:
                from io import StringIO

                buffer = StringIO()
                emit_text_report(summary, buffer)
                args.output.write_text(buffer.getvalue(), encoding="utf-8")
        except OSError as exc:  # pragma: no cover - defensive
            sys.stderr.write(f"warning: could not write --output: {exc}\n")

    critical = summary["totals"]["critical"]
    if critical and not args.allow_critical:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
