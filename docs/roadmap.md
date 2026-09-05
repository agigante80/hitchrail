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
3. **Cost-of-delay order, which was added on 2026-09-04 and has exactly one
   member so far.** A phase whose cost rises with every day it is not done
   comes forward, even past phases that are more valuable in themselves.

**Phase 12 runs next, ahead of 9, 10 and 11.** It changes what a project is
called on the wire, so every saved link and every API caller written against
0.1.0 changes with it. That is a MINOR while the version is `0.y.z` and a MAJOR
after 1.0, and 0.1.0 was published on 2026-09-04 with no installed base. The
break is free today, and every subsequent day it is not. Phases 9, 10 and 11
make Hitchrail better and do not get more expensive by waiting, so they wait.

The renumbering that would follow from moving it is deliberately not done. The
milestones are the queryable record and renaming five of them to reorder one is
churn that breaks every link into them. The order is what this section says,
not what the numbers imply.

<!--
Every closed phase carries a `**Status: done**` line directly under its
heading, with the closing date and the issues. Three phases had their milestone
closed and every issue closed while saying nothing here at all, because the
file was using three conventions at once: a status line on 0 and 1, a `(done)`
suffix on 4, 5 and 6, and nothing on 2, 3 and 7.

The suffix is kept where it is rather than churned, because
`test_the_roadmap_marks_a_phase_done_only_when_its_plan_is_finished` reads it.
A new phase gets the status line. AGENTS.md says this file is the one place
that says what is built, and for three phases it was not saying.
-->

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

**Status: done**, closed 2026-08-25. Issues #6, #8, #9, #13, #14, #15 and #16.

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

**Status: done**, closed 2026-08-26. Issues #11, #18, #19, #22, #23, #24,
#25, #26, #27, #29 and #31.

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

## Phase 6: Interface (done)

**Plan: [`superpowers/plans/2026-08-27-hitchrail-phase-6-interface.md`](superpowers/plans/2026-08-27-hitchrail-phase-6-interface.md)**

**Closed 2026-09-03.** All six tasks implemented and all eleven exit criteria
ticked with evidence.

The browser interface from the design canvas, and the end to end tier that
proves it. Six tasks, 18 to 23. Delivers: the single page and its assets, the
list with search and filter, the start and stop flows including the escalation,
the log drawer, the new folder sheet, the memory footer, live updates over SSE
with reconnection, the token screen, dark theme, and the Playwright end to end
tests running against a private tmux server and a fake `claude` shim.

**What the last criterion cost, because it is the point of the phase.** "Every
flow works on a real phone against a real machine" sat unticked for six days
while everything else was green, and running it produced defects no tier could
reach:

| Found by | What |
|---|---|
| The first hour against a real root | #84 a tmux server's own argv read as a detached agent, #88 a session stuck on a trust prompt reported as `running`, #83 a `Kill pid` button with no handler, #81 a timeout asserting from a listing it never read, #89 a "graceful" stop that was a double interrupt quit |
| Running #89's sequence mid task | #101, the stop opening a prompt and leaving the agent on it |
| Two Android devices, three browser engines | #103 the keyboard burying the sheet's primary action, a row crushing its name to one character per line, and assets served with no `cache-control` so a fix could ship and not be seen |

Every one of those was invisible to a suite that was passing. The phase's own
standing rule is why they were found at all: a phase is finished when the
behaviour has been watched working in the running application.

**The criterion was ticked on partial evidence, deliberately.** Three of the
seven flows were walked; thumb reach and a real radio dropping are not
simulable, and no iOS device exists on this network, which leaves #103's
`visualViewport` fallback unexercised on the platform it was written for. The
plan records it and #75 carries the full account. Residual findings get their
own tickets rather than holding a phase open.

**Test coverage:** this is where the browser tier arrived. `tests/e2e/` runs
Playwright against the real server on a temporary root with a fake `claude`
shim, and it drives a PRIVATE tmux server for the same reason the live tmux
tier does. It is the only tier that can see SSE reconnection after a
backgrounded tab, the stop escalation in the state the user is really in, and
the layout holding at a phone viewport. That was #38.

## Phase 7: The security argument holds

**Status: done**, closed 2026-09-03. Issues #4, #35, #77, #79, #80, #91,
#108, #109, #111, #112 and #115.

**Objective: everything the design promises about safety is true and asserted,
before anything is published.**

This comes BEFORE the release and did not used to. The roadmap's own words are
why: prove the security tests actually assert *before* shipping something that
spawns an agent with permissions skipped, "because three defects in this project
shipped green at 98% branch coverage". A release is the one step that cannot be
taken back, and every ticket here is a claim the design makes that nothing
currently checks.

Delivers: security headers on every response, mutation testing over the five
modules between a web page and a shell, the threat model naming the powers the
API actually has, and the CI supply chain pinned.

**Done when:** a changed line in any of those five modules makes a test fail,
every response carries the headers with a test per refusal, and section 5 names
keystroke injection and pid signalling as capabilities rather than leaving them
to be discovered.

**Closed 2026-09-03.** All three exit criteria ticked with evidence, and every
ticket resolved.

| Done | |
|---|---|
| #4 | every action pinned to a SHA, and a guard so the next one cannot arrive on a tag |
| #35 | mutation testing on the five modules: 836 mutants, 680 killed, the survivors read and categorised |
| #77 | nosniff, framing refused, a CSP per route |
| #79 | the fragment grant asserted against the server's log rather than the browser's |
| #91 | keystroke injection and pid signalling named in section 5, and a grep keeping the first one narrow |
| #108 | the token demand follows reach, not the bind address |
| #109 | `HITCHRAIL_TOKEN`, because argv is world readable |
| #111 | the documented middleware order was the reverse of the real one |
| #112 | token before origin was a promise nothing checked |

**#80 was closed by doing something else, and the reason is worth carrying.**
It asked where to move the `?token=` carrier so `security.py` would come back
under its cap. Measured, that was unreachable: the movable unit is 101 lines
against a 542 line file, landing near 435 with the exception intact. The query
grant was never what made the file long.

Reviewing it turned up the better question. The carrier existed so "an already
saved link does not break", and **nothing had shipped**: no tags, no release,
and nothing had generated a query link since the banner moved to
`/grant#token=`. It protected compatibility with a version that was never
published, and the window in which deleting it was free closed at Phase 8, the
next phase. #115 deleted it: 135 lines, `security.py` at 409, exception gone.

What left with it mattered more than the lines. `_scrub_grant_param` existed
only to keep that carrier's token out of uvicorn's access line, and rested on
where uvicorn emits that line rather than on anything ASGI guarantees. A
control whose correctness depends on another project's call ordering is one
worth not needing.

Three tickets came out of the work rather than into it: #113 (a spawned agent
inherits `HITCHRAIL_TOKEN`, Phase 9), #114 (two tests that failed in CI and
passed on rerun, Phase 10), and #107, which moved to Phase 9 because it depended
on two tickets that live there.

**What the phase was for, in two examples.** #35 found that
`_safe_redirect_path` could be turned into an open redirect by changing
`path[1:2]` to `path[2:2]`, while the test written for exactly that case could
not fail: httpx resolves `//evil.example` as a netloc, so the application never
saw it. A test that had been green since Phase 2 was asserting nothing about
the thing it was named for.

And #80 was a ticket about where to put code, which turned into deleting it,
because reviewing the argument found that its premise had expired. **Both
findings came from checking a claim rather than reading one.**

#107 moved to Phase 9 on 2026-09-03. It depends on #96 and #85, which live
there, and a phase cannot depend on a later one. Its documentation half, the
section 5 paragraph naming pid signalling, stayed in #91 so the exit criterion
below keeps an owner.

## Phase 8: Release

**Objective: a stranger can install it, understand it, and report a hole in it.**

The original Phase 7, narrowed back to what it actually said it was. Everything
that accumulated in it because "Release" was the only bucket left has moved to a
phase about that thing instead.

Delivers: PyPI publication as `hitchrail`, a tagged GitHub release, a README a
stranger can follow with screenshots of the phone case, a security policy, and
the contribution rules written where a person and a non Claude agent can both
find them.

**Done when:** `uvx hitchrail` works on a machine that has never seen this
repository, and the security section is the first thing a reader meets after
learning what the tool does.

**And two more, added by #110** rather than left implicit in "install and
understand". A tool whose point is reaching agents from a phone is not
installable in any useful sense while the only documented way to run it is a
foreground shell:

- `packaging/hitchrail.service` exists as a user unit template, its flags are
  asserted against the real CLI parser, and it is documented as a file to edit
  rather than to install blindly.
- `docs/guides/phone-access.md` exists, ordered overlay first, named address
  second, wildcard never, each with its exposure stated rather than only its
  instruction.

**Plan: [`superpowers/plans/2026-09-04-hitchrail-phase-8-release.md`](superpowers/plans/2026-09-04-hitchrail-phase-8-release.md)**
Started 2026-09-04. Six tasks, 24 to 29.

Tickets: #58, #59, #60, #61, #62, #105, #110, #116, #117, #170.

**#170 arrived late and belongs here rather than in a later phase**, because it
is a defect in the unit template #110 shipped. `Restart=on-failure` restarts on
any non-zero exit and a config refusal exits 2, so an `EnvironmentFile` with a
blank token loops: measured at 37 restarts and 38 copies of the same message,
never rate limited because `RestartSec=5` keeps it under systemd's default. The
template's comment claims `on-failure` prevents exactly that. Verified fix is
`RestartPreventExitStatus=2`, and a uvicorn bind failure exits 3, so the case
where retrying IS right still retries.

**Phase 8 therefore reopens for two items**, both on the same file: #110's
manual reboot verification, and this.

**#106 was the gate and is closed**, by decision rather than by the objects
being purged. What it described remains true: the pre-rewrite objects are served
by SHA until GitHub collects them, nothing references the commit, and the remedy
is a Support request, which has been sent. The owner accepted the residual
exposure rather than hold the phase for it, and the reasoning is on the ticket.
The plan records it as a risk accepted rather than a problem solved. One part of
it survives as a live requirement: a screenshot or fixture carrying a real
project name would be the same failure through a door this phase opens itself.

**Two deliverables had no ticket, and both were found the same way**, by reading
the exit criteria against the ticket list rather than the list against itself.

#116: the objective delivers a PyPI publication and a tagged release, and the
eight tickets on the milestone were documentation, screenshots, a funding link
and the blocker. Every one could have closed with nothing shipped.

#117: "the security section is the first thing a reader meets" was owned by
nobody, and the plan's task 27 read "README assembly", a task line standing in
for a ticket that did not exist.

**Twice in one phase is a pattern rather than an oversight.** Every check this
project has reads from the ticket list: `ticket-gate` scores a ticket that
exists, `check-ticket-hygiene.sh` sweeps for missing milestones, and
`test_docs_are_true.py` checks claims about code. A deliverable nobody ticketed
is invisible to all of them, because there is nothing to inspect. #118 carries
the guard, in Phase 10 where the gates are made to check what they claim to.

Also on review: #110 and #116 swapped, because #110's own dependencies name the
publish and it had been scheduled first, and #17 moved to Backlog, because a
funding link serves none of install, understand or report.

## Phase 9: The truth on a shared machine

**Status: done**, closed 2026-09-05 at `ccfa3c3`. Issues #93, #96, #102, #46,
#49, #95, #97, #113, #85, #100 and #32. Every exit criterion is ticked with
evidence, and #107 left the phase rather than being skipped in it.

**Objective: derivation is right on a machine Hitchrail does not own.**

Every defect in this phase was found the same way: by running against a real
root with another tool's sessions on it. The suite's fixtures describe a machine
where Hitchrail is the only thing that has ever run, which is why none of these
was reachable from it.

Delivers: derivation that agrees with itself in both directions, adapters that
survive a tmux they did not start, and the input box check that stopped being
fragile.

**Done when:** an agent inside another tool's session, a tmux binary under
another name, and a terminal that emits an unusual escape all produce an honest
answer rather than a confident wrong one.

**Plan: [`superpowers/plans/2026-09-05-hitchrail-phase-9-shared-machine.md`](superpowers/plans/2026-09-05-hitchrail-phase-9-shared-machine.md)**
Started 2026-09-05. Twelve tickets, tasks 30 to 41, in six batches.

Tickets: #93, #96, #102, #85, #46, #49, #95, #97, #100, #32, #113, #107.

**That list gained two and was reordered, both deliberately.** #113 arrived from
Phase 7's retrospective and #107 from #83, after the original line was written,
so this section named ten while the milestone held twelve. The order is now the
plan's batch order rather than the order they were filed, because the ordering is
a dependency: #107 must follow #96 and #85, since it builds a destructive control
on top of an identification that has been wrong twice this month.

**Eight shipped, then four decisions were taken on 2026-09-05, two of them
became code the same day, and the phase closed.** #93, #96, #102, #46, #49, #95, #97 and #113 are
done and closed with their commits. #85, #100 and #32 were escalated rather than
implemented, and #107 was blocked behind #85. Each of the four was a decision
rather than an implementation, and each is now decided on the ticket:

- **#85: `detached` is redefined, and the missing fact becomes an overlay.** The
  four options were a fifth state, `running` qualified, the label redefined, and
  reporting `stopped`. What settled it is that a foreign-owned agent and a true
  orphan are operationally identical - start refuses, graceful stop is
  impossible, kill-by-session is impossible for both - and differ only in what
  the row should say. That is what this project's overlays are for, and the
  discriminator is free: `list-panes -a` already returns the foreign panes and
  `pane_pids` discards them. The design's section 4.1 wording moves with it.
- **#100: the capture is paid for, capped at ten.** Measured rather than argued:
  `capture-pane` costs 3.0 ms against a warm server on the development machine,
  so ten stuck rows is +30 ms on a listing and fifty is +149 ms, and the browser
  refreshes every 700 ms for a whole stop wait. Two corrections came out of
  reading the code: `input_is_clear` cannot be reused, because its anchor was
  shortened so a modal and a person's draft both read as "not clear", and the
  free "no link yet" signal cannot replace the capture, because a link is not
  written for every session.
- **#32: closed as a decision.** Option B, keying sessions off the resolved path,
  now contradicts two settled arguments rather than one open question: #119's
  `<root-label>~<folder>` identity, and `sanitize`'s own "injective by
  construction beats injective by hash". The behaviour, its docstring and the
  test that pins it are unchanged, and the work went to the cause instead.
- **#107 is unblocked and smaller.** With an owner name on the wire it refuses
  whenever a foreign session owns the agent, so the first unscoped destructive
  path applies only to agents nothing is known to own. The race its body accepts
  is closable rather than only narrowable: this project declares Linux and 3.11,
  so a pidfd pins the process the pid was reused from, and the ordering is
  acquire-then-verify.

**Two tickets left for Backlog, both causes rather than defects.** #172 was the
cgroup owner test, which would see the sockets and terminals the pane map
cannot. **It is closed, and the reason is worth reading**: measured twice on a
real machine, cgroups are inherited across fork, so a tmux server started from
inside a pane sits in that pane's scope and the proposed rule called a LIVE tmux
server an orphan. The mechanism also yields a bare UUID, so it could never have
delivered the session name it promised. #189 carries the question it was asking,
by ancestry rather than by cgroup, scoped as row wording and explicitly not as a
gate. #173 asks whether `NAME_PATTERN` must still refuse a space, which is
what makes the alias in #32 the obvious response to our own error message; it
also records that `pane_pids` parses `#{session_name} #{pane_pid}` on the first
space, so widening the pattern is not a one-line change.

**How the four actually ended.**

- **#85 built** at `0b24fbb`, with review round 1 at `acafafc` and `ccfa3c3`.
  The row names the session that owns a foreign agent; where none can be seen it
  says so rather than claiming there is none. The first exit criterion is
  ticked, proven against a real tmux and through a browser rather than only
  against a fake.
- **#100 built** at `ccfa3c3`, and the cost decision went the other way from the
  ticket: the capture runs on the sweep, never on the listing route, so the cost
  scales with the state of the machine rather than with how often a browser
  polls. `test_list_captures_no_pane` keeps its assertion untouched, which is
  the outcome the placement was chosen for.
- **#32 closed as a decision**, unchanged behaviour, with the reasoning on the
  ticket and the cause filed as #173.
- **#107 moved to Phase 14**, not skipped. The gate found its scoping premise
  false: `foreign_session is None` means no owner was SEEN, not that there is
  none, and that bucket holds agents under another socket, under screen, under a
  plain terminal, and another user's, since tmux sockets are per uid and the
  process table is not. Signalling on that basis is the warning #85 just added
  to the interface, inverted. It was moved to Phase 14 behind #172, which was to
  establish orphanhood positively.

  **That dependency was withdrawn the same evening**, and the correction belongs
  here rather than only on the ticket. #172's mechanism turned out to be wrong,
  and it was never the right prerequisite: `pidfd_send_signal` returns `EPERM`
  across uids, so the case that worried us most is refused by the kernel rather
  than by us, and #107's real safety property is acquire-then-verify with a
  pidfd, which does not depend on knowing who owns the process. Requiring a
  signal with a demonstrated false positive and a measured false negative to
  AUTHORISE a destructive action is control 7 inverted. What is left is one
  honest sentence in the confirmation, and #107 is unblocked.

**Six tickets came out of this work rather than being fixed inside it**, which
is the phase behaving as intended: #172, now closed, and #173 from the
decisions, #174 from a
control count that had drifted across three documents, and #175, #176 and #177
from the review of #85. Two of those name tests this phase itself added that
could not fail on what they claimed, which is the failure Phase 10 exists for
and worth noticing in a phase about honest answers.

## Phase 10: A suite that would notice

**Objective: the tests fail when the code is wrong, and only then.**

The recurring failure this phase exists for: a fixture written to agree with the
code. It happened three times in one session, and each time the test passed
while the thing it named was broken.

Delivers: fixtures that cannot agree with the bug, a tier that reads the real
machine without depending on it, a device tier that makes the phone flows
repeatable, and the gates checking what they claim to.

**Done when:** the fixtures are built from the production path rather than
beside it, no tier's result depends on what the machine running it happens to
have, and a phase's progress count in prose is checked against the boxes it
describes.

Tickets: #94, #104, #70, #73, #92, #67, #30, #10, #86, #5, #114, #118, #128,
#135, #136, #143.

**#51 left this phase for Backlog.** It corrects two commit messages that
describe a different change. The trees are right and the gates were green, so
nothing here would have caught it and nothing is proposed that would: it was in
a phase whose exit criteria it cannot meet. The list above also gained the six
tickets filed into this milestone since it was written, which is the drift #92
is open about.

## Phase 11: The interface in every state

**Objective: every state the interface can be in says something true, legibly.**

What is left of the browser work after Phase 6 closed: the states that are rare,
the wordings that are wrong, and the one module that has grown past the point
where anybody reads all of it.

Delivers: a stream that reports its own failures honestly, dialogs whose titles
match what happened, colour that passes AA on its own tints, a memory footer
with a ceiling, and `app.js` split along the seam it already has.

**Done when:** no screen states something it did not read, every token pair
passes AA, and no file in `web/` does more than one thing.

Tickets: #68, #69, #71, #72, #78, #82, #90, #161, #162, #163, #165, #166, #169.

**#169 is the one to read, because it is a dead end and its justification was
false.** A stop whose input box will not clear refuses to type, correctly, and
the resulting dialog offers only Close. The comment above it justifies
withholding a kill by saying "Kill is still on the row". `renderRow` renders
Open, Get link, Start, Stop and Clear, and no kill at all; `killNow` is
reachable from three places and all three are downstream of a `DELETE` that
succeeded. So the session cannot be ended from the interface, and the reasoning
that made that acceptable pointed at an affordance nobody had built.

That is #83's defect inverted. There, a button existed with no route behind it
and a browser test asserted only that it was visible. Here a route exists with
no button, and a comment asserts a button that does not.

**Section 7 forbids escalation by DEFAULT, not availability**, and the two
timeout dialogs already resolve the identical situation the other way, with the
kill second and styled danger. Three terminal dialogs, two offering a decision
and one offering Close; the inconsistency was the bug. The operator's position
is recorded on the ticket as the decision: a force kill is always theirs to
choose. Putting a kill on the row itself stays out, because that WOULD be
escalation by default, and it gets its own ticket if it is ever wanted.

**Three arrived from using it and they are the shape this phase was cut for.**
#161 is a defect with a measured cause: every dialog is pinned to the bottom of
the viewport, because `margin-bottom` resolving to `0px` replaces the user
agent's `margin-bottom: auto` and collapses the centring. A regression from
#103's keyboard fix, whose reasoning is right and whose default is not, and
whose test covered only the keyboard-open direction. It matters more than a
misplaced box: `showDialog` orders actions safest first so the dangerous one is
furthest from the thumb, and a bottom-pinned dialog inverts that.

#162 and #163 are "the wordings that are wrong", literally. `Open` is the one
control that does not open the session, and `Continue` is Claude Code's own word
borrowed out of the sentence that explained it. **They are one decision filed as
two tickets**, and both say so: renaming the log control to `Logs` is what frees
`open` for the control that actually opens a session.

## Phase 13: Fifty rows on a phone

**Objective: the interface stays usable when there are fifty projects across
five roots, and says what it knows about each.**

Phase 11 is about states saying something true. This is about a person finding
the row they want among a lot of them, and about the page answering questions it
currently cannot: which version am I looking at, since when, as whom.

Cut from a real five root install rather than from the design. Every ticket here
came from using it, which is also why none of them is a new power: the list is
complete and correct, and what is missing is navigation and provenance.

Delivers: filtering by root, a header that survives scrolling, a footer that
names the version and links to the source, the server's own start time and
account, logs at a URL you can bookmark, and an icon set.

**Done when:** a fifty row list can be narrowed to one root in one tap, the
primary action is reachable at any scroll position, and the page answers "which
build is this and who is it running as" without an SSH session.

Tickets: #146, #147, #148, #149, #150, #151, #160, #164, #168, #179.

**#179 came from a phone, and it is a rule whose premise moved rather than a
regression.** A stopped row crushes its name to one or two characters per line:
an eighteen character name over three lines, a six character one over two. The
guard for exactly
this exists, from #75, and covers `running`, `stale` and `detached`, because
when it was written a stopped row carried a name, a badge and one button, which
fit. #122 then added the root chip, `flex-shrink: 0` like everything else on
that line, so the name became the only item that could give and
`overflow-wrap: anywhere` let it give all the way down.

It belongs here rather than in Phase 11 because the fix spends vertical space
this phase is otherwise trying to save: a stopped row roughly doubles in height,
which at fifty rows is about 2,200px of scroll becoming 4,400px. #150 is what
gives that space back, by turning six word badges into glyphs, so the two should
be read together.

**#150 was rewritten from twenty icons to seven, and the two icon tickets pull
in opposite directions on purpose.** #150 is a SET, so it is vendored from an
existing library and never generated: a set has to agree with itself on grid,
stroke weight and optical alignment, and that agreement is what generation gets
wrong. #160 is the application's own MARK, one drawing that has to agree with
nothing and that no library ships, so drawing it is the right call there.

The seven are the six state badges plus the protected row. The badge is the one
place a shape does something a word cannot, because a list of fifty is scanned
rather than read, and because it stops six states being told apart by colour
alone while #69 is open. Everything else keeps its word: an argument that Stop
and Clear needed distinct glyphs did not survive reading the code, since Stop
renders only on a running row and Clear only on a stale one, so the pair never
appears together.

**One of these closed a question rather than opening one.** #149 was filed as
"research how to improve the header, iframed?". Measured on `claude.ai`:
`x-frame-options: SAMEORIGIN`, plus a CSP that says the same thing. Framing the
session view under our header is refused by the browser, twice, and the only
workarounds are a proxy that strips a vendor's frame guard on an authenticated
session or a browser extension. It is recorded as impossible rather than left
open as untried, and what remains is the real question underneath it.

## Phase 14: The perimeter, chosen rather than assumed

**Objective: the operator chooses how this is reached and how it is proved,
instead of being handed one answer.**

Every ticket here touches a security control, so each is a decision before it is
work. **No count in this line**: it said "three" while the milestone held four,
then six, which is the decay `AGENTS.md` already refuses for phases and modules.
The list at the end of this section is the record. They are together because they interact: TLS changes what a
sign-in form costs, and both change what the README's stated limitations say.

Delivers: HTTPS from the server itself rather than only from a proxy in front of
it; a sign-in page for people who have a token but not the saved link; and roots
that come from a config file rather than only from a unit's `ExecStart`.

**Two of the three are deliberately NOT what was asked for**, and the tickets
argue it rather than quietly narrowing the scope:

- **#153.** A prompt is missing and should exist. Replacing a 192 bit token with
  a password a person can type on a phone is a downgrade on an API equivalent to
  a shell, with no rate limiting anywhere in this codebase. Stage 1 is a form
  that accepts the token. A passphrase ships only with a slow KDF, rate
  limiting, and a refusal off loopback without TLS, and that list is the cost
  rather than an obstacle course.
- **#154.** A route that takes a PATH removes control 5 outright: the credential
  that lists projects would become one that runs an agent anywhere the user can
  write. The answer is a config file the operator edits on the machine, and a UI
  that can only toggle roots already in it. That is most of what was wanted and
  none of what it would have cost.

**Done when:** a LAN deployment can be HTTPS without a second daemon, a person
holding a token can get in without a saved link, and adding a folder does not
mean editing a systemd unit.

Tickets: #152, #153, #154, #123, #107.

**#123 moved here from Backlog.** `session_prefix` is a config field with
validation and no flag, which is the same shape as #154's problem: configuration
that exists in the code and cannot be reached by the operator. #154 says taking
it first makes this a two-line addition, and the Backlog note below no longer
means anything now that Phase 12 has closed.

## Phase 15: The package as strangers meet it

**Objective: somebody who has never seen this project can install it, tell what
it is, see that it is maintained, and be helped when it goes wrong.**

Everything here came from looking at the published PyPI page beside our own
README and finding they disagree, or say nothing.

**The last clause of the objective was added for #167 rather than #167 being
squeezed under the original.** Logging is not part of meeting a package, and
answering a stranger's bug report is the other half of publishing one. Widening
the phase is the honest move; filing it here under "installation" would not
have been.

Delivers: `pip` acknowledged as an install route, the deprecated licence
classifier removed and the licence made clickable, a badge row on the first
screen, and a bot that keeps the dependencies and the pinned actions honest.

**#155 is P0 and the only P0 open.** Every third party action here is pinned to a
commit SHA on purpose, because a tag is a mutable pointer. That pin is correct
and it cannot update itself, so today nothing tells anybody a newer version
exists. A supply chain that only updates when somebody remembers is not a
control, and this package is installed with `uvx` on other people's machines.

**Done when:** the PyPI page and the README agree, the licence is one clickable
statement rather than four scattered ones, and a direct dependency going stale
arrives as a pull request against `develop`.

Tickets: #155, #156, #157, #158, #167, #141, #17.

**#167 came from failing to answer a support question about this machine.** An
operator asked whether a stop request had actually been sent. The journal held
uvicorn's access lines and nothing else: not the keystrokes, not the pane check,
not the decision to stop waiting. Measured afterwards, the nine `logger` calls
in the tree have no handler at all, so a warning prints as a bare message with
no timestamp and no level, and `info` and `debug` are discarded entirely. Two of
the nine are therefore dead in every deployment. That is the gap to close before
strangers start filing bug reports.

## Phase 16: What survives a reboot

**Objective: decide whether Hitchrail remembers anything, and if so what.**

One ticket, and it is a phase rather than a Backlog entry because of what it
changes rather than how big it is.

**Hitchrail holds no state.** The security argument says so in as many words:
no database, no session registry, every answer derived from the operating
system on demand. That is why nothing can get out of sync, nothing needs
migrating, and no file's contents decide what runs.

Remembering which sessions were running is the first persistent state in the
product, and it is specifically a file that decides what gets spawned. The
ticket is written for the requested default of ON, and it lists the six things
that have to be true for that default to be defensible: the memory guard
re-evaluated between each restored start, a cap, never doubling an agent that
survived, a command line kill switch, protection against a restart loop
multiplying it, and restored rows being visibly restored. If any of the six is
not built, the default is off and the feature still ships.

**Done when:** a reboot brings back what was running, exactly once each, without
a person tapping anything, and the security argument has been rewritten rather
than quietly outgrown.

Tickets: #159.

## Deliberately later

Not scheduled, and not to be smuggled into an earlier phase:

- Restart as its own operation. It is stop then start, and the interface can
  compose it.
- More than one root.
- Authentication beyond a single shared token. #153 is not this: it adds a way
  to TYPE the existing credential, and says why a second kind of credential is a
  downgrade rather than a feature.
- Streaming logs. A tail on demand is enough until it demonstrably is not. #151
  gives the tail its own URL and deliberately does not stream it.
- Sending input to a session. Hitchrail starts and stops agents; it is not a
  terminal, and making it one is a different product. #159 restores sessions
  and deliberately does not reach into an agent's own conversation state.

  **#166 asks for one keystroke and is not this**, and the difference is
  written on that ticket in four conditions: only in reply to a prompt our own
  stop provoked, only from a set fixed in code, only while the pane still shows
  that prompt, and never chosen for the operator. The interface today offers
  `Kill it` for a question whose safe answer is one keypress, which is the
  destructive option offered and the safe one withheld, in a situation
  Hitchrail created. If any of the four conditions is dropped it becomes the
  deferred item and the deferral stands.

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
- **`no_agent`** is returned when the derived state rules the action out, and
  **a stale row offers Clear rather than Stop**. Both come from #98, and #83
  widened the first: a stop finds nothing to ask in a `stale` or `detached`
  session, and a kill finds nothing to kill in a `detached` one, because a kill
  targets the tmux session and that state is defined by not having one.
  The design's stop flow assumes there is an agent to ask, and two of the four
  derived states have none: `stale` is a tmux session whose agent is gone, and
  `detached` is an agent with no tmux session. Verified against a real tmux
  rather than assumed, because the old behaviour looked like it worked: the
  quit command an agent understands is not one a shell does, so a stale
  session survived the graceful stop and the whole thirty second wait before
  offering a kill. Stop on such a row could only ever refuse, and the
  interface's own rule is that offering a tap that refuses has already failed
  the person holding the phone. Clear is the kill route, confirmed and styled
  as destructive, because `stale` says only that no AGENT is in the session
  and the pane may be running something else.
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

## Phase 12: More than one root

**Runs next, out of numeric order.** See "How the phases are cut" above for
why: this is the one phase whose cost rises every day it is not done.

**#119 is decided as of 2026-09-04.** A project is `<root-label>~<folder>`,
always, including with one root. The reasoning, the three options that lost and
the questions that followed from the answer are in the design, section 6.0.
The three implementation tickets are no longer blocked.

**Objective: a project is still one thing when there is more than one place to
keep projects.**

`--root` takes one folder and every directory inside it is a project, so
somebody with a client tree and a personal tree cannot see both in one
Hitchrail. Running two instances is the obvious workaround and it is unsafe:
the session name is derived from the project name and nothing else, so two
roots containing a folder of the same name collide.

```
~/work/vessel      -> hr-vessel
~/personal/vessel  -> hr-vessel
```

**The failure is silent and destructive.** The second project reads as
`running` on the first one's session, and tapping Stop there stops the other
one's agent.

Delivers: several roots in one instance, a project identity that stays unique
across them, and an interface that shows which root a row is in.

**Done when:** two roots each containing a folder of the same name are two rows
that can be started and stopped independently, proven against a real tmux
rather than a fake, and a single root deployment is unchanged.

**This has to land before 1.0.** `docs/versioning.md` cuts 1.0 when the HTTP
interface is one you are willing to keep, and this phase decides what
identifies a project on the wire. After 1.0 that is a MAJOR break with saved
links and any client to migrate; before it, it is a MINOR under the `0.y.z`
rule.

**#119 gates the rest of the phase and is a decision rather than work.** Four
options are written up with what each costs. Everything else here is written
against a question and will need rewriting against the answer, which is said on
each ticket rather than left to be discovered.

Tickets: #119, #120, #121, #122.

The interim workaround was #123, kept out of this phase because it was a
workaround for the limitation this phase removed. **It is now in Phase 14**, on
its merits rather than as an interim anything: one instance takes several roots,
so nobody needs two, and `session_prefix` is simply a setting the operator
cannot reach.
