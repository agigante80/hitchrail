# Contributing

This project has specific expectations, and they are written down. This file
points at where, so that a change is not sent back for a reason that looks
arbitrary from outside.

**It deliberately restates almost nothing.** `docs/tech-guidelines.md` is five
hundred lines and correct; a summary here would drift from it within a phase,
and the copy that drifts is the one somebody reads.

## Before you write code

**A ticket comes first**, and it carries a milestone and at least one area
label. An empty milestone means untriaged rather than unphased, so
`is:open no:milestone` is the triage queue.

[`docs/guides/ticket-standards.md`](docs/guides/ticket-standards.md) is the
single source of truth for what a ready ticket contains. The issue templates
collect it and the `ticket-gate` check scores against it.

Read [`docs/roadmap.md`](docs/roadmap.md) for what is built and what is next,
and the design in `docs/superpowers/specs/` for the argument. **The design is
something to follow or to change deliberately, never to drift from.** If your
change departs from it, amend it in the same pull request and say why.

## The five gates

All blocking, on 3.11, 3.12 and 3.13. Run them before committing rather than
after being asked.

```sh
uv sync
uv run pytest
uv run ruff check
uv run ruff format
uv run mypy
uv run lint-imports
```

## The habits that get a change sent back

These are the ones that are not obvious from the code.

**Show the test failing.** A test that has never failed is not evidence. This
project has repeatedly caught its own vacuous tests: a teardown assertion that
ran after its socket was deleted, a redirect case the HTTP client normalised
away before the server saw it, an assertion satisfied by the name of the
temporary directory it was checking. Every one passed. When you add a test,
break the thing it covers, watch it go red, and say so in the pull request.

**Comments carry what the code cannot.** A workaround, a footgun, a decision
that looks wrong and is not. A comment restating the line above it gets
deleted. When a change reverses an earlier decision, write the reason into the
code, or the next reader re-litigates it.

**No em dashes or en dashes.** Anywhere: code, comments, documents, commit
messages, issue bodies. A hook enforces it and it is confusing to hit in a
commit message without warning. Restructure instead of substituting a hyphen: a
colon for an explanation, commas for an aside, "to" for a range, two sentences
for a contrast.

**A file past roughly 400 lines is doing more than one thing.** Split it along
the seam already there, or record the exception with its argument in
`tests/test_config.py`, where every current one is argued rather than waved
through.

**Test the refusals.** A security control with only a happy path test is
untested.

## The test tiers

Four, and the choice is not a matter of taste.

| Tier | What it is for |
|---|---|
| unit | hermetic, every external surface faked |
| `integration` | the real app through `httpx.ASGITransport`, no socket |
| `live`, `live_tmux` | a real socket, a real tmux on a private server |
| `e2e` | a real browser; needs `playwright install chromium` |

```sh
uv run pytest -m integration
uv run pytest -m "not live_tmux"   # on a machine without tmux
```

The `live_tmux` and `e2e` tiers drive a **private** tmux server through
`env -u TMUX`. A bare `tmux` honours `$TMUX`, so a suite run from inside tmux
would otherwise talk to your real one.

## Review

The loop is bounded, because "review until green" has no natural end: a
reviewer asked to find problems will find them, eventually in the fixes from
the previous round.

- **Round 1** reviews the change. Findings at high or medium are fixed;
  anything below becomes a ticket.
- **Round 2** reviews only the fix commits. The target does not grow.
- **Hard stop after four rounds**, and immediately if two consecutive rounds
  find a defect inside the previous round's fix.

**Anything unfixed when the loop ends becomes a ticket.** A ticket is a
finished outcome for a finding, not a failure to fix it.

## Commits

Work on `main`. Conventional commit subjects. Say what changed and why it was
not the obvious alternative; the diff already says what.

## Security

Do not open a public issue for a vulnerability. [`SECURITY.md`](SECURITY.md)
says what is in scope and where to send it.

## Agents

[`AGENTS.md`](AGENTS.md) holds the architecture, the non negotiables and the
footguns that cost real debugging to find. It is worth reading whether or not
you are one.
