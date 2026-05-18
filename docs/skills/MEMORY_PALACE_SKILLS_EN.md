# Memory Palace Skills Design

Structural overview of the `memory-palace` skill system. If you only want to wire up clients, see [`SKILLS_QUICKSTART_EN.md`](SKILLS_QUICKSTART_EN.md).

---

## 1. Single Source of Truth

The canonical bundle lives at:

```text
docs/skills/memory-palace/
├── SKILL.md
├── references/
│   ├── mcp-workflow.md
│   └── trigger-samples.md
├── agents/
│   └── openai.yaml
└── variants/
    ├── antigravity/
    │   └── global_workflows/
    │       └── memory-palace.md
    └── gemini/
        ├── SKILL.md
        └── memory-palace-overrides.toml
```

Distribution and installation:

- `scripts/sync_memory_palace_skill.py` - Distributes the canonical bundle to CLI mirror directories
- `scripts/install_skill.py` - Installs to workspace or user directories, optionally with `--with-mcp`
- `scripts/render_ide_host_config.py` - Renders MCP config snippets for IDE hosts

Mirror directories like `.claude / .codex / .gemini / .opencode` are local artifacts generated after sync/install and are not part of the public repository.

---

## 2. Alignment with Claude Skills Specification

- **Structure**: Standard `skill-name/SKILL.md` bundle layout
- **Trigger contract**: `description` covers both "what it does" and "when to use it"
- **Progressive loading**: Main `SKILL.md` stays concise; tool details live in `references/`
- **Cross-client distribution**: Claude / Codex / OpenCode use mirrors; Gemini uses a variant

Boundary: validation is engineering-style smoke / e2e rather than `skill-creator`'s `evals.json` + automatic description optimization loop.

---

## 3. Directory Responsibilities

| Path | Responsibility |
|---|---|
| `docs/skills/memory-palace/SKILL.md` | Defines when to trigger, the shortest safe default flow, hard constraints |
| `docs/skills/memory-palace/variants/gemini/SKILL.md` | Shorter, stronger-trigger Gemini variant; anchors first move / NOOP / trigger sample path |
| `docs/skills/memory-palace/variants/gemini/memory-palace-overrides.toml` | Gemini policy override: switches MCP tool to the `mcpName = "memory-palace"` format to avoid deprecated `__` syntax warnings |
| `docs/skills/memory-palace/references/mcp-workflow.md` | Minimum safe workflow for all 9 MCP tools + recall / write / compact / rebuild ordering |
| `docs/skills/memory-palace/references/trigger-samples.md` | Stable should-trigger / should-not-trigger / borderline prompt set |
| `docs/skills/memory-palace/variants/antigravity/global_workflows/memory-palace.md` | Antigravity-specific workflow projection (compatibility layer) |

---

## 4. Design Principles

1. `description` is the trigger contract
2. The `SKILL.md` body keeps only execution steps, hard constraints, and failure handling
3. Tool details belong in `references/`
4. Repository scripts handle distribution and validation; users do not hand-copy skills
5. Runtime references prioritize repo-visible canonical paths (do not rely on hidden mirrors being readable)
6. Check not only "skill is discoverable" but also "MCP is bound to the current project"

---

## 5. Default Workflow

### Boot

Before the first real operation:

```python
read_memory("system://boot")
```

### Recall

When the URI is uncertain:

```python
search_memory(query="...", include_session=True)
```

When the URI is already explicit, prefer `read_memory(uri)` directly instead of bouncing through `search_memory(...)`.

### Read before write

Read the target or candidate target before `create_memory` / `update_memory` / `delete_memory` / `add_alias`.

Defaults:

- Provide an explicit `title` for `create_memory` when creating
- Use the `update_memory` patch for standard updates
- Use `append` only when truly appending new content

### Guard-aware write

Do not ignore these fields:

- `guard_action`
- `guard_reason`
- `guard_method`
- `guard_target_uri`
- `guard_target_id`

Rules:

- `NOOP` -> Stop writing; inspect `guard_target_uri / guard_target_id` and read the suggested target before deciding
- `UPDATE` -> Inspect the suggested target first; if still in pre-write decision, usually switch to `update_memory`
- `DELETE` -> Confirm the old memory really should be replaced

### Compact / Recover

- Long, noisy sessions -> `compact_context(force=false)`
- Retrieval degradation -> `index_status()`, and if needed `rebuild_index(wait=true)`

---

## 6. Trigger Design

`description` must cover:

- English: memory / remember / recall / long-term memory
- Chinese: 记住, 回忆, 长期记忆, 跨会话, 压缩上下文, 重建索引
- Explicit mentions of `system://boot`, `search_memory`, `compact_context`, `rebuild_index`
- User asking "should this be `create` or `update`"
- Maintenance, rollback, or index recovery actions

Boundaries:

- Not for general README / UI / benchmark / coding tasks
- Not for generalized "skill design" work unrelated to the Memory Palace MCP

`references/trigger-samples.md` provides a should-trigger / should-not-trigger / borderline sample set so `description` iterations have a fixed control group.

---

## 7. Maintenance Order

When iterating on the skill, follow this order:

1. Adjust the trigger description
2. Adjust the `SKILL.md` body
3. Run `python scripts/sync_memory_palace_skill.py --check`
4. Run `python scripts/evaluate_memory_palace_skill.py`
5. Run `cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py`
6. Run `bash scripts/pre_publish_check.sh`
7. Expand `references/` only when really necessary

Do not return to the old "write a long doc, ask users to manually copy it into a skill" pattern.

---

## 8. Gemini Compatibility Notes

The CLI can discover and load the `memory-palace` skill, but the runtime file-reading strategy may skip hidden mirror directories (e.g. `.gemini/skills/...`). Therefore `SKILL.md` consistently references `docs/skills/memory-palace/...` for files instead of relying on hidden mirrors being readable.

For more reliable Gemini smoke tests:

```bash
gemini -m gemini-3-flash-preview \
  -p '<your prompt>' \
  --output-format text \
  --allowed-tools activate_skill,read_file
```

This is an empirical path, not a universal guarantee.
