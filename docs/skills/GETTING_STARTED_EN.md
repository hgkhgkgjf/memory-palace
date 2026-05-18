# Memory Palace Skills Integration Guide

The previous content of this file has been merged into `SKILLS_QUICKSTART_EN.md` to avoid keeping the same step list in two documents.

Read next:

- Fastest way to wire `Claude / Codex / Gemini / OpenCode`: [`SKILLS_QUICKSTART_EN.md`](SKILLS_QUICKSTART_EN.md)
- Full per-CLI options and boundaries: [`CLI_COMPATIBILITY_GUIDE_EN.md`](CLI_COMPATIBILITY_GUIDE_EN.md)
- IDE hosts (`Cursor / Windsurf / VSCode-host / Antigravity`): [`IDE_HOSTS_EN.md`](IDE_HOSTS_EN.md)
- Skill design: [`MEMORY_PALACE_SKILLS_EN.md`](MEMORY_PALACE_SKILLS_EN.md)
- Docker / GHCR images only: [`docs/GHCR_QUICKSTART_EN.md`](../GHCR_QUICKSTART_EN.md)

If you are troubleshooting:

```bash
python scripts/sync_memory_palace_skill.py --check
python scripts/evaluate_memory_palace_skill.py
cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py
```

These three scripts generate `docs/skills/TRIGGER_SMOKE_REPORT.md` and `docs/skills/MCP_LIVE_E2E_REPORT.md` locally, which are excluded by `.gitignore` by default.
