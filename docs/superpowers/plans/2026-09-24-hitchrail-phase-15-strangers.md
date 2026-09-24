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

**A fifth was added the same day, from the operator's own direction rather
than a gap found in passing.** #324 puts the app's own mark, #160's drawing,
in front of the `hitchrail` heading on every page that carries one; today it
only ever appears as a favicon. Researched first: an icon before a wordmark
at the header's leading edge is the standard lockup, and the accepted
accessible pattern for a mark that duplicates visible text is an inlined,
`aria-hidden` SVG on CSS custom properties rather than an `<img>`, which this
codebase's own badge glyphs already do. Reading `logs.js` found a real
constraint rather than a style choice: its heading carries `data-title` and
is overwritten wholesale on load, so the mark has to sit beside that element,
not inside it, or that page alone would lose it the instant its own script
ran. The same comparison also found `icon.svg`'s own dark mode accent colour
never moved when #69 unified `--accent` across themes on 2026-09-11, since
that retune was scoped to `app.css` and never touched the standalone file;
task 120 corrects it in the same pass, since this ticket is already reading
and duplicating that file's colours.

**A sixth and seventh were added the same day, both checked against the
running code before being filed.** The operator asked to use the app's icon
as the website favicon; reading all four pages, the manifest and #160 found
that already shipped, so no duplicate ticket was filed for it. What that
reading did turn up is a real, separate gap: `/favicon.ico`, the path a
browser asks for on its own regardless of any `<link rel="icon">` tag, is
neither a route in `pages.ASSETS` nor a member of
`security.UNAUTHENTICATED_ASSETS`, so `TokenMiddleware` answers every
browser's implicit probe with a 401. #325 files that gap alone, aliasing the
existing `icon.svg` bytes rather than shipping a second binary asset. The
operator's second ask, a CLI startup banner naming the service, its version
and where it lives, found the opposite: `cli.py`'s only existing banner
(`banner()`) is entirely about the token grant link and prints nothing on a
normal start. Researched first, and grounded in a real constraint already
in the file: the new banner in #326 is a second, always printed function,
never a change to `banner()`'s own tested silence on loopback, and it has to
print before `build_config()` so it still appears when a later config,
preflight or gateway check refuses to start, exactly the case a stranger's
bug report needs it most.

**An eighth was added the same day, for the README rewrite this phase
already carries.** The operator asked for a section explaining, in concrete
scenarios, why a stranger would install this at all, distinct from the
feature summary `## What it will do` already gives and from the badge,
install-line and upgrade tickets already in this phase, none of which
answer "is this for me". Researched first: current README guidance
converges on a reader asking three questions in order, what is this, is it
for me, how do I start, and answers the second with a small number of
concrete, project specific scenarios rather than a generic use-case list.
#327 draws its scenarios from behaviour the README already documents
elsewhere (the phone interface, the four derived states, the memory floors,
multiple roots), so the new section restates and frames rather than
introduces a claim nothing else backs.

**A ninth was added the same day, from the operator reading the project's
own tagline back to itself.** The GitHub About field and `pyproject.toml`'s
`description`, identical strings, both say "from your phone" and never say
"web," so a reader who sees only that one line, GitHub search results or
the PyPI page, before ever opening the README, has no way to tell this
apart from a native phone app. `README.md`'s own opening sentence already
gets this right ("A web UI for..."), so #328 brings the other two in line
with it rather than inventing new copy; the phone-first design priority
itself is untouched, since that is a deliberate, already argued and already
tested decision this ticket was never asked to reopen. Checking
`.claude/CLAUDE.md` as part of the same review found it already correct
("Hitchrail is a web UI for... Phone first"), so the omission is confined
to the two surfaces #328 fixes, not a third.

**A tenth was added the same day, from the operator asking to take new
screenshots for the README rewrite this phase already carries.** Checked
first whether the scripted capture the operator remembered still exists:
it does, `tests/e2e/test_screenshots.py` behind `uv run pytest -m
screenshots`, already seeding every image from demo data (all four derived
states, two roots, a dark theme toggle) rather than a real machine, so
there was nothing to build from scratch. What the review found instead:
the committed images stop at commit `ad15337`, 2026-09-11, while twenty-odd
commits since then changed `src/hitchrail/web/`, including the settings
page itself, and the settings page has never been captured at all despite
being documented prose twice in the README (the "Settings, from the phone"
paragraph and the plugin-update section). Three of the seven images the
tier already produces, `phone-grant.png`, `phone-logs.png` and
`phone-new-folder.png`, are not referenced anywhere in the current
README, either. #329 regenerates the set as part of this phase's rewrite,
adds one capture test for the settings page mid plugin update, reusing the
fake-agent seam `tests/e2e/test_plugins.py` already built, and confirms
every image the tier produces is used somewhere in the rewritten README.

**An eleventh was added the same day, from the operator asking that the
roadmap be linked from the README.** Checked first: it already is, twice,
in the intro paragraph (`README.md:18-25`), more prominently than most
repos manage. What is missing is the second, scannable place a reader
looks: the `## Documents` table (`README.md:517-524`) indexes every other
doc, `docs/api.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`,
`docs/releasing.md`, but not `docs/roadmap.md`. Researched first: current
guidance wants a roadmap findable in a dedicated, scannable place, usually
a `## Roadmap` heading with a checklist mirroring the roadmap's phase
states; rejected here on the same grounds `README.md:18-19` already states
out loud, that a phase checklist in the README goes stale the way "phases 0
to 6" once did, and `tests/test_docs_are_true.py` exists to catch exactly
that. #330 adds the one missing row to the table this project already has
for this purpose instead, duplicating no state.

**A twelfth was added the same day, from the operator asking for the
reference README's centred icon, title and badge row, plus a one line
description reused across the app.** #158 already carried this phase's
badge row research and two explicit decisions against exactly this: "left,
not centred" and "an icon is out of scope." Both were correct when written
and are not now: the icon they said did not exist yet shipped as #160 and
is already used, uncentred, at `README.md:1`, and the centring request now
has a second source, the operator who wrote the reference README asking
directly for the same treatment here. #158 was rewritten in place rather
than superseded by a new ticket, with the reversal and its reasoning
written into the ticket body, and now also proposes the centred, bold one
line description the reference uses beneath its badges, with several
worded candidates rather than one guess, chosen so it can be the same
string #328 ships for `pyproject.toml`, #326 ships for the CLI banner, and
the fourth surface named directly, page metadata. That fourth surface had
no ticket: `index.html` and `settings.html` have no `<meta
name="description">` and no Open Graph tags at all, so a shared link or a
search result shows a bare title today. #331 adds it, reusing whichever
wording #158 settles on rather than inventing a fifth string.

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

- [ ] **Task 125, #329 (P1).** `tests/e2e/test_screenshots.py` gains a
      capture of the settings page mid plugin update, seeded through
      `Harness.seed_plugins`/`release_plugin` the way `tests/e2e/test_plugins.py`
      already does, and all seven images are regenerated via `uv run pytest
      -m screenshots` after this phase's README markup changes land, not
      before. Every image the tier produces ends up referenced somewhere in
      `README.md`; three currently are not.

- [ ] **Task 110, #156 (P2).** The README gets a `pip install hitchrail` line
      next to `uvx`, matching what PyPI's own project page already shows.

- [ ] **Task 111, #157 (P2).** The deprecated PyPI licence classifier is
      dropped in favour of the SPDX expression already correct in
      `pyproject.toml`, and the README's "MIT" becomes a clickable link to
      `LICENSE`.

- [ ] **Task 112, #158 (P2).** A centred icon and title, a badge row above
      the fold (version, downloads, licence, supported Python, CI status),
      and a centred, bold one line description beneath it, matching the
      reference `agigante80/actual-mcp-server` README the ticket names.
      Reverses #158's own earlier "left, not centred" and "icon is out of
      scope" decisions, with the reversal's reasoning written into the
      ticket.

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

- [ ] **Task 124, #328 (P2).** `pyproject.toml`'s `description` (also
      PyPI's summary) and the GitHub repo's About field, both currently
      "from your phone" with no mention of "web," changed to name it as a
      web UI, proposed wording "from a phone-first web UI," matching what
      `README.md`'s own opening sentence already gets right and this
      project's own established "phone," not "mobile," vocabulary. No
      change to the phone-first design priority itself. Interacts with
      task 122/#326, which quotes the pre-fix string as its reconciliation
      target: whichever of the two ships second reads the other's final
      wording.

- [ ] **Task 123, #327 (P2).** A `## Why you'd use this` section added
      between `## What it will do` and `## What it looks like`, three to
      four concrete scenarios (checking on or stopping a session from a
      phone with no shell; telling apart the four derived states so a
      `detached` agent is not mistaken for `stopped`; the memory floors
      refusing a start that would exhaust the machine; two roots kept
      apart by a chip), each naming a behaviour the README already
      documents elsewhere rather than a new claim.

- [ ] **Task 126, #330 (P3).** `docs/roadmap.md` added as a row to the
      `## Documents` table (`README.md:517-524`), alongside `docs/api.md`,
      `CHANGELOG.md` and the rest. The two existing inline links in the
      intro paragraph are unchanged; no phase state duplicated into the
      README.

- [ ] **Task 127, #331 (P2).** `<meta name="description">` and
      `og:title`/`og:description` added to `index.html` and `settings.html`,
      reusing whichever one line description task 112/#158 settles on for
      the README's centred tagline. `grant.html` and `logs.html` excluded:
      the former is compared byte for byte against disk by an existing test
      and names nothing on the machine on purpose, the latter is never a
      stranger's first, cold visit.

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

### `web`: the mark appears in the header, not only as a favicon

- [ ] **Task 120, #324 (P3).** The app's mark (`icon.svg`, #160) inlined as
      static SVG, immediately before the `hitchrail` heading, in a new
      `.bar-title-row` wrapper on `index.html`, `settings.html` and
      `logs.html`; `grant.html` is out of scope, since it has no `.bar`
      header and is byte compared against disk by
      `test_the_grant_page_names_nothing_on_the_machine`. The inlined copy's
      fills are `var(--ink)`/`var(--accent)`, not the standalone file's own
      hardcoded colours and media query, so it follows the page's
      `[data-theme]` override the way a favicon cannot. `aria-hidden="true"`,
      since the adjacent heading already says "hitchrail". Placed beside the
      `<h1>`, not inside it: `logs.html`'s heading carries `data-title` and
      is overwritten wholesale by `logs.js:32` on load, so a child node there
      would be lost the instant that page's own script ran. `icon.svg`'s own
      dark mode `.live` fill, stale since #69's 2026-09-11 retune touched
      only `app.css`, is corrected in the same pass to match the current
      `--accent` value. `tests/e2e/test_shell.py` covers the mark's presence,
      its theme tracking, the unaffected heading accessible name, and the
      unchanged 390px bar width on all three pages.

### `security`, `web`: the implicit favicon probe stops being a 401

- [ ] **Task 121, #325 (P3).** `/favicon.ico` added to `pages.ASSETS`,
      aliasing the existing `icon.svg` bytes under `image/svg+xml` rather
      than shipping a new binary asset, and added to
      `security.UNAUTHENTICATED_ASSETS`, widening that set's comment from
      four files to five with the reason written beside it. `tests/
      test_security_token.py`'s pinned frozenset and `tests/test_api.py`'s
      `test_the_mark_and_the_manifest_are_served_without_a_token`
      parametrization both gain the new path; the existing full route sweep
      picks it up automatically through `UNAUTHENTICATED_ASSETS`
      membership, with no separate change.

### `cli`: a startup banner names the service

- [ ] **Task 122, #326 (P2).** A new `identity_banner()` in `cli.py`,
      separate from and never touching `banner()`'s own tested silence on
      loopback, printing the name, `pyproject.toml`'s one line description,
      `__version__` and the GitHub link, unconditionally, with `flush=True`
      per the `#145` journal-buffering footgun `banner()` itself already
      documents. Called in `main()` right after `parse_args()` succeeds and
      before `build_config()`, so it still appears when a later config,
      preflight or gateway check fails, and is skipped entirely on the
      `update-plugins` one shot path. `cli.py:53`'s argparse `description=`
      corrected in the same pass to match `pyproject.toml`'s wording, which
      the new banner also reuses. `tests/test_cli.py` covers a normal start,
      a start that fails after the banner, the `update-plugins` exclusion,
      and the journal-buffering case, following the existing
      `BlockBuffered` pattern.

## Done looks like

- [ ] Every task above is ticked, or marked MOVED OUT or NOT BUILT with the
      issue number that carries it.
- [ ] #167, #156, #157, #158, #319, #141, #17 and #320 are closed. #321 is
      closed; #322 is closed or is MOVED OUT to #321. #323 is closed. #324 is
      closed. #325 is closed. #326 is closed. #327 is closed. #328 is closed.
      #329 is closed. #330 is closed. #331 is closed.
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
- [ ] The app's mark sits in front of the `hitchrail` heading on every page
      that has one, tracks the page's theme the way the rest of it does, and
      the heading's accessible name is unchanged.
- [ ] `/favicon.ico` answers 200 with the app's mark, not a 401, with no
      token presented.
- [ ] A normal `hitchrail` start prints the name, version and GitHub link
      before the server starts, even when a later check refuses to start;
      `update-plugins` and `--help`/`--version` are unaffected.
- [ ] The README answers "is this for me" with concrete scenarios before it
      shows a single screenshot.
- [ ] Every screenshot in `docs/screenshots/` is captured against the
      rewritten interface, is referenced somewhere in `README.md`, and the
      settings page mid plugin update has a picture for the first time.
- [ ] The GitHub About field and PyPI's summary both say "web UI," not only
      "from your phone"; the phone-first design priority is unchanged.
- [ ] `docs/roadmap.md` is a row in the `## Documents` table, not only in
      the intro paragraph.
- [ ] The README's icon, title, badge row and one line description are
      centred, matching the reference README, with the left-aligned body
      prose below them unchanged.
- [ ] `index.html` and `settings.html` carry a meta description and Open
      Graph tags, reusing the same one line description the README, the
      GitHub About field, PyPI's summary and the CLI banner all use.
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
