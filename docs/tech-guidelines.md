# Corral: technical guidelines

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

- Full type annotations on everything public. `Any` needs a comment explaining
  why it is unavoidable.
- Docstrings state why, not what. The signature already says what.
- Comments earn their place by carrying information the code cannot: a
  workaround, a footgun, a decision that looks wrong and is not. A comment that
  restates the line above it is deleted.
- When a later change reverses an earlier decision, write the reason into the
  code. Otherwise the next reader relitigates it.

## 5. Security rules

Corral spawns `claude --dangerously-skip-permissions`. Anyone who can drive its
API can run arbitrary code as the user who started it. Every rule below is
non negotiable and each has a test that asserts the refusal.

1. **No shell.** Subprocess calls take an argument list. `shell=True` is
   forbidden, with no exceptions.
2. **Host allowlist always on.** `TrustedHostMiddleware` is applied to every
   route including the event stream. This is DNS rebinding defence, and it is
   the exact hole that produced CVE-2026-32632 in Glances, a tool of the same
   shape.
3. **Origin checked on every mutating request.** This is the CSRF control for a
   same origin JSON API.
4. **A token is mandatory for any non loopback bind.** The server refuses to
   start without one. A README warning is not a mitigation. Compare tokens in
   constant time.
5. **The root is a hard boundary.** Resolve every path and confirm it is a
   direct child of the configured root before spawning anything or creating
   anything. Validate names against an allowlist pattern, never a denylist.
6. **Never a bare `tmux kill-server`,** and never kill a session Corral did not
   create. Scope every tmux invocation explicitly.
7. **Report refusals honestly.** A guard that fails open, or an error rendered
   as a success, is worse than no guard. If Corral cannot determine a session's
   state, it says so rather than guessing.

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

- Tests are hermetic. No test touches a real tmux server, a real Claude
  process, the network, or the filesystem outside a temporary root.
- External surfaces are faked behind injectable seams: tmux, the process table,
  memory readings, and the Claude state directory.
- Test the refusals, not only the successes. A security control with only a
  happy path test is untested.
- Every workaround for a documented footgun gets a named regression test that
  fails if the workaround is removed. A workaround with no test is a bug
  waiting to be reintroduced by someone tidying up.
- New behaviour arrives with its test in the same commit.

## 8. Documentation

- The README states what Corral does, how to run it, and its limitations,
  including the ones that are inconvenient to admit.
- A stated limitation is a feature of the documentation. Do not soften it.
- `docs/superpowers/specs/` holds design documents. They are not updated to
  match drift; when a design changes materially, a new dated document supersedes
  the old one and says so.
