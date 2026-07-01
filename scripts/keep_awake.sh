#!/usr/bin/env bash
# Standalone sleep inhibitor — prevents PC suspend during Jules sessions.
# Runs independently of Claude Code / the MCP server, so the PC stays awake
# even if Claude Code exits or was never connected.
#
# Usage:
#   scripts/keep_awake.sh [MINUTES]          # block for N minutes (default: 180)
#   tmux new -d -s keep-awake 'scripts/keep_awake.sh 180'
#
# Blocks: sleep, idle, lid-close suspend.
# Kill it manually when Jules sessions are done: tmux kill-session -t keep-awake

set -euo pipefail

MINUTES=${1:-180}
SECONDS_=$((MINUTES * 60))

echo "Sleep inhibitor active for ${MINUTES} min (PID $$)." >&2
echo "PC will not suspend. Kill this process when Jules sessions are done." >&2
echo "  tmux kill-session -t keep-awake" >&2
echo "" >&2

exec systemd-inhibit \
    --what=sleep:idle:handle-lid-switch \
    --why="Jules coding sessions running" \
    --mode=block \
    sleep "$SECONDS_"
