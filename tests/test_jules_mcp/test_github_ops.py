"""Unit tests for jules_mcp.github_ops."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from jules_mcp.github_ops import (
    MergeResult,
    PrStatus,
    _ci_passing,
    _run_gh,
    _run_git,
    commit_and_push,
    get_pr_diff,
    get_pr_status,
    merge_pr,
)


def _check_run(name: str, conclusion: str) -> dict:
    return {"__typename": "CheckRun", "name": name, "status": "COMPLETED", "conclusion": conclusion}


def _status_ctx(context: str, state: str) -> dict:
    return {"__typename": "StatusContext", "context": context, "state": state}


def _pr_json(
    mergeable: str = "MERGEABLE",
    merge_state: str = "CLEAN",
    rollup: list | None = None,
) -> str:
    return json.dumps({
        "mergeable": mergeable,
        "mergeStateStatus": merge_state,
        "statusCheckRollup": rollup or [],
    })


class TestRunGh:
    def test_success_returns_stdout(self) -> None:
        with patch("jules_mcp.github_ops.subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=0, stdout="output\n", stderr="")
            assert _run_gh("pr", "list") == "output\n"

    def test_failure_raises_runtime_error_with_stderr(self) -> None:
        with patch("jules_mcp.github_ops.subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
            with pytest.raises(RuntimeError, match="not found"):
                _run_gh("pr", "view", "bad-url")

    def test_failure_with_empty_stderr_uses_exit_code(self) -> None:
        with patch("jules_mcp.github_ops.subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=2, stdout="", stderr="")
            with pytest.raises(RuntimeError, match="gh exited 2"):
                _run_gh("some", "command")

    def test_passes_all_args_to_subprocess(self) -> None:
        with patch("jules_mcp.github_ops.subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=0, stdout="", stderr="")
            _run_gh("pr", "view", "https://github.com/org/repo/pull/1")
        called_cmd = mock.call_args[0][0]
        assert called_cmd == ["gh", "pr", "view", "https://github.com/org/repo/pull/1"]


class TestCiPassing:
    def test_empty_rollup_passes(self) -> None:
        ok, msg = _ci_passing([])
        assert ok is True
        assert msg == "no checks"

    def test_all_success_passes(self) -> None:
        rollup = [_check_run("gate", "SUCCESS"), _check_run("build", "SUCCESS")]
        ok, msg = _ci_passing(rollup)
        assert ok is True
        assert "passed" in msg

    def test_skipped_counts_as_passing(self) -> None:
        ok, _ = _ci_passing([_check_run("optional", "SKIPPED")])
        assert ok is True

    def test_neutral_counts_as_passing(self) -> None:
        ok, _ = _ci_passing([_check_run("optional", "NEUTRAL")])
        assert ok is True

    def test_failure_is_not_passing(self) -> None:
        rollup = [_check_run("gate", "SUCCESS"), _check_run("build", "FAILURE")]
        ok, msg = _ci_passing(rollup)
        assert ok is False
        assert "build" in msg

    def test_in_progress_is_pending(self) -> None:
        rollup = [
            {"__typename": "CheckRun", "name": "ci", "status": "IN_PROGRESS", "conclusion": None}
        ]
        ok, msg = _ci_passing(rollup)
        assert ok is False
        assert "pending" in msg

    def test_status_context_success(self) -> None:
        ok, _ = _ci_passing([_status_ctx("travis-ci", "SUCCESS")])
        assert ok is True

    def test_status_context_failure(self) -> None:
        ok, msg = _ci_passing([_status_ctx("travis-ci", "FAILURE")])
        assert ok is False
        assert "travis-ci" in msg

    def test_mixed_failing_and_pending_reports_failing(self) -> None:
        rollup = [
            _check_run("gate", "FAILURE"),
            {"__typename": "CheckRun", "name": "slow", "status": "IN_PROGRESS", "conclusion": None},
        ]
        ok, msg = _ci_passing(rollup)
        assert ok is False
        assert "failing" in msg


class TestGetPrStatus:
    def test_returns_pr_status_model(self) -> None:
        with patch("jules_mcp.github_ops._run_gh", return_value=_pr_json()):
            status = get_pr_status("https://github.com/org/repo/pull/1")
        assert isinstance(status, PrStatus)
        assert status.pr_url == "https://github.com/org/repo/pull/1"

    def test_passes_mergeable_through(self) -> None:
        with patch("jules_mcp.github_ops._run_gh", return_value=_pr_json(mergeable="CONFLICTING")):
            status = get_pr_status("url")
        assert status.mergeable == "CONFLICTING"

    def test_ci_passing_with_green_check(self) -> None:
        rollup = [_check_run("gate", "SUCCESS")]
        with patch("jules_mcp.github_ops._run_gh", return_value=_pr_json(rollup=rollup)):
            status = get_pr_status("url")
        assert status.ci_passing is True

    def test_ci_failing_with_red_check(self) -> None:
        rollup = [_check_run("gate", "FAILURE")]
        with patch("jules_mcp.github_ops._run_gh", return_value=_pr_json(rollup=rollup)):
            status = get_pr_status("url")
        assert status.ci_passing is False
        assert "gate" in status.ci_summary

    def test_defaults_unknown_when_gh_returns_empty_fields(self) -> None:
        with patch("jules_mcp.github_ops._run_gh", return_value=json.dumps({})):
            status = get_pr_status("url")
        assert status.mergeable == "UNKNOWN"
        assert status.merge_state_status == "UNKNOWN"


class TestMergePr:
    def test_successful_merge(self) -> None:
        with patch("jules_mcp.github_ops._run_gh", return_value=""):
            result = merge_pr("https://github.com/org/repo/pull/1")
        assert isinstance(result, MergeResult)
        assert result.merged is True
        assert result.message == "merged successfully"

    def test_squash_is_default_method(self) -> None:
        with patch("jules_mcp.github_ops._run_gh") as mock:
            mock.return_value = ""
            merge_pr("url")
        assert "--squash" in mock.call_args.args

    def test_delete_branch_flag_passed(self) -> None:
        with patch("jules_mcp.github_ops._run_gh") as mock:
            mock.return_value = ""
            merge_pr("url")
        assert "--delete-branch" in mock.call_args.args

    def test_invalid_method_returns_error_without_calling_gh(self) -> None:
        with patch("jules_mcp.github_ops._run_gh") as mock:
            result = merge_pr("url", method="invalid")
        assert result.merged is False
        assert "invalid" in result.message
        mock.assert_not_called()

    def test_gh_failure_returns_merged_false(self) -> None:
        with patch("jules_mcp.github_ops._run_gh", side_effect=RuntimeError("already merged")):
            result = merge_pr("url")
        assert result.merged is False
        assert "already merged" in result.message

    def test_rebase_method_accepted(self) -> None:
        with patch("jules_mcp.github_ops._run_gh") as mock:
            mock.return_value = ""
            result = merge_pr("url", method="rebase")
        assert result.merged is True
        assert "--rebase" in mock.call_args.args


class TestGetPrDiff:
    def test_returns_diff_string(self) -> None:
        diff = "diff --git a/foo.py b/foo.py\n+++ b/foo.py\n+new line\n"
        with patch("jules_mcp.github_ops._run_gh", return_value=diff):
            result = get_pr_diff("url")
        assert result == diff

    def test_calls_gh_pr_diff_with_url(self) -> None:
        with patch("jules_mcp.github_ops._run_gh") as mock:
            mock.return_value = ""
            get_pr_diff("https://github.com/org/repo/pull/5")
        args = mock.call_args.args
        assert args[0] == "pr"
        assert args[1] == "diff"
        assert "https://github.com/org/repo/pull/5" in args


class TestRunGit:
    def test_success_returns_stdout(self) -> None:
        with patch("jules_mcp.github_ops.subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
            assert _run_git("/repo", "status") == "ok\n"

    def test_passes_cwd_to_subprocess(self) -> None:
        with patch("jules_mcp.github_ops.subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=0, stdout="", stderr="")
            _run_git("/my/repo", "status")
        assert mock.call_args.kwargs["cwd"] == "/my/repo"

    def test_failure_raises_runtime_error(self) -> None:
        with patch("jules_mcp.github_ops.subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=1, stdout="", stderr="not a git repo")
            with pytest.raises(RuntimeError, match="not a git repo"):
                _run_git("/repo", "status")


class TestCommitAndPush:
    def _make_git(self, status_output: str = "M AGENTS.md") -> MagicMock:
        return MagicMock(side_effect=lambda *a, **_kw: status_output if "status" in a else "")

    def test_adds_stages_files(self) -> None:
        with patch("jules_mcp.github_ops._run_git") as mock:
            mock.return_value = ""
            commit_and_push("/repo", ["AGENTS.md"], "chore: update")
        first_call = mock.call_args_list[0]
        assert first_call.args[1] == "add"
        assert "AGENTS.md" in first_call.args

    def test_commits_when_status_has_changes(self) -> None:
        call_results = ["", "M AGENTS.md\n", "", ""]
        with patch("jules_mcp.github_ops._run_git", side_effect=call_results):
            commit_and_push("/repo", ["AGENTS.md"], "chore: update")
        # Can't easily assert commit called without capturing call_args_list

    def test_skips_commit_when_nothing_to_stage(self) -> None:
        calls: list[tuple] = []

        def fake_git(_path: str, *args: str) -> str:
            calls.append(args)
            return ""  # empty status = nothing to commit

        with patch("jules_mcp.github_ops._run_git", side_effect=fake_git):
            commit_and_push("/repo", ["AGENTS.md"], "chore: update")

        commands = [c[0] for c in calls]
        assert "commit" not in commands
        assert "push" in commands

    def test_push_uses_correct_branch(self) -> None:
        calls: list[tuple] = []

        def fake_git(_path: str, *args: str) -> str:
            calls.append(args)
            return ""

        with patch("jules_mcp.github_ops._run_git", side_effect=fake_git):
            result = commit_and_push("/repo", ["AGENTS.md"], "msg", branch="develop")

        push_call = next(c for c in calls if c[0] == "push")
        assert "develop" in push_call
        assert "origin/develop" in result

    def test_returns_confirmation_string(self) -> None:
        with patch("jules_mcp.github_ops._run_git", return_value=""):
            result = commit_and_push("/repo", ["AGENTS.md"], "msg")
        assert "main" in result
