# Hitchrail: roadmap

The design says what to build. This file says which phases exist, what state
each is in, and why each one sits where it does. One phase at a time, each
ending in something that runs and has been watched running.

Design: [`superpowers/specs/2026-08-25-hitchrail-design.md`](superpowers/specs/2026-08-25-hitchrail-design.md)
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

## Phase: Phase 19: Stop means wrap up, and says so
state: open
plan: docs/superpowers/plans/2026-09-29-hitchrail-phase-19-stop-wrap-up.md

A session stopped from a phone leaves the same record as one closed by hand.
Cut out of Phase 11 on 2026-09-11.

Stop today types `C-u`, `Escape`, `/exit`, `Enter` and nothing else: the agent
is interrupted mid task and asked to exit, and whatever it knew about the work
in flight leaves with it. The operator's stated model of Stop is "run the
closing skill, summarise everything, then close the session", and the code did
none of that. Decided over the concern that a typed instruction on the
operator's behalf is impersonation: what keeps it relay is that the prompt is
authored on the machine only, sent only on a tapped Stop, and sent with
`send-keys -l`.

A phase rather than a ticket for the reason Phase 16 is one: what it changes,
not how big it is. It changes design section 4.3, the stop sequence. The
order the interrupt and the prompt are sent in was the operator's to decide,
and was decided on 2026-09-29: Stop queues the prompt behind the task in
flight, and Kill, available throughout the wait, is the interrupt.

Moved ahead of 16, 17 and 18 on 2026-09-16, on the third ordering rule, cost
of delay, invoked for the second time. Every stop tapped from a phone today
loses the wrap up the operator's own model of Stop says should happen, and
nothing in 16, 17 or 18 depends on it or is made cheaper by waiting. It sits
after Phase 15 rather than before it because #167's logging is what makes
the new stop sequence diagnosable when it is first watched on a real
session: "was the prompt sent, and did the pane go idle" has to have an
answer in the journal before the sequence is trusted.

Delivers: a configured prompt sent before the exit sequence, with no default so
an unconfigured Stop is today's (decided 2026-10-01: the closing skill is a
plugin most installs do not have), and a per session wait for the pane to show
an idle input box under a ceiling; and an opt in, off by default, that lets a
stop ending on a prompt end the session anyway because the operator said so
ahead of time.

Done when a session with a prompt configured, stopped from the interface, has
run the closing skill before it exits, a stop that ends on a prompt still does
nothing on its own unless the operator opted in before tapping, and
`stop_prompt` cannot be set through any HTTP route.

The deferral under "Deliberately later" still binds, and this phase is written
against it rather than around it: the prompt is configuration on the machine,
never text from the page, and the page's only verb is still Stop.

Two tickets joined it from Backlog on 2026-09-29, each because this is the
next phase to change the file it names: the split of `claude_ipc.py` into a package, which
this phase adds the wrap up to before Phase 23 adds anything, so the split goes
first; and `Config`'s surviving mutants, which are pinned before this phase
adds `stop_prompt`'s refusals beside them.

## Phase: Phase 23: Decide on more than one agent
state: planned

Answer design section 3.1 before anybody builds against it. The spec says more
than one agent is "not built, not closed off". An epic filed on 2026-09-22
proposes building it, with a registry of command templates written from the
settings page, and that collides with three things the product rests on: the
settings file is read once and never written, no vendor name enters the
operator or API contract, and no text from a page reaches a spawn.

Those are decisions rather than obstacles, so the answer is one of three: stay
single agent and close the epic with the reason; widen the vendor seam that
`claude_ipc` already is, one quarantined package per agent and no templates;
or change the security argument deliberately and say so in the spec.

Delivers: the decision, written into the design spec and into what
`docs/versioning.md` means by 1.0, and every ticket in this milestone rewritten
against it or closed with it.

Done when section 3.1 says built, not built, or closed off, with the reason,
and no open ticket asks for something the decision refused.

Placed before Phase 16 because both would add the first state the product
writes, and a reboot restore designed for one agent is rework if the answer is
several.

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

The unit's own behaviour across a reboot belongs here too, with one caveat
written down before the phase opens: on the operator's machine the LAN address
lives on a removable adapter that is often absent at boot, so no retry budget
reaches it, and that ticket may close as a documented limitation rather than a
fix. `server.py`'s split lands here, first, because the restore adds to the
file that is already past the guideline.

Done when a reboot brings back what was running, exactly once each, without a
person tapping anything, and the security argument has been rewritten rather
than quietly outgrown.

## Phase: Phase 24: The interface, found
state: planned

Everything the phone offers can be found by looking at it. Filed together from
using it: settings is a text link at the end of the footer, the button that
creates a project disappears under every filter and does not say what it
creates, a chosen theme cannot go back to following the system, the mark
never appears in the header, and the browser's implicit favicon request is
refused. Two display defects on the plugin update page join them, and so does
`app.js`'s split, because every one of these edits `app.js` and the split is
cheaper before them than after.

Delivers: settings and project creation as bar controls that survive a filter,
a theme choice that includes the system's, the mark in the header, the favicon
request answered by decision rather than by accident, plugin update rows that
say what moved and do not repeat, and `app.js` split along the seam it
already follows.

Done when each control is reached from the first screen on the phone the
design is for, watched there, and the screenshots have been regenerated.

After Phase 16 because only the favicon touches the perimeter, and that one is
a refusal the operator never sees. Before 17 because interface changes are
what the documents then describe.

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
several belong upstream in forge-kit. Placed last because every phase before
it changes what the documents describe.

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
Three open questions decide whether it is, and each is a phase above rather
than a promise here: whether anything survives a reboot (Phase 16), what Stop
does (Phase 19), and whether there is more than one agent (Phase 23). A 1.0
before all three are answered is a promise about an interface still moving.

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
