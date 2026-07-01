#!/usr/bin/env bash
# Thin wrapper — resolves project root and runs watch_jules.py via uv.
#
# Usage:
#   scripts/watch_jules.sh sessions/abc123 sessions/def456
#   scripts/watch_jules.sh --file jules_sessions.json
#   tmux new -d -s jules-watch "scripts/watch_jules.sh --file jules_sessions.json"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

exec uv run --directory "$PROJECT_ROOT" python "$SCRIPT_DIR/watch_jules.py" "$@"
