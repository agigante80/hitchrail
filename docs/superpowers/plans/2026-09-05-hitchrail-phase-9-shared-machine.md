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

- [ ] **Task 33, #85.** An agent inside another tool's tmux session is reported
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

- [ ] **Task 35, #49.** `_look()` reads the process table before the pane map, so
      the table is always the older of the two, and nothing says why. A session
      killed between the reads leaves its agent in the table with no pane, which
      derives as `detached` for one listing.

      Whichever order survives, the choice gets a comment naming the race it
      prefers. Both orders have one; the bug is that neither is chosen.

## Batch 3: claude_ipc stops being fragile, tasks 36 to 38

- [ ] **Task 36, #95.** `request_stop` defaults `settle` to a real `time.sleep`,
      which the architecture says must be injected. **First in this batch because
      it is what makes the other two testable without wall clocks**, and because
      #70 in Phase 10 is about tests that wait on clocks instead of events.

- [ ] **Task 37, #97.** A charset escape in an empty input box refuses every
      graceful stop on that terminal. The ticket is explicit that widening the
      regex is not the fix: two attempts produced one incomplete pattern and one
      dangerous one, which is evidence about the approach.

      Consider deciding emptiness from the CHARACTERS rather than by subtraction,
      or stripping escapes with a small parser. Whatever is chosen, the captured
      bytes from a real terminal are the test input, not a hand written string.

- [ ] **Task 38, #100.** A modal that is not the trust prompt still reports a
      healthy running row. #88 covers the trust prompt exactly, by reading the
      agent's own config; anything else on screen is invisible. The Remote
      Control modal is the named example and it has actionable entries.

      **`claude_ipc` is quarantine.** Whatever this reads about what is on
      screen stays in that module, and the interface degrades to something honest
      rather than reporting a state it cannot support.

## Batch 4: discovery, task 39

- [ ] **Task 39, #32.** Aliases to an unlistable target can still rename a running
      project. `_dedup_order` prefers a real directory over a symlink so the
      surviving name is durable; when every candidate is a symlink there is no
      durable name to prefer. Standalone, and it can be taken at any point.

## Batch 5: the token an agent inherits, task 40

- [ ] **Task 40, #113.** An agent Hitchrail starts inherits `HITCHRAIL_TOKEN`,
      measured rather than assumed. "Print your environment" is a thing people
      ask agents, and the token is the only thing between a stranger and a shell.

      Independent of the batches above and it could be taken earlier. It is
      placed here because it is the one ticket in this phase that is a security
      control rather than a truthfulness fix, and it should not be rushed
      alongside a refactor.

## Batch 6: ending a detached agent, task 41

- [ ] **Task 41, #107.** A detached agent cannot be ended from a phone, and doing
      so needs the first UNSCOPED destructive path in the project: signalling a
      pid that no tmux session of ours owns.

      **Last, and the ticket says why in its own words.** It depends on #96,
      because the argv match that identifies a detached agent has been wrong
      twice this month, and on #85, because some rows currently marked detached
      may not be. Building a kill on top of an identification that is still
      wrong is the worst possible ordering.

## Phase 9 exit criteria

Ticked only with evidence.

- [ ] An agent inside another tool's tmux session produces an honest answer
      rather than a confident wrong one.
- [ ] A tmux binary under another name does not invent a detached agent.
- [ ] A terminal emitting an unusual escape does not refuse every graceful stop.
- [ ] The two derivation directions follow one stated rule, or their asymmetry is
      documented with its reason and tested.
- [ ] The read order in `_look()` names the race it prefers.
- [ ] A spawned agent does not inherit the token.
- [ ] `tmux.py` no longer holds the name vocabulary, and the dependency direction
      is asserted.

## What would make this phase a failure

**Fixing these against the existing fixtures.** The fixtures describe an empty
machine, which is why none of these was reachable from the suite. A fix that
passes only there has not been verified, and this phase would then close having
changed the code and not the answer.

Phase 10 is where the fixtures learn about shared machines (#94 is explicit about
the live tmux tier reading the real process table with no namespacing). Some
tickets here will want that first; when one does, say so on the ticket rather
than writing a test that agrees with the bug.
