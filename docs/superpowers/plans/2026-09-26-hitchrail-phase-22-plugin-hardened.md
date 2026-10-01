# Phase 22: The plugin update, hardened

**Objective: the plugin update and the agent binary it runs are as careful as
the rest of the path between a web page and a shell.**

## Goal

The agent binary is resolved once, checked where it runs, and spawned exactly
as checked. Every finding Phase 21's review filed is fixed or closed with its
reason.

## What this phase is actually about

Phase 21 shipped the plugin update, from the command line and from the
settings page, and its review loop stopped on the trip wire: round 3 found
defects in round 2's fix, so the last round's findings were filed rather than
fixed. They sat in Backlog, which is where the roadmap's second Backlog rule
now says they must not stay. A phase that ships new surface is followed by one
that hardens it, as Phase 20 followed 14.

**Written on 2026-09-26, before the phase opened; opened 2026-09-27**, while Phase 15 was still
open, so the phase can open the moment 15 closes. Every ticket was checked
against the tree that day, reading the body, the comments and the named lines.
All eighteen still describe the code. One was half wrong: #304 claimed
`claude_ipc.py` was missing from `.claude/rules/security.md`, and it has been
listed there since before Phase 21. The body was rewritten with the old one
preserved as a comment, and only the mutation half stands.

**The seventeen review findings are terse**: Summary, Priority, Proposed fix,
Test. They do not carry the full shape `docs/guides/ticket-standards.md` asks
of a ticket. They are accepted as they are, because each is a single file
change with a concrete input already in the body. That is a standing
exception for `from-review` tickets and is written here so it is not mistaken
for a silent waiver.

**Three tickets are one defect.** #302 says the binary check exists twice and
the server spawns the unstripped value; #196 says preflight resolves the binary
and throws the answer away; #298 says a relative binary is checked from one
directory and run from another. They are built as one change behind one seam,
in that order, and cross-linked rather than closed as duplicates, because each
names a different place the second resolution happens.

## What this phase is NOT about

**A redesign of the plugin update.** The operation, the route and the settings
strip stay as Phase 21 shipped them; each task below is a named defect.

**More than one agent.** Phase 23 decides that. The seam built in batch 1 takes
one binary; it is not a registry.

**The settings page's layout.** Phase 24.

## Expected work

Tasks continue from Phase 15's. Batches run in order; inside a batch the order
is the one written.

### Batch 1: the agent binary, resolved once, tasks 130 to 132

- [x] **Task 130, #302 (P2).** One `check_agent_binary(raw) -> str` in
      `config.py`, called from `Config.__post_init__` and from
      `cli.update_plugins_command`, returning the value that is actually
      spawned. The two divergent checks at `config.py` and `cli.py` go.
- [x] **Task 131, #196 (P2).** Preflight's resolution is kept and threaded
      through `launch_argv` and `find_detached`, so the engine spawns the
      absolute path preflight found rather than a bare name tmux's server
      resolves again in its own environment.
- [x] **Task 132, #298 (P2).** The update's argv carries the same resolved
      absolute path, so `plugin_runner`'s `cwd=Path.home()` cannot change
      which file runs. One test asserts every spawn site, engine and plugin
      update alike, receives the single resolved value: the guard premortem 1
      below asks for.

### Batch 1b: Phase 15's review lows on `cli.py`, tasks 148 to 150

Added on 2026-09-27 when the phase opened: batch 1 changes `cli.py`, so the
open from-review tickets on it come with it.

- [x] **Task 148, #336 (P3).** The banner's `--help` and `--version` test
      goes through `main()`, so moving the print above `parse_args` fails it.
- [x] **Task 149, #337 (P3).** The banner's description test also pins
      `_FALLBACK_DESCRIPTION` to `pyproject.toml`.
- [x] **Task 150, #338 (P3).** The pragma comment's spaced hyphen is
      restructured.

### Batch 2: the settings strip and the run display, tasks 133 to 138

- [x] **Task 133, #315 (P1).** The strip's `note` and `settle` get an owner,
      so the plugin flow cannot settle away a refusal the settings flow
      wrote. The comment says why the owner exists.
- [x] **Task 134, #314 (P2).** `onPluginRecord` compares against the epoch and
      sequence captured before its `await`, not the live globals after it.
- [x] **Task 135, #316 (P3).** A test pins the second `isStale()` check,
      written against task 134's code, not before it.
- [x] **Task 136, #313 (P3).** A `visibilitychange` refresh, going through
      the same staleness check as every other path that paints a record.
- [x] **Task 137, #317 (P3).** The `internal_error` sentence reads as one
      sentence.
- [x] **Task 138, #308 (P3).** A guard that `settings.js` and `plugins.js`
      never assign `innerHTML`, reading structure rather than grepping for a
      string its own explanation contains.

### Batch 2b: batch 2's round 3 findings, tasks 153 to 155

Added on 2026-09-27. Batch 2's review loop stopped on its trip wire: round 2
found a defect in round 1's fix (`8967654`) and round 3 found defects in
round 2's (`aad020c`, `18397c7`). What round 3 found is filed rather than
fixed as a fourth round, and #348 waits on a decision: the page has now
guessed wrong four times at which of two unordered epochs is newer, so the
candidate fix is an epoch the server mints with an order, not a fifth guess.

- [x] **Task 153, #348 (P1).** A restart during a page load no longer lets
      the old process's record retire the live epoch. Decided 2026-09-28:
      ordered, not the narrow bail. Every record carries `boot` (the kernel's
      boot id) and `since_boot_us` (`CLOCK_BOOTTIME`, which NTP cannot step
      back); the page compares them within a boot and takes arrival order
      across boots, and `retiredEpochs` is gone.
- [x] **Task 154, #349 (P2).** The owner guard test waits for the held
      settings response to be delivered before asserting.
- [x] **Task 155, #350 (P3).** The residual case comment went with
      `retiredEpochs` in task 153.

### Batch 3: what the update prints, tasks 139 to 142

- [x] **Task 139, #305 (P2).** `_shown` cuts the raw text and escapes after,
      with a visible cut marker, and its docstring is rewritten to match.
- [x] **Task 140, #306 (P2).** The escaping test's input has no `\r`, so it
      fails with escaping reverted. Written after task 139.
- [x] **Task 141, #303 (P3).** `_read_listing` and `_approved_command` catch
      `RecursionError` beside `ValueError`, and report `plugins_unreadable`.
- [x] **Task 142, #300 (P3).** A plugin listed twice is reported as skipped,
      "listed twice", so the count covers every row, as the comment claims.

### Batch 3b: batch 3's review, task 156

Added on 2026-09-27. Batch 3's loop stopped clean after round 2: round 1's
one medium (the cut before escape pinned in the branch that actually cuts)
was fixed in `190b93e`, and round 2 found nothing in it. Its lows went to
Backlog as #352 to #357; one is a crash on the path this phase hardens, so it
stays here.

- [x] **Task 156, #351 (P2).** Output that is not valid UTF-8 is reported as
      unreadable rather than crashing the update into `internal_error`.

### Batch 4: processes and the test seams, tasks 143 to 147

- [x] **Task 143, #299 (P2).** `plugin_runner` and `tmux.py`'s runner start
      the child in its own session and kill the group on timeout, so an
      install's grandchild does not outlive the run.
- [x] **Task 144, #307 (P2).** A `thread.start()` that raises leaves the run
      `failed` with `internal_error`, published, not stuck `running`.
- [x] **Task 145, #301 (P3).** The closed stdin test fails when
      `stdin=subprocess.DEVNULL` is removed, under pytest's own capture.
- [x] **Task 146, #310 (P3).** `no_real_plugin_update` fails the test that
      reaches it, instead of being swallowed into an `internal_error` record.
- [x] **Task 147, #304 (P2).** `claude_ipc.py` moves to mutmut's
      `source_paths`, and the survivors in the plugin section are read after
      batch 3, each killed or written down as equivalent on the ticket.

### Batch 4b: batch 1's round 2 findings, tasks 151 and 152

Added on 2026-09-27. Batch 1's review loop stopped after round 2 by rule, as
round 2 found no high; its two mediums are defects in the guard premortem 1
asks for, so they stay in this phase rather than going to Backlog.

- [x] **Task 151, #345 (P2).** The `agent_binary` guard's allowlist names the
      exact expression read, not a whole function, so a raw spawn added in
      `cli.main` fails it.
- [x] **Task 152, #346 (P2).** `main()`'s resolved path test also checks the
      `Config` that `create_app` receives, and that it is the one `Engine` got.

### Batch 4c: batch 4's review, task 157

Added on 2026-09-27. Batch 4's loop stopped after round 2 by rule: round 1
found a high (an unbounded reap after the group kill) and four mediums, fixed
in `73ce21b` and `e0a1b28`; round 2 found no high. Its three lows are defects
in those fixes and went to Backlog as #362 to #364. Its medium is older than
the fixes but made worse by task 143, so it stays here.

- [x] **Task 157, #361 (P2).** The server's shutdown kills an in flight plugin
      update's group, since a daemon thread never sees Ctrl-C and the child
      no longer shares the terminal's process group.

### Batch 5b: batch 5's review, task 158

Added on 2026-09-27. Batch 5 built tasks 154, 156 and 157 (`422609d`,
`20ffb9b`, `60c0465`). Its loop stopped after round 2 by rule: round 1 found
two mediums in task 157, fixed in `0ea8706` (the handle latches); round 2
found no high, and its one medium is a missing regression test for that
latch, so it stays here. Its lows went to Backlog as #365 to #368 and #370.

- [x] **Task 158, #369 (P2).** A real runner test kills the handle mid
      update and asserts the next plugin never spawns.

### Batch 6: the dependency updates, tasks 159 to 163

Added on 2026-09-28 at Andrea's request: every open Dependabot pull request
was closed unmerged and each direct dependency it named became a ticket in
this phase, so a bump is made on `develop` and reviewed like any other change
rather than merged as a bot wrote it. This is outside the phase's objective by
decision, not by drift. Three of the nine pull requests (#192 to #194) needed
no ticket, since `develop` already locks newer versions.

- [x] **Task 159, #371 (P2).** `uvicorn` 0.53, read against the access log
      scrub and the lifespan. Locked at 0.54, which adds only opt-in HTTP/2.
- [x] **Task 160, #372 (P2).** `sse-starlette` 3.4.11, read against the
      stream's disconnect and shutdown.
- [x] **Task 161, #373 (P2).** `upload-artifact` v7 and `download-artifact`
      v8 in one commit, with the build handoff exercised before a release
      depends on it.
- [x] **Task 162, #374 (P3).** `mutmut` 3.8, checked against each
      `[tool.mutmut]` workaround. 3.8 mutates dataclass methods, so
      `Config`'s refusals were swept for the first time: #377, Backlog.
- [x] **Task 163, #375 (P3).** `astral-sh/setup-uv` v10.2.0.

## Done looks like

- [x] Every task above is ticked, or marked MOVED OUT or NOT BUILT with the
      issue number that carries it.
- [x] No spawn site resolves the agent binary a second time, and a test says
      so for every site at once:
      `test_every_read_of_agent_binary_is_the_resolved_property_or_allowlisted`,
      tightened by #345 and #346.
- [x] No from-review ticket about the plugin update or the agent binary is
      open without a decision. Checked 2026-09-29: #369 is this phase's; every
      other one filed by its reviews sits in Backlog with a P3 priority.
- [x] The mutation survivors in `claude_ipc.py`'s plugin section have been
      read, not counted: `495e6da` and `ed04093`, dispositions on #304.
- [x] A plugin update started from the phone has been watched finishing on
      the phone, after batch 2, against a private test root. Watched
      2026-10-01 on the Pixel 2 in Chrome, over `adb reverse` to a loopback
      instance with an empty root and an empty config file: 16 updated, 0
      failed, 7 left alone, in 33 seconds, the button disabled while it ran
      and the summary and every row painted when it finished. The six
      identical `local` rows it showed are #312, in Phase 24. The device
      tier was run first and was red on a label renamed on 2026-09-11,
      unnoticed because nothing selects that tier; fixed the same day.
- [x] The roadmap's Phase 22 block says `state: done`, the milestone is
      closed, and `scripts/check-phases.sh` passes. Closed 2026-10-01 as
      **done**: every ticket in the milestone landed, and every review
      finding outside it sits in Backlog with a priority. The block then
      left the roadmap under the 2026-09-26 rule.

## Fails if

Written as a premortem on 2026-09-26: it is the end of this phase and it
failed badly; what happened?

**The binary got fixed three times.** Each of #302, #196 and #298 passed its
own test, and a fourth caller that reads `config.agent_binary` directly
appeared later and resolved it again. Rule: task 132's test enumerates the
spawn sites by reading the code that spawns, not by listing the three sites
known today.

**The strip's owner was undone by the next flow.** #315 ships correctly for
two flows, and a third async writer is added without reading why the owner
exists. Rule: the owner check lives in the one function that writes the note,
and the comment says what it prevents.

**A replacement test passed for the wrong reason again.** #306's new test was
written against the old cut and escape order and passes coincidentally, the
exact defect it replaces. Rule: task 140 runs after 139, and its mutation is
checked by reverting the escape, with bytecode caching off.

**The new visibility refresh reopened the race.** #313's handler repaints
without the staleness check #314 just fixed, and a dead run's record paints
over a finished one. Rule: task 136 goes through the same entry point as
every other refresh, and batch 2 is reviewed with that question named.

**The mutation sweep was abandoned.** `claude_ipc.py` is over a thousand
lines; the sweep times out, and the closing report claims coverage nobody
read. Rule: task 147 scopes the run to the plugin section and records the
survivors on #304 before the ticket closes.

**Review found defects in its own fixes twice.** As in Phase 21. Rule: the
review loop's trip wire stops it, and the remainder is filed, which is a
finished outcome rather than a failure.

## Out of scope

- A registry of agents, or a second binary: Phase 23.
- The settings page's layout and the plugin rows' display: Phase 24, which
  holds #311 and #312.
- Splitting `server.py`: Phase 16. Splitting `app.js`: Phase 24.
- A finding from this phase's own review that adds rather than fixes:
  Backlog.
