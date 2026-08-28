# Hitchrail: roadmap

The design says what to build. This says in what order, and what "done" means
at each stop. One phase at a time, each ending in something that runs.

Design: [`superpowers/specs/2026-08-25-hitchrail-design.md`](superpowers/specs/2026-08-25-hitchrail-design.md)
Rules: [`tech-guidelines.md`](tech-guidelines.md)

## How the phases are cut

Small phases, each with a demonstrable exit. A phase you cannot show somebody
is a phase you cannot tell is finished.

Two ordering rules decide what goes where:

1. **Dependency order.** Nothing is built before what it consumes.
2. **Risk order, where dependencies allow a choice.** The security boundary
   needs only the configuration, so it comes before the engine rather than
   after it. Its argument is the one the whole design rests on, and finding out
   late that the token cannot reach the event stream is expensive. It happened
   in the first draft of this plan, which put security at task 12 of 15 and did
   not notice until review that `EventSource` cannot send an `Authorization`
   header.

## Phase 0: Design

**Status: done.**

Design approved, technical guidelines written, interface drawn and clickable,
name secured on both registries.

## Phase 1: Foundations

**Status: done**, closed 2026-08-25 at `2c9be3b`. Issues #1, #2, #3 and #7.
All six exit criteria in the plan are ticked with the evidence that closed them.

**Plan: [`superpowers/plans/2026-08-25-hitchrail-phase-1-foundations.md`](superpowers/plans/2026-08-25-hitchrail-phase-1-foundations.md)**

The skeleton, the gates, the configuration and the path boundary. Three tasks.

Delivers: `pyproject.toml` with every tool configured from it, the module stubs
that make the import contract enforceable from the first commit, CI on three
interpreters, the `Config` that refuses a network bind without a token, and the
name allowlist that makes traversal impossible.

**Done when:** all five gates are green on 3.11, 3.12 and 3.13; a wildcard bind
produces an allowlist that actually contains the machine's own address; and a
name containing a separator, a parent reference or a leading hyphen is refused.

All three held, confirmed on the real runner and against this machine's real
network configuration. Two things worth carrying forward:

- Review of the batch found the path allowlist **failing open**. `NAME_PATTERN`
  was anchored with `$`, which matches before a trailing newline, so `evil\n`
  became a real directory and a 64 character name plus a newline walked past
  the pattern's own length cap. Every hand written payload in the ticket's test
  list passed that pattern. Future guards here want fuzzing or property tests,
  not only enumeration.
- Seven deferred items came out of the phase. Phase 2 closed four of them:
  #6 (a TLS proxy on a non standard port is refused by the origin check), #7
  (folders with a space or a non ASCII name are silently invisible), #8
  (normalise every host in one place) and #9 (`RootUnavailable` is a client
  error, and an intra-root alias is two projects). Still open: #4 (pin actions
  to SHAs before Phase 7 introduces a publish token), #5 (the plans' snippets
  are no longer checked by any tool) and #10 (the mypy gate checks 3.11 on all
  three matrix legs).

**The review loop was stopped by its trip wire, not by running clean.** Three
rounds found nine findings each, and rounds 2 and 3 each found defects inside
the previous round's fixes: the `contextlib.suppress` placement fixed in round
1 had the same defect one line above it, and the `extra_hosts` validation added
in round 2 left the same hole open on `host`. The user's `CLAUDE.md` says to
stop immediately when two consecutive rounds do that, because past that point
iteration removes value rather than adding it.

Fourteen findings were fixed across rounds 1 and 2, every one with a named
regression test verified to fail on revert. The nine from round 3 are #8, #9
and #10, to be done as deliberate work rather than a fourth round of point
patches. #8 in particular argues for one normalisation function rather than
per entry point validation, which is the shape all three rounds kept
rediscovering.

## Phase 2: The security boundary

**Plan: [`superpowers/plans/2026-08-25-hitchrail-phase-2-security.md`](superpowers/plans/2026-08-25-hitchrail-phase-2-security.md)**

The controls that stand between a web page and a shell, built before there is
anything to serve. Three tasks.

Delivers: the host allowlist, the origin check with scheme and port, and token
authentication over three carriers (header, cookie, and a one time query grant
that redirects the token out of the URL bar).

**Done when:** a real socket refuses a forged `Host`, refuses a mutating request
with a foreign or missing `Origin`, refuses a wrong token, and accepts a request
shaped the way `EventSource` sends one. The host check is proven to run before
the token check.

**Not done if:** the only proof is an `ASGITransport` test. That proves the
middleware is configured, not that the deployed server refuses anything.

All of it held. `tests/test_live_socket.py` binds a real loopback socket and
drives every refusal through uvicorn's own HTTP parser, and the middleware
order is asserted by a test rather than left to the order somebody typed. Four
things worth carrying forward:

- **The same defect shape ran through all three review rounds:** a value
  accepted after normalisation and then used in its raw form. `--allow-host
  box.lan:8787` validated and never matched. `--allow-origin https://box.lan:443`
  validated and never matched. `Config(host="[::1]")` validated and could not
  be bound. The fix that finally held was one canonical function each for hosts
  (`normalise_host`) and origins (`origin_forms`), used by every door, rather
  than a validator per entry point. Per entry point validation is how the
  allowlist ended up holding two spellings of one host and disagreeing with
  itself.
- **A redirect hides a secret from the browser, not from the server.** The
  `?token=` grant redirects the token out of the address bar, and it was still
  written to uvicorn's access log in cleartext on every use, because uvicorn
  builds that line after the app returns from the same scope dict the app was
  handed. The fix overwrites `scope["query_string"]` once the token is spent.
  The suite could not see this because its own fixture ran at
  `log_level="warning"`; a test tier that silences the component under test
  cannot observe it.
- The three security controls landing together broke two host and origin tests
  that bound a network address, because such a bind now demands a token. That
  is the suite catching a real cross ticket interaction, and it is the argument
  for building the boundary as one phase rather than three.
- `tests/conftest.py` now stubs `local_addresses` for every test that is not
  marked `live`. Around twenty tests in the tier the guidelines call hermetic
  were doing real DNS, and their answers changed with the machine. A rule that
  every test author has to remember had already decayed by the time it was
  written down, so it is enforced by an autouse fixture instead.

**The review loop ran its full four rounds and was stopped by the hard bound,
not by running clean.** Round 1 found nine. Round 2 found five, three of them
defects inside round 1's own fixes. Round 3 found five, none of them in round
2's fixes, which broke the consecutive streak the trip wire watches for and is
why the loop continued. Round 4 then found defects in round 3's fixes.

Three of the four rounds found a defect in the previous round's work, which is
above the 7 to 29 percent bad fix injection rate that the user's `CLAUDE.md`
cites as normal, and it is the argument for the bound existing at all.

The worst injection was mine and it is worth naming, because it is the failure
mode this phase kept teaching. Round 3 stripped the FQDN root dot in
`normalise_host` to fix an accepted-then-never-matches case, and by doing it on
the config side only it created a fresh accepted-then-never-matches case
(`box.lan..` stored as `box.lan.`) while removing the one spelling that had
worked. A fix aimed at a defect class produced a new instance of that class.

The resolution was a revert rather than a fifth patch. A revert restores a
state that already survived three rounds and cannot inject anything; a
cleverer two line fix at the hard stop would have shipped unreviewed with this
batch's injection rate as the prior. Both remaining defects are tickets: #19
for the root dot done on both sides, #20 for the access log leak on the paths
the grant fix does not reach. A ticket is a finished outcome for a finding.

## Phase 3: The adapters

**Plan: [`superpowers/plans/2026-08-25-hitchrail-phase-3-adapters.md`](superpowers/plans/2026-08-25-hitchrail-phase-3-adapters.md)**

One module per external surface, each pure, injectable and testable without a
machine. Four tasks.

Delivers: the tmux adapter carrying its footguns, the process table snapshot,
the Claude Code quarantine, and the memory guard.

**Done when:** each of the four addressing footguns in the design's section 4.2
(1, 2, 3 and 5) has a named regression test that fails if its workaround is
removed, and nothing in this layer imports Starlette. Footgun 4, serialising
concurrent starts, belongs to Phase 4: starting is an engine operation and
there is nothing in this layer to serialise.

All of it held. The four adapters are built and every one of the ten exit
criteria was verified by driving the modules rather than by reading the
tickets. Three things worth carrying forward:

- **The hermetic tmux tests could not have caught a wrong belief.** Every one
  asserts the argv the adapter sent, which proves the code builds what we
  intended and can never falsify the intention, because the fake encodes the
  same belief. `tests/test_live_tmux.py` runs the real thing, and all four
  addressing premises reproduce on tmux 3.4. This is the same gap Phase 2
  closed with a live socket, and it is worth assuming it exists wherever a
  fake stands in for an external tool.
- **That live tier leaked four tmux servers before it caught itself**, through
  the exact footgun it exists to prove: teardown killed the name it asked for,
  and tmux had stored a different one. Its first leak check was vacuous
  because it ran after the socket was deleted. A teardown assertion that
  cannot fail is worse than none, because it reads as proof.
- **`sanitize` was not injective**, which was its only requirement, and the
  digest design in this plan is what made it so. A project literally named
  `a-b-<the digest of a.b>` collided with `a.b`, and that name is computable
  by anyone who can create a folder. Injective by construction beat injective
  by hash.

## Phase 4: The engine (done)

**Plan: [`superpowers/plans/2026-08-25-hitchrail-phase-4-engine.md`](superpowers/plans/2026-08-25-hitchrail-phase-4-engine.md)**

All nine exit criteria in the plan are ticked with the evidence that closed
them. The last one, driving a real agent with no web server involved, is the
one that found the stale `stopping` marker that every fake had missed.

State derivation and the session lifecycle, with no HTTP anywhere. Four tasks.

Delivers: the event bus, derivation across all four states, start with a grace
window and a start lock, and the three step stop with its non persisted marker.

**Done when:** a Python session, with no web server involved, starts a real
Claude session, watches it become `running`, gracefully stops it, and kills it.
All four states have a passing test, `detached` included.

## Phase 5: The HTTP API and the CLI (done)

**Plan: [`superpowers/plans/2026-08-25-hitchrail-phase-5-api.md`](superpowers/plans/2026-08-25-hitchrail-phase-5-api.md)**

All twelve exit criteria are ticked with the evidence that closed them. A real
Claude agent was started, watched, gracefully stopped and killed through the
API by hand, which is what the "not done if" clause below asks for.

The thin layer on top. Three tasks.

Delivers: the REST surface and its stable error envelope, the event stream over
`sse-starlette`, and the command line entry point.

**Done when:** `uvx hitchrail --root ~/dev` serves an API a person can drive with
`curl`. It starts a real session, reports it accurately, stops it gracefully,
kills it when told to, refuses to bind to a network interface without a token,
and refuses a forged `Host` on a live socket.

**Not done if:** the suite passes but nobody has watched it start and stop a real
Claude session.

## Phase 6: Interface

**Plan: [`superpowers/plans/2026-08-27-hitchrail-phase-6-interface.md`](superpowers/plans/2026-08-27-hitchrail-phase-6-interface.md)**

The browser interface from the design canvas, and the end to end tier that
proves it. Six tasks, 18 to 23.

Delivers: the single page and its assets, the list with search and filter, the
start and stop flows including the escalation, the log drawer, the new folder
sheet, the memory footer, live updates over SSE with reconnection, the token
screen, dark theme, and the Playwright end to end tests running against a
private tmux server and a fake `claude` shim.

**Done when:** every flow in the design canvas works on a real phone against a
real machine, and the E2E tier covers the things unit tests structurally cannot
see: SSE reconnecting after a backgrounded tab, the stop escalation reaching the
kill control in the state the user is really in, the layout holding at a phone
viewport, and a forged `Host` being rejected on a live socket.


**Test coverage:** this is where the browser tier arrived. `tests/e2e/` runs
Playwright against the real server on a temporary root with a fake `claude`
shim, and it drives a PRIVATE tmux server for the same reason the live tmux
tier does. It is the only tier that can see SSE reconnection after a
backgrounded tab, the stop escalation in the state the user is really in, and
the layout holding at a phone viewport. That was #38, and it is #38's tier that
found most of what the reviews of tasks 22 and 23 reported.

## Phase 7: Release

**Test coverage:** before shipping something that spawns
`claude --dangerously-skip-permissions`, prove the security tests actually
assert. Mutation testing scoped to the five modules standing between a web page
and a shell is the check that the suite would NOTICE a changed line, which
coverage cannot tell you: three defects in this project shipped green at 98%
branch coverage. That is #35.


Delivers: PyPI publication as `hitchrail`, a tagged GitHub release, a README
that a stranger can follow, and a security policy telling people how to report
something.

**Done when:** `uvx hitchrail` works on a machine that has never seen this
repository, and the security section is the first thing a reader meets after
learning what the tool does.

## Deliberately later

Not scheduled, and not to be smuggled into an earlier phase:

- Restart as its own operation. It is stop then start, and the interface can
  compose it.
- More than one root.
- Authentication beyond a single shared token.
- Streaming logs. A tail on demand is enough until it demonstrably is not.
- Sending input to a session. Hitchrail starts and stops agents; it is not a
  terminal, and making it one is a different product.

## Deliberate additions to the design

Recorded here rather than left to drift. Both come from the design's own
section 6, which names error codes the first plan draft did not deliver:

- **`GET /api/sessions/{name}/url`** is a route the design's table does not list.
  It exists because listing must stay cheap: deriving the session link from the
  terminal costs a `capture-pane` per running row, and doing that on every list
  request is what turns a 50 row page into 50 subprocess calls. The list reports
  the link only when Claude's own state file has already written it; the
  interface asks this route when the user taps a row whose link is still
  pending, and that is where the design's `url_pending` code is returned.
- **`HostAllowlistMiddleware` replaces `TrustedHostMiddleware`**, which the
  design's section 5.1 names. Starlette's does `host.split(":")[0]`, so every
  IPv6 literal becomes `"["` and `http://[::1]:8787/` is refused whatever the
  allowlist holds, which makes a phone on an IPv6 network unable to reach
  Hitchrail at all. Its `www_redirect` default also answers an unrecognised
  host with a 307 built from that same untrusted header. The control is
  unchanged; only the mechanism is, which is why this is recorded here rather
  than superseding the design.
- **`--allow-origin`** is a configuration option the design does not mention.
  `allowed_origins` used to derive `https://{host}` for every allowed host,
  which made any HTTPS service on port 443 of the same machine a same origin
  caller. A TLS terminating proxy's origin cannot be derived at all, because
  the scheme and the port are both the proxy's, so it is configured.
- **`locked`** is returned when a start arrives while another start is in flight
  for the same folder. The design asks for concurrent starts to serialize; a web
  UI makes double submission easy, and answering the second tap immediately and
  honestly is better than holding its connection open behind a lock.

## The standing rule

A phase is not finished because its code exists and the suite is green. It is
finished when the behaviour has been watched working in the running
application. See [`tech-guidelines.md`](tech-guidelines.md) section 7.

## Superseded

`superpowers/plans/2026-08-25-hitchrail-core.md` was a single 15 task phase
covering everything from the skeleton to the CLI. It was replaced by phases 1
to 5 above after a review found four defects that a smaller phase boundary would
have caught earlier, including a start path that would have reported failure on
every successful start. The file is deleted rather than kept alongside its
replacement, because two plans for the same work is the drift this project
exists to avoid. Git has it.
