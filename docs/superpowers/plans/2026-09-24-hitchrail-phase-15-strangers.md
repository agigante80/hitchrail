# Phase 15: The package as strangers meet it

**Objective: somebody who has never seen this project can install it, tell
what it is, and see that it is maintained.** Narrowed on 2026-09-26: being
helped when it goes wrong, the logging ticket, moved to Phase 19.

## Goal

The PyPI page and the README agree with each other and with what `--help`
actually prints. A stranger's first two seconds on the README answer whether
the project is published, maintained and licensed; their first `pip install`
or `uvx` run works from the line PyPI itself shows.

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

**A thirteenth changed the phase's own shape rather than adding a ticket.**
Re-reading this file, the operator asked whether PyPI publishing was a
future decision, since the roadmap's own Phase 15 prose already says "the
published PyPI page." Checked directly against PyPI's own JSON API for this
project: twelve releases exist, most recently 0.10.0, published through the
trusted-publishing pipeline `docs/releasing.md` already documents. Publishing is not a decision left to make; the README already is
the PyPI page, so there is no second, separable "PyPI phase" to split this
one into. The operator also asked whether the Linux-only constraint was an
untested hedge; `git log -S "POSIX :: Linux" -- pyproject.toml` shows it was
a deliberate, dated decision from the same day as the design spec, tied to
`/proc/meminfo` and `ps`, and the README's Prerequisites table already states
the reason. Neither needed a ticket. What the same re-reading did surface,
checked against the file rather than recalled: the README's `## Install`
section is the hardest of three install mentions to reach, 475 lines in,
after the entire systemd walkthrough, and repeats its own `uv tool install`
versus `uvx` reasoning in two adjacent paragraphs. #332 carries that,
folded into the same `docs`, `packaging`, `cli` work already listed. The
operator's actual ask, once the PyPI premise was corrected, was narrower
than a split: keep this phase for what a stranger meets before and during
install, and move out what a stranger only meets once the app is already
running. Tasks 116 to 121, #320 to #325 (the bar's settings icon, the
project creation row, the Light/Dark/System choice, the header mark, and
the favicon route) are in-app UI a stranger reaches only after installing
and signing in; none of them changes what the PyPI page, the README or
`--help` say. Moved to the existing Backlog milestone rather than a new
phase, the same move `docs/roadmap.md` itself already describes for Phase
10, "sixteen tickets to thirty nine... narrowed to escape it": Backlog is
where a real, already-triaged ticket waits for a phase, not an invented
extra phase, and every guard this file is checked against still holds with
Phase 15 open and Backlog the one phase already carrying that state.

## What this phase is NOT about

**A redesign of anything this phase's tickets touch.** Every ticket here is a
specific, already-argued fix: a missing line, a stale classifier, a badge
row, a help string, a log handler. None of them is licence to restructure
`cli.py`'s banner, rewrite `server.py`'s routes, or invent a logging
framework beyond what #167 actually asks for. That restraint is the point:
the premortem below is exactly about this phase absorbing more than its
tickets, the way Phase 10 once did before it was narrowed to escape it.

**Splitting `app.js` or `server.py`.** Phase 24 and Phase 16, since Phase 18
was deleted on 2026-09-26.

**The stop sequence.** Phase 19.

**Streaming logs, or a log viewer.** Not asked for; #167 is about the daemon
producing a usable journal, not shipping a viewer.

## Expected work

No task here depends on another; they touch disjoint files and ship in any
order. Listed by priority.

### `docs`, `packaging`, `cli`: the README and PyPI agree with each other

- [ ] **Task 109, #167 (P1).** MOVED OUT to Phase 19, #167, on 2026-09-26:
      its stop sequence is the first thing that needs the journal to answer
      a question, so the handler is built and watched there. A real logging
      handler, level and timestamp for the daemon, so "was the stop request sent" and "did the plugin
      update run" have an answer in the journal on a machine nobody here has
      seen. `tests/test_cli.py` or a new `tests/test_logging.py` per the
      ticket's own unit test specs.

- [x] **Task 125, #329 (P1).** `tests/e2e/test_screenshots.py` gained
      `test_capture_the_settings_page_after_a_plugin_update`, seeded through
      `Harness.seed_plugins`/`release_plugin` the way `tests/e2e/test_plugins.py`
      already does, producing `phone-settings-plugins.png`. All eight images
      (the original seven plus this one) were regenerated via `uv run pytest
      -m screenshots` after this phase's README markup changes had landed.
      `phone-grant.png`, `phone-logs.png` and `phone-new-folder.png`, the
      three that shipped with no README reference, are now shown in
      `## What it looks like`; the new capture is shown beside "Settings,
      from the phone". `tests/test_docs_are_true.py` gained
      `test_every_committed_shot_is_referenced_in_the_readme`, which fails on
      exactly the three-orphan state this ticket found.

- [x] **Task 110, #156 (P2).** The README gets a `pip install hitchrail` line
      next to `uvx`, matching what PyPI's own project page already shows.

- [x] **Task 111, #157 (P2).** The deprecated PyPI licence classifier is
      dropped in favour of the SPDX expression already correct in
      `pyproject.toml`, and the README's "MIT" becomes a clickable link to
      `LICENSE`.

- [x] **Task 112, #158 (P2).** A centred icon and title, a badge row above
      the fold (version, downloads, licence, supported Python, CI status),
      and a centred, bold one line description beneath it, matching the
      reference `agigante80/actual-mcp-server` README the ticket names.
      Reverses #158's own earlier "left, not centred" and "icon is out of
      scope" decisions, with the reversal's reasoning written into the
      ticket.

- [x] **Task 113, #319 (P2).** An "Upgrading" section in the README covering
      both install shapes (`uvx` re-resolution and its cache escape hatch;
      `uv tool upgrade hitchrail` plus the required `systemctl --user
      restart hitchrail` for the packaged unit), with `hitchrail --version`
      named as the way to confirm it landed.

- [x] **Task 128, #332 (P2).** ALREADY TRUE, checked 2026-09-26: `fe88990`
      (2026-09-05, before this ticket was filed) already put `## Install`
      directly after `## What it costs you to run this` and before
      `## Prerequisites`, and already folds the `uv tool install` versus
      `uvx` point into one paragraph naming both `packaging/hitchrail.service`
      and its `ExecStart`'s `~/.local/bin/hitchrail`, not two. Every
      acceptance criterion in #332 holds against the current README with no
      further edit; `test_the_readme_states_the_risk_before_the_instructions`
      still passes.

- [x] **Task 114, #141 (P3).** `--port` and the other undocumented flags get
      help text and shown defaults; `--help`'s epilog gets one worked
      example invocation.

- [ ] **Task 115, #17 (P3).** MOVED OUT to Backlog, #17, on 2026-09-26:
      nothing a stranger needs to install or trust the package waits on it.
      A GitHub Sponsors section and button in the
      README, `https://github.com/sponsors/agigante80`, replacing no other
      funding link since none currently exists.

- [x] **Task 124, #328 (P2).** `pyproject.toml`'s `description` (also
      PyPI's summary) and the GitHub repo's About field, both currently
      "from your phone" with no mention of "web," changed to name it as a
      web UI, proposed wording "from a phone-first web UI," matching what
      `README.md`'s own opening sentence already gets right and this
      project's own established "phone," not "mobile," vocabulary. No
      change to the phone-first design priority itself. Interacts with
      task 122/#326, which quotes the pre-fix string as its reconciliation
      target: whichever of the two ships second reads the other's final
      wording.

- [x] **Task 123, #327 (P2).** A `## Why you'd use this` section added
      between `## What it will do` and `## What it looks like`, three to
      four concrete scenarios (checking on or stopping a session from a
      phone with no shell; telling apart the four derived states so a
      `detached` agent is not mistaken for `stopped`; the memory floors
      refusing a start that would exhaust the machine; two roots kept
      apart by a chip), each naming a behaviour the README already
      documents elsewhere rather than a new claim.

- [x] **Task 126, #330 (P3).** `docs/roadmap.md` added as a row to the
      `## Documents` table (`README.md:517-524`), alongside `docs/api.md`,
      `CHANGELOG.md` and the rest. The two existing inline links in the
      intro paragraph are unchanged; no phase state duplicated into the
      README.

- [x] **Task 127, #331 (P2).** `<meta name="description">` and
      `og:title`/`og:description` added to `index.html` and `settings.html`,
      reusing whichever one line description task 112/#158 settles on for
      the README's centred tagline. `grant.html` and `logs.html` excluded:
      the former is compared byte for byte against disk by an existing test
      and names nothing on the machine on purpose, the latter is never a
      stranger's first, cold visit.

### `web`: the bar and settings rearrangement, moved out

None of these five is about what a stranger meets before or during install;
each is in-app UI reached only after installing and signing in, the
distinction the thirteenth paragraph above draws. Moved to the Backlog
milestone on 2026-09-24, and from there to Phase 24 on 2026-09-26; each ticket's own body is unchanged and carries its
full implementation detail, not duplicated here.

- [ ] **Task 116, #320 (P2).** MOVED OUT to Phase 24, #320: settings
      relocated from the footer into a gear icon in `.bar-actions`.

- [ ] **Task 117, #321 (P2).** MOVED OUT to Phase 24, #321: the bar's `New`
      button replaced by a permanent create-project row in the list.

- [ ] **Task 118, #322 (P3).** MOVED OUT to Phase 24, #322: the `New`
      button's label clarified, moot if #321 lands first.

- [ ] **Task 119, #323 (P2).** MOVED OUT to Phase 24, #323: a Light / Dark /
      System choice added to settings.

- [ ] **Task 120, #324 (P3).** MOVED OUT to Phase 24, #324: the app's mark
      inlined in the header, not only as a favicon.

- [ ] **Task 121, #325 (P3).** MOVED OUT to Phase 24, #325: `/favicon.ico`
      added to the unauthenticated asset set instead of answering 401.

- [ ] **Task 129, #333 (P3).** MOVED OUT to Phase 24, #333, on 2026-09-26:
      the `hitchrail` heading made a link back to the project list. Filed
      into this milestone after the narrowing above and in-app for the same
      reason, so it follows #324, which edits the same heading.

### `cli`: a startup banner names the service

- [x] **Task 122, #326 (P2).** A new `identity_banner()` in `cli.py`,
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
- [ ] #156, #157, #158, #319, #141 and #332 are closed. #326 is
      closed. #327 is closed. #328 is closed. #329 is closed. #330 is
      closed. #331 is closed. #320 to #325 and #333 are MOVED OUT to Phase 24, #167 to
      Phase 19 and #17 to Backlog, and are no longer this phase's to close.
- [ ] The PyPI page and the README agree: install line, licence statement,
      and what CI reports.
- [ ] The licence is one clickable statement, not four scattered ones.
- [ ] `## Install` is the first heading reached after the risk section, not
      one of three scattered install mentions 475 lines in, and states the
      `uv tool install` versus `uvx` distinction once, not twice.
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
