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

## Done looks like

- [ ] Every task above is ticked, or marked MOVED OUT or NOT BUILT with the
      issue number that carries it.
- [ ] #167, #156, #157, #158, #319, #141 and #17 are closed.
- [ ] The PyPI page and the README agree: install line, licence statement,
      and what CI reports.
- [ ] The licence is one clickable statement, not four scattered ones.
- [ ] A stranger's bug report can be answered from the journal alone.
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
