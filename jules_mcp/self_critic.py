"""Self-critic review template — sent to Jules automatically once a PR is opened."""

from __future__ import annotations


def build_self_critic_prompt() -> str:
    """Return the mandatory self-critic review instruction sent after PR creation."""
    return """\
## Final Self-Critic Review (Mandatory — Non-Negotiable)

You are now entering the **Final Self-Critic Review** phase.
Your implementation has been submitted as a PR. Before this is merged, you must \
perform one last critical review of your own code.

**OPERATIONAL INSTRUCTIONS**:
1. **SELF-CORRECTION**: Do NOT just output a report. YOU MUST FIX THE CODE YOURSELF. \
If you find any issues, use your tools to modify the files, run tests, and push fixes to this PR.
2. **POLISH FOCUS**: Focus on architectural elegance, strict typing, clean code patterns, \
and ensuring no regressions.

**THINKING BLOCK**: Begin your response with a `<thought>` block where you perform an \
"Audit Gap Analysis" — identify every discrepancy before applying any fix.

---

## Audit Checklists

### 1. Functional Implementation & Scope
- [ ] **Logic Correctness**: Is the logic correct, optimal, and efficient? \
Did refactoring accidentally break anything?
- [ ] **No Half-Finished Code**: No `TODO`, `FIXME`, empty functions, `pass`, `...`, \
or placeholder log outputs.
- [ ] **Preservation of Existing Assets**: Were existing tests or code unnecessarily deleted?

### 2. DRY — Don't Repeat Yourself
- [ ] **No duplicated logic**: Search for copy-pasted blocks. Every duplicated logic \
must be extracted into a shared function, method, or base class.
- [ ] **No duplicated constants**: Any value used in more than one place must be a named constant.
- [ ] **No duplicated type definitions**: If two Pydantic models share fields, \
consider a common base model.

### 3. SOLID Principles
- [ ] **S — Single Responsibility**: Every class and function does exactly one thing. \
If you need "and" to describe what it does, split it.
- [ ] **O — Open/Closed**: Classes are open for extension, closed for modification. \
New behaviour is added via subclassing or composition, not by editing existing logic.
- [ ] **L — Liskov Substitution**: Every subclass can replace its parent without \
breaking callers. No subclass narrows a parameter type or raises new exceptions \
not declared by the parent.
- [ ] **I — Interface Segregation**: No class is forced to depend on methods it does \
not use. Large protocols/ABCs must be split into smaller, focused ones.
- [ ] **D — Dependency Inversion**: High-level modules depend on abstractions \
(protocols/ABCs), not on concrete implementations. Inject dependencies; \
do not instantiate them inside business logic.

### 4. Architecture, Design & Maintainability
- [ ] **Simplicity (YAGNI)**: No over-engineering. Three similar lines is better than \
a premature abstraction.
- [ ] **No Hardcoded Settings**: All config via Pydantic settings or a config module.

### 5. Data Integrity & Security
- [ ] **Strict Typing**: Pydantic models used at all module boundaries.
- [ ] **Schema Rigidity**: `model_config = ConfigDict(extra="forbid", strict=True)` \
on all schemas.
- [ ] **Security**: No hardcoded secrets or paths. No injection risks.

### 6. Scalability & Efficiency
- [ ] **Memory Safety**: No loading entire datasets into memory. Use iterators/streaming.
- [ ] **I/O Efficiency**: No I/O inside tight loops. Use batching.

### 7. Test Quality
- [ ] **TDD Traceability**: Tests exist for every requirement (happy path + unhappy path).
- [ ] **Edge Cases**: Error paths and boundary conditions are tested.
- [ ] **All Tests Pass**: Run pytest and confirm zero failures.

---

## ZERO TOLERANCE FOR HARDCODING
Search your own code for magic numbers, magic strings, unexplained constants, \
hardcoded paths, and credentials. Extract every one to config.

---

## BONSAI — Codebase Pruning & Alignment (Mandatory after self-critic fixes)

Execute all four phases in order. Each phase has an interim gate before proceeding.

### Phase 1 — Pruning (Dead Code Elimination)
- [ ] Identify and **completely remove** deprecated logic, dead code branches, \
and unused imports. Use `ruff check --select F401,F811` to find unused imports.
- [ ] Delete orphaned test files, obsolete test cases, stale mocks, and unused \
fixture data. Leftover tests for deleted code pollute the suite and hide real failures.
- [ ] **Interim gate**: Run `ruff check . && mypy --strict .` — zero errors before continuing.

### Phase 2 — Shaping (Integration & Refactoring)
- [ ] Refactor new code to use existing shared utilities (logging, error handling, \
config). Do not reinvent what already exists in the codebase.
- [ ] Find and consolidate all duplicated logic or copy-pasted blocks introduced \
during development. Apply DRY — extract to a shared function or base class.
- [ ] **Interim gate**: Run `pytest --tb=short` — all tests still pass after reshaping.

### Phase 3 — Potting (Interface Boundary Alignment)
- [ ] Verify that all entry points (API routes, MCP tools, CLI commands, public \
functions) correctly route to the latest implementation — no stale references.
- [ ] Audit interface definitions: remove deprecated parameters/endpoints, \
register newly added capabilities. Ensure Pydantic schemas reflect the current \
contract exactly.
- [ ] **Interim gate**: Manually trace at least one request through every entry \
point and confirm it reaches the correct implementation.

### Phase 4 — Finishing (Documentation Sync)
- [ ] Update README as the single source of truth: setup steps, dependencies, \
and architecture must accurately reflect the current state.
- [ ] Update inline docstrings and type stubs for any public API that changed.
- [ ] **Interim gate**: All documentation examples must be runnable as-is.

---

## MUST PASS STATIC CHECKS (Non-Negotiable)
Before completing this review, confirm ALL of the following pass with zero failures:
1. `pytest --tb=short --cov=. --cov-branch --cov-report=term-missing --cov-fail-under=90`
   - All tests pass.
   - Overall line coverage ≥ 90 %.
   - Branch coverage ≥ 90 %. Review every uncovered branch in the `term-missing` report.
   - If coverage is below threshold: add tests — do NOT raise the ignore threshold.
2. `ruff check . && ruff format .` — zero violations.
3. `mypy --strict .` — zero errors.
4. `bandit -c pyproject.toml -r .` — zero medium/high severity findings.
   - No use of `eval`, `exec`, `pickle`, `subprocess(shell=True)`, hardcoded secrets,
     or any other pattern flagged by bandit. Fix the code — do not add `# nosec` to hide issues.

## MUTATION TESTING — Verify Test Quality (not just coverage)
Coverage ≥ 90 % proves tests *run* the code. Mutation testing proves tests *catch bugs*.
Run `mutmut run` on the modules you changed and check the survival rate:
- A surviving mutant means a test that should have failed did not — the test is incomplete.
- For every surviving mutant: strengthen the assertion or add a new test case.
- Target: mutation score ≥ 80 % on all newly written modules.
- If `mutmut` takes too long (> 5 min): run with `--paths-to-mutate <changed_module>` to scope it.

**CRITICAL LOOP RULE**: If you modify even a single line during this review or \
BONSAI phases, you MUST restart the entire static validation sequence from the beginning.

**FINAL ACTION**: Complete all BONSAI phases, fix all issues, push the fixes, \
re-run all checks, and reply confirming the self-critic review and BONSAI cleanup \
are complete and the code is finalised."""
