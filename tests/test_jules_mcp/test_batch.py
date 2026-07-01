"""Unit tests for jules_mcp.batch."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from jules_agent_sdk import models

from jules_mcp.batch import (
    BatchPollResult,
    BatchTaskSpec,
    _create_one,
    _extract_pr_url,
    _fetch_status,
    create_batch,
    get_batch_status,
    poll_batch,
    wait_for_batch,
)


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


def _make_task(label: str = "task-1") -> BatchTaskSpec:
    return BatchTaskSpec(
        label=label,
        prompt="Add tests to the auth module",
        source="sources/github/org/repo",
    )


class TestExtractPrUrl:
    def test_returns_url_when_present(self) -> None:
        session = _make_session(pr_url="https://github.com/org/repo/pull/1")
        assert _extract_pr_url(session) == "https://github.com/org/repo/pull/1"

    def test_returns_none_when_no_outputs(self) -> None:
        assert _extract_pr_url(_make_session()) is None

    def test_returns_none_when_no_pr(self) -> None:
        session = models.Session(
            name="sessions/test",
            prompt="test",
            source_context=models.SourceContext(source="sources/test"),
            state=models.SessionState.IN_PROGRESS,
            outputs=[models.SessionOutput(pull_request=None)],
        )
        assert _extract_pr_url(session) is None


class TestCreateOne:
    def test_happy_path(self) -> None:
        session = _make_session(state=models.SessionState.IN_PROGRESS)
        client = MagicMock()
        client.sessions.create.return_value = session

        with patch("jules_mcp.batch.watch_session_for_pr") as mock_watch:
            result = _create_one(client, _make_task(), auto_self_review=True)

        assert result.label == "task-1"
        assert result.session_id == "sessions/test-123"
        assert result.state == "IN_PROGRESS"
        assert result.error is None
        mock_watch.assert_called_once_with(client, "sessions/test-123")

    def test_no_watch_when_auto_self_review_false(self) -> None:
        client = MagicMock()
        client.sessions.create.return_value = _make_session()

        with patch("jules_mcp.batch.watch_session_for_pr") as mock_watch:
            _create_one(client, _make_task(), auto_self_review=False)

        mock_watch.assert_not_called()

    def test_prompt_is_enforced(self) -> None:
        client = MagicMock()
        client.sessions.create.return_value = _make_session()

        _create_one(client, _make_task(), auto_self_review=False)

        called_prompt = client.sessions.create.call_args.kwargs["prompt"]
        assert "Mandatory Quality Rules" in called_prompt
        assert "Add tests to the auth module" in called_prompt

    def test_acceptance_criteria_injected_into_prompt(self) -> None:
        client = MagicMock()
        client.sessions.create.return_value = _make_session()
        task = BatchTaskSpec(
            label="auth",
            prompt="implement login endpoint",
            source="sources/github/org/repo",
            acceptance_criteria=["POST /login returns 200", "bad password returns 401"],
        )

        _create_one(client, task, auto_self_review=False)

        prompt = client.sessions.create.call_args.kwargs["prompt"]
        assert "POST /login returns 200" in prompt
        assert "bad password returns 401" in prompt
        assert "Acceptance Criteria" in prompt

    def test_returns_error_on_api_failure(self) -> None:
        client = MagicMock()
        client.sessions.create.side_effect = RuntimeError("API down")

        result = _create_one(client, _make_task("failing-task"), auto_self_review=False)

        assert result.label == "failing-task"
        assert result.session_id is None
        assert result.error == "API down"

    def test_no_watch_when_session_has_no_name(self) -> None:
        session = _make_session(name="")
        client = MagicMock()
        client.sessions.create.return_value = session

        with patch("jules_mcp.batch.watch_session_for_pr") as mock_watch:
            _create_one(client, _make_task(), auto_self_review=True)

        mock_watch.assert_not_called()


class TestCreateBatch:
    def test_fires_all_tasks(self) -> None:
        client = MagicMock()
        client.sessions.create.side_effect = [
            _make_session("sessions/s1"),
            _make_session("sessions/s2"),
        ]
        tasks = [_make_task("a"), _make_task("b")]

        with patch("jules_mcp.batch.watch_session_for_pr"):
            results = create_batch(client, tasks, auto_self_review=False)

        assert len(results) == 2
        assert {r.label for r in results} == {"a", "b"}
        assert all(r.error is None for r in results)

    def test_partial_failure_does_not_stop_others(self) -> None:
        client = MagicMock()
        client.sessions.create.side_effect = [
            RuntimeError("boom"),
            _make_session("sessions/s2"),
        ]
        tasks = [_make_task("fail"), _make_task("ok")]

        with patch("jules_mcp.batch.watch_session_for_pr"):
            results = create_batch(client, tasks, auto_self_review=False)

        assert len(results) == 2
        errors = [r for r in results if r.error is not None]
        successes = [r for r in results if r.error is None]
        assert len(errors) == 1
        assert len(successes) == 1


class TestFetchStatus:
    def test_returns_status_with_pr_url(self) -> None:
        client = MagicMock()
        client.sessions.get.return_value = _make_session(
            state=models.SessionState.COMPLETED,
            pr_url="https://github.com/org/repo/pull/5",
        )

        status = _fetch_status(client, "sessions/test-123")

        assert status.session_id == "sessions/test-123"
        assert status.state == "COMPLETED"
        assert status.pr_url == "https://github.com/org/repo/pull/5"

    def test_returns_status_without_pr_url(self) -> None:
        client = MagicMock()
        client.sessions.get.return_value = _make_session(state=models.SessionState.IN_PROGRESS)

        status = _fetch_status(client, "sessions/test-123")

        assert status.pr_url is None
        assert status.state == "IN_PROGRESS"


class TestGetBatchStatus:
    def test_returns_one_status_per_session(self) -> None:
        client = MagicMock()
        client.sessions.get.side_effect = [
            _make_session("sessions/s1", state=models.SessionState.IN_PROGRESS),
            _make_session("sessions/s2", state=models.SessionState.COMPLETED),
        ]

        statuses = get_batch_status(client, ["sessions/s1", "sessions/s2"])

        assert len(statuses) == 2
        assert statuses[0].session_id == "sessions/s1"
        assert statuses[1].session_id == "sessions/s2"

    def test_preserves_input_order(self) -> None:
        client = MagicMock()
        client.sessions.get.side_effect = [
            _make_session("sessions/s1"),
            _make_session("sessions/s2"),
            _make_session("sessions/s3"),
        ]

        statuses = get_batch_status(client, ["sessions/s1", "sessions/s2", "sessions/s3"])

        assert [s.session_id for s in statuses] == ["sessions/s1", "sessions/s2", "sessions/s3"]

    def test_error_per_session_does_not_crash_others(self) -> None:
        client = MagicMock()
        client.sessions.get.side_effect = [
            RuntimeError("network error"),
            _make_session("sessions/s2", state=models.SessionState.COMPLETED),
        ]

        statuses = get_batch_status(client, ["sessions/s1", "sessions/s2"])

        assert len(statuses) == 2
        errors = [s for s in statuses if s.error is not None]
        assert len(errors) == 1


class TestPollBatch:
    def test_ready_when_all_completed(self) -> None:
        client = MagicMock()
        client.sessions.get.side_effect = [
            _make_session("sessions/s1", state=models.SessionState.COMPLETED,
                          pr_url="https://github.com/org/repo/pull/1"),
            _make_session("sessions/s2", state=models.SessionState.COMPLETED,
                          pr_url="https://github.com/org/repo/pull/2"),
        ]
        result = poll_batch(client, ["sessions/s1", "sessions/s2"])
        assert isinstance(result, BatchPollResult)
        assert result.ready is True
        assert len(result.pr_urls) == 2
        assert len(result.pending) == 0
        assert len(result.failed) == 0

    def test_not_ready_when_any_in_progress(self) -> None:
        client = MagicMock()
        client.sessions.get.side_effect = [
            _make_session("sessions/s1", state=models.SessionState.COMPLETED,
                          pr_url="https://github.com/org/repo/pull/1"),
            _make_session("sessions/s2", state=models.SessionState.IN_PROGRESS),
        ]
        result = poll_batch(client, ["sessions/s1", "sessions/s2"])
        assert result.ready is False
        assert "sessions/s2" in result.pending

    def test_ready_when_all_failed(self) -> None:
        client = MagicMock()
        client.sessions.get.side_effect = [
            _make_session("sessions/s1", state=models.SessionState.FAILED),
        ]
        result = poll_batch(client, ["sessions/s1"])
        assert result.ready is True
        assert "sessions/s1" in result.failed
        assert len(result.pr_urls) == 0

    def test_failed_includes_api_errors(self) -> None:
        client = MagicMock()
        client.sessions.get.side_effect = [
            RuntimeError("network error"),
            _make_session("sessions/s2", state=models.SessionState.COMPLETED,
                          pr_url="https://github.com/org/repo/pull/2"),
        ]
        result = poll_batch(client, ["sessions/s1", "sessions/s2"])
        assert result.ready is True
        assert "sessions/s1" in result.failed
        assert len(result.pr_urls) == 1

    def test_pr_urls_preserve_input_order(self) -> None:
        client = MagicMock()
        client.sessions.get.side_effect = [
            _make_session("sessions/s1", state=models.SessionState.COMPLETED,
                          pr_url="https://github.com/org/repo/pull/1"),
            _make_session("sessions/s2", state=models.SessionState.COMPLETED,
                          pr_url="https://github.com/org/repo/pull/2"),
        ]
        result = poll_batch(client, ["sessions/s1", "sessions/s2"])
        assert result.pr_urls[0] == "https://github.com/org/repo/pull/1"
        assert result.pr_urls[1] == "https://github.com/org/repo/pull/2"

    def test_statuses_included_in_result(self) -> None:
        client = MagicMock()
        client.sessions.get.return_value = _make_session(
            state=models.SessionState.IN_PROGRESS
        )
        result = poll_batch(client, ["sessions/s1"])
        assert len(result.statuses) == 1
        assert result.statuses[0].session_id == "sessions/s1"


class TestWaitForBatch:
    @patch("jules_mcp.batch.time.sleep")
    def test_returns_immediately_when_ready_on_first_poll(self, mock_sleep: MagicMock) -> None:
        client = MagicMock()
        client.sessions.get.return_value = _make_session(
            state=models.SessionState.COMPLETED,
            pr_url="https://github.com/org/repo/pull/1",
        )
        result = wait_for_batch(client, ["sessions/s1"])
        assert result.ready is True
        assert result.pr_urls == ["https://github.com/org/repo/pull/1"]
        mock_sleep.assert_not_called()

    @patch("jules_mcp.batch.time.sleep")
    def test_polls_until_all_sessions_complete(self, mock_sleep: MagicMock) -> None:
        client = MagicMock()
        client.sessions.get.side_effect = [
            _make_session("sessions/s1", state=models.SessionState.IN_PROGRESS),
            _make_session("sessions/s1", state=models.SessionState.COMPLETED,
                          pr_url="https://github.com/org/repo/pull/1"),
        ]
        result = wait_for_batch(client, ["sessions/s1"])
        assert result.ready is True
        mock_sleep.assert_called_once_with(60)

    @patch("jules_mcp.batch.time.monotonic")
    @patch("jules_mcp.batch.time.sleep")
    def test_returns_on_timeout(self, mock_sleep: MagicMock, mock_monotonic: MagicMock) -> None:
        mock_monotonic.side_effect = [0.0, float(120 * 60 + 1)]
        client = MagicMock()
        client.sessions.get.return_value = _make_session(state=models.SessionState.IN_PROGRESS)
        result = wait_for_batch(client, ["sessions/s1"], timeout_minutes=120)
        assert result.ready is False
        mock_sleep.assert_not_called()

    @patch("jules_mcp.batch.time.sleep")
    def test_respects_custom_timeout(self, _mock_sleep: MagicMock) -> None:
        client = MagicMock()
        client.sessions.get.return_value = _make_session(
            state=models.SessionState.COMPLETED
        )
        result = wait_for_batch(client, ["sessions/s1"], timeout_minutes=30)
        assert result.ready is True

    @patch("jules_mcp.batch.time.sleep")
    def test_returns_partial_result_on_mixed_states(self, _mock_sleep: MagicMock) -> None:
        client = MagicMock()
        client.sessions.get.side_effect = [
            _make_session("sessions/s1", state=models.SessionState.COMPLETED,
                          pr_url="https://github.com/org/repo/pull/1"),
            _make_session("sessions/s2", state=models.SessionState.COMPLETED,
                          pr_url="https://github.com/org/repo/pull/2"),
        ]
        result = wait_for_batch(client, ["sessions/s1", "sessions/s2"])
        assert result.ready is True
        assert len(result.pr_urls) == 2
