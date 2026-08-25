# Hitchrail: roadmap

The design says what to build. This says in what order, and what "done" means
at each stop. One phase at a time, each ending in something that runs.

Design: [`superpowers/specs/2026-08-25-hitchrail-design.md`](superpowers/specs/2026-08-25-hitchrail-design.md)
Rules: [`tech-guidelines.md`](tech-guidelines.md)

## Phase 0: Design

**Status: done.**

Design approved, technical guidelines written, interface drawn and clickable,
name secured on both registries.

## Phase 1: Core

**Plan: [`superpowers/plans/2026-08-25-hitchrail-core.md`](superpowers/plans/2026-08-25-hitchrail-core.md)**

The engine and the HTTP API, with no browser interface. Everything that decides
whether Hitchrail tells the truth about a machine lives here.

Delivers: project skeleton and CI gates, configuration, folder discovery, the
tmux adapter carrying the five footguns, the process table adapter, the Claude
Code quarantine module, the memory guard, state derivation across all four
states, start, the three step stop, the log tail, the event bus, the security
middleware, the REST API, the SSE stream, and the CLI.

**Done when:** `uvx hitchrail --root ~/dev` serves an API that a person can
drive with `curl`. It starts a real session, reports it accurately, stops it
gracefully, kills it when told to, and refuses to bind to a network interface
without a token. All gates green on 3.11, 3.12 and 3.13.

**Not done if:** the suite passes but nobody has watched it start and stop a
real Claude session.

## Phase 2: Interface

The browser interface from the design canvas, and the end to end tier that
proves it.

Delivers: the single page and its assets, the list with search and filter, the
start and stop flows including the escalation, the log drawer, the new folder
sheet, the memory footer, live updates over SSE with reconnection, the token
gate, dark theme, and the Playwright end to end tests running against a private
tmux server and a fake `claude` shim.

**Done when:** every flow in the design canvas works on a real phone against a
real machine, and the E2E tier covers the things unit tests structurally cannot
see: SSE reconnecting after a backgrounded tab, the stop escalation reaching the
kill control in the state the user is really in, the layout holding at a phone
viewport, and a forged `Host` being rejected on a live socket.

## Phase 3: Release

Delivers: PyPI publication as `hitchrail`, a tagged GitHub release, a README
that a stranger can follow, and a security policy telling people how to report
something.

**Done when:** `uvx hitchrail` works on a machine that has never seen this
repository, and the security section is the first thing a reader meets after
learning what the tool does.

## Deliberately later

Not scheduled, and not to be smuggled into an earlier phase:

- Restart as its own operation. It is stop then start, and the interface can
  compose it.
- More than one root.
- Authentication beyond a single shared token.
- Streaming logs. A tail on demand is enough until it demonstrably is not.
- Sending input to a session. Hitchrail starts and stops agents; it is not a
  terminal, and making it one is a different product.

## The standing rule

A phase is not finished because its code exists and the suite is green. It is
finished when the behaviour has been watched working in the running
application. See [`tech-guidelines.md`](tech-guidelines.md) section 7.
