# Phase 25: The wrap up, hardened

**Objective: the stop sequence Phase 19 shipped is as careful at its edges as
it is on its main path, and the journal says what it did.**

**Written 2026-10-07 while Phase 19 was still open** on its one unticked
criterion, Andrea watching a real wrap up. It opens the day 19 closes. If that
watch finds a defect, the defect joins this milestone as batch 0 and is built
first.

## Goal

Every finding the Phase 19 reviews filed is fixed or closed with its reason.
`engine.py` is split along the seam it already has before any of them land.
A kill nobody tapped reaches only the agent that was looked at, and every kill
leaves a line in the journal.

## What this phase is actually about

Phase 19 shipped the wrap up (#242), the stop policy (#239, #409) and the
logging that makes both diagnosable (#167). Its review loops stopped where the
global rules say they stop: #242 on its trip wire at round 3, #239 clean at
round 2, #409 with three lows. Everything left was filed, 29 tickets, and
landed in Backlog so a low never held the phase open. The roadmap's second
Backlog rule says new surface is followed by a phase that hardens it, as 20
followed 14 and 22 followed 21. This is that phase for 19.

**Checked against the tree on 2026-10-07**, reading each body, its comments
and the lines it names at `3d74855`: all 29 still describe the code, none is
fixed by a later commit, none duplicates another. Two needed a decision, both
taken by Andrea that day and recorded on the ticket:

- **#391: stop deriving the plain http origin** for a declared `--allow-host`
  whose `--allow-origin` values are all https, under a loopback bind. The
  grant is refused with the origin refusal rather than answered 200 and then
  401 forever.
- **#419: the policy in force is the one confirmed.** `StopMarker` records the
  stop policy at `stop()`; the expiry reads the marker, never the live
  setting.

**The from-review tickets are terse,** as Phase 22's were, and are accepted as
they are under the same standing exception: each is one change with a concrete
input already in the body.

**Why the split goes first.** `engine.py` is 1786 lines against a cap raised to
exactly that, and nine of these tickets edit `stop()`, `advance_wrap_ups`,
`expire_stops` or `_end_anyway`. #274 names the seam: the pidfd path, which
#418's kill by pid needs anyway. Splitting after the fixes is how
`claude_ipc.py` grew past its seam in Phase 22; Phase 19 split it first and
the suite proved the move.

**Three tickets add to `StopMarker`.** #406 (a typing flag), #407 (restoring
`closing` after a refused exit) and #419 (the policy at confirm) each change
the marker and the same two branches. Built separately, a later one undoes an
earlier one. Task 179 decides the marker's shape for all three before any is
built.

**#181 joins** from Phase 17 by the Backlog's first rule: it is a `from-review`
ticket about docstrings in `engine.py`, which this phase changes most.

## What this phase is NOT about

**New stop behaviour.** No new setting, no new phase of a stop, no new route.
Each task is a named defect, or a test that cannot fail when it should.

**`stop_prompt` over HTTP.** Still never; "Deliberately later" binds.

**`app.js`'s split.** Phase 24 owns it. This phase's web tasks are five small
edits to the stop dialog and are cheaper made in place than worth pulling the
split forward.

**`server.py`'s split.** Phase 16 owns it; #392 is one `await`.

## Expected work

Tasks continue from Phase 19's 176. Batches run in order; inside a batch the
order is the one written. Review at the end of each batch, bounded as the
global rules say, and findings go to Backlog, not this milestone.

### Batch 1: `engine.py` split along its seam, task 177

- [x] **Task 177, #274 (P3).** The pidfd and signal path leaves `engine.py`
      for its own module, every public name still reached as before. The
      structural guards key on the new path first, as a no-op commit, so the
      move's diff proves one thing. The size cap, `.claude/rules/security.md`'s
      list, mutmut's `source_paths` and the import contracts move with it. No
      behaviour change, and the suite unchanged proves it.

### Batch 2: the wrap up's engine edges, tasks 178 to 185

- [x] **Task 178, #405.** Skip SGR 58's operands in `claude_ipc/screen.py`.
      First because it is the only finding whose failure is in the dangerous
      direction: an exit typed into a busy agent.
- [x] **Task 179, #406.** A Stop while the sweep types the exit is a no-op.
      Decides `StopMarker`'s shape for #407 and #419 as well.
- [x] **Task 180, #407.** The four edges: the docstring, a refused Exit now
      restoring `closing`, the stranded marker, the moved list.
- [x] **Task 181, #418, #412, #387.** `end_anyway` kills by the agent's pid,
      through batch 1's seam; its fallbacks are tested; every kill writes a
      journal line, written once, before the read that can fail. Security
      auditor review required.
- [x] **Task 182, #410.** The expiry's and the refused exit's waiting overlay
      carry the attention epoch.
- [x] **Task 183, #419.** The stop policy is recorded at `stop()` and read
      from the marker at expiry (decided 2026-10-07).
- [x] **Task 184, #389, #390.** The start line after the start, the timeout
      line's wording, duration and person wait.
- [x] **Task 185, #181.** The two docstrings from #100 say what the code does.

### Batch 3: the stop dialog, tasks 186 to 188

- [x] **Task 186, #408, #411.** One listing change, two fields: the typing
      phase other browsers must see, and the stop's start a reopened wait
      counts from. `docs/api.md` in the same commit.
- [x] **Task 187, #416, #414.** A repeated Stop on an exiting row says exit,
      not wrap up; Stop all counts in the singular.
- [x] **Task 188, #417.** The lost reply test fails without the fix on a slow
      runner, re-checked after task 186.

### Batch 4: the stop policy's settings, tasks 189 to 191

- [x] **Task 189, #421.** A saved `stop_policy` under a pin is cleared or
      reported, so removing the pin never silently restores a kill.
- [x] **Task 190, #397.** A refused state file is said at startup, not
      forgotten.
- [x] **Task 191, #420.** A pinned refusal writes no roots half beside it.

### Batch 5: bind and command line edges, tasks 192 to 196

- [x] **Task 192, #391.** No plain http origin derived for an https only
      declared host under a loopback bind (decided 2026-10-07); the
      docstring says why; `CHANGELOG.md` under Changed. Security auditor
      review required.
- [x] **Task 193, #395.** The IPv4 mapped loopback is refused by name, not by
      a uvicorn traceback.
- [x] **Task 194, #394.** The loopback advice asks the cookie rule it
      describes. After 192, which changes what it should say.
- [x] **Task 195, #393.** The absolute typed path that is not there, pinned;
      the comment about `which` corrected.
- [x] **Task 196, #413.** The spec's two passages that say expiry never kills;
      the startup line naming the policy, pinned.

### Batch 6: the journal, shutdown, and tests that could not fail, tasks 197 to 202

- [x] **Task 197, #388 (P2).** No query string token reaches the journal
      through uvicorn's access line.
- [x] **Task 198, #392.** Shutdown does not re-raise a stuck scan's logged
      error over the kill's own.
- [x] **Task 199, #396.** The TLS 1.1 refusal test fails if only the client
      refuses.
- [x] **Task 200, #403.** `{}` on the signal routes pinned as the unbound
      request.
- [ ] **Task 201, #404.** The kill mid update test opens its pidfds before the
      reap.
- [ ] **Task 202, #398.** The missed run refresh test: cause found and fixed,
      or quarantined with a ticket naming the cause. Never retried into green.

## Done looks like

- [ ] Every task ticked, or marked MOVED OUT or NOT BUILT with an issue number
- [ ] `engine.py` is smaller than at `3d74855`, and the signal path has its own
      module and its own cap
- [ ] A kill nobody tapped is bound to the pid that was looked at, and a test
      restarting the session inside the window proves the new agent survives
- [ ] Every kill writes a journal line, and no journal line carries a token,
      both asserted from captured stderr in the live tier
- [ ] Watched on the phone: a Stop with a second browser open shows the same
      phase in both, and a reopened wait shows the stop's real age
- [ ] No `from-review` ticket open in the milestone without a decision
- [ ] Roadmap says done, milestone closed, `check-phases.sh` passes

## Fails if

Drafted by the agent on 2026-10-07, to be confirmed or rewritten by Andrea
when the phase opens: it is the end of this phase and it failed badly; what
happened?

**The split changed behaviour.** A patch point in a test stopped reaching the
real function after the move, so a test passed against nothing. Rule: the
guards key on the new path in a no-op commit first, and the mutants that the
moved tests killed before are reapplied to the new paths.

**Three fixes to one marker undid each other.** #406, #407 and #419 were each
built and reviewed alone, and the third reverted a branch the first had fixed,
green because each test pinned only its own ticket. Rule: task 179 decides the
marker's shape for all three, and each later task's test runs the earlier
tasks' scenarios.

**The kill by pid killed the wrong process.** Binding to a pid read too early
let a reused pid be signalled. Rule: through the pidfd seam batch 1 extracts,
never a bare pid, and the security auditor reviews task 181.

**The hardening never ended.** Thirty one lows produced forty more, each
review round finding something in the last round's fix. Rule: review per
batch, the global loop's bounds and trip wire, and what is left goes to
Backlog. A batch still open when the rest are done closes the phase re-shaped.

**#391 broke somebody's forwarder silently.** An operator on a plain http
forwarder upgraded and their grant started failing with nothing to say why.
Rule: the refusal names the origin, the startup block says the http origin is
not derived and why, and the changelog says it under Changed.

**The flaky test hid a regression.** #398 was retried until green and the
release ran on it. Rule: task 202 finds the cause or quarantines with a ticket;
a retry is never the fix.

## Out of scope

- New stop behaviour or settings: none planned
- `stop_prompt` from the page: "Deliberately later"
- `app.js`'s split: Phase 24, #68
- `server.py`'s split: Phase 16, #205
- More than one agent's stop: Phase 23
