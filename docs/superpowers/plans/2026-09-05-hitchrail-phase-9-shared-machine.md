# Phase 9: The truth on a shared machine

**Objective: derivation is right on a machine Hitchrail does not own.**

Twelve tickets, tasks 30 to 41, in six batches. Work the batches in order and the
tickets within a batch in the order given; the ordering is dependency, not taste.

## What this phase is actually about

Every defect here was found the same way: by running against a real root with
another tool's sessions on it. **The suite's fixtures describe a machine where
Hitchrail is the only thing that has ever run**, so none of these was reachable
from it. That is the phase's real subject, and it is why Phase 10 exists next.

Read that as a constraint on the work rather than as history. A fix verified only
against the existing fixtures has not been verified: several of these tickets are
about the fixture being wrong, and a test written inside the same assumption will
agree with the bug.

## The ticket list, corrected

`docs/roadmap.md` named ten. The milestone holds twelve: **#113 and #107 moved in
after that line was written**, from Phase 7's retrospective and from #83
respectively. The roadmap is corrected in the same change as this plan.

## Batch 1: the tmux adapter, tasks 30 to 32

The mechanical batch, and first because it clears the ground for the rest.

- [x] **Task 30, #93.** Split the name vocabulary out of `tmux.py`. `sanitize`,
      `_needs_encoding`, `_SEPARATORS`, `_ENCODED_PREFIX`, `BINARY` and
      `is_tmux_argv` are pure functions over strings living inside the module
      that spawns processes. The seam is the same one `hostnames.py` took beside
      `config.py` and `projectnames.py` beside `discovery.py`.

      **Do this first because #96 edits code this moves.** Doing it second means
      writing the fix twice. It also takes `tmux.py` off its recorded size cap of
      522, and it moves the vocabulary into a module that can be mutation tested
      without dragging the spawner along (#135 reports 48 mutants there with no
      covering test).

      No behaviour change. A pure move with a test asserting the dependency runs
      one way, as `test_projectnames_does_not_import_config` already does.

      **Done 2026-09-05.** `tmuxnames.py`, matching `hostnames` and
      `projectnames` rather than the ticket's `tmux_names`: a third spelling of
      the same idea is a tax on everyone who later has to remember which one
      this was. `tmux.py` 522 to 439, and its four cap notes are replaced by one
      recording that they argued in good faith from a premise the split removed.
      `is_tmux_argv` had NO test at all and now has five, one of which asserts
      #96's defect so it fails the day #96 is fixed. Sweep: 852 killed to 856,
      survivors 233 to 229.

- [x] **Task 31, #96.** `is_tmux_argv` compares `argv[0]`'s basename to the
      literal `"tmux"`, so a tmux installed as `tmux3`, or invoked through a
      wrapper, reopens #84: a tmux server's own argv satisfies the agent match
      and a detached agent is invented.

      Write it in the module task 30 created.

      **Done 2026-09-05.** A version or build suffix never begins with a letter
      and another program's name always does, so `tmux-3.4`, `tmux3` and
      `tmux_next` match while `tmuxinator`, `tmuxp` and `tmuxifier` do not.
      `startswith` alone would have claimed all three of those, and claiming one
      HIDES a genuine agent, which is worse than the false negative it fixes.
      The ticket's `display-message -p '#{pid}'` was not taken: it asks the
      server we are talking to, so it cannot see the foreign server that is the
      whole case, and it costs a tmux call per listing that
      `test_list_issues_one_tmux_call_and_one_ps_call` forbids.

- [x] **Task 32, #102.** A timed out `new_session` can leave a session with
      `remain-on-exit` still on, which presents as a `stale` row that never
      clears. #67 gave every tmux call a ten second bound and that bound is what
      makes this reachable.

      **Done 2026-09-05.** `_abandon_partial_session` on the `TmuxUnavailable`
      path, which ASKS `has-session` and acts on the answer rather than assuming
      either way: assuming it exists kills something that may not, assuming it
      does not leaves the defect. A failure in the cleanup never replaces the
      original error, because the machine being unreadable is what the caller
      must be told and the cleanup failing is the same cause showing twice. The
      fake now models both outcomes of a timed out create, since a fake that
      raised before creating could not express the defect at all.

## Batch 2: derivation agrees with itself, tasks 33 to 35

The phase's headline, and the hardest. All three are about what counts as a
match and when.

- [x] **Task 33, #85.** An agent inside another tool's tmux session is reported
      `detached`. `pane_pids` filters to sessions carrying our prefix, which is
      correct, and the second direction then calls any agent no PREFIXED pane
      owns detached. An agent owned by somebody else's pane is owned; it is just
      not ours.

      **The honest answer is a fourth possibility, not a reclassification.**
      Decide whether such an agent is invisible to Hitchrail or reported as
      something new, and write the decision down: `detached` currently means "no
      pane owns it", and it must not quietly come to mean "no pane we can see".

      **SKIPPED 2026-09-05, attempted and reverted, and the plan understated
      it.** The narrow fix works and costs no extra call, and then the row says
      `stopped`, which offers Start. Starting gives a second agent in the same
      folder, which is the outcome the design names as the reason derivation
      exists at all. So it trades a label that invites a wrong DESTRUCTIVE
      action for one that invites a wrong CREATIVE one, and the second is what
      the whole mechanism was built to prevent.

      It needs a decision about the state model, which is design section 4.1.
      Four options are written on the ticket, which now carries `needs-human`.
      Tasks 34 and 35 do not depend on it; task 41 does, by its own body.

      **Decided and done 2026-09-05.** Option 3 plus an overlay: four states
      kept, `detached` redefined to what the code already derived, and the
      missing fact carried in `Session.foreign_session`, the name of the tmux
      session that owns the agent.

      What settled it was not on the option list. A foreign owned agent and a
      true orphan are operationally IDENTICAL: start refuses for both, a
      graceful stop has no pane of ours to type into for both, a kill has no
      session of ours to kill for both. Only the sentence on the row differs,
      and this project already has three overlays for exactly that. A fifth
      state would have cost `api.md`, the design, `app.js`, `app.css`,
      `TALL_STATES` and every state test to change no action.

      A NAME rather than a flag, because its absence has to mean "no owner was
      SEEN". `list-panes -a` covers one server on one socket, so an agent under
      another socket, under screen or under a plain terminal lands there too.
      The row says "no session Hitchrail can address"; the old copy said "no
      tmux session" and could not know it.

      Two things the implementation found that the ticket had not. The parser
      split on the first space, so a foreign name containing one was dropped
      and its agent looked unowned: this defect, reached through the parser.
      And the two API refusals still opened "has no tmux session", so the claim
      deleted from the interface was still being made to the person who read
      the row and then tapped Stop.

      Review then found that `rpartition` made one input WORSE: a foreign
      session called `hr-my project` classified as ours, hid the agent under
      its pane and derived `stopped`, which offers Start. Fixed by refusing a
      space on the `ours` side, which is safe because `session_name` cannot
      produce one.

- [x] **Task 34, #46.** The two directions match with different strictness and
      neither behaviour is written down or tested. The pane direction accepts any
      marked process anywhere in the pane's tree regardless of which project its
      command line names; the orphan direction matches on the project name.

      Task 33 changes what the second direction sees, so do it after. The
      deliverable is one stated rule both directions follow, with the asymmetry
      either removed or documented as deliberate with its reason.

      **Done 2026-09-05, documented rather than removed**, which is what the
      ticket argues for: ownership beats argv, and tightening the pane direction
      would turn every running session `stale` the day `launch_argv` changes,
      far worse than the mislabelled pid it would fix. Both behaviours now have
      a test asserting them explicitly, and a third fails if the reasoning is
      deleted from `derive.py`, because the risk the ticket names is a later
      consistency tidy up rather than the asymmetry itself. Task 33 being
      skipped did not block it: the two directions' strictness is independent of
      what the second one sees.

- [x] **Task 35, #49.** `_look()` reads the process table before the pane map, so
      the table is always the older of the two, and nothing says why. A session
      killed between the reads leaves its agent in the table with no pane, which
      derives as `detached` for one listing.

      Whichever order survives, the choice gets a comment naming the race it
      prefers. Both orders have one; the bug is that neither is chosen.

      **Done 2026-09-05.** `ps` first is kept, on the reasoning the ticket
      proposed and `derive.look` now states: a false `detached` is loud and
      recoverable because the row offers a kill, while a false `stale` offers
      Start and a start gives a second agent in the same folder. That is the
      same argument that rejected task 33's narrow fix on the same day, which
      is worth noticing: the design has one consistent preference about which
      lie is safe, and it is the oldest thing in it. Mutation verified by
      swapping the two reads.

## Batch 3: claude_ipc stops being fragile, tasks 36 to 38

- [x] **Task 36, #95.** `request_stop` defaults `settle` to a real `time.sleep`,
      which the architecture says must be injected. **First in this batch because
      it is what makes the other two testable without wall clocks**, and because
      #70 in Phase 10 is about tests that wait on clocks instead of events.

      **Done 2026-09-05, and smaller than the ticket assumed.** It said the
      engine "acquires a SLEEP seam, which it does not have", and estimated a
      change to the constructor and to every test that builds an engine. The
      engine already has `_sleep`, added later for `_await_running`, so the work
      was passing it through and deleting the default. The DURATION stays in
      `claude_ipc` because how a Claude Code pane settles is quarantine
      knowledge; the WAITING is the injected seam. Removing the default is what
      keeps it wired: a default is exactly what let the seam be bypassed while
      the parameter existed and the unit tests passed a fake.

- [x] **Task 37, #97.** A charset escape in an empty input box refuses every
      graceful stop on that terminal. The ticket is explicit that widening the
      regex is not the fix: two attempts produced one incomplete pattern and one
      dangerous one, which is evidence about the approach.

      Consider deciding emptiness from the CHARACTERS rather than by subtraction,
      or stripping escapes with a small parser. Whatever is chosen, the captured
      bytes from a real terminal are the test input, not a hand written string.

      **Done 2026-09-05, a parser.** A regex cannot express "consume exactly
      this sequence and not the character after it" for every form at once
      without becoming unreadable, which is what both previous attempts
      demonstrated by failing in OPPOSITE directions: one refused every stop
      forever, the other ate a draft character and would have typed into a half
      written sentence. Four branches, each consuming precisely its own
      sequence: CSI, OSC, a charset designator with its one character argument,
      and every other two character escape. Tested in both directions across the
      whole set rather than only the one the ticket names, because a fix that
      special cases `ESC ( B` leaves the next terminal to file the next ticket.

- [x] **Task 38, #100.** A modal that is not the trust prompt still reports a
      healthy running row. #88 covers the trust prompt exactly, by reading the
      agent's own config; anything else on screen is invisible. The Remote
      Control modal is the named example and it has actionable entries.

      **`claude_ipc` is quarantine.** Whatever this reads about what is on
      screen stays in that module, and the interface degrades to something honest
      rather than reporting a state it cannot support.

      **Done 2026-09-05, and the ticket's own proposal was wrong twice.**

      It proposed reusing `claude_ipc.input_is_clear`. That predicate cannot do
      this: #89 shortened its anchor to the prompt ornament ALONE so a modal and
      an input box would both match, which is right for deciding whether to type
      and useless for deciding whether a person is needed. It returns False for
      a person's half typed draft exactly as it does for a modal. The
      distinguishing byte is the one the anchor gave up: an input box renders a
      non breaking space after the ornament and a modal does not. So
      `shows_input_box` sits beside it rather than replacing it, and the two
      differ on exactly one case.

      `engine._pane_needs_a_person` switched to it as well, which is a defect
      fix in shipping code: the design's own words for that overlay are
      "showing something that had to be answered, not an ordinary input box",
      and the old predicate also fired on the draft.

      **The capture runs on the SWEEP, not on the listing**, and that is the
      cost decision the ticket asked for. Measured: `capture-pane` is 3.0 ms
      against a warm server, which is not what decides it. The interface polls
      the listing every 700 ms for a whole stop wait, and the adapter's call
      timeout is ten seconds, so a cap of ten captures on that route would be a
      hundred seconds of worst case latency on the executor that also serves
      the operator's stop. On the sweep the ceiling is ten captures per second
      machine wide, whatever any client is doing, and
      `test_list_captures_no_pane` keeps its assertion unchanged.

      Three bounds, each for a different failure: a cap on count, a wall clock
      budget because the cap alone does not bound time, and a TTL because a
      remembered claim about a screen has to expire on its own. The deciding
      moved to a new module, `attention.py`, along the seam `derive.py` already
      established.

## Batch 4: discovery, task 39

- [x] **Task 39, #32.** Aliases to an unlistable target can still rename a running
      project. `_dedup_order` prefers a real directory over a symlink so the
      surviving name is durable; when every candidate is a symlink there is no
      durable name to prefer. Standalone, and it can be taken at any point.

      **Closed 2026-09-05 as a decision rather than a fix**, and the behaviour,
      its docstring and the test that pins it are all unchanged. The complete
      fix is option B from #11, keying sessions off the resolved path, and it
      now contradicts two settled arguments rather than one open question:
      #119's `<root-label>~<folder>` identity, shipped in 0.2.0 the day before,
      and `sanitize`'s own "injective by construction beats injective by hash",
      which is exactly what a resolved path with separators and no length bound
      would force.

      One option nobody had listed was considered and rejected: prefer the alias
      that currently owns a live tmux session. It fixes the real harm and
      requires `discovery` to know about tmux, inverting a dependency the module
      split exists to keep one way, and it would make the names in a listing
      depend on what is running.

      The work went to the CAUSE instead, as #173: the trigger is our own error
      message refusing a folder for a space, which makes a symlink the obvious
      response.

## Batch 5: the token an agent inherits, task 40

- [x] **Task 40, #113.** An agent Hitchrail starts inherits `HITCHRAIL_TOKEN`,
      measured rather than assumed. "Print your environment" is a thing people
      ask agents, and the token is the only thing between a stranger and a shell.

      Independent of the batches above and it could be taken earlier. It is
      placed here because it is the one ticket in this phase that is a security
      control rather than a truthfulness fix, and it should not be rushed
      alongside a refactor.

      **Done with `env -u`, which is none of the three options the ticket
      listed.** Measured on tmux 3.4 against a pre existing server, because the
      ticket's own warning is that each candidate silently does nothing in the
      wrong case: a pane inherits from the SERVER, so filtering the client call
      changes nothing; `new-session -e VAR=` leaves the variable set and empty
      rather than absent; `env -u VAR` in the argv we already build leaves it
      genuinely unset, mutates nothing belonging to tmux or to anyone else's
      sessions, and `execs` away before `ps` sees it, so the argv tail
      `find_detached` matches is untouched. `TOKEN_ENV` moved to `config` so the
      engine can name it without importing `cli`, which the import contract
      forbids.

## Batch 6: ending a detached agent, task 41

- [ ] **Task 41, #107. NOT BUILT, and MOVED OUT of this phase.** It was skipped
      first because #85 was undecided, and after #85 landed the gate found that
      its scoping premise does not hold at all.

      **`foreign_session is None` does not mean orphaned.** It means no owner
      was SEEN, which is the distinction #85 spent a commit teaching the
      interface to make: ownership is read from one server on one socket, while
      `ps -eww` sees every process on the machine. That bucket also holds an
      agent under a different socket, under screen, under a plain terminal, and
      another user's agent, since tmux sockets are per uid and the process table
      is not. Signalling on that basis is the interface's own new warning
      inverted, and the wrong action here is the destructive one.

      What it actually needs is a POSITIVE establishment that nothing owns the
      process, which is #172's cgroup test. So the chain is #172 then #107, and
      #85 was necessary and not sufficient. Both moved to Phase 14, where every
      ticket touches a security control and each is a decision before it is
      work. This phase's objective is that derivation is right on a machine
      Hitchrail does not own; adding the most destructive capability in the
      project is the opposite direction, and it sat here only because its
      blockers did.

      A detached agent cannot be ended from a phone, and doing
      so needs the first UNSCOPED destructive path in the project: signalling a
      pid that no tmux session of ours owns.

      **Last, and the ticket says why in its own words.** It depends on #96,
      because the argv match that identifies a detached agent has been wrong
      twice this month, and on #85, because some rows currently marked detached
      may not be. Building a kill on top of an identification that is still
      wrong is the worst possible ordering.

## Phase 9 exit criteria

Ticked only with evidence.

- [x] An agent inside another tool's tmux session produces an honest answer
      rather than a confident wrong one. #85: the row names the session that
      owns it, and where no owner can be seen it says that rather than claiming
      there is none. Proven against a real tmux on a private socket and through
      a browser against a real foreign session, not only against a fake.
- [x] A tmux binary under another name does not invent a detached agent. #96:
      `tmux3.4` and `tmux-next` are tmux, `tmuxinator` is not.
- [x] A terminal emitting an unusual escape does not refuse every graceful stop.
      #97 replaced the regex with a parser, after two regexes failed in
      opposite directions.
- [x] The two derivation directions follow one stated rule, or their asymmetry is
      documented with its reason and tested. #46 took the second branch, because
      the asymmetry is correct: ownership beats argv.
- [x] The read order in `_look()` names the race it prefers. #49.
- [x] A spawned agent does not inherit the token. `env -u HITCHRAIL_TOKEN`
      prefixes the spawn; `tests/test_tmux.py` pins the argv and that the tail
      is unchanged, and `tests/test_engine.py` pins the wiring, which the tmux
      tests structurally cannot see.
- [x] `tmux.py` no longer holds the name vocabulary, and the dependency direction
      is asserted. #93, and 522 lines became 439 with nothing explanatory cut.

## What would make this phase a failure

**Fixing these against the existing fixtures.** The fixtures describe an empty
machine, which is why none of these was reachable from the suite. A fix that
passes only there has not been verified, and this phase would then close having
changed the code and not the answer.

Phase 10 is where the fixtures learn about shared machines (#94 is explicit about
the live tmux tier reading the real process table with no namespacing). Some
tickets here will want that first; when one does, say so on the ticket rather
than writing a test that agrees with the bug.

## How this phase actually ended

**In two passes, and the second one is the interesting half.**

The first pass shipped eight tickets and escalated four: #85, #100 and #32 for
decisions, and #107 behind #85. That is recorded above at each task, including
the attempt at #85 that was made and reverted.

The second pass, later the same day, took all four decisions. Two became code,
one became a closed decision, and one left the phase:

- **#85 decided and built.** Four states kept, `detached` redefined to what the
  code already derived, the missing fact carried as an overlay. The argument
  that settled it was not among the four options on the ticket: a foreign owned
  agent and an orphan are operationally identical, so a fifth state would have
  changed no action.
- **#100 decided and built.** The capture is paid for, and paid for on the sweep
  rather than the listing, because the cost has to scale with the state of the
  machine rather than with how often a browser polls. Two of the ticket's own
  proposals were wrong and are corrected at the task above.
- **#32 closed as a decision.** The complete fix now contradicts two settled
  arguments, and the work went to the cause instead, as #173.
- **#107 moved to Phase 14**, because the gate found its scoping premise false:
  the field it wanted to scope on means "no owner seen", not "no owner". It
  needs #172 first.

**Every exit criterion is ticked with evidence.** The phase closes.

Six tickets were filed from this work rather than fixed inside it: #172 and
#173 from the decisions, #174 from a count that had drifted, and #175, #176 and
#177 from the review of #85. Filing them is the finished outcome; three of them
name defects in code this phase touched, and two name tests this phase added
that could not fail on what they claimed.
