"""Unit tests for jules_mcp.prompt."""

from __future__ import annotations

import importlib
import json

import pytest

import jules_mcp.prompt as prompt_module
from jules_mcp.prompt import _DEFAULT_RULES, build_enforced_prompt


class TestBuildEnforcedPrompt:
    def test_contains_user_task(self) -> None:
        result = build_enforced_prompt("add logging to main.py")
        assert "add logging to main.py" in result

    def test_rules_prepended_before_task(self) -> None:
        result = build_enforced_prompt("my task")
        rules_pos = result.index("Mandatory Quality Rules")
        task_pos = result.index("my task")
        assert rules_pos < task_pos

    def test_all_default_rules_present(self) -> None:
        result = build_enforced_prompt("x")
        for rule in _DEFAULT_RULES:
            assert rule[:40] in result

    def test_rules_are_numbered(self) -> None:
        result = build_enforced_prompt("x")
        assert "1." in result
        assert "2." in result

    def test_task_section_header(self) -> None:
        result = build_enforced_prompt("write tests")
        assert "## Task" in result
        assert "## Mandatory Quality Rules" in result

    def test_custom_rules_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        custom = ["Rule A", "Rule B"]
        monkeypatch.setenv("JULES_QUALITY_RULES", json.dumps(custom))
        importlib.reload(prompt_module)
        result = build_enforced_prompt("task")
        assert "Rule A" in result
        assert "Rule B" in result
        importlib.reload(prompt_module)  # restore defaults

    def test_invalid_json_env_falls_back_to_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JULES_QUALITY_RULES", "not-json{{{")
        importlib.reload(prompt_module)
        result = build_enforced_prompt("task")
        for rule in _DEFAULT_RULES:
            assert rule[:40] in result
        importlib.reload(prompt_module)

    def test_non_array_json_falls_back_to_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JULES_QUALITY_RULES", json.dumps({"key": "value"}))
        importlib.reload(prompt_module)
        result = build_enforced_prompt("task")
        for rule in _DEFAULT_RULES:
            assert rule[:40] in result
        importlib.reload(prompt_module)
