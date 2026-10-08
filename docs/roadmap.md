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

## Phase: Phase 25: The wrap up, hardened
state: open
plan: docs/superpowers/plans/2026-10-07-hitchrail-phase-25-wrap-up-hardened.md

Every finding the Phase 19 reviews filed is fixed or closed with its reason,
and the journal says what a stop did. The roadmap's second Backlog rule,
applied a third time: 20 followed 14, 22 followed 21, and this follows 19.

Phase 19 stopped its review loops where the global rules say they stop, and
filed what was left, 29 tickets, in Backlog so a low never held the phase
open. All 29 were checked against the tree on 2026-10-07 and all still
describe the code. Two needed a decision, both taken by Andrea that day: #391
stops deriving a plain http origin for an https only host, and #419 records
the stop policy when the stop is confirmed. `engine.py`'s split (#274) goes
first, because nine of the findings edit the functions it would move, and #181
joins from Phase 17 by the first Backlog rule.

Its plan was written ahead of opening, and the phase opened on 2026-10-08,
the day Phase 19 closed on its real session watch.

Done when every finding is closed or moved with a number, a kill nobody tapped
is bound to the agent that was looked at, every kill leaves a journal line and
none carries a token, and a stop watched from two browsers on the phone shows
the same phase in both.

Placed before 23 on the first ordering rule: 23 adds an agent seam beside
`engine.py`'s stop path, and adding to the path before it is hardened is how a
second agent inherits its defects.

## Phase: Phase 24: The interface, found
state: planned

Everything the phone offers can be found by looking at it. Filed together from
using it: settings is a text link at the end of the footer, the button that
creates a project disappears under every filter and does not say what it
creates, a chosen theme cannot go back to following the system, the mark
never appears in the header, the title does not lead back to the list, and
the browser's implicit favicon request is refused. The plugin update page's
display defects join them, and so does `app.js`'s split, because every one of
these edits `app.js` and the split is cheaper before them than after. The
`innerHTML` guard's gaps (#342) come with the split, since the guard has to
read the files the split creates.

#321 and #322 rewrite the same control: decide #321 first, and #322 closes if
the bar button it renames is gone.

**The list as a real phone holds it** (added 2026-10-08, from the owner's
phone: five roots, 67 folders, 360 CSS px, default font settings). Three
layout defects nobody had seen, because every test and screenshot uses one
root and short names: a stopped row crushes its name again (#449, #179
regressed), the root chips overlap (#448), and the footer covers the last row
under a filter (#447). Order: those three first, then #450 (a fixture with
that data, and the type scale at phone width, which is the owner's call),
then #451 (a clear control for the search).

Delivers: settings and project creation as bar controls that survive a filter,
a theme choice that includes the system's, the mark in the header, the favicon
request answered by decision rather than by accident, plugin update rows that
say what moved and do not repeat, and `app.js` split along the seam it
already follows.

Done when each control is reached from the first screen on the phone the
design is for, watched there, the busy list reads at 360px on that phone, and
the screenshots have been regenerated.

Moved ahead of 23 and 16 on 2026-10-08, at the owner's request: the layout
defects are daily use pain on the phone, while 23 and 16 are new capability.
Only the favicon touches the perimeter, and that one is a refusal the
operator never sees, so nothing in 16 needs to come first. Before 17 because
interface changes are what the documents then describe.

## Phase: Phase 23: More than one agent, one package each
state: planned

Build more than one agent through the seam `claude_ipc` already is: one
quarantined package per agent, the agents chosen on the machine, and no
command template anywhere.

Decided by Andrea on 2026-10-07, on #334, between three answers to design
section 3.1's "not built, not closed off": stay single agent; widen the vendor
seam; or change the security argument so a page could edit a registry of
command templates, as the epic filed on 2026-09-22 proposed. The seam won, so
the three things the product rests on still hold: the settings file is read
once and never written, no vendor name enters the operator or API contract,
and no text from a page reaches a spawn. #291, the settings page that edited
templates, closed with that reason.

The phase's first task is #334 itself: the answer written into section 3.1 and
into what `docs/versioning.md` means by 1.0. Then every epic ticket is
rewritten against it when the phase opens, because each was written for the
registry. Two questions are left for the plan rather than assumed here:
whether the page may choose among the agents the operator configured when it
starts a project (#292), which is a choice from an allowlist but changes the
start route's contract; and whether a daemon one agent needs (#293) is a
process Hitchrail should own at all, since it would be the first long lived
child that is not a session.

Done when a second agent starts, stops and is derived exactly as Claude Code
is, through its own package, the stop sequence included, with no vendor name
outside that package and nothing an agent runs coming from a page.

Placed before Phase 16 because a reboot restore has to record which agent a
session was, and designing it for one is rework. After Phase 25 because the
stop path the second agent plugs into should be hardened first.

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
out if the phase runs long. `server.py`'s split (#205) lands here, first,
because the restore adds to the file that is already past the guideline.

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

- **Restart as its own operation.** It is stop then start, and the interface
  can compose it.
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

