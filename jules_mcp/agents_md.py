"""Generate AGENTS.md for a GitHub repository."""

from __future__ import annotations

from pathlib import Path

_TEMPLATE = """\
# AGENTS.md — Jules Orchestration Rules

This file is read by Jules (Google's autonomous coding agent) before starting any task.

## Project Structure
{sub_projects_section}

## Integration Test Contracts
Integration tests live at `{integration_test_path}` and define the interface contracts
between sub-projects. **All integration tests must pass before any PR is merged.**

## Merge Order
{merge_order_section}

## Quality Gates (enforced on every PR — non-negotiable)
1. `ruff check --select ALL` must pass (zero warnings)
2. `mypy --strict` must pass
3. `bandit -r .` must pass (no medium+ severity issues)
4. `pytest --cov --cov-branch --cov-fail-under=90` must pass
5. No hardcoded secrets, API keys, or environment-specific values
6. Blueprint → TDD → CDD order: design first, tests second, implementation third

## Branch Convention
- Branch name: `jules/<task-label>` (e.g., `jules/auth-module`)
- One PR per Jules session
- Base branch: `main`

## Conflict Resolution
If your PR has merge conflicts:
1. Fetch latest main: `git fetch origin main`
2. Rebase: `git rebase origin/main`
3. Resolve conflicts — preserve the integration test contracts
4. Force-push: `git push --force-with-lease`

## Self-Critic Review
After opening a PR you will receive a self-critic review prompt.
Act on it: fix DRY/SOLID violations, run BONSAI cleanup, and ensure all
static checks pass. Fix the code — do not just report issues.
{extra_rules_section}"""


def build_agents_md(
    sub_projects: list[str],
    integration_test_path: str = "tests/integration",
    merge_order: list[str] | None = None,
    extra_rules: list[str] | None = None,
) -> str:
    """Return AGENTS.md content as a string."""
    sub_projects_section = "\n".join(f"- `{p}`" for p in sub_projects)

    if merge_order:
        lines = []
        for i, p in enumerate(merge_order):
            suffix = " (merge first)" if i == 0 else ""
            lines.append(f"{i + 1}. `{p}`{suffix}")
        merge_order_section = "\n".join(lines)
    else:
        merge_order_section = (
            "Merge in dependency order: leaf modules first, integrations last. "
            "Confirm ordering with Claude before merging."
        )

    extra_rules_section = ""
    if extra_rules:
        rules_text = "\n".join(f"- {r}" for r in extra_rules)
        extra_rules_section = f"\n## Project-Specific Rules\n{rules_text}\n"

    return _TEMPLATE.format(
        sub_projects_section=sub_projects_section,
        integration_test_path=integration_test_path,
        merge_order_section=merge_order_section,
        extra_rules_section=extra_rules_section,
    )


def write_agents_md(
    repo_path: str,
    sub_projects: list[str],
    integration_test_path: str = "tests/integration",
    merge_order: list[str] | None = None,
    extra_rules: list[str] | None = None,
) -> str:
    """Write AGENTS.md to ``repo_path/AGENTS.md`` and return the written content."""
    content = build_agents_md(
        sub_projects=sub_projects,
        integration_test_path=integration_test_path,
        merge_order=merge_order,
        extra_rules=extra_rules,
    )
    path = Path(repo_path) / "AGENTS.md"
    path.write_text(content, encoding="utf-8")
    return content
