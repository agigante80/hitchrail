# Corral: design

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

`corral`. Free on PyPI, a real word rather than a mashup, and the metaphor
matches the job: a corral is where you gather a group, let one out to work and
bring it back. The CLI reads naturally as `corral serve`.

Deliberately not named with "Claude" in it. That is Anthropic's trademark, and
a third party package leading with it invites a forced rename later. "Claude
Code" belongs in the description and the README, not in the package name.

Known collision: the Pony language's dependency manager is also called Corral.
Different ecosystem, judged acceptable.

## 3. Scope

In scope for v1:

- List every direct subfolder of the root. No git filter, no badge, no
  distinction. A folder is a project.
- Refresh the list on demand.
- Create a new empty folder, immediately startable.
- Start a session in a folder.
- Stop a session, gracefully first, with force as an explicit second choice.
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
- Sending input to a session. Corral starts and stops agents; it is not a
  terminal.

## 4. Architecture

Modules with hard boundaries, in three layers: discovery and engine below,
Claude Code specifics quarantined to one side, HTTP on top. The engine must be
testable without HTTP, and the HTTP layer must be testable without tmux.

```
corral/
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

`detached` is surfaced in the UI with its pid and an explanation. Corral never
silently reconciles it, because the safe action depends on what that agent is
doing, which Corral cannot know.

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
5. Never issue a bare `tmux kill-server`. Never kill a session Corral did not
   create. Every tmux invocation is scoped explicitly.

### 4.3 Claude Code internals are quarantined

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

The threat model is not incidental to this project. Corral spawns
`claude --dangerously-skip-permissions`. Anyone who can drive its API can run
arbitrary code as the user who started it.

The mobile requirement makes network binding the normal case rather than the
exception, so the token path is the main path.

### 5.1 Controls

1. **Host allowlist, always on.** `TrustedHostMiddleware` with an allowlist
   covering loopback names plus any host the operator configures. This is DNS
   rebinding defence: without it, any site the user visits in any browser on the
   network can rebind a name to Corral's address and drive the API, with the
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
API. Fixed in 4.5.2 by adding a host allowlist. Corral has the same shape and a
worse blast radius, because Glances reports state while Corral starts processes.

Sources:
- https://github.com/nicolargo/glances/security/advisories/GHSA-hhcg-r27j-fhv9
- https://www.starlette.io/middleware/

### 5.3 Stated limitations

Documented in the README rather than hidden:

- Over plain HTTP on a LAN the token crosses the network in cleartext. On a
  WPA2 or WPA3 network that is a modest risk; the remedy is a reverse proxy
  with TLS, and that is documented.
- Corral does not sandbox the sessions it starts. It is a launcher. The agent
  it launches has whatever access the user has.

## 6. HTTP interface

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | the single page |
| GET | `/api/projects` | every folder with its state |
| POST | `/api/projects` | create a folder |
| POST | `/api/sessions/{name}` | start a session |
| DELETE | `/api/sessions/{name}` | stop a session, `?force=1` to skip the graceful attempt |
| GET | `/api/sessions/{name}/logs` | tail of the pane |
| GET | `/api/events` | SSE stream of state changes |

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
- **The controller session is visibly protected.** Where Corral is running in a
  folder that has its own session, that row shows a lock rather than a stop
  control. Refusing after the tap is worse than not offering the tap.
- **Graceful stop is the primary button; force is a separate underlined link.**
  On a phone, the destructive path must not sit under the thumb with the same
  weight as the safe one.
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

## 9. Testing

Hermetic. No test touches a real tmux server, a real Claude, or the real
filesystem outside a temporary root.

- `tmux`, the process table and `/proc` are faked behind injectable seams, the
  same approach the reference `another tool` suite uses for its hardware backends.
- Every behaviour in section 4.2 gets a named regression test that fails if the
  workaround is removed.
- The four states in section 4.1 each get a test, including `detached`, which is
  the one a naive implementation gets wrong.
- Security tests assert refusals, not just successes: a bad Host is rejected, a
  missing Origin on a mutating request is rejected, a non loopback bind without
  a token refuses to start, and a folder name containing a path separator or a
  parent reference is rejected.
- The API is tested through `httpx.ASGITransport` with no network and no server.

CI runs lint, format check, types, the import boundary contract, and tests on
Python 3.11, 3.12 and 3.13.

## 10. Risks

| Risk | Handling |
|---|---|
| `bridgeSessionId` changes or disappears | quarantined in `claude_ipc.py`, degrades to `pending` |
| A user exposes Corral to a hostile network | token forced on non loopback bind, host allowlist always on |
| Two starts race on the same folder | start lock, and the API is idempotent per folder |
| A started session dies immediately | reported as `start_died` with the captured output, never as running |
| Memory exhaustion from one tap per session | RAM guard with a hard floor and a soft confirmation gate |
