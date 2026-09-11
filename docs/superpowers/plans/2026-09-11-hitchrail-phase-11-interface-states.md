# Phase 11: The interface in every state

**Objective: every state the interface can be in says something true, legibly.**

Twelve tickets, tasks 54 to 65, in five batches. Work the batches in order and
the tickets within a batch in the order given; the ordering is dependency, not
taste.

## Goal

No screen states something it did not read, and every token pair passes AA.
That is the roadmap's done-when, unchanged, and this plan exists to make both
halves checkable rather than felt.

## What this phase is actually about

The states that are rare and the wordings that are wrong. Phase 6 built the
interface for the states a demo reaches; what is left is the dialog a person
sees once a week, at the exact moment they are deciding whether to kill a
process with unsaved work, and it is the dialog that sends them to the wrong
place (#165), or tells them the opposite of what happened (#82), or is pinned
to the bottom of the screen with the destructive action nearest the thumb
(#161).

**Four of the milestone's tickets had already shipped when this plan was
written, and one had been superseded.** #204, #169 and the mechanism half of
#166 landed on 2026-09-06 with the 0.5.0 release and stayed open with every
acceptance box unticked; #204's own body called #165 shipped and pointed at the
log drawer, which is the pane VIEW and not the dialog #165 names. Every ticket
below was checked against the tree on 2026-09-11 before it was given a task,
and the check is the first step of each task, not a formality: this repository
moves faster than its tickets.

## What this phase is NOT about

**The stop redesign.** #242 and #239 sat in this milestone and neither is a
screen saying something true: they change what Stop MEANS, in the engine and
`claude_ipc`, and they carry an open sub decision. They are **Phase 19** now,
cut on 2026-09-11 for the reason Phase 16 is one ticket: what it changes, not
how big it is.

**The `app.js` split.** #68 is Phase 18. Every task here that touches `app.js`
must reuse the view that exists rather than add a renderer, which #165 already
says of itself, and the size guard in `test_config.py` does not read `web/`, so
this plan has to say it instead.

**Engine work beyond the two facts a screen renders.** Tasks 56 and 57 are
engine and `claude_ipc` tickets, and they are here because the "waiting for an
answer" badge is a screen and both are the reasons it lies: one when the server
knows and the page is never told, one when the pane shows an answered modal in
the scrollback and the row reads as live. **A third engine ticket does not join
them.** It goes to its phase, or to Backlog, and this plan is the precedent the
next reviewer cites.

## The exit criteria, and which task answers each

| Criterion | Tasks |
|---|---|
| 1. No screen states something it did not read | 55, 56, 57, 58, 59, 60, 61, 62, 64, 65 |
| 2. Every token pair passes AA | 63 |

Task 54 serves neither directly and goes first, because a bottom-pinned dialog
inverts the one thing `showDialog` promises: safest action first, the
dangerous one furthest from the thumb. Every dialog this phase touches is
measured after it, and none can be measured before.

## Batch 1: the dialogs sit where the design says, task 54

- [ ] **Task 54, #161.** Every dialog is pinned to the bottom of the viewport.
      `margin-bottom: var(--keyboard-inset, 0px)` at `app.css:392` resolves to
      `0px` with no keyboard, which replaces the user agent's
      `margin-bottom: auto` and collapses the centring. A regression from #103,
      whose reasoning is right, whose default is not, and whose test covered
      the keyboard-open direction only.

      Either `--keyboard-inset` is never written as `0px`, or the stylesheet
      stops treating a zero length as "no adjustment"; the code says which and
      why, and the stylesheet comment is rewritten, because today it explains
      a correct mechanism and a wrong default, which is worse than no comment.

      **Verified at the phone viewport `tests/e2e/test_screenshots.py` already
      defines and at a desktop one, both directions**: centred with no
      keyboard, primary action visible with one. The regression test fails
      against today's stylesheet before it passes.

## Batch 2: the screen that decides a kill, and the two facts behind its badge, tasks 55 to 57

- [ ] **Task 55, #165.** The `is waiting for you` dialog knows where the prompt
      is and does not show it. The engine captured that pane one screen
      earlier to set the flag this dialog renders; the dialog then offers
      `Leave it` and `Kill it`, and "that terminal" points the reader at the
      session link, which is the one surface the prompt is never on.

      Reuse `openLogs`'s pane view, which since #204 carries the keypad for a
      row flagged as waiting, so the keys arrive in this dialog with the pane.
      That is the last clause of #166 ("from the waiting dialog"), closed as
      superseded, and it lands here rather than as its own ticket. Order as
      `showDialog` requires: the pane and its keys above `Leave it`, `Kill it`
      last. Say pane, not terminal. `textContent` only. The `No answer` branch
      is unchanged, and the capture count is written down: one from the sweep
      and one from the dialog is affordable and must be deliberate.

- [ ] **Task 56, #218.** A "waiting for an answer" claim re-confirmed AFTER its
      TTL is kept and announced to nobody, so the server knows and the page
      shows nothing. Two representations of one fact, the store and
      `attention.standing`, and the prune sits on the wrong side of the
      renewal. The test asserts an EVENT was published, not a flag, and
      `aging = []` no longer survives the suite.

- [ ] **Task 57, #208.** `awaits_answer` scans backwards for the ornament, so a
      modal already answered and scrolled up reads as live while the agent
      works. Harmless when it drew a badge; #204 turned it into a keystroke
      into a working agent. Fix it in `claude_ipc` and nowhere else, with a
      captured row behind every new belief about Claude Code's layout, proven
      against a real pty in the live tier, and `send_answer`'s signature still
      refusing a capture handed in from outside.

## Batch 3: the wordings that are wrong, tasks 58 to 60

- [ ] **Task 58, #162.** `Open` is the one control that does not open the
      session; it opens the pane tail. Rename it to the word `docs/api.md`,
      the route and the drawer heading already use, measured to fit a running
      row at 390px beside the other controls and the badge, accessible name
      equal to the visible label, and the `app.js` comment that disambiguates
      the two controls deleted rather than left describing a distinction the
      words now make.

- [ ] **Task 59, #163.** `Continue` is Claude Code's own word, borrowed out of
      the sentence that explained it. One decision with task 58, filed as two:
      renaming the log control is what frees `open` for the control that
      actually opens a session. The label names the action and its object, no
      vendor name, visibly a link that leaves the page, `rel="noopener
      noreferrer"` if it opens a new context, and `Get link` reads as the same
      action in a not-ready state or the difference is argued in place.

- [ ] **Task 60, #82.** `showRefusal` renders `unreadable_answer` as "That did
      not work", and for a stop, a kill, a start or a create that is a guess
      which guesses wrong: on a 2xx the action DID work and only reading the
      reply failed. The next thing a person does is tap Stop again or reach
      for Kill. `showRefusal` stops speaking for that code; the page says what
      it knows, the request was sent and the reply could not be read, and
      that the list will catch up.

## Batch 4: a stream that reports its own failures honestly, tasks 61 and 62

Both live in the stream's fatal error branch, which `2dc9396` made testable:
a refused stream AND a refused listing installed before `goto`, with the
listing succeeding exactly once so boot's own `refresh()` cannot fake the
pass. Build on that harness rather than beside it.

- [ ] **Task 61, #71.** The fatal branch asks once per fatal error, and the
      reopen backs off forever, so a phone holding a stale token has its
      refusal dialog torn down and rebuilt every minute, focus and all. A
      refusal already open for the same reason is left alone, asserted at the
      browser tier by dialog IDENTITY across at least two reopen attempts:
      the rebuild produces identical text, so text proves nothing.

- [ ] **Task 62, #72.** The fatal branch's `refresh()` can reach
      `setStreamState("blind")`, whose copy is "Live, but this machine cannot
      be read", at the one moment the stream is provably not live. `blind`
      requires an open stream the way the recovery path already does when
      clearing it. The test sets both conditions at once, stream fatally
      refused and listing answering 503, which neither existing `blind` test
      does.

## Batch 5: measured rather than felt, tasks 63 to 65

- [ ] **Task 63, #69.** Four palette pairs put a colour on its own tint and
      fall under 4.5:1; the dark `--danger` pair is 1.5:1, and `detached` is
      the state the design says must never be missed. Not "darken the token":
      `--danger` is also a background under `#FFFDFA` and a border, so a
      separate `--danger-on-tint` and `--warn-on-tint` in all three palette
      blocks, which the theme test already asserts of every other token.

      **The exit criterion is a computation, not a judgement.** A test reads
      `app.css`, derives every foreground and background pair the stylesheet
      actually produces, computes the WCAG ratio, and fails under 4.5:1. The
      premortem below names the alternative: tokens retuned by eye until they
      look fine, and "passes AA" asserted by nobody.

- [ ] **Task 64, #78.** `GET /grant/` answers a raw JSON 401 in a phone
      browser, because `TokenMiddleware` answers before the router's
      `redirect_slashes` sees it and `/grant/` is not in `UNAUTHENTICATED`.
      Safe direction, and still the dead end `test_an_arrival_with_no_key_can_type_one`
      was written about; phones and messaging apps add the slash on their own.
      Add the entry and write down why, because the set's whole point is being
      short with an argument behind each member, and the next person to add
      one will cite this.

- [ ] **Task 65, #90.** The footer shows memory used with no ceiling. "1.4 GB"
      beside "no limit" is a different sentence from "1.4 GB of 4 GB", and the
      reading is free where the setting is not ours: Hitchrail is a launcher
      and does not own cgroup policy. Read the ceiling through the injected
      memory seam, show it where it exists, say "no limit" where it does not,
      and never set one. The control half of the ticket stays out, argued on
      the ticket.

## Done looks like

- [ ] Every task above is ticked, or is marked MOVED OUT with the issue that
      carries it, per the convention in `.claude/CLAUDE.md`.
- [ ] Every dialog and every row control this phase touched has been seen at
      the phone viewport, in the e2e tier, not only under a desktop one. The
      test that proves each fix runs there.
- [ ] `uv run pytest` carries a test that computes every foreground and
      background pair from `app.css` and fails under 4.5:1, and it passes.
- [ ] The release that ships this phase runs `uv run pytest -m screenshots`
      and commits `docs/screenshots/`, because three of the twelve change a
      label or a dialog those images show.
- [ ] The roadmap's Phase 11 section carries `**Status: done**` with the
      closing date and the issues, and this plan has no unticked box without
      a marker.

## Fails if

Written as a premortem on 2026-09-11, by asking: it is the end of this phase
and it failed badly; what happened? Four answers, each with the evidence that
made it believable, and each with the rule that stops it.

1. **The fixes were verified on fixtures, not on a phone.** #161 IS this: #103's
   keyboard fix was right, its test covered one direction, and every dialog in
   the product moved to the bottom of the screen for a week before anybody
   held it. A dialog fix checked under Playwright at a desktop viewport
   repeats it. Rule: the e2e test for each web task runs at the phone
   viewport, and the closing review holds the phone.

2. **AA was felt, not measured.** The done-when says "every token pair passes
   AA", and until task 63 lands nothing computes a ratio. Tokens retuned by
   eye until the badge looks fine is Phase 10's criterion 1 again, a claim
   with no check behind it. Rule: task 63's test is the criterion; a phase
   closing without it has not met criterion 2.

3. **The screenshots now lie.** `Open` becomes something else, `Continue` is
   reworded, the dialogs move, and `docs/screenshots/` still shows the old
   interface on PyPI and in the README, because the capture is run at a
   release and by default never. Phase 10 found that capture publishing the
   wrong image for months. Rule: the closing release regenerates them, and
   `test_every_shot_the_capture_declares_is_committed` keeps the set
   complete.

4. **It absorbed the engine again.** Two engine tickets are in, both argued
   above as the facts behind one badge. The stop redesign followed them in
   and was moved out on the day this plan was written. Phase 10 went from
   sixteen tickets to thirty nine while six were being closed, because its
   objective absorbed every finding. Rule: a third engine or `claude_ipc`
   ticket goes to its phase, and this plan is what the reviewer cites.

## Out of scope

- The stop redesign, #242 and #239: **Phase 19**.
- Splitting `app.js`, #68: **Phase 18**.
- A kill control on the row itself: escalation by default, and its own
  ticket if it is ever wanted, per #169.
- Setting `MemoryHigh` on a scope: not Hitchrail's, argued on #90.
- A free text field to a session: deferred in the roadmap, and #204's three
  conditions are the line.
