"""Unit tests for jules_mcp.agents_md."""

from __future__ import annotations

from pathlib import Path

from jules_mcp.agents_md import build_agents_md, write_agents_md


class TestBuildAgentsMd:
    def test_returns_string(self) -> None:
        assert isinstance(build_agents_md(["project_a", "project_b"]), str)

    def test_includes_all_sub_projects(self) -> None:
        result = build_agents_md(["auth", "storage", "api"])
        assert "`auth`" in result
        assert "`storage`" in result
        assert "`api`" in result

    def test_default_integration_test_path(self) -> None:
        result = build_agents_md(["auth"])
        assert "tests/integration" in result

    def test_custom_integration_test_path(self) -> None:
        result = build_agents_md(["auth"], integration_test_path="e2e/tests")
        assert "e2e/tests" in result

    def test_merge_order_numbered_when_provided(self) -> None:
        result = build_agents_md(["auth", "api"], merge_order=["auth", "api"])
        assert "1. `auth`" in result
        assert "2. `api`" in result

    def test_merge_order_marks_first_as_merge_first(self) -> None:
        result = build_agents_md(["auth", "api"], merge_order=["auth", "api"])
        assert "merge first" in result

    def test_fallback_merge_order_when_none(self) -> None:
        result = build_agents_md(["auth"])
        assert "dependency order" in result

    def test_extra_rules_included(self) -> None:
        result = build_agents_md(["auth"], extra_rules=["Never use print()", "Avoid globals"])
        assert "Never use print()" in result
        assert "Avoid globals" in result

    def test_extra_rules_section_heading(self) -> None:
        result = build_agents_md(["auth"], extra_rules=["Rule A"])
        assert "Project-Specific Rules" in result

    def test_no_extra_rules_section_when_none(self) -> None:
        result = build_agents_md(["auth"], extra_rules=None)
        assert "Project-Specific Rules" not in result

    def test_quality_gates_present(self) -> None:
        result = build_agents_md(["auth"])
        for tool in ("ruff", "mypy", "bandit", "pytest"):
            assert tool in result
        assert "90" in result

    def test_conflict_resolution_present(self) -> None:
        result = build_agents_md(["auth"])
        assert "rebase" in result
        assert "conflict" in result.lower()

    def test_self_critic_section_present(self) -> None:
        result = build_agents_md(["auth"])
        assert "Self-Critic" in result
        assert "BONSAI" in result


class TestWriteAgentsMd:
    def test_writes_agents_md_to_repo_path(self, tmp_path: Path) -> None:
        write_agents_md(str(tmp_path), ["auth", "storage"])
        assert (tmp_path / "AGENTS.md").exists()

    def test_returns_content_string(self, tmp_path: Path) -> None:
        content = write_agents_md(str(tmp_path), ["auth"])
        assert isinstance(content, str)
        assert len(content) > 100

    def test_written_content_matches_returned(self, tmp_path: Path) -> None:
        content = write_agents_md(str(tmp_path), ["auth"])
        written = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
        assert content == written

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        (tmp_path / "AGENTS.md").write_text("old content", encoding="utf-8")
        write_agents_md(str(tmp_path), ["new_project"])
        written = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
        assert "new_project" in written
        assert "old content" not in written

    def test_sub_projects_appear_in_written_file(self, tmp_path: Path) -> None:
        write_agents_md(str(tmp_path), ["auth", "storage"])
        written = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
        assert "`auth`" in written
        assert "`storage`" in written
