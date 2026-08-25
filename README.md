# corral

A web UI for starting and stopping headless Claude Code sessions across a
folder of projects. Open it on your phone, tap a folder, get a session link.

**Status: design complete, not yet implemented.** There is no working code in
this repository yet. See
[`docs/superpowers/specs/2026-08-25-corral-design.md`](docs/superpowers/specs/2026-08-25-corral-design.md)
for the design, and [`docs/tech-guidelines.md`](docs/tech-guidelines.md) for the
engineering rules that govern the code once it exists.

## What it will do

Point it at a directory. It lists every folder inside, shows which ones have a
live Claude Code session, and lets you start or stop one with a single tap. It
shows memory pressure, refuses to start a session that would exhaust the
machine, and tails a session's output when you want to know what it is doing.

## Read this before running it

Corral starts `claude --dangerously-skip-permissions`. **Anyone who can reach
its API can run arbitrary code on that machine as you.**

It binds to loopback with no authentication by default. Binding it to any other
interface requires a token, and the server refuses to start without one. It
validates the `Host` header on every request, because a localhost service
without that check can be driven by any website you visit, through DNS
rebinding. Over plain HTTP on a LAN the token crosses the network in cleartext;
put a TLS terminating reverse proxy in front of it if that matters to you.

Corral does not sandbox the sessions it starts. It is a launcher. The agent it
launches has whatever access you have.

## Not affiliated with Anthropic

Corral is an independent open source tool. Claude and Claude Code are
trademarks of Anthropic.

## Licence

MIT.
