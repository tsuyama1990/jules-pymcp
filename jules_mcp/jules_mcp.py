#  Copyright (C) 2025 Yurii Serhiichuk
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import os
from typing import Any, Final

from fastmcp import FastMCP
from jules_agent_sdk import JulesClient, models
from mcp.types import ToolAnnotations

from jules_mcp import agents_md as _agents_md
from jules_mcp import github_ops as _github_ops
from jules_mcp.batch import (
    BatchPollResult,
    BatchSessionResult,
    BatchTaskSpec,
    create_batch,
    poll_batch,
)
from jules_mcp.prompt import build_enforced_prompt
from jules_mcp.session_watcher import watch_session_for_pr

version: Final[str] = "0.1.3"

_jules_client: JulesClient | None = None


def jules(api_key: str | None = None) -> JulesClient:
    """Get a singleton JulesClient instance.

    The API key is read from the JULES_API_KEY environment variable if not provided.
    """
    global _jules_client
    if _jules_client is None:
        if api_key is None:
            api_key = os.getenv("JULES_API_KEY")
        if not api_key:
            raise ValueError(
                "Jules API key not provided. Please set the JULES_API_KEY environment variable or explicitly provide it."
            )
        _jules_client = JulesClient(api_key)
    return _jules_client


mcp = FastMCP("Jules MCP Server", version=version)


# -------------------- Sources --------------------
@mcp.tool(
    name="get_source",
    title="Get source",
    description="Get a single source by ID (e.g., sources/abc123 or abc123)",
    tags={"sources"},
    annotations=ToolAnnotations(
        title="Get Jules source by ID",
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
        openWorldHint=True,
    ),
)
def get_source(source_id: str) -> models.Source:
    """Get a single source by ID.

    Args:
        source_id: The ID or full name of the source. For GitHub sources, this is the Jules source ID, e.g. 'sources/abc123'.
    """
    result = jules().sources.get(source_id)
    return result


@mcp.tool(
    name="list_sources",
    title="List sources (paginated)",
    description="List sources with optional filter and pagination; returns items and nextPageToken.",
    tags={"sources"},
)
def list_sources(
    filter_str: str | None = None,
    page_size: int | None = None,
    page_token: str | None = None,
) -> dict[str, Any]:
    """List sources (paginated).

    Args:
        filter_str: Filter expression per AIP-160. Currently supports filtering by name, e.g. "name=sources/source1 OR name=sources/source2".
        page_size: Max number of sources to return.
        page_token: Token from a previous call to retrieve the next page.

    Returns:
        Dict with keys:
            - sources: list[Source]
            - nextPageToken: Optional[str]
    """
    result = jules().sources.list(
        filter_str=filter_str, page_size=page_size, page_token=page_token
    )
    return result


@mcp.tool(
    name="get_all_sources",
    title="Get all sources",
    description="Get all sources with optional filtering (auto-pagination).",
    tags={"sources"},
)
def get_all_sources(filter_str: str | None = None) -> list[models.Source]:
    """Get all sources (auto-pagination).

    Args:
        filter_str: The filter expression for listing sources, based on AIP-160.
            If not set, all sources will be returned. Currently only supports filtering by name,
            which can be used to filter by a single source or multiple sources separated by OR.
            Example: 'name=sources/source1 OR name=sources/source2'
    """
    result = jules().sources.list_all(filter_str=filter_str)
    return result


# -------------------- Sessions --------------------
@mcp.tool(
    name="create_session",
    title="Create session",
    description="Create a new Jules session for a given source and prompt.",
    tags={"sessions"},
)
def create_session(
    prompt: str,
    source: str,
    starting_branch: str | None = None,
    title: str | None = None,
    require_plan_approval: bool = False,
    auto_self_review: bool = True,
) -> models.Session:
    """Create a new session.

    Args:
        prompt: The prompt to start the session with.
        source: The source to use (e.g., 'sources/abc123').
        starting_branch: Optional starting branch for GitHub repos.
        title: Optional human-friendly title for the session.
        require_plan_approval: If True, the plan requires explicit approval before execution.
        auto_self_review: If True (default), sends a strict self-critic review to Jules
            automatically once the PR is opened.
    """
    client = jules()
    session = client.sessions.create(
        prompt=build_enforced_prompt(prompt),
        source=source,
        starting_branch=starting_branch,
        title=title,
        require_plan_approval=require_plan_approval,
    )
    if auto_self_review and session.name:
        watch_session_for_pr(client, session.name)
    return session


@mcp.tool(
    name="get_session",
    title="Get session",
    description="Get a single session by ID.",
    tags={"sessions"},
)
def get_session(session_id: str) -> models.Session:
    """Get a session by ID.

    Args:
        session_id: The session ID or full name (e.g., 'sessions/abc123' or 'abc123').
    """
    return jules().sessions.get(session_id)


@mcp.tool(
    name="list_sessions",
    title="List sessions (paginated)",
    description="List sessions with pagination; returns items and nextPageToken.",
    tags={"sessions"},
)
def list_sessions(
    page_size: int | None = None, page_token: str | None = None
) -> dict[str, Any]:
    """List sessions (paginated).

    Args:
        page_size: Max number of sessions to return.
        page_token: Token from a previous call to retrieve the next page.

    Returns:
        Dict with keys:
            - sessions: list[Session]
            - nextPageToken: Optional[str]
    """
    return jules().sessions.list(page_size=page_size, page_token=page_token)


@mcp.tool(
    name="approve_session_plan",
    title="Approve session plan",
    description="Approve the pending plan for a session that requires approval.",
    tags={"sessions"},
)
def approve_session_plan(session_id: str) -> dict[str, str]:
    """Approve a plan in a session.

    Args:
        session_id: The session ID or full name.

    Returns:
        Simple status confirmation.
    """
    jules().sessions.approve_plan(session_id)
    return {"status": "approved"}


@mcp.tool(
    name="send_session_message",
    title="Send user message to session",
    description="Send a user message (prompt) to an existing session.",
    tags={"sessions"},
)
def send_session_message(session_id: str, prompt: str) -> dict[str, str]:
    """Send a message to a session.

    Args:
        session_id: The session ID or full name.
        prompt: The message/prompt from the user.

    Returns:
        Simple status confirmation.
    """
    jules().sessions.send_message(session_id, prompt)
    return {"status": "sent"}


@mcp.tool(
    name="wait_for_session_completion",
    title="Wait for session completion",
    description="Poll the session until completion or failure, with optional timeout.",
    tags={"sessions"},
)
def wait_for_session_completion(
    session_id: str,
    poll_interval: int = 5,
    timeout: int | None = 600,
) -> models.Session:
    """Wait for a session to reach a terminal state.

    Args:
        session_id: The session ID or full name.
        poll_interval: Seconds between polling requests (default: 5).
        timeout: Optional timeout in seconds (default: 600). Set None for no timeout.
    """
    return jules().sessions.wait_for_completion(
        session_id, poll_interval=poll_interval, timeout=timeout
    )


# -------------------- Activities --------------------
@mcp.tool(
    name="get_activity",
    title="Get activity",
    description="Get a single activity by ID within a session.",
    tags={"activities"},
)
def get_activity(session_id: str, activity_id: str) -> models.Activity:
    """Get an activity by ID.

    Args:
        session_id: The session ID or full name.
        activity_id: The activity ID.
    """
    return jules().activities.get(session_id, activity_id)


@mcp.tool(
    name="list_activities",
    title="List activities (paginated)",
    description="List activities for a session with pagination; returns items and nextPageToken.",
    tags={"activities"},
)
def list_activities(
    session_id: str,
    page_size: int | None = None,
    page_token: str | None = None,
) -> dict[str, Any]:
    """List activities for a session (paginated).

    Args:
        session_id: The session ID or full name.
        page_size: Max number of activities to return.
        page_token: Token from a previous call to retrieve the next page.

    Returns:
        Dict with keys:
            - activities: list[Activity]
            - nextPageToken: Optional[str]
    """
    return jules().activities.list(
        session_id, page_size=page_size, page_token=page_token
    )


@mcp.tool(
    name="list_all_activities",
    title="List all activities",
    description="List all activities for a session (auto-pagination).",
    tags={"activities"},
)
def list_all_activities(session_id: str) -> list[models.Activity]:
    """List all activities for a session (auto-pagination)."""
    return jules().activities.list_all(session_id)


# -------------------- Batch orchestration --------------------
@mcp.tool(
    name="create_batch_sessions",
    title="Create batch sessions (concurrent)",
    description=(
        "Fire multiple Jules coding sessions concurrently. "
        "Each task gets quality rules injected and a self-critic review scheduled. "
        "Returns one result per task with session ID and initial state. "
        "After firing, call poll_batch every 5 minutes until ready=True, then merge PRs."
    ),
    tags={"batch"},
)
def create_batch_sessions(
    tasks: list[BatchTaskSpec],
    auto_self_review: bool = True,
) -> list[BatchSessionResult]:
    """Fire multiple Jules sessions concurrently.

    Args:
        tasks: List of sub-tasks to execute in parallel. Each must have a unique label.
        auto_self_review: If True (default), sends self-critic review to each session
            automatically once its PR is opened.

    Returns:
        One result per task with session_id, initial state, or error if creation failed.

    """
    return create_batch(jules(), tasks, auto_self_review)


@mcp.tool(
    name="poll_batch",
    title="Poll batch (call every 5 min)",
    description=(
        "Check status of all sessions in a batch — non-blocking snapshot. "
        "Call every 5 minutes after create_batch_sessions. "
        "When ready=True every session has finished: pr_urls lists PRs to merge in order, "
        "failed lists sessions that need attention. "
        "If ready=False, reschedule and call again in 5 minutes."
    ),
    tags={"batch"},
)
def poll_batch_tool(session_ids: list[str]) -> BatchPollResult:
    """Poll all sessions and return a ready flag plus PR URLs.

    Args:
        session_ids: List of session IDs returned by create_batch_sessions.

    Returns:
        ready: True when all sessions have reached a terminal state.
        pr_urls: PR URLs for completed sessions, in input order.
        pending: Session IDs still running.
        failed: Session IDs that failed or errored.
        statuses: Full status detail for each session.

    """
    return poll_batch(jules(), session_ids)


# -------------------- Top-level orchestration entry point --------------------
@mcp.tool(
    name="start_jules_batch",
    title="Start Jules batch (use this, not create_batch_sessions)",
    description=(
        "Single entry point for launching a Jules batch. "
        "Enforces the full prep sequence in order: "
        "(1) writes AGENTS.md to the local repo, "
        "(2) commits and pushes it to GitHub so Jules sees it on clone, "
        "(3) fires all Jules sessions concurrently with quality rules injected. "
        "Returns session_ids — pass them to poll_batch every 5 minutes."
    ),
    tags={"batch"},
)
def start_jules_batch(
    repo_path: str,
    tasks: list[BatchTaskSpec],
    sub_projects: list[str],
    integration_test_path: str = "tests/integration",
    merge_order: list[str] | None = None,
    extra_rules: list[str] | None = None,
    branch: str = "main",
    auto_self_review: bool = True,
) -> dict[str, Any]:
    """Write AGENTS.md, commit+push, then fire all Jules sessions concurrently.

    Args:
        repo_path: Absolute path to the local repository root.
        tasks: Sub-tasks to execute in parallel. Each needs a unique label.
        sub_projects: Sub-project names written into AGENTS.md.
        integration_test_path: Integration test path for AGENTS.md (default: tests/integration).
        merge_order: Merge order for AGENTS.md, leaf-first.
        extra_rules: Additional project-specific rules for AGENTS.md.
        branch: Branch to push AGENTS.md to (default: main).
        auto_self_review: Auto-send self-critic when each PR opens (default: True).

    Returns:
        session_ids: Pass to poll_batch every 5 min until ready=True.
        results: Per-task creation result with initial state.
        pushed_to: Branch AGENTS.md was pushed to.
    """
    _agents_md.write_agents_md(
        repo_path=repo_path,
        sub_projects=sub_projects,
        integration_test_path=integration_test_path,
        merge_order=merge_order,
        extra_rules=extra_rules,
    )
    _github_ops.commit_and_push(
        repo_path=repo_path,
        files=["AGENTS.md"],
        message="chore: update AGENTS.md for Jules batch",
        branch=branch,
    )
    results = create_batch(jules(), tasks, auto_self_review)
    return {
        "pushed_to": branch,
        "session_ids": [r.session_id for r in results if r.session_id],
        "results": [r.model_dump() for r in results],
    }


# -------------------- GitHub operations --------------------
@mcp.tool(
    name="get_pr_status",
    title="Get PR status",
    description=(
        "Check the CI status and mergeability of a GitHub pull request. "
        "Returns mergeable flag, merge state, and whether all CI checks are passing. "
        "Use this before merge_pr to confirm the PR is ready."
    ),
    tags={"github"},
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, destructiveHint=False),
)
def get_pr_status(pr_url: str) -> dict[str, Any]:
    """Check CI status and mergeability of a GitHub pull request.

    Args:
        pr_url: Full GitHub PR URL, e.g. 'https://github.com/org/repo/pull/42'.
    """
    return _github_ops.get_pr_status(pr_url).model_dump()


@mcp.tool(
    name="merge_pr",
    title="Merge pull request",
    description=(
        "Merge a GitHub pull request. Always call get_pr_status first to confirm "
        "CI is green and the PR is not conflicting before merging. "
        "Deletes the source branch after merge."
    ),
    tags={"github"},
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False),
)
def merge_pr(pr_url: str, method: str = "squash") -> dict[str, Any]:
    """Merge a GitHub pull request.

    Args:
        pr_url: Full GitHub PR URL, e.g. 'https://github.com/org/repo/pull/42'.
        method: Merge method — 'squash' (default), 'merge', or 'rebase'.
    """
    return _github_ops.merge_pr(pr_url, method=method).model_dump()


@mcp.tool(
    name="get_pr_diff",
    title="Get PR diff",
    description=(
        "Return the full unified diff of a GitHub pull request. "
        "Use this when get_pr_status reports conflicts: pass the diff to Jules via "
        "send_session_message so it can rebase and resolve conflicts."
    ),
    tags={"github"},
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, destructiveHint=False),
)
def get_pr_diff(pr_url: str) -> str:
    """Return the full unified diff of a GitHub pull request.

    Args:
        pr_url: Full GitHub PR URL, e.g. 'https://github.com/org/repo/pull/42'.
    """
    return _github_ops.get_pr_diff(pr_url)


@mcp.tool(
    name="create_agents_md",
    title="Create AGENTS.md",
    description=(
        "Generate and write AGENTS.md to a local repository. "
        "Call this before firing any Jules batch so Jules understands the project "
        "structure, integration test contracts, merge order, and quality rules. "
        "Returns the written content for review."
    ),
    tags={"github"},
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True, destructiveHint=False),
)
def create_agents_md(
    repo_path: str,
    sub_projects: list[str],
    integration_test_path: str = "tests/integration",
    merge_order: list[str] | None = None,
    extra_rules: list[str] | None = None,
) -> str:
    """Generate and write AGENTS.md to a local repository.

    Args:
        repo_path: Absolute path to the local repository root.
        sub_projects: List of sub-project names or paths Jules will work on.
        integration_test_path: Path to integration tests (default: 'tests/integration').
        merge_order: Ordered list of sub-projects for merge sequencing, leaf-first.
        extra_rules: Additional project-specific rules to append.
    """
    return _agents_md.write_agents_md(
        repo_path=repo_path,
        sub_projects=sub_projects,
        integration_test_path=integration_test_path,
        merge_order=merge_order,
        extra_rules=extra_rules,
    )


def start_mcp() -> None:
    mcp.run()


if __name__ == "__main__":
    start_mcp()
