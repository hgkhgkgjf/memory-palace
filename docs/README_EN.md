# Memory Palace Documentation Center

> **Memory Palace** is a long-term memory system designed for AI coding assistants. Through MCP (Model Context Protocol), it provides a unified path for memory read/write, retrieval, review, and maintenance across Codex / Claude Code / Gemini CLI / OpenCode. For IDE hosts such as `Cursor / Windsurf / VSCode-host / Antigravity`, start with `docs/skills/IDE_HOSTS_EN.md`.
>
> License: MIT
>
> If you want the AI to walk you through installation, start with the standalone repo [`memory-palace-setup`](https://github.com/AGI-is-going-to-arrive/memory-palace-setup). The repository stance is: **prefer skills + MCP first, not MCP-only by default**.
>
> A/B/C/D are different configuration profiles, not a seamless hot-switch button. Once you change embedding backend / model / dimension, re-check whether the existing index still matches; the runtime asks for reindex on dimension mismatch instead of pretending the switch already succeeded.
>
> The frontend restores the saved language first. With no saved value, Chinese browser languages map to `zh-CN`; others default to English. The top-right language button toggles between English and Chinese, and the choice is persisted.

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
| [SECURITY_AND_PRIVACY_EN.md](SECURITY_AND_PRIVACY_EN.md) | API key secure configuration, privacy protection, and pre-sharing self-checks |

## 🔧 Core Documents

| Document | Description |
|---|---|
| [TECHNICAL_OVERVIEW_EN.md](TECHNICAL_OVERVIEW_EN.md) | Overview of the implementation structure and tech stack for the backend, frontend, MCP, and Docker |
| [TOOLS_EN.md](TOOLS_EN.md) | Inputs, outputs, return conventions, and degradation semantics of the 9 MCP tools |
| [DEPLOYMENT_PROFILES_EN.md](DEPLOYMENT_PROFILES_EN.md) | Configuration templates for the four A/B/C/D tiers, parameter tuning, and deployment methods |
| [GHCR_QUICKSTART_EN.md](GHCR_QUICKSTART_EN.md) | Shortest user path for GHCR prebuilt images |
| [GHCR_ACCEPTANCE_CHECKLIST_EN.md](GHCR_ACCEPTANCE_CHECKLIST_EN.md) | Minimal post-pull user acceptance checklist for GHCR images |
| [skills/SKILLS_QUICKSTART_EN.md](skills/SKILLS_QUICKSTART_EN.md) | One page on how the CLI-client skill path is triggered, how MCP is configured, and how acceptance is verified |
| [changelog/post_release_hardening_2026-04-21_EN.md](changelog/post_release_hardening_2026-04-21_EN.md) | Hardening follow-up: MCP contract tightening, retrieval fallback semantics, snapshot recovery |
| [changelog/release_v3.7.1_2026-03-26_EN.md](changelog/release_v3.7.1_2026-03-26_EN.md) | Actual fixes and verification scope for `v3.7.1` |
| [changelog/ghcr_release_2026-03-11_EN.md](changelog/ghcr_release_2026-03-11_EN.md) | GHCR prebuilt image release notes |

## 🧩 Skills and Clients

| Document | Description |
|---|---|
| [skills/MEMORY_PALACE_SKILLS_EN.md](skills/MEMORY_PALACE_SKILLS_EN.md) | Canonical `memory-palace` skill design, installation, and multi-CLI orchestration strategy |
| [skills/CLI_COMPATIBILITY_GUIDE_EN.md](skills/CLI_COMPATIBILITY_GUIDE_EN.md) | Recommended installation paths, verification methods, and known boundaries for each CLI |
| [skills/IDE_HOSTS_EN.md](skills/IDE_HOSTS_EN.md) | How IDE hosts such as Cursor / Windsurf / VSCode-host / Antigravity connect to this repository |

> If you only want the service running first, start with the **GHCR prebuilt image** path in `GETTING_STARTED_EN.md`.
>
> If you also want to wire `Claude / Codex / Gemini / OpenCode / IDE hosts` into this repository, continue with `docs/skills/`. Docker starts the service side only; it does not rewrite local skill / MCP configuration on your machine.

## 📊 Evaluation and Quality

| Document | Description |
|---|---|
| [EVALUATION_EN.md](EVALUATION_EN.md) | Public benchmark methodology, summary of key A/B/C/D metrics, and reproduction commands |
</content>
