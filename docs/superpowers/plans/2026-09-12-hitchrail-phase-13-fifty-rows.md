# Phase 13: Fifty rows on a phone

**Objective: the interface stays usable when there are fifty projects across
five roots, and says what it knows about each.**

## Goal

A fifty row list can be narrowed to one root in one tap, the primary action is
reachable at any scroll position, and the page answers "which build is this,
since when, and who is it running as" without an SSH session. That is the
roadmap's done-when, unchanged, and this plan exists to make each half
checkable at fifty rows rather than at the five the fixtures seed.

## What this phase is actually about

Phase 11 was about states saying something true. This is about a person
FINDING the row they want among a lot of them, and about the page answering
questions it currently cannot. Every ticket came from using a real five root
install, which is also why none of them is a new power: the list is complete
and correct, and what is missing is navigation, provenance, and one control
that composes a power each row already has.

**Every ticket was checked against the tree on 2026-09-12 before it was given
a task**, body and comments, and every premise held. What had gone stale was
the cross-references: controls renamed in 0.6.0, `#161` and `#69` cited as
open, a note on `#240` that read as a dependency on Phase 19. Those are fixed
on the tickets, and the check is the first step of each task, not a
formality: this repository moves faster than its tickets.

**Two decisions were taken by the operator on the day this opened**, and
neither is a question a task still has to answer. A standalone Kill all is not
built (#241, closed, recorded in design section 7 beside the row rule it
extends). The mark is direction 3, the rail as the list with one session
running (#160).

## What this phase is NOT about

**Grouping the list by root.** Section headers are the obvious next thought
after the chips and a different trade: they cost vertical space on the surface
with least of it, and with a filter applied most groups are empty. Filter
first, measure, then decide; #146 says so itself.

**Streaming logs.** Deliberately later in the roadmap. #151 gives the tail a
URL and polls the same route the drawer uses; if that page makes the case for
a stream, the case goes on its own ticket with the evidence.

**A drag-resizable drawer.** #168 takes the cheap widening; #151 is the real
answer; a handle is the mechanism that works around a size chosen too small,
and it is a poor target on the device this product is for.

**Setting a memory limit.** #243 reads the ceiling and #90 shows it. Hitchrail
is a launcher and does not own cgroup policy; setting `MemoryHigh` on a scope
it created is a separate decision with its own ticket if it is ever wanted.

**The artboards.** #244 asks the owner to re-export them with the measured
palette. Nothing here waits on it, and this phase's glyphs and mark are
vendored or drawn to `currentColor`, so they do not depend on it either.

## The exit criteria, and which task answers each

| Criterion | Tasks |
|---|---|
| 1. A fifty row list narrows to one root in one tap | 71, and 72 makes the search agree with it |
| 2. The primary action is reachable at any scroll position | 73 |
| 3. The page answers "which build, since when, as whom" without SSH | 67, 68 |

Tasks 69, 70, 74, 75, 76, 77 and 78 serve the objective's second clause, "says
what it knows about each", and the phase's delivers line, rather than a
criterion: the ceiling beside a row's figure, logs at a URL, bulk stop, and
the marks.

## Expected work

Twelve tasks in five batches, one ticket each. Work the batches in order and
the tickets within a batch in the order given; the ordering is dependency,
not taste. **The fifty row fixture comes first in batch 2 and every later
batch runs against it**, because premortem 1 is the failure this phase is
most likely to have.

### Batch 1: the facts the page cannot answer, tasks 67 to 70

One payload, `GET /api/projects`, gains the per server constants, because it
is fetched already and a second round trip for a string is a round trip on a
phone. The footer gains one line under what is there. `docs/api.md` is checked
against the server both ways, so each field is documented or the suite fails.

- [x] **Task 67, #147.** The footer says which version this is and where it
      came from. `hitchrail.__version__` on the listing payload, `null` when
      `importlib.metadata` cannot answer (a source checkout with no install),
      and the footer omits it rather than rendering a guess. One link, to the
      repository, `rel="noopener noreferrer"`, and the code says it is the
      only outbound link on the page besides the session links. Fits at 360px
      with a long dev version string.

- [x] **Task 68, #148.** Since when, as whom. `getpass.getuser()` falling back
      to the numeric uid, and `time.time()` at startup, both read ONCE and held,
      asserted by a test that two listings taken apart in time report an
      identical start instant. Formatted in the viewer's timezone by the
      browser, absolute with the relative beside it. Same payload as task 67.

- [x] **Task 69, #243.** A session's memory ceiling, read from the tightest
      `memory.max` along its cgroup ancestry, never the leaf's: #172 measured
      that cgroups are inherited across fork, so a pid can sit in the scope of
      the shell that started the tmux server. A seam in `ram.py`, driven in
      the hermetic tier by a fake cgroup tree on a temp dir; unknown is
      `null`, never `total_mb`; cgroup v1 is `null` rather than a parse of the
      wrong file. `ram_limit_mb` on the session payload, and the cost with
      fifty running rows measured and written in the reader's docstring.

- [x] **Task 70, #90.** The row shows "1.4 GB of 4 GB" where a ceiling exists
      and says "no limit" plainly where none does, and the hard floor refusal
      names the largest session with its ceiling. Display only; the reading is
      task 69's and this cannot start before it.

### Batch 2: finding the row, tasks 71 to 73

**First, the fixture.** An e2e harness seed of fifty folders across five
roots, with a handful running, so that the chips, the search, the sticky
header and the bulk stop are each proved at the size the phase is named for.
Five rows prove nothing about fifty; the phase has that number in its title
and no test had ever rendered it.

- [ ] **Task 71, #146.** Root chips, multi-select, in a strip below the state
      tabs and above the search, present only with more than one root. OR
      among roots, AND with the state tab and the search text. Persisted per
      viewer in `localStorage`, intersected with the roots actually present so
      a stale selection cannot filter a single root to nothing, and rendered
      as text. Deselecting every chip is "all", never "none": zero rows for a
      full machine is the named failure. The empty state says which filter
      emptied the list. Not a server side parameter.

- [ ] **Task 72, #164.** Suggestions under the search, from `state.projects`,
      no request. The ARIA editable combobox with list autocomplete: focus
      stays on the input, `aria-activedescendant` moves attention, nothing is
      auto-selected, down, up, Enter and Escape as the reference pattern
      specifies. Matches the folder, not the qualified string, which is why
      this follows task 71: roots have their own chips by then. Each
      suggestion shows its root when there is more than one.

- [ ] **Task 73, #149.** The header collapses to a compact row on scroll and
      keeps New and the theme toggle; the tabs, the chips and the search stay
      sticky beneath it. `env(safe-area-inset-*)` respected. The iframe idea
      is already recorded as impossible on the ticket with the measured
      headers. **Measured, not felt:** the header costs no more vertical
      space at rest than it does today, and premortem 3's rule below is the
      assertion.

### Batch 3: reading the pane, tasks 74 and 75

- [ ] **Task 74, #168.** The pane view is wider and taller where there is
      room. A modifier on the shared pane view's container, never on the
      shared dialog rule, sized in `ch` so eighty columns fit without wrapping
      at a desktop width. At the phone viewport nothing changes, and the stop
      confirmation is measured unchanged at both widths, which is the
      assertion that stops the shared rule being edited.

- [ ] **Task 75, #151.** `GET /logs/{name}`, a page served from `web/` behind
      the same stack, polling the same `/api/sessions/{name}/logs` route the
      drawer uses. No stream. The pane view gains "Open in a tab" and the
      drawer stays. **A page route resolves a name exactly as strictly as the
      API route beside it**: same allowlist, same `split_identifier`, same
      resolved-parent check, and the refusal tests run on the new path (a
      separator, a leading dot, a parent reference, a trailing newline, an
      unknown name, a forged `Host`, no token). An unknown name refuses; it
      never renders an empty tail that reads as "printed nothing".

### Batch 4: many rows at once, task 76

- [ ] **Task 76, #240.** Stop all, composed from the stop each row has, no new
      route. The set is every `running` row that is not protected; stale rows
      get Clear and are left out. One confirmation naming the count, DELETEs
      issued **in sequence**, never in parallel: `request_stop` captures the
      pane between key groups on the executor that serves the operator, and
      fifty captures at once is the load #180 moved the sweep off the request
      path to avoid. One wait dialog reporting per row from the event stream:
      requested, exited, refused with the code's message, not finished. "Do
      not wait, kill them all" throughout the wait, styled danger, second,
      killing only rows still in flight. The timeout reports and does not
      kill. Proved against the fifty row fixture, scrolling inside the dialog
      at 400px. Builds against today's stop sequence; when #242 lands in
      Phase 19 the per row phase becomes a word on the row, nothing more.

### Batch 5: the marks, tasks 77 and 78

- [ ] **Task 77, #150.** Seven glyphs for the badge and the protected row,
      from Tabler, vendored as one inline `<symbol>` sprite with the licence
      text and the version recorded in the file, `currentColor`, sized in
      `em`. `detached` and `stale` are the pair to get right, and the test is
      the ticket's: obviously different at 16px. The words stay beside the
      shapes. `tests/test_palette.py` keeps the contrast honest whatever the
      glyphs do.

- [ ] **Task 78, #160.** The mark, direction 3: a row of short vertical marks
      on a baseline, one taller or filled. One path-based SVG on a 24 or 32
      unit grid, checked at 16px in both themes, then the favicon on both
      pages, the touch icon, a minimal manifest, `theme-color`, and the top of
      the README. Nothing fetched off the machine, no service worker with the
      reason written down, and the wheel's asset check grows to include it.

## Done looks like

- [ ] Every task above is ticked, or is marked MOVED OUT with the issue that
      carries it.
- [ ] The fifty row fixture exists and tasks 71, 72, 73, 75 and 76 have a test
      that runs against it at the phone viewport.
- [ ] `docs/api.md` documents every field this phase added to the listing and
      session payloads, and the round trip tests pass.
- [ ] The premortem's four rules each have the assertion named below, in the
      suite.
- [ ] `uv run pytest -m screenshots` regenerated and committed, since the
      footer, the header, the chips and the badges all appear in them.
- [ ] The roadmap's Phase 13 block says `state: done`, the milestone is closed,
      `scripts/check-phases.sh` is clean, and this plan has no unticked box
      without a marker.

## Fails if

Written as a premortem on 2026-09-12, by asking the operator: it is the end of
this phase and it failed badly; what happened? Four answers, confirmed as the
list, each with the evidence that makes it believable and the rule that stops
it.

1. **Nothing was ever tested with fifty rows.** The fixtures seed three to
   five projects, the phase has fifty in its title, and every one of the
   chips, the suggestions, the sticky header and the bulk dialog would pass
   at five and fail at fifty in a way nobody saw. Rule: the fifty row fixture
   is the first thing batch 2 builds, and no later task's browser test runs
   against a smaller seed.

2. **Stop all fired fifty captures at once and the machine stalled.** The
   stop sequence captures the pane between key groups on the request
   executor; fifty in parallel is exactly the load #180 measured and moved
   off the request path. Rule: the DELETEs are issued in sequence, asserted
   by a test that observes their order and their non-overlap, not only their
   count.

3. **A sticky header plus chips plus search plus the footer left three rows
   of list on an 844px phone.** Every strip is individually right and together
   they eat the screen the phase exists to make scannable. Rule: a browser
   test at 390x844 measures the list's visible height with the header at
   rest and asserts it is no smaller than today's, and the collapsed header
   is measured smaller than the rest state.

4. **A new page route resolved a name more loosely than the API beside it.**
   `/logs/{name}` is the first page route with a project name in its path,
   and a page that validates less strictly than the sub-route it mirrors is
   the asymmetry that gets missed. Rule: task 75's refusal tests are the
   API's own refusal cases run on the page path, plus a forged `Host` and a
   missing token, and the page reaches the engine through the same function
   the API does.

## Out of scope

- Grouping by root: after the chips are measured, its own ticket if wanted.
- Streaming logs: deferred in the roadmap; #151 polls.
- A drag-resizable drawer: #168 option 2, reopened only with evidence after
  #168 and #151 have landed.
- A standalone Kill all: #241, decided not built, design section 7.
- Setting `MemoryHigh` on a scope: not Hitchrail's; its own ticket if wanted.
- The artboards: #244, the owner's.
- Sending input beyond one key from a literal set: #204's three conditions
  are the line, and the logs page adds no input.
