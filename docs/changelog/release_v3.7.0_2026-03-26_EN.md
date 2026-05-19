# Memory Palace v3.7.0 Release Notes (2026-03-26)

This note records what was actually changed and re-verified in the current repository.

---

## 1. One-Sentence Conclusion

`v3.7.0` is a tightening release: stricter fail-closed input validation, clearer Dashboard auth behavior under configured API base URLs, and a repaired repo-local skill bundle sync path.

---

## 2. Actual Changes

- `session_id` validation is fail-closed for leading/trailing whitespace and control-style characters. The same rule is reused by the Review API instead of drifting from the snapshot layer.
- The public `priority` contract is consistent across MCP and SQLite. The MCP tool layer no longer coerces `True`, `False`, or `1.9` into integers.
- The Dashboard keeps attaching the saved browser auth key when protected requests are resolved through the configured `VITE_API_BASE_URL`, including non-root-path and cross-origin API deployments. It still does **not** send that key to unrelated third-party absolute URLs.
- Repo-local skill mirrors are back in sync with the canonical `memory-palace` bundle, so `python scripts/sync_memory_palace_skill.py --check` returns `PASS` again.

---

## 3. Verification Scope

- Backend test suite: `785 passed, 18 skipped`
- Frontend test suite: `114 passed`
- Frontend production build: passed
- Live stdio MCP e2e: passed
- Repo-local skill sync check: passed
- macOS local smoke:
  - isolated backend + SSE + Vite path verified
  - Dashboard `Memory / Review / Maintenance / Observability` pages loaded
  - language toggle and browser persistence rechecked
- Linux Docker smoke:
  - `docker_one_click.sh --profile b` rechecked
  - Dashboard root, backend health, and `/sse` (returning `text/event-stream`) reachable
- D-style retrieval chain smoke:
  - verified against real OpenAI-compatible embedding / reranker / intent-LLM services
  - observability search returned `degraded=false`
  - `intent_llm_applied=true` on the verified path

---

## 4. Practical User-Facing Summary

- Obviously malformed `session_id` inputs are rejected earlier and more consistently
- Malformed `priority` values no longer slip through the MCP tool layer
- Dashboard auth behaves more predictably when the API lives under a custom base URL
- The repo-local skill sync path is cleaner again

Conservative release summary:

> `v3.7.0` re-verifies the main backend/frontend paths, repairs strict validation around `session_id` and `priority`, and restores repo-local skill sync consistency.
