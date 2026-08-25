"""A thin tmux adapter, carrying the target addressing footguns.

Everything here exists because a tmux target spec does not mean what it looks
like. Each behaviour below was verified against a real tmux 3.4 on a private
socket rather than recalled, and #27 keeps that honest with a live tier: the
tests in this layer prove the adapter builds the target it believes in, which
is a different and weaker claim than the target doing what we believe.

This module is in the engine layer and imports nothing from the web layer;
`lint-imports` enforces it.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable

# What a subprocess call looks like from here. Injected so the whole engine can
# be tested without a machine, which is the single seam the architecture rests
# on. `procs` consumes this alias too.
Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]

# tmux reads both as target separators. Mapped to '-' rather than stripped so
# the readable part of the name survives.
_UNSAFE = str.maketrans({".": "-", ":": "-"})

# Six hex characters. Long enough that a collision needs deliberate effort,
# short enough that the session name stays something a person can read in
# `tmux ls`.
_DIGEST_BYTES = 3


class NotOurSession(ValueError):
    """Refusing to touch a session that does not carry the configured prefix."""


def sanitize(name: str) -> str:
    """Make a project name addressable as a tmux session, one to one.

    tmux reads '.' and ':' as window and pane separators in a target spec.
    Verified on 3.4: a session created as `hr-dotted.site` is stored as
    `hr-dotted_site`, so it exists under a name nobody looked for and
    `has-session -t =hr-dotted.site` fails while the agent is running, which
    presents as the session having vanished. Emitting neither character
    sidesteps the rewrite rather than trying to predict it.

    The digest is the part that is easy to leave out and expensive to leave
    out. A plain replacement maps both `a.b` and `a-b` onto `a-b`, so two
    folders share one tmux session: one reads as running because the other is,
    and stopping one kills the other's agent. That is the same "two agents in
    one folder" outcome #11 fixed from the discovery side, reached from here.

    It is appended only when the name actually changed, so ordinary names stay
    readable, and it is deterministic, because a session has to survive a
    restart of Hitchrail.
    """
    safe = name.translate(_UNSAFE)
    if safe == name:
        return safe
    digest = hashlib.blake2b(name.encode(), digest_size=_DIGEST_BYTES).hexdigest()
    return f"{safe}-{digest}"


class Tmux:
    """Target addressing for one prefix. The operations arrive with #23.

    The display name and the tmux name are deliberately different things. A
    caller passes the project name it got from `discovery`; everything sent to
    tmux goes through `sanitize` first, so nothing outside this class needs to
    know that the two can differ.
    """

    def __init__(
        self,
        prefix: str,
        socket: str | None = None,
        run: Runner | None = None,
    ) -> None:
        self.prefix = prefix
        self.socket = socket
        self._run = run

    def session_name(self, project: str) -> str:
        """The name a session is CREATED with. Not a target: see below."""
        return f"{self.prefix}{sanitize(project)}"

    def session_target(self, project: str) -> str:
        """A session target, anchored.

        Without the '=', `has-session -t hr-vessel` prefix matches and resolves
        `hr-vessel-social`. Verified on tmux 3.4. A stopped project then reports
        a sibling's session as its own, which the interface renders as running.
        """
        return f"={self.session_name(project)}"

    def pane_target(self, project: str) -> str:
        """A pane target, anchored AND colon terminated. Both are required.

        `list-panes` takes a pane target, and on a bare `=hr-vessel` it ignores
        the anchor and falls back to prefix matching: verified on tmux 3.4, a
        session that does not exist returned its sibling's pane pid. The
        trailing ':' qualifies the string as a session target, after which the
        anchor is honoured and a missing session is correctly refused.

        The colon looks like a typo and is load bearing. There is a named
        regression test for it.
        """
        return f"={self.session_name(project)}:"
