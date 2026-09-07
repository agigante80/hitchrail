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

- [x] **Task 42, #221.** `uv run mutmut run` dies in stats collection with
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

      **Done 2026-09-07. Two causes, both invisible to the guard that existed.**
      `engine.py` imports `attention`, `attention.py` was in neither list, so
      the tree held the importer and not the module and `conftest.py` could not
      import: pytest exits 4, a USAGE error, which mutmut renders as "Failed to
      run pytest with args" with every argument in it valid. The guard walked
      `source_paths` only, and `engine.py` is copied rather than mutated, so the
      module that could not import was one it never looked at. Second cause,
      same family from the other end:
      `test_the_sweep_drives_every_public_method` reads `vars(Tmux)`, and under
      a run those are `xǁTmuxǁ…__mutmut_N` variants whose names do not start
      with an underscore, so it joined the four deselected repo shape guards.

      The guard now walks every COPIED file with `also_copy` directories
      expanded, and a second one asserts every deselected node id still exists,
      because a stale node id produces the identical opaque message. Both were
      falsified before landing.

      **The sweep runs: 1188 mutants, 911 killed, 264 survived, 13 with no
      covering test, 0 timeouts, at 14 mutations a second.** Criterion 3 is
      measurable, and those 264 are the input to tasks 51 and 52.

## Batch 2: no tier depends on the machine, tasks 43 to 45

Criterion 2. These are ordered by how much of the machine they touch.

- [x] **Task 43, #216.** The CLI tier runs against the operator's own tmux
      server. `TMUX_TMPDIR` fixes it.

      This is the same hazard class as testing against the real projects root,
      and it is worse than a flaky test: a tier that can see the operator's live
      sessions is a tier that can act on them. Do this before task 44, because
      the process table work needs a tier that is already isolated at the tmux
      level to have anything to stand on.

      **Done 2026-09-07.** Every console script spawn now carries a private
      `TMUX_TMPDIR`, killed with `-S` and removed at teardown, and
      `test_the_cli_tier_never_spawns_without_an_isolated_tmux` reads the AST
      rather than asking the next author nicely. The conftest's "do not add a
      start case" warning is gone and the start case is written: it starts a
      real session, asserts the private server holds it, and asserts the
      operator's own does not.

      **The hazard is not theoretical, and I proved it the expensive way.**
      Falsifying the isolation by REMOVING `TMUX_TMPDIR` put `hr-cli~probe-<hex>`
      on the real server with a fake agent sleeping in it, which had to be found
      and killed by hand. The test now says to falsify it by pointing at a second
      private directory instead. That is the whole ticket in one line: a tier
      that looks isolated and is not.

      Also landed, all from the same file: `serving` drains the child's pipe in
      a thread and yields a `Program` carrying its output, which made #128's two
      banner cases assertable and they are now covered (the token printed, and
      withheld under `JOURNAL_STREAM`, which is #110's decision). `test_tiers.py`
      globs recursively, so `e2e/`, `cli_tier/` and `device/` are scanned at all
      for the first time. `free_port`'s TOCTOU is knowingly left: the poll checks
      `process.poll()` first, so a lost race surfaces as "the program exited
      before serving" with uvicorn's reason attached.

- [x] **Task 44, #94.** `tests/test_live_tmux.py` isolates tmux carefully: a
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

      **Done 2026-09-07.** `PROJECT_NAMESPACE = f"hrlt{os.getpid()}-"` and
      `live_project()`, with the `machine` fixture minting the name and creating
      the folder in one statement and handing it back as `Machine.project`. So a
      test asks the fixture what it made rather than naming a project, which is
      the browser tier's `Harness.project()` answer in this tier's shape. The
      hand written `LIVE_PROJECT` is gone.

      The pid is #177's decision reused rather than re-argued: two concurrent
      runs get separate tmux servers and separate roots, and share exactly one
      process table.

      **Two guards, because one of them names a single file.**
      `test_the_live_tier_never_derives_a_project_it_did_not_namespace` reads the
      AST of every `derive.derive` call and requires `machine.project` or
      `live_project(...)`. `test_no_other_test_reads_the_real_process_table` is
      what makes that scope honest: every other `snapshot()` caller in the suite
      passes a fake runner, nothing said so, and a guard scoped to one file on an
      unstated assumption is the shrinking-subset failure this module already had
      when its glob was non-recursive.

      Six falsifications, all caught: a bare literal, a module constant in the
      exact #94 shape, an f-string that looks namespaced but was not minted, a
      namespace with no run identity, the namespace folded into `PREFIX`, and a
      real `snapshot()` in `test_procs.py`.

      `FOREIGN_PREFIX` is a plain `"hrother-"` rather than derived from either
      constant: it names sessions on a server that is already private per run, it
      must not start with `PREFIX` or `panes().ours` claims them and they stop
      being foreign, and building it from the namespace produced
      `hrlt<pid>-other-hrlt<pid>-vessel`.

- [x] **Task 45, #67.** `test_a_start_that_dies_says_so_and_offers_the_output`
      passes locally in about nine seconds and fails on CI after forty five.
      **The reason is not known**, and that is the ticket rather than an aside.

      Serves criteria 1 and 2 at once, and it is the one task here that may end
      in a decision rather than a fix: a test that fails only where nobody can
      watch it is either finding something real about the CI machine or is
      itself the defect. Budget an investigation, and if the answer is "the test
      is wrong", say so and delete it rather than adding a retry.

      **Investigated 2026-09-07. It was the third answer: the test as weakened
      was the defect, and not in the direction the ticket expected.** The
      weakened assertion asserts nothing. The row is already `stopped` when the
      button is clicked, so `not_to_have_attribute("data-state", "running")` is
      satisfied before the start has done anything: 0.26s against the restored
      form's 8.65s. It passed with `_dead_start_output` returning `""`, which is
      exactly the #56 case its own comment claimed it caught, and it passed with
      `Engine.start` replaced by `return self.get(name)` so that nothing was
      started at all. **Thirteen commits of apparent coverage over an assertion
      that could not fail.**

      Both of the ticket's candidates are closed without a CI round trip.
      Candidate 1 is answered by a measurement CI already takes:
      `test_a_dead_pane_and_a_live_one_are_told_apart` asserts `pane_is_dead` is
      True against a real dead pane, and `ci.yml` refuses a `live_tmux` skip, so
      green CI is the runner's answer to `#{pane_dead}`. Candidate 2 was fixed in
      `5a50a87`. Scoped rather than generalised: this rules out "`#{pane_dead}`
      differs on the runner", not "`pane_is_dead` returned True in that run".

      The likely cause of the original failure is `E2E_PREFIX` contamination,
      fixed since by `a1c0acb`: the ticket's failure snapshot reads
      `hrx-vessel stale` while the test seeds `koala`, and under the constant
      prefix then in force that row is not this test's project.

      The assertion is restored with the measurement and both falsifications in
      the docstring. **Left open: one CI round trip.** `ci.yml` runs on push to
      `main` and on `pull_request`, so a `develop` push does not exercise it, and
      that is the risk `39bdded` weakened the assertion to avoid. Step 1 of the
      ticket's plan, capturing the uvicorn log and browser console, was
      deliberately not built: needed only if that round trip is red.

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
