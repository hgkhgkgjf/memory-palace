# Memory Palace Documentation Center

> **Memory Palace** is a long-term memory system designed for AI coding assistants. Through MCP (Model Context Protocol), it provides a unified path for memory read/write, retrieval, review, and maintenance for Codex / Claude Code / Gemini CLI / OpenCode; for IDE hosts such as `Cursor / Windsurf / VSCode-host / Antigravity`, it is recommended to start with `docs/skills/IDE_HOSTS_EN.md`.
>
> License: MIT
>
> This section prioritizes the instructions that **users will actually need**.
>
> If you want the AI to walk you through installation, start with the standalone repo [`memory-palace-setup`](https://github.com/AGI-is-going-to-arrive/memory-palace-setup). The repository stance is: **prefer skills + MCP first, not MCP-only by default**.
>
> If you need additional verification of skill smoke tests or the real MCP call chain, you can run `python scripts/evaluate_memory_palace_skill.py` or `cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py`. They generate local summaries under `docs/skills/`, but those reports are not the primary entry documents. The current scripts also redact common secret-like values, local absolute paths, and session tokens in those reports, and use private file permissions where the host supports them. `evaluate_memory_palace_skill.py` now returns a non-zero exit code whenever any check is `FAIL`; `SKIP` / `PARTIAL` / `MANUAL` do not fail the process by themselves. If `codex exec` does not emit structured output before the smoke timeout, the `codex` item is reported as `PARTIAL` instead of blocking the whole run. In this round, `evaluate_memory_palace_mcp_e2e.py` also gained a re-exec guard so a local Python handoff does not re-enter repeatedly by accident.
>
> Also, A/B/C/D are better understood as different configuration profiles, not a seamless hot-switch button. Once you change embedding backend / model / dimension, be ready to re-check whether the existing index still matches; when the runtime detects a dimension mismatch, it asks for reindex instead of pretending the profile switch already succeeded.
>
> The frontend restores the saved language first. If there is no saved value, common Chinese browser languages are normalized to `zh-CN`; other first visits fall back to English. The language button in the upper-right corner still switches between English and Chinese with one click, and the browser remembers your choice.

> Current docs in this English set reflect this 2026-05-15 review session: backend `1382 passed / 22 skipped`, frontend `203 passed`, frontend typecheck/build, i18n audit, bundle budget, repo-local live MCP e2e, and focused Docker/profile/SSE/script contracts passed. `Profile B` keeps the project's shipped settings; `Profile C/D` runtime-injection contracts were checked with a 1024-dimension external embedding/reranker-style configuration and Docker loopback rewrite. The public A/B/C/D benchmark tables were not recalculated in this pass, and native Windows / native Linux host-runtime paths remain target-environment checks.

![System Architecture Diagram](images/系统架构图.png)

---

## 📖 Getting Started

| Document | Description |
|---|---|
| [`memory-palace-setup`](https://github.com/AGI-is-going-to-arrive/memory-palace-setup) | Standalone onboarding skill for AI-guided installation. After installing it, say: `Use $memory-palace-setup to install and configure Memory Palace step by step. Prefer skills + MCP.` |
| [GETTING_STARTED_EN.md](GETTING_STARTED_EN.md) | Get local development, GHCR image pull, and Docker running in 5 minutes, with example MCP client configurations |
| [DASHBOARD_GUIDE_EN.md](DASHBOARD_GUIDE_EN.md) | Explains every Dashboard button, field, and typical operation flow page by page |
| [skills/GETTING_STARTED_EN.md](skills/GETTING_STARTED_EN.md) | Connect the CLI-client skill + MCP path to the current repository for the first time |
| [TROUBLESHOOTING_EN.md](TROUBLESHOOTING_EN.md) | Troubleshooting for common issues such as startup failures, port conflicts, authentication failures, and search degradation |
| [SECURITY_AND_PRIVACY_EN.md](SECURITY_AND_PRIVACY_EN.md) | API Key secure configuration, privacy protection, and pre-sharing self-checks |

## 🔧 Core Documents

| Document | Description |
|---|---|
| [TECHNICAL_OVERVIEW_EN.md](TECHNICAL_OVERVIEW_EN.md) | Overview of the implementation structure and tech stack for the backend, frontend, MCP, and Docker |
| [TOOLS_EN.md](TOOLS_EN.md) | Inputs, outputs, return conventions, and degradation semantics of the 9 MCP tools |
| [DEPLOYMENT_PROFILES_EN.md](DEPLOYMENT_PROFILES_EN.md) | Configuration templates for the four A/B/C/D tiers, parameter tuning, and deployment methods |
| [GHCR_QUICKSTART_EN.md](GHCR_QUICKSTART_EN.md) | Shortest user path for GHCR prebuilt images |
| [GHCR_ACCEPTANCE_CHECKLIST_EN.md](GHCR_ACCEPTANCE_CHECKLIST_EN.md) | Minimal post-pull user acceptance checklist for GHCR images |
| [skills/SKILLS_QUICKSTART_EN.md](skills/SKILLS_QUICKSTART_EN.md) | Understand in one page how the CLI-client skill path is triggered, how MCP is configured, and how acceptance is verified |
| [changelog/post_release_hardening_2026-04-21_EN.md](changelog/post_release_hardening_2026-04-21_EN.md) | Post-release hardening follow-up for this session: MCP contract tightening, retrieval fallback semantics, snapshot recovery, and re-verification summary |
| [changelog/release_v3.7.1_2026-03-26_EN.md](changelog/release_v3.7.1_2026-03-26_EN.md) | Actual fixes, verification scope, and conservative boundaries for `v3.7.1` |
| [changelog/dashboard_i18n_2026-03-09_EN.md](changelog/dashboard_i18n_2026-03-09_EN.md) | Summary of the dashboard's default English setting, Chinese/English switching, screenshots, and verification |
| [changelog/ghcr_release_2026-03-11_EN.md](changelog/ghcr_release_2026-03-11_EN.md) | GHCR prebuilt image release notes and scope boundaries |

## 🧩 Skills and Clients

| Document | Description |
|---|---|
| [skills/MEMORY_PALACE_SKILLS_EN.md](skills/MEMORY_PALACE_SKILLS_EN.md) | Canonical `memory-palace` skill design, installation, and multi-CLI orchestration strategy |
| [skills/CLI_COMPATIBILITY_GUIDE_EN.md](skills/CLI_COMPATIBILITY_GUIDE_EN.md) | Recommended installation paths, verification methods, and known boundaries for each CLI |
| [skills/IDE_HOSTS_EN.md](skills/IDE_HOSTS_EN.md) | How IDE hosts such as Cursor / Windsurf / VSCode-host / Antigravity should connect to this repository |

> If you only want to get the service running first, start with the **GHCR prebuilt image** path in `GETTING_STARTED_EN.md`.
>
> If you also want to wire `Claude / Codex / Gemini / OpenCode / IDE hosts` into this repository, continue with the docs under `docs/skills/`. Docker starts the service side; it does not automatically rewrite the local skill / MCP configuration on your machine.

## 📊 Evaluation and Quality

| Document | Description |
|---|---|
| [EVALUATION_EN.md](EVALUATION_EN.md) | Public benchmark methodology, summary of key A/B/C/D metrics, and reproduction commands |

> Verification note: in this review session, backend `1382 passed / 22 skipped`, frontend `203 passed`, frontend typecheck/build, i18n audit, bundle budget, repo-local live MCP e2e, and the focused Docker/profile/SSE/script contracts passed. The public A/B/C/D benchmark tables were not recalculated in this pass, and native Windows / native Linux host runtime paths still keep explicit target-environment recheck boundaries.
