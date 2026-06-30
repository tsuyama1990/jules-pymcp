"""Unit tests for jules_mcp.session_watcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from jules_agent_sdk import models

from jules_mcp.session_watcher import _extract_pr_url, _run_watcher, watch_session_for_pr


def _make_session(
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
        name="sessions/test-123",
        prompt="test",
        source_context=models.SourceContext(source="sources/test"),
        state=state,
        outputs=outputs,
    )


class TestExtractPrUrl:
    def test_returns_url_when_pr_present(self) -> None:
        session = _make_session(pr_url="https://github.com/org/repo/pull/1")
        assert _extract_pr_url(session) == "https://github.com/org/repo/pull/1"

    def test_returns_none_when_no_outputs(self) -> None:
        session = _make_session()
        assert _extract_pr_url(session) is None

    def test_returns_none_when_output_has_no_pr(self) -> None:
        session = _make_session()
        session.outputs = [models.SessionOutput(pull_request=None)]
        assert _extract_pr_url(session) is None


class TestRunWatcher:
    def _make_client(self, sessions: list[models.Session]) -> MagicMock:
        client = MagicMock()
        client.sessions.get.side_effect = sessions
        return client

    @patch("jules_mcp.session_watcher.time.sleep")
    def test_sends_self_critic_when_pr_found(self, _mock_sleep: MagicMock) -> None:
        no_pr = _make_session(state=models.SessionState.IN_PROGRESS)
        with_pr = _make_session(
            state=models.SessionState.COMPLETED,
            pr_url="https://github.com/org/repo/pull/1",
        )
        client = self._make_client([no_pr, with_pr])
        sent: list[tuple[str, str]] = []

        _run_watcher(
            client, "sessions/test-123",
            _send_message=lambda _s, _m: sent.append((_s, _m)),
        )

        assert len(sent) == 1
        assert "Self-Critic" in sent[0][1]

    @patch("jules_mcp.session_watcher.time.sleep")
    def test_self_critic_sent_only_once(self, _mock_sleep: MagicMock) -> None:
        with_pr = _make_session(
            state=models.SessionState.IN_PROGRESS,
            pr_url="https://github.com/org/repo/pull/1",
        )
        completed = _make_session(
            state=models.SessionState.COMPLETED,
            pr_url="https://github.com/org/repo/pull/1",
        )
        client = self._make_client([with_pr, completed])
        sent: list[tuple[str, str]] = []

        _run_watcher(
            client, "sessions/test-123",
            _send_message=lambda _s, _m: sent.append((_s, _m)),
        )

        assert len(sent) == 1

    @patch("jules_mcp.session_watcher.time.sleep")
    def test_stops_on_failed_state_without_pr(self, _mock_sleep: MagicMock) -> None:
        failed = _make_session(state=models.SessionState.FAILED)
        client = self._make_client([failed])
        sent: list[tuple[str, str]] = []

        _run_watcher(
            client, "sessions/test-123",
            _send_message=lambda _s, _m: sent.append((_s, _m)),
        )

        assert len(sent) == 0
        assert client.sessions.get.call_count == 1

    @patch("jules_mcp.session_watcher.time.sleep")
    def test_continues_after_poll_error(self, _mock_sleep: MagicMock) -> None:
        completed = _make_session(
            state=models.SessionState.COMPLETED,
            pr_url="https://github.com/org/repo/pull/1",
        )
        client = MagicMock()
        client.sessions.get.side_effect = [Exception("network error"), completed]
        sent: list[tuple[str, str]] = []

        _run_watcher(
            client, "sessions/test-123",
            _send_message=lambda _s, _m: sent.append((_s, _m)),
        )

        assert len(sent) == 1

    @patch("jules_mcp.session_watcher.time.sleep")
    def test_continues_after_send_error(self, _mock_sleep: MagicMock) -> None:
        with_pr = _make_session(
            state=models.SessionState.COMPLETED,
            pr_url="https://github.com/org/repo/pull/1",
        )
        client = self._make_client([with_pr])

        def failing_send(sid: str, msg: str) -> None:
            raise RuntimeError("send failed")

        _run_watcher(client, "sessions/test-123", _send_message=failing_send)
        # Should not raise — errors are logged and swallowed


class TestWatchSessionForPr:
    def test_starts_daemon_thread(self) -> None:
        client = MagicMock()
        completed = _make_session(state=models.SessionState.COMPLETED)
        client.sessions.get.return_value = completed

        with patch("jules_mcp.session_watcher._run_watcher") as mock_watcher:
            watch_session_for_pr(client, "sessions/test-123")
            # Give the thread a moment to start
            import time
            time.sleep(0.05)
            mock_watcher.assert_called_once_with(client, "sessions/test-123")
