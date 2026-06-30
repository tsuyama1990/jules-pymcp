"""Background session watcher — sends self-critic review once a PR is opened."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from jules_agent_sdk import JulesClient, models

from jules_mcp.self_critic import build_self_critic_prompt

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS: int = 60
_MAX_DURATION_SECONDS: int = 4 * 60 * 60  # 4 hours

_TERMINAL_STATES: frozenset[models.SessionState] = frozenset(
    {models.SessionState.COMPLETED, models.SessionState.FAILED}
)


def watch_session_for_pr(client: JulesClient, session_id: str) -> None:
    """Start a background daemon thread that sends the self-critic review when a PR is opened.

    Returns immediately; all work happens in the background thread.

    Args:
        client: Authenticated Jules API client.
        session_id: The session name/ID to watch.

    """
    thread = threading.Thread(
        target=_run_watcher,
        args=(client, session_id),
        daemon=True,
        name=f"session-watcher-{session_id}",
    )
    thread.start()


def _extract_pr_url(session: models.Session) -> str | None:
    for output in session.outputs:
        if output.pull_request and output.pull_request.url:
            return output.pull_request.url
    return None


def _run_watcher(
    client: JulesClient,
    session_id: str,
    _send_message: Callable[[str, str], None] | None = None,
) -> None:
    """Poll the session and send the self-critic message once a PR is detected."""
    send = _send_message or (lambda sid, msg: client.sessions.send_message(sid, msg))

    deadline = time.monotonic() + _MAX_DURATION_SECONDS
    self_critic_sent = False

    while time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL_SECONDS)

        try:
            session = client.sessions.get(session_id)
        except Exception:  # noqa: BLE001 — broad catch is intentional in a daemon thread
            logger.warning(
                "session-watcher: failed to poll session %s", session_id, exc_info=True
            )
            continue

        pr_url = _extract_pr_url(session)

        if pr_url and not self_critic_sent:
            try:
                send(session_id, build_self_critic_prompt())
                self_critic_sent = True
                logger.info(
                    "session-watcher: self-critic review sent to session %s (PR: %s)",
                    session_id,
                    pr_url,
                )
            except Exception:  # noqa: BLE001 — broad catch is intentional in a daemon thread
                logger.warning(
                    "session-watcher: failed to send self-critic to session %s",
                    session_id,
                    exc_info=True,
                )

        if session.state in _TERMINAL_STATES:
            logger.info(
                "session-watcher: session %s reached terminal state %s — stopping.",
                session.name,
                session.state,
            )
            return

    logger.warning(
        "session-watcher: watcher for session %s timed out after 4 hours.", session_id
    )
