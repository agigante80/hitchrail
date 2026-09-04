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

## The exposure this phase was gated on, and why it no longer gates it

**#106 is closed, by decision, and nothing in this phase waits on it.** Written
here rather than deleted, because the plan was drafted around it and a reader
who finds the closed ticket deserves to know the gate was lifted deliberately.

What it described is still true. The pre-rewrite objects are served by SHA until
the host collects them, and 40 of 45 private names were readable in one of them
on 2026-09-04. Nothing references that commit, so the remedy is a support
request rather than garbage collection, and one has been sent.

The owner decided not to wait. **That is a risk accepted, not a problem solved**,
and the reasoning is on the ticket. Publishing does not copy git history to an
index, so the publish does not spread those objects; it raises the project's
profile, which raises the chance somebody looks.

The plan's original exit criterion, that the API call return 404 before anything
is published, is therefore **withdrawn rather than left unsatisfiable**. A plan
that cannot be finished is worse than one that states its risk.

**What this does not change:** screenshots and fixtures still must not carry a
real project name. That is #106's failure through a different door and it is a
requirement of task 26, not of this section.

## Phase 8 tickets, in dependency order

| Task | Tickets | Why here |
|---|---|---|
| 24 | #59, #61, #60 | the "report a hole" half of the objective, and nothing depends on it |
| 25 | #58, #62 | two documents that are wrong about the code today |
| 26 | #105 | screenshots, which the README then uses |
| 27 | #117 | the README's order, which is an exit criterion. Needs 24 to 26 to link to |
| 28 | #116 | the publish |
| 29 | #110 | the unit and the phone access document, which needs the publish to be real |

**Two corrections on 2026-09-04, both found by reading the exit criteria against
the ticket list rather than the list against itself.**

#117 was filed because "the security section is the first thing a reader meets"
was owned by no ticket. Task 27 previously read "README assembly", which is a
task line standing in for a ticket that did not exist. That is the same gap that
produced #116, twice in one phase, and it is worth naming as a pattern: an exit
criterion nobody ticketed is invisible to every ticket based check.

**#110 and #116 are swapped.** #110's own Depends On names "the PyPI publish,
for `uv tool install` to be a real instruction", which was scheduled after it.
It is the only ticket here that depends on another in the same phase.

#17, the funding link, moved to Backlog. The objective is install, understand,
report; a sponsor button is none of them, and it was in the phase because it
touches the README rather than because it serves the goal.

---

### Task 24: Somewhere to report a hole, and rules a stranger can read

**Tickets:** #59, #61, #60

The objective's third verb. Today a person who finds a hole in the token check
has nowhere to send it, and a contributor discovers the expectations by having
work rejected.

- [x] `SECURITY.md`, per #59. It states what is in scope, what is explicitly
      not, and how to report privately. **Enable GitHub private vulnerability
      reporting** rather than publishing an email address, and say so in the
      file.
- [x] It must be honest about the threat model rather than reassuring. Design
      section 5.3 and the README already say Hitchrail does not sandbox what it
      starts, that the token buys keystrokes into agents (#91), and that plain
      HTTP on a LAN carries the cookie in clear. A security policy that omits
      these is worse than none: it invites reports about the documented design
      and buries the real surface.
- [x] `CONTRIBUTING.md`, per #61: the five gates, the three test tiers, the
      ticket standard, conventional commits, the dash rule.
- [x] #60 is the load bearing half. **The conventions live in `.claude/CLAUDE.md`,
      which is not published**, so a human contributor and a non Claude agent
      cannot read them. Decide what moves into `CONTRIBUTING.md` and what stays,
      and make one the source with the other pointing at it. Two copies drift,
      which is the argument `docs/guides/ticket-standards.md` already makes.
- [x] `tests/test_docs_are_true.py` gains a guard for whichever direction is
      chosen, so the copy cannot silently diverge.

**Verify:** read `CONTRIBUTING.md` as somebody who has never seen the project
and check that every command in it runs. A rule nobody can execute is prose.

---

### Task 25: Two documents that currently contradict the code

**Tickets:** #58, #62

- [x] #58: the API's error envelope is documented only inside a closed phase's
      plan. Move it to where somebody integrating would look, and keep the
      existing guard: `test_the_spec_documents_every_code_the_server_can_return`
      and its inverse already assert both directions, so the new home must be
      what those tests read.
- [x] #62: `docs/versioning.md` defines semver as an operator contract and
      nothing reports against it. Decide what "reporting" is: at minimum the
      release notes must name the level and why, and the `release-gate` workflow
      already knows the comparison.
- [x] **State the two contract changes already in the backlog for the first
      release:** #108 made a token mandatory for a declared remote reach, and
      #115 removed the `?token=` carrier. Both are breaking, both ship as MINOR
      under the `0.y.z` rule, and the first published release notes are where an
      operator learns that.

---

### Task 26: Screenshots taken by a machine

**Ticket:** #105

- [x] Capture from the Playwright tier that already exists, on a phone viewport
      and a desktop one, into a committed directory.
- [x] **Regenerate only on a release**, which is what the owner asked for when
      #105 was discussed: a screenshot that changes on every push is a diff
      nobody reads.
- [x] The fixtures must use the fake agent shim and a temporary root. A
      screenshot is a published artefact, so a real project name in one is the
      #106 failure with a different door.
- [x] Assert the images are non trivial: a blank page screenshots fine.

---

### Task 27: The README tells you the cost before the instructions

**Ticket:** #117

- [x] Move the security material above `## Run it`, directly after `## What it
      will do`. The objective says the security section comes first, after
      learning what the tool does, and the file currently puts install, run and
      contribution notes ahead of it.
- [x] **Do not soften it while moving it.** Four claims are stated plainly
      today: no sandboxing, the token buys keystrokes into agents, a detached
      agent cannot be ended, cleartext on plain HTTP. A section promoted to the
      top is one somebody will later want to make friendlier.
- [x] Link `SECURITY.md` from it, once task 24 has written it.
- [x] Fold in the screenshots from task 26 where they help, which is
      `## What it will do` rather than here.
- [x] Two guards in `tests/test_docs_are_true.py`: the security heading precedes
      `## Run it` positionally, and each of the four claims is still present.
      Verify both by mutation, per #35.
- [ ] The Install section says "Not yet". It stays wrong until task 28 and is
      corrected in the same change that makes it true.

### Task 28: The publish

**Ticket:** #116

- [x] Trusted publishing via OIDC, no stored credential. `id-token: write` and
      nothing else.
- [x] Triggered by a published GitHub release, never by a tag push.
- [ ] A `release` environment with the owner as a required reviewer.
- [ ] **TestPyPI first**, installed from that index into a clean container. A
      version number on PyPI cannot be reused, so the first real upload must not
      be the first install from an index.
- [x] `test_no_workflow_holds_a_publish_credential`, because the argument above is
      worth a guard.
- [x] **No longer gated on #106**, which was closed by decision. The section
      above says what that accepts. What still holds is narrower and belongs in
      the release notes: this is a first publication, and the two breaking
      changes from Phase 7, #108 and #115, are what an operator needs told.

### Task 29: It dies when you close the terminal

**Ticket:** #110

- [x] The systemd **user** unit template, `Restart=on-failure`, and
      `loginctl enable-linger` documented rather than performed.
- [x] `EnvironmentFile` at mode 600 holding `HITCHRAIL_TOKEN`, which #109 built
      and which is what makes the link on a phone survive a restart.
- [x] The phone access document, ordered overlay first, named interface second,
      wildcard never, each with its exposure stated.
- [x] **Decide the journal question #109 handed over**: the banner writes the
      grant link, token included, to stdout, which under a unit is journald and
      therefore a stable secret in a persistent log. Decide it with the unit in
      hand and write the answer down.
- [x] `uv tool install`, not `uvx`, and say why: `uvx` is deliberately
      ephemeral and a unit needs a stable path. **This is why the task moved
      after the publish**: the instruction is not true until task 28 lands, and
      the earlier ordering had this written before the thing it names existed.

---

---

## Phase 8 exit criteria

Ticked only with evidence, per the roadmap's own rule.

**Ticking pass, 2026-09-04.** Every box above was ticked against the repository
rather than against memory: the file exists, the guard exists, the test name is
the one the suite actually has. One correction came out of it, and the plan
named `test_no_workflow_holds_a_publish_password` while the suite has
`test_no_workflow_holds_a_publish_credential`.

**Seven boxes are deliberately left open, and they reduce to two blockers.**
Neither is work:

1. **The publish has not happened.** It is gated on two actions only the owner
   can take in a browser, listed in `docs/releasing.md`: the pending publisher
   on PyPI, and the `release` environment with a required reviewer. Five of the
   seven wait on that, including the Install section, which says "Not yet" on
   purpose and is corrected by the same change that makes it true.
2. **The reboot has not been done by hand.** #110 chose a documented manual
   verification over an E2E tier that would skip on every runner without a
   systemd user session. The unit exists and its flags are asserted against the
   real parser; what is missing is somebody installing it, rebooting, and
   confirming the link saved on a phone still works.

An open box here is the honest state, not an oversight. Ticking either of these
early is exactly the failure `test_the_roadmap_marks_a_phase_done_only_when_its_plan_is_finished`
exists to catch.

- [ ] `uvx hitchrail --root <folder>` works on a machine that has never seen
      this repository, with the transcript recorded on #116.
- [x] The security section is the first thing a reader meets after learning what
      the tool does.
- [x] A hole in the token check has a private channel to be reported through,
      and `SECURITY.md` names what is in scope and what is a documented design
      choice.
- [x] A contributor can find the conventions without reading `.claude/`.
- [x] The error envelope is documented where an integrator would look, and the
      existing guards read that document.
- [ ] The first release notes name both breaking changes and the level chosen.
- [x] Screenshots in the README were produced by a machine, from a fake root.
- [ ] Hitchrail survives closing the terminal, and the link on a phone survives
      a restart.
- [x] No workflow holds a publish credential, asserted.
- [ ] The first release notes name #108 and #115 as breaking, and the level.

**Withdrawn: "#106 returns 404 before anything is published."** It was closed by
decision rather than by the objects being purged, so this criterion could never
have been met and the phase could never have finished. The exposure it named is
recorded above as accepted. Screenshots and fixtures still must not carry a real
project name, and that is task 26's requirement rather than this one's.

## What would make this phase a failure

Stated because the failure mode here is different from every previous phase.
Phases 1 to 7 could be wrong in private. This one is the first that is wrong in
public, and two of its steps cannot be taken back: a published version and a
name on an index.

- A README that reads as marketing. The tool spawns agents with permissions
  skipped; the honest description of that IS the pitch.
- A `SECURITY.md` that promises a response time nobody will meet.
- Screenshots containing a real project name. This is the one part of #106 that
  survives its closure, because a screenshot is content this phase creates
  rather than history it inherits.
