# Memory Palace Post-Release Hardening Follow-up (2026-04-21)

This note records only what was **actually changed and actually re-verified**
in the 2026-04-21 post-release hardening validation. It does not turn
target-environment caveats into blanket guarantees.

---

## 1. One-Sentence Conclusion

This round is a post-release hardening follow-up: the public MCP contract is
tighter, percent-encoded memory URIs are handled more predictably, existing
SQLite files now fail closed earlier when integrity checks fail, vitality
cleanup multi-delete is no longer allowed to half-succeed, and the
authenticated Observability SSE path now recovers more explicitly when browser
auth changes.

---

## 2. What Actually Changed

- The public MCP boundary now rejects URIs containing control chars, invisible
  format chars, or surrogates instead of letting them continue into the write
  chain.
- Percent-encoded memory URIs now keep literal percent sequences as valid path
  text, while still resolving existing paths through decoded variants such as
  encoded spaces or slashes. Percent-decoded Windows filesystem paths such as
  `C%3A/...` are rejected as invalid memory URIs.
- `search_memory.query` is now capped at `8000` characters at the MCP entry
  point; `create_memory.content` and
  `update_memory.old_string/new_string/append` are now capped at `100000`
  characters. Overlong payloads are rejected before DB work begins.
- If `add_alias` writes the alias path first but snapshot capture fails
  afterwards, the current implementation compensates by rolling back that alias
  path instead of leaving a “tool errored, alias still landed” half-success
  state behind.
- Keyword retrieval now checks whether a query is safe for FTS first. Reserved
  tokens such as `AND / OR / NOT / NEAR`, or wildcard-heavy inputs, no longer
  get to silently steer match semantics; the current implementation falls back
  safely for that request.
- Snapshot recovery now covers not only “damaged manifest” but also “manifest
  missing while resource files still exist,” as long as the original database
  scope can still be preserved.
- Private provider validation now covers not only private IP literals but also
  hostnames that resolve to private non-loopback addresses; loopback literals
  and `localhost` remain allowed by default.
- The `read_memory` recent-read fast path now consults a lighter recent-state
  check before deciding whether the second full read can be skipped, reducing
  repeated DB work on hot paths.
- The Maintenance observability search request now uses the same query length
  cap as the MCP search path, so the public HTTP surface and MCP surface no
  longer drift on that contract.
- Existing on-disk SQLite files now fail closed during init if
  `PRAGMA quick_check(1)` does not return `ok`; bootstrap indexing now repairs
  active memories missing FTS rows as well as memories missing chunk rows; and
  permanent memory deletion now clears chunk/vector/FTS rows for that memory.
- Reviewed vitality-cleanup delete batches now execute atomically inside one DB
  session when session-backed delete support is available. If that multi-delete
  batch cannot be made atomic, the backend rejects it instead of deleting early
  items and failing halfway through; single-delete fallback remains allowed.
- Changing or clearing browser-side Dashboard auth now emits a
  maintenance-auth change event, and the Observability page uses that signal,
  plus a focus-time recheck, to rebuild its authenticated `/sse` stream after
  auth changes or after a terminal `401` stopped retries.

---

## 3. What Was Actually Re-verified

- Full backend suite: `1136 passed, 22 skipped`
- Full frontend suite: `198 passed`
- Frontend `typecheck`: passed
- Frontend `build`: passed
- Repo-local live MCP e2e script: passed
- The same validation round also covered repo-local macOS `Profile B`
  real-browser smoke
- Repo-local skill smoke in that validation round:
  - `structure`, `description_contract`, `mirrors`, `sync_check`,
    `mcp_bindings`, `claude`, `gemini`, and `opencode` are `PASS`
  - `codex`, `cursor`, `agent`, and `antigravity` remain `PARTIAL`
  - `gemini_live` remains `SKIP`
- A small real A/B/C/D rerun in that validation round:
  - dataset: `BEIR NFCorpus`
  - parameters: `sample_size=5`, `extra_distractors=20`,
    `candidate_multiplier=8`
  - result: `Profile D` Phase 6 Gate stayed `PASS`

---

## 4. What This Follow-up Still Does Not Claim

- This round did **not** recalculate the public benchmark tables end to end;
  the evaluation page keeps the existing public baseline tables and only adds
  the smaller same-session real A/B/C/D rerun note.
- This round also does **not** turn Docker one-click `Profile C/D`, native
  Windows, or native Linux host-runtime paths into “freshly revalidated
  everywhere” claims; those paths still keep explicit target-environment
  boundaries.
- Host-sensitive items such as `codex`, `gemini`, `cursor`, `agent`, and
  `antigravity` still depend on local login state, CLI output shape, and host
  availability, so they continue to be described conservatively as
  `PARTIAL` / `SKIP` where appropriate.

---

## 5. Practical User-Facing Summary

If you only care about what became more reliable after this follow-up, the
simple version is:

- public MCP tools now reject obviously invalid URIs and overlong inputs earlier
- `add_alias` no longer leaves a “failed but already written” alias behind
- FTS control words and wildcard-heavy user text no longer quietly change
  retrieval semantics
- Review snapshots are more likely to recover safely when the manifest file is
  missing

If you need a conservative one-line summary for others, use something like:

> This follow-up tightens the public MCP input contract, makes percent-encoded
> URI handling more predictable, fail-closes earlier on bad local SQLite files,
> removes the half-success window from vitality multi-delete, and re-verifies
> backend, frontend, and repo-local MCP while keeping target-environment
> caveats explicit.
