# hitchrail

A web UI for starting and stopping headless Claude Code sessions across a folder
of projects. Phone first. Python, standalone, no bash dependency.

## Where things are

- `docs/roadmap.md` is the order of work. Read it before starting anything.
- `docs/superpowers/specs/2026-08-25-hitchrail-design.md` is the design. It is
  the argument; follow it or change it deliberately, never drift from it.
- `docs/superpowers/plans/` holds the implementation plan for the current phase.
- `docs/tech-guidelines.md` is binding for all code here.
- `docs/design/` holds the interface artboards. The published canvas is
  https://claude.ai/code/artifact/e02013e2-d501-405a-a95c-6404ebe492a6

## Commands

```sh
uv sync                    # set up
uv run pytest              # tests
uv run ruff check          # lint
uv run ruff format         # format
uv run mypy                # types
uv run lint-imports        # module boundaries
```

All five gates are blocking in CI on 3.11, 3.12 and 3.13. Run them before
committing, not after being asked.

## Non negotiables

These are the ones that cost real debugging to find, or that protect somebody.

- **No shell.** Every subprocess call takes an argument list. `shell=True` is
  forbidden, no exceptions.
- **Never a bare `tmux kill-server`.** Never kill a tmux session that does not
  carry the configured prefix. A bare `tmux` honours `$TMUX`, so from inside a
  session it hits the developer's real server.
- **Starlette is 1.x here.** `on_startup`, `on_shutdown`, `add_event_handler()`
  and the `@app.route()` decorators were removed at 1.0. Use the `lifespan`
  context manager and an explicit `routes=` list. Most examples online are
  written against 0.4x and are wrong.
- **Three runtime dependencies:** `starlette`, `uvicorn`, `sse-starlette`. A
  fourth needs a written justification in the pull request. Every dependency is
  audit surface for a tool that spawns processes as the user.
- **The engine layer must not import** `server`, `cli`, `starlette`, `uvicorn`
  or `sse_starlette`. `uv run lint-imports` enforces it.
- **The root stays lean.** Configure tools from `pyproject.toml`. Do not add
  root level dotfiles without a reason.
- **`claude_ipc.py` is quarantine.** It is the only module allowed to know
  about Claude Code internals, because they are undocumented and will change.

## Verify, do not recall

Anything version dependent or security sensitive gets checked against primary
sources before it is decided. Not remembered. The Starlette 1.0 trap above is
exactly why: the remembered API is the wrong one.

## Style

Comments carry what the code cannot: a workaround, a footgun, a decision that
looks wrong and is not. A comment restating the line above it gets deleted.
When a change reverses an earlier decision, write the reason into the code.

## Git

Work on `main`. Conventional commit subjects. Say what changed and why it was
not the obvious alternative; the diff already says what.
