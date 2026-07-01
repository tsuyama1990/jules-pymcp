"""Batch session orchestration — fire multiple Jules sessions concurrently."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from jules_mcp.prompt import build_enforced_prompt
from jules_mcp.session_watcher import watch_session_for_pr

if TYPE_CHECKING:
    from concurrent.futures import Future

    from jules_agent_sdk import JulesClient
    from jules_agent_sdk.models import Session

logger = logging.getLogger(__name__)


class BatchTaskSpec(BaseModel):
    """Specification for a single sub-task within a batch."""

    model_config = ConfigDict(extra="forbid", strict=True)

    label: str
    prompt: str
    source: str
    branch: str = "main"
    title: str | None = None
    acceptance_criteria: list[str] = []


class BatchSessionResult(BaseModel):
    """Result of a single session creation attempt within a batch."""

    model_config = ConfigDict(extra="forbid", strict=True)

    label: str
    session_id: str | None = None
    state: str | None = None
    error: str | None = None


class BatchSessionStatus(BaseModel):
    """Current status snapshot of a session in a batch."""

    model_config = ConfigDict(extra="forbid", strict=True)

    session_id: str
    state: str | None = None
    pr_url: str | None = None
    error: str | None = None


class BatchPollResult(BaseModel):
    """Result of a single poll across all sessions in a batch."""

    model_config = ConfigDict(extra="forbid", strict=True)

    ready: bool
    pr_urls: list[str]
    pending: list[str]
    failed: list[str]
    statuses: list[BatchSessionStatus]


def _extract_pr_url(session: Session) -> str | None:
    """Extract the first PR URL from session outputs."""
    for output in session.outputs:
        if output.pull_request and output.pull_request.url:
            return output.pull_request.url
    return None


def _create_one(
    client: JulesClient,
    task: BatchTaskSpec,
    auto_self_review: bool,
) -> BatchSessionResult:
    """Create a single session — runs inside a thread pool worker."""
    try:
        session = client.sessions.create(
            prompt=build_enforced_prompt(task.prompt, task.acceptance_criteria),
            source=task.source,
            starting_branch=task.branch,
            title=task.title,
        )
        if auto_self_review and session.name:
            watch_session_for_pr(client, session.name)
        return BatchSessionResult(
            label=task.label,
            session_id=session.name,
            state=session.state.value,
        )
    except Exception as exc:  # noqa: BLE001 — surface per-task errors without killing the batch
        logger.warning("Batch: failed to create session for task %r: %s", task.label, exc)
        return BatchSessionResult(label=task.label, error=str(exc))


def create_batch(
    client: JulesClient,
    tasks: list[BatchTaskSpec],
    auto_self_review: bool = True,
) -> list[BatchSessionResult]:
    """Fire all tasks concurrently and return one result per task."""
    results: list[BatchSessionResult] = []
    futures: list[tuple[BatchTaskSpec, Future[BatchSessionResult]]] = []

    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        for task in tasks:
            future: Future[BatchSessionResult] = pool.submit(
                _create_one, client, task, auto_self_review
            )
            futures.append((task, future))

        for task, future in futures:
            try:
                results.append(future.result(timeout=60))
            except Exception as exc:  # noqa: BLE001 — timeout or unexpected error per task
                logger.warning("Batch: future for task %r raised: %s", task.label, exc)
                results.append(BatchSessionResult(label=task.label, error=str(exc)))

    return results


def _fetch_status(client: JulesClient, session_id: str) -> BatchSessionStatus:
    """Fetch status for a single session — runs inside a thread pool worker."""
    session = client.sessions.get(session_id)
    return BatchSessionStatus(
        session_id=session_id,
        state=session.state.value,
        pr_url=_extract_pr_url(session),
    )


def get_batch_status(
    client: JulesClient,
    session_ids: list[str],
) -> list[BatchSessionStatus]:
    """Fetch current status of all sessions concurrently — non-blocking snapshot."""
    statuses: list[BatchSessionStatus] = []
    futures_map: dict[Future[BatchSessionStatus], str] = {}

    with ThreadPoolExecutor(max_workers=len(session_ids)) as pool:
        for sid in session_ids:
            future: Future[BatchSessionStatus] = pool.submit(_fetch_status, client, sid)
            futures_map[future] = sid

        for future in as_completed(futures_map):
            sid = futures_map[future]
            try:
                statuses.append(future.result(timeout=30))
            except Exception as exc:  # noqa: BLE001 — surface per-session errors
                logger.warning("Batch status: failed for session %r: %s", sid, exc)
                statuses.append(BatchSessionStatus(session_id=sid, error=str(exc)))

    return sorted(statuses, key=lambda s: session_ids.index(s.session_id))


_TERMINAL_STATES: frozenset[str] = frozenset({"COMPLETED", "FAILED"})


def poll_batch(client: JulesClient, session_ids: list[str]) -> BatchPollResult:
    """Check all sessions once and return a ready flag plus PR URLs.

    ready=True means every session has reached a terminal state (COMPLETED or FAILED)
    and polling can stop. pr_urls lists the PRs that are ready to merge, in input order.
    """
    statuses = get_batch_status(client, session_ids)
    pr_urls = [s.pr_url for s in statuses if s.pr_url is not None]
    pending = [
        s.session_id for s in statuses
        if (s.state or "") not in _TERMINAL_STATES and s.error is None
    ]
    failed = [
        s.session_id for s in statuses
        if s.state == "FAILED" or s.error is not None
    ]
    return BatchPollResult(
        ready=len(pending) == 0,
        pr_urls=pr_urls,
        pending=pending,
        failed=failed,
        statuses=statuses,
    )


def wait_for_batch(
    client: JulesClient,
    session_ids: list[str],
    timeout_minutes: int = 120,
) -> BatchPollResult:
    """Block until all sessions reach a terminal state or timeout expires.

    Polls every 60 seconds internally — the caller blocks for the entire duration.
    Returns the final BatchPollResult: ready=True means all done; ready=False means
    timeout was reached with sessions still pending.
    """
    deadline = time.monotonic() + timeout_minutes * 60
    while True:
        result = poll_batch(client, session_ids)
        if result.ready:
            return result
        if time.monotonic() >= deadline:
            return result
        time.sleep(60)
