# Memory Palace v3.7.1 Release Notes (2026-03-26)

This note records what was actually changed and re-verified in the current repository.

---

## 1. One-Sentence Conclusion

`v3.7.1` is a tightening and operator-safety release: path deletion is more atomic, rollback metadata restore is less lossy, Windows script boundaries are safer, and the repo-local skill evaluator behaves more like an environment check than a false repo failure.

---

## 2. Actual Changes

- `delete_memory` keeps the current-path read, delete snapshot capture, and path removal inside one SQLite write transaction. Another local process sharing the same SQLite file is less likely to swap the path occupant between "what was deleted" and "what was actually removed."
- `rollback_to_memory(..., restore_path_metadata=True)` restores metadata only for the selected path. Alias-specific `priority` / `disclosure` values are no longer overwritten by the primary path's snapshot metadata.
- Provider-chain embedding cache reuse is tighter. In fail-open remote chains, later requests can reuse cached provider results after an earlier remote failure instead of always re-hitting every fallback provider.
- Review session listing skips invalid legacy session directory names instead of letting those names break session listing.
- `add_alias` enforces the same public `priority` contract as `create_memory` / `update_memory`, so bool/float-style values are rejected at the MCP boundary.
- `apply_profile.sh` normalizes Windows absolute target paths passed from PowerShell / WSL / Git Bash on a native Windows checkout, including the common separator-mangled form, instead of dropping a broken filename into the repository root.
- `docker_one_click.ps1` preserves UTF-8 without BOM when it rewrites the generated Docker env file. Native Windows PowerShell no longer risks feeding Docker Compose a UTF-16 env file through that path.
- `evaluate_memory_palace_skill.py` parses normal dotenv-style `DATABASE_URL` values more correctly, including quoted values, `export DATABASE_URL=...`, and trailing comments. The same script treats user-scope binding drift and Gemini login/auth prompts as environment `PARTIAL`s, and keeps `gemini_live` as an explicit opt-in path.

---

## 3. Verification Scope

- Backend test suite: `797 passed, 20 skipped`
- Frontend test suite: `119 passed`
- Frontend production build: passed
- Live stdio MCP e2e: passed
- Repo-local skill sync check: passed
- Repo-local skill evaluator:
  - exit code rechecked as success on the current machine
  - environment-sensitive items such as user-scope drift, Gemini login, or missing host runtimes remain `PARTIAL` / `MANUAL`
- Native macOS local validation:
  - repo-local backend + standalone SSE + Vite path rechecked
  - Memory / Review / Maintenance / Observability pages rechecked in a real browser
  - English/Chinese toggle and persistence rechecked
- Native Windows local smoke:
  - follow-up real-host validation confirmed on the released tag
  - host-side startup and the main functional path were rechecked
- Docker validation:
  - Profile B one-click path rechecked
  - Profile C / D runtime-injection retrieval paths rechecked against real embedding / reranker / LLM services
  - Dashboard root, backend health, authenticated browse, and `/sse` reachable

---

## 4. Practical User-Facing Summary

- Deleting a path is less racy on a shared local SQLite file
- Rolling back one path no longer wipes alias-specific metadata
- Windows shell / PowerShell deployment helpers are less brittle
- Repo-local skill validation is less likely to fail for machine-local auth or config drift that is not a repository bug

Conservative release summary:

> `v3.7.1` tightens local delete-path atomicity, preserves alias-specific rollback metadata, hardens Windows operator script boundaries, and re-verifies the main backend/frontend paths on real macOS and Windows hosts.
</content>
