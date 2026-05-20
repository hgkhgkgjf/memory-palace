import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _extract_section_numbers(path: Path, *, chapter: str) -> list[str]:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^### ({re.escape(chapter)}\.\d+)\b", re.MULTILINE)
    return pattern.findall(text)


def test_getting_started_section_four_numbers_are_unique_and_ordered() -> None:
    assert _extract_section_numbers(
        PROJECT_ROOT / "docs" / "GETTING_STARTED.md",
        chapter="4",
    ) == ["4.1", "4.2", "4.3"]
    assert _extract_section_numbers(
        PROJECT_ROOT / "docs" / "GETTING_STARTED_EN.md",
        chapter="4",
    ) == ["4.1", "4.2", "4.3"]


def test_getting_started_notes_local_shell_database_autofill() -> None:
    zh_text = (PROJECT_ROOT / "docs" / "GETTING_STARTED.md").read_text(encoding="utf-8")
    en_text = (PROJECT_ROOT / "docs" / "GETTING_STARTED_EN.md").read_text(
        encoding="utf-8"
    )

    assert "包括 `/Users/...` 和 `/home/...`" in zh_text
    assert "including `/Users/...` and `/home/...`" in en_text


def test_readme_benchmark_reproduction_note_matches_repo_layout() -> None:
    readme_en = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    readme_zh = (PROJECT_ROOT / "README_CN.md").read_text(encoding="utf-8")

    assert "`backend/tests/benchmark/`" in readme_en
    assert "`backend/tests/benchmark/`" in readme_zh


def test_skill_install_docs_use_user_scope_as_the_default_recommendation() -> None:
    readme_en = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    readme_zh = (PROJECT_ROOT / "README_CN.md").read_text(encoding="utf-8")
    cli_guide_en = (
        PROJECT_ROOT / "docs" / "skills" / "CLI_COMPATIBILITY_GUIDE_EN.md"
    ).read_text(encoding="utf-8")
    cli_guide_zh = (
        PROJECT_ROOT / "docs" / "skills" / "CLI_COMPATIBILITY_GUIDE.md"
    ).read_text(encoding="utf-8")

    assert "User-scope install is the stable default on fresh machines" in readme_en
    assert "新机器上更稳的默认方案是 `user` 级安装" in readme_zh
    assert "### User-scope install (recommended default)" in cli_guide_en
    assert "`Codex / OpenCode` do not get a stable MCP binding under workspace scope; user-scope is their primary path." in cli_guide_en
    assert "### user-scope 安装（推荐默认）" in cli_guide_zh
    assert "`Codex / OpenCode` 在 workspace scope 下不会写 MCP 配置，user-scope 才是它们的主路径。" in cli_guide_zh


def test_hygiene_docs_list_root_pytest_cache_and_only_current_local_reports() -> None:
    zh_security = (PROJECT_ROOT / "docs" / "SECURITY_AND_PRIVACY.md").read_text(
        encoding="utf-8"
    )
    en_security = (
        PROJECT_ROOT / "docs" / "SECURITY_AND_PRIVACY_EN.md"
    ).read_text(encoding="utf-8")

    assert "`.pytest_cache/`、`backend/.pytest_cache/`" in zh_security
    assert "`.pytest_cache/`, `backend/.pytest_cache/`" in en_security
    assert "docs/skills/CLAUDE_SKILLS_AUDIT.md" not in zh_security
    assert "docs/skills/CLAUDE_SKILLS_AUDIT.md" not in en_security


def test_docs_describe_platform_specific_repo_local_mcp_wrappers_and_setup_auto_open_gate() -> None:
    readme_en = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    readme_zh = (PROJECT_ROOT / "README_CN.md").read_text(encoding="utf-8")
    zh_getting_started = (PROJECT_ROOT / "docs" / "GETTING_STARTED.md").read_text(
        encoding="utf-8"
    )
    en_getting_started = (
        PROJECT_ROOT / "docs" / "GETTING_STARTED_EN.md"
    ).read_text(encoding="utf-8")

    assert "neither runtime Dashboard auth nor stored browser Dashboard auth is available" in readme_en
    assert "既没有已保存的 Dashboard 鉴权，也没有运行时注入的 Dashboard 鉴权" in readme_zh
    assert "原生 Windows：`python backend/mcp_wrapper.py`" in zh_getting_started
    assert "macOS / Linux / Git Bash / WSL：`bash scripts/run_memory_palace_mcp_stdio.sh`" in zh_getting_started
    assert "native Windows: `python backend/mcp_wrapper.py`" in en_getting_started
    assert "macOS / Linux / Git Bash / WSL: `bash scripts/run_memory_palace_mcp_stdio.sh`" in en_getting_started


def test_docs_describe_shell_wrapper_utf8_defaults() -> None:
    readme_en = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    readme_zh = (PROJECT_ROOT / "README_CN.md").read_text(encoding="utf-8")
    troubleshooting_en = (
        PROJECT_ROOT / "docs" / "TROUBLESHOOTING_EN.md"
    ).read_text(encoding="utf-8")
    troubleshooting_zh = (
        PROJECT_ROOT / "docs" / "TROUBLESHOOTING.md"
    ).read_text(encoding="utf-8")

    assert "PYTHONIOENCODING=utf-8" in readme_en
    assert "PYTHONUTF8=1" in readme_en
    assert "PYTHONIOENCODING=utf-8" in readme_zh
    assert "PYTHONUTF8=1" in readme_zh
    assert "PYTHONIOENCODING=utf-8" in troubleshooting_en
    assert "PYTHONUTF8=1" in troubleshooting_en
    assert "PYTHONIOENCODING=utf-8" in troubleshooting_zh
    assert "PYTHONUTF8=1" in troubleshooting_zh


def test_docs_keep_direct_api_smoke_examples_aligned_with_auth_and_dimensions() -> None:
    zh_profiles = (PROJECT_ROOT / "docs" / "DEPLOYMENT_PROFILES.md").read_text(
        encoding="utf-8"
    )
    en_profiles = (
        PROJECT_ROOT / "docs" / "DEPLOYMENT_PROFILES_EN.md"
    ).read_text(encoding="utf-8")
    zh_troubleshooting = (
        PROJECT_ROOT / "docs" / "TROUBLESHOOTING.md"
    ).read_text(encoding="utf-8")
    en_troubleshooting = (
        PROJECT_ROOT / "docs" / "TROUBLESHOOTING_EN.md"
    ).read_text(encoding="utf-8")

    for text in (zh_profiles, en_profiles, zh_troubleshooting, en_troubleshooting):
        assert 'Authorization: Bearer <RETRIEVAL_EMBEDDING_API_KEY>' in text
        assert '"dimensions":<RETRIEVAL_EMBEDDING_DIM>' in text
        assert 'Authorization: Bearer <RETRIEVAL_RERANKER_API_KEY>' in text


def test_docs_keep_wal_network_bind_mount_safety_boundary_consistent() -> None:
    readme_en = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    readme_zh = (PROJECT_ROOT / "README_CN.md").read_text(encoding="utf-8")
    zh_getting_started = (PROJECT_ROOT / "docs" / "GETTING_STARTED.md").read_text(
        encoding="utf-8"
    )
    en_getting_started = (
        PROJECT_ROOT / "docs" / "GETTING_STARTED_EN.md"
    ).read_text(encoding="utf-8")
    zh_profiles = (PROJECT_ROOT / "docs" / "DEPLOYMENT_PROFILES.md").read_text(
        encoding="utf-8"
    )
    en_profiles = (
        PROJECT_ROOT / "docs" / "DEPLOYMENT_PROFILES_EN.md"
    ).read_text(encoding="utf-8")
    zh_troubleshooting = (
        PROJECT_ROOT / "docs" / "TROUBLESHOOTING.md"
    ).read_text(encoding="utf-8")
    en_troubleshooting = (
        PROJECT_ROOT / "docs" / "TROUBLESHOOTING_EN.md"
    ).read_text(encoding="utf-8")

    for text in (readme_en, en_getting_started, en_profiles, en_troubleshooting):
        assert "named volume" in text or "named-volume" in text
        assert "NFS/CIFS/SMB" in text
        assert "MEMORY_PALACE_DOCKER_WAL_ENABLED=false" in text
        assert "MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete" in text
        assert (
            "manual `docker compose up`" in text
            or "run `docker compose up` manually" in text
            or "bypass the one-click script" in text
        )

    for text in (readme_zh, zh_getting_started, zh_profiles, zh_troubleshooting):
        assert "named volume" in text
        assert "NFS/CIFS/SMB" in text
        assert "MEMORY_PALACE_DOCKER_WAL_ENABLED=false" in text
        assert "MEMORY_PALACE_DOCKER_JOURNAL_MODE=delete" in text
        assert "手动 `docker compose up`" in text or "绕过一键脚本" in text


def test_docs_keep_embedding_dim_codex_partial_and_profile_c_guidance_consistent() -> None:
    zh_getting_started = (PROJECT_ROOT / "docs" / "GETTING_STARTED.md").read_text(
        encoding="utf-8"
    )
    en_getting_started = (
        PROJECT_ROOT / "docs" / "GETTING_STARTED_EN.md"
    ).read_text(encoding="utf-8")
    quickstart_zh = (
        PROJECT_ROOT / "docs" / "skills" / "SKILLS_QUICKSTART.md"
    ).read_text(encoding="utf-8")
    quickstart_en = (
        PROJECT_ROOT / "docs" / "skills" / "SKILLS_QUICKSTART_EN.md"
    ).read_text(encoding="utf-8")
    profiles_zh = (
        PROJECT_ROOT / "docs" / "DEPLOYMENT_PROFILES.md"
    ).read_text(encoding="utf-8")
    profiles_en = (
        PROJECT_ROOT / "docs" / "DEPLOYMENT_PROFILES_EN.md"
    ).read_text(encoding="utf-8")

    assert "默认模板值；切到远端 backend 时必须由你填写 provider 实际维度" in zh_getting_started
    assert "default template value; you must provide the provider's real dimension for remote backends" in en_getting_started
    assert "`PARTIAL`" in quickstart_zh
    assert "`PARTIAL`" in quickstart_en
    assert "都能通过" not in quickstart_zh
    assert "both `mcp_bindings` and `Codex smoke` passed" not in quickstart_en
    assert "仓库自带的 `profile-c` 模板默认仍会把 Reranker 一起打开" in profiles_zh
    assert "the shipped `profile-c` template still enables the Reranker by default" in profiles_en
    assert "RRF 与 MMR 在 C/D 模板中保持关闭" in profiles_zh
    assert "RRF and MMR remain disabled in the C/D templates" in profiles_en
    assert "不再默认替你补 `1024`" in zh_getting_started
    assert "no longer auto-fills `1024` for you" in en_getting_started


def test_docs_keep_report_override_guidance_consistent() -> None:
    readme_zh = (PROJECT_ROOT / "README_CN.md").read_text(encoding="utf-8")
    readme_en = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    skill_readme_zh = (
        PROJECT_ROOT / "docs" / "skills" / "README.md"
    ).read_text(encoding="utf-8")
    skill_readme_en = (
        PROJECT_ROOT / "docs" / "skills" / "README_EN.md"
    ).read_text(encoding="utf-8")
    skill_getting_started_zh = (
        PROJECT_ROOT / "docs" / "skills" / "GETTING_STARTED.md"
    ).read_text(encoding="utf-8")
    skill_getting_started_en = (
        PROJECT_ROOT / "docs" / "skills" / "GETTING_STARTED_EN.md"
    ).read_text(encoding="utf-8")
    quickstart_zh = (
        PROJECT_ROOT / "docs" / "skills" / "SKILLS_QUICKSTART.md"
    ).read_text(encoding="utf-8")
    quickstart_en = (
        PROJECT_ROOT / "docs" / "skills" / "SKILLS_QUICKSTART_EN.md"
    ).read_text(encoding="utf-8")

    assert "合并到 `SKILLS_QUICKSTART.md`" in skill_getting_started_zh
    assert "merged into `SKILLS_QUICKSTART_EN.md`" in skill_getting_started_en

    for text in (readme_zh, skill_readme_zh, quickstart_zh):
        assert "memory-palace-reports" in text
        assert "仓库外的绝对路径" in text
        assert "改写到别的本地路径" not in text

    for text in (readme_en, skill_readme_en, quickstart_en):
        assert "memory-palace-reports" in text
        assert "outside the repository" in text or "outside the repo" in text
        assert "write the reports to another local path" not in text
