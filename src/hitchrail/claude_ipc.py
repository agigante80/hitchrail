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

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

# How the agent is found in the process table. State derivation matches this as
# a substring of a command line, so it has to be something no other process on
# the machine carries by accident.
REMOTE_CONTROL_MARKER = "--remote-control"

# Where a session link points. The bridge id is appended verbatim.
URL_BASE = "https://claude.ai/code/"

# What a bridge id is allowed to look like. An ALLOWLIST of shape, not a
# denylist of bad strings: the value comes from a file another process wrote
# and ends up in a link the interface renders, so anything not obviously a
# single path segment is refused rather than sanitised into one.
_BRIDGE_ID = re.compile(r"\A[A-Za-z0-9._~-]{1,128}\Z")

logger = logging.getLogger(__name__)

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


@dataclass(frozen=True)
class SessionUrl:
    """A session link and WHERE IT CAME FROM.

    The source is carried rather than a confidence score. We know exactly why a
    scraped URL is uncertain, so naming the mechanism lets the interface say
    "found in the terminal output, may be from an earlier session" instead of
    "low confidence", which tells the user nothing they can act on.
    """

    url: str
    source: Literal["bridge", "scraped"]


def _valid_bridge_id(value: object) -> str | None:
    """A bridge id, or None. Every refusal here is deliberate.

    The file is written by another process and its contents are guaranteed to
    be nothing in particular, while the value ends up in a link somebody taps.
    A separator would let it climb out of the path segment it belongs in; a
    scheme would point it at another host entirely, which is an open redirect
    rendered by our own interface.

    The pattern refuses both without enumerating them, along with control
    characters, empty strings and anything absurdly long.
    """
    # No bool guard here on purpose: bool subclasses int, not str, so `True`
    # is already refused by the str check. Adding one reads as defensive and
    # is unreachable, which mypy says out loud.
    if not isinstance(value, str):
        return None
    return value if _BRIDGE_ID.match(value) else None


def bridge_url(pid: int, sessions_dir: Path) -> str | None:
    """The session link from `<sessions_dir>/<pid>.json`, or None.

    `bridgeSessionId` is an undocumented internal, it is not written for every
    session, and it may be caught mid write. Every one of those is None rather
    than an exception, because the interface shows `pending` for None and a
    missing link is honest while a wrong one is not.

    `pid` is an `int`, so the filename cannot traverse. Keep it that way:
    accepting a `str` for convenience reintroduces that through the filename.
    """
    path = sessions_dir / f"{pid}.json"
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    bridge_id = _valid_bridge_id(payload.get("bridgeSessionId"))
    if bridge_id is None:
        return None
    # Verbatim, including the session_ prefix. The value IS the path segment.
    return f"{URL_BASE}{bridge_id}"


def _scrape(pane_text: str) -> str | None:
    """A claude.ai/code URL from terminal output, validated the same way.

    Pane text is attacker influenceable: anybody who can write to the pane can
    put a URL in the scrollback, so the segment gets the same allowlist the
    JSON value does.
    """
    match = re.search(rf"{re.escape(URL_BASE)}(\S+)", pane_text)
    if match is None:
        return None
    bridge_id = _valid_bridge_id(match.group(1))
    return None if bridge_id is None else f"{URL_BASE}{bridge_id}"


def session_url(
    pid: int, sessions_dir: Path, pane_text: str | None = None
) -> SessionUrl | None:
    """The best link available, saying which it is, or None for `pending`.

    **The bridge value always wins**, following the ordinary treatment of an
    observed fact against a self reported one: the authoritative source
    decides, and the disagreement is itself a signal.

    The scrape exists because the JSON is not written for every session, and it
    cannot be trusted because three things produce a match and only one is
    right. The nastiest is scrollback from a PREVIOUS session in the same pane:
    a perfectly well formed URL pointing at a session that ended hours ago.
    Nothing about the string looks wrong, so no amount of parsing separates it
    from a good one and the only honest response is to say where it came from.
    """
    from_bridge = bridge_url(pid, sessions_dir)
    from_pane = _scrape(pane_text) if pane_text else None

    if from_bridge is not None:
        if from_pane is not None and from_pane != from_bridge:
            # Good evidence the pane is showing stale scrollback, and exactly
            # the diagnostic somebody wants when a link misbehaves.
            logger.debug(
                "session %s: pane URL %s differs from the bridge URL %s, "
                "the pane is probably showing an earlier session",
                pid,
                from_pane,
                from_bridge,
            )
        return SessionUrl(from_bridge, "bridge")

    return SessionUrl(from_pane, "scraped") if from_pane is not None else None
