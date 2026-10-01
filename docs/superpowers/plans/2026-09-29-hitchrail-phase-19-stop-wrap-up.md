# Phase 19: Stop means wrap up, and says so

**Objective: a session stopped from a phone leaves the same record as one
closed by hand.**

**Written 2026-09-29 while Phase 22 was still open; opened 2026-10-01**, the
day 22 closed. Three things were Andrea's to settle before it opened, and
each is recorded as **Decided** where it sits: no default prompt, all 25
Backlog tickets in the last batch, and the premortem as written. Kill is
unchanged, confirmed the same day.

## Goal

Stop queues the closing skill behind the task in flight, waits for the agent
to finish it under a ceiling, then exits; every moment of that sequence is in
the journal; and a stop that ends on a prompt ends the session only if the
operator opted in beforehand.

## What this phase is actually about

Stop today types `C-u`, `Escape`, `/exit`, `Enter`. The agent is interrupted
mid task and asked to exit, and whatever it knew about the work in flight
leaves with it. #242 is the change; #239 is its companion for the stop that
ends on a question; #167 is what makes either one diagnosable.

**The order is decided, and it changes #242's design.** On 2026-09-29 Andrea
answered the A/B question: "If it's close, queue, if it's kill interrupt."
Read as: Stop sends the prompt WITHOUT the `Escape` that interrupts, so it
waits behind the task in flight, and Kill, reachable throughout the wait, is
the interrupt. #242's body is still written for the other order (`C-u`,
`Escape`, verify clear, then the prompt), so it is rewritten and re-gated
before task 170 starts. The interpretation is written on #242 and asks
Andrea to say so if Kill was meant to change instead.

Three consequences of queueing that #242's body does not yet answer, each a
task below rather than an assumption:

1. **What Claude Code does with text typed while it works.** Queueing is
   remembered behaviour, not measured behaviour. #101 is the precedent: the
   background work modal was measured before anything was built on it.
   Task 169 captures the bytes.
2. **When "finished" is true.** Behind a busy agent, the pane shows an idle
   box for a moment between the task in flight ending and the queued prompt
   starting. `wrap_up_finished` reading "idle box, clear input" in that gap
   runs `/exit` before the skill ever ran. The check needs evidence the
   prompt was consumed, and task 169 says what that evidence looks like.
3. **What `C-u` destroys.** It clears whatever the person had typed but not
   sent. The exit sequence already does that; the wrap up does it earlier,
   while the agent may still be working for minutes. Written down, not
   changed.

**Why logging goes first.** The roadmap puts this phase after 15 because
"was the prompt sent, and did the pane go idle" needs an answer in the
journal before the sequence is trusted on a real session. #167 is P1 and
has no dependency, so it is batch 1.

**Why the split goes before the wrap up.** `claude_ipc.py` is 1341 lines.
#242 adds `request_wrap_up` and `wrap_up_finished` to its pane half; adding
them before #368 splits it is how the file grew past its seam in Phase 22.

**Why the mutants go before the new refusals.** #377's survivors are in
`Config`'s refusals; #242 and #239 add `stop_prompt`, `stop_prompt_timeout`
and `stop_policy` refusals beside them. Pinning the existing ones first means
a new survivor is visibly new.

## What this phase is NOT about

**Text from the page.** The deferral under "Deliberately later" binds
unchanged: `stop_prompt` is set by flag or config file only, the settings
page shows it read only, and `PATCH /api/config` refuses it.

**A reply channel.** The Stop hook option in #242 stays rejected for now; the
end of the skill is observed in the pane, as #89 decided.

**Answering the background work modal for the operator.** #239 kills on an
opt in; it never presses `1`, which is #204 condition 4.

**Changing Kill.** Kill is the interrupt because it already is one.

## Expected work

Tasks continue from Phase 22's 163. Batches run in order.

### Batch 1: the journal can answer "what did Stop do", tasks 164 to 165

- [x] **Task 164, #167 (P1).** Logging configured once at startup for
      `hitchrail.*`, formatted like uvicorn's, with `--log-level`; the stop
      sequence emits its moments; the token and pane content never reach a
      log line.
- [x] **Task 165.** The live tier proves a start and a stop are readable end
      to end from captured stderr, and a unit's journal receives them (#145's
      flush). Built as the cli tier (the real console script's startup block
      and access line, one format) and the e2e tier (a tapped stop's trace in
      order). The journal itself is Andrea's manual check under the unit.

### Batch 2: `claude_ipc` split along its seam, task 166

- [x] **Task 166, #368 (P3).** `claude_ipc/` becomes a package of four
      modules along the seams the file had: `screen` (reading a pane), `keys`
      (typing into one), `launch` (argv, trust, session link) and `plugins`,
      every public name still importable from `hitchrail.claude_ipc` and
      reached only through it. The structural guards key on a path under
      `src/hitchrail` first, as a no-op commit, so the move's diff proves one
      thing. The size caps, the vocabulary guard, `.claude/rules/security.md`'s
      list and mutmut's `source_paths` move with it. No behaviour change, and
      the suite unchanged proves it.

### Batch 3: `Config`'s refusals pinned, tasks 167 to 168

- [x] **Task 167, #377 (P2).** The 46 counted were 38 with a changed
      condition and 8 that change only a message. 29 of the 38 are killed in
      `tests/test_config_mutants.py`, along with all 8 message mutants. The
      other 9 are equivalent, and the file's docstring says why for each.
      `tests/test_tls.py` stays out of the mutmut selection because it runs
      `openssl`. Its refusals are pinned with plain files instead.
- [x] **Task 168.** All 37 killable mutants were reapplied by hand with
      bytecode caching off. Each one fails the new file on a refusal or an
      acceptance, and none fails on an import error.

### Batch 4: Stop queues the closing skill, tasks 169 to 174

- [x] **Task 169.** Measure, on a real `claude` in a private tmux: the pane
      bytes while a typed message waits behind a running task, the moment it
      is dequeued, and what `C-u` does to a queued message. Recorded in memory
      and on #242 as #101 recorded the modal. Nothing after this task is
      built until it is.
- [x] **Task 170, #242 rewritten.** The body rewritten for order B from task
      169's bytes, the old body preserved as a comment, and re-gated.
- [x] **Task 171, #242.** `Config.stop_prompt` and `stop_prompt_timeout`, with
      refusals for a newline or control character. **No default: unset or
      empty is today's Stop**, decided 2026-10-01 because the obvious
      default, `/forge-kit-governance:closing-sessions`, is a skill most
      installs do not have. The operator sets it once in the config file,
      and the startup block says which prompt Stop will send, or that it
      sends none.
- [x] **Task 172, #242.** `Tmux.send_text` through `send-keys -l`;
      `claude_ipc.request_wrap_up` (no `Escape`) and `wrap_up_finished`; the
      grep guard widened to name both typing functions.
- [x] **Task 173, #242.** `Engine.stop()` gains the `closing` phase, the sweep
      advances it to `exiting`, `Session.stopping_phase`, `docs/api.md`, and
      design 4.3 step 2 amended.
- [x] **Task 174, #242.** The wait dialog names the phase; E2E with a fake
      `claude` shim that queues a line while busy and writes a handoff when it
      reads the prompt, driven on events (#70).

### Batch 5: a stop that ends on a prompt, tasks 175 to 176

- [x] **Task 175, #239.** `stop_policy`, off by default, refused for an
      unknown value; at the expiry, a modal plus the opt in kills, anything
      else reports; the self project is never killed.
- [x] **Task 176, #239.** Design 4.3 step 4 and "Deliberately later" amended;
      E2E where a shim answering `/exit` with a prompt ends `stopped`.
- [ ] **#239's settings page control.** MOVED OUT to #409, Backlog: shipped
      read only there, since `end_anyway` is a kill nobody tapped and a page
      the token reaches is a weaker choice than a flag; Andrea decides.

### Batch 6: the Backlog's first rule, tasks from 177

**Decided 2026-10-01: all 25.** The Backlog's first rule hands an opening phase
"every open `from-review` ticket about a file it changes", by rule rather than
judgement. This phase changes `claude_ipc.py` (all of it, by the split),
`config.py`, `engine.py`, `tmux.py`, `tmuxnames.py`, `server.py`, `cli.py`,
`settings.py`, `web/app.js`, `web/settings.js` and `docs/api.md`. Read
literally, that is 25 tickets, as many as Phase 22 took and built:

- `claude_ipc.py`: #352, #353, #355, #356, #362, #363, #366, #370, #384, and
  the tests the split moves: #367, #385
- `config.py` and its tests: #30, #275, #283, #347, #358
- `engine.py`, `server.py`: #279, #365
- `tmux.py`, `tmuxnames.py`: #276, #278, #357, #364
- `cli.py`: #341
- `settings.py`, `web/settings.js`, `web/app.js`: #281, #343

Left in Backlog because the phase does not change their file: #342
(`tests/test_web.py`), #344 (`web/plugins.js`), #359 (`tests/conftest.py`),
#360 (`procs.py`), #376 (`plugin_runs.py`), #277 (`tests/support.py`), and the
four infrastructure tickets.

All 25 are taken, as the rule says, in this last batch, so the stop work in
batches 1 to 5 is never waiting on a low. If batch 6 is still open when
batches 1 to 5 are done, the phase closes re-shaped and the rest go back to
Backlog: re-shape, never extend. Their milestones moved when the phase
opened. Each is ticked here by number as it closes.

All 25 closed by 2026-10-01, #30 last. Its review lows and those of #242 and
#239 went to Backlog (#410 to #418), not this milestone, so the phase is never
held open by a low.

## Done looks like

- [ ] A session with `stop_prompt` configured, stopped from the interface,
      ran the closing skill before it exited, observed on a real session by
      Andrea, and the journal shows the prompt sent, the wait, and the exit
- [x] A stop that ends on a prompt does nothing on its own unless the operator
      opted in before tapping
- [x] `stop_prompt` cannot be set through any HTTP route, and a test says so
- [x] With `stop_prompt` unset, which is the default, Stop is byte for byte
      today's sequence
- [x] Every task ticked, or marked MOVED OUT or NOT BUILT with an issue number
- [x] No `from-review` ticket open in the milestone without a decision
- [ ] Roadmap says done, milestone closed, `check-phases.sh` passes

## Fails if

Written as a premortem on 2026-09-29: it is the end of this phase and it
failed badly; what happened? Drafted by the agent and **confirmed by Andrea
as written on 2026-10-01**, with the second one settled by removing the
default rather than choosing a better one. They added none of their own, so
the list is the agent's view of the risk rather than the operator's.

**The skill never ran and the journal said it had.** The pane showed an idle
box in the gap between the task in flight ending and the queued prompt
starting, `wrap_up_finished` read it as done, and `/exit` went in first.
Rule: task 169 names the evidence of consumption before task 172 builds the
check, and a unit test drives a capture sequence with that gap.

**The prompt named a skill the machine did not have.** On a machine without
forge-kit, Stop typed an unknown command, the agent answered with an error,
and the wrap up "finished" in a second having done nothing. Rule: there is
no default (task 171), and the startup block says which prompt Stop will
send. A configured skill that is missing is still possible, and the journal
line for the wait says how long it took, so a one second wrap up is visible.

**The ceiling cut the work it was protecting.** A task in flight ran past
300 seconds, the ceiling fired, and the exit's `Escape` interrupted the very
work queueing was chosen to protect, with the skill never started. Rule: the
dialog says the ceiling was reached, the journal records it, and the default
is revisited after Andrea's first real week, not at design time.

**A person's unsent draft was destroyed.** Someone typing into a session
from the terminal lost their text when a phone tapped Stop. Rule: written
into the docs and the dialog's copy, since the exit sequence already does it.

**The split changed behaviour.** Batch 2 moved a name and a patch point in
a test stopped reaching the real module, so a test passed against nothing.
Rule: after the split, the mutants that killed tests before it are
reapplied to the new paths.

**Review found defects in its own fixes twice.** Rule: the trip wire stops
the loop and the remainder is filed.

## Out of scope

- A reply channel through a Claude Code Stop hook: Backlog, recorded on #242
- Choosing a key for the background work modal: never, #204 condition 4
- Text from the page into a session: "Deliberately later"
- More than one agent's wrap up: Phase 23
- The settings page's layout: Phase 24
- Editing `stop_policy` from the settings page: Backlog, #409
