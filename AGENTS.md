# AGENTS.md

Conventions for anyone working on this repository, human or agent.

This is the canonical file. `.claude/CLAUDE.md` points here, so there is one
copy rather than two that drift: it went three phases out of date once with a
single copy, and two would not have survived a phase.

**Some paths below are not in this repository.** `.claude/` holds the
maintainer's agent configuration, its path scoped rules and its private name
list, and it is deliberately untracked: a public file enumerating the private
names would tell a reader exactly what to search the history for. Those
references are kept because they explain where a rule is enforced, not because
you can read them here.

A web UI for starting and stopping headless Claude Code sessions across a folder
of projects. Phone first. Python, standalone, no bash dependency.

## Status

**Do not state the phase count here.** It was wrong for three phases: this
section claimed "phases 1 to 3 of 7" and named `engine.py`, `server.py`,
`events.py` and `cli.py` as one line placeholders long after all four were
implemented, which told every reader the opposite of the truth about the part
they were most likely to touch.

`docs/roadmap.md` is the one place that says what is built. A closed milestone
means a phase whose exit criteria were ticked with evidence. Read it first, and
`tests/test_docs_are_true.py` asserts that this file has not gone back to
claiming otherwise.

## Where things are

- `docs/roadmap.md` is the order of work. Read it before starting anything.
- `docs/superpowers/specs/2026-08-25-hitchrail-design.md` is the design. It is
  the argument; follow it or change it deliberately, never drift from it.
- `docs/superpowers/plans/` holds one plan per phase, six of them so far.
  Phases 7 to 11 have none yet: a plan is written when its phase starts.
  Tasks are numbered continuously across the phases, 1 to 17, in dependency
  order. Work them in that order and do not start a phase before the previous
  one meets its exit criteria.
- `docs/tech-guidelines.md` is binding for all code here.
- `docs/guides/ticket-standards.md` is the single source of truth for what a
  ready ticket contains. The issue templates collect it, `ticket-gate` scores
  against it, and `scripts/check-template-lockstep.sh` keeps them on one version.
- `docs/versioning.md` is the single semver authority. Semver here is an operator
  contract: MAJOR means the person running `uvx hitchrail` must change something.
- `docs/design/` holds the interface artboards, which are the reference for
  anything the spec describes in words. The canvas they were exported from is
  private to its owner; the exports here are the published form.
- `.claude/rules/` holds path scoped rules that load automatically when you edit
  the files they name: testing for anything under `src/` or `tests/`, security
  for the modules its own `paths:` list names. Read that list rather than a
  count repeated here, which is how this line came to say "five" while the file
  named eight.
- `.claude/agents/`, `.claude/commands/` and `.claude/skills/` hold the
  governance components, adapted to this project rather than copied. Each carries
  a `<name>-version` marker so `forge-adapt` can tell drift from adaptation.

## Commands

```sh
uv sync                    # set up
uv run pytest              # tests
uv run ruff check          # lint
uv run ruff format         # format
uv run mypy                # types
uv run lint-imports        # module boundaries
```

On demand, not a gate, and not in `dev` so `uv sync` stays lean:

```sh
uv sync --group mutation   # once
uv run mutmut run          # the five modules between a web page and a shell
uv run mutmut results      # survivors are READ, never counted
```

All five gates are blocking in CI on 3.11, 3.12 and 3.13. Run them before
committing, not after being asked.

One test, one file, one tier:

```sh
uv run pytest tests/test_engine.py::test_detached_is_not_stopped
uv run pytest -m integration      # the real app through ASGITransport, no socket
uv run pytest -m live             # binds a real loopback socket
uv run pytest -m live_tmux        # drives a real tmux on a private socket
uv run pytest -m e2e              # a real browser; needs `playwright install chromium`
uv run pytest -m "not integration and not live and not live_tmux and not e2e"
uv run pytest -m "not live_tmux"  # skip it, on a machine without tmux
uv run pytest tests/test_properties.py   # the invariants, via hypothesis
uv run pytest -k detached
```

The `live_tmux` tier needs tmux installed. It skips without it, and CI installs
tmux and fails if the tier skipped, because a tier that skips everywhere looks
like coverage while proving less than none.

Three tiers, and the choice is not a matter of taste. Unit is hermetic with
every external surface faked. Integration drives the real Starlette app through
`httpx.ASGITransport` with a faked engine, and opens no socket. End to end
launches the real server against a temporary root, and is the only tier that
can see SSE reconnection, the stop escalation in the state the user is really
in, the phone viewport, or a forged `Host` refused on a live socket.

**The E2E tier must drive a private tmux server**, `tmux -S "$SOCK"` invoked
through `env -u TMUX`. A bare `tmux` honours `$TMUX` over `$TMUX_TMPDIR`, so a
suite run from inside tmux talks to the developer's real server.

## Architecture

Three layers with hard boundaries. The engine must be testable without HTTP,
and the HTTP layer testable without tmux.

```
src/hitchrail/
  hostnames.py   what a valid host or origin IS: one canonical form for each
  config.py      the dataclass, its refusals, and the derived allowlists
  discovery.py   root scanning, folder creation, path safety
  tmux.py        the tmux adapter and its footguns
  procs.py       process table snapshot
  claude_ipc.py  everything that knows Claude Code internals
  ram.py         memory readings and the guard decision
  sessions.py    what a session IS, and every refusal the engine can make
  events.py      the change feed the SSE stream serves, dropping slow clients
  engine.py      state derivation, start, stop, log tail; an unreadable
                 machine is an error rather than a fifth state
  security.py    host allowlist, token, origin check, in that order
  headers.py     nosniff, frame refusal and the CSP; refuses nothing
  server.py      Starlette app, routes, middleware, SSE
  web/           index.html, app.js, app.css (no build step)
  cli.py         argument parsing, config, uvicorn launch
```

`hostnames.py` holds the pure vocabulary `security.py` reaches for on every
request; `config.py` holds the dataclass and startup refusals built from it. The
dependency runs one way and a test asserts it. Both sit at the boundary rather
than in the engine, and both are in the `paths:` list of
`.claude/rules/security.md`, alongside the modules that spawn things.

Every external surface is injected: tmux, the process table, memory readings,
the Claude state directory, the clock. That is what makes the engine testable
without a real machine, so a new external dependency arrives as a seam.

**State is derived on demand, never stored.** There is no database and no
session registry, so there is nothing to drift. Derivation runs in two
directions, and the second one is the whole point: for each prefixed tmux
session find the Claude process it owns, then *independently* scan for Claude
processes no pane owns. A tool that only asks tmux reports an agent that
outlived its terminal as `stopped`, and invites you to start a second one in
the same folder.

| State | Meaning |
|---|---|
| `running` | tmux session alive, owns a live Claude process |
| `stale` | tmux session alive, no Claude in it |
| `detached` | Claude alive, no tmux session owns it |
| `stopped` | neither |

`detached` is surfaced with its pid and never silently reconciled. It is the
state a naive implementation gets wrong, and it has its own test.

**One piece of state is not derived:** the in flight graceful stop, held in
memory in the engine, keyed by session name, deliberately not persisted. It is
an overlay on the table above, not a fifth state. If Hitchrail restarts mid
stop that knowledge is lost and the session reads as `running` again, which is
the truth; a `stopping` marker that outlived the process would be a lie.

Stopping is a sequence: confirm, graceful request, kill available throughout the
wait, then a 30 second timeout that reports and **does not escalate on its own**.
The API keeps graceful and kill as separate ROUTES rather than one call with a
flag, so a client that meant to be gentle is never one query parameter from a
kill: `DELETE /api/sessions/{name}` is the graceful one, `POST
/api/sessions/{name}/kill` is the other. A duration is a parameter, an action
is a route, and there is not even a duration here because the wait is
`stop_timeout` in the configuration. The etiquette of trying gently first is a
property of the interface, not of the API.

Defaults: session prefix `hr-`, stop timeout 30s, hard memory floor 1536 MB,
soft floor 3072 MB, per session estimate 1536 MB, port 8787.

## Non negotiables

These are the ones that cost real debugging to find, or that protect somebody.

- **No shell.** Every subprocess call takes an argument list. `shell=True` is
  forbidden, no exceptions.
- **Never a bare `tmux kill-server`.** Never kill a tmux session that does not
  carry the configured prefix. A bare `tmux` honours `$TMUX`, so from inside a
  session it hits the developer's real server.
- **tmux target specs lie by default.** `has-session -t name` prefix matches, so
  `hr-vessel` resolves `hr-vessel-social`; `=` forces exact, and only for a
  session target. `list-panes` ignores a leading `=` and needs a trailing `:` to
  read its argument as a session, or a stopped project reports a sibling's
  process as its own. `.` and `:` are window and pane separators, so a session
  named `dotted.site` can be created and never addressed: sanitize on the way in
  and keep the display name apart from the tmux name. **A pane vanishes before
  it can be read**: an agent that dies takes the pane, the window, the session
  and then the server with it in under 50ms, so `remain-on-exit` is chained
  into the same `new-session` invocation and cleared once the start succeeds,
  or a dead start reports nothing and a live one lingers as `stale`. That
  `set-option` needs `=name:` and not `=name`, the same colon `list-panes`
  needs, because it is a WINDOW option. Each of these gets a named regression
  test that fails if the workaround is removed.
- **Starlette is 1.x here.** `on_startup`, `on_shutdown`, `add_event_handler()`
  and the `@app.route()` decorators were removed at 1.0. Use the `lifespan`
  context manager and an explicit `routes=` list. Most examples online are
  written against 0.4x and are wrong.
- **Three runtime dependencies:** `starlette`, `uvicorn`, `sse-starlette`. A
  fourth needs a written justification in the pull request. Every dependency is
  audit surface for a tool that spawns processes as the user.
- **The engine layer must not import** `server`, `cli`, `starlette`, `uvicorn`
  or `sse_starlette`. `uv run lint-imports` enforces it.
- **The root stays lean.** Configure tools from `pyproject.toml`. Do not add
  root level dotfiles without a reason.
- **`claude_ipc.py` is quarantine.** It is the only module allowed to know
  about Claude Code internals, because they are undocumented and will change.
  When `bridgeSessionId` breaks, exactly one module changes and the UI degrades
  to `pending` rather than reporting something false. "Knows about" includes
  iterating a key sequence, not only importing: the engine calls
  `claude_ipc.request_stop(...)` and never loops over `GRACEFUL_STOP_KEYS`,
  because a `for` loop in the engine teaches it that stopping is keystrokes
  through tmux. `lint-imports` cannot catch this one, so it has a grep test.
  This module is also the vendor seam. Multi agent is an explicit v1 non goal
  (design section 3.1); what is kept open is the seam, not an abstraction, and
  no vendor name may enter the operator or API contract. The setting is
  `agent_binary`, not `claude_binary`, for that reason.
- **Every ticket gets a milestone and an area label.** The milestone is a phase
  from `docs/roadmap.md`, or `Backlog` for triaged work with no phase. **Empty
  means untriaged**, never "no phase", so `is:open no:milestone` is the triage
  queue. `ticket-gate` blocks without both, and
  `scripts/check-ticket-hygiene.sh` sweeps for the ones it never sees. A ticket
  that wants two milestones wants splitting.
- **Test the refusals.** A security control with only a happy path test is
  untested. Full rules in `.claude/rules/security.md`.

## Verify, do not recall

Anything version dependent or security sensitive gets checked against primary
sources before it is decided. Not remembered. The Starlette 1.0 trap above is
exactly why: the remembered API is the wrong one.

## Style

Comments carry what the code cannot: a workaround, a footgun, a decision that
looks wrong and is not. A comment restating the line above it gets deleted.
When a change reverses an earlier decision, write the reason into the code.

**No em dashes or en dashes,** anywhere: code, comments, docs, commit messages,
release notes, issue bodies. Every document in this repository already held to
this before it was written down; `.claude/no-dashes` now opts the project into
the hook that enforces it. Do not substitute an ASCII hyphen when it fires.
Restructure instead: a colon for an explanation, commas for an aside, "to" for a
range, or two sentences for a strong contrast.

A file past roughly 400 lines is doing more than one thing. Split it along the
seam that is already there.

## Git

Work on `main`. Conventional commit subjects. Say what changed and why it was
not the obvious alternative; the diff already says what.
