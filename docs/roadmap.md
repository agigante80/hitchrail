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
of delay, which has been invoked once, when Phase 12 jumped ahead of 9, 10 and
11 because the wire format it changed was free to break that week and more
expensive every week after. The next candidate for jumping the queue is argued
against that one.

**Phases 1 to 10 and 12 closed before this format was adopted on 2026-09-11
and are not written into it.** Rewriting finished work to look planned in a
format it never used would be less honest than saying where the format
started. Their closed milestones hold their tickets, `superpowers/plans/`
holds the plans the ones that had plans wrote, and `CHANGELOG.md` says what
each release shipped.

**The standing rule.** A phase is not finished because its code exists and the
suite is green. It is finished when the behaviour has been watched working in
the running application, on the phone it is for. See
[`tech-guidelines.md`](tech-guidelines.md) section 7.

## Phase: Phase 11: The interface in every state
state: open
plan: docs/superpowers/plans/2026-09-11-hitchrail-phase-11-interface-states.md

Every state the interface can be in says something true, legibly. Phase 6
built the interface for the states a demo reaches; this is the rest: the
dialog a person sees once a week, at the moment they are deciding whether to
kill a process with unsaved work, and it sends them to the wrong place, tells
them the opposite of what happened, or puts the destructive action nearest the
thumb.

Delivers: a stream that reports its own failures honestly, dialogs whose
titles match what happened, colour that passes AA on its own tints, computed
rather than judged, and a memory footer with a ceiling.

Done when no screen states something it did not read, and every token pair
passes AA.

Two things were cut out of it on the day it opened, and the plan is the
precedent the next reviewer cites. The stop redesign is Phase 19: it changes
what Stop means, in the engine and `claude_ipc`, and nothing about it is a
screen saying something true. The `app.js` split is Phase 18. Two engine
tickets stay, because each is the reason one badge lies; a third goes to its
own phase or to Backlog.

## Phase: Phase 13: Fifty rows on a phone
state: planned

The interface stays usable when there are fifty projects across five roots,
and says what it knows about each. Phase 11 is about states saying something
true; this is about a person finding the row they want among a lot of them,
and about the page answering what it currently cannot: which build is this,
since when, as whom.

Cut from a real five root install rather than from the design. None of it is a
new power: the list is complete and correct, and what is missing is
navigation and provenance.

Delivers: filtering by root, a header that survives scrolling, a footer that
names the version and links to the source, the server's own start time and
account, logs at a URL you can bookmark, bulk stop composed from the stop each
row already has, and an icon set.

Done when a fifty row list can be narrowed to one root in one tap, the primary
action is reachable at any scroll position, and the page answers "which build
is this and who is it running as" without an SSH session.

Two decisions are already taken and the tickets argue them. The badge glyphs
are a SET, vendored from a library and never generated, because a set has to
agree with itself on grid and stroke and that agreement is what generation
gets wrong; the application's own mark is one drawing that agrees with
nothing, so it is drawn. And framing the vendor's session view under our
header is measurably impossible: it refuses framing twice, by header and by
CSP, so what remains of that idea is the header question underneath it.

## Phase: Phase 14: The perimeter, chosen rather than assumed
state: planned

The operator chooses how this is reached and how it is proved, instead of
being handed one answer. Every ticket here touches a security control, so each
is a decision before it is work, and they are together because they interact:
TLS changes what a sign-in costs, and both change what the README's stated
limitations say.

Delivers: HTTPS from the server itself rather than only from a proxy in front
of it; a way for a person holding a token to get in without the saved link;
roots and the session prefix from configuration the operator can reach rather
than only from a unit's `ExecStart`; and a settings page with the line drawn
between what it shows and what a request may change.

Two of those are deliberately not what was first asked for, and the tickets
argue it rather than quietly narrowing. Replacing a 192 bit token with a
password a person can type on a phone is a downgrade on an API equivalent to a
shell, with no rate limiting anywhere in this codebase, so enrolling a device
is solved another way. And a route that takes a PATH removes the root boundary
outright: the credential that lists projects would become one that runs an
agent anywhere the user can write, so roots come from a file the operator
edits on the machine and a UI can only toggle what is already in it.

Done when a LAN deployment can be HTTPS without a second daemon, a person
holding a token can get in without a saved link, and adding a folder does not
mean editing a systemd unit.

## Phase: Phase 15: The package as strangers meet it
state: planned

Somebody who has never seen this project can install it, tell what it is, see
that it is maintained, and be helped when it goes wrong. Everything here came
from looking at the published PyPI page beside our own README and finding they
disagree, or say nothing, and from failing to answer a support question about
this machine because the journal held uvicorn's access lines and nothing else.

Delivers: `pip` acknowledged as an install route, the deprecated licence
classifier removed and the licence made clickable, a badge row on the first
screen, `--help` that shows its defaults and an example, a banner that offers
only links the server is listening on, and logging with a handler, a level and
a timestamp, so that "was the stop request sent" has an answer.

Done when the PyPI page and the README agree, the licence is one clickable
statement rather than four scattered ones, and a stranger's bug report can be
answered from the journal.

## Phase: Phase 16: What survives a reboot
state: planned

Decide whether Hitchrail remembers anything, and if so what. Small in tickets
and a phase because of what it changes rather than how big it is.

Hitchrail holds no state. The security argument says so in as many words: no
database, no session registry, every answer derived from the operating system
on demand. That is why nothing can get out of sync, nothing needs migrating,
and no file's contents decide what runs. Remembering which sessions were
running is the first persistent state in the product, and specifically a file
that decides what gets spawned. The ticket is written for a default of ON and
lists what has to be true for that default to be defensible: the memory guard
re-evaluated between each restored start, a cap, never doubling an agent that
survived, a command line kill switch, protection against a restart loop
multiplying it, and restored rows visibly restored. If any of those is not
built, the default is off and the feature still ships.

The unit's own behaviour across a reboot belongs here too: an address that
arrives after boot must not be a cliff the service falls off, and socket
activation for a named bind comes with the token rule it needs.

Done when a reboot brings back what was running, exactly once each, without a
person tapping anything, and the security argument has been rewritten rather
than quietly outgrown.

## Phase: Phase 17: Documents that are true
state: planned

Every claim a document, comment or guard makes is checked against the thing it
describes, or it is not written. Counts are generated, never typed.

Cut out of Phase 10 on 2026-09-07, because eleven of that phase's tickets were
not about a suite that would notice. They were about a sentence, a comment, a
label or a count that disagreed with the thing standing next to it: one defect
in eleven costumes, and inside a phase about tests it looked like eleven
unrelated chores.

The guards are in scope, not only the prose, and they are the harder half. A
lockstep guard that compares version markers proves the marker moved, which is
not the claim. Every hygiene check reads from the ticket list, so a
deliverable nobody ticketed is invisible to all of them at once. A governance
guard that skips silently looks identical to one that passed.

Delivers: counts derived from what they count, comments and docstrings that
name something which exists and does what they say, and guards whose
expectation comes from the thing described rather than from a second copy of
the answer.

Done when, and each is checkable rather than felt: no document states a count
a person typed; every comment or docstring that names a file, a ticket or a
behaviour names one that exists and does what it says, enforced by a guard;
and no guard proves only that its own marker moved.

## Phase: Phase 18: Modules that do one thing
state: planned

A file is one thing, or the file says why it is not. Cut out of Phase 10 on
2026-09-07, with the files that carry a split ticket and the one place an
answer is computed twice.

The guideline is 400 lines and the mechanism around it already works, which is
why this is a set of splits rather than a policy: `test_config.py` holds a
`caps` table, a module over the guideline fails unless it is tracked there
with the ticket that splits it, and the table retires its own exceptions. No
line count is written here or in the tickets on purpose. Every count they held
was stale twice over; the table is generated from the files and was right
about all of them.

Each file is over for a different reason, and the reason decides the cut.
`server.py` because routes accumulated, and its seam is what the handlers
touch; its ticket also says what must NOT happen, which outranks the split:
the per route error ladders stay at the route, because `docs/api.md` is
checked against the server in both directions and a ladder at the route is
what makes a route's refusals readable. `discovery.py` because the plural root
layer sits on top of the single root one, two layers deep rather than two jobs
wide. `app.js` because the browser code all landed in one file and it has a
seam it already follows. `test_config.py` because it does not split along the
seam its own source has, and it is the file the guard cannot see, since `caps`
reads `src/` and this is where `caps` lives. And one computation done twice:
`preflight` resolves the agent binary and throws the answer away, and the
spawn resolves the bare name again in a different environment.

Done when every file over the guideline has either been split along a seam
that already existed, or carries in `caps` the argument for why it is one
thing. `claude_ipc.py` is the standing example that the second answer is
legitimate: it is over on purpose, because when Claude Code moves exactly one
file changes. `engine.py` is the other, and most of its length is comments
recording footguns that cost real debugging to find. A split that moves lines
without moving responsibility is refused; length is the trigger for looking,
never the reason for cutting.

## Phase: Phase 19: Stop means wrap up
state: planned

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
not how big it is. It changes design section 4.3, the stop sequence, and it
carries an open sub decision, the order in which the interrupt and the prompt
are sent, that is the operator's to make.

Delivers: a configured prompt sent before the exit sequence, the closing skill
by default, with a per session wait for the pane to show an idle input box
under a ceiling; and an opt in, off by default, that lets a stop ending on a
prompt end the session anyway because the operator said so ahead of time.

Done when a session stopped from the interface has run the closing skill
before it exits, a stop that ends on a prompt still does nothing on its own
unless the operator opted in before tapping, and `stop_prompt` cannot be set
through any HTTP route.

The deferral under "Deliberately later" still binds, and this phase is written
against it rather than around it: the prompt is configuration on the machine,
never text from the page, and the page's only verb is still Stop.

## Phase: Backlog
state: backlog

Triaged, real, and belonging to no phase yet. A ticket whose home is unknown
goes here rather than into the nearest phase with room, because a phase whose
objective absorbs every finding never ends: Phase 10 went from sixteen tickets
to thirty nine while six were being closed, and was narrowed to escape it.
Every time a phase opens, this is read for what now belongs in it.

## Deliberately later

Not scheduled, and not to be smuggled into an earlier phase:

- **Restart as its own operation.** It is stop then start, and the interface
  can compose it.
- **Authentication beyond a single shared token.** Phase 14 adds ways to
  present the existing credential and says why a second kind of credential is
  a downgrade rather than a feature.
- **Streaming logs.** A tail on demand is enough until it demonstrably is not.
  Phase 13 gives the tail its own URL and deliberately does not stream it.
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
