<!-- template-version: 7 -->

# Ticket standards (canonical)

This is the **single source of truth** for what a *ready* work ticket must contain in this
repository. The five work issue templates (`feature`, `bug`, `security`, `infrastructure`,
`design`) carry the form fields that collect the content; this document holds the rules and the
reasons. The `ticket-gate` agent enforces them, and `scripts/check-template-lockstep.sh` keeps
the templates and this document on one shared `template-version`, so the standard cannot
silently drift apart from the forms that implement it.

It sits under `docs/tech-guidelines.md`, not beside it. The guidelines are binding for code; this
says what a ticket must contain before that code is written. Where the two appear to disagree,
the guidelines win and this document is wrong.

## Why single source

The requirement text used to be restated in each template, in `CLAUDE.md`, and in the gate. Six
copies drift: prose says one thing while a template says another, and nobody notices until a
ticket is gated against a stale rule. Keeping the rules here, referenced rather than restated
elsewhere, plus the lockstep guard, makes "the standard is the same everywhere" mechanically true
instead of a matter of discipline.

## Required sections

A ready work ticket must satisfy every rule below whose scope it actually touches. Applicability
is decided by the gate from the ticket type and the modules it affects. A rule the ticket does
not touch is marked N/A with a one-line justification, never failed. A rule that *does* apply and
is absent fails the gate.

### 1. GWT scenarios (Given / When / Then)

At least one positive and one negative scenario per independent condition, written against
specific module, route and state names where the ticket makes them evident. Vague restatements of
the description do not count.

**A refusal is a condition.** If the change adds a guard, the negative scenario is the guard
firing, and it names the error `code` returned.

### 2. Unit test specs

Concrete cases: a specific test file path, a concrete input value, and the expected output or
error code. "Add unit tests" is not a spec.

Unit tests here are **hermetic**. No test touches a real tmux server, a real Claude process, the
network, or the filesystem outside a temporary root. tmux, the process table, memory readings,
the Claude state directory and the clock are faked behind injectable seams, so a ticket that
introduces a new external surface must say how that surface is injected.

**When a ticket adds or modifies an HTTP route**, complete coverage of that route is required:
the success path, every documented refusal with the `code` it returns, and the error body shape.

### 3. Integration test specs

The API driven through `httpx.ASGITransport` against a real Starlette app with a faked engine. No
socket is opened and no server is started. This is the tier that proves routing, middleware,
status codes, error bodies and the SSE contract.

Required for anything that touches `server.py`. Engine-only and discovery-only tickets mark it
N/A with that reason.

### 4. E2E test specs

The real application, launched the way a user launches it, against a temporary root and a fake
`claude` shim, driven through a browser with Playwright. Give a specific test file, the setup,
the action and the assertion, for the happy and the unhappy path.

Required for any interface-visible behaviour, and for anything a unit test **structurally cannot
see**: the SSE stream reconnecting, the stop escalation arriving in the state the user is really
in, the layout holding at a phone viewport, a forged `Host` refused on a live socket.

API-only and engine-only tickets mark this N/A with justification rather than inventing a flow.

**The E2E tier drives a private tmux server on its own socket**, addressed as `tmux -S "$SOCK"`
and invoked through `env -u TMUX`. A ticket that adds E2E coverage inherits that rule; a ticket
that proposes E2E coverage without it is not ready.

### 5. Blast radius

There is no GDPR section in this repository's templates, and its absence is deliberate.
Hitchrail stores no personal data and has no database: state is derived on demand from the
operating system, and the only thing it holds in memory is an in-flight stop marker. A GDPR
section here would be N/A on every ticket forever, which trains authors to skip sections.

What replaces it is the thing this project actually risks. Hitchrail spawns
`claude --dangerously-skip-permissions`, so anyone who can drive its API can run arbitrary code
as the user who started it. Every ticket states, in plain terms:

- whether it touches one of the seven controls in `docs/tech-guidelines.md` section 5, and how
- the exact argv of any new subprocess call (argument list, never a shell)
- the target spec of any new tmux invocation, and how it is scoped to the configured prefix
- how any new path is resolved and confirmed to be a direct child of SOME configured root,
  and how the identifier names which one (#119 made a project `<root-label>~<folder>`)
- whether it adds a runtime dependency, against a budget of three
- what the code does when a session's state cannot be determined

That last one is the one people skip. A guard that fails open, or an error rendered as a success,
is worse than no guard.

### 6. Security checklist

Which control applies, what the allowlist pattern is, which stable error `code` the refusal
returns, and whether the route is mutating (Origin checked) or a `GET` (exempt, because
`EventSource` cannot set headers).

Order matters and the ticket should reflect it: the host check runs before the token check, so a
rebound request never reaches anything that could reveal whether a token is even correct.

A `security` label dispatches the security lens regardless of what the content selection chose.

### 7. Required reviews

The reviews the ticket must pass before it is done, checked off explicitly. This is the author
acknowledging the gate, not a substitute for it.

### 8. Documentation impact

Which documents this change makes wrong, and the edit that fixes each. Named files, not
"update the docs".

This section exists because the project shipped two phases without the README once
mentioning tmux, while every session Hitchrail starts lives in one. Nothing was
negligent: each ticket did its own job, and no ticket owned the sentence. A section
nobody is required to fill in is a section that gets filled in by nobody.

**Documentation is part of the change, not a follow up ticket.** The same rule the testing
guidelines apply to tests applies here: a ticket that lands code and leaves a document
contradicting it has not finished, it has created a second ticket nobody wrote down.

The candidates in this repository, and what each one owns:

| Document | Owns |
|---|---|
| `README.md` | anything a user does before or while running Hitchrail: prerequisites, install, flags, stated limitations |
| `docs/superpowers/specs/...-design.md` | the argument. Amend it when the implementation departs from it, rather than letting the code drift |
| `docs/roadmap.md` | phase scope, exit criteria, and the retrospective once a phase closes |
| `docs/tech-guidelines.md` | a rule that generalises beyond this ticket |
| `.claude/rules/*.md` | the same rule, where it loads automatically for the files it governs |
| `AGENTS.md` | project shape, commands, architecture, and the non negotiables. Tracked, and the canonical copy since #60; `.claude/CLAUDE.md` is a pointer |
| `docs/versioning.md` | anything that changes the operator contract |

Three cases where this section may **not** be N/A, because these are the ones that were
missed:

1. **A new runtime prerequisite**, or a new assumption about the machine. It goes in the
   README, and it needs a check in the program, because a README is documentation rather
   than a mitigation.
2. **A deliberate departure from the design.** Amend the design and say why. The design is
   the argument; code that silently disagrees with it turns the argument into fiction.
3. **A mitigation that is not a fix.** Say which one it is and name the ticket that ends
   it. A partial fix recorded as complete is how a known exposure stops being tracked.

N/A is legitimate and common: a pure refactor with no behaviour change, or a bug fix that
restores documented behaviour, changes no document. Say that, with the reason.

## The N/A rule (load-bearing)

A coverage or E2E requirement that a docs-only, infrastructure-only or engine-only ticket cannot
satisfy makes that ticket **un-passable**, which trains people to box-tick and rots the whole
gate. Every rule here is scoped: it applies only to tickets whose type and affected modules bring
it into play, and the gate derives that scope rather than asking the author to self-declare it.

When you add a new rule with a coverage-style requirement, give it an explicit type-and-area
scope here, or it will backfire.

## Milestones and labels

Every ticket carries **one milestone and at least one area label**, and each of
those answers a different question. The milestone says *when*; the labels say
*what* and *where*.

### The milestone is the phase, and empty means untriaged

| Milestone | Meaning |
|---|---|
| `Phase 1` through `Phase 7` | Triaged, and it belongs to that phase of `docs/roadmap.md` |
| `Backlog` | Triaged, real work, no phase. Do-anytime maintenance, and tickets whose right answer may turn out to be closing them |
| **empty** | **Nobody has triaged this yet** |

The empty state is load bearing, so do not use it as a resting place. A ticket
with no phase is not "unphased", it is **unread**, and `is:open no:milestone`
is therefore the triage queue rather than a list of things somebody decided to
leave alone. That distinction is free, and it disappears the moment an empty
milestone is allowed to mean two things.

`Backlog` is the honest answer for work with no phase. Its progress bar is
meant to stay partial; it is a holding pen, not a phase.

**One milestone, not several.** A ticket that wants two phases is a ticket that
wants splitting, and this is the pressure that reveals it. Issue #9 spanned
Phase 2 and Phase 3 and read as one coherent ticket until a milestone forced
the question; it became #9 and #11, and the two halves land months apart.

### Labels, in three groups

| Group | Labels | Rule |
|---|---|---|
| **Area** | `config`, `discovery`, `tmux`, `procs`, `claude-ipc`, `ram`, `events`, `engine`, `security`, `server`, `web`, `cli`, `packaging`, `infrastructure`, `documentation` | **At least one, and the gate blocks without it.** This is what routes the specialist agents |
| **Type** | `bug`, `enhancement`, `security`, `design`, `testing`, `documentation` | At least one. A missing type warns rather than blocks |
| **Process** | `gated`, `blocked`, `needs-human`, `from-review` | Optional, applied as the ticket moves |

`gated` is applied by whoever runs `/gate-ticket` on a PASS, and it is the
answer to "what can I start". Without it the gate's verdict lives only in a
comment, which is not a thing you can query.

**A PASS is a verdict, not a score.** The gate used to run five agents that each
scored 1 to 10 and required 10 from all of them. That model was retired: it ran
five agents to reach a number, and a committee converging on 10/10 certifies
less than one grounded critique with its sources. The gate now runs
deterministic mechanical checks, then ONE critic, plus a specialist lens where
the labels call for it, and returns PASS, NEEDS-WORK or BLOCKED with a concrete
change list.

What did not change is what a ready ticket must CONTAIN, which is this document.
The gate's shape is how the rules are checked; the rules are here.

`from-review` marks a ticket that came out of code review rather than out of
using the tool. It is worth being able to see that ratio: if nearly everything
is `from-review`, review is doing the work usage should be doing.

`needs-human` marks a decision only a person can make. `blocked` is the
general case, waiting on another ticket.

### Priority is not a label

The five issue templates already carry a required Priority dropdown, and
`ticket-gate` reads it. A `P0` label would be a second copy of the same fact,
and the first section of this document explains at length what happens to the
second copy. Filter on the body, or on the milestone, which is usually the
question you actually meant.

### Where this is enforced

- **`ticket-gate` Step 0b** refuses to review a ticket with no area label or no
  milestone, returning BLOCKED. Nothing gets implemented without both.
- **`scripts/check-ticket-hygiene.sh`** sweeps every open issue and reports
  what is missing, because the gate only sees tickets somebody chose to run it
  on. Run it before planning a phase.
- Issue forms **cannot** set a milestone. GitHub's form schema supports
  `labels`, `assignees`, `projects`, `title` and `type`, and nothing else, so
  the templates set labels and the milestone is applied by hand or by the
  sweep. That is checked, not remembered: see the syntax reference for issue
  forms.

## Area labels

The gate blocks a ticket with no area label, because that is what routes the specialist agents.
The areas match the module layout in the design, section 4:

| Label | Covers |
|---|---|
| `config` | runtime configuration and its refusals |
| `discovery` | root scanning, folder creation, path safety |
| `tmux` | target addressing and the footguns |
| `procs` | the process table snapshot |
| `claude-ipc` | the Claude Code quarantine |
| `ram` | memory readings and the guard |
| `events` | the in process fan out |
| `engine` | state derivation, start, stop, log tail |
| `security` | host allowlist, origin check, token |
| `server` | Starlette routes, middleware, SSE |
| `web` | the browser interface |
| `cli` | arguments, config, uvicorn launch |
| `packaging` | pyproject, the wheel, PyPI |
| `infrastructure` | CI, tooling, gates |
| `documentation` | docs and specs |

One label per module the implementation plan creates. Routing a ticket to the
right specialist is the whole reason the gate blocks without an area, and a
vocabulary that stops short of the modules people actually work in forces them
to pick the nearest wrong answer.

Type labels are `bug`, `enhancement`, `security`, `design`, `testing`, `documentation`. A missing
type label warns; a missing area label blocks.

## What this document does not do

It does not restate `docs/tech-guidelines.md`, and it does not restate the design. A ticket that
contradicts the design is not fixed by writing more ticket: either it follows the design, or it
changes the design deliberately with a new dated document in `docs/superpowers/specs/` that says
what it supersedes. Drift is the failure this whole apparatus exists to prevent.
