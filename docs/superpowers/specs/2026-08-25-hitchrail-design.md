# Hitchrail: design

Date: 2026-08-25
Status: approved for planning

## 1. What it is

A small web application that lists every folder under a configured root and
starts or stops a headless Claude Code session in any of them with one tap.
It is a standalone open source tool with its own engine. It does not wrap, call
or require `another tool`.

The primary interface is a phone. The desktop layout is the secondary one.

Design canvas (phone, desktop, edge states):
https://claude.ai/code/artifact/e02013e2-d501-405a-a95c-6404ebe492a6

## 2. Why the name

`hitchrail`. A hitching rail is what you tie your mounts to while they wait,
outside whichever building you are working in. That is what this tool holds: a
row of projects, standing ready, none of them costing you anything until you
take one out.

It was chosen against a hard availability bar, because this is a public
repository and a published package and a rename later would be expensive:

- free on PyPI, including the hyphenated variants PyPI normalizes together
- **zero** existing GitHub repositories of that name, anywhere
- `github.com/hitchrail` unclaimed as an account or organisation
- no software trademark found

Nothing else screened this cleanly. `corral`, the first choice, is free on PyPI
but `ponylang/corral` already owns the name on GitHub. `remuda` has the better
metaphor, a remuda being the string of horses a ranch hand picks a mount from
each day, but its GitHub account name is taken and few people can pronounce it.

Deliberately not named with "Claude" in it. That is Anthropic's trademark, and
a third party package leading with it invites a forced rename later. "Claude
Code" belongs in the description and the README, not in the package name.

The CLI reads as `hitchrail serve`.

## 3. Scope

In scope for v1:

- List every direct subfolder of the root. No git filter, no badge, no
  distinction. A folder is a project.
- Refresh the list on demand.
- Create a new empty folder, immediately startable.
- Start a session in a folder.
- Stop a session in three steps: confirm, then a graceful request you can watch,
  then a kill you can reach for at any moment during the wait. See section 4.3.
- Filter by state (all, running, stopped) and search by name.
- Refuse or warn when starting would exhaust memory.
- Live updates over SSE.
- Read the tail of a session's terminal output.

Out of scope for v1, and stated so nobody plans around them:

- Restart. It is stop followed by start, and the UI can compose it later.
- Multiple roots.
- Any authentication beyond a single shared token.
- Streaming logs. A tail on demand is enough.
- User accounts, roles, or multi-tenancy.
- Sending input to a session. Hitchrail starts and stops agents; it is not a
  terminal.

## 4. Architecture

Modules with hard boundaries, in three layers: discovery and engine below,
Claude Code specifics quarantined to one side, HTTP on top. The engine must be
testable without HTTP, and the HTTP layer must be testable without tmux.

```
src/hitchrail/
  discovery.py   root scanning, folder creation, path safety
  engine.py      state derivation, start, stop, log tail
  claude_ipc.py  everything that knows Claude Code internals
  ram.py         memory readings and the guard decision
  server.py      Starlette app, routes, middleware, SSE
  web/           index.html, app.js, app.css (no build step)
  cli.py         argument parsing, config, uvicorn launch
```

`engine.py` must not import `server.py` or Starlette. This is enforced by an
import-linter contract in CI, not by convention.

### 4.1 The state model

State is derived on demand from the operating system. There is no database and
no persisted session registry, so there is nothing to drift out of sync.

Derivation runs in two directions:

1. For each tmux session with the configured prefix, find the Claude process it
   owns.
2. Independently, scan for processes matching `--remote-control` that no tmux
   pane owns.

That second scan is the point. A tool that only asks tmux reports a Claude that
outlived its terminal as `stopped`, which invites starting a second agent in the
same folder. Four states result:

| State | Meaning |
|---|---|
| `running` | tmux session alive, and it owns a live Claude process |
| `stale` | tmux session alive, no Claude process in it |
| `detached` | Claude process alive, no tmux session owns it |
| `stopped` | neither |

`detached` is surfaced in the UI with its pid and an explanation. Hitchrail never
silently reconciles it, because the safe action depends on what that agent is
doing, which Hitchrail cannot know.

### 4.2 tmux behaviours to encode deliberately

These are known, non obvious, and each gets a named regression test. They are
invisible from the outside and will be reintroduced by any refactor that does
not know about them.

1. tmux treats `.` and `:` as window and pane separators in a target spec. A
   session named `dotted.site` can be created but never addressed. Sanitize on
   the way in and keep the display name separate from the tmux name.
2. `has-session -t name` prefix matches. `cc-vessel` resolves `cc-vessel-social`.
   The `=` prefix forces an exact match, and only for a session target.
3. `list-panes` takes a pane target, ignores a leading `=`, and falls back to
   prefix matching. It needs a trailing `:` to be read as a session. Getting
   this wrong makes a stopped project read as running on a sibling's process.
4. Concurrent starts must serialize behind a lock. A web UI makes double
   submission far easier than a CLI does.
5. Never issue a bare `tmux kill-server`. Never kill a session Hitchrail did not
   create. Every tmux invocation is scoped explicitly.

### 4.3 Stopping, and the one piece of state that is not derived

Stopping is a sequence, not a button:

1. **Confirm.** Cheap to reverse, so it is one tap away from nothing happening.
2. **Graceful request.** Hitchrail asks the agent to finish and exit, and the row
   enters `stopping`. Nothing has been killed. The user watches it happen.
3. **Escalation, available throughout.** A kill control is present for the whole
   wait, so a user who does not want to wait never has to. It is styled as the
   secondary, destructive path, never as the way out of a stuck dialog.
4. **Timeout.** After 30 seconds with no reply, Hitchrail stops waiting and says
   so. It does **not** escalate on its own. The session is still running, and
   the choice to kill it stays the user's.

Kill is deliberately unreachable before a graceful attempt has been made. Not
because forcing is wrong, but because on a phone the destructive control would
otherwise sit under the thumb at the same size as the safe one.

This introduces the only state Hitchrail holds that is not derived from the
operating system: the fact that a graceful stop is in flight, and when it
started. It lives in memory in the engine, keyed by session name, and it is
deliberately not persisted. If Hitchrail restarts mid-stop, that knowledge is lost
and the session simply reads as `running` or `stopped` again, which is the
truth. A `stopping` marker that outlived the process would be a lie waiting to
be told.

So the state table in 4.1 gains one transient overlay, not a fifth derived
state: any session may additionally be marked `stopping` while a request is in
flight. Every consumer treats an unknown or expired marker as absent.

### 4.4 Claude Code internals are quarantined

The session link comes from `~/.claude/sessions/<pid>.json`, key
`bridgeSessionId`, whose value is the URL path segment verbatim including its
`session_` prefix. That file is an undocumented internal, it is not written for
every session, and the fallback of scraping the terminal for a `claude.ai/code`
URL can match a URL that merely appeared as text rather than a live bridge.

All of this lives in `claude_ipc.py` behind one documented function with an
explicit instability warning. When it breaks on a Claude Code update, exactly
one module changes, and the UI degrades to a `pending` state rather than
reporting something false.

## 5. Security

The threat model is not incidental to this project. Hitchrail spawns
`claude --dangerously-skip-permissions`. Anyone who can drive its API can run
arbitrary code as the user who started it.

The mobile requirement makes network binding the normal case rather than the
exception, so the token path is the main path.

### 5.1 Controls

1. **Host allowlist, always on.** `TrustedHostMiddleware` with an allowlist
   covering loopback names plus any host the operator configures. This is DNS
   rebinding defence: without it, any site the user visits in any browser on the
   network can rebind a name to Hitchrail's address and drive the API, with the
   browser treating responses as same origin.
2. **Origin check on every mutating request.** `fetch` and `EventSource` send
   `Origin` and a rebound attacker cannot forge it. This is the CSRF control for
   a same origin JSON API.
3. **Token required for any non loopback bind.** Refuse to start, do not warn.
   Generated on first run, printed to the terminal, compared in constant time.
4. **Root is a hard boundary.** Every path is resolved with `Path.resolve()` and
   confirmed to be a direct child of the configured root before any process is
   spawned or any directory created. Folder names are validated against an
   allowlist pattern, not a denylist.
5. **No shell.** Every subprocess call passes an argument list. No
   `shell=True`, ever.

### 5.2 Precedent

This is not hypothetical. CVE-2026-32632 (GHSA-hhcg-r27j-fhv9) hit Glances, a
localhost and LAN system monitoring web UI, for exactly this: no host
validation, therefore DNS rebinding, therefore an attacker's page reading the
API. Fixed in 4.5.2 by adding a host allowlist. Hitchrail has the same shape and a
worse blast radius, because Glances reports state while Hitchrail starts processes.

Sources:
- https://github.com/nicolargo/glances/security/advisories/GHSA-hhcg-r27j-fhv9
- https://www.starlette.io/middleware/

### 5.3 Stated limitations

Documented in the README rather than hidden:

- Over plain HTTP on a LAN the token crosses the network in cleartext. On a
  WPA2 or WPA3 network that is a modest risk; the remedy is a reverse proxy
  with TLS, and that is documented.
- Hitchrail does not sandbox the sessions it starts. It is a launcher. The agent
  it launches has whatever access the user has.

## 6. HTTP interface

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | the single page |
| GET | `/api/projects` | every folder with its state |
| POST | `/api/projects` | create a folder |
| POST | `/api/sessions/{name}` | start a session |
| DELETE | `/api/sessions/{name}` | begin a graceful stop, returns immediately |
| DELETE | `/api/sessions/{name}?kill=1` | kill now, valid at any point |
| GET | `/api/sessions/{name}/logs` | tail of the pane |
| GET | `/api/events` | SSE stream of state changes |

The two stop calls are separate on purpose. The graceful one returns as soon as
the request is sent, marks the session `stopping`, and never blocks the
connection for 30 seconds; progress arrives over SSE like every other state
change. The kill is a distinct call rather than a flag on the same one, so that
"escalate the stop I already started" and "stop this thing" cannot be confused
at the call site, and so a kill is never a query parameter away from a client
that meant to be gentle.

A kill is accepted whether or not a graceful stop preceded it. The requirement
that you try gently first is a property of the interface, not of the API: a CLI
user or a script has a legitimate need to kill outright, and enforcing etiquette
in the transport would only invite working around it.

Errors return a JSON body with a stable machine readable `code` and a human
readable `message`. The codes carry the meanings the UI branches on, including
`ram_soft`, `ram_hard`, `self_protected`, `start_died`, `url_pending` and
`locked`.

`ram_soft` is a confirmation gate: the client resubmits with an explicit
acknowledgement. The server never proceeds on a soft refusal by itself.

SSE uses `sse-starlette`, not a hand rolled `StreamingResponse`. Ping keepalive,
client disconnect detection and generator shutdown are the parts that are
awkward to get right, and reusing a maintained implementation is preferred to
reinventing one. Note its documented caveat: SSE and `GZipMiddleware` are
incompatible, so gzip is not applied to the event route.

## 7. Interface design

The canvas linked in section 1 is the reference. The decisions it encodes:

- **Row asymmetry carries the mobile case.** A running row is tall because it
  holds three actions. A stopped row is one line with one button, so the
  remaining folders stay scannable with a thumb.
- **Nothing depends on hover.** Touch and pointer get identical affordances.
- **44px minimum hit target** in all mockup content.
- **The controller session is visibly protected.** Where Hitchrail is running in a
  folder that has its own session, that row shows a lock rather than a stop
  control. Refusing after the tap is worse than not offering the tap.
- **Stopping escalates, it does not branch.** The confirm step offers only
  Cancel and Stop. Kill appears once the graceful attempt is under way, phrased
  as impatience rather than as an alternative ("Do not wait, kill it now"), and
  stays available for the whole wait. On a phone the destructive path must never
  sit under the thumb at the same weight as the safe one.
- **The timeout screen states the risk before offering the kill**, because that
  is the moment the user is most likely to reach for it and least likely to have
  thought about uncommitted work.
- **The token screen states the consequence plainly**, in the words a person
  would use, not in security jargon.
- **Dark theme is a first class requirement**, not a later addition.

Palette and type are defined in the canvas: warm neutral ground, a saddle tan
accent, sage for running, brick for destructive, Zilla Slab for display, Karla
for body, IBM Plex Mono for machine values.

## 8. Technology and versions

Verified on 2026-08-25 rather than recalled.

| Component | Version | Why |
|---|---|---|
| Python | 3.11+ | present everywhere current, no ambiguity |
| uv | latest | environment, lock, build, publish, one tool |
| uv_build | >=0.12.5,<0.13 | the `uv init` default, and much faster than hatchling |
| Starlette | 1.6.0 | stable since 1.0.0 in March 2026 |
| uvicorn | 0.52.4 | ASGI server |
| sse-starlette | 3.4.8 | SSE, see section 6 |
| pytest | 9.1.1 | tests |
| pytest-asyncio | 1.4.0 | async tests |
| httpx | 0.28.1 | test client |
| ruff | 0.16.4 | lint and format |
| mypy | 2.3.1 | types, strict |

Starlette 1.0 removed `on_startup`, `on_shutdown`, `add_event_handler()` and the
`@app.route()` and `@app.websocket_route()` decorators. Use the `lifespan`
async context manager and an explicit `routes=` list. Any example written
against 0.4x is wrong, and there is a lot of it in circulation.

`ty`, Astral's type checker, is 0.0.74 and marked beta. Not a day one choice for
a tool that spawns processes as the user. Revisit when it is stable.

Runtime dependency budget is three: `starlette`, `uvicorn`, `sse-starlette`. A
fourth requires a written justification in the pull request. Every dependency is
audit surface for a tool with this blast radius.

The frontend has no build step: vanilla JavaScript and CSS served as static
files. A `node_modules` tree would be larger than the auditable part of the
project.

## 9. Distribution and repository layout

### 9.1 How a user installs it

Python, so the equivalent of `npx` is `uvx`. Three supported routes, in the
order the README should present them:

```sh
uvx hitchrail                      # run it without installing anything
uv tool install hitchrail          # keep it on PATH
pipx install hitchrail             # for people already living in pipx
```

`uvx hitchrail` is the headline. It fetches, resolves and runs in one command,
and leaves nothing behind, which is the right first contact for a tool that
people should be able to try before trusting.

The package name is confirmed free on PyPI as of 2026-08-25, along with the
hyphenated variants PyPI normalizes to the same project. See section 2 for the
full availability check.

The distribution is a pure Python wheel built by `uv_build`. The frontend has
no build step, so the wheel is source plus three static files, and nothing in
the release pipeline compiles anything.

### 9.2 Repository layout

The root is kept deliberately small. Anything that can live in a subdirectory
does, and every tool that can be configured from `pyproject.toml` is configured
there rather than in its own dotfile.

```
README.md          what it is, how to run it, what it will not protect you from
LICENSE            MIT
pyproject.toml     package metadata AND ruff, mypy, pytest, import-linter config
uv.lock            resolved dependencies, committed
.python-version    the development interpreter
.gitignore
src/hitchrail/        the package (see section 4 for the modules)
tests/             mirrors src/hitchrail/, plus tests/e2e/
docs/              specs, guidelines, and the design canvas sources
.github/workflows/ CI
```

`src/` layout rather than a flat package, so tests run against the installed
distribution and cannot accidentally pass by importing the working tree.

Ruff, mypy and pytest all read `pyproject.toml` natively. Import Linter also
supports it, via a `[tool.importlinter]` section, which is what keeps a fifth
dotfile out of the root.

## 10. Testing

Every change ships with the test coverage appropriate to it. Code that
compiles, and a suite that still passes, are not evidence that new behaviour
works: they are evidence that nothing obviously broke. The two are different
claims and only the second one is cheap.

### 10.1 What must be covered

For any behaviour added or modified:

- the primary success path
- the edge cases that behaviour actually has
- the failure and error conditions, including the refusals
- the regression, when the change is a fix

A change is not done when the code is written. It is done when the relevant
suites have been run, the failures the change introduced have been fixed, and
the new behaviour is demonstrably protected by a test that would fail without
it.

### 10.2 Three tiers

**Unit.** Hermetic and fast. `tmux`, the process table, memory readings and the
Claude state directory are all faked behind injectable seams, the same approach
the `another tool` suite uses for its hardware backends. No unit test touches a real
tmux server, a real Claude, the network, or the filesystem outside a temporary
root.

**Integration.** The API driven through `httpx.ASGITransport` against a real
Starlette app with a faked engine. No socket is opened and no server is started.
This is the tier that proves routing, middleware, status codes, error bodies and
the SSE contract.

**End to end.** The real application, launched the way a user launches it,
against a temporary root and a fake `claude` shim, driven through a browser with
Playwright. This tier exists because the things most likely to be wrong here are
precisely the things unit tests cannot see: whether the SSE stream actually
reconnects, whether the stop escalation reaches the kill control in the state
the user is really in, whether 53 rows behave at a phone viewport, and whether
the host allowlist rejects a forged `Host` on a live socket rather than in
theory.

E2E has one hard safety rule, learned the expensive way in the reference
implementation: **the E2E tier drives a private tmux server on its own socket**
(`tmux -S "$SOCK"`, invoked with `env -u TMUX`). A bare `tmux` honours `$TMUX`
over `$TMUX_TMPDIR`, so a suite run from inside a tmux session would otherwise
talk to the developer's real server. It creates only prefixed sessions, kills
only what it created, and never the server.

Playwright is a development dependency. It does not touch the three package
runtime dependency budget.

### 10.3 Non negotiable tests

- Each of the four states in 4.1, including `detached`, which is the one a naive
  implementation gets wrong.
- The `stopping` overlay from 4.3: that it is set, that it expires, that a
  restart clears it, and that a kill during the wait is accepted.
- Each tmux behaviour in 4.2, as a named regression test that fails if the
  workaround is removed.
- Every security control in section 5 asserted as a refusal, not only as a
  success: a bad `Host` is rejected, a mutating request with a missing or
  foreign `Origin` is rejected, a non loopback bind without a token refuses to
  start, a folder name containing a separator or a parent reference is rejected,
  and no code path reaches a shell.

### 10.4 Gates

CI runs lint, format check, types, the import boundary contract, unit,
integration and E2E on Python 3.11, 3.12 and 3.13. All are blocking.

Coverage is measured and reported. It is not turned into a percentage gate:
a number that can be satisfied by exercising lines without asserting on them
rewards the wrong behaviour. The gate is review, and the standard is the list in
10.1.

## 11. Risks

| Risk | Handling |
|---|---|
| `bridgeSessionId` changes or disappears | quarantined in `claude_ipc.py`, degrades to `pending` |
| A user exposes Hitchrail to a hostile network | token forced on non loopback bind, host allowlist always on |
| Two starts race on the same folder | start lock, and the API is idempotent per folder |
| A started session dies immediately | reported as `start_died` with the captured output, never as running |
| Memory exhaustion from one tap per session | RAM guard with a hard floor and a soft confirmation gate |
