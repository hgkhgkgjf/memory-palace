#!/usr/bin/env python3
"""Audit Memory Palace frontend translation key coverage.

This script compares three sources of truth:

1. ``frontend/src/locales/en.js``      -- canonical key tree (English).
2. ``frontend/src/locales/zh-CN.js``   -- Chinese key tree.
3. ``t('...')`` / ``t("...")`` / ``i18n.t('...')`` call sites under
   ``frontend/src/**/*.{jsx,js,mjs,ts,tsx}``.

For each comparison it reports:

- Keys used in code but missing from ``en.js``.
- Keys used in code but missing from ``zh-CN.js``.
- Keys defined in either locale but never used in code (stale keys).
- Keys present in ``en.js`` but not in ``zh-CN.js`` (and vice versa).

The locale files are JavaScript module exports (``const en = {...}; export
default en``) rather than JSON, so we parse them with a small, dedicated
parser that understands the subset of JS used in those files (string keys,
identifier keys, nested objects, strings with single/double/backtick quotes,
trailing commas, and ``//`` line comments).

Exit codes:

- ``0`` -- all keys present in both locales and at least one locale exists.
- ``1`` -- one or more critical mismatches (missing keys or missing locales).

Outputs both a human-readable report on stdout and, with ``--json``, a JSON
summary suitable for CI consumption.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Locale file parser
# ---------------------------------------------------------------------------


class LocaleParseError(RuntimeError):
    """Raised when a locale file cannot be parsed."""


def _strip_comments(source: str) -> str:
    """Drop ``//`` line comments and ``/* ... */`` block comments.

    The parser only needs to look at object literal structure, so a defensive
    pre-pass is good enough -- we are not building a full JS parser.
    """
    out: list[str] = []
    i = 0
    n = len(source)
    in_str: str | None = None
    while i < n:
        ch = source[i]
        # Inside a string literal: copy verbatim, handle escapes.
        if in_str is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(source[i + 1])
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        # String start
        if ch in ("'", '"', "`"):
            in_str = ch
            out.append(ch)
            i += 1
            continue
        # Line comment
        if ch == "/" and i + 1 < n and source[i + 1] == "/":
            while i < n and source[i] != "\n":
                i += 1
            continue
        # Block comment
        if ch == "/" and i + 1 < n and source[i + 1] == "*":
            i += 2
            while i + 1 < n and not (source[i] == "*" and source[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


class _JsObjectParser:
    """Minimal recursive-descent parser for the locale JS objects.

    Supports:
    - Object literals ``{ key: value, ... }`` with trailing commas.
    - Keys as identifiers, single-quoted strings, double-quoted strings, or
      template strings without substitutions.
    - Values that are string literals (any quote style), nested objects, or
      arrays of strings/objects (kept for completeness even though the
      project does not currently use array values).
    """

    def __init__(self, source: str) -> None:
        self.source = source
        self.i = 0
        self.n = len(source)

    # -- low-level helpers ------------------------------------------------

    def _peek(self) -> str:
        return self.source[self.i] if self.i < self.n else ""

    def _advance(self) -> str:
        ch = self.source[self.i]
        self.i += 1
        return ch

    def _skip_ws(self) -> None:
        while self.i < self.n and self.source[self.i] in " \t\r\n":
            self.i += 1

    def _expect(self, ch: str) -> None:
        self._skip_ws()
        if self._peek() != ch:
            raise LocaleParseError(
                f"Expected '{ch}' at offset {self.i}; saw {self._peek()!r}"
            )
        self._advance()

    # -- public entry point ----------------------------------------------

    def parse_object(self) -> dict:
        self._skip_ws()
        self._expect("{")
        obj: dict = {}
        self._skip_ws()
        if self._peek() == "}":
            self._advance()
            return obj
        while True:
            self._skip_ws()
            if self._peek() == "}":
                self._advance()
                break
            key = self._parse_key()
            self._skip_ws()
            self._expect(":")
            self._skip_ws()
            value = self._parse_value()
            obj[key] = value
            self._skip_ws()
            if self._peek() == ",":
                self._advance()
                continue
            if self._peek() == "}":
                self._advance()
                break
            raise LocaleParseError(
                f"Expected ',' or '}}' at offset {self.i}; saw {self._peek()!r}"
            )
        return obj

    # -- keys/values ------------------------------------------------------

    _IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")

    def _parse_key(self) -> str:
        ch = self._peek()
        if ch in ("'", '"', "`"):
            return self._parse_string()
        if ch == "[":
            # bracketed computed property: ``[expression]: value``. We treat
            # the bracketed identifier as the key, e.g. ``[CHINESE_LOCALE]``.
            self._advance()
            self._skip_ws()
            match = self._IDENT_RE.match(self.source, self.i)
            if not match:
                raise LocaleParseError(
                    f"Unsupported computed key at offset {self.i}"
                )
            self.i = match.end()
            self._skip_ws()
            self._expect("]")
            return match.group(0)
        match = self._IDENT_RE.match(self.source, self.i)
        if not match:
            raise LocaleParseError(
                f"Expected identifier or string key at offset {self.i}; saw {ch!r}"
            )
        self.i = match.end()
        return match.group(0)

    def _parse_value(self):
        ch = self._peek()
        if ch == "{":
            return self.parse_object()
        if ch == "[":
            array = self._parse_array()
            # Locale files occasionally use ``[ ... ].join('\n')`` to express
            # multi-line strings. Skip the chained call so the value compiles
            # as a single string for downstream key flattening.
            self._skip_ws()
            if self._peek() == "." and self.source[self.i : self.i + 5] == ".join":
                # consume ``.join(...)`` greedily, respecting parens.
                self.i += 5
                self._skip_ws()
                if self._peek() == "(":
                    self.i += 1
                    depth = 1
                    in_str: str | None = None
                    while self.i < self.n and depth > 0:
                        c = self.source[self.i]
                        if in_str is not None:
                            if c == "\\" and self.i + 1 < self.n:
                                self.i += 2
                                continue
                            if c == in_str:
                                in_str = None
                        elif c in ("'", '"', "`"):
                            in_str = c
                        elif c == "(":
                            depth += 1
                        elif c == ")":
                            depth -= 1
                        self.i += 1
                return "\n".join(str(item) for item in array)
            return array
        if ch in ("'", '"', "`"):
            return self._parse_string()
        # Fallback: read until comma or closing brace and treat as literal.
        depth = 0
        start = self.i
        while self.i < self.n:
            c = self.source[self.i]
            if c in "{[":
                depth += 1
            elif c in "}]":
                if depth == 0:
                    break
                depth -= 1
            elif c == "," and depth == 0:
                break
            self.i += 1
        raw = self.source[start : self.i].strip()
        return raw

    def _parse_array(self) -> list:
        self._expect("[")
        out: list = []
        self._skip_ws()
        if self._peek() == "]":
            self._advance()
            return out
        while True:
            self._skip_ws()
            out.append(self._parse_value())
            self._skip_ws()
            if self._peek() == ",":
                self._advance()
                continue
            if self._peek() == "]":
                self._advance()
                return out
            raise LocaleParseError(
                f"Expected ',' or ']' at offset {self.i}; saw {self._peek()!r}"
            )

    def _parse_string(self) -> str:
        quote = self._advance()
        out: list[str] = []
        while self.i < self.n:
            ch = self._advance()
            if ch == "\\" and self.i < self.n:
                esc = self._advance()
                out.append({"n": "\n", "t": "\t", "r": "\r"}.get(esc, esc))
                continue
            if ch == quote:
                return "".join(out)
            out.append(ch)
        raise LocaleParseError("Unterminated string literal")


def _extract_top_level_object(source: str) -> str:
    """Find the first ``= { ... };`` assignment and return the object text."""
    # ``const en = { ... };`` is the canonical shape. Find the first ``{``
    # after the first ``=`` token and read a balanced object.
    eq = source.find("=")
    if eq == -1:
        raise LocaleParseError("Locale source has no '=' assignment")
    brace = source.find("{", eq)
    if brace == -1:
        raise LocaleParseError("Locale source has no '{' after '='")
    depth = 0
    i = brace
    n = len(source)
    in_str: str | None = None
    while i < n:
        ch = source[i]
        if in_str is not None:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            in_str = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[brace : i + 1]
        i += 1
    raise LocaleParseError("Unbalanced braces in locale source")


def parse_locale_file(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    stripped = _strip_comments(raw)
    object_text = _extract_top_level_object(stripped)
    parser = _JsObjectParser(object_text)
    return parser.parse_object()


# ---------------------------------------------------------------------------
# Key flattening
# ---------------------------------------------------------------------------


def flatten_keys(tree: dict, prefix: str = "") -> set[str]:
    """Return the set of dotted leaf keys from a nested locale dict."""
    keys: set[str] = set()
    for key, value in tree.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            if not value:
                keys.add(full)
            else:
                keys.update(flatten_keys(value, full))
        else:
            keys.add(full)
    return keys


# ---------------------------------------------------------------------------
# Source scanning for t() calls
# ---------------------------------------------------------------------------


# Match ``t('key')`` / ``t("key")`` / ``i18n.t('key')`` / ``this.t(\`key\`)``.
# The key must be a string literal (we do NOT try to resolve template
# expressions or variables -- those are reported separately as dynamic keys).
_T_CALL_RE = re.compile(
    r"""
    (?<![A-Za-z0-9_$])         # left boundary: not a word character
    (?:[A-Za-z0-9_$]+\.)?      # optional receiver (e.g. ``i18n.``)
    t\s*                       # the ``t`` function name
    \(\s*                      # open paren
    (?P<quote>['"`])           # opening quote
    (?P<key>[^'"`\\]*(?:\\.[^'"`\\]*)*)
    (?P=quote)                 # matching closing quote
    """,
    re.VERBOSE,
)


def _looks_like_translation_key(key: str) -> bool:
    """Heuristic: real keys are dotted identifiers (or dot-free leaves)."""
    if not key:
        return False
    if len(key) > 200:
        return False
    # Allow letters, digits, underscore, hyphen, dot. Reject obvious sentences
    # (multiple spaces) and template literals.
    if not re.fullmatch(r"[A-Za-z0-9_.\-\[\] ]+", key):
        return False
    if "  " in key:
        return False
    return True


def _is_test_file(path: Path) -> bool:
    name = path.name
    if ".test." in name or ".spec." in name:
        return True
    parts = set(path.parts)
    if {"test", "tests", "__tests__"} & parts:
        return True
    return False


def scan_source_for_keys(
    roots: Iterable[Path],
    *,
    include_tests: bool = False,
) -> tuple[set[str], list[dict]]:
    """Return (key_set, occurrences) found across the supplied roots.

    By default test sources are excluded so injected fixtures (e.g.
    ``t('tests.nullValue')`` in ``i18n.test.jsx``) do not create false
    "missing key" reports against the production locale files.
    """
    keys: set[str] = set()
    occurrences: list[dict] = []
    skip_parts = {"node_modules", "dist", "build", ".vite", ".next", ".turbo"}
    suffixes = {".jsx", ".js", ".mjs", ".ts", ".tsx"}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in suffixes:
                continue
            if set(path.parts) & skip_parts:
                continue
            # Skip the locale files themselves (their string keys would
            # otherwise produce phantom ``t(...)`` matches inside string
            # literal content -- unlikely but defensive).
            if path.name in {"en.js", "zh-CN.js", "locales.test.js", "i18n.js"}:
                # locale files do not call t(); skip them entirely
                continue
            if not include_tests and _is_test_file(path):
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for match in _T_CALL_RE.finditer(content):
                key = match.group("key")
                if not _looks_like_translation_key(key):
                    continue
                keys.add(key)
                line = content.count("\n", 0, match.start()) + 1
                occurrences.append(
                    {
                        "key": key,
                        "file": str(path).replace("\\", "/"),
                        "line": line,
                    }
                )
    return keys, occurrences


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@dataclass
class AuditResult:
    en_keys: set[str] = field(default_factory=set)
    zh_keys: set[str] = field(default_factory=set)
    used_keys: set[str] = field(default_factory=set)
    occurrences: list[dict] = field(default_factory=list)

    def to_summary(self) -> dict:
        used_keys = self.used_keys
        en_keys = self.en_keys
        zh_keys = self.zh_keys

        missing_in_en = sorted(used_keys - en_keys)
        missing_in_zh = sorted(used_keys - zh_keys)
        stale_keys = sorted((en_keys | zh_keys) - used_keys)
        only_in_en = sorted(en_keys - zh_keys)
        only_in_zh = sorted(zh_keys - en_keys)

        return {
            "totals": {
                "en_keys": len(en_keys),
                "zh_keys": len(zh_keys),
                "used_keys": len(used_keys),
                "missing_in_en": len(missing_in_en),
                "missing_in_zh": len(missing_in_zh),
                "stale_keys": len(stale_keys),
                "only_in_en": len(only_in_en),
                "only_in_zh": len(only_in_zh),
            },
            "missing_in_en": missing_in_en,
            "missing_in_zh": missing_in_zh,
            "stale_keys": stale_keys,
            "only_in_en": only_in_en,
            "only_in_zh": only_in_zh,
        }


# i18next pluralization suffixes. A code-side call to ``t('foo')`` with a
# ``count`` argument is satisfied by ``foo_one``/``foo_other``/etc. in the
# locale file. We treat any of these as fulfilling the bare key.
_PLURAL_SUFFIXES = ("_zero", "_one", "_two", "_few", "_many", "_other")


def _key_or_prefix_exists(key: str, locale_keys: set[str]) -> bool:
    """A code-side ``t('a.b')`` is satisfied if any of the following hold:

    - ``a.b`` is a defined leaf.
    - Any leaf below ``a.b.*`` is defined (parent-prefix namespace usage).
    - A pluralized variant ``a.b_one``/``a.b_other``/etc. is defined.
    """
    if key in locale_keys:
        return True
    prefix = key + "."
    if any(existing.startswith(prefix) for existing in locale_keys):
        return True
    for suffix in _PLURAL_SUFFIXES:
        if (key + suffix) in locale_keys:
            return True
    return False


def reconcile_used_keys(used: set[str], en: set[str], zh: set[str]) -> tuple[set[str], set[str]]:
    """Return (missing_in_en, missing_in_zh) after prefix reconciliation."""
    missing_in_en = {k for k in used if not _key_or_prefix_exists(k, en)}
    missing_in_zh = {k for k in used if not _key_or_prefix_exists(k, zh)}
    return missing_in_en, missing_in_zh


def run_audit(
    en_path: Path,
    zh_path: Path,
    source_roots: list[Path],
    *,
    include_tests: bool = False,
) -> AuditResult:
    result = AuditResult()
    if en_path.exists():
        result.en_keys = flatten_keys(parse_locale_file(en_path))
    if zh_path.exists():
        result.zh_keys = flatten_keys(parse_locale_file(zh_path))
    result.used_keys, result.occurrences = scan_source_for_keys(
        source_roots, include_tests=include_tests
    )
    return result


def summarise(result: AuditResult) -> dict:
    summary = result.to_summary()
    # Reconcile by prefix so namespaced calls (``t('common.actions')``) do
    # not get flagged when the leaves exist (``common.actions.save`` etc.).
    missing_en, missing_zh = reconcile_used_keys(result.used_keys, result.en_keys, result.zh_keys)
    summary["missing_in_en"] = sorted(missing_en)
    summary["missing_in_zh"] = sorted(missing_zh)
    summary["totals"]["missing_in_en"] = len(missing_en)
    summary["totals"]["missing_in_zh"] = len(missing_zh)
    # Recompute stale considering that a defined leaf may be reached via a
    # parent prefix call in code, or via a pluralized variant of the key.
    used_with_prefixes: set[str] = set()
    locale_leaves = result.en_keys | result.zh_keys
    for key in result.used_keys:
        used_with_prefixes.add(key)
        prefix = key + "."
        for locale_leaf in locale_leaves:
            if locale_leaf == key or locale_leaf.startswith(prefix):
                used_with_prefixes.add(locale_leaf)
            else:
                for suffix in _PLURAL_SUFFIXES:
                    if locale_leaf == key + suffix or locale_leaf.startswith(key + suffix + "."):
                        used_with_prefixes.add(locale_leaf)
                        break
    stale = sorted(locale_leaves - used_with_prefixes)
    summary["stale_keys"] = stale
    summary["totals"]["stale_keys"] = len(stale)
    return summary


def emit_text_report(summary: dict, occurrences: list[dict], stream) -> None:
    totals = summary["totals"]
    stream.write("Memory Palace i18n audit\n")
    stream.write("=" * 50 + "\n")
    stream.write(f"  en keys defined:   {totals['en_keys']}\n")
    stream.write(f"  zh-CN keys defined: {totals['zh_keys']}\n")
    stream.write(f"  keys used in code: {totals['used_keys']}\n")
    stream.write(f"  occurrences:       {len(occurrences)}\n")
    stream.write("\n")
    stream.write(f"  missing in en.js:    {totals['missing_in_en']}\n")
    stream.write(f"  missing in zh-CN.js: {totals['missing_in_zh']}\n")
    stream.write(f"  only in en.js:       {totals['only_in_en']}\n")
    stream.write(f"  only in zh-CN.js:    {totals['only_in_zh']}\n")
    stream.write(f"  stale keys:          {totals['stale_keys']}\n")
    stream.write("\n")
    sections = [
        ("missing in en.js", summary["missing_in_en"]),
        ("missing in zh-CN.js", summary["missing_in_zh"]),
        ("only in en.js", summary["only_in_en"]),
        ("only in zh-CN.js", summary["only_in_zh"]),
        ("stale keys", summary["stale_keys"]),
    ]
    for title, items in sections:
        if not items:
            continue
        stream.write(f"[{title}] ({len(items)})\n")
        for item in items[:50]:
            stream.write(f"  {item}\n")
        if len(items) > 50:
            stream.write(f"  ... ({len(items) - 50} more)\n")
        stream.write("\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    default_repo = Path(__file__).resolve().parent.parent
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=default_repo,
        help="Repository root (defaults to the parent of this script's directory).",
    )
    parser.add_argument(
        "--en",
        type=Path,
        default=None,
        help="Path to en.js (defaults to <repo>/frontend/src/locales/en.js).",
    )
    parser.add_argument(
        "--zh",
        type=Path,
        default=None,
        help="Path to zh-CN.js (defaults to <repo>/frontend/src/locales/zh-CN.js).",
    )
    parser.add_argument(
        "--src",
        type=Path,
        action="append",
        default=None,
        help="Frontend source root to scan; may be repeated.",
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
        "--allow-missing",
        action="store_true",
        help="Always exit 0 even when keys are missing (for triage).",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help=(
            "Include test files when scanning for t() calls. By default they "
            "are skipped so test-only fixture keys do not create false "
            "missing-key reports."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    en_path = (args.en or (repo_root / "frontend/src/locales/en.js")).resolve()
    zh_path = (args.zh or (repo_root / "frontend/src/locales/zh-CN.js")).resolve()
    src_roots = [p.resolve() for p in (args.src or [repo_root / "frontend/src"])]

    if not en_path.exists():
        sys.stderr.write(f"error: en locale not found at {en_path}\n")
        return 1
    if not zh_path.exists():
        sys.stderr.write(f"error: zh-CN locale not found at {zh_path}\n")
        return 1

    result = run_audit(en_path, zh_path, src_roots, include_tests=args.include_tests)
    summary = summarise(result)
    summary["occurrences_count"] = len(result.occurrences)

    if args.json:
        sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    else:
        emit_text_report(summary, result.occurrences, sys.stdout)

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
                emit_text_report(summary, result.occurrences, buffer)
                args.output.write_text(buffer.getvalue(), encoding="utf-8")
        except OSError as exc:  # pragma: no cover - defensive
            sys.stderr.write(f"warning: could not write --output: {exc}\n")

    totals = summary["totals"]
    if not args.allow_missing and (totals["missing_in_en"] or totals["missing_in_zh"]):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
