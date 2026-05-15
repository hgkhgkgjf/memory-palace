"""MCP Contract Golden Test.

Round 0 baseline: this test pins the *signatures* of the 9 MCP tools exposed by
``backend/mcp_server.py``. It fails loudly if any tool is added, removed,
renamed, or has its parameter list / type annotations / defaults / return type
changed without a matching update to ``mcp_contract_golden.json``.

Why a separate test instead of inspecting ``mcp_server.mcp``?
- Importing ``mcp_server`` triggers heavy module-level side effects (SQLite
  client init, runtime state, write lanes). The contract layer must remain
  importable in CI without those side effects. We therefore prefer the AST
  path; only when AST is unavailable do we fall back to ``importlib`` + the
  function objects exposed by ``mcp_server`` (these are the original
  ``async def`` callables; the ``@mcp.tool()`` decorator does not wrap them).

Refactoring contract: if a Round changes a signature *on purpose*, the same
commit MUST regenerate the golden JSON (e.g. via
``python -m backend.tests.contract.regenerate_golden``, or by hand). A test
failure here without a paired golden update means "regression".
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import os
import sys
import typing
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

CONTRACT_DIR = Path(__file__).resolve().parent
GOLDEN_PATH = CONTRACT_DIR / "mcp_contract_golden.json"
E2E_GOLDEN_PATH = CONTRACT_DIR / "e2e_golden_transcript.json"
REPO_ROOT = CONTRACT_DIR.parents[2]
MCP_SERVER_PATH = REPO_ROOT / "backend" / "mcp_server.py"
E2E_SCRIPT_PATH = REPO_ROOT / "scripts" / "evaluate_memory_palace_mcp_e2e.py"

EXPECTED_TOOL_NAMES = {
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

SQLITE_CLIENT_REEXPORT_NAMES = {
    "Base",
    "Memory",
    "Path",
    "MemoryChunk",
    "MemoryChunkVec",
    "EmbeddingCache",
    "IndexMeta",
    "SchemaMigration",
    "MemoryGist",
    "MemoryTag",
    "AccessLog",
    "MemorySummary",
    "ArchivedMemory",
    "ProceduralMemory",
    "_utc_now_naive",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def golden() -> Dict[str, Any]:
    """Load the frozen contract."""
    with GOLDEN_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def e2e_golden() -> Dict[str, Any]:
    with E2E_GOLDEN_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def extracted_tools() -> Dict[str, Dict[str, Any]]:
    """Parse ``backend/mcp_server.py`` with ``ast`` and return a dict keyed by
    function name for every function decorated with ``@mcp.tool()``.

    We pin on AST (not import) so the test is hermetic: no DB, no runtime,
    no side effects. Importing mcp_server is gated behind a separate test
    that is skipped if the import fails (e.g. missing optional deps).
    """
    source = MCP_SERVER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(MCP_SERVER_PATH))

    tools: Dict[str, Dict[str, Any]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if not _has_mcp_tool_decorator(node):
            continue
        tools[node.name] = _describe_function(node)
    return tools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_mcp_tool_decorator(node: ast.AST) -> bool:
    for dec in getattr(node, "decorator_list", []):
        try:
            text = ast.unparse(dec)  # py>=3.9
        except AttributeError:  # pragma: no cover - py<3.9 fallback
            text = ""
        if "mcp.tool" in text:
            return True
    return False


def _describe_function(node: ast.AST) -> Dict[str, Any]:
    args = node.args
    positional = list(args.args)
    defaults = list(args.defaults)
    n_pos = len(positional)
    n_def = len(defaults)

    params: List[Dict[str, Any]] = []
    for i, arg in enumerate(positional):
        has_default = i >= n_pos - n_def
        default_value: Any = None
        if has_default:
            default_node = defaults[i - (n_pos - n_def)]
            try:
                default_value = ast.literal_eval(default_node)
            except Exception:
                default_value = ast.unparse(default_node)
        params.append(
            {
                "annotation": ast.unparse(arg.annotation) if arg.annotation else None,
                "default": default_value if has_default else None,
                "has_default": has_default,
                "name": arg.arg,
                "order": i,
            }
        )

    return {
        "is_async": isinstance(node, ast.AsyncFunctionDef),
        "line_no": node.lineno,
        "params": params,
        "return_annotation": ast.unparse(node.returns) if node.returns else None,
    }


def _normalize_param(p: Dict[str, Any]) -> Tuple[str, str, bool, Any, int]:
    """Stable comparable tuple for one parameter."""
    return (
        p["name"],
        p.get("annotation") or "",
        bool(p.get("has_default", False)),
        p.get("default"),
        int(p.get("order", -1)),
    )


def _import_db_module(module_name: str):
    backend_root = REPO_ROOT / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    return importlib.import_module(module_name)


# ---------------------------------------------------------------------------
# 1) Inventory: same set of @mcp.tool()-decorated functions
# ---------------------------------------------------------------------------


def test_tool_inventory_matches_golden(
    golden: Dict[str, Any], extracted_tools: Dict[str, Dict[str, Any]]
) -> None:
    expected = set(golden["tools"].keys())
    actual = set(extracted_tools.keys())

    assert expected == EXPECTED_TOOL_NAMES, (
        "Golden tool set drifted from the canonical 9 tools. "
        f"Golden has {sorted(expected)}; canonical is {sorted(EXPECTED_TOOL_NAMES)}."
    )
    assert actual == EXPECTED_TOOL_NAMES, (
        "@mcp.tool() inventory in backend/mcp_server.py drifted. "
        f"Found {sorted(actual)}; expected {sorted(EXPECTED_TOOL_NAMES)}. "
        "If this is intentional, update mcp_contract_golden.json in the same commit."
    )
    assert golden["tool_count"] == 9, "tool_count field must stay at 9 in Round 0."


# ---------------------------------------------------------------------------
# 2) Per-tool: async/return/param order/annotations/defaults
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_TOOL_NAMES))
def test_tool_signature_matches_golden(
    tool_name: str,
    golden: Dict[str, Any],
    extracted_tools: Dict[str, Dict[str, Any]],
) -> None:
    expected_spec = golden["tools"][tool_name]
    actual_spec = extracted_tools[tool_name]

    # async flag
    assert actual_spec["is_async"] == expected_spec["is_async"], (
        f"{tool_name}: async-ness changed "
        f"(golden={expected_spec['is_async']}, actual={actual_spec['is_async']})."
    )

    # return annotation
    assert actual_spec["return_annotation"] == expected_spec["return_annotation"], (
        f"{tool_name}: return annotation changed "
        f"(golden={expected_spec['return_annotation']!r}, "
        f"actual={actual_spec['return_annotation']!r})."
    )

    expected_params = [_normalize_param(p) for p in expected_spec["params"]]
    actual_params = [_normalize_param(p) for p in actual_spec["params"]]

    assert len(expected_params) == len(actual_params), (
        f"{tool_name}: parameter count changed "
        f"(golden={len(expected_params)}, actual={len(actual_params)}). "
        f"golden={[p[0] for p in expected_params]}; "
        f"actual={[p[0] for p in actual_params]}."
    )

    # Compare positionally; param order is part of the contract for MCP clients.
    for golden_p, actual_p in zip(expected_params, actual_params):
        assert golden_p == actual_p, (
            f"{tool_name}: parameter drift detected.\n"
            f"  golden: name={golden_p[0]!r} annotation={golden_p[1]!r} "
            f"has_default={golden_p[2]} default={golden_p[3]!r} order={golden_p[4]}\n"
            f"  actual: name={actual_p[0]!r} annotation={actual_p[1]!r} "
            f"has_default={actual_p[2]} default={actual_p[3]!r} order={actual_p[4]}"
        )


# ---------------------------------------------------------------------------
# 3) Source line drift: lets reviewers spot moved code quickly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_TOOL_NAMES))
def test_tool_source_line_is_close_to_golden(
    tool_name: str,
    golden: Dict[str, Any],
    extracted_tools: Dict[str, Dict[str, Any]],
) -> None:
    """Soft check: warn (assert with tolerance) when the function moved a lot.

    Source lines drift naturally as the file is edited. We assert they are
    within +/- 200 lines of the frozen value so a refactor that swaps two
    tools or re-orders them fails the test even though signatures match.
    """
    expected_line = int(golden["tools"][tool_name]["source_line"])
    actual_line = int(extracted_tools[tool_name]["line_no"])
    delta = abs(actual_line - expected_line)
    assert delta <= 200, (
        f"{tool_name}: function moved more than +/-200 lines "
        f"(golden_line={expected_line}, actual_line={actual_line}, delta={delta}). "
        "Verify this isn't a reorder/extraction that changed call semantics, "
        "then update mcp_contract_golden.json."
    )


# ---------------------------------------------------------------------------
# 4) Domain / URI scheme contract
# ---------------------------------------------------------------------------


def test_uri_schemes_and_domains_match_golden(golden: Dict[str, Any]) -> None:
    source = MCP_SERVER_PATH.read_text(encoding="utf-8")

    # Pin the env default for VALID_DOMAINS = "core,writer,game,notes,system"
    assert (
        f'"VALID_DOMAINS", "{golden["valid_domains_env_default"]}"' in source
        or f"'VALID_DOMAINS', '{golden['valid_domains_env_default']}'" in source
    ), (
        "VALID_DOMAINS env default in backend/mcp_server.py drifted from the "
        f"frozen value {golden['valid_domains_env_default']!r}."
    )

    # Pin DEFAULT_DOMAIN
    assert f'DEFAULT_DOMAIN = "{golden["default_domain"]}"' in source, (
        f"DEFAULT_DOMAIN in backend/mcp_server.py drifted from "
        f"{golden['default_domain']!r}."
    )

    # Pin READ_ONLY_DOMAINS membership (we only require 'system' to remain RO)
    assert "READ_ONLY_DOMAINS" in source and '"system"' in source, (
        "READ_ONLY_DOMAINS must keep 'system' for the contract to hold."
    )


# ---------------------------------------------------------------------------
# 5) Backwards-compatibility shims: sqlite_client model re-exports
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SQLITE_CLIENT_REEXPORT_NAMES))
def test_sqlite_client_reexports_model_identity(name: str) -> None:
    """``from db.sqlite_client import Memory`` must remain a pure re-export."""

    original_env = dict(os.environ)
    try:
        sqlite_client = _import_db_module("db.sqlite_client")
        models = _import_db_module("db.models")
    finally:
        os.environ.clear()
        os.environ.update(original_env)

    assert hasattr(sqlite_client, name), f"db.sqlite_client no longer exports {name!r}"
    assert hasattr(models, name), f"db.models no longer defines {name!r}"
    assert getattr(sqlite_client, name) is getattr(models, name), (
        f"db.sqlite_client.{name} must be identical to db.models.{name}. "
        "Do not replace this BC shim with duplicate wrapper classes."
    )


def test_sqlite_client_reexport_roster_matches_models_all() -> None:
    original_env = dict(os.environ)
    try:
        sqlite_client = _import_db_module("db.sqlite_client")
        models = _import_db_module("db.models")
    finally:
        os.environ.clear()
        os.environ.update(original_env)

    exported = set(getattr(models, "__all__", ()))
    assert SQLITE_CLIENT_REEXPORT_NAMES.issubset(exported)
    missing = [
        name for name in SQLITE_CLIENT_REEXPORT_NAMES if not hasattr(sqlite_client, name)
    ]
    assert missing == []


# ---------------------------------------------------------------------------
# 6) E2E golden: tool name set is the same 9
# ---------------------------------------------------------------------------


def test_e2e_golden_inventory_matches_canonical(e2e_golden: Dict[str, Any]) -> None:
    inventory = set(e2e_golden["expected_tool_inventory"])
    assert inventory == EXPECTED_TOOL_NAMES, (
        "E2E golden transcript expected_tool_inventory drifted from the "
        f"canonical 9 tools. Got {sorted(inventory)}; "
        f"expected {sorted(EXPECTED_TOOL_NAMES)}."
    )


def test_e2e_golden_steps_reference_only_known_tools(
    e2e_golden: Dict[str, Any],
) -> None:
    for step in e2e_golden["steps"]:
        tool = step.get("tool")
        if tool is None:
            continue  # inventory-only step
        assert tool in EXPECTED_TOOL_NAMES, (
            f"E2E golden step {step.get('name')!r} references unknown tool "
            f"{tool!r}. Either fix the step or expand EXPECTED_TOOL_NAMES + "
            f"mcp_contract_golden.json."
        )


def test_e2e_script_has_matching_expected_tools(e2e_golden: Dict[str, Any]) -> None:
    """The live E2E script declares EXPECTED_TOOLS; the golden must agree."""
    src = E2E_SCRIPT_PATH.read_text(encoding="utf-8")
    for name in EXPECTED_TOOL_NAMES:
        assert f'"{name}"' in src, (
            f"scripts/evaluate_memory_palace_mcp_e2e.py is missing tool name "
            f"{name!r} in its EXPECTED_TOOLS literal set."
        )
    inventory = set(e2e_golden["expected_tool_inventory"])
    assert inventory == EXPECTED_TOOL_NAMES


# ---------------------------------------------------------------------------
# 7) Optional: import-based double-check (skipped if mcp_server can't import)
# ---------------------------------------------------------------------------


def _try_import_mcp_server():
    if "backend.mcp_server" in sys.modules:
        return sys.modules["backend.mcp_server"]
    try:
        return importlib.import_module("backend.mcp_server")
    except Exception:
        return None


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_TOOL_NAMES))
def test_runtime_signature_matches_golden_when_importable(
    tool_name: str, golden: Dict[str, Any]
) -> None:
    """When the module imports cleanly, also assert the live callable has the
    same parameter list. Skipped (not failed) when the import requires heavy
    runtime that isn't available in the contract test environment."""
    mcp_server = _try_import_mcp_server()
    if mcp_server is None:
        pytest.skip(
            "backend.mcp_server is not importable in this environment; "
            "AST-based assertions still ran."
        )

    func = getattr(mcp_server, tool_name, None)
    if func is None:
        pytest.fail(
            f"backend.mcp_server has no top-level attribute {tool_name!r}. "
            "Did the @mcp.tool() function get renamed?"
        )

    # ``inspect.signature`` works on the underlying async function even though
    # it carries the @mcp.tool() decorator (FastMCP keeps the wrapper as a
    # simple registration, not a wrapping closure).
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError) as exc:
        pytest.skip(f"Could not introspect {tool_name}: {exc}")

    expected_params = golden["tools"][tool_name]["params"]
    actual_param_names = [
        p.name
        for p in sig.parameters.values()
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    ]
    expected_param_names = [p["name"] for p in expected_params]
    assert actual_param_names == expected_param_names, (
        f"{tool_name}: live callable parameter names drifted from golden. "
        f"golden={expected_param_names}, runtime={actual_param_names}."
    )


# ---------------------------------------------------------------------------
# 8) Boot text hash sanity check
# ---------------------------------------------------------------------------


def test_boot_text_skeleton_hash_is_consistent(golden: Dict[str, Any]) -> None:
    import hashlib

    skeleton = "\n".join(golden["boot_text_skeleton"])
    h = hashlib.sha256(skeleton.encode("utf-8")).hexdigest()
    assert h == golden["boot_text_hash"], (
        "boot_text_hash in mcp_contract_golden.json does not match the "
        "sha256 of boot_text_skeleton. Recompute one of them; the skeleton "
        "is the deterministic empty-DB output of read_memory('system://boot')."
    )
