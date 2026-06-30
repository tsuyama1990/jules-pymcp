"""Unit tests for jules_mcp.cli."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from jules_agent_sdk import models

from jules_mcp.cli import _build_parser, _make_client, _tail_activities, main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(
    name: str = "sessions/test-123",
    state: models.SessionState = models.SessionState.IN_PROGRESS,
    pr_url: str | None = None,
) -> models.Session:
    outputs: list[models.SessionOutput] = []
    if pr_url:
        outputs = [
            models.SessionOutput(
                pull_request=models.PullRequest(url=pr_url, title="PR", description="")
            )
        ]
    return models.Session(
        name=name,
        prompt="test",
        source_context=models.SourceContext(source="sources/test"),
        state=state,
        outputs=outputs,
    )


def _make_activity(
    name: str = "activities/1",
    id_: str = "act-1",
    description: str = "Step 1",
    create_time: str = "2025-01-01T10:00:00Z",
    originator: str = "",
    **kwargs: object,
) -> models.Activity:
    return models.Activity(
        name=name,
        id=id_,
        description=description,
        create_time=create_time,
        originator=originator,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# _make_client
# ---------------------------------------------------------------------------


class TestMakeClient:
    def test_returns_client_when_key_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JULES_API_KEY", "test-key")
        with patch("jules_mcp.cli.JulesClient") as mock_cls:
            _make_client()
            mock_cls.assert_called_once_with("test-key")

    def test_exits_when_key_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JULES_API_KEY", raising=False)
        with pytest.raises(SystemExit) as exc:
            _make_client()
        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# _build_parser
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_session_id_mode(self) -> None:
        args = _build_parser().parse_args(["--session-id", "sessions/abc"])
        assert args.session_id == "sessions/abc"
        assert args.prompt is None

    def test_create_mode(self) -> None:
        args = _build_parser().parse_args(
            ["--prompt", "add tests", "--source", "sources/github/org/repo"]
        )
        assert args.prompt == "add tests"
        assert args.source == "sources/github/org/repo"
        assert args.branch == "main"

    def test_all_options(self) -> None:
        args = _build_parser().parse_args([
            "--prompt", "do X",
            "--source", "sources/github/org/repo",
            "--branch", "dev",
            "--title", "My task",
            "--acceptance-criteria", "criterion A", "criterion B",
        ])
        assert args.branch == "dev"
        assert args.title == "My task"
        assert args.acceptance_criteria == ["criterion A", "criterion B"]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def _run(self, argv: list[str]) -> None:
        with patch.object(sys, "argv", ["jules-run", *argv]):
            main()

    def test_monitor_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JULES_API_KEY", "k")
        session = _make_session(state=models.SessionState.COMPLETED)
        mock_client = MagicMock()
        mock_client.sessions.get.return_value = session

        with (
            patch("jules_mcp.cli.JulesClient", return_value=mock_client),
            patch("jules_mcp.cli.watch_session_for_pr") as mock_watch,
            patch("jules_mcp.cli._tail_activities") as mock_tail,
        ):
            self._run(["--session-id", "sessions/test-123"])

        mock_client.sessions.get.assert_called_once_with("sessions/test-123")
        mock_watch.assert_called_once_with(mock_client, "sessions/test-123")
        mock_tail.assert_called_once_with(mock_client, "sessions/test-123")

    def test_create_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JULES_API_KEY", "k")
        session = _make_session(state=models.SessionState.IN_PROGRESS)
        mock_client = MagicMock()
        mock_client.sessions.create.return_value = session

        with (
            patch("jules_mcp.cli.JulesClient", return_value=mock_client),
            patch("jules_mcp.cli.build_enforced_prompt", return_value="enforced") as mock_ep,
            patch("jules_mcp.cli.watch_session_for_pr"),
            patch("jules_mcp.cli._tail_activities"),
        ):
            self._run([
                "--prompt", "add tests",
                "--source", "sources/github/org/repo",
                "--title", "My task",
            ])

        mock_ep.assert_called_once_with("add tests", None)
        mock_client.sessions.create.assert_called_once_with(
            prompt="enforced",
            source="sources/github/org/repo",
            starting_branch="main",
            title="My task",
            require_plan_approval=False,
        )

    def test_create_mode_passes_acceptance_criteria(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JULES_API_KEY", "k")
        session = _make_session()
        mock_client = MagicMock()
        mock_client.sessions.create.return_value = session

        with (
            patch("jules_mcp.cli.JulesClient", return_value=mock_client),
            patch("jules_mcp.cli.build_enforced_prompt", return_value="enforced") as mock_ep,
            patch("jules_mcp.cli.watch_session_for_pr"),
            patch("jules_mcp.cli._tail_activities"),
        ):
            self._run([
                "--prompt", "add tests",
                "--source", "sources/github/org/repo",
                "--acceptance-criteria", "crit A", "crit B",
            ])

        mock_ep.assert_called_once_with("add tests", ["crit A", "crit B"])

    def test_exits_when_prompt_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JULES_API_KEY", "k")
        with (
            patch("jules_mcp.cli.JulesClient", return_value=MagicMock()),
            pytest.raises(SystemExit) as exc,
        ):
            self._run(["--source", "sources/github/org/repo"])
        assert exc.value.code == 1

    def test_exits_when_source_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JULES_API_KEY", "k")
        with (
            patch("jules_mcp.cli.JulesClient", return_value=MagicMock()),
            pytest.raises(SystemExit) as exc,
        ):
            self._run(["--prompt", "do X"])
        assert exc.value.code == 1

    def test_exits_when_session_name_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JULES_API_KEY", "k")
        session = _make_session(name=None)  # type: ignore[arg-type]
        mock_client = MagicMock()
        mock_client.sessions.create.return_value = session

        with (
            patch("jules_mcp.cli.JulesClient", return_value=mock_client),
            patch("jules_mcp.cli.build_enforced_prompt", return_value="p"),
            pytest.raises(SystemExit) as exc,
        ):
            self._run(["--prompt", "do X", "--source", "sources/github/org/repo"])
        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# _tail_activities
# ---------------------------------------------------------------------------


class TestTailActivities:
    def _make_client(
        self,
        sessions: list[models.Session],
        activities: list[models.Activity] | None = None,
    ) -> MagicMock:
        client = MagicMock()
        client.sessions.get.side_effect = sessions
        client.activities.list_all.return_value = activities or []
        return client

    @patch("jules_mcp.cli.time.sleep")
    def test_breaks_on_terminal_state(self, _mock_sleep: MagicMock) -> None:
        session = _make_session(state=models.SessionState.COMPLETED)
        client = self._make_client([session])
        _tail_activities(client, "sessions/test-123")
        assert client.sessions.get.call_count == 1

    @patch("jules_mcp.cli.time.sleep")
    def test_prints_pr_url_on_terminal(
        self, _mock_sleep: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        session = _make_session(
            state=models.SessionState.COMPLETED,
            pr_url="https://github.com/org/repo/pull/1",
        )
        client = self._make_client([session])
        _tail_activities(client, "sessions/test-123")
        out = capsys.readouterr().out
        assert "https://github.com/org/repo/pull/1" in out

    @patch("jules_mcp.cli.time.sleep")
    def test_prints_activity_description(
        self, _mock_sleep: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        act = _make_activity(description="Doing something")
        session = _make_session(state=models.SessionState.COMPLETED)
        client = self._make_client([session], activities=[act])
        _tail_activities(client, "sessions/test-123")
        assert "Doing something" in capsys.readouterr().out

    @patch("jules_mcp.cli.time.sleep")
    def test_deduplicates_activities(self, _mock_sleep: MagicMock) -> None:
        act = _make_activity()
        running = _make_session(state=models.SessionState.IN_PROGRESS)
        done = _make_session(state=models.SessionState.COMPLETED)
        client = MagicMock()
        client.sessions.get.side_effect = [running, done]
        client.activities.list_all.return_value = [act]

        with patch("builtins.print") as mock_print:
            _tail_activities(client, "sessions/test-123")
            description_calls = [
                c for c in mock_print.call_args_list
                if c.args and "Step 1" in str(c.args[0])
            ]
        assert len(description_calls) == 1

    @patch("jules_mcp.cli.time.sleep")
    def test_prints_plan_generated(
        self, _mock_sleep: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        act = _make_activity(plan_generated={"planSummary": "Build the thing"})
        session = _make_session(state=models.SessionState.COMPLETED)
        client = self._make_client([session], activities=[act])
        _tail_activities(client, "sessions/test-123")
        assert "Build the thing" in capsys.readouterr().out

    @patch("jules_mcp.cli.time.sleep")
    def test_prints_plan_approved(
        self, _mock_sleep: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        act = _make_activity(plan_approved={"approved": "true"})
        session = _make_session(state=models.SessionState.COMPLETED)
        client = self._make_client([session], activities=[act])
        _tail_activities(client, "sessions/test-123")
        assert "Plan approved" in capsys.readouterr().out

    @patch("jules_mcp.cli.time.sleep")
    def test_prints_progress_updated(
        self, _mock_sleep: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        act = _make_activity(progress_updated={"progressPercent": "50", "statusMessage": "Halfway"})
        session = _make_session(state=models.SessionState.COMPLETED)
        client = self._make_client([session], activities=[act])
        _tail_activities(client, "sessions/test-123")
        out = capsys.readouterr().out
        assert "50%" in out
        assert "Halfway" in out

    @patch("jules_mcp.cli.time.sleep")
    def test_prints_agent_messaged(
        self, _mock_sleep: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        act = _make_activity(agent_messaged={"message": "Here is my plan"})
        session = _make_session(state=models.SessionState.COMPLETED)
        client = self._make_client([session], activities=[act])
        _tail_activities(client, "sessions/test-123")
        assert "Here is my plan" in capsys.readouterr().out

    @patch("jules_mcp.cli.time.sleep")
    def test_truncates_long_agent_message(
        self, _mock_sleep: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        long_msg = "x" * 200
        act = _make_activity(agent_messaged={"message": long_msg})
        session = _make_session(state=models.SessionState.COMPLETED)
        client = self._make_client([session], activities=[act])
        _tail_activities(client, "sessions/test-123")
        out = capsys.readouterr().out
        assert "..." in out
        assert long_msg not in out

    @patch("jules_mcp.cli.time.sleep")
    def test_prints_session_completed(
        self, _mock_sleep: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        act = _make_activity(session_completed={"result": "ok"})
        session = _make_session(state=models.SessionState.COMPLETED)
        client = self._make_client([session], activities=[act])
        _tail_activities(client, "sessions/test-123")
        assert "Session completed" in capsys.readouterr().out

    @patch("jules_mcp.cli.time.sleep")
    def test_prints_session_failed(
        self, _mock_sleep: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        act = _make_activity(session_failed={"failureReason": "timeout"})
        session = _make_session(state=models.SessionState.FAILED)
        client = self._make_client([session], activities=[act])
        _tail_activities(client, "sessions/test-123")
        out = capsys.readouterr().out
        assert "timeout" in out

    @patch("jules_mcp.cli.time.sleep")
    def test_stops_on_keyboard_interrupt(
        self, _mock_sleep: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        client = MagicMock()
        client.sessions.get.side_effect = KeyboardInterrupt
        _tail_activities(client, "sessions/test-123")
        assert "Polling stopped" in capsys.readouterr().out

    @patch("jules_mcp.cli.time.sleep")
    def test_continues_after_exception(self, mock_sleep: MagicMock) -> None:
        done = _make_session(state=models.SessionState.COMPLETED)
        client = MagicMock()
        client.sessions.get.side_effect = [RuntimeError("oops"), done]
        client.activities.list_all.return_value = []
        _tail_activities(client, "sessions/test-123")
        assert client.sessions.get.call_count == 2
        mock_sleep.assert_called_with(15)

    @patch("jules_mcp.cli.time.sleep")
    def test_prints_originator_when_present(
        self, _mock_sleep: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        act = _make_activity(originator="jules")
        session = _make_session(state=models.SessionState.COMPLETED)
        client = self._make_client([session], activities=[act])
        _tail_activities(client, "sessions/test-123")
        assert "[jules]" in capsys.readouterr().out
