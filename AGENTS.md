# Memory Palace Agent Rules

These rules apply to AI coding agents working inside this repository.

## Read First

- `README.md`
- `docs/GETTING_STARTED.md`
- `docs/skills/memory-palace/SKILL.md` when the task is about durable memory workflow or skill behavior

## Durable Memory Workflow

- Start with `read_memory("system://boot")` before the first real Memory Palace operation in a session.
- If the target URI is unknown, use `search_memory(..., include_session=true)` before guessing a path.
- Before `create_memory`, `update_memory`, `delete_memory`, or `add_alias`, read the target or the best matching candidate first.
- If `guard_action` is `NOOP`, stop the write, inspect `guard_target_uri` / `guard_target_id`, read the suggested target, then decide whether anything should change.

## Code and Validation

- Backend: `cd backend && .venv/bin/pytest tests -q`
- Frontend: `cd frontend && npm test && npm run build`
- Skill smoke: `python scripts/evaluate_memory_palace_skill.py`
- Live MCP e2e: `cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py`

## MCP Binding

- Native Windows: `backend/mcp_wrapper.py`
- macOS / Linux / `Git Bash` / `WSL`: `scripts/run_memory_palace_mcp_stdio.sh`
</content>
