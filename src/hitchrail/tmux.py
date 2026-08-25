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

import subprocess
from collections.abc import Callable

# What a subprocess call looks like from here. Injected so the whole engine can
# be tested without a machine, which is the single seam the architecture rests
# on. `procs` consumes this alias too.
Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]

# tmux reads both of these as target separators, so neither may appear in a
# session name. `-` is the escape character, which is why it is escaped too.
_SEPARATORS = (".", ":")

# Marks a name that went through the encoding below. A name that would
# otherwise start with it is encoded as well, which is what keeps the encoded
# and unencoded forms disjoint and therefore the whole mapping injective.
_ENCODED_PREFIX = "e-"


class NotOurSession(ValueError):
    """Refusing to touch a session that does not carry the configured prefix."""


def sanitize(name: str) -> str:
    """Make a project name addressable as a tmux session, ONE TO ONE.

    tmux reads '.' and ':' as window and pane separators in a target spec.
    Verified on 3.4: a session created as `hr-dotted.site` is stored as
    `hr-dotted_site`, so it exists under a name nobody looked for and
    `has-session -t =hr-dotted.site` fails while the agent is running, which
    presents as the session having vanished. Emitting neither character
    sidesteps the rewrite rather than trying to predict it.

    Injectivity is the hard requirement here, not a nicety. If two project
    names collide onto one session name, one project reads as running because
    the other is, and stopping one kills the other's agent. That is the "two
    agents in one folder" outcome #11 fixed from the discovery side, reached
    from this one.

    **A digest suffix does not deliver it, which is why this is an escape
    encoding.** An earlier version returned `a-b-<6 hex of blake2b>` for `a.b`
    and returned already safe names unchanged. A project named literally
    `a-b-28b8f5` is already safe, so it came back unchanged and collided with
    `a.b`, and the colliding name is trivially computable by anyone who can
    create a folder. Widening the digest only raises the price: 6 hex is 24
    bits, so distinct names also birthday collide by accident somewhere around
    four thousand projects. Injective by construction beats injective by hash.

    The encoding is the usual escape and escape-the-escape:

        -  ->  --      .  ->  -d      :  ->  -c

    and the whole thing gets an `e-` prefix so encoded and unencoded names
    occupy disjoint spaces. A name that already starts with `e-` is encoded for
    the same reason. Names with neither separator are returned untouched, so
    the common case still reads plainly in `tmux ls`, and readability is the
    right thing to trade away here anyway: the project already keeps the
    display name apart from the tmux name.
    """
    if not _needs_encoding(name):
        return name
    body = name.replace("-", "--").replace(".", "-d").replace(":", "-c")
    return f"{_ENCODED_PREFIX}{body}"


def _needs_encoding(name: str) -> bool:
    """A name is encoded if it holds a separator, or could be mistaken for one
    that was. The second half is what keeps the two spaces disjoint."""
    return any(sep in name for sep in _SEPARATORS) or name.startswith(_ENCODED_PREFIX)


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
