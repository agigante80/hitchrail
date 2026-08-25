<!-- ci-health-version: 3 -->

# CI Health Monitor

Check every GitHub Actions workflow for failures, create P0 tickets, gate each ticket, and
auto-fix the failures that are safe to auto-fix.

## Process

Execute these phases in order. Stop early if all workflows are passing.

### Phase 1: Discover and assess workflows

```bash
ls .github/workflows/*.yml .github/workflows/*.yaml 2>/dev/null
```

If there are no workflows, say so and stop. Before Phase 1 Task 1 of the implementation plan the
only workflow here is `template-lockstep.yml`; the five-gate matrix arrives with the skeleton.

Detect the working branch:

```bash
git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || echo "main"
```

For each workflow, check the latest run on that branch:

```bash
gh run list --workflow <workflow-file> --branch <branch> --limit 1 --json databaseId,conclusion,createdAt,name -q '.[0]'
```

For each failing run:

```bash
gh run view <RUN_ID> --json jobs --jq '.jobs[] | select(.conclusion == "failure") | .name'
gh run view <RUN_ID> --log-failed 2>&1 | tail -150
```

Report a summary table:

| Workflow | Status | Failed jobs |
|---|---|---|
| ci.yml | pass/fail | job1, job2 |

If all workflows are passing, report "All workflows green" and stop.

**The matrix multiplies the job list.** CI here runs the five gates on Python 3.11, 3.12 and
3.13, so one broken gate surfaces as three failing jobs. Group by gate, not by job: three
identical `mypy` failures are one ticket, not three. A gate that fails on **only one** interpreter
is the more interesting finding and gets its own ticket, because that is a version compatibility
bug rather than a code bug.

**Classify governance workflows separately.** Two workflows here are intentional governance
signals rather than CI breakage:

- **Template lockstep** (`template-lockstep.yml`): red means the issue templates and
  `docs/guides/ticket-standards.md` have drifted apart in their `template-version` markers. The
  fix is to align the markers deliberately, which is an editorial decision. Surface it as
  "action: align the template-version markers" and do not file a P0 bug.
- **Release gate** (`release-gate.yml`, from the `release-automation` skill): red means the PR
  author did not bump the version. Surface it as "action: bump the version per
  `docs/versioning.md`" and move on. Never auto-bump to make it pass; that defeats the gate.

### Phase 2: Create tickets for failures

For each failing gate:

1. **Check for an existing open ticket:**

```bash
gh issue list --repo agigante80/hitchrail --search "fix(ci): <gate-keyword>" --state open --limit 1
```

2. **If none exists,** create one:
   - Title: `fix(ci): <workflow> - <gate> failing on <branch>` (append ` (3.11 only)` and similar
     when it is interpreter specific)
   - Labels: `bug`, `infrastructure`
   - Priority: P0
   - Body must include: the last 100 lines of the failed job, a link to the run, the affected
     files if identifiable, the `<!-- template-version: 4 -->` marker, and acceptance criteria
     "the gate passes on `<branch>` on all three interpreters"
   - There is **no GDPR section** in this repository's templates. Use the `Blast radius` section
     instead, which for a CI failure is usually "touches none of the seven controls"

3. **If a ticket exists,** comment with the latest logs.

### Phase 3: Gate each new ticket

Run the ticket-gate agent on each newly created ticket. Fix and re-run until 10/10.

### Phase 4: Implement fixes

**AUTO-IMPLEMENT:**

- `ruff check` failures
- `ruff format --check` failures (run `uv run ruff format`)
- `mypy` failures that are genuinely annotation errors
- unit and integration test failures
- packaging and build failures
- `uv.lock` drift

**DO NOT AUTO-IMPLEMENT (investigate and comment only):**

- **E2E failures.** Comment "E2E: investigation complete, manual review required before fix". An
  E2E failure here may mean the SSE reconnection or the stop escalation is genuinely broken, and
  those are behaviour, not lint
- **`lint-imports` failures.** A broken import boundary contract means the engine layer imported
  Starlette or the server. The fix is architectural, and the tempting fast fix, loosening the
  contract, is exactly the thing the contract exists to prevent. Never edit the
  `[tool.importlinter]` section to make a gate pass
- **Anything that would weaken one of the seven security controls** to make a test pass. If a
  security test fails, the test is usually right
- **Security scan findings.** Comment with a summary, do not auto-fix
- **Release gate and template lockstep.** See Phase 1

After implementing, run the project's gates locally before pushing:

```bash
uv run ruff format
uv run ruff check
uv run mypy
uv run lint-imports
uv run pytest
```

Then:

```bash
git add <specific-files>
git commit -m "fix(ci): <description>"
git push origin <branch>
```

### Phase 5: Verify

Wait, then check whether a new run was triggered:

```bash
gh run list --workflow <workflow-file> --branch <branch> --limit 1 --json databaseId,status,conclusion -q '.[0]'
```

Report whether the fix was pushed and a new run is in progress. Do not claim the CI is fixed
until a run has actually gone green; a pushed commit is not a passing pipeline.

---

## Rules

- **Never hard-code workflow file names:** always discover via `ls .github/workflows/`
- **Never hard-code branch names:** detect from git or ask
- **Group matrix failures by gate,** not by job. One broken gate on three interpreters is one
  ticket; a gate broken on one interpreter only is its own ticket
- **Gate review must pass 10/10** before implementing any fix
- **One commit per fix,** not one commit for everything
- **Never loosen a gate to make it pass.** Not the import contract, not a mypy override, not a
  skipped security test. If the gate is wrong, that is a separate ticket with an argument in it
- **No duplicate tickets:** always search before creating
- **Work on `main`** unless a working branch exists, per the project's git convention
