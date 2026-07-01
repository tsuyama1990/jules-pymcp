# jules-pymcp

MCP server that lets Claude orchestrate Google Jules — with enforced quality gates,
concurrent session management, and a complete fan-out/fan-in PR merge loop.

- Language: Python 3.13+
- Framework: FastMCP
- SDK: jules-agent-sdk
- License: Apache-2.0
- Fork of: [CodeAgentBridge/jules-mcp-server](https://github.com/CodeAgentBridge/jules-mcp-server)

---

## What this does

Claude calls MCP tools in this server to:

1. Decompose a large project into Jules-sized sub-tasks
2. Write `AGENTS.md` + integration tests, commit and push them to GitHub
3. Fire all Jules sessions concurrently (each gets quality rules + acceptance criteria injected)
4. Poll every 5 minutes until all PRs are open
5. Merge PRs one by one, gated by integration tests, resolving conflicts via Jules

Jules does the implementation. Claude does the reasoning.

---

## Architecture

```
Claude (reasoning)
  │
  └── MCP tools (this server)
        │
        ├── Jules API  ──► Jules sessions (concurrent)
        │                       │
        │                  SessionWatcher daemon (per session)
        │                       └── auto-sends self-critic when PR opens
        │
        └── gh CLI  ──► GitHub (AGENTS.md push, PR status, merge)
```

**Quality enforcement is deterministic, not stochastic.**
Every Jules prompt is wrapped with mandatory rules before the API call —
Jules cannot receive a task without them.

---

## When to use Jules vs Claude directly

Jules has real overhead that Claude coding directly does not:

| Cost | Jules | Claude directly |
|------|-------|----------------|
| Polling (waiting for PRs) | history_size × poll_count | zero |
| Prompt writing | 1 extra turn per task | zero |
| Review / error recovery | 1+ turns per failure | immediate fix in same turn |

**Jules pays off only when parallelism savings outweigh this overhead.**

### Use Jules when

- **N ≥ 3 independent tasks** that can run concurrently
- Each task is **large enough** that it would take Claude multiple turns to implement
- Tasks have **low coupling** (no cross-task dependencies mid-flight)
- You can tolerate Jules' ~15 min startup latency

### Use Claude directly when

- 1–2 tasks, or tasks that must run sequentially
- Fast iteration is needed (tight error → fix → retest loops)
- Tasks are small (Jules overhead > implementation time)
- Jules has already gotten stuck on this type of task before

### The break-even rule of thumb

If `N × estimated_turns_per_task > 10`, Jules is likely worth it.
If not, Claude coding directly is faster and cheaper.

---

## Setup

### 1. Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- [gh CLI](https://cli.github.com/) authenticated (`gh auth login`)
- Jules API key from [Google Jules](https://jules.google.com/)

### 2. Install

```bash
git clone https://github.com/tsuyama1990/jules-pymcp
cd jules-pymcp
uv sync
```

### 3. Environment variables

```bash
export JULES_API_KEY="your-jules-api-key"
```

Optional — override the default quality rules injected into every Jules prompt:

```bash
export JULES_QUALITY_RULES='["Rule A", "Rule B"]'   # JSON string array
```

### 4. MCP configuration (Claude Code / claude.ai)

Add to your `~/.claude/settings.json` (or equivalent MCP config):

```json
{
  "mcpServers": {
    "jules": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/jules-pymcp",
        "python", "-m", "jules_mcp"
      ],
      "env": {
        "JULES_API_KEY": "your-jules-api-key"
      }
    }
  }
}
```

---

## Before launching Jules — keep the PC awake

Jules sessions run for 15–60+ minutes. If the PC suspends mid-session, the
MCP server exits and Jules stalls (state stays `IN_PROGRESS` but nothing progresses).

**Run these in two tmux panes before calling `start_jules_batch`:**

```bash
# Pane 1 — sleep inhibitor (independent of Claude Code)
tmux new -d -s keep-awake 'scripts/keep_awake.sh 180'   # 3 hours; adjust as needed

# Pane 2 — session watcher (survives Claude Code exit)
# Run after start_jules_batch returns and you have session IDs:
tmux new -d -s jules-watch 'scripts/watch_jules.sh --file jules_sessions.json'
# or pass IDs directly:
# tmux new -d -s jules-watch 'scripts/watch_jules.sh sessions/abc123 sessions/def456'
```

When Jules is done: `tmux kill-session -t keep-awake && tmux kill-session -t jules-watch`

The watcher logs to `jules_watch.log` in the current directory — check it after waking up.

---

## Workflow

### Full fan-out/fan-in orchestration

```
Phase 0 — Contracts (Claude)
  Write integration tests defining interfaces between sub-projects.
  These gate every merge in Phase 3.

Phase 1 — Prep + Fire
  Call: start_jules_batch(repo_path, tasks, sub_projects, merge_order)
    ├── writes AGENTS.md to local repo
    ├── commits + pushes to GitHub  (Jules clones THIS)
    └── fires all Jules sessions concurrently
        └── each session: quality rules + acceptance criteria injected into prompt

Phase 2 — Wait for batch to complete (one Claude turn)
  Call wait_for_batch(session_ids) once. The MCP server polls Jules internally
  (60 s between checks) and returns only when all sessions reach a terminal
  state — consuming ONE Claude turn instead of 20+.

  ready=True   → all sessions done, pr_urls is complete → proceed to Phase 3
  ready=False  → timeout reached; check pending/failed fields, decide whether
                 to call wait_for_batch again or proceed with partial results.

  !! DO NOT call these tools during Phase 2 !!
    list_all_activities       — response is large and accumulates in context
    list_activities           — same problem
    get_activity              — unnecessary; self-critic is handled automatically
    get_session               — wait_for_batch already calls this internally
    wait_for_session_completion — single-session; use wait_for_batch for batches
    poll_batch + ScheduleWakeup — each wakeup re-sends full conversation history;
                                  use wait_for_batch to block in one turn instead

  Background (automatic, no action needed):
    SessionWatcher daemon per session
    └── detects PR open → auto-sends self-critic review to Jules
        (DRY, SOLID, BONSAI cleanup, coverage, mutation testing)
        Claude does NOT need to check activities or send self-critic manually.

Phase 3 — Merge loop (Claude)
  For each pr_url in merge_order:
    get_pr_status(pr_url)
      CI green + MERGEABLE  → merge_pr(pr_url)
      CI red               → send_session_message(session, "fix CI: <log>") → reschedule
      CONFLICTING          → get_pr_diff(pr_url)
                           → send_session_message(session, "resolve:\n<diff>") → reschedule
    run integration tests  → gate before next merge
```

### Phase 2 token cost — why wait_for_batch is preferred

Every Claude turn re-sends the entire conversation history as input tokens.
Polling Jules from Claude (via `poll_batch` + `ScheduleWakeup`) means each
wakeup on a long session is very expensive.

**`wait_for_batch` eliminates this entirely:** Claude calls it once, the MCP server
Python thread blocks polling Jules internally, and Claude resumes only when all
sessions are done. One turn consumed regardless of how long Jules takes.

---

## Tool reference

### Orchestration (use these)

| Tool | When to call |
|------|-------------|
| `start_jules_batch` | **Primary entry point.** Writes AGENTS.md, commits+pushes, fires Jules concurrently. |
| `wait_for_batch` | **Preferred Phase 2 tool.** Call once after `start_jules_batch`. Blocks internally until all sessions finish — one Claude turn consumed. |
| `poll_batch` | One-shot snapshot. Use only when you need a non-blocking check (e.g. after a user notification). Prefer `wait_for_batch`. |
| `create_agents_md` | Low-level. Use only if you need to review AGENTS.md before committing. |

### GitHub PR operations

| Tool | When to call |
|------|-------------|
| `get_pr_status` | Before merging. Returns `ci_passing`, `mergeable`, CI summary. |
| `merge_pr` | After `get_pr_status` confirms CI green + MERGEABLE. Default method: squash. |
| `get_pr_diff` | When `get_pr_status` shows `CONFLICTING`. Pass diff to Jules via `send_session_message`. |

### Jules sessions (low-level)

| Tool | Description |
|------|-------------|
| `create_session` | Single Jules session. Quality rules + self-critic auto-applied. |
| `create_batch_sessions` | Low-level batch fire. Prefer `start_jules_batch`. |
| `send_session_message` | Send a follow-up message to a running Jules session. |
| `get_session` / `list_sessions` | Inspect session state. |
| `approve_session_plan` | Approve Jules' plan when `require_plan_approval=True`. |
| `wait_for_session_completion` | Blocking poll for a single session. |

### Jules activities (low-level)

`get_activity`, `list_activities`, `list_all_activities` — inspect Jules' step-by-step activity log.

### Jules sources

`get_source`, `list_sources`, `get_all_sources` — list GitHub repos connected to Jules.

---

## Quality enforcement

Every Jules prompt is deterministically wrapped with:

1. **Mandatory quality rules** — ruff ALL, mypy strict, bandit, pytest ≥90% coverage
2. **Development order** — Blueprint → CDD (Pydantic contracts) → TDD → Implementation
3. **Acceptance criteria** — per-task checklist Jules must check off before opening the PR
4. **Self-critic review** — auto-sent when PR opens (DRY, all 5 SOLID principles, BONSAI cleanup,
   static checks, mutation testing ≥80%)

Jules cannot skip these — they are injected by `build_enforced_prompt()` before every API call.

**AGENTS.md** is also written to the repo before Jules starts, giving Jules stochastic context
about sub-project structure, integration test paths, and merge order.

---

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`) runs the `quality-gate` job on every PR:

```
ruff check --select ALL
ruff format --check
mypy --strict jules_mcp/
bandit -c pyproject.toml -r jules_mcp/
pytest  # --cov-fail-under=90, --cov-branch enforced via pyproject.toml
```

**Add `quality-gate` as a required status check in GitHub branch protection rules**
to block Jules PRs that fail quality gates from merging.

---

## Development

```bash
# Install with dev deps
uv sync

# Run tests (118 tests, ≥90% branch+line coverage)
uv run pytest

# Lint
uv run ruff check .
uv run ruff format .

# Type check
uv run mypy jules_mcp/

# Security scan
uv run bandit -c pyproject.toml -r jules_mcp/

# Mutation testing (optional, slow)
uv run mutmut run
```

### Pre-commit hooks

```bash
uv run pre-commit install   # installs ruff + mypy + bandit hooks
```

### Module map

```
jules_mcp/
  jules_mcp.py        MCP tool definitions (FastMCP server)
  batch.py            Concurrent session creation + polling (BatchTaskSpec, poll_batch, wait_for_batch)
  github_ops.py       gh/git CLI wrappers (PR status, merge, diff, commit+push)
  agents_md.py        AGENTS.md generation
  prompt.py           build_enforced_prompt — injects quality rules + acceptance criteria
  self_critic.py      Self-critic review template (DRY, SOLID, BONSAI, static checks)
  session_watcher.py  Daemon thread — polls Jules, auto-sends self-critic on PR open
  cli.py              jules-run CLI — create or monitor a single session with live logs

scripts/
  keep_awake.sh       Standalone sleep inhibitor — run in tmux before Jules batch
  watch_jules.sh      Shell wrapper for watch_jules.py
  watch_jules.py      Polls Jules sessions; logs to jules_watch.log; survives Claude Code exit
  jules-mcp.service   systemd user service template for a persistent MCP server
```

---

## License

Apache License 2.0. See [LICENSE](LICENSE).
