"""CLI for creating or monitoring a single Jules session with live activity logs."""

from __future__ import annotations

import argparse
import os
import sys
import time

from jules_agent_sdk import JulesClient
from jules_agent_sdk.models import SessionState

from jules_mcp.prompt import build_enforced_prompt
from jules_mcp.session_watcher import watch_session_for_pr


def _make_client() -> JulesClient:
    """Return a JulesClient authenticated from JULES_API_KEY."""
    api_key = os.environ.get("JULES_API_KEY")
    if not api_key:
        print("Error: JULES_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    return JulesClient(api_key)


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="jules-run",
        description="Run or monitor a Jules session with live activity logs.",
    )
    parser.add_argument(
        "--prompt",
        help="Prompt for the session (required unless --session-id is given)",
    )
    parser.add_argument(
        "--session-id",
        dest="session_id",
        help="Existing session ID to monitor — skips session creation",
    )
    parser.add_argument(
        "--source",
        help="Jules source ID, e.g. sources/github/owner/repo",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="Starting branch (default: main)",
    )
    parser.add_argument("--title", help="Session title")
    parser.add_argument(
        "--acceptance-criteria",
        dest="acceptance_criteria",
        nargs="*",
        default=[],
        metavar="CRITERION",
        help="Acceptance criteria passed to the quality enforcer",
    )
    return parser


def _tail_activities(client: JulesClient, session_id: str) -> None:  # noqa: PLR0912
    """Poll and print new activities until the session reaches a terminal state."""
    printed: set[str] = set()
    terminal = {SessionState.COMPLETED, SessionState.FAILED}

    print(
        "Polling activities (Ctrl+C to stop; the session keeps running on Jules)...",
        flush=True,
    )

    while True:
        try:
            session = client.sessions.get(session_id)
            for act in sorted(
                client.activities.list_all(session_id),
                key=lambda a: a.create_time or "",
            ):
                act_key = act.id or f"{act.create_time}:{act.description}"
                if act_key in printed:
                    continue
                printed.add(act_key)
                ts = act.create_time.split("T")[-1][:8] if act.create_time else "??:??:??"
                origin = f" [{act.originator}]" if act.originator else ""
                print(f"[{ts}]{origin} {act.description}", flush=True)
                if act.plan_generated:
                    print(
                        f"  -> Plan: {act.plan_generated.get('planSummary', '')}",
                        flush=True,
                    )
                if act.plan_approved:
                    print("  -> Plan approved.", flush=True)
                if act.progress_updated:
                    pct = act.progress_updated.get("progressPercent", 0)
                    msg = act.progress_updated.get("statusMessage", "")
                    print(f"  -> Progress: {pct}% — {msg}", flush=True)
                if act.agent_messaged:
                    raw = act.agent_messaged.get("message", "")
                    max_len = 150
                    snippet = raw[:max_len] + "..." if len(raw) > max_len else raw
                    print(f"  -> Agent: {snippet}", flush=True)
                if act.session_completed:
                    print("  -> Session completed.", flush=True)
                if act.session_failed:
                    reason = act.session_failed.get("failureReason", "")
                    print(f"  -> Session failed: {reason}", flush=True)

            if session.state in terminal:
                print(f"\nTerminal state: {session.state.value}", flush=True)
                for out in session.outputs:
                    if out.pull_request and out.pull_request.url:
                        print(f"PR: {out.pull_request.url}", flush=True)
                break

            time.sleep(15)

        except KeyboardInterrupt:
            print(
                "\nPolling stopped. Jules session continues on Google Jules.",
                flush=True,
            )
            break
        except Exception as exc:  # noqa: BLE001
            print(f"\nPolling error: {exc}", flush=True)
            time.sleep(15)


def main() -> None:
    """Entry point for the jules-run CLI."""
    args = _build_parser().parse_args()
    client = _make_client()

    if args.session_id:
        session_id: str = args.session_id
        print(f"Monitoring existing Jules session: {session_id}", flush=True)
        session = client.sessions.get(session_id)
    else:
        if not args.prompt:
            print(
                "Error: --prompt is required when --session-id is not specified.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not args.source:
            print(
                "Error: --source is required when creating a new session.",
                file=sys.stderr,
            )
            sys.exit(1)

        full_prompt = build_enforced_prompt(args.prompt, args.acceptance_criteria)
        print(f"Creating Jules session: {args.title or '(no title)'}", flush=True)
        print(f"Source: {args.source}  Branch: {args.branch}", flush=True)

        session = client.sessions.create(
            prompt=full_prompt,
            source=args.source,
            starting_branch=args.branch,
            title=args.title,
            require_plan_approval=False,
        )
        name = session.name
        if name is None:
            print("Error: Jules returned a session with no ID.", file=sys.stderr)
            sys.exit(1)
        session_id = name

    print(f"\n{'=' * 50}", flush=True)
    print(f"Session ID : {session_id}", flush=True)
    print(f"State      : {session.state.value}", flush=True)
    print(f"{'=' * 50}\n", flush=True)

    print("Starting background self-critic watcher...", flush=True)
    watch_session_for_pr(client, session_id)

    _tail_activities(client, session_id)
