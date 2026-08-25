---
name: find-dead-code
description: Find genuinely dead source code in Hitchrail - unused functions, classes, methods and unreachable branches that ruff's local-scope rules miss - using vulture with a curated allowlist for this project's dynamic-reference patterns (Starlette route tables, the injected seams, the CLI entry point, the package's public surface). Use when asked to "find dead code", "remove unused code", "dead-code scan", or before a refactor or release.
---

<!-- find-dead-code-version: 2 -->

# Find Dead Code (Hitchrail)

Locate genuinely dead source code so it can be removed safely, without proposing the deletion of
code that only *looks* unused because it is referenced dynamically. This is the source code
counterpart to `dep-auditor`, which owns unused **dependencies**.

## The load-bearing rule

> **The tool flags CANDIDATES, not verdicts.** Never delete a symbol because the scanner listed
> it. Every candidate must be confirmed to have no dynamic reference before removal, and the
> **full gate run is the real safety net**. Static analysis cannot see a route table, an injected
> seam, or a name that appears only in a string.

For this project there is a second rule that overrides the scanner entirely:

> **A workaround is not dead code.** `docs/tech-guidelines.md` requires a named regression test
> for every workaround around a documented footgun, precisely because "a workaround with no test
> will be reintroduced by the next person tidying up". A dead code scan is the archetypal tidy up.
> If a symbol exists to defend against a tmux target footgun, a Starlette 1.0 API removal, or one
> of the seven security controls, it stays, whatever the scanner says.

## Local vs global

`ruff` already catches the local cases in CI and they must not be re-reported here: `F401`
(unused import), `F811` (redefinition), `F841` (unused local). This skill targets what a linter
structurally cannot find: unused module level functions, classes, methods, and unreachable
branches across the whole program.

## The tool

**vulture**, as a development dependency only. It never enters the runtime budget of three.

```bash
uv add --dev vulture
uv run vulture src/hitchrail tests --min-confidence 80
```

Wrap it so the scan is one repeatable command with the project's suppressions applied:

```sh
# scripts/find-dead-code.sh
#!/usr/bin/env bash
# vulture at high confidence, with the allowlist that encodes this project's dynamic references.
# The allowlist is not noise suppression: each entry is a symbol reached by a mechanism static
# analysis cannot see. Every entry carries a one line why.
set -euo pipefail
uv run vulture src/hitchrail tests scripts/dead-code-allowlist.py --min-confidence "${1:-80}"
```

Adding vulture is itself subject to the project's dependency question, at the lower development
bar: it does something we would otherwise not do at all, we use one command of it, and removing
it later costs one line in `pyproject.toml` and one script. Say that in the PR that adds it.

## Dynamic reference categories in this project

These look unused to a static analyser and are load bearing. This table is the project's actual
set, not a generic one:

| Pattern | Why it is referenced dynamically |
|---|---|
| **Starlette route endpoints** | listed in the explicit `routes=[Route(...)]` table and dispatched by path. In Starlette 1.x there is no `@app.route()` decorator to make the reference obvious |
| **The `lifespan` context manager** | passed to `Starlette(lifespan=...)`, never called by name |
| **Middleware classes** | instantiated from the `middleware=[Middleware(...)]` list |
| **Injected seams** | the tmux adapter, the process table adapter, the memory reader, the Claude state directory reader and the clock are passed in as callables. The production implementation may have no direct call site in `src/`, only a default argument in a constructor |
| **Fakes and stubs in `tests/`** | a fake seam's methods are called through the interface, and vulture often cannot see it. They are also the thing a scan most wants to delete, which would silently gut the suite |
| **The console script entry point** | `cli:main` is named as a string in `pyproject.toml` `[project.scripts]` |
| **`__init__.py` re-exports and `__all__`** | this is a published package. "No internal caller" does not mean dead; the caller is a consumer who has not been written yet |
| **pytest fixtures** | `conftest.py` fixtures are wired by name at collection time |
| **Error code constants** | `ram_soft`, `ram_hard`, `self_protected`, `start_died`, `url_pending`, `locked` are part of the HTTP contract the interface branches on. A constant with no current raise site is contract surface, not dead code |
| **Frontend references** | `web/app.js` reaches route paths as strings. A route that appears unused in Python may be the one the page calls |

Seed the allowlist from that table before the first real scan, so the first run is signal rather
than noise.

## Two detection modes

1. **Static (default).** vulture at `--min-confidence 80`. Fast, and finds most of it.
2. **Coverage complement.** Run the suite under coverage and cross reference. Code the scanner
   says is reachable but that has zero coverage is a strong lead. **This project measures coverage
   deliberately and does not gate on a percentage**, because a percentage gate is satisfied by
   executing lines without asserting on them. Use coverage here as a *signal*, never as an
   argument that a symbol is dead: low coverage often means untested, not unused, and in a
   greenfield repository it usually means "not written yet".

## Workflow

1. **Baseline first** if there is a body of existing code. Capture the current findings with
   `vulture --make-whitelist` and act only on *new* findings, so adoption is incremental.
2. **Run** at high confidence and group by confidence.
3. **Verify each candidate.** Grep the name including string literals, the route table,
   `pyproject.toml`, `web/app.js`, `__all__`, and `conftest.py`. Check whether it is referenced
   only in tests: test-only is effectively dead, but confirm it is not a seam.
4. **Classify:**
   - **Confirmed dead** -> remove in a small single purpose commit, then run **all five gates**:
     `uv run pytest`, `ruff check`, `ruff format --check`, `mypy`, `lint-imports`
   - **Dynamically referenced** -> do not delete. Add it to the allowlist with a one line why, so
     the scan gets quieter and more trustworthy over time
   - **A documented workaround** -> keep, always. Check that its named regression test exists; if
     it does not, the finding is "this workaround is unprotected", which is a ticket
   - **Unsure** -> keep it. Bias toward keeping
5. **Respect project invariants.** Never remove a symbol `.claude/CLAUDE.md`, the design, or
   `docs/tech-guidelines.md` marks as load bearing on a scanner's say so.

## Output format

Group into **High confidence dead** / **Likely dead (verify dynamic refs)** / **Probable false
positives** (anything matching a category above). For each, give `file:line`, then
`symbol (kind, confidence)`, then a one line verification note saying which reference you looked
for and did not find.

**Never auto-delete.** Propose removals for confirmation, or file gate ready tickets for anything
non trivial.

## Scope boundary

This owns **source** dead code. Unused **dependencies** belong to `dep-auditor`; do not
double-report them here. Dead *artboards* and superseded design documents are also out of scope:
`docs/superpowers/specs/` is deliberately append only, and an old spec is history, not dead code.

## Before Phase 1 exists

If `src/hitchrail/` does not exist yet, say so and stop. A dead code scan of an empty package is
not a finding, and this is the expected state until the skeleton lands.
