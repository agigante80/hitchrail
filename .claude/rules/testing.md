---
paths:
  - "tests/**/*.py"
  - "src/hitchrail/**/*.py"
---

# Test coverage is part of the implementation

Not a follow up ticket. Full rules in `docs/tech-guidelines.md` section 7.

## Before writing tests

Read how this project already tests the area you are touching, and follow that
pattern. Do not introduce a second style alongside an established one.

## What every change must cover

For the behaviour you added or modified:

- the primary success path
- the edge cases the behaviour actually has
- the failure and error conditions, including every refusal
- the regression itself, when the change is a bug fix

Choose the kind of test that suits the behaviour: unit, integration, end to
end, component. Not the kind that is convenient.

## Done means run, not written

Code that type checks and a suite that still passes say nothing about the
behaviour just added. Complete means the relevant suites have been run, the
output inspected, failures introduced by the change fixed, and the new
behaviour protected by a test that would fail if the change were reverted.

Never report work as complete without having run the tests.

## Prove it in the running application

Where practical, verify through the actual runtime, not through unit tests and
type checking alone. Unit tests confirm a function does what its author
believed. They cannot confirm the assembled application does anything at all.

Use the end to end tier for anything a unit test structurally cannot see: the
SSE stream reconnecting, the stop escalation arriving in the state the user is
really in, the layout holding at a phone viewport, a forged `Host` being
rejected on a live socket.

## Hermetic, always

No test touches a real tmux server, a real Claude process, the network, or the
filesystem outside a temporary root. tmux, the process table, memory readings
and the Claude state directory are faked behind injectable seams.

**The end to end tier drives a private tmux server on its own socket**,
addressed as `tmux -S "$SOCK"` and invoked through `env -u TMUX`. A bare `tmux`
honours `$TMUX` over `$TMUX_TMPDIR`, so a suite run from inside tmux would
otherwise talk to the developer's real server. Create only prefixed sessions,
kill only what you created, never the server.

## Two habits that keep the suite honest

- Test the refusals, not only the successes. A security control with only a
  happy path test is untested.
- Every workaround for a documented footgun gets a named regression test that
  fails if the workaround is removed. A workaround with no test will be
  reintroduced by the next person tidying up.

Coverage is measured but not enforced as a percentage. A percentage gate is
satisfied by executing lines without asserting on them.
