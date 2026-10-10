"""What the engine may ask of an agent, and the types every agent package shares (#290).

Design section 3.1 promised that the second implementation would teach the real
interface, and refused to guess it from one. So this Protocol is not designed:
it is the calls `derive`, `engine` and `sweep` already made of `claude_ipc`
before a second agent existed, each moved behind a method with no change in
what it does, and nothing a caller did not already ask. Antigravity's shapes
were recorded on a real session (#294, task 265) before any of it was written,
and the one thing they changed is that `launch_argv` is told the folder: agy
refuses a trailing tag, so its argv tail is unique by folder instead.

This module names no vendor and knows no vendor's behaviour. Each agent package
(`claude_ipc`, `agy_ipc`) implements `Agent` and is the only code that knows
its agent's internals; `agents.py` holds the closed mapping from a config
file's package name to one of them. A test reads the members of `Agent` and
fails if a package stops implementing one.

The exceptions live here rather than in a package so the engine can catch them
from any agent without importing one, and translate them at its boundary: the
HTTP layer catches engine errors only.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol


class AnswerNotSafe(RuntimeError):
    """The screen does not hold a question, so no key was sent (#204).

    A sibling of `StopNotSafe` and refused for the same reason: an agent
    package would rather do nothing than act on a screen it cannot read. The
    engine translates it, so nothing above the engine catches an agent's type.
    """


class StopNotSafe(RuntimeError):
    """The graceful stop was abandoned before anything was typed.

    Raised rather than returned, because every caller's correct response is the
    same: do not continue, and tell the person. A boolean return invites a
    caller to carry on with a warning, and carrying on here means submitting
    text into somebody else's session.
    """


class Pane(Protocol):
    """The narrow surface an agent package needs from whatever hosts the session.

    Deliberately NOT `Tmux`. Naming the concrete class would put "the stop
    channel is tmux" back into functions written to remove channel
    assumptions. An agent that wanted to send a signal would need the process
    table; one that wanted an HTTP call would need neither.

    `Tmux` satisfies this structurally, without either module importing the
    other, and mypy checks it.
    """

    def send_keys(self, project: str, *keys: str) -> None: ...  # pragma: no cover

    # #242. Literal text, never key names: `send_keys("Enter")` is a keystroke,
    # `send_text("Enter")` is five characters.
    def send_text(self, project: str, text: str) -> None: ...  # pragma: no cover

    def capture_pane(  # pragma: no cover
        self, project: str, lines: int = 40, escapes: bool = False
    ) -> str: ...


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


class WrapUpWatch(Protocol):
    """Whether a wrap up prompt has finished, from readings over time (#242).

    The engine owns the clock and the ceiling; the package owns what
    "finished" looks like on its agent's screen.
    """

    def observe(self, now: float, pane: str) -> bool: ...  # pragma: no cover

    def readings(self) -> str: ...  # pragma: no cover


class Agent(Protocol):
    """One agent, as the engine layer sees it. Every member is a call the
    engine layer made of `claude_ipc` before #290; see the module docstring.
    """

    # Read only, so a package may declare each as a plain class attribute.

    @property
    def package(self) -> str:
        """The name `agents.py` maps from a config file's `package` key. Shown
        to nobody: the operator's own identifier is what the API carries."""
        ...  # pragma: no cover

    @property
    def marker(self) -> str:
        """A substring every one of this agent's command lines carries, and
        that no other process on the machine carries by accident. The pane
        direction of derivation searches a pane's tree for it."""
        ...  # pragma: no cover

    @property
    def answer_keys(self) -> Collection[str]:
        """The keys `send_answer` will type. Empty for an agent whose
        questions are not read, which makes every answer a refusal."""
        ...  # pragma: no cover

    def launch_argv(self, binary: str, project: str, folder: Path) -> list[str]:
        """The argv that starts this agent. A LIST, never a string. Its tail
        after the binary must be unique per project and per agent: the
        detached direction matches it."""
        ...  # pragma: no cover

    def trusted(self) -> frozenset[str] | None:
        """The folders this agent will start in without asking, read once per
        look, or None when that cannot be told. Never an empty set for
        unknown: that would warn on every running row."""
        ...  # pragma: no cover

    def folder_is_trusted(
        self, folder: Path, trusted: frozenset[str]
    ) -> bool: ...  # pragma: no cover

    def bridge_url(self, pid: int) -> str | None:
        """The session link without touching a pane, or None. Cheap: called
        for every live row on every listing."""
        ...  # pragma: no cover

    def session_url(
        self, pid: int, pane_text: str | None
    ) -> SessionUrl | None: ...  # pragma: no cover

    def request_stop(self, pane: Pane, project: str, settle: Callable[[float], None]) -> None:
        """Ask the agent to exit. Raises `StopNotSafe` if nothing was sent."""
        ...  # pragma: no cover

    def request_wrap_up(
        self, pane: Pane, project: str, prompt: str, settle: Callable[[float], None]
    ) -> None: ...  # pragma: no cover

    def send_answer(self, pane: Pane, project: str, key: str) -> None:
        """Type one key from `answer_keys`. Raises `AnswerNotSafe` if not."""
        ...  # pragma: no cover

    def awaits_answer(self, pane: str) -> bool | None: ...  # pragma: no cover

    def wrap_up_watch(self, sent_at: float) -> WrapUpWatch: ...  # pragma: no cover
