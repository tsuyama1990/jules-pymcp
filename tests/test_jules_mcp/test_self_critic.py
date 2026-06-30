"""Unit tests for jules_mcp.self_critic."""

from __future__ import annotations

from jules_mcp.self_critic import build_self_critic_prompt


class TestBuildSelfCriticPrompt:
    def test_returns_string(self) -> None:
        assert isinstance(build_self_critic_prompt(), str)

    def test_contains_self_correction_instruction(self) -> None:
        assert "FIX THE CODE YOURSELF" in build_self_critic_prompt()

    def test_contains_dry_section(self) -> None:
        assert "DRY" in build_self_critic_prompt()

    def test_contains_all_solid_principles(self) -> None:
        result = build_self_critic_prompt()
        principles = (
            "Single Responsibility", "Open/Closed", "Liskov",
            "Interface Segregation", "Dependency Inversion",
        )
        for principle in principles:
            assert principle in result, f"Missing SOLID principle: {principle}"

    def test_contains_bonsai_phases(self) -> None:
        result = build_self_critic_prompt()
        for phase in ("Pruning", "Shaping", "Potting", "Finishing"):
            assert phase in result, f"Missing BONSAI phase: {phase}"

    def test_contains_coverage_requirement(self) -> None:
        result = build_self_critic_prompt()
        assert "90" in result
        assert "cov" in result

    def test_contains_static_checks(self) -> None:
        result = build_self_critic_prompt()
        assert "ruff" in result
        assert "mypy" in result
        assert "pytest" in result

    def test_contains_bandit(self) -> None:
        assert "bandit" in build_self_critic_prompt()

    def test_contains_mutation_testing(self) -> None:
        assert "mutmut" in build_self_critic_prompt()

    def test_contains_critical_loop_rule(self) -> None:
        assert "CRITICAL LOOP RULE" in build_self_critic_prompt()

    def test_thinking_block_required(self) -> None:
        assert "<thought>" in build_self_critic_prompt()
