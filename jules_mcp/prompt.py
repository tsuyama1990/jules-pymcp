"""Deterministic prompt enforcement — injects quality rules into every Jules task."""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_DEFAULT_RULES: list[str] = [
    # Static analysis
    "All Python code must pass `ruff check --select ALL`"
    " with only project-level ignores in pyproject.toml.",
    "All Python code must pass `mypy --strict` with zero errors."
    " No `type: ignore` unless accompanied by an explanation comment.",
    # Typing
    "Every function and method must have complete type annotations"
    " on all parameters and return values.",
    "Do not use `Any` unless strictly necessary."
    " Every use of `Any` must have an explanation comment.",
    # Development order — enforced sequencing
    "STEP 1 — BLUEPRINT: Before writing any code, produce a written design"
    " documenting data flow, module boundaries, and key interfaces"
    " as a comment block or docstring.",
    "STEP 2 — CONTRACT (CDD): Define all data boundaries as Pydantic models"
    " with `model_config = ConfigDict(extra='forbid', strict=True)`."
    " No raw dicts at module boundaries.",
    "STEP 3 — TESTS FIRST (TDD): Write tests before implementation in this order:"
    " (a) integration tests, (b) unit tests, (c) E2E tests."
    " Tests must be written to fail before the implementation exists.",
    "STEP 4 — IMPLEMENTATION: Write the implementation that makes the tests pass."
    " Do not write implementation code before tests exist.",
    # Test coverage — non-negotiable
    "Every new public function must have at least one pytest test"
    " covering a happy path and at least one unhappy path (error/edge case).",
    "Run `pytest --cov --cov-report=term-missing --cov-fail-under=90` and confirm"
    " overall line coverage is ≥ 90 %. Branch coverage must also be checked"
    " with `--cov-branch`. Any uncovered branch must be explained or tested.",
    "For every new module, aim for 100 % line + branch coverage."
    " Anything below 90 % is a hard failure — add tests, do not raise the ignore threshold.",
    # Code hygiene
    "Use `pathlib.Path` instead of `os.path` for all file operations.",
    "No TODO, FIXME, empty function bodies (`pass`/`...`),"
    " or placeholder log outputs in submitted code.",
    "No hardcoded paths, secrets, magic numbers, or magic strings"
    " — all config via Pydantic settings or a dedicated config module.",
]


def _load_rules() -> list[str]:
    raw = os.getenv("JULES_QUALITY_RULES")
    if not raw:
        return _DEFAULT_RULES
    try:
        parsed: object = json.loads(raw)
        if isinstance(parsed, list) and all(isinstance(r, str) for r in parsed):
            return parsed
        logger.warning("JULES_QUALITY_RULES is not a JSON string array — using defaults.")
    except json.JSONDecodeError:
        logger.warning("Failed to parse JULES_QUALITY_RULES JSON — using defaults.")
    return _DEFAULT_RULES


_RULES: list[str] = _load_rules()


def build_enforced_prompt(
    user_prompt: str,
    acceptance_criteria: list[str] | None = None,
) -> str:
    """Wrap a user prompt with mandatory quality rules and optional acceptance criteria.

    Rules are placed before the task so Jules reads constraints before intent.
    Acceptance criteria appear as a checklist Jules must satisfy before opening a PR.

    Args:
        user_prompt: The original task description from the caller.
        acceptance_criteria: Scenario-level pass/fail conditions for this specific task.

    Returns:
        A prompt string with quality rules and acceptance criteria prepended.

    """
    numbered = "\n".join(f"{i + 1}. {rule}" for i, rule in enumerate(_RULES))
    criteria_section = ""
    if acceptance_criteria:
        checklist = "\n".join(f"- [ ] {c}" for c in acceptance_criteria)
        header = "## Acceptance Criteria (all boxes must be checked before opening PR)"
        criteria_section = f"\n\n{header}\n{checklist}"
    return (
        f"## Mandatory Quality Rules (non-negotiable)\n{numbered}"
        f"{criteria_section}"
        f"\n\n## Task\n{user_prompt}"
    )
