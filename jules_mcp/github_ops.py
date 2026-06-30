"""GitHub pull request operations via the gh CLI."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from pydantic import BaseModel, ConfigDict


class PrStatus(BaseModel):
    """Merge readiness and CI status for a pull request."""

    model_config = ConfigDict(extra="forbid", strict=True)
    pr_url: str
    mergeable: str
    merge_state_status: str
    ci_passing: bool
    ci_summary: str


class MergeResult(BaseModel):
    """Result of a merge attempt."""

    model_config = ConfigDict(extra="forbid", strict=True)
    pr_url: str
    merged: bool
    message: str


_PASSING_STATES: frozenset[str] = frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})
_FAILING_STATES: frozenset[str] = frozenset({
    "FAILURE",
    "ERROR",
    "TIMED_OUT",
    "ACTION_REQUIRED",
    "CANCELLED",
    "STARTUP_FAILURE",
    "STALE",
})


def _run_gh(*args: str) -> str:
    """Execute a gh CLI command and return stdout, raising RuntimeError on failure."""
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"gh exited {result.returncode}")
    return result.stdout


def _ci_passing(rollup: list[dict[str, Any]]) -> tuple[bool, str]:
    """Determine CI pass/fail from a statusCheckRollup array."""
    if not rollup:
        return True, "no checks"

    failing: list[str] = []
    pending: list[str] = []

    for check in rollup:
        typename = check.get("__typename", "")
        name: str = check.get("name") or check.get("context") or "unknown"
        # CheckRun uses `conclusion`; StatusContext uses `state`
        raw_state = check.get("conclusion") if typename == "CheckRun" else check.get("state")
        state = (raw_state or "").upper()

        if state in _FAILING_STATES:
            failing.append(name)
        elif state not in _PASSING_STATES:
            pending.append(name)

    if failing:
        return False, f"failing: {', '.join(failing)}"
    if pending:
        return False, f"pending: {', '.join(pending)}"
    return True, "all checks passed"


def get_pr_status(pr_url: str) -> PrStatus:
    """Return merge readiness and CI status for a pull request."""
    raw = _run_gh(
        "pr", "view", pr_url,
        "--json", "mergeable,mergeStateStatus,statusCheckRollup",
    )
    data: dict[str, Any] = json.loads(raw)
    ci_ok, ci_summary = _ci_passing(data.get("statusCheckRollup") or [])
    return PrStatus(
        pr_url=pr_url,
        mergeable=data.get("mergeable", "UNKNOWN"),
        merge_state_status=data.get("mergeStateStatus", "UNKNOWN"),
        ci_passing=ci_ok,
        ci_summary=ci_summary,
    )


def merge_pr(pr_url: str, method: str = "squash") -> MergeResult:
    """Merge a pull request using the specified method (squash/merge/rebase)."""
    valid: frozenset[str] = frozenset({"squash", "merge", "rebase"})
    if method not in valid:
        return MergeResult(
            pr_url=pr_url,
            merged=False,
            message=f"invalid method '{method}': must be one of {sorted(valid)}",
        )
    try:
        _run_gh("pr", "merge", pr_url, f"--{method}", "--delete-branch")
        return MergeResult(pr_url=pr_url, merged=True, message="merged successfully")
    except RuntimeError as exc:
        return MergeResult(pr_url=pr_url, merged=False, message=str(exc))


def get_pr_diff(pr_url: str) -> str:
    """Return the full unified diff of a pull request."""
    return _run_gh("pr", "diff", pr_url)


def _run_git(repo_path: str, *args: str) -> str:
    """Execute a git command in repo_path and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git exited {result.returncode}")
    return result.stdout


def commit_and_push(
    repo_path: str,
    files: list[str],
    message: str,
    branch: str = "main",
) -> str:
    """Stage files, commit (if anything changed), and push to origin/branch."""
    _run_git(repo_path, "add", *files)
    status = _run_git(repo_path, "status", "--porcelain")
    if status.strip():
        _run_git(repo_path, "commit", "-m", message)
    _run_git(repo_path, "push", "origin", branch)
    return f"pushed to origin/{branch}"
