# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Conventions for anyone working on this repository, human or agent. Tracked on
purpose: `.gitignore` excludes the rest of `.claude/` and re-admits this one
file, so a clone, a worktree and every CI leg carry it. Private, machine
specific notes go in `CLAUDE.local.md` at the root, which is ignored.

<!-- Maintainer notes are HTML comments. Claude Code strips them before loading
this file, so they cost no context: use them for history a person editing the
file needs and an agent working from it does not. Keep the file under about 200
lines; past that, adherence drops. Derivable facts (the module map is the one
exception, because tests/test_docs_are_true.py checks it) belong in docs/. -->

Hitchrail is a web UI for starting and stopping headless Claude Code sessions
across a folder of projects. Phone first. Python, standalone, no bash dependency.

## Read first

- `docs/roadmap.md` says which phases exist and what state each is in, in
  forge-kit's `roadmap-phases` shape: a `## Phase:` block per phase whose
  heading is the milestone's title, a `state:` line (`planned`, `open`,
  `done`, `backlog`), and a `plan:` line once the phase has started. GitHub's
  milestones say which phase each ticket is in, and the closed milestones plus
  `CHANGELOG.md` say what is built: phases closed before 2026-09-11 are not
  in the file. Never state a phase count, a plan count or a test count here:
  each decayed within a phase, and `tests/test_docs_are_true.py` checks this
  file for the claims that did.
- `docs/superpowers/specs/2026-08-25-hitchrail-design.md` is the argument.
  Follow it or change it deliberately; never drift from it.
- `docs/superpowers/plans/` holds one plan per phase, written when the phase
  opens, from the roadmap prose AND the tickets that accumulated in its
  milestone while it was a bucket. Five sections: Goal, Done looks like,
  Fails if (a premortem, never a risk list), Expected work, Out of scope.
  Tasks are numbered continuously across plans in dependency order. An open or
  done phase declares a plan that exists and has a `Fails if` section, at most
  one phase is open, exactly one is the backlog, and a done plan's unticked
  items say MOVED OUT or NOT BUILT with an issue number on the same line.
  `tests/test_docs_are_true.py` asserts all of that offline;
  `scripts/check-phases.sh` asserts the rest against the milestones.
- `docs/tech-guidelines.md` is binding for all code here.
- `docs/api.md` is the HTTP reference, checked against the server both ways: a
  status code the server can return and the document omits fails, and so does a
  documented code the server cannot return.
- `docs/guides/ticket-standards.md` says what a ready ticket contains;
  `docs/versioning.md` is the semver authority (MAJOR means the person running
  `uvx hitchrail` must change something); `docs/design/` holds the interface
  artboards, the reference for anything the spec describes in words.
- `.claude/rules/` holds path scoped rules that load when you edit the files
  their `paths:` lists name: testing for `src/` and `tests/`, security for the
  modules between a web page and a shell. They are untracked, like the agents
  and skills beside them, so the guard that keeps the security list complete
  (`test_every_mutated_module_loads_the_security_rules_when_it_is_edited`)
  skips wherever `.claude/rules/` is absent: a clone, CI, a `git worktree`.

## Commands

```sh
uv sync                    # set up
uv run pytest              # tests
uv run ruff check          # lint
uv run ruff format         # format
uv run mypy                # types
uv run lint-imports        # module boundaries
uv run hitchrail --root main=/tmp/empty  # run it; NEVER against a real projects root, it spawns agents as you
```

All five gates block in CI on 3.11, 3.12 and 3.13. Run them before committing,
not after being asked. `ci.yml` fires on a push to `main` and on pull requests,
so nothing watches a push to `develop`: `gh workflow run ci.yml --ref develop`
then `gh run watch`, or a pull request into `develop`, gets a runner (#232).

On demand, never a gate, and not in the `dev` group: `uv sync --group mutation`
once, then `uv run mutmut run` over the modules between a web page and a shell,
and `uv run mutmut results`. Survivors are READ, never counted.

```sh
uv run pytest tests/test_engine.py::test_detached_is_not_stopped
uv run pytest -k detached
uv run pytest tests/test_properties.py   # the invariants, via hypothesis
uv run pytest -m integration      # the real app through ASGITransport, no socket
uv run pytest -m live             # binds a real loopback socket
uv run pytest -m live_tmux        # drives a real tmux on a private socket
uv run pytest -m e2e              # a real browser; needs `playwright install chromium`
uv run pytest -m cli              # the installed console script as a subprocess
uv run pytest -m device           # a real Android over adb; opt in, selected by nothing else
uv run pytest -m screenshots      # rewrites docs/screenshots/; run at a release, by default never
uv run pytest -m "not live_tmux"  # on a machine without tmux
```

What each tier can prove is `docs/tech-guidelines.md` section 7.4; the tier is
a marker you DECLARE, never inferred from imports. Three rules that cost
something to learn:

- A tier that skips everywhere looks like coverage while proving less than
  none. `live_tmux` skips without tmux; CI installs tmux and fails if it skipped.
- Any `-m` on the command line REPLACES the `-m "not screenshots and not
  device"` in `addopts` rather than extending it, so a collection hook in
  `tests/conftest.py` deselects both unless the run names them (#104, #105).
- The E2E tier drives a PRIVATE tmux server, `tmux -S "$SOCK"` through
  `env -u TMUX`: a bare `tmux` honours `$TMUX` over `$TMUX_TMPDIR`, so a suite
  run from inside tmux talks to the developer's real server.

## Architecture

Three layers with hard boundaries: the engine is testable without HTTP, the
HTTP layer without tmux, and `uv run lint-imports` enforces the direction.

```
src/hitchrail/
  hostnames.py     what a valid host or origin IS: one canonical form for each
  projectnames.py  what a valid project NAME is, and how one is safely shown
  roots.py         what a root IS, and what a qualified project identifier
                   IS: `<root-label>~<folder>`, injective by allowlist
  config.py        the dataclass, its refusals, and the derived allowlists
  discovery.py     root scanning, folder creation, path safety
  tmuxnames.py     what a valid tmux name IS, and what a tmux invocation
                   looks like: pure strings, no server
  tmux.py          the tmux adapter and its footguns
  procs.py         process table snapshot
  claude_ipc.py    everything that knows Claude Code internals
  ram.py           memory readings and the guard decision
  sessions.py      what a session IS, and every refusal the engine can make
  events.py        the change feed the SSE stream serves, dropping slow clients
  derive.py        what state a project is in: a question, asked of one look at
                   the machine, that mutates and spawns nothing. An unreadable
                   machine is an error rather than a fifth state
  attention.py     which sessions are waiting on a person, and the budget that
                   makes looking affordable: reading a screen is a subprocess
                   per row, where derivation answers every row from one look
  engine.py        start, stop, log tail: what to DO about derive's answer
  security.py      host allowlist, token, origin check, in that order
  headers.py       nosniff, frame refusal and the CSP; refuses nothing
  server.py        Starlette app, routes, middleware, SSE
  pages.py         the two HTML pages and their assets, and the only code in
                   the project that reads a file chosen by a URL
  web/             index.html, grant.html, app.js, app.css, fonts (no build)
  cli.py           argument parsing, config, uvicorn launch
```

Every external surface is injected: tmux, the process table, memory readings,
the Claude state directory, the clock. A new external dependency arrives as a
seam, which is what keeps the engine testable without a real machine.

**State is derived on demand, never stored.** No database, no session registry,
nothing to drift. Derivation runs in two directions, and the second is the
point: for each prefixed tmux session find the Claude process it owns, then
INDEPENDENTLY scan for Claude processes no pane owns. A tool that only asks tmux
reports an agent that outlived its terminal as `stopped` and invites a second
one in the same folder.

| State | Meaning |
|---|---|
| `running` | tmux session alive, owns a live Claude process |
| `stale` | tmux session alive, no Claude in it |
| `detached` | Claude alive, no tmux session Hitchrail can address owns it |
| `stopped` | neither |

`detached` carries its pid and is never silently reconciled. "Hitchrail can
address" is load bearing (#85): ownership is read from one `list-panes -a`
against the configured tmux server, so an agent under another socket or in a
plain terminal is not orphaned and must not look it; a visible owner is named
in `foreign_session`, and a null one never renders as "no tmux session".

Two overlays are NOT derived, both in engine memory and deliberately
unpersisted: the in flight graceful stop (a `stopping` marker outliving the
process would be a lie) and the observation that a row is waiting on a person
(#100), written by the sweep with a TTL because reading a screen is a
subprocess per row and must not scale with how often a browser polls.

Stopping is a sequence: confirm, graceful request, kill available throughout the
wait, then a 30 second timeout that reports and does not escalate on its own.
Graceful and kill are separate ROUTES, never one call with a flag: `DELETE
/api/sessions/{name}` is graceful, `POST /api/sessions/{name}/kill` is the
other. A duration is a parameter; an action is a route.

Defaults: session prefix `hr-`, stop timeout 30s, hard memory floor 1536 MB,
soft floor 3072 MB, per session estimate 1536 MB, port 8787.

## Non negotiables

Each one cost real debugging or protects somebody, and each tmux workaround has
a named regression test that fails if it is removed.

- **No shell.** Every subprocess call takes an argument list. `shell=True` is
  forbidden, no exceptions.
- **Never a bare `tmux kill-server`**, and never kill a session without the
  configured prefix. A bare `tmux` honours `$TMUX`, so from inside a session it
  hits the developer's real server.
- **tmux target specs lie by default.** `has-session -t name` prefix matches
  (`hr-vessel` resolves `hr-vessel-social`); `=` forces exact, for a session
  target only. `list-panes` ignores a leading `=` and needs a trailing `:` to
  read its argument as a session, or a stopped project reports a sibling's
  process as its own. `.` and `:` are window and pane separators: sanitize names
  on the way in and keep the display name apart from the tmux name. A dead agent
  takes pane, window, session and server with it in under 50ms, so
  `remain-on-exit` is chained into the same `new-session` invocation and cleared
  once the start succeeds; that `set-option` is a WINDOW option and needs
  `=name:`, the same colon `list-panes` needs.
- **Starlette is 1.x here.** `on_startup`, `on_shutdown`, `add_event_handler()`
  and the `@app.route()` decorators are gone. Use the `lifespan` context manager
  and an explicit `routes=` list. Most examples online target 0.4x and are wrong.
- **Three runtime dependencies:** `starlette`, `uvicorn`, `sse-starlette`. A
  fourth needs a written justification in the pull request: every dependency is
  audit surface for a tool that spawns processes as the user.
- **The engine layer must not import** `server`, `cli`, `starlette`, `uvicorn`
  or `sse_starlette`.
- **`claude_ipc.py` is quarantine**: the only module allowed to know Claude Code
  internals, which are undocumented and will change. "Knows about" includes
  iterating a key sequence: the engine calls `claude_ipc.request_stop(...)` and
  never loops over `GRACEFUL_STOP_KEYS`; `lint-imports` cannot see that, so a
  grep test does. It is also the vendor seam: multi agent is a v1 non goal, and
  no vendor name enters the operator or API contract, which is why the setting
  is `agent_binary` and not `claude_binary`.
- **The root stays lean.** Configure tools from `pyproject.toml`; no new root
  dotfiles without a reason.
- **Every ticket gets a milestone and an area label.** The milestone is a phase
  from `docs/roadmap.md`, or `Backlog`. Empty means UNTRIAGED, so
  `is:open no:milestone` is the triage queue, and a ticket wanting two
  milestones wants splitting. `scripts/check-phases.sh` (every open ticket
  has a phase, roadmap and milestone states agree, a done phase holds no open
  ticket) and `scripts/check-ticket-hygiene.sh` need the network and an
  authenticated `gh`, so run them before planning a phase and before a
  release; they cannot be a pytest gate. After editing the roadmap,
  `scripts/sync-phases.sh --check`, then without the flag: it creates and
  closes milestones and never deletes or reopens one. Both find
  `forge-lib.sh` in the forge-kit-devops plugin and say so when they cannot.
- **Test the refusals.** A security control with only a happy path test is
  untested. Full rules in `.claude/rules/security.md`.
- **Verify, do not recall.** Anything version dependent or security sensitive is
  checked against primary sources before it is decided. The Starlette trap above
  is exactly why: the remembered API is the wrong one.

## Style

- Comments carry what the code cannot: a workaround, a footgun, a decision that
  looks wrong and is not. A comment restating the line above it gets deleted.
  When a change reverses an earlier decision, write the reason into the code,
  or the next review re-litigates it.
- **No em dashes or en dashes,** anywhere: code, comments, docs, commit
  messages, release notes, issue bodies. `.claude/no-dashes` opts the project
  into the hook. Do not substitute a hyphen when it fires; restructure: a colon
  for an explanation, commas for an aside, "to" for a range, two sentences for
  a strong contrast.
- A file past roughly 400 lines is doing more than one thing. Split it along
  the seam that is already there.
- Conventional commit subjects that say why the change was not the obvious
  alternative; the diff already says what.

## Git

Work on `develop`. `main` is the default branch and the release branch, reached
only by pull request, which is what makes the release gate real: it fires on a
PR to `main` and blocks the merge unless `pyproject.toml`'s version is ahead of
the latest release tag. Merging to `main` publishes to PyPI, where a version
number cannot be reused, so `docs/releasing.md`'s preconditions are checked on
the exact head being merged: the version bumped, CI green, and a local
`uv run pytest -m "e2e or live or live_tmux"` green.

`main` stays the default deliberately (#155): it is what `git clone` shows of
a published package. So Dependabot's SECURITY updates land on `main` whatever
`dependabot.yml` says and fail the gate; read one as a notification and
implement the fix on `develop` like every other change.
