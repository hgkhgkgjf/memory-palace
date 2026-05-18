# Memory Palace Skills 接入指南

本文件之前的内容已经合并到 `SKILLS_QUICKSTART.md`，避免在多份文档里维护重复的步骤。

继续往下读：

- 想最快接通 `Claude / Codex / Gemini / OpenCode`：看 [`SKILLS_QUICKSTART.md`](SKILLS_QUICKSTART.md)
- 想看各 CLI 的完整选项与边界：看 [`CLI_COMPATIBILITY_GUIDE.md`](CLI_COMPATIBILITY_GUIDE.md)
- 想接入 IDE 宿主（`Cursor / Windsurf / VSCode-host / Antigravity`）：看 [`IDE_HOSTS.md`](IDE_HOSTS.md)
- 想看 skill 设计：看 [`MEMORY_PALACE_SKILLS.md`](MEMORY_PALACE_SKILLS.md)
- 只想跑 Docker / GHCR 镜像：看 [`docs/GHCR_QUICKSTART.md`](../GHCR_QUICKSTART.md)

如果你正在排障：

```bash
python scripts/sync_memory_palace_skill.py --check
python scripts/evaluate_memory_palace_skill.py
cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py
```

三条脚本会在本地生成 `docs/skills/TRIGGER_SMOKE_REPORT.md` 和 `docs/skills/MCP_LIVE_E2E_REPORT.md`，默认被 `.gitignore` 排除。
