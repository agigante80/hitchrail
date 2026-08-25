# Hitchrail: technical guidelines

These are binding for all code in this repository, from the first commit.
Where a rule is enforced by tooling, the tooling is named. A rule that cannot
be enforced is stated as a review obligation instead.

## 1. Verify, do not recall

Any decision that is version dependent, security sensitive, or costly to get
wrong is researched against primary sources before it is made. Not recalled.

- Prefer official documentation, release notes, advisories and the package
  index over blog posts, answers and memory.
- Confirm that guidance applies to the version this project actually pins, not
  to whatever version the source was written against.
- Record the check: when a decision rests on a source, cite it in the pull
  request or in a comment next to the code.

This is not ceremony. Starlette went stable at 1.0 in March 2026 and removed
`on_startup`, `on_shutdown`, `add_event_handler()` and the `@app.route()`
decorator. Most examples in circulation, and most recollection, are written
against the 0.4x API and are simply wrong. The same trap exists for every fast
moving dependency here.

Security decisions never rest on memory. See section 5.

## 2. Reuse before invention

Use what exists: the project's own helpers first, then a maintained library,
then new code. Reinventing a solved problem is a defect, not diligence.

The counterweight matters just as much: do not add abstraction for its own
sake. An interface with one implementation and no second one in view is
overhead. Prefer a direct call, and introduce the seam when the second case
actually arrives.

Worked example, both halves at once. Server Sent Events are trivial to emit and
awkward to operate: ping keepalive, client disconnect detection and generator
shutdown are where hand rolled implementations fail. So `sse-starlette` is a
dependency rather than fifty lines of our own. In the other direction, there is
no `SessionBackend` abstract base class, because there is exactly one backend
and inventing a plugin point for it would be complexity with no payer.

## 3. Modules and boundaries

Every module answers three questions on its own: what does it do, how is it
used, and what does it depend on.

- `discovery` scans the root and creates folders. It knows nothing about tmux.
- `engine` derives state and starts and stops sessions. It knows nothing about
  HTTP and must not import Starlette.
- `claude_ipc` is the only module that knows Claude Code internals.
- `ram` reads memory and decides the guard. Pure, given its inputs.
- `server` is Starlette and routing. It orchestrates; it holds no logic worth
  testing separately.

The `engine` to `server` direction is enforced by an import-linter contract in
CI. Import boundaries defended only by good intentions do not survive.

When a file grows past roughly 400 lines, treat it as a signal that it is doing
more than one thing, and split along the seam that is already there.

## 4. Style and tooling

| Concern | Tool | Enforced |
|---|---|---|
| Lint | ruff | CI, blocking |
| Format | ruff format | CI, blocking |
| Types | mypy, strict | CI, blocking |
| Tests | pytest | CI, blocking |
| Boundaries | import-linter | CI, blocking |

**The repository root stays lean.** Anything that can live in a subdirectory
does. Every tool that can be configured from `pyproject.toml` is configured
there and not in its own dotfile: ruff, mypy and pytest read it natively, and
Import Linter reads a `[tool.importlinter]` section. A new tool that insists on
its own root level config file needs a reason before it is adopted.

- Full type annotations on everything public. `Any` needs a comment explaining
  why it is unavoidable.
- Docstrings state why, not what. The signature already says what.
- Comments earn their place by carrying information the code cannot: a
  workaround, a footgun, a decision that looks wrong and is not. A comment that
  restates the line above it is deleted.
- When a later change reverses an earlier decision, write the reason into the
  code. Otherwise the next reader relitigates it.

## 5. Security rules

Hitchrail spawns `claude --dangerously-skip-permissions`. Anyone who can drive its
API can run arbitrary code as the user who started it. Every rule below is
non negotiable and each has a test that asserts the refusal.

1. **No shell.** Subprocess calls take an argument list. `shell=True` is
   forbidden, with no exceptions.
2. **Host allowlist always on**, applied to every route including the event
   stream. This is DNS rebinding defence, and it is the exact hole that
   produced CVE-2026-32632 in Glances, a tool of the same shape.

   Implemented by `security.HostAllowlistMiddleware`, **not** by Starlette's
   `TrustedHostMiddleware`, which the design originally named. That one does
   `host.split(":")[0]`, so every IPv6 literal becomes `"["` and
   `http://[::1]:8787/` is refused whatever the allowlist holds; and its
   `www_redirect` default answers an unrecognised host with a redirect built
   from that same untrusted header. Ten lines of our own, argued against
   section 2 in `docs/superpowers/plans/2026-08-25-hitchrail-phase-2-security.md`
   and recorded in `docs/roadmap.md`.
3. **Origin checked on every mutating request.** This is the CSRF control for a
   same origin JSON API.
4. **A token is mandatory for any non loopback bind.** The server refuses to
   start without one. A README warning is not a mitigation. Compare tokens in
   constant time.
5. **The root is a hard boundary.** Resolve every path and confirm it is a
   direct child of the configured root before spawning anything or creating
   anything. Validate names against an allowlist pattern, never a denylist.
6. **Never a bare `tmux kill-server`,** and never kill a session Hitchrail did not
   create. Scope every tmux invocation explicitly.
7. **Report refusals honestly.** A guard that fails open, or an error rendered
   as a success, is worse than no guard. If Hitchrail cannot determine a session's
   state, it says so rather than guessing.
8. **A secret in a URL is a secret in the log.** Redirecting it out of the
   address bar hides it from the browser and from nothing else. uvicorn builds
   its access line after the application returns, from the same scope dict the
   application was handed, so `?token=` was written to the server's log in
   cleartext on every grant until `security.TokenMiddleware` started clearing
   `scope["query_string"]` once the token is spent. Anything that carries a
   secret in a request target has to be followed all the way to where the
   server writes that target down.

   That clearing is still incomplete, and #20 tracks it: it sits on the grant
   path, so a request that already holds a valid cookie or header returns
   before reaching it and logs the token anyway. A partial fix to this kind of
   leak is worth recording as partial rather than as done.

   And note how far the rule reaches. Scrubbing our own log cannot be
   sufficient while the secret is in the URL at all, because a reverse proxy,
   the `Referer` header and browser history sync each write that URL down
   somewhere we do not control. #21 moves it into a fragment, which no server
   ever receives. When a mitigation only narrows an exposure, say which one
   ends it.

   The suite could not see this on its own: the live socket fixture ran at
   `log_level="warning"`, so the component under test was silenced by the test
   that was meant to observe it. A tier that quiets its subject proves less
   than it appears to.

## 6. Dependencies

The runtime budget is three: `starlette`, `uvicorn`, `sse-starlette`. A fourth
requires a written justification in the pull request that answers: what does it
do that we would otherwise write, how much of it do we use, who maintains it,
and what is the cost of removing it later.

Every dependency is audit surface for a tool with this blast radius. Development
dependencies are held to a lower bar, but the same question is still asked.

The frontend has no build step. Vanilla JavaScript and CSS, served as static
files. A `node_modules` tree would be larger than the auditable part of this
project, which defeats the point of it being auditable.

## 7. Testing

Every implementation includes automated test coverage appropriate to what it
changed. This is part of the work, not a follow up ticket.

### 7.1 The standard

Before writing tests, read how this project already tests the area you are
touching and follow that pattern. Do not introduce a second style alongside an
established one.

Then cover, for the behaviour you added or changed:

- the primary success path
- the edge cases the behaviour actually has
- the failure and error conditions, including every refusal
- the regression itself, when the change is a bug fix

Add or update whichever kind of test fits: unit, integration, end to end,
component. The type is chosen to suit the behaviour, not to suit convenience.

### 7.2 Done means run, not written

Work is not complete because the code type checks and the existing suite still
passes. Those say nothing about the behaviour just added.

Complete means: the relevant suites have been run, output inspected, failures
and regressions introduced by the change have been fixed, and the new behaviour
is protected by a test that would fail if the change were reverted. If a quality
gate exists, the change satisfies it.

Claiming completion without having run the tests is the single failure mode this
section exists to prevent.

### 7.3 Prove it in the running application

Where it is practical, verify behaviour through the actual runtime rather than
through unit tests and type checking alone. Unit tests confirm that a function
does what its author believed; they cannot confirm that the assembled
application does anything at all.

For this project that means an end to end tier: the real server, launched the
way a user launches it, against a temporary root and a fake `claude` shim,
driven through a browser. Use it for anything a unit test structurally cannot
see, including the SSE stream reconnecting, the stop escalation arriving in the
state the user is really in, the layout holding at a phone viewport, and the
host allowlist rejecting a forged `Host` on a live socket.

### 7.4 Standing rules

- Tests are hermetic. No test touches a real tmux server, a real Claude
  process, the network, or the filesystem outside a temporary root.
- **One documented exception: `tests/test_live_socket.py`.** It binds 127.0.0.1
  on an ephemeral port, talks to itself, and shuts down, and it is marked
  `live` so it can be deselected. It exists because section 5 asks for a forged
  `Host` to be refused on a live socket, and an `ASGITransport` test cannot
  make that claim: it proves the middleware is configured, not that the
  deployed server refuses anything, because a real request arrives through
  uvicorn's HTTP parser rather than through a dictionary a test constructed.
  A reader of these guidelines alone would otherwise conclude the suite opens
  no socket at all.
- External surfaces are faked behind injectable seams: tmux, the process table,
  memory readings, and the Claude state directory.
- **The E2E tier drives a private tmux server on its own socket**, addressed as
  `tmux -S "$SOCK"` and invoked through `env -u TMUX`. A bare `tmux` honours
  `$TMUX` over `$TMUX_TMPDIR`, so a suite run from inside tmux would otherwise
  talk to the developer's real server. It creates only prefixed sessions, kills
  only what it created, and never the server.
- Test the refusals, not only the successes. A security control with only a
  happy path test is untested.
- Every workaround for a documented footgun gets a named regression test that
  fails if the workaround is removed. A workaround with no test is a bug
  waiting to be reintroduced by someone tidying up.
- New behaviour arrives with its test in the same commit.
- Coverage is measured and reported, but not enforced as a percentage. A
  percentage gate is satisfied by executing lines without asserting on them,
  which rewards exactly the wrong behaviour. The gate is review against 7.1.

## 8. Documentation

- The README states what Hitchrail does, how to run it, and its limitations,
  including the ones that are inconvenient to admit.
- A stated limitation is a feature of the documentation. Do not soften it.
- `docs/superpowers/specs/` holds design documents. They are not updated to
  match drift; when a design changes materially, a new dated document supersedes
  the old one and says so.
