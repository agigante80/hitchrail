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
- [x] **Task 201, #404.** The kill mid update test opens its pidfds before the
      reap.
- [x] **Task 202, #398.** The missed run refresh test: cause found and fixed,
      or quarantined with a ticket naming the cause. Never retried into green.

### Batch 7: added 2026-10-08, after the build, tasks 203 and 204

Andrea pulled both in on 2026-10-08, the one exception to "findings go to
Backlog": each is in the direction this phase exists to close.

- [x] **Task 203, #435 (P1).** The stop dialog flake that failed twice under
      load on 2026-10-07: reproduced, its cause named, fixed at the cause or
      quarantined naming the ticket. Never retried into green.
- [x] **Task 204, #429.** `end_anyway` ends an agent only on an answer
      prompt two looks agree on, never on `shows_input_box`'s transient false
      answer during a redraw.

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

**Rewritten 2026-10-08 at Andrea's request**, after batches 1 to 6 were built
overnight, replacing the agent's draft of 2026-10-07. The question is still the
premortem's: it is the end of this phase and it failed badly; what happened?
Each scenario says whether the build already met it, the rule that answers it,
what that rule costs, and what to do next.

**1. The split changed behaviour.** A patch point stopped reaching the real
function after `signals.py` moved out, so a test passed against nothing.
- Status: not seen. 140633a keyed the guards on the new path first, 9d43ed0
  moved the code, and the suite count did not move.
- Rule: guards first in a no-op commit; the moved tests' mutants reapplied.
- Pro: the move's diff proves one thing. Con: two commits and a mutation pass
  for a change that adds nothing.
- Suggestion: the same recipe for the `settings.py` split (#443), which is the
  next file past its seam.

**2. Three fixes to one marker undid each other.** #406, #407 and #419 each
changed `StopMarker`, and the last reverted a branch the first had fixed.
- Status: not seen, but close. The batch 2a review found a medium in the
  interplay (a Kill failing during prompt typing stranded the marker), fixed in
  7079aea; #431 and #432 are the lows the same seam left.
- Rule: task 179 fixed the marker's shape for all three before any was built.
- Pro: one design, reviewed once. Con: the shape was an agent's assumption
  taken overnight (policy, typing, withdrawn), not a decision Andrea made.
- Suggestion: Andrea reads the marker's fields in the report before the phase
  closes; any change is cheaper now than after a release builds on it.

**3. A kill nobody tapped reached the wrong process, or the wrong moment.**
- Status: the pid half is met. #418 kills by the pid read at the look, through
  a pidfd, and the security audit of task 181 passed. The moment half was not:
  #429 found that `end_anyway` can end a working agent on a redraw misread.
- Rule: never a bare pid; a kill decision on screen content needs two agreeing
  looks (task 204).
- Pro: the dangerous direction is closed at both ends. Con: a second look adds
  a settle delay to every `end_anyway` expiry, and an agent that keeps
  redrawing may never be ended, which is the safe failure.
- Suggestion: if two looks are not enough on a real phone, `end_anyway` is
  better narrowed than made cleverer.

**4. A security fix covered only the shape that motivated it.** #388 removed
the token from the access line for `/?token=` and nothing else.
- Status: happened, and caught. The batch 6 review drove a real uvicorn and
  found absolute form, `?x` and `x?y` targets still journalled the token; fixed
  in 2d309ac, which also fails closed on an unknown record shape.
- Rule: a redaction is tested against the inputs the transport can produce,
  read from the installed source, not against the one in the ticket.
- Pro: the second round found nothing. Con: the fail closed branch can hide a
  real access line if uvicorn changes its record, which is the intended trade.
- Suggestion: #440 (tracebacks) is the same question one layer down; it goes
  before the next release that touches logging.

**5. The flaky test hid a regression.** A stop dialog test was rerun until
green and the release shipped on it.
- Status: half happened. #398 was found and fixed at its cause (2b9c38d), but
  a second flake, `test_kill_appears_once_the_wait_is_under_way_and_stays`,
  failed twice under load and has no cause yet (#435).
- Rule: a cause or a quarantine naming the ticket; a rerun is never the fix,
  and a release does not ship over a red run.
- Pro: the tier keeps meaning something. Con: a quarantine removes coverage of
  the kill button until the cause is found.
- Suggestion: task 203 before the next release, and capture the assertion
  text the first time it fails: neither failure kept it.

**6. develop was red, and nobody noticed for a commit.** An implementer ran
the files it touched and broke a guard elsewhere.
- Status: happened twice (d45adf3 to 929331f, 7475e33 to 202870a), each fixed
  by the next commit, never pushed to `main`.
- Rule: the guard subset (`-k "docs_are_true or size or guard or dashes or
  structure"`) before every commit, the full suite before the last.
- Pro: cheap, about a minute. Con: it is a convention an agent can skip.
- Suggestion: a pre-commit hook running the guard subset would make it a gate.

**7. #391 broke somebody's forwarder silently.** An operator on a plain http
forwarder upgraded and their grant started failing with nothing to say why.
- Status: answered, with a twist. The refusal names the origin and the startup
  block says it, but the batch 5 review found the startup line fired on the
  guide's OWN https deployment and advised turning Secure off; f178084 silences
  it there.
- Rule: the refusal names the origin, the startup block says why, the
  changelog says it under Changed.
- Pro: a forwarder operator is told before the first failure. Con: an https
  proxy and a plain forwarder on the same host now get no startup line, only
  the named 403 (#439).
- Suggestion: read the Changed entry in `CHANGELOG.md` as an operator would
  before the release.

**8. The hardening never ended.** Thirty one lows produced forty more.
- Status: not seen. Seven batches of review loops, ten rounds, one round that
  found a defect in a prior fix; the run stopped at its ticket cap of 12 and
  filed nine more on 2026-10-08 (#435 to #443).
- Rule: per batch reviews under the global loop's bounds and trip wire;
  findings to Backlog.
- Pro: the phase ended. Con: Backlog grew by about twenty tickets from one
  phase, most of them lows.
- Suggestion: the next phase that edits the stop path sweeps the stop path's
  Backlog lows first, as this one did for Phase 19's.

**9. The phase closed without the watch.** Every task ticked, the release out,
and nobody looked at a phone.
- Status: open. The "Done looks like" phone watch (two browsers, the same stop
  phase; a reopened wait shows the real age) is not done, and Phase 19's own
  watch is still pending.
- Rule: a done phase needs its watch, not only its suite.
- Pro: the e2e tier fakes the typing moment (#408); only a phone proves it.
  Con: a release can reach PyPI before the watch, so the watch can find a
  defect already shipped.
- Suggestion: do Phase 19's watch and this one in one sitting, then close both.

## Out of scope

- New stop behaviour or settings: none planned
- `stop_prompt` from the page: "Deliberately later"
- `app.js`'s split: Phase 24, #68
- `server.py`'s split: Phase 16, #205
- More than one agent's stop: Phase 23
