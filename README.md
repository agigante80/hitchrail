# hitchrail

A web UI for starting and stopping headless Claude Code sessions across a
folder of projects. Open it on your phone, tap a folder, get a session link.

**Status: early. Phase 1 of 7 is built; there is no runnable server yet.**

What exists today is the package skeleton with five blocking gates on Python
3.11, 3.12 and 3.13, the configuration and its refusals, and the folder
discovery that makes the root a hard boundary. What does not exist yet is
everything you would actually use: the HTTP API, the browser interface, and
the engine that starts and stops sessions. `hitchrail` is not on PyPI, and the
install commands below will not work until it is.

See [`docs/roadmap.md`](docs/roadmap.md) for the order of work,
[`docs/superpowers/specs/2026-08-25-hitchrail-design.md`](docs/superpowers/specs/2026-08-25-hitchrail-design.md)
for the design, and [`docs/tech-guidelines.md`](docs/tech-guidelines.md) for the
engineering rules that govern the code.

## What it will do

Point it at a directory. It lists every folder inside, shows which ones have a
live Claude Code session, and lets you start or stop one with a single tap. It
shows memory pressure, refuses to start a session that would exhaust the
machine, and tails a session's output when you want to know what it is doing.

Stopping is a sequence rather than a button: it asks the agent to wrap up, shows
you the wait, and keeps a kill control within reach the whole time if you would
rather not wait.

## Install

**Not yet.** Nothing is published, so none of these work today. They are here
so the intended shape is on the record, and they become true at Phase 7.

Hitchrail is a Python package, so the equivalent of `npx` here is `uvx`:

```sh
uvx hitchrail                  # run it, install nothing
uv tool install hitchrail      # keep it on PATH
pipx install hitchrail         # if you already live in pipx
```

One word, no hyphen.

## Working on it

```sh
uv sync                    # set up
uv run pytest              # tests
uv run ruff check          # lint
uv run ruff format         # format
uv run mypy                # types
uv run lint-imports        # module boundaries
```

All five are blocking in CI on 3.11, 3.12 and 3.13. The last one is the
unusual one: it enforces that the engine layer never imports Starlette,
uvicorn, `sse_starlette`, the server or the CLI, so the engine stays testable
without HTTP. Import boundaries defended only by good intentions do not
survive.

## Read this before running it

Hitchrail starts `claude --dangerously-skip-permissions`. **Anyone who can reach
its API can run arbitrary code on that machine as you.**

This section describes the finished tool. Of the controls below, the mandatory
token off loopback and the root boundary are built; the host and origin checks
land in Phase 2, before there is any API to reach. None of it is optional, and
none of it is a reason to run this on a network you do not trust.

It binds to loopback with no authentication by default. Binding it to any other
interface requires a token, and the server refuses to start without one. It
validates the `Host` header on every request, because a localhost service
without that check can be driven by any website you visit, through DNS
rebinding. Over plain HTTP on a LAN the token crosses the network in cleartext;
put a TLS terminating reverse proxy in front of it if that matters to you.

Hitchrail does not sandbox the sessions it starts. It is a launcher. The agent it
launches has whatever access you have.

## Not affiliated with Anthropic

Hitchrail is an independent open source tool. Claude and Claude Code are
trademarks of Anthropic.

## Licence

MIT.
