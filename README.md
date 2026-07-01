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

Phase 2 — Wait for user notification (zero token cost while idle)
  Do NOT schedule automatic polling timers. Token cost per wakeup is
  proportional to accumulated conversation history — polling every 5 min
  on a long session becomes very expensive.

  Instead:
    1. After start_jules_batch returns, tell the user which session IDs
       were created and ask them to say "PR ready" (or similar) once
       Jules has opened a pull request.
    2. When the user sends that message, call poll_batch(session_ids)
       once to get the current state and pr_urls.
    3. ready=True   → proceed to Phase 3
       ready=False  → report which sessions are still pending;
                      ask the user to notify again when done.

  !! DO NOT call these tools during Phase 2 !!
    list_all_activities   — response is large and accumulates in context
    list_activities       — same problem
    get_activity          — unnecessary; self-critic is handled automatically
    get_session           — poll_batch already calls this internally
    wait_for_session_completion — blocks and adds verbose output to context

  poll_batch is the only tool needed. It returns ready/pr_urls/pending/failed —
  no activity logs, no raw session objects. One call per user notification.

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

### Phase 2 token cost — why manual notification is preferred

Every scheduled wakeup re-sends the entire conversation history as input tokens.
On a long batch (many sessions, verbose tool outputs), this makes 5-minute timers
very expensive.

**Preferred flow:** after `start_jules_batch`, Claude asks the user to send a message
when Jules has opened a PR. Claude then calls `poll_batch` once on demand.
No ScheduleWakeup, no recurring cost.

---

## Tool reference

### Orchestration (use these)

| Tool | When to call |
|------|-------------|
| `start_jules_batch` | **Primary entry point.** Writes AGENTS.md, commits+pushes, fires Jules concurrently. |
| `poll_batch` | Call every 5 min after `start_jules_batch`. Returns `ready=True` + `pr_urls` when done. |
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
  batch.py            Concurrent session creation + polling (BatchTaskSpec, poll_batch)
  github_ops.py       gh/git CLI wrappers (PR status, merge, diff, commit+push)
  agents_md.py        AGENTS.md generation
  prompt.py           build_enforced_prompt — injects quality rules + acceptance criteria
  self_critic.py      Self-critic review template (DRY, SOLID, BONSAI, static checks)
  session_watcher.py  Daemon thread — polls Jules, auto-sends self-critic on PR open
```

---

## License

Apache License 2.0. See [LICENSE](LICENSE).
