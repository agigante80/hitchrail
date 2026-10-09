# Phase 26: Stop, settled, and Restart on it

**Objective: no open ticket describes a defect in the path that ends
processes, and Restart is built on that path once it is settled.**

**Written 2026-10-09,** from the roadmap block and the nineteen tickets in
the milestone (#475 joined the same day, from a real Stop), each read against the tree at `55c19e5`. Andrea took the
decisions the plan needed the same day, recorded below.

## Goal

Stop, Kill, `end_anyway` and the sweep each claim and release the stop marker
in exactly one way. Two reviews and an audit found the places where they do
not, and this phase fixes them. `server.py` and `engine.py` are split before
anything is added to them. Then Restart (#472) goes on top: one press, the
graceful stop unchanged, and a start once the old agent has gone. It is
watched on a real session on the phone: once with a clean stop, and once with
a stop that times out and starts nothing.

## What this phase is actually about

Phase 25 filed what its review loops found and did not fix, and the second
Backlog rule never gave those findings a phase. Eleven of the nineteen
tickets are about one object: the `StopMarker` and who holds it. #427, #431
and #432 are three windows in which a Stop, a Kill and the sweep disagree
about that. #430 and #444 are the sweep's own looks, and #425 and #426 are
`end_anyway`'s journal line and its error path. They are all low, and they
come first anyway, because Restart adds a third reader of the marker. A
restart built on a known race inherits it, as #472's own comment says.

**Checked against the tree on 2026-10-09.** Every ticket still describes the
code. #277's first item was fixed by #272, as its 2026-10-07 comment says.
Two items are left: the `Orphan` docstring and the launcher that hides an exec
error.

**Decisions taken by Andrea on 2026-10-09:**

- **#472: the engine holds the restart.** `POST /api/sessions/{name}/restart`
  is its own route, never a flag on `DELETE`. It sets an in-memory
  `restart_pending` beside the stop marker, and like the marker it is not
  persisted. The sweep starts the agent once, and only from a `stopped` it
  actually derived. If the stop times out, is killed, or `end_anyway` ends it,
  no start follows. Each new run is a fresh conversation, as Start is today.
- **#473 (filed at this plan): split the sweep out of `engine.py`,** a pure
  move before Restart, with the cap lowered rather than raised a ninth time.
  The moved code reaches the engine through a named interface, the one #424
  gives `signals.py`, so both share one structural test.
- **#463: the guard stays,** with a comment naming the stale and detached
  case. A detached row whose stop ran out is shown "No answer" with Kill,
  since its agent is alive.

**Backlog's first rule, applied.** Among the open `from-review` tickets in
Backlog, none is about a file this phase changes. #442 touches the plugin
tests and a logging fixture, so it stays where it is.

## Fails if

Andrea did not expect a bad failure, and asked for the causes that would
matter most to be written in. These are agent drafted, from the Phase 21 and
25 loops and the Phase 24 close. It is the end of the phase and it failed
badly. What happened?

1. **A race fix reopened another race.** #427, #431 and #432 each change who
   owns the marker, and each fix was right on its own. Built in parallel, one
   gave back a marker that another had just taken out of the table, and
   #406's double exit came back. So the three are built one after another, by
   one hand, in one batch. Each threaded test is seen failing on the old code
   before its fix lands. Then all of `test_engine_wrap_up.py` runs again after
   the last of the three.
2. **Restart started two agents, or started after a failure.** The sweep saw
   `stopped` on two ticks, or two tabs both pressed Restart, or a timed out
   stop cleared its marker and the restart read that as done. So the pending
   restart is consumed under the same lock that reads `stopped`, and
   "exactly once" is a test that runs two sweep ticks and two Restart presses.
   Every scenario in #472 in which the stop does not end cleanly asserts that
   no start was called at all, and does not settle for no agent being found
   afterwards.
3. **The review loop ran away.** Eleven fixes in one module, each reviewed.
   Then round 3 found a defect in round 2's fix, as it did in Phase 21, and the
   phase stopped closing. So the review runs once per batch, not per ticket.
   The trip wire in the global rules is obeyed, and what it leaves becomes a
   ticket in Backlog, not a fourth round.
4. **A split changed behaviour.** `server.py` and `engine.py` were each moved
   and edited in the same commit. A route lost a refusal, or the sweep lost a
   lock, and the diff was too large to see it. So each split is a pure move in
   its own commit, with the default suite and `-m "live or live_tmux"` green
   before anything lands on top. `docs/api.md`'s two way check must pass with
   the document unchanged.
5. **The watch never happened.** Restart passed every tier, and then the S25
   was unreachable, just as it was at Phase 24's close. So the phone is
   checked to be reachable before batch 4 starts, not at the close. A watch
   done on the Pixel says so, and it leaves the phone criterion open.
6. **The flake was retried into green.** #459's lost status line appeared
   once under load. A green rerun is not a cause, so it is reproduced first,
   or explained from tmux's source.

## Expected work

Tasks continue from Phase 24's 220. Batch 0 lands first and alone, because
every later batch edits the files it moves. Batches 1 and 3 touch different
files and may run concurrently in separate worktrees. Batch 2 waits for
batch 1, whose code its guards read. Batch 4 is last. Each batch is reviewed
once, at its end, under the bounded loop. Its lows go to Backlog.

### Batch 0: room to build, tasks 221 to 223

- [x] **Task 221, #205.** `server.py` split along what its handlers touch, a
      pure move. Every route's refusal ladder stays readable at the route;
      `docs/api.md`'s two way check passes unchanged; the cap goes down.
- [x] **Task 222, #473.** The sweep out of `engine.py`, a pure move, the cap
      lowered. Security auditor review, since `end_anyway` moves with it.
      Built as `sweep.py`. Differs from the text: `end_anyway`'s kill stayed in
      `signals.py` (the one file that signals by pid), and the sweep's call to
      it moved; the review is of that call site.
- [x] **Task 223, #424.** `signals.py` and the new sweep module reach no
      underscore member of `Engine`, through a named interface; one structural
      test covers both, vacuity checked.
      Built as a Protocol in `engine_seam.py` plus a mixin of public members
      on `Engine`, so `engine.py` did not grow; `tests/test_engine_seam.py`.

### Batch 1: one owner for the marker, tasks 224 to 230

Serial, in this order, one implementer.

- [x] **Task 224, #427.** Stop clears only a typing flag it still owns.
- [x] **Task 225, #431.** The refused Exit now during a failing Kill, tested.
- [x] **Task 226, #432.** A Stop during a Kill in flight sees a stop in
      flight; one sequence typed. Differs: a `_kill_held` table beside
      `_stopping`, not a placeholder in it, since a placeholder would list
      the row `stopped` with a marker present and break #387.
- [x] **Task 227, #430.** A per name attention epoch, or one counter kept by a
      tested, written decision beside `_flag_waiting`. Differs: a per name
      epoch (`attention_cleared`) for `_flag_waiting`; `scan_for_stuck` keeps
      its one counter, argued in `_flag_waiting`.
- [x] **Task 228, #426.** A failing pidfd close is logged, and the ticker
      carries on; both callers.
- [x] **Task 229, #425.** "sent SIGHUP to", and a survivor journalled.
      Differs: a survivor also makes `end_anyway` return False, so the `ask`
      report runs.
- [x] **Task 230, #444.** One settle per pass, the second look's wording, the
      pid recheck tested, the persistent ornament written into `docs/api.md`.
      Differs: the shared settle is not built; the cost is written beside the
      loop with the reason. Finding 5 (a non tmux capture error escaping
      `_pane_needs_a_person`) is left for a ticket.

### Batch 2: the guards and the tiers that prove it, tasks 231 to 235

- [x] **Task 231, #423.** The pidfd guard sees `os.kill`, `os.killpg`,
      `pidfd_open`, `pidfd_send_signal` and a dotted `hitchrail.procs`.
- [x] **Task 232, #458.** A kill's journal line read from the real server's
      stderr; removing the log call turns it red.
      Built as `test_a_kill_route_ends_a_real_session_and_writes_one_journal_line`
      in `test_live_tmux.py`. Differs: the server is in process uvicorn read
      through capsys, like #388's test. `end_anyway`'s kill is not reachable
      without faking the screen reader; said in the test and the ticket.
- [ ] **Task 233, #459.** The lost status line: cause named from a
      reproduction or tmux's source, never retried into green.
- [ ] **Task 234, #277.** The `Orphan` docstring names the subreaper; the
      launcher's exec error reaches its caller.
- [ ] **Task 235, #445.** The kill watch catches `visibility`, `opacity` and
      `inert`; one frame loop; an exact phase marker if the page has one.

### Batch 3: the dialog, the exit menu and the wrap up's watch, tasks 236 to 239

- [ ] **Task 236, #433.** A wait re-reads its policy; the plural strings;
      the lost work sentence in Stop all.
- [ ] **Task 237, #463.** The guard kept and named; a detached row offered
      Kill; the stale `log_drawer.js` comment gone.
- [ ] **Task 238, #454.** A `TmuxUnavailable` during the menu wait is a miss;
      two looks or the reason one is enough, written; the menu mutated and its
      survivors read; the two doc lines; `MENU_TRIES` sampled once under load.
- [ ] **Task 239, #475.** Filed after the plan, from a real Stop that waited
      its full 300s with background work running: capture an idle box with a
      background task on a private socket; if `wrap_up_reading` misses it, add
      the shape from the fixture. The ceiling line counts what the watch saw.

### Batch 4: Restart, tasks 240 and 241

- [ ] **Task 240, #472.** The route, the overlay, the sweep's one start, and
      the button beside Stop at 360 px, with every scenario in the ticket at
      its tier. `docs/api.md`, the README's row actions and the spec's stop
      section are updated. Security auditor review, since the route mutates.
- [ ] **Task 241.** Watched on the S25 on a throwaway root: one clean restart
      gets a new session link, and one restart whose stop times out starts
      nothing and says why. A Kill pressed mid restart is watched too.

## Done looks like

- [ ] Every task ticked, or marked MOVED OUT or NOT BUILT with an issue number
- [ ] No open ticket in any milestone describes a defect in stop, kill,
      `end_anyway` or the sweep
- [ ] `server.py` and `engine.py` both under caps that went down this phase
- [ ] Every new test that guards a fix was seen failing with the fix reverted
- [ ] Restart watched on the S25: clean, timed out (nothing started), killed
- [ ] Roadmap says done, milestone closed, `check-phases.sh` passes

## Out of scope

**Resuming the conversation on restart.** #472 decision 2: a fresh
conversation, like Start. A resume flag lives in `claude_ipc` and needs its
own ticket and its own decision.

**Restart for a `stopped`, `stale` or `detached` row.** Start is the button
for those; the route refuses them with `DELETE`'s codes.

**Restart from Stop all.** One row at a time until somebody asks.

**The perimeter and the page's other lows.** Phases 27 and 28.

**`claude_ipc`'s other findings (#456, #460).** Phase 23 re-cuts the package.
#454 is here only because its findings are about the stop's exit.
