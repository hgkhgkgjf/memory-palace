# Memory Palace Post-Release Hardening Follow-up (2026-04-21)

This note records what was actually changed and re-verified in this round.

---

## 1. One-Sentence Conclusion

The public MCP contract is tighter, percent-encoded memory URIs are handled more predictably, existing SQLite files now fail closed earlier when integrity checks fail, vitality cleanup multi-delete is no longer allowed to half-succeed, and the authenticated Observability SSE path now recovers more explicitly when browser auth changes.

---

## 2. Actual Changes

- The public MCP boundary rejects URIs containing control chars, invisible format chars, or surrogates.
- Percent-encoded memory URIs keep literal percent sequences as valid path text, while still resolving existing paths through decoded variants such as encoded spaces or slashes. Percent-decoded Windows filesystem paths such as `C%3A/...` are rejected as invalid memory URIs.
- `search_memory.query` is capped at `8000` characters at the MCP entry; `create_memory.content` and `update_memory.old_string/new_string/append` are capped at `100000` characters. Overlong payloads are rejected before DB work begins.
- If `add_alias` writes the alias path first but snapshot capture fails afterwards, the implementation compensates by rolling back that alias path instead of leaving a "tool errored, alias still landed" half-success state behind.
- Keyword retrieval checks whether a query is safe for FTS first. Reserved tokens such as `AND / OR / NOT / NEAR`, or wildcard-heavy inputs, no longer get to silently steer match semantics.
- Snapshot recovery now covers not only "damaged manifest" but also "manifest missing while resource files still exist," as long as the original database scope can still be preserved.
- Private provider validation covers both private IP literals and hostnames that resolve to private non-loopback addresses; loopback literals and `localhost` remain allowed by default.
- The `read_memory` recent-read fast path consults a lighter recent-state check before deciding whether the second full read can be skipped.
- The Maintenance observability search request uses the same query length cap as the MCP search path.
- Existing on-disk SQLite files fail closed during init if `PRAGMA quick_check(1)` does not return `ok`; bootstrap indexing repairs active memories missing FTS rows as well as memories missing chunk rows; permanent memory deletion clears chunk/vector/FTS rows for that memory.
- Reviewed vitality-cleanup delete batches execute atomically inside one DB session when session-backed delete support is available. If that batch cannot be made atomic, the backend rejects it instead of deleting early items and failing halfway; single-delete fallback remains allowed.
- Changing or clearing browser-side Dashboard auth emits a maintenance-auth change event, and the Observability page uses that signal plus a focus-time recheck to rebuild its authenticated `/sse` stream after auth changes or after a terminal `401` stopped retries.

---

## 3. Verification Scope

- Full backend suite: `1136 passed, 22 skipped`
- Full frontend suite: `198 passed`
- Frontend `typecheck`: passed
- Frontend `build`: passed
- Repo-local live MCP e2e script: passed
- Repo-local macOS `Profile B` real-browser smoke: passed

---

## 4. Practical User-Facing Summary

- Public MCP tools reject obviously invalid URIs and overlong inputs earlier
- `add_alias` no longer leaves a "failed but already written" alias behind
- FTS control words and wildcard-heavy user text no longer quietly change retrieval semantics
- Review snapshots are more likely to recover safely when the manifest file is missing
- Observability rebuilds an authenticated `/sse` connection after browser auth changes

If you need a conservative one-liner for others:

> This follow-up tightens the public MCP input contract, makes percent-encoded URI handling more predictable, fail-closes earlier on bad local SQLite files, removes the half-success window from vitality multi-delete, and re-verifies backend, frontend, and repo-local MCP.
