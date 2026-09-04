# Security policy

Hitchrail starts `claude --dangerously-skip-permissions`. **Anyone who can
reach its API can run arbitrary code on that machine as the user who started
it.** That is what the tool is for, and it is the frame for everything below.

## Reporting

**Use [private vulnerability reporting](https://github.com/agigante80/hitchrail/security/advisories/new).**
It is enabled on this repository, it is private until an advisory is published,
and it keeps the report with the code.

Please do not open a public issue for anything in the in scope list below. A
public issue is a disclosure rather than a report.

### What to expect

This is a single maintainer project. **An acknowledgement within a week**, and
no promise faster than that, because a promise nobody can keep is worse than an
honest one. If a week passes with no reply, the report was not seen, and
opening a public issue saying only "sent a private report, no reply" is a
reasonable escalation.

There is no bounty.

## What is in scope

Anything that lets somebody:

- **reach the API without the token**, including bypassing the host allowlist,
  the origin check, or the constant time token comparison
- **escape the configured root**, by any path that reaches a directory which is
  not a direct child of it
- **turn a documented refusal into an acceptance**: a config the program says
  it refuses and does not, a state it says it will not act on and does
- **inject arguments or a shell** into anything spawned, given that every
  subprocess call here takes an argument list and `shell=True` is forbidden
- **address a tmux session outside the configured prefix**, which is the
  property that keeps Hitchrail from touching sessions it did not create

## What is not in scope, and why

**The token grants code execution.** That is the design, stated in the README
and in the design document, not a vulnerability. A report saying "whoever has
the token can run commands" is answered by this paragraph.

**The agent runs unsandboxed.** Hitchrail is a launcher. What it launches has
whatever access the user who started Hitchrail has. It does not contain the
agent and does not claim to.

**Hitchrail types into the agent, and the agent cannot tell that from a
keyboard.** Stopping works by sending keystrokes through the terminal, so
whoever holds the token can cause characters to be typed into any agent session
under the configured root. This is deliberate and is what makes a graceful stop
possible at all. It is documented rather than hidden.

**Plain HTTP on a LAN carries the token in cleartext.** This is a stated
limitation, not a bug. The remedy is a TLS terminating reverse proxy, and the
README says so.

**A `detached` agent cannot be ended by Hitchrail.** It shows the pid and stops
there, because everything it can destroy is addressed by a session name it
created. That is a deliberate limit rather than a missing feature.

If you think one of these is wrong rather than merely unwelcome, that argument
is worth a public issue. The line between "the design is bad" and "the design
is not implemented" is the line between an issue and an advisory.

## Supported versions

**The latest release only.** There is no long term support branch and no
backporting, and pretending otherwise would be a promise this project cannot
keep. `docs/versioning.md` is the authority on what a version change means to
somebody running it: while the version is `0.y.z`, a breaking change may ship
as a MINOR.

## What the controls are

So a reporter can tell a hole from the design. Full detail is in the design
document, section 5.

1. **A host allowlist** on every request, including the event stream, because a
   loopback service without one can be driven by any website the operator
   visits through DNS rebinding.
2. **An origin check** on every mutating request. `GET` is exempt because
   `EventSource` cannot set headers, and that exemption is deliberate and
   tested.
3. **A token**, demanded whenever anything outside the machine can reach the
   server: a non loopback bind, or a non loopback name passed to `--allow-host`
   or `--allow-origin`. Compared with `compare_digest` on bytes.
4. **Response headers**: `nosniff`, framing refused, and a content security
   policy per route.
5. **The root is a hard boundary.** Every path is resolved and confirmed to be a
   direct child of the configured root before anything is spawned.
6. **No shell, ever.** Every subprocess call takes an argument list.
7. **tmux is addressed by an exact prefixed name**, and the empty prefix is
   refused at construction, so Hitchrail can only kill sessions it named.

The order of the first three is asserted by a test: host, then token, then
origin. Token precedes origin so an unauthenticated caller cannot enumerate the
origin allowlist by watching a 403 become a 401.
