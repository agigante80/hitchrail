# Hitchrail: roadmap

The design says what to build. This file says which phases exist, what state
each is in, and why each one sits where it does. One phase at a time, each
ending in something that runs and has been watched running.

Design:
[`superpowers/specs/2026-08-25-hitchrail-design.md`](superpowers/specs/2026-08-25-hitchrail-design.md)
Rules: [`tech-guidelines.md`](tech-guidelines.md)

## How to read this file

Rolling wave planning, in the shape `forge-kit`'s `roadmap-phases` skill
defines and `scripts/check-phases.sh` enforces. Two stores hold two different
facts, so nothing is written twice and nothing can drift:

- **This file owns which phases exist and what state each is in.** A phase is
  a `## Phase:` block with a `state:` line and, once it has started, a `plan:`
  line naming its plan file. The heading is the milestone's title, exactly.
- **GitHub owns which phase each ticket is in**, as the milestone. No ticket
  number is typed here for that reason: every list this file ever carried was
  wrong within a week, and a count nobody checks is a count that decays.

The four states: `planned` is a bucket, declared and ordered, taking tickets
as they occur to somebody and committing to nothing; `open` is the one phase
in progress, and it has a plan; `done` is closed in both places; `backlog` is
the permanent holding phase, a decision to decide later. At most one phase is
`open`. A phase that stalls is re-shaped, never extended: closing it forces
every unfinished ticket somewhere explicit.

Phases appear in the order they are meant to run. Three rules decide that
order: dependency first, then risk where dependency allows a choice, then cost
of delay. The third has jumped the queue three times (Phase 12 ahead of 9 to
11, Phase 19 ahead of 16 to 18, Phase 21 ahead of 15 to 19), and the next
candidate is argued against those three.

**A phase leaves this file when it closes.** Its closed milestone holds its
tickets, its plan stays in `superpowers/plans/`, and `CHANGELOG.md` says what
the release shipped. Phases 1 to 10 and 12 closed before this format was
adopted on 2026-09-11 and were never written into it; 11, 13, 14, 20 and 21
were, and left on 2026-09-26. The file is a plan of what happens next, and a
finished phase's prose here only lengthens the walk to it.

**The standing rule.** A phase is not finished because its code exists and the
suite is green. It is finished when the behaviour has been watched working in
the running application, on the phone it is for. See
[`tech-guidelines.md`](tech-guidelines.md) section 7.

## Phase: Phase 16: What survives a reboot
state: planned

Decide whether Hitchrail remembers anything, and if so what. Small in tickets
and a phase because of what it changes rather than how big it is.

Hitchrail holds no state, and the security argument says so in as many words:
every answer is derived from the operating system on demand, so nothing drifts
and no file's contents decide what runs. Remembering which sessions were
running is the first persistent state in the product, and specifically a file
that decides what gets spawned. The ticket is written for a default of ON and
lists what has to be true for that default to be defensible: the memory guard
re-evaluated between each restored start, a cap, never doubling an agent that
survived, a command line kill switch, protection against a restart loop, and
restored rows visibly restored. If any of those is not built, the default is
off and the feature still ships.

The unit's own behaviour across a reboot belongs here too. On the operator's
machine the LAN address lives on a removable adapter that is often absent at
boot, so no retry budget reaches it; #201 has since decided the fix is a
recovery timer that starts the unit once the address appears, not a longer
budget. Socket activation (#220) sits here as its alternative, P3, and
helps nobody while the unit binds loopback, so it is the first ticket to move
out if the phase runs long. `server.py`'s split (#205) moved to Phase 26 on
2026-10-09, because the restart route reaches that file first.

Phase 23 closed re-shaped on 2026-10-10 and left two things here. #504,
agy's `--add-dir=` answering agy's trust prompt for every folder, is Andrea's
decision and holds the next release, since agy is already in `## Unreleased`.
And the S25 watch at 360 CSS px (#468, #485), which has slipped four phases
running and covers the bar, Restart, the countdown and the agent chip.

Done when a reboot brings back what was running, exactly once each, without a
person tapping anything, and the security argument has been rewritten rather
than quietly outgrown.

## Phase: Phase 17: Documents that are true
state: planned

Every claim a document, comment or guard makes is checked against the thing it
describes, or it is not written. Counts are generated, never typed.

Delivers: counts derived from what they count, and comments and docstrings that
name something which exists and does what they say.

Done when, and each is checkable rather than felt: no document states a count
a person typed, and every comment or docstring that names a file, a ticket or
a behaviour names one that exists and does what it says, enforced by a guard.

Narrowed on 2026-09-26 to the documents themselves. The tickets about the
governance machinery, a lockstep guard that proves only its marker moved, a
skipped guard that looks like a passed one, checks that read only the ticket
list, moved to Backlog: they are about the process around the product, and
several belong upstream in forge-kit. Narrowed again on 2026-10-07 by the
same test: the mypy matrix gap (#10) and the missing area labels (#143) are a
gate and a governance change, not documents, and went to Backlog; #181's
engine docstrings went to Phase 25, which changes `engine.py`. What is left is
small document fixes plus the two guards the done line names, which no ticket
builds yet: the plan files them when the phase opens. #244 needs the private
design canvas re-exported, so it is Andrea's, not an agent's.

Placed last because every phase before it changes what the documents describe.

## Phase: Backlog
state: backlog

Triaged, real, and belonging to no phase yet. A ticket whose home is unknown
goes here rather than into the nearest phase with room, because a phase whose
objective absorbs every finding never ends: Phase 10 went from sixteen tickets
to thirty nine while six were being closed, and was narrowed to escape it.

Every time a phase opens, this is read for what now belongs in it, by two
rules rather than by judgement. The opening phase takes every open
`from-review` ticket about a file it changes, because that is when fixing it
is cheapest. And a phase that ships new surface is followed by one that
hardens it, as Phase 20 followed 14 and Phase 22 followed 21: a review loop that
stops on its trip wire files its findings here, and without the second rule
they stay here.

## Toward 1.0

`versioning.md` says 1.0 comes when the HTTP interface is one worth keeping.
Three questions decide whether it is. What Stop does is answered, built and
watched on a real session (Phase 19, closed 2026-10-08). The other two are
phases above rather than promises here. Whether there is more than one agent is answered, yes and one
package each, but not built, and building it changes the start route
(Phase 23). Whether anything survives a reboot is still open (Phase 16). A 1.0
before all three are built is a promise about an interface still moving.

## Deliberately later

Not scheduled, and not to be smuggled into an earlier phase:

- **Authentication beyond a single shared token.** Phase 14 added ways to
  present the existing credential and says why a second kind of credential is
  a downgrade rather than a feature.
- **Streaming logs.** A tail on demand is enough until it demonstrably is not.
  Phase 13 gave the tail its own URL and deliberately did not stream it.
- **Sending input to a session.** Hitchrail starts and stops agents; it is not
  a terminal, and making it one is a different product. Phase 16 restores
  sessions and deliberately does not reach into an agent's own conversation
  state.

  `POST /api/sessions/{name}/answer` shipped one keystroke, and this deferral
  still stands, because the line between the two is now in code rather than
  only on a ticket. The route carries ONE key from `claude_ipc.ANSWER_KEYS`, a
  literal frozenset, to a session whose pane is showing a question, in reply
  to words the operator read in that pane. Three conditions hold it there and
  each has a test that fails if it is widened: the key set is a literal,
  asserted member by member, with the browser's copy asserted equal to the
  server's; the pane is re-read INSIDE the send, so a screen that moved on
  refuses, and the function's signature is asserted so a parameter carrying
  an earlier capture fails in the suite rather than in review; and the answer
  pad must not build an `<input>`. The root boundary already bounds it:
  Hitchrail starts sessions only inside a configured `--root`, so an
  answerable prompt is a subset of a trust decision the operator made on the
  command line. If a free text field, an automatic choice, or a key sent
  without re-reading the pane ever appears, this becomes the deferred item and
  the deferral binds.

  #242's `stop_prompt` is not the deferred item either: a fixed string the
  operator configured on the machine, typed on Stop. A string arriving through
  the API would be, which is why no route can set it.

  Nor is #239's `stop_policy`. "No timeout that presses a key" stays true: a
  stop that runs out of time on a prompt is KILLED under an opt in the
  operator set before tapping, exactly as the dialog's Kill would, and
  nothing is typed into the prompt.

## Notes

- **Deleted, 2026-09-26: "Phase 18: Modules that do one thing".** Its splits
  are refactors with no change a person can see. Each one that makes a later
  phase cheaper went with that phase: `app.js` to 24, `server.py` to 16, and
  the agent binary resolved twice to 22, as the defect it is. The rest wait in
  Backlog for a phase that edits their files, which the Backlog's first rule
  then hands them to.
- **Reviewed 2026-10-07, every open ticket against the tree.** Phase 25 was
  inserted to hold Phase 19's 29 review findings, by the second Backlog rule.
  Phase 23 was renamed from "Decide on more than one agent" once Andrea
  decided it, so the old milestone is left on the host, emptied. #360 closed
  as a premise that did not hold (`procs.py` runs only `ps`, which does not
  fork), and #291 closed with #334's decision. Phase 17 and 24 each lost a
  ticket that was not about what the phase is for (#10, #143, #339 to Backlog).
- **Reviewed 2026-10-09: the Backlog had become a phase nobody opened.** It
  held 46 tickets, about thirty of them review findings from Phases 24 and 25,
  the case the second Backlog rule exists for. Phases 26 to 28 were inserted
  ahead of 23 to hold them, split by the code they touch: the stop path, the
  perimeter, the page. Restart left "Deliberately later" because Andrea asked
  for it (#472): it is still a stop then a start, and landed in Phase 26 on the
  settled stop path. What stays in Backlog is the governance and test
  machinery, the TLS passphrase (#280), the sponsors link (#17), and the text
  size work that waits on Chrome (#452).

