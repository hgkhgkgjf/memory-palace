#!/usr/bin/env python3
"""Render per-host SKILL.md files from the canonical Memory Palace template.

The canonical template lives under :pyref:`docs/skills/memory-palace/SKILL.md`.
This script renders host-specific variants for the six supported agents:

    claude, codex, cursor, opencode, agent, gemini

Each host gets a tiny patch applied on top of the canonical template:

* ``claude``, ``codex``, ``cursor``, ``opencode``, ``agent``
  Use the full canonical template verbatim (including the
  ``allowed-tools`` frontmatter that pins all 9 MCP tool symbols).

* ``gemini``
  Uses the dedicated *shorter* variant under
  ``docs/skills/memory-palace/variants/gemini/SKILL.md`` because Gemini CLI
  does not parse the ``allowed-tools`` key and prefers a tighter description
  block.

The renderer also resolves a tiny set of template variables so that future
host-specific tweaks (different MCP namespaces, different reference paths)
remain a one-line change in ``HOST_PATCHES`` rather than a five-file edit:

* ``{{MCP_NS}}``      — MCP tool namespace prefix used by the host
* ``{{TRIGGER_REF}}`` — repository-visible path of trigger samples reference
* ``{{WORKFLOW_REF}}``— repository-visible path of the workflow reference

These variables are deliberately rendered with ``{{ NAME }}`` style mustaches
so they cannot collide with the existing YAML / Markdown body that uses
single-brace ``{...}`` punctuation in code examples.

The script intentionally does NOT touch the canonical templates. It only
reads them and emits the rendered output. Golden tests under
``backend/tests/test_render_skill.py`` pin the output byte-for-byte for each
of the six hosts.

CLI usage::

    # Render one host and write to a chosen path
    python scripts/render_skill.py --host claude \
        --output .claude/skills/memory-palace/SKILL.md

    # Render to stdout (default when --output is omitted)
    python scripts/render_skill.py --host gemini

    # Render every host into the conventional workspace mirror layout
    python scripts/render_skill.py --all

The ``--all`` mode writes to the repo's existing workspace mirror dirs:

    .claude/skills/memory-palace/SKILL.md
    .codex/skills/memory-palace/SKILL.md
    .cursor/skills/memory-palace/SKILL.md
    .opencode/skills/memory-palace/SKILL.md
    .agent/skills/memory-palace/SKILL.md
    .gemini/skills/memory-palace/SKILL.md

All errors exit with a non-zero status and a single-line message on stderr.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DIR = REPO_ROOT / "docs" / "skills" / "memory-palace"
CANONICAL_SKILL = CANONICAL_DIR / "SKILL.md"
GEMINI_VARIANT = CANONICAL_DIR / "variants" / "gemini" / "SKILL.md"


SUPPORTED_HOSTS: tuple[str, ...] = (
    "claude",
    "codex",
    "cursor",
    "opencode",
    "agent",
    "gemini",
)


# ---------------------------------------------------------------------- patches


@dataclass(frozen=True)
class HostPatch:
    """Per-host rendering patch.

    Attributes
    ----------
    source:
        Path of the per-host *template* relative to the repo root. Either
        the canonical ``docs/skills/memory-palace/SKILL.md`` or the Gemini
        variant. Other hosts reuse the canonical template; switching one of
        them to a dedicated variant only requires editing this table.
    output:
        Repository-local mirror path for ``--all`` rendering.
    variables:
        Template variable map. The values are inserted verbatim into the
        rendered output wherever ``{{ KEY }}`` appears.
    """

    source: Path
    output: Path
    variables: Mapping[str, str]


_BASE_VARIABLES: Dict[str, str] = {
    "MCP_NS": "mcp__memory-palace__",
    "TRIGGER_REF": "docs/skills/memory-palace/references/trigger-samples.md",
    "WORKFLOW_REF": "docs/skills/memory-palace/references/mcp-workflow.md",
}


HOST_PATCHES: Dict[str, HostPatch] = {
    "claude": HostPatch(
        source=CANONICAL_SKILL,
        output=REPO_ROOT / ".claude" / "skills" / "memory-palace" / "SKILL.md",
        variables=_BASE_VARIABLES,
    ),
    "codex": HostPatch(
        source=CANONICAL_SKILL,
        output=REPO_ROOT / ".codex" / "skills" / "memory-palace" / "SKILL.md",
        variables=_BASE_VARIABLES,
    ),
    "cursor": HostPatch(
        source=CANONICAL_SKILL,
        output=REPO_ROOT / ".cursor" / "skills" / "memory-palace" / "SKILL.md",
        variables=_BASE_VARIABLES,
    ),
    "opencode": HostPatch(
        source=CANONICAL_SKILL,
        output=REPO_ROOT / ".opencode" / "skills" / "memory-palace" / "SKILL.md",
        variables=_BASE_VARIABLES,
    ),
    "agent": HostPatch(
        source=CANONICAL_SKILL,
        output=REPO_ROOT / ".agent" / "skills" / "memory-palace" / "SKILL.md",
        variables=_BASE_VARIABLES,
    ),
    "gemini": HostPatch(
        source=GEMINI_VARIANT,
        output=REPO_ROOT / ".gemini" / "skills" / "memory-palace" / "SKILL.md",
        variables=_BASE_VARIABLES,
    ),
}


# ----------------------------------------------------------- template rendering


_VARIABLE_PATTERN = re.compile(r"\{\{\s*([A-Z_][A-Z0-9_]*)\s*\}\}")


def render_template(text: str, variables: Mapping[str, str]) -> str:
    """Substitute ``{{ NAME }}`` placeholders with values from ``variables``.

    Unknown placeholders raise :class:`KeyError` to keep golden tests honest:
    if a template references a variable the renderer cannot resolve, the
    rendering must fail loudly instead of leaking the literal placeholder
    into the output.
    """

    def _replace(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name not in variables:
            raise KeyError(f"Unknown template variable: {name!r}")
        return variables[name]

    return _VARIABLE_PATTERN.sub(_replace, text)


def render_for_host(host: str) -> str:
    """Render the SKILL.md content for ``host`` as a single string.

    The function does NOT write to disk; the caller is responsible for the
    I/O step. This makes it trivial to compare the rendered string against
    a golden fixture byte-for-byte.
    """
    if host not in HOST_PATCHES:
        raise ValueError(
            f"Unknown host {host!r}. Supported hosts: {', '.join(SUPPORTED_HOSTS)}"
        )
    patch = HOST_PATCHES[host]
    if not patch.source.is_file():
        raise FileNotFoundError(
            f"Missing template for host {host!r}: {patch.source}"
        )
    raw = patch.source.read_text(encoding="utf-8")
    return render_template(raw, patch.variables)


# ----------------------------------------------------------------- file output


def _write_text_atomic(target: Path, content: str) -> None:
    """Write ``content`` to ``target`` via a temp-then-rename swap.

    Using a sibling temp path keeps the rename atomic on the same
    filesystem, so a partial rendering never corrupts the mirror file.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(target)


def render_to_path(host: str, output_path: Path) -> Path:
    """Render ``host`` and write the result to ``output_path``."""
    content = render_for_host(host)
    _write_text_atomic(output_path, content)
    return output_path


def render_all(hosts: Iterable[str] = SUPPORTED_HOSTS) -> Dict[str, Path]:
    """Render every host into its conventional workspace mirror path.

    Returns a mapping from host name to the absolute path that was
    written. Already-up-to-date files are still rewritten (idempotent).
    """
    written: Dict[str, Path] = {}
    for host in hosts:
        patch = HOST_PATCHES[host]
        written[host] = render_to_path(host, patch.output)
    return written


# -------------------------------------------------------------------- CLI glue


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render per-host SKILL.md variants from the canonical Memory Palace "
            "skill template. See module docstring for the host list and patch "
            "table."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--host",
        choices=SUPPORTED_HOSTS,
        help="Render a single host. Use --output to choose the destination.",
    )
    mode.add_argument(
        "--all",
        dest="render_all",
        action="store_true",
        help=(
            "Render every supported host into its workspace mirror path. "
            "Ignores --output."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Where to write the rendered output. Defaults to stdout when "
            "rendering a single host. Ignored when --all is set."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    try:
        if args.render_all:
            written = render_all()
            for host, path in written.items():
                print(f"{host}: {path.relative_to(REPO_ROOT)}")
            return 0

        # Single-host mode.
        if args.output is None:
            sys.stdout.write(render_for_host(args.host))
            return 0
        path = render_to_path(args.host, args.output.resolve())
        print(f"{args.host}: {path}")
        return 0
    except FileNotFoundError as exc:
        print(f"render_skill: {exc}", file=sys.stderr)
        return 1
    except (ValueError, KeyError) as exc:
        print(f"render_skill: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
