# Phase 15: The package as strangers meet it

**Objective: somebody who has never seen this project can install it, tell
what it is, see that it is maintained, and be helped when it goes wrong.**

## Goal

The PyPI page and the README agree with each other and with what `--help`
actually prints. A stranger's first two seconds on the README answer whether
the project is published, maintained and licensed; their first `pip install`
or `uvx` run works from the line PyPI itself shows; and a bug report from a
machine nobody on this project has seen can be answered from the journal
instead of guessed at.

## What this phase is actually about

Everything here came from looking at the published PyPI page beside the
README and finding they disagree, or say nothing, and from failing to answer
a support question about a real machine because the journal held uvicorn's
access lines and nothing else. Opened on 2026-09-24, ahead of Phase 16 to 19
in the file even though none of them jumped the queue: it was already the
next `planned` phase in order, and it was pulled forward on the operator's
call because they are about to write about the project publicly and point
readers at exactly the surfaces this phase fixes.

**One ticket was filed the same day the phase opened, from a real gap.** The
operator asked how to update the Hitchrail install on this machine and found
the running service two minor versions and five patch versions behind, with
no README section telling them how to close that gap for either install
shape (`uvx`, which re-resolves close to every run, or `uv tool install` plus
the packaged systemd unit, which does not). That is #319, folded into this
phase's `docs` work rather than opened as its own phase, because it is the
same "stranger meets the package" objection this phase already exists to
answer.

**A second ticket was added the same day, by the operator's own direction
rather than from a gap found in passing.** #320 moves the settings control
from a text link at the end of the footer into an icon button in the header
bar. It is not in the roadmap's original Delivers list for this phase, and it
is not about install or PyPI parity; it is included anyway because the
operator asked for it directly, ahead of the same public write-up driving
task 113. It reverses a placement #238 argued for on purpose (a *text*
button in the bar wrapped at 390px and grew the header), so task 116 below
carries the new measurement rather than assuming an icon behaves like the
text button that was actually tested.

**A third pair was added the same day, from the same direction rather than a
gap found in passing.** The operator found the bar's `New` button unclear on
its own, asked for online research before a ticket was filed, and chose both
directions the research turned up rather than one: #322 gives the button a
clearer label, and #321 removes it from the bar entirely in favour of a
permanent row at the end of the project list, the "persistent add action"
pattern Trello, Notion and Google Keep all use. #321, if built, makes #322
moot, and #322 says so under its own Dependencies section. #321 also reverses
part of #149's decision that the controls acting on the list survive
scrolling: task 118 below records why creation is treated differently from
the filters #149 named, and rewrites the one test that measured it.

**A fourth was added the same day, from a question the operator asked
directly rather than a gap found in passing.** The header's `Dark`/`Light`
toggle can reach an explicit light or dark choice but never back to following
the system once one is picked. Researched first: Lea Verou's 2026 piece on
dark mode toggles argues a persistent header toggle, which is a developer
tool convention Hitchrail already follows, should stay a simple two state
control, and that the full three way choice belongs in settings instead of
crowding the one-tap spot. #323 adds Light/Dark/System to the settings page
and leaves the header toggle exactly as it behaves today, so #53's already
tested guarantee that an explicit choice wins over a later system change is
not touched.

## What this phase is NOT about

**A redesign of anything this phase's tickets touch.** Every ticket here is a
specific, already-argued fix: a missing line, a stale classifier, a badge
row, a help string, a log handler. None of them is licence to restructure
`cli.py`'s banner, rewrite `server.py`'s routes, or invent a logging
framework beyond what #167 actually asks for. That restraint is the point:
the premortem below is exactly about this phase absorbing more than its
tickets, the way Phase 10 once did before it was narrowed to escape it.

**Splitting `app.js` or `server.py`.** Phase 18.

**The stop sequence.** Phase 19.

**Streaming logs, or a log viewer.** Not asked for; #167 is about the daemon
producing a usable journal, not shipping a viewer.

## Expected work

No task here depends on another; they touch disjoint files and ship in any
order. Listed by priority.

### `docs`, `packaging`, `cli`: the README and PyPI agree with each other

- [ ] **Task 109, #167 (P1).** A real logging handler, level and timestamp
      for the daemon, so "was the stop request sent" and "did the plugin
      update run" have an answer in the journal on a machine nobody here has
      seen. `tests/test_cli.py` or a new `tests/test_logging.py` per the
      ticket's own unit test specs.

- [ ] **Task 110, #156 (P2).** The README gets a `pip install hitchrail` line
      next to `uvx`, matching what PyPI's own project page already shows.

- [ ] **Task 111, #157 (P2).** The deprecated PyPI licence classifier is
      dropped in favour of the SPDX expression already correct in
      `pyproject.toml`, and the README's "MIT" becomes a clickable link to
      `LICENSE`.

- [ ] **Task 112, #158 (P2).** A badge row above the fold: version,
      downloads, licence, supported Python, CI status, matching the reference
      `agigante80/actual-mcp-server` README the ticket names.

- [ ] **Task 113, #319 (P2).** An "Upgrading" section in the README covering
      both install shapes (`uvx` re-resolution and its cache escape hatch;
      `uv tool upgrade hitchrail` plus the required `systemctl --user
      restart hitchrail` for the packaged unit), with `hitchrail --version`
      named as the way to confirm it landed.

- [ ] **Task 114, #141 (P3).** `--port` and the other undocumented flags get
      help text and shown defaults; `--help`'s epilog gets one worked
      example invocation.

- [ ] **Task 115, #17 (P3).** A GitHub Sponsors section and button in the
      README, `https://github.com/sponsors/agigante80`, replacing no other
      funding link since none currently exists.

### `web`: settings moves from the footer into the bar

- [ ] **Task 116, #320 (P2).** The settings link relocated from the footer's
      `.about` line to an icon only gear button in `.bar-actions`, same
      element (`data-settings-link`), same route, `aria-label="Settings"`.
      Verified at the e2e tier's 390px viewport that the bar does not wrap
      and the header's height is unchanged, since that is the exact
      regression #238 was written to avoid for a text button; this is an
      icon, and the ticket does not get to assume the old measurement still
      holds. `tests/e2e/test_settings.py` updated for the new accessible
      name and the new assertion. `index.html`'s comment rewritten to record
      why the decision reversed.

### `web`: creating a project stops being a bar button

- [ ] **Task 117, #321 (P2).** The `data-new` button removed from
      `.bar-actions`; a permanent "create new project" row appended after the
      real rows in `renderList()`, and after the empty state template too, so
      it survives every filter (search, tab, root chip) and the zero-match
      case alike. Same `showNewFolder()` dialog, unchanged. Reverses part of
      #149's "controls that act on the list survive scrolling": the create
      row does not, on a long list, and `index.html`'s new comment records
      why creating is treated differently from the filters #149 named, per
      this repository's rule that a reversed decision writes its reason into
      the code.
      `tests/e2e/test_list.py`'s `test_the_header_costs_no_more_at_rest_and_less_when_scrolled`
      rewritten to stop asserting a bar bounding box for a control that no
      longer lives there, plus a new assertion that the create row is the
      list's last child at every filter state. The other ten `name="New"`
      locators across `test_starting.py`, `test_roots.py`,
      `test_screenshots.py`, `test_shell.py` and `test_stopping.py` updated
      to the row.

- [ ] **Task 118, #322 (P3).** MOVED OUT to #321 if task 117 lands first,
      since the bar button #322 relabels will no longer exist; otherwise the
      button's text becomes "New project" (not "Create New Project": the
      research behind both tickets found that redundant), with the same
      390px no-wrap check task 116 and #320 already carry, and the eleven
      `name="New"` locators updated to `name="New project"`.

### `web`: a way back to following the system

- [ ] **Task 119, #323 (P2).** A Light / Dark / System `role="radiogroup"`
      added to `settings.html`, reusing `settings.js`'s existing `THEME_KEY`
      read on load; picking one applies immediately with no reload and no
      server round trip, unlike the Stopping field's `Save` button, since a
      theme is stored in `localStorage` only. The header toggle's own
      behaviour and markup are untouched; `settings.js`'s file comment
      ("the two things a request may change") updated to name Appearance as
      a third, explicitly non-request change. `tests/e2e/test_settings.py`
      covers each of the three picks, cross page consistency with the header
      toggle in both directions, and the private-window fallback;
      `tests/e2e/test_shell.py`'s two existing theme tests pass unmodified.

## Done looks like

- [ ] Every task above is ticked, or marked MOVED OUT or NOT BUILT with the
      issue number that carries it.
- [ ] #167, #156, #157, #158, #319, #141, #17 and #320 are closed. #321 is
      closed; #322 is closed or is MOVED OUT to #321. #323 is closed.
- [ ] The PyPI page and the README agree: install line, licence statement,
      and what CI reports.
- [ ] The licence is one clickable statement, not four scattered ones.
- [ ] A stranger's bug report can be answered from the journal alone.
- [ ] Settings is reachable from an icon in the bar, not a text link at the
      end of the footer, with no header wrap at 390px.
- [ ] Creating a project is a permanent row at the end of the list, reachable
      under every filter, not a bar button whose word alone did not say what
      it did.
- [ ] Settings offers an explicit Light / Dark / System choice; the header
      toggle's own behaviour is unchanged, and #53's guarantee that an
      explicit choice wins over a later system change still holds.
- [ ] The roadmap's Phase 15 block says `state: done`, the milestone is
      closed, and `scripts/check-phases.sh` passes for this phase.

## Fails if

Written as a premortem on 2026-09-24, with the operator's own answer: it is
the end of this phase and it failed badly; what happened?

**The README got fixed and installs stayed stale anyway.** Every ticket above
lands, the PyPI page and the README agree with each other on paper, and the
phase is marked done, but nobody's actual running install moves, because
correct words are not the same thing as an operator following them on a real
machine. This is the exact failure the phase's own opening ticket, #319, was
filed from: the gap was not that nobody knew a new version existed, it was
that even a person looking directly at the README could not find the two
commands to close it. Rule: task 113's "Upgrading" section is written as
literal, copy-pasteable commands for both install shapes, not prose that
describes the idea of upgrading; and the acceptance criterion for #319
requires naming `hitchrail --version` as the way to confirm the upgrade
actually took, so "did it work" has a mechanical answer instead of a hopeful
one.

## Out of scope

- Any restructuring of `cli.py`, `server.py` or `app.js` beyond what a
  named ticket above asks for: see "What this phase is NOT about".
- A log viewer or streaming logs: Deliberately later, `docs/roadmap.md`.
- Project, local, synced and managed scope plugin work: Phase 21's own out
  of scope, unrelated to this phase.
- A finding from this phase's own review: Backlog, or the next phase.
