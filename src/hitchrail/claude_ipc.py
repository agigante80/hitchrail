"""Everything that knows Claude Code internals, and the only place that may.

Every constant and every parsing rule below depends on UNDOCUMENTED Claude Code
behaviour that will change without notice. That is the whole reason this module
exists: when it breaks, exactly one file changes and the interface degrades to
`pending` rather than reporting something false.

Written against Claude Code as of 2026-08. If a session link stops resolving or
an agent stops being found in the process table, look here first and expect the
cause to be upstream rather than a bug in Hitchrail.

This module is also the vendor seam. Multi agent is an explicit v1 non goal
(design section 3.1); what is kept open is the seam, not an abstraction.
Nothing outside this module may name a Claude Code behaviour, file or key
sequence, and "name" includes iterating one: `lint-imports` cannot see a string
literal, so the quarantine has grep tests instead.

This module is in the engine layer and imports nothing from the web layer.
"""

from __future__ import annotations

from typing import Protocol

# How the agent is found in the process table. State derivation matches this as
# a substring of a command line, so it has to be something no other process on
# the machine carries by accident.
REMOTE_CONTROL_MARKER = "--remote-control"

# What to type at a running agent to ask it to finish, as a sequence of key
# GROUPS. Each group is one send_keys call, because tmux distinguishes a key
# from literal text by argument position: two interrupts, then the exit
# command, then the newline that submits it.
GRACEFUL_STOP_KEYS: tuple[tuple[str, ...], ...] = (
    ("C-c",),
    ("C-c",),
    ("/exit", "Enter"),
)


class Pane(Protocol):
    """The narrow surface `request_stop` needs from whatever hosts the session.

    Declared HERE, next to its consumer, and deliberately NOT `Tmux`. Naming
    the concrete class would contradict the phase's rule that no adapter
    imports another, contradict this module's "consumes nothing", and defeat
    the point: it puts "the stop channel is tmux" back into the function
    written to remove channel assumptions. An adapter that wanted to send a
    signal would need the process table; one that wanted an HTTP call would
    need neither.

    `Tmux` satisfies this structurally, without either module importing the
    other, and mypy checks it.
    """

    def send_keys(self, project: str, *keys: str) -> None: ...  # pragma: no cover


def launch_argv(binary: str, project: str) -> list[str]:
    """The argv that starts an agent. A LIST, never a string.

    The no shell rule has to survive the handoff to whatever runs this, so the
    type is the guarantee rather than a convention.

    `--dangerously-skip-permissions` is what makes unattended operation
    possible and is also the whole of this project's threat model. It belongs
    in this module and nowhere else.
    """
    return [binary, "--dangerously-skip-permissions", REMOTE_CONTROL_MARKER, project]


def request_stop(pane: Pane, project: str) -> None:
    """Ask the agent to finish, by whatever means this agent understands.

    The engine calls this and learns nothing more. Iterating GRACEFUL_STOP_KEYS
    at the call site instead would teach the engine three Claude Code facts:
    that stopping is keystrokes, that it is a sequence of them, and that they
    travel through a pane. None of those is true of an agent that wants a
    signal, a subcommand or an HTTP call.

    GRACEFUL_STOP_KEYS stays public because the test asserting the exact
    sequence needs it. The rule is that nothing outside this module ITERATES
    it, and there is a grep test for that, because no import contract can see
    a `for` loop.
    """
    for keys in GRACEFUL_STOP_KEYS:
        pane.send_keys(project, *keys)
