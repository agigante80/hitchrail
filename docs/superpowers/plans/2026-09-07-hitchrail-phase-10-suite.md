# Phase 10: A suite that would notice

**Objective: the tests fail when the code is wrong, and only then.**

Twelve tickets, tasks 42 to 53, in five batches. Work the batches in order and
the tickets within a batch in the order given; the ordering is dependency, not
taste.

## What this phase is actually about

**A fixture written to agree with the code.** It happened three times in one
session, and each time the test passed while the thing it named was broken.
Phase 9 is the evidence: every defect it fixed was found by running against a
real machine, because the suite's fixtures describe a machine where Hitchrail is
the only thing that has ever run.

Read that as a constraint on the work rather than as history. **A fix verified
only against the existing fixtures has not been verified.** Several tickets here
are about the fixture being wrong, and a test written inside the same assumption
will agree with the bug.

## What this phase is NOT about, since it used to be

This phase was narrowed on 2026-09-07 because it had become where everything
went: 16 tickets to 39 while six were being closed. A phase whose objective is
"quality" absorbs every finding and therefore never ends. Prose contradicted by
code went to **Phase 17**; files doing more than one thing went to **Phase 18**.

What stays is the machinery that decides whether a test can fail: tiers,
fixtures, mutation, and the guards that check the guards. **A finding that is
not about that goes to its phase, not into this plan.** That rule is the phase's
own exit condition as much as the four below.

## The exit criteria, and which task answers each

The roadmap states four. This plan exists to make each one reachable rather than
felt, so every task below names the criterion it serves and no criterion is left
without a task.

| Criterion | Tasks |
|---|---|
| 1. A fixture cannot agree with the bug | 45, 46, 47, 48, 49 |
| 2. No tier's result depends on what the machine has | 44, 45, 46 |
| 3. The mutation sweep's survivors have been read | 42, 51, 52 |
| 4. No tier can be selected by accident | 53 |

Task 50 serves none of them directly and is here because the phase cannot close
honestly without it; it is argued in place.

## Batch 1: the sweep can start, task 42

**First, because criterion 3 is currently unmeasurable and two tasks below are
blocked on it.**

- [ ] **Task 42, #221.** `uv run mutmut run` dies in stats collection with
      `BadTestExecutionCommandsException`, pytest exit code 4, which is a usage
      error rather than a test failure. Pre-existing: reproduced against
      `origin/develop` with `tests/test_config.py` and `pyproject.toml` reverted.

      The selected tests are fine. Run directly from a generated `mutants/` tree
      with mutmut's own selection they give `692 passed, 1 skipped, 4
      deselected`. So the fault is in how the command is assembled, and
      `pytest_add_cli_args` and `pytest_add_cli_args_test_selection` are the two
      inputs to that assembly.

      **Do not stop at making it run.** The ticket asks for a cheap check that
      the sweep can START, in the shape of
      `test_every_mutated_module_can_be_imported_from_the_mutants_tree`, which
      exists because the same class of breakage happened twice and which
      verifies the tree imports rather than that the command runs. Without it
      this recurs the next time either list changes, and it recurs silently,
      because nobody runs a twenty minute sweep to find out.

## Batch 2: no tier depends on the machine, tasks 43 to 45

Criterion 2. These are ordered by how much of the machine they touch.

- [ ] **Task 43, #216.** The CLI tier runs against the operator's own tmux
      server. `TMUX_TMPDIR` fixes it.

      This is the same hazard class as testing against the real projects root,
      and it is worse than a flaky test: a tier that can see the operator's live
      sessions is a tier that can act on them. Do this before task 44, because
      the process table work needs a tier that is already isolated at the tmux
      level to have anything to stand on.

- [ ] **Task 44, #94.** `tests/test_live_tmux.py` isolates tmux carefully: a
      private socket, `env -u TMUX`, only prefixed sessions, teardown that asks
      the server what it holds. **None of that isolates the process table.** Any
      test in the tier that derives rather than only driving tmux calls
      `procs.snapshot()`, which reads every process on the machine running the
      suite.

      The fixtures memory names this directly: every tier starts from a private
      tmux server and a fresh temp dir, so shared machine defects are
      unreachable. This ticket is the other half of that, and the namespace on
      project names is what makes a derived answer attributable to the test that
      caused it.

- [ ] **Task 45, #67.** `test_a_start_that_dies_says_so_and_offers_the_output`
      passes locally in about nine seconds and fails on CI after forty five.
      **The reason is not known**, and that is the ticket rather than an aside.

      Serves criteria 1 and 2 at once, and it is the one task here that may end
      in a decision rather than a fix: a test that fails only where nobody can
      watch it is either finding something real about the CI machine or is
      itself the defect. Budget an investigation, and if the answer is "the test
      is wrong", say so and delete it rather than adding a retry.

## Batch 3: fixtures that cannot agree with the bug, tasks 46 to 49

Criterion 1. These are the tests that pass while what they name is broken.

- [ ] **Task 46, #73.** The fatal stream error's refresh has no test of its own.
      A screen state with no test is a screen state nobody has read since it was
      written.

- [ ] **Task 47, #70.** The e2e negatives wait on wall clocks instead of on
      events. A negative that waits two seconds and asserts nothing happened
      proves the machine was slow, not that the thing is refused. This is the
      shape that makes a whole tier untrustworthy while it is green.

- [ ] **Task 48, #215.** Two published screenshots are wrong, and every capture
      ships a pid. The pid is a privacy leak into a tracked artefact; the wrong
      screenshots are a document contradicted by the thing it shows.

      **Check the boundary before working it:** the wrong-screenshot half is
      arguably Phase 17. It stays here because the capture path is a fixture
      that produces an artefact, and the fix is to the capture, not to the
      prose.

- [ ] **Task 49, #206.** The unit flag check crashes instead of failing when
      `ExecStart` is continued across lines. A guard that raises where it should
      refuse reports a broken check as a broken build, and the two need
      different responses.

## Batch 4: the survivors are read, tasks 50 to 52

Criterion 3. **Blocked on task 42.** Do not start these before the sweep runs.

- [ ] **Task 50, #209.** What the #201 review loop left open when it hit its
      trip wire. Round 2 found three defects in round 1's fix and round 3 found
      three in round 2's: 75% then 100% fix-induced against a 7-29% base rate,
      so the loop was re-deriving the same three mistakes in new wording rather
      than converging.

      **This serves no exit criterion and is here deliberately.** It is the
      residue of a stopped loop, and a stopped loop's residue is the one thing
      that never gets picked up unless it is scheduled. Reading it first is also
      the cheapest way into batch 4: it is a written record of assertions that
      did not hold, which is what a survivor is.

- [ ] **Task 51, #135.** 48 mutants in `tmux.py` have no covering test, and 74
      survivors have never been read. The 48 are a coverage gap the module was
      hiding by not being in `source_paths` until #130 put it there.

      **Read them, do not count them.** The exit criterion is that each survivor
      is either killed or recorded with the reason it is not worth killing, and
      a score is satisfiable without improving anything.

- [ ] **Task 52, #217.** Two attention-sweep mutations survive the whole suite.
      Small, specific, and the right last task in this batch: two named
      survivors with a known module are the proof that the criterion 3 loop
      closes.

## Batch 5: no tier runs unasked, task 53

- [ ] **Task 53, #214.** Two known limits in the e2e prefix guard and the
      screenshot tier. Criterion 4 is the `addopts` deselection being replaced
      by any `-m`, so a tier that must not run unasked has to enforce it in
      collection rather than in configuration a flag can drop.

## Done when

The four criteria in `docs/roadmap.md`, and nothing beyond them. Specifically:

- [ ] Every task above is ticked, or is marked MOVED OUT with the issue that
      carries it, per the convention in `AGENTS.md`.
- [ ] `uv run mutmut run` completes, and every survivor in the modules it covers
      has been read and either killed or recorded.
- [ ] No tier's result depends on what the machine running it happens to have,
      with `device` as the one stated exception: it is opt in and FAILS rather
      than skips when the hardware is absent.
- [ ] The roadmap's Phase 10 section carries `**Status: done**` with the closing
      date and the issues, and this plan has no unticked box without a marker.

## What would make this phase fail rather than finish

Written down because this phase has already failed once, by growing:

1. **A finding that is not about whether a test can fail.** It goes to its
   phase. The three that already left, #10, #5 and #198, are the precedent.
2. **A mutation score quoted as progress.** The criterion is survivors READ. A
   score improves by deleting a weak test, which is the opposite of the point.
3. **A tier made green by making it skip.** Criterion 2's exception is opt in
   and failing, never silently absent. `device` is the only one.
