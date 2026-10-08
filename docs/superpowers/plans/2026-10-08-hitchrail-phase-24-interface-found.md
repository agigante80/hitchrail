# Phase 24: The interface, found

**Objective: everything the phone offers can be found by looking at it, and
the list reads on the phone the design is for.**

**Written 2026-10-08, the day Phase 25 closed,** from the roadmap block and
the seventeen tickets in the milestone, each read against the tree at
`40a54fd`. Andrea asked for the phase to be built, closed and released
without stopping; the decisions below that were open are taken here as
recorded assumptions, each reversible, and each one says so.

## Goal

The settings page, project creation, the theme's way back to the system, the
mark and the way home are each reached from the first screen at 360 CSS px.
The busy list (five roots, sixty folders, long names) reads at that width
without a crushed name, an overlapping chip or a hidden last row. `app.js` is
split along the seams its section comments already draw, and the web assets
have a size guard. The plugin update page says what moved and says it once.

## What this phase is actually about

Two things filed weeks apart turned out to be one: the controls nobody could
find (#320 to #325, #333, from using the page) and the layout defects only a
real phone showed (#447 to #451, from Andrea's S25 on 2026-10-08). Both are
the same failure: every test and screenshot used one root and short names on
a 390 px viewport, and the phone in daily use is 360 px with five roots and
67 folders. So the realistic fixture (#450) is not one task among many: every
layout assertion this phase writes runs against it, at 360 px and at 320 px.

**Checked against the tree on 2026-10-08.** All seventeen still describe the
code. One premise is false: #321 says project creation "disappears under
every filter", and it does not. `New` sits in `.bar-actions` inside the sticky
`.top` block (#149), so it survives every filter and every scroll position
today. What #321 does get right is the moment it names: a search that
matches nothing is when a person most wants to create the folder they typed.

**Decisions taken as assumptions (Andrea may reverse any of them):**

- **#321: the trailing create row is not built.** It would give up #149's
  scroll survival to buy a filter survival the bar button already has. What
  is built is the part the premise check left standing: the empty state of a
  search that matches nothing offers to create a folder by that name, opening
  the same sheet with the name filled in. #321 closes on that, its comment
  recording the reason.
- **#322 is built**, since the bar button it renames stays: `New project`.
  The bar must not wrap at 360 px with the mark, the gear and the theme
  toggle beside it. If the words do not fit, the theme toggle becomes an icon
  with the same accessible name, rather than the label shrinking back.
- **#325: `/favicon.ico` joins the unauthenticated set** as one
  `(http, GET, path)` triple serving the mark's bytes, with #21's argument
  written beside it. Security auditor review required.
- **#450's type scale** was already decided by Andrea on the ticket (Material
  3: controls 14 px, body and names 16 px, meta 12 to 13 px, search input
  never under 16 px, tap targets 44 px).

**The from-review tickets (#342, #344) are terse,** and accepted as they are
under the standing exception: each is one change with its input in the body.

## Fails if

Agent drafted, as Phase 19's was: written at the plan from the evidence in
the milestone, for Andrea to amend. It is the end of the phase and it failed
badly; what happened?

1. **The split changed behaviour and nothing noticed.** `app.js` is read only
   by the browser tier. A module cycle evaluated in the wrong order leaves a
   binding in its temporal dead zone at boot, and the page is blank in one
   browser. So the split is a pure move, its own commit, run against the full
   default suite and the packaging test before anything else lands on top.
2. **The bar wrapped on the S25.** Every bar test measured 390 px, as #238's
   did, the gear and the mark and the longer label each fitted alone, and
   together they wrapped at 360. Phase 13's premortem 3 again. So every bar
   assertion runs at 360 and 320 as well as 390, with all of this phase's
   controls present at once.
3. **The fixture lied again.** Layout tests passed on one root and short
   names while the real list still broke. So #450's fixture is what the
   layout tests run on, and the screenshot of the busy list is taken from it.
4. **The favicon exemption admitted more than one path.** An entry keyed by
   path alone exempts every method and the websocket scope. So the entry is a
   triple, and `test_the_exemption_is_exactly_these_entries` names it.
5. **The watch was done on the wrong phone.** The S25 was unreachable, the
   Pixel stood in, and "the phone the design is for" was ticked on a 411 px
   screen. A watch on the Pixel says so and leaves that criterion open.
6. **The release check was muddied by #457.** The e2e flake failed 2 of 2
   full runs on 2026-10-08. So it is fixed at its cause first, never retried
   into green.

## Expected work

Tasks continue from Phase 25's 204. Batches 1 and 2 run concurrently in
separate worktrees (the layout batch touches `app.js` only for #447's
observer); every later batch builds on the split. Review at the end of each
batch, bounded as the global rules say; lows go to Backlog.

### Batch 0: the release check's flake, task 205

- [x] **Task 205, #457.** A captured failure, its cause named, fixed there or
      quarantined naming the ticket. Never retried into green.

### Batch 1: `app.js` split along its seams, task 206

- [x] **Task 206, #68, #342.** ES modules along the section comments, a pure
      move first; every new file served from the wheel and asserted so; the
      web assets gain a size guard with argued caps; the `innerHTML` guard
      reads every split file and catches the four shapes #342 names. The dead
      `.scrim` goes with it.

### Batch 2: the list as the phone holds it, tasks 207 to 209

- [x] **Task 207, #447.** The footer's real height reserves the list's end.
- [x] **Task 208, #448.** Chips and tabs never shrink into each other.
- [x] **Task 209, #449.** The name has its own line in every state.

### Batch 3: the scale and the search, tasks 210 and 211

- [x] **Task 210, #450.** The realistic fixture, the Material 3 scale, the
      computed sizes asserted, a phone capture of the busy list.
- [x] **Task 211, #451.** A clear control inside the search field.

### Batch 4: the controls, found, tasks 212 to 215

- [x] **Task 212, #320.** Settings as a gear in the bar; the footer link goes.
- [x] **Task 213, #321, #322.** `New project` in the bar; the empty search
      offers to create what was typed. #321 closes as decided above.
- [x] **Task 214, #324, #333.** The mark before the title on the three pages,
      the title a link home; `icon.svg`'s stale dark fill corrected.
- [x] **Task 215, #323.** Light, Dark and System in settings.

### Batch 5: the perimeter, task 216

- [x] **Task 216, #325.** `/favicon.ico` answered with the mark, by decision.
      Security auditor review required. Built as an entry in
      `UNAUTHENTICATED_ASSETS`, GET and HEAD only, with its refusals tested;
      the audit passed and its two lows were fixed in the merge.

### Batch 6: the plugin update rows, tasks 217 to 219

- [x] **Task 217, #311.** `updated` splits into moved (from and to) and
      current, from a second listing; an unreadable one falls back.
- [x] **Task 218, #312.** Identical skipped rows collapse into one with a
      count, in the page and the CLI; the record keeps every row.
- [x] **Task 219, #344.** `failureText`'s fallback normalised; the n=0 case.

### Batch 7: seen, task 220

- [x] **Task 220.** Screenshots regenerated; watched on the S25 at 360 px on
      a throwaway root, every control reached from the first screen and the
      busy list read. The S25's screenshots stay private. The screenshots were
      regenerated for 0.15.0; the watch is MOVED OUT, #468: the S25's wireless
      debugging was off and the Pixel was PIN locked.

## Done looks like

- [x] Every task ticked, or marked MOVED OUT or NOT BUILT with an issue number
- [x] No file under `src/hitchrail/web/` past 400 lines without an argued cap,
      held by a test
- [x] At 360 and 320 px on the realistic fixture: no horizontal scroll, no
      chip overlap, every name on its own line, the last row clear of the
      footer, the bar on one line with every control of this phase in it
- [x] `GET /favicon.ico` answers 200 with no token, and the exemption test
      names exactly one more triple. It is a set entry rather than a triple,
      the reason written in `security.py`, and the test names it
- [x] Watched on the S25: each control reached from the first screen, the
      busy list read at 360 px. MOVED OUT, #468
- [x] Screenshots regenerated
- [x] Roadmap says done, milestone closed, `check-phases.sh` passes.
      Closed 2026-10-08 as **re-shaped**: all 18 tickets in the milestone
      landed and shipped in 0.15.0, #321 closing as decided (no trailing row;
      a failed search offers to create the name, only when no project has
      it). The phone watch did not happen, moved to #468. The reviews' lows
      went to Backlog as #463 to #467. The block then left the roadmap under
      the 2026-09-26 rule.

## Out of scope

**Design changes beyond the tickets.** No new colour, no new page, no new
route besides `/favicon.ico`.

**`server.py`'s split.** Phase 16 owns it.

**A genuine multi resolution `.ico`.** #325 serves the SVG under that path;
a legacy client nobody has reported is not a reason for a binary asset.

**A build step.** The split uses the browser's own module loader; nothing is
bundled.
