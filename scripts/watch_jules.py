"""Standalone Jules session watcher — survives Claude Code exits when run in tmux.

Polls Jules sessions until all reach a terminal state. Logs to stdout and
jules_watch.log in the current directory.

Usage:
    # Pass session IDs directly:
    uv run python scripts/watch_jules.py sessions/abc123 sessions/def456

    # Or read from the JSON file written by start_jules_batch:
    uv run python scripts/watch_jules.py --file jules_sessions.json

    # Custom poll interval (seconds, default 120):
    uv run python scripts/watch_jules.py --interval 60 sessions/abc123

    # Recommended: run inside tmux so it survives Claude Code exit:
    tmux new -d -s jules-watch 'scripts/watch_jules.sh sessions/abc123'
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time


def _log(msg: str, log_path: str) -> None:
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(log_path, "a") as f:
        f.write(line + "\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="watch_jules",
        description="Poll Jules sessions until all are terminal.",
    )
    parser.add_argument(
        "session_ids",
        nargs="*",
        metavar="SESSION_ID",
        help="One or more session IDs to watch (e.g. sessions/abc123).",
    )
    parser.add_argument(
        "--file",
        metavar="PATH",
        help="JSON file with a 'session_ids' key (written by start_jules_batch).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=120,
        metavar="SECONDS",
        help="Poll interval in seconds (default: 120).",
    )
    parser.add_argument(
        "--log",
        default="jules_watch.log",
        metavar="PATH",
        help="Log file path (default: jules_watch.log in current directory).",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    session_ids: list[str] = list(args.session_ids)

    if args.file:
        with open(args.file) as f:
            data = json.load(f)
        file_ids: list[str] = data.get("session_ids", [])
        if not file_ids:
            print(f"Error: no 'session_ids' key in {args.file}", file=sys.stderr)
            sys.exit(1)
        session_ids.extend(file_ids)

    if not session_ids:
        print("Error: provide session IDs as arguments or via --file.", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("JULES_API_KEY", "")
    if not api_key:
        print("Error: JULES_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    from jules_agent_sdk import JulesClient

    client = JulesClient(api_key)
    log = args.log
    terminal = {"COMPLETED", "FAILED"}

    _log(f"Watching {len(session_ids)} session(s) — poll every {args.interval}s", log)
    for sid in session_ids:
        _log(f"  {sid}", log)

    while True:
        try:
            done: list[tuple[str, str, str | None]] = []
            pending: list[tuple[str, str]] = []

            for sid in session_ids:
                session = client.sessions.get(sid)
                state = session.state.value
                pr_url = next(
                    (
                        o.pull_request.url
                        for o in session.outputs
                        if o.pull_request and o.pull_request.url
                    ),
                    None,
                )
                if state in terminal:
                    done.append((sid, state, pr_url))
                else:
                    pending.append((sid, state))

            _log(f"Done: {len(done)}/{len(session_ids)}  Pending: {len(pending)}", log)
            for sid, state, pr_url in done:
                pr_str = f" -> {pr_url}" if pr_url else " (no PR)"
                _log(f"  DONE   {sid}: {state}{pr_str}", log)
            for sid, state in pending:
                _log(f"  WAIT   {sid}: {state}", log)

            if not pending:
                _log("All sessions terminal. Done.", log)
                break

            time.sleep(args.interval)

        except KeyboardInterrupt:
            _log("Interrupted. Jules sessions continue on Google Jules.", log)
            break
        except Exception as exc:  # noqa: BLE001
            _log(f"Poll error: {exc}", log)
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
