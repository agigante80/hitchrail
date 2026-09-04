# Phase 8: Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stranger can install it, understand it, and report a hole in it.

**Architecture:** Almost nothing in `src/` changes. This phase is documentation,
one CI workflow and one systemd unit template. The one code change is whatever
#58 needs to keep the error envelope's documentation honest, and #105's
screenshot capture, which is a test tier addition rather than a product change.

**Tech Stack:** Markdown, GitHub Actions, and the Playwright tier that already
exists. No new runtime dependency; the budget of three is untouched.

**Spec:** `docs/superpowers/specs/2026-08-25-hitchrail-design.md` sections 9
(distribution) and 5 (security, for what SECURITY.md must promise).

---

## Global Constraints

Copied rather than summarised, because a task's requirements implicitly include
this section.

- **Three runtime dependencies:** `starlette`, `uvicorn`, `sse-starlette`. A
  fourth needs a written justification in the pull request.
- **No em dashes or en dashes**, anywhere, including release notes and issue
  bodies. `.claude/no-dashes` enforces it.
- **Every ticket gets a milestone and an area label.** Empty means untriaged.
- **Test the refusals.** A control with only a happy path test is untested.
- **Verify, do not recall.** Anything version dependent gets checked against
  primary sources. This phase is full of them: PyPI's publishing model, systemd
  unit semantics, GitHub's release triggers.
- The engine layer must not import `server`, `cli`, `starlette`, `uvicorn` or
  `sse_starlette`. `uv run lint-imports` enforces it.

## What is already true, measured on 2026-09-04

Recorded so no task re-derives it, and so a reviewer can check the claims.

| | |
|---|---|
| `pypi.org/pypi/hitchrail/json` | 404, the name is free |
| `uv build` | builds an sdist and a wheel |
| the wheel in a clean venv | installs, `hitchrail --version` prints `0.1.0` |
| `web/` inside the wheel | yes, including `fonts/` |
| workflows | `ci.yml`, `release-gate.yml`, `template-lockstep.yml` |
| every `uses:` | pinned to a SHA, asserted by a test (#4) |

The `src/` layout and `web/` living inside the package, both chosen in design
section 9.2 for exactly this, hold up. **The packaging problem for this phase is
publishing, not building.**

## The blocker, and exactly what it blocks

**#106 is not resolved and the repository is public.** Re-verified 2026-09-04:
the pre-rewrite blob is still served by SHA and 40 of 45 private names are
readable in it. Nothing references that commit, so what remains is GitHub's
retention of an unreferenced object, and the documented remedy is a Support
request the owner must file.

**The owner has decided to leave the repository public while Support is asked**,
and that decision is recorded on #106 rather than left implicit.

It blocks **task 29 only**, the PyPI publish and the tagged release, because
those copy content to an index that mirrors and never forgets. Every other task
edits files in a repository that is already public and neither spreads the
unreferenced objects nor makes them easier to find. **Do not reorder task 29
earlier to "get the phase moving".**

## Phase 8 tickets, in dependency order

| Task | Tickets | Why here |
|---|---|---|
| 24 | #59, #61, #60 | the "report a hole" half of the objective, and nothing depends on it |
| 25 | #58, #62 | two documents that are wrong about the code today |
| 26 | #105 | screenshots, which the README then uses |
| 27 | #17, README assembly | needs 24 to 26 to link to |
| 28 | #110 | the unit and the phone access document; needs the README shape from 27 |
| 29 | #116 | the publish. **Gated on #106.** |

#106 itself is owner action and appears in no task.

---

### Task 24: Somewhere to report a hole, and rules a stranger can read

**Tickets:** #59, #61, #60

The objective's third verb. Today a person who finds a hole in the token check
has nowhere to send it, and a contributor discovers the expectations by having
work rejected.

- [ ] `SECURITY.md`, per #59. It states what is in scope, what is explicitly
      not, and how to report privately. **Enable GitHub private vulnerability
      reporting** rather than publishing an email address, and say so in the
      file.
- [ ] It must be honest about the threat model rather than reassuring. Design
      section 5.3 and the README already say Hitchrail does not sandbox what it
      starts, that the token buys keystrokes into agents (#91), and that plain
      HTTP on a LAN carries the cookie in clear. A security policy that omits
      these is worse than none: it invites reports about the documented design
      and buries the real surface.
- [ ] `CONTRIBUTING.md`, per #61: the five gates, the three test tiers, the
      ticket standard, conventional commits, the dash rule.
- [ ] #60 is the load bearing half. **The conventions live in `.claude/CLAUDE.md`,
      which is not published**, so a human contributor and a non Claude agent
      cannot read them. Decide what moves into `CONTRIBUTING.md` and what stays,
      and make one the source with the other pointing at it. Two copies drift,
      which is the argument `docs/guides/ticket-standards.md` already makes.
- [ ] `tests/test_docs_are_true.py` gains a guard for whichever direction is
      chosen, so the copy cannot silently diverge.

**Verify:** read `CONTRIBUTING.md` as somebody who has never seen the project
and check that every command in it runs. A rule nobody can execute is prose.

---

### Task 25: Two documents that currently contradict the code

**Tickets:** #58, #62

- [ ] #58: the API's error envelope is documented only inside a closed phase's
      plan. Move it to where somebody integrating would look, and keep the
      existing guard: `test_the_spec_documents_every_code_the_server_can_return`
      and its inverse already assert both directions, so the new home must be
      what those tests read.
- [ ] #62: `docs/versioning.md` defines semver as an operator contract and
      nothing reports against it. Decide what "reporting" is: at minimum the
      release notes must name the level and why, and the `release-gate` workflow
      already knows the comparison.
- [ ] **State the two contract changes already in the backlog for the first
      release:** #108 made a token mandatory for a declared remote reach, and
      #115 removed the `?token=` carrier. Both are breaking, both ship as MINOR
      under the `0.y.z` rule, and the first published release notes are where an
      operator learns that.

---

### Task 26: Screenshots taken by a machine

**Ticket:** #105

- [ ] Capture from the Playwright tier that already exists, on a phone viewport
      and a desktop one, into a committed directory.
- [ ] **Regenerate only on a release**, which is what the owner asked for when
      #105 was discussed: a screenshot that changes on every push is a diff
      nobody reads.
- [ ] The fixtures must use the fake agent shim and a temporary root. A
      screenshot is a published artefact, so a real project name in one is the
      #106 failure with a different door.
- [ ] Assert the images are non trivial: a blank page screenshots fine.

---

### Task 27: The README a stranger can follow

**Ticket:** #17, plus assembly

- [ ] The objective says the security section comes **first, after learning what
      the tool does**. Reorder to match: what it is, what it costs you to run
      it, then how to run it.
- [ ] Fold in the screenshots from task 26 and link the documents from task 24.
- [ ] #17, the Sponsors link, last, because it is the least load bearing thing
      in the file and it is where it will read as least important.
- [ ] The Install section currently says "Not yet". It stays wrong until task 29
      and must be corrected in the same change that makes it true, never before.

---

### Task 28: It dies when you close the terminal

**Ticket:** #110

- [ ] The systemd **user** unit template, `Restart=on-failure`, and
      `loginctl enable-linger` documented rather than performed.
- [ ] `EnvironmentFile` at mode 600 holding `HITCHRAIL_TOKEN`, which #109 built
      and which is what makes the link on a phone survive a restart.
- [ ] The phone access document, ordered overlay first, named interface second,
      wildcard never, each with its exposure stated.
- [ ] **Decide the journal question #109 handed over**: the banner writes the
      grant link, token included, to stdout, which under a unit is journald and
      therefore a stable secret in a persistent log. Decide it with the unit in
      hand and write the answer down.
- [ ] `uv tool install`, not `uvx`, and say why: `uvx` is deliberately
      ephemeral and a unit needs a stable path. That instruction is only true
      after task 29.

---

### Task 29: The publish. Gated on #106

**Ticket:** #116

- [ ] Trusted publishing via OIDC, no stored credential. `id-token: write` and
      nothing else.
- [ ] Triggered by a published GitHub release, never by a tag push.
- [ ] A `release` environment with the owner as a required reviewer.
- [ ] **TestPyPI first**, installed from that index into a clean container. A
      version number on PyPI cannot be reused, so the first real upload must not
      be the first install from an index.
- [ ] `test_no_workflow_holds_a_publish_password`, because the argument above is
      worth a guard.
- [ ] **Confirm #106 first**, by the API call in that ticket returning 404. Not
      by the ticket being closed: check the thing itself.

---

## Phase 8 exit criteria

Ticked only with evidence, per the roadmap's own rule.

- [ ] `uvx hitchrail --root <folder>` works on a machine that has never seen
      this repository, with the transcript recorded on #116.
- [ ] The security section is the first thing a reader meets after learning what
      the tool does.
- [ ] A hole in the token check has a private channel to be reported through,
      and `SECURITY.md` names what is in scope and what is a documented design
      choice.
- [ ] A contributor can find the conventions without reading `.claude/`.
- [ ] The error envelope is documented where an integrator would look, and the
      existing guards read that document.
- [ ] The first release notes name both breaking changes and the level chosen.
- [ ] Screenshots in the README were produced by a machine, from a fake root.
- [ ] Hitchrail survives closing the terminal, and the link on a phone survives
      a restart.
- [ ] No workflow holds a publish credential, asserted.
- [ ] **#106 returns 404 before anything is published.**

## What would make this phase a failure

Stated because the failure mode here is different from every previous phase.
Phases 1 to 7 could be wrong in private. This one is the first that is wrong in
public, and two of its steps cannot be taken back: a published version and a
name on an index.

- Publishing before #106 returns 404.
- A README that reads as marketing. The tool spawns agents with permissions
  skipped; the honest description of that IS the pitch.
- A `SECURITY.md` that promises a response time nobody will meet.
- Screenshots containing a real project name.
