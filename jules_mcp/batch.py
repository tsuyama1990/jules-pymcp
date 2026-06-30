"""Batch session orchestration — fire multiple Jules sessions concurrently."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from jules_mcp.prompt import build_enforced_prompt
from jules_mcp.session_watcher import watch_session_for_pr

if TYPE_CHECKING:
    from concurrent.futures import Future

    from jules_agent_sdk import JulesClient
    from jules_agent_sdk.models import SessionOutput

logger = logging.getLogger(__name__)


class BatchTaskSpec(BaseModel):
    """Specification for a single sub-task within a batch."""

    model_config = ConfigDict(extra="forbid", strict=True)

    label: str
    prompt: str
    source: str
    branch: str = "main"
    title: str | None = None


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


def _extract_pr_url(outputs: list[SessionOutput]) -> str | None:
    """Extract the first PR URL from session outputs."""
    for output in outputs:
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
            prompt=build_enforced_prompt(task.prompt),
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


def _fetch_status(client: JulesClient, session_id: str) -> BatchSessionStatus:
    """Fetch status for a single session — runs inside a thread pool worker."""
    session = client.sessions.get(session_id)
    return BatchSessionStatus(
        session_id=session_id,
        state=session.state.value,
        pr_url=_extract_pr_url(session.outputs),
    )
